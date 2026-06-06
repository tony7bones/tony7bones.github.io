# Model B — One Source of Truth (`dropbox/` → `repo/`)

> Status: **APPROVED — ready to execute.** Decided spec, hardened by a three-lens
> review (Kodi / architecture / QA) and the owner's decisions. No repo changes
> yet — this is the agreed plan; execution begins on the owner's "go."
>
> **Decisions locked:** Full Model B · source of truth = `dropbox/` at repo root ·
> compiled output = `repo/` (committed, generated) · build from `dropbox/`.
>
> **When ready, pull the trigger here →** start at **Step 0** in
> [Sequencing](#sequencing) and proceed in order; each step is independently
> CI-clean and pushed only after the local gates pass. The **byte-identity
> migration gate** (P0 #1) is the hard go/no-go: post-migration `repo/` must be
> byte-identical to today's `repo/`, or live Kodi installs break.

## The model

Two folders, one rule each:

|                                                               | **`dropbox/`** — source of truth                                   | **`repo/`** — compiled output                            |
| ------------------------------------------------------------- | ------------------------------------------------------------------ | -------------------------------------------------------- |
| Lives at                                                      | repo root                                                          | repo root (as today)                                     |
| Contains                                                      | **only** human-authored content, organized however the human likes | a full copy of `dropbox/` **+** every generated artifact |
| Generated junk (`index.html`, `addons.xml`, `.sha256`, zips)? | **NEVER**                                                          | yes — all of it                                          |
| Who edits it                                                  | the human, freely                                                  | the build, only — never hand-edited                      |
| Who looks at it                                               | the human                                                          | Kodi / Pages / CI                                        |
| Committed to git?                                             | yes                                                                | yes (see below — it must be)                             |

The human works **only** in `dropbox/`. Everything they see there is meaningful —
no index pages, no checksums, no machine clutter, no "why is this here?" The
build compiles `dropbox/ → repo/`, injecting all the junk into the **copy**. The
pristine source is never written to by the system.

This is the real fix for the old "`repo/` is two things wearing one coat"
problem: we **split the coat** — pristine source in, fully-generated output out.

## Why `repo/` must stay committed (not a gitignored build artifact)

The virtual proxy fetches add-on metadata and zips **live at runtime** from
`raw.githubusercontent.com/<user>/<repo>/main/repo/...` — both the first-party
add-on zips and the `hosted/<id>/` third-party mirror trees (driven by
`repository.json`, all entries `branch: main`, `asset_prefix` ending in
`/repo/...`). Those byte paths must physically exist in the committed `main`
tree or **every installed Kodi box breaks**.

Therefore `repo/` is **committed generated output**, not a Pages-built artifact.
Consequence: a `dropbox/` change produces a "doubled diff" (the source change +
the regenerated `repo/`). That's inherent and acceptable — reviewers read the
`dropbox/` half; the `repo/` half is derived and verified by CI. GitHub Pages
keeps serving `main` directly (no new deploy machinery), and the constant install
URL is preserved.

## What moves into `dropbox/` (Full Model B)

Everything human-authored, **source form only** (no generated zips/indexes):

- **First-party add-on source** — `dropbox/repository.tony7bones/`,
  `script.module.tony7bones/`, `script.tony7bones.bootstrap/`,
  `script.tony7bones.video/`, `script.tony7bones.modv2plus/` (their `addon.xml`,
  `default.py`, `lib/`, `resources/` — including the proxy's authored
  `resources/repository.json` — but **not** the built `*.zip` or per-addon
  `index.html`).
- **`hosted/` mirror trees** — the hand-curated third-party `addon.xml` + zips.
- **Third-party installer zips** — the `repositories/` and `scripts/` content.
- **Assets** — `media/`, `iptv/`, `rss/` content (the human's structure).

The human may organize freely. The build interprets a **few reserved
conventions** (intuitive, not "wiring noise"):

- a folder containing an `addon.xml` is an **add-on** → built into a zip +
  listed in `addons.xml`;
- `hosted/` is a **mirror tree** → copied through, not zipped/indexed as add-ons
  (today's `_SPECIAL_DIRS` behavior);
- everything else is **browsable content** → copied through + given Kodi indexes.

(No extension-point sniffing / type-routing — the human owns structure; the build
only needs "is this an add-on dir or not," which the generator already detects.)

## What `repo/` becomes (100% generated)

A deterministic compile of `dropbox/`:

1. **Mirror** `dropbox/ → repo/` (content copied verbatim).
2. **Build add-on zips** for every dir with an `addon.xml`
   (existing reproducible-zip logic: 1980 timestamps, sorted members,
   `__pycache__` excluded).
3. **Generate** `addons.xml` + `.sha256` + `.md5`.
4. **Generate** a Kodi-browsable `index.html` for every folder
   (href == text, trailing slash on dirs, relative hrefs, **no dates**),
   including a generated `repo/index.html` browse landing (no install-URL line).
5. **Preserve** `hosted/` as a pass-through mirror.

`repo/` is never hand-edited again. The old "`repo/index.html` is hand-crafted,
never overwrite" guard is removed — it's now generated like everything else.

## The build pipeline

The build is essentially **today's `generate_repo.py` logic with an
input/output split**: read from `dropbox/`, write to `repo/`, instead of
operating in place. That keeps the proven, deterministic machinery and minimizes
new surface area.

```text
dropbox/ (pristine source, committed)
   │   generate_repo.py  (mirror + build zips + indexes + addons.xml)
   ▼
repo/ (committed generated output)  ──Pages/raw.githubusercontent──▶ Kodi
```

CI rule is unchanged and is the determinism backstop: run the build, then
`git status --porcelain` must be empty. So the compile must be **deterministic
and idempotent** — same `dropbox/` ⇒ byte-identical `repo/`, every time, on any
machine. (Reuse the existing dateless-index + fixed-timestamp-zip discipline; the
mirror copy is content-only, and git tracks content not mtime, so copies stay
clean.)

## Release interaction (`deploy.py`)

`deploy.py` stays the release path for `repository.tony7bones`, re-pointed at the
new source:

- It bumps the version in **`dropbox/repository.tony7bones/addon.xml`** (the
  authored source), then runs the `dropbox/ → repo/` build.
- The four version-bearing locations become: **`dropbox/` addon.xml (source)**,
  **root installer zip filename**, **root `index.html` link**, **git tag**. The
  generated `repo/repository.tony7bones/addon.xml` is now a _derived copy_;
  `check_consistency.py` verifies it equals the source rather than treating it as
  an independent location.
- The **root `/index.html`** and the **root `repository.tony7bones-X.Y.Z.zip`**
  stay at the repo root (NOT inside `dropbox/` or `repo/`), still owned by
  `deploy.py`, still the constant install URL. The root zip is built from
  `dropbox/repository.tony7bones/` source.
- `script.*` add-ons still release via the build + commit + push (not
  `deploy.py`); they now bump their `dropbox/<id>/addon.xml` and the build
  regenerates `repo/`.

## Safety rules (P0 — enforced in code AND tested)

1. **Byte-identity on migration** — the first `dropbox/ → repo/` build must
   produce `repo/` **byte-identical** to today's committed `repo/` (same add-on
   zips especially). A changed same-version zip silently breaks Kodi upgrades.
   This is the migration's hard acceptance gate.
2. The build **never writes the root `/index.html`** (that's `deploy.py`'s) and
   never changes the constant install URL.
3. The build **never writes into `dropbox/`** (source is read-only to the system).
4. `hosted/` is preserved at `repo/hosted/<id>/` byte-for-byte so the proxy's
   `raw.githubusercontent` fetches keep resolving.
5. Determinism: build twice ⇒ zero git diff (the CI gate).

## Migration (one-time, history-preserving, byte-identical)

1. **Pre-clean** the known rot first so we don't migrate garbage: delete the
   stale tracked zips `repo/scripts/script.tony7bones.bootstrap-1.0.5.zip` and
   `repo/scripts/script.tony7bones.modv2.patch-1.0.2.zip` (retired add-on),
   regenerate, commit.
2. **`git mv`** the human-authored source out of `repo/` into `dropbox/`
   (add-on source dirs, `hosted/`, `repositories/`, `scripts/`, `media/`,
   `iptv/`, `rss/`), preserving history. Leave generated artifacts behind to be
   re-emitted.
3. **Implement the input/output split** in `generate_repo.py` (read `dropbox/`,
   write `repo/`).
4. **Build**, then assert `repo/` is byte-identical to the pre-migration `repo/`
   (P0 gate #1) — proving zero behavior change for live installs.
5. **Re-point `deploy.py` / `check_consistency.py`** at the new source locations.
6. **Update CI + pre-push** to build from `dropbox/` and keep the
   `git status --porcelain` determinism check.

## Sequencing

- **Step 0 — pre-clean** (rot zips + regenerate). Standalone, low-risk.
- **Step 1 — input/output split** in the generator (build `dropbox/ → repo/`),
  behind a flag/no-op until `dropbox/` exists; full determinism tests.
- **Step 2 — migrate** source into `dropbox/` via `git mv`; assert byte-identical
  `repo/` output (P0 gate).
- **Step 3 — re-point release tooling** (`deploy.py`, `check_consistency.py`) and
  the version-location model.
- **Step 4 — generated `repo/index.html`** (remove the never-overwrite guard) +
  wire the build/determinism check into `.githooks/pre-push` and CI.

Each step independently CI-clean and pushed only after the local gates pass.

## Test matrix & acceptance

New `_tools/test_build.py` (mirrors `test_generate_repo.py` conventions) with a
`_snapshot_tree(root) -> {path: bytes}` oracle (mtime-excluded):

- **Determinism/idempotency:** build twice ⇒ byte-identical `repo/`; empty/absent
  `dropbox/` is a safe no-op; build is machine-independent (no mtime/date leak).
- **Compile correctness:** every add-on dir in `dropbox/` → a deterministic zip +
  an `addons.xml` entry in `repo/`; `hosted/` mirrored verbatim; every folder gets
  a Kodi-format `index.html`; `repo/index.html` lists present areas, no dates, no
  install-URL line.
- **Byte-identity migration gate:** post-migration `repo/` == pre-migration
  `repo/` (the live-install safety proof).
- **Release:** `deploy.py` bumps `dropbox/` source, four version locations agree,
  root zip + root index synced, tag correct, root `/index.html` untouched by the
  build.
- **Safety negatives (P0):** build never writes `dropbox/`; never writes root
  `/index.html`; never changes a `hosted/` byte.
- **Regression:** existing generator behavior preserved; `test_deploy.py` /
  consistency gate green.

**Acceptance:** all of the above pass; `ruff` clean; on the real repo, build →
`git status` empty, build again → still empty; byte-identity gate proven; a
deliberately-broken `dropbox/` fails at pre-push, before any push.

## Open sub-decisions (settle during Step 1)

1. **`dropbox/` internal conventions doc** — a short README _in `dropbox/`_ (the
   one permitted "meta" file) describing the few reserved conventions (addon.xml =
   add-on, `hosted/` = mirror), so the human never wonders. Confirm wanted.
2. **Old-version installer-zip accumulation** in `repositories/`/`scripts/`:
   keep-all (surface duplicates in the build log) vs. keep-latest. Leaning:
   surface in log, prune deliberately (consistent with the root-zip cleanup).
3. **Doubled-diff ergonomics** — optionally have CI/PR view collapse `repo/` diffs
   (generated) to keep human review focused on `dropbox/`. Nice-to-have.
