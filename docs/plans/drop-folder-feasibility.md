# Model B — One Source of Truth (`dropbox/` → `repo/`)

> **SUPERSEDED (2026-06-06).** A live spike confirmed a simpler approach —
> a clean `main` branch plus a CI-built `dist` branch — which avoids the
> problems the amendments below try to patch. See
> [dist-branch-decision.md](dist-branch-decision.md) for the chosen direction.
> This document is kept for history and for the still-useful Kodi findings in
> the amendments section.

> Status: **APPROVED IN DIRECTION — blocking amendments pending (do not execute
> as written).** Decided spec, hardened by a three-lens review (Kodi /
> architecture / QA) and the owner's decisions, then re-reviewed by a second
> independent three-lens panel (2026-06-06) that found the byte-identity gate
> self-contradictory and several unlisted safety gaps. **Read
> [Panel review amendments (2026-06-06)](#panel-review-amendments-2026-06-06)
> before Step 0** — four edits are required first. No repo changes yet.
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

## Panel review amendments (2026-06-06)

A second, independent three-lens panel (architecture / QA / Kodi), each agent
working in isolation against the live code, re-reviewed this plan. They confirmed
the direction and the core Kodi mechanics (see "Confirmed by the panel" below)
but found the **byte-identity gate is self-contradictory as a whole-tree
invariant** and surfaced safety gaps not in the original plan. The four
amendments below are **blocking** — fold them in before Step 0.

> Numbering note: these supersede the affected lines above where they conflict.
> The original text is left intact for history; this section is the authority.

### Amendment A — Scope the byte-identity gate (do NOT assert whole-tree). **[P0, blocking]**

P0 gate #1 as written ("post-migration `repo/` byte-identical to today's `repo/`")
is unachievable, for **two independent reasons** the panel reached separately:

- **`repo/index.html` (QA + Kodi).** Today's `repo/index.html` is hand-crafted
  **and stale** — it advertises
  `https://tony7bones.github.io/repo/repositories/repository.tony7bones-1.0.5.zip`,
  a path that does not exist (the real install zip is the root
  `repository.tony7bones-2.0.0.zip`). Step 4 generates this file _without_ an
  install-URL line, so its bytes necessarily change → CI `git status --porcelain`
  is non-empty → the gate the plan calls its go/no-go fails on Step 4. (The
  **root** `/index.html` is correct at 2.0.0 and is untouched by the build — only
  `repo/index.html` is the problem. Dropping its stale line is a net fix, not a
  regression.)
- **Source de-duplication (architecture, see Amendment B).** If `repo/<addon>/`
  stops carrying unpacked source, it can no longer be byte-identical to today's
  `repo/<addon>/`, which _contains_ that source.

**Resolution:** redefine the gate to cover **only what Kodi actually loads** —
the five first-party add-on **zips**, every `addon.xml` (first-party + each
`repo/hosted/<id>/addon.xml`), and the `hosted/` trees — **not** the whole tree.
`repo/index.html` is an explicit, reviewed **one-time carve-out** shipped in its
own Step 4 commit. The byte-identity assertion in Steps 0–3 must exclude
`repo/index.html`; a Step 4 test asserts the regenerated landing is well-formed
and carries no `1.0.5` / `repo/repositories/` / install-URL line. Pin the oracle
snapshot to the **post-Step-0** commit (Step 0 deletes rot zips and regenerates
`repo/scripts/index.html`, so the pre-clean changes `repo/` before the gate).

### Amendment B — Secrets / `.gitignore` in the mirror. **[P0, blocking — active leak risk]**

`.gitignore` ignores `repo/iptv/instance-settings*.xml` (a local-only secret),
and the ignore pattern is **path-anchored to `repo/`**. When that file moves to
`dropbox/iptv/…` it is **no longer ignored at all** — a verbatim
`dropbox/ → repo/` mirror would (a) commit the secret in `dropbox/` and (b) copy
it into the committed, **Pages-served** `repo/`. Double exposure of a secret to a
public repo. The plan's P0 rules never mention `.gitignore`.

**Resolution:** add a P0 rule — **the mirror honors `.gitignore`** (skips ignored
paths) — and **re-anchor** the existing `repo/iptv/instance-settings*.xml` ignore
to the `dropbox/` source. Add a **negative test**: a gitignored/secret file under
`dropbox/` never appears in `repo/` (nor in any `addons.xml`/index). Implement the
exclusion with a **batched** `git check-ignore --stdin` (or `git ls-files`
filtering), **not** the current per-file `_git_ignored()` subprocess — a per-file
fork across the whole `dropbox/` tree on every build/pre-push is too slow.

### Amendment C — Re-point ALL version gates, not just `deploy.py`/`check_consistency.py`. **[blocking]**

The plan's Steps 3/5 name only `deploy.py` and `check_consistency.py`. The panel
found two more:

- **`check_versions.py` is omitted and would silently regress.** It hardcodes
  `ADDON_BASE = repo/` and diffs `repo/<addon>/` source against `origin/main`. If
  Amendment B/source-dedup removes source from `repo/<addon>/`, it finds nothing
  to diff → the "every changed add-on must bump its version" gate **silently
  passes for everything**. Re-point it at `dropbox/`.
- **`check_consistency.py` gains a new invariant, not just a path swap.** Making
  `repo/repository.tony7bones/addon.xml` a _derived copy_ of the `dropbox/` source
  changes the gate from "do N independent locations agree" to "…agree **and** the
  derived copy equals its source." `MAIN_ADDON` (currently the `repo/` path) must
  point at the source, a new derived-equality field/check is added, and
  `test_deploy.py`'s sandbox must be updated to the new layout. This introduces a
  new **source/derived skew** failure mode (build skipped or non-deterministic →
  served self-update metadata diverges from the tag) — enumerate it in the gate
  list. Also verify `deploy.py`'s `GENERATED_ZIP_DIR` still resolves to the
  **output** `repo/repository.tony7bones/` and that the build runs **before** the
  root-zip copy.

### Amendment D — Document the ROI / duplication trade before committing to Full Model B. **[blocking decision, not code]**

The plan is marked "APPROVED / decisions locked" without a written comparison to
lighter options. The panel rated this its weakest point. Cost the alternatives
explicitly:

- **Permanent binary bloat.** `hosted/` (~1.7M), `repositories/` (~2.9M),
  `media/` (~576K) are binary; Full Model B commits them under two paths forever,
  and zips don't delta-compress — roughly **doubling the pack's binary growth
  rate**. Adopting source-dedup (Amendment B/below) removes only first-party
  _source_ duplication, not these pass-through binaries.
- **Lighter alternatives to weigh:** a `git`-aware **"clean view"** command that
  hides generated artifacts (≈90% of the "clean folder" benefit, ≈1% of the risk,
  zero migration); and/or a **scoped split** — `dropbox/<addon>/` holds source,
  `repo/<addon>/` holds only the built zip + index — applied **only** to add-on
  dirs, leaving `hosted/`/`repositories/`/`scripts/`/`media/` exactly where they
  are (already clutter-free). The scoped split is where the dedup is nearly free.

Decide Full Model B vs. scoped split vs. clean-view **with this trade written
down** before any code.

### Other findings to fold in (non-blocking but real)

- **`_zip_is_stale` mtime heuristic doesn't survive a copy pipeline.** The mirror
  rewrites mtimes every run, breaking the incremental-rebuild trigger
  (determinism itself is fine — fixed 1980 timestamps). Switch to always-rebuild
  or content-hash staleness. "Just an I/O split, minimal new surface" understates
  this.
- **Mirror must prune deletions.** Git sees adds, not the _absence_ of a delete;
  a file removed from `dropbox/` but left in `repo/` won't trip the porcelain
  gate. Add a test: remove a `dropbox/` file → it disappears from `repo/`.
- **Rollback / determinism is now load-bearing for production.** Model B inserts a
  build transform between human edit and the bytes live Kodi boxes fetch from
  `…/main/repo/…`. Require a tested rollback (revert to the pre-migration commit
  reproduces identical `repo/`) and treat the determinism gate as a production
  guard, not just CI hygiene.
- **Keep HTML-3.2 for parser-facing indexes.** `_make_index` (HTML 3.2 `<pre>`)
  is required for the add-on/asset index pages Kodi's file-manager parses; do not
  unify them onto `_styled_page`.
- **`_git_date`/`_fmt_date` are effectively dead in `generate()`** (indexes emit
  sizes, not dates). The rewrite is the moment to delete them or wire them — don't
  carry them in unexamined, and confirm no date leak reactivates.
- **Naming.** `dropbox/` reads as the SaaS, not a drop folder; `src/`/`source/`
  is clearer. Cheap to fix now.

### Confirmed by the panel (de-risks execution)

- **Zip arcname is provably location-independent.** `arcname =
relpath(fpath, dirname(addon_dir))` depends only on the add-on's basename, so
  `repo/ → dropbox/` does not perturb member paths **provided the split only
  re-points the scan root and leaves the arcname math alone**. Add a test
  asserting member paths have no `dropbox/`/`repo/` prefix and the built zip hash
  equals the committed one — the failure would be invisible to humans.
- **Proxy fetch paths need ZERO `asset_prefix` edits.** All `repository.json`
  entries are `branch: main` with `asset_prefix` under `/repo/…`; keeping `repo/`
  committed with `hosted/` mirrored verbatim preserves every
  `raw.githubusercontent` path byte-for-byte. The proxy rebuilds `addons.xml`
  in-memory at runtime (it never reads `repo/addons.xml`), so that file's bytes
  matter only to legacy static-repo users, not the proxy.
- **Install-URL flow is preserved.** Root `/index.html` + the versioned root zip
  stay at the repo root, owned by `deploy.py`; the constant install URL
  `https://tony7bones.github.io/` is untouched.
