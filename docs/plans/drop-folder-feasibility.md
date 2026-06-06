# Drop-Folder Feasibility — Session Notes

> Status: **exploration / not implemented.** This captures the feasibility
> discussion so it can be reviewed before any code changes. Nothing in the repo
> has been changed.

## The idea

Today the Kodi file-manager view under `repo/` shows five folders — `iptv/`,
`media/`, `repositories/`, `rss/`, `scripts/`. It works fine for Kodi, but as a
**human mental model** it isn't true to life: it carries wiring noise and forces
the author to know "which folder does this thing go in, and what do I run after."

The goal: a **clean, content-representative drop folder**. An end user drops a
file or folder and doesn't worry about wiring logistics. The script + CI do the
heavy lifting — classifying the dropped content and wiring it so Kodi serves it
correctly.

## What `repo/` actually is today

`repo/` is **two things wearing one coat**: the Kodi-servable layout *and* the
place a human authors content. On disk it mixes five different categories:

| What's in `repo/`                                                                 | Category                  | Who edits it       |
| --------------------------------------------------------------------------------- | ------------------------- | ------------------ |
| `addons.xml`, `.sha256`, `.md5`                                                   | generated metadata        | the script         |
| `repository.tony7bones/`, `script.module.tony7bones/`, `script.tony7bones.*/`     | first-party add-on source | you, as code       |
| `hosted/`                                                                          | proxy mirror trees        | by hand, carefully |
| `repositories/`, `scripts/`, `media/`, `iptv/`, `rss/`                            | **drop content**          | drop-and-forget    |
| `index.html` (hand-crafted)                                                       | the Kodi browse view      | you, manually      |

**Key seam:** the file-manager view (the 5 folders) is *not* a reflection of
disk — it's whatever the **hand-crafted `repo/index.html` links to**. The add-on
source dirs, `hosted/`, and metadata are all served by Pages but invisible in the
browse view because nothing links them. The "view" is already decoupled from
storage — which is exactly the seam the drop-folder idea needs.

> Note: `repo/index.html` is already drifted — it points at
> `repository.tony7bones-1.0.5.zip`, which no longer exists. A generated index
> would remove this whole class of manual error.

## Verdict: feasible, and the repo is well-positioned for it

Every content type **carries its own identity inside the bytes** — no manifest,
no naming convention, no human wiring required:

| You drop…                                  | How the script knows what it is (content sniff)                                    | Where it wires to                                  |
| ------------------------------------------ | --------------------------------------------------------------------------------- | -------------------------------------------------- |
| a folder with `addon.xml`                  | `<extension point="…">` → `xbmc.addon.repository` / `xbmc.python.script` / `pluginsource` | add-on → `addons.xml` + zip                 |
| a `.zip`                                   | **peek inside**, read its `addon.xml` extension point                             | repository zip → `repositories/`; script zip → `scripts/` |
| `.jpg/.png/.svg…`                          | file extension                                                                    | `media/`                                           |
| `RssFeeds.xml`                             | root element `<rss>`                                                              | `rss/`                                             |
| `customTVGroups-*.xml`, `instance-settings*.xml` | filename pattern + root element                                             | `iptv/`                                            |
| anything else                              | fallback                                                                          | a generic browsable asset folder                   |

The one distinction the current generator makes by **folder location** (is this
zip a "repository" or a "script"?) is exactly the distinction a zip's inner
`addon.xml` already answers. So **routing-by-content** replaces
**routing-by-where-you-happened-to-put-it**. That's the whole trick.

## Two design models

### Model A — `drop/` as a staging inbox (router)

You drop into `drop/`. `generate_repo.py` sniffs each item, **moves** it to its
canonical `repo/<area>/` home, regenerates indexes, and rewrites `repo/index.html`
from the actual areas present. `drop/` ends empty.

- **Pros:** smallest change; existing `repo/` layout and the proxy untouched;
  fully testable with the existing determinism harness.
- **Cons:** the "drop" is transient (git shows a move), so it's a convenience
  inbox, not a persistent human view.

### Model B — `drop/` as the source of truth (compiler)

`drop/` *is* where content lives, organized for humans (e.g.
`drop/third-party-repos/`, `drop/scripts/`, `drop/branding/`, `drop/iptv/`). The
Kodi `repo/` content areas become **pure build output** — generated, never
hand-touched. The generator compiles `drop/ → repo/`.

- **Pros:** truest realization of "clean drop folder that represents its
  content"; kills drift (e.g. the stale `script.tony7bones.bootstrap-1.0.5.zip`
  duplicate currently rotting in `repo/scripts/`).
- **Cons:** bigger change to layout and CI.

In **both** models the first-party add-on source dirs stay put — they're *code*,
not drops, so they live outside `drop/` either way. And in both, `repo/index.html`
becomes **generated from what's actually there**.

## How CI fits — and the one hard constraint

CI here **never commits**; it runs `generate_repo.py` and fails if the tree isn't
clean (`git status --porcelain`). That's the backbone for "CI does the
deployment," but it imposes a non-negotiable rule on the drop pipeline:

> The transform must be **deterministic and idempotent** — running it twice
> produces zero diff.

This already governs the zips (fixed 1980 timestamps, sorted members,
`__pycache__` excluded). A drop router must obey the same discipline: a stable
destination for every input, no timestamp/order churn, and "already-routed" must
be a clean no-op. This is where the real engineering goes — a naive `shutil.move`
would make CI flag stale files on every push.

**Resulting flow:** drop file → run `generate_repo.py` locally → commit → push →
CI re-runs the identical transform and verifies it matches → Pages serves. No new
deployment machinery needed; it rides the rails that already exist.

## Honest limits (what won't fully automate)

- **`hosted/` and the proxy's `repository.json`** are genuinely more than a drop:
  adding a served third-party repo needs an `asset_prefix` + branch entry in
  `repository.json`. A drop could *stage* the `addon.xml`/zip, but the manifest
  edit is semantic. Keep it out of scope, or make it a guided "drop + one-line
  manifest" step — not magic.
- **`repository.tony7bones` releases** ride `deploy.py` (version-sync + tag +
  Pages build) — untouched by any of this.
- **IPTV/RSS detection** is the most heuristic (filename + root-element); a truly
  novel config file may need a fallback bucket. Better to route ambiguous items
  to a visible `unsorted/` than to guess wrong silently.
- A `.zip` with **no inner `addon.xml`** (a plain asset archive) has no add-on
  identity — it needs a default rule.

## Recommendation

**Model A is the low-risk 80%** and should ship first: a `drop/` inbox + a
content-sniffing router inside `generate_repo.py`, with a generated
`repo/index.html`. It delivers "drop a file, don't think about wiring"
immediately, fixes the broken hand-maintained index, and is fully testable. Model
B is the same router pointed the other way — easy to evolve into once the sniffing
is proven.

## Open decisions (to settle before building)

1. **Model A vs B vs design-doc-only** — staging inbox, source-of-truth, or just
   review the write-up first.
2. **Drop UX** — a single flat `drop/` folder (script fans items out by type), or
   human-named subfolders (`drop/third-party-repos/`, `drop/scripts/`,
   `drop/branding/`, `drop/iptv/`) where the folder is a hint and content sniffing
   confirms, or dropping straight into the live Kodi/Pages browse area (more
   ambitious, needs further assessment).
3. **Ambiguity handling** — confirm the "route to visible `unsorted/` rather than
   guess" policy.
