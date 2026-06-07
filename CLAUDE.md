# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repo is

A GitHub Pages site (`tony7bones.github.io`) that hosts a Kodi add-on repository. The site is static — no bundler, no runtime. Python tooling under `_tools/` generates everything; `package.json` is only a script-runner wrapper.

The repository add-on, `repository.tony7bones`, is a **virtual repository** built on i96751414's `repository.github` engine: once installed in Kodi it runs a local HTTP proxy (`127.0.0.1:61234`) that streams add-on metadata and zips live from GitHub at runtime, driven by a `repository.json` manifest. There are no committed per-add-on zips for the third-party repos it lists.

**Install URL (must stay constant): `https://tony7bones.github.io/`** (the root). The root `index.html` is **generated** and exposes a Kodi-parseable link to `repository.tony7bones-<version>.zip` (the installer) plus the canvas folders (`repositories/ media/ iptv/ rss/`) for file-manager browsing. Cache-busting comes ONLY from the versioned zip _filename_ — never from versioned paths, because Kodi cannot follow a moving base URL.

### Two source trees: `dropbox/` (canvas) and `addons/` (add-on tree)

The repo has two pristine, committed source trees, each with a different job:

- **`dropbox/`** — the owner's **pristine human canvas**. It holds ONLY hand-authored installable content (`repositories/` third-party repo installer zips, `media/`, `iptv/`, `rss/`) and NEVER any generated files (no `index.html`, no checksums). The build **mirrors `dropbox/` 1:1 to the repo ROOT**, which is what GitHub Pages serves at the bare URL `https://tony7bones.github.io/`. Pointing Kodi's File Manager at the bare URL therefore shows exactly the canvas: `repositories/ media/ iptv/ rss/` plus the install zip and a generated Kodi index per folder. The mirror **honors `.gitignore`**, so a secret-bearing source file (e.g. `dropbox/iptv/instance-settings*.xml`) lives in the canvas for local use but is never copied into the served tree or any listing.
- **`addons/`** — the machine/add-on tree. It holds the first-party add-on source, the proxy source at `addons/repository.tony7bones/`, the built per-addon zips, `addons.xml`/`.sha256`/`.md5`, and the mirrored third-party-repo trees under `addons/hosted/<id>/`. The virtual proxy fetches add-on metadata and zips from `main` via raw.githubusercontent (`.../main/addons/...` and `.../main/addons/hosted/<id>/`). The `addons/` tree is NOT listed at the bare URL.

### Single branch — `main` only

Everything lives on `main` and the proxy fetches everything from `main` via raw.githubusercontent. `main` is served by GitHub Pages and holds the root installer zip(s), the generated root `index.html`, the served canvas (mirrored from `dropbox/`), the `addons/` tree (add-on source + the proxy source at `addons/repository.tony7bones/` + the mirrored third-party-repo trees under `addons/hosted/<id>/`), and all `_tools/`.

A release bumps the version in one place — `addons/repository.tony7bones/addon.xml` — which is **both** the installed-addon metadata and the proxy's self-update version source. `_tools/deploy.py` does this atomically and pushes `main + tag` (see below).

> The `virtual-repo` branch is **retired** (the single-branch migration moved its `hosted/<id>/` trees to `addons/hosted/` on main and consolidated the self-update source into the main `addon.xml`). It may still exist as a fallback but is **unreferenced** by all shipped manifests and tooling — do not add anything to it. `hybrid-repo` is an abandoned experiment — ignore it.

### First-party add-ons (current)

Besides the proxy, the repo ships two first-party Setup/library add-ons plus the Estuary MOD V2+ skin patch — **four** first-party add-ons in total (counting the proxy):

- `repository.tony7bones` — the virtual proxy repository (runs the local `127.0.0.1:61234` server).
- `script.module.tony7bones` — a Python **library** (`xbmc.python.module`, invisible on the home screen) holding the shared install machinery (HTTP fetch, addons.xml index load/parse/merge, the dependency-closure resolvers, zip extract, enable/disable, add-on `origin` stamping, source-repo enabling, the curated-video installer `install_selection()`, self-uninstall, restart, platform detection). The Setup `<requires>` it, so Kodi auto-installs it from the repo.
- `script.tony7bones.bootstrap` — "Tony.7.Bones Setup", the one-tap base install; runs fully **unattended** (no prompts, no picker), installs the base repos + apps plus a curated set of video add-ons in one pass, shows one summary, restarts once, then self-uninstalls.
- `script.tony7bones.modv2plus` — "Estuary MOD V2+", the lean patch that customizes `skin.estuary.modv2` (gear-menu reorder, a "Tony.7.Bones MOD V2+" Skin Settings category with per-item toggles, crisp white nav wordmark, thin clock, Outline HD weather icons). Run by hand — it offers **Apply / Restore** (Restore confirms first) — after installing/updating the skin. Built FRESH from the current omega source each release; replaced the retired `script.tony7bones.modv2.patch`. Full dev cycle + lessons: `docs/playbooks/modv2plus-dev-cycle-and-lessons.md`.

> The standalone `script.tony7bones.video` ("Video Add-ons Setup") add-on has been **removed**. Its install logic was folded into the shared library as `install_selection(selected, official_base, disable_ids, dialog, log)`, which the Setup now calls directly to install the curated video add-ons unattended.

### What the base Setup does after installing (`script.tony7bones.bootstrap/default.py`)

After the unattended video install and before the single end-of-setup restart, `run()` applies a sequence of **base-box configuration** steps — each defensive (logged, never aborts the run), set before the restart so Kodi re-reads them:

- `_add_file_sources()` — merge File-Manager sources into `sources.xml` (deduped).
- `_trim_home_menu()` — hide all but TV / Add-ons / Favourites / Weather on stock Estuary via `Skin.SetBool` (the in-memory set is what survives the restart; a settings.xml merge backs it up).
- `_configure_box()` — weather + interface prefs: provider → `weather.multi`, **location 1 → Sacramento** (written into weather.multi's `addon_data`; note `loc1_url` is the field weather.multi actually fetches by, NOT lat/lon), RSS ticker on, top-bar weather (`Skin.SetBool(show_weatherinfo)`), then `_copy_device_files()` + `_ensure_iptv_custom_tv_groups()`.

**Device→userdata file convention.** `DEVICE_FILE_COPIES` copies user-placed files from the Fire Stick path `/storage/emulated/0/kodi/tony.7.bones/{rss,iptv}/…` into `userdata/` (RssFeeds.xml) and `userdata/addon_data/pvr.iptvsimple/…` (instance-settings-1.xml, channelGroups/customTVGroups-\*.xml). Each copy is **guarded** (no-ops if the source is absent, so desktop runs skip cleanly), **creates dest dirs, and overwrites**. The real copy only happens on the device; on the dev Mac only the guarded-skip path runs live — the copy logic is proven by unit tests, not live verification (state this honestly).

**Two non-obvious Kodi constraints encoded here (don't relearn them the hard way):**

- **pvr.iptvsimple _instance_ settings cannot be set via JSON-RPC** — `Settings.SetSettingValue` reaches only CORE Kodi settings. Instance settings (TV group mode, custom-groups file, m3u/EPG) live ONLY in `addon_data/pvr.iptvsimple/instance-settings-1.xml`; `_ensure_iptv_custom_tv_groups()` patches `tvGroupMode=2` (custom) + `customTvGroupsFile` there after the copy.
- **Hiding a single PVR channel group (e.g. "All channels") is NOT automatable from Setup** — the flag is `channelgroups.bIsHidden` in the PVR DB (`userdata/Database/TV<N>.db`), and that row only exists AFTER pvr.iptvsimple syncs channels post-restart; no JSON-RPC/core setting toggles it. It stays a one-time manual step (PVR & Live TV → Channels → Group manager).

The proxy serves add-ons from its **baked** `resources/repository.json` (read locally by `lib/service.py`), not `addons/addons.xml`. To add/change a served add-on, edit the single `repository.json` at `addons/repository.tony7bones/resources/` (for a mirrored third-party repo, drop its `addon.xml`/zip under `addons/hosted/<id>/` and point `asset_prefix` at `.../{ref}/addons/hosted/{id}/` with `"branch": "main"`) and release the proxy. (Note: the `repository.peno64` entry legitimately keeps `/repo/` in its URLs because that is peno64's OWN upstream repo layout — not our `addons/` tree.)

> Detailed operating guidance lives in the playbooks and the agent skill:
>
> - `docs/playbooks/kodi-install-mechanics.md` — install on Omega without blocking prompts (direct-extract + `SetAddonEnabled`, origin stamping, optional/required deps, platform binaries, self-uninstall, Estuary skin/home-menu, file sources).
> - `docs/playbooks/release-and-deploy.md` — the two release paths + the GitHub Pages skip-build gotcha + determinism.
> - `docs/playbooks/local-kodi-verification.md` — drive the real local Kodi; **honest** verification (prove non-empty `GetDirectory` + rendered menu, not just "no ImportError").
> - `docs/playbooks/one-shot-and-architecture.md` — the first-party add-on architecture and the one-shot flow.
> - `docs/playbooks/modv2plus-dev-cycle-and-lessons.md` — **MOD V2+ patch: the ADB-on-real-Fire-TV dev cycle + hard-won lessons** (Mac ≠ device; build from current omega; the `WeatherIcons` skin-string mechanism; default-on opt-out flags; logo wordmark-vs-mark; JSON-RPC limits; XBTF extraction; safety).
> - `docs/playbooks/firetv-adb-dev.md` — command-level runbook for driving the Office Fire TV over ADB + JSON-RPC (`_tools/firetv.sh`).
> - `.claude/skills/kodi-super-agent/SKILL.md` — distilled agent operating guide.
> - `docs/plans/` — historical design docs (implemented).

## Commands

```bash
# Regenerate addons.xml, addons.xml.sha256, per-addon zips, and all index pages
# Run this locally before committing whenever you change addon sources or add zips
python3 _tools/generate_repo.py

# Run the full test suite
python3 -m pytest _tools/ -q

# Run one test file, or a single test (test files mapped below)
python3 -m pytest _tools/test_bootstrap.py -q
python3 -m pytest _tools/test_bootstrap.py::test_video_installs_unattended -q

# Lint the Python tooling
ruff check _tools/
```

Test files map to what they cover (all tests import the add-on `default.py` under **mocked Kodi modules** — `run()` is `__main__`-guarded, so importing is side-effect-free, and the install/resolve logic is exercised directly with fake `xbmc*`):

| Test file                | Covers                                                                                                        |
| ------------------------ | ------------------------------------------------------------------------------------------------------------- |
| `test_bootstrap.py`      | `script.tony7bones.bootstrap` (base Setup + the unattended one-shot, incl. the curated video step)            |
| `test_module.py`         | `script.module.tony7bones` (shared install library, incl. `install_selection`)                                |
| `test_modv2plus.py`      | `script.tony7bones.modv2plus` (the Estuary MOD V2+ skin patch)                                                |
| `test_proxy.py`          | `repository.tony7bones` proxy engine (version math, manifest validators, tag/URL resolution, cache, platform) |
| `test_deploy.py`         | `deploy.py` / `release_lib.py` (sandbox end-to-end with a bare remote)                                        |
| `test_check_versions.py` | the per-add-on version-bump gate                                                                              |
| `test_generate_repo.py`  | the generator (zips, indexes, canvas mirror, determinism)                                                     |

## Releasing

There are **two** release paths — pick the right one (full detail in `docs/playbooks/release-and-deploy.md`):

- **A `script.*` / `script.module.*` add-on** (`script.module.tony7bones`, `script.tony7bones.bootstrap`, `script.tony7bones.modv2plus`): bump its `addons/<id>/addon.xml` version (+ news), run `python3 _tools/generate_repo.py`, commit the regenerated files, `git push`. **Not** `deploy.py`. The pre-push hook enforces tests, ruff, generated-files freshness, version consistency on main, and a per-add-on version-bump (`check_versions.py`).
- **The repository add-on (`repository.tony7bones`)**: use the one-command release tool below.

### Releasing the repository add-on (`repository.tony7bones`)

**Never hand-edit the version in multiple places.** Use the one-command release tool.
Every release MUST bump the version — Kodi keys auto-upgrade off the version number,
so same-version byte changes are forbidden (they silently break upgrades).

```bash
python3 _tools/deploy.py --news "What changed"     # patch bump (default)
python3 _tools/deploy.py --minor --news "..."      # or --major / --version X.Y.Z
python3 _tools/deploy.py --news "..." --dry-run     # preview the plan, change nothing
python3 _tools/deploy.py check                      # version-consistency gate only
```

Or via npm (thin wrappers): `npm run deploy -- --news "..."`, `deploy:dry`, `deploy:minor`, `deploy:major`, `deploy:local` (`--no-push`), `check`, `verify`.

`deploy.py` runs the whole pipeline atomically: bump → build deterministically →
sync all four version-bearing locations (main `addons/repository.tony7bones/addon.xml`
— which doubles as the proxy self-update source — root zip filename, root
`index.html` link, git tag) → commit main → tag → `git push --atomic main <tag>` →
force a GitHub Pages build → verify live on Pages. The root `index.html` link is
produced by the generator (which owns the bare-URL canvas listing) when deploy
re-runs the build, so there is no separate index-link rewrite step. Any failure
before the push rolls main and the tag back. It refuses to run on a dirty tree, when
behind origin, or when the new version is not greater than the current one. The
version lives ONLY in `addon.xml`; `package.json` deliberately does not mirror it.

The release tooling is split for testability: `_tools/release_lib.py` (pure version
math + file transforms + the single-source-of-truth `DeployPlan`), `_tools/check_consistency.py`
(reads all four locations on main and fails on any mismatch — reused by
the hook, CI, and deploy), `_tools/deploy.py` (orchestrator), `_tools/test_deploy.py`
(unit + end-to-end sandbox tests with a bare remote).

## Gates (pre-push hook)

`.githooks/pre-push` blocks a push unless tests pass, lint is clean, generated files
are up to date, and all four version locations agree and are tagged. Install once
after cloning:

```bash
git config core.hooksPath .githooks
```

The hook runs `python3 -m pytest` and `ruff` with the bare interpreter on PATH, so
those deps must be importable by that `python3` or the hook fails closed (blocking
legitimate pushes). On a fresh clone install them once — on an externally-managed
(PEP 668) Homebrew/macOS python this is:

```bash
python3 -m pip install --user --break-system-packages pytest ruff
```

If they're missing, the hook can't validate and a red-test release can reach `main`
(CI only catches it post-push). Re-run after a python **minor** upgrade (new user-site).

CI (`generate_repo.yml`) re-runs the same checks as a backstop and **never commits to
main**. The old `.pre-commit-config.yaml` (pytest on commit) still works if installed.

## Architecture

### Source areas

| Path                            | Purpose                                                                                                                                                                                                                                                                                                                                 |
| ------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `addons/<addon-id>/`            | Any dir with an `addon.xml` is built into a zip and listed in `addons/addons.xml`. Currently: `repository.tony7bones` (the virtual proxy), `script.module.tony7bones` (the shared LIBRARY), `script.tony7bones.bootstrap` (Tony.7.Bones Setup), and `script.tony7bones.modv2plus` (Estuary MOD V2+ skin patch).                         |
| `addons/hosted/<id>/`           | Mirrored third-party-repo trees (`addon.xml` + zip) that the **proxy fetches from `main`** via raw.githubusercontent (the single-branch home of what used to be `virtual-repo:hosted/`). Static, committed by hand — NOT zipped or indexed by the generator (`hosted` is the sole `_ADDONS_SPECIAL` entry). Not listed at the bare URL. |
| `dropbox/repositories/`         | The owner's hand-authored stand-alone third-party repository installer zips. Not in `addons.xml` — Kodi installs them manually via file manager. Mirrored 1:1 to the served `/repositories/`.                                                                                                                                           |
| `dropbox/media/`                | Hand-authored images. Mirrored to the served `/media/`, browsable from Kodi's file manager (`index.html` auto-generated in the served copy).                                                                                                                                                                                            |
| `dropbox/iptv/`, `dropbox/rss/` | Hand-authored asset dirs. Mirrored to the served root and recursively auto-indexed for file-manager browsing. Git-ignored files (e.g. `dropbox/iptv/instance-settings*.xml`) are kept locally and never copied into the served tree.                                                                                                    |

`dropbox/` is **pristine** — the build NEVER writes generated files (index.html, checksums) back into it; the generator mirrors it to the repo ROOT, which is what GitHub Pages serves at the bare URL.

`addons/addons.xml` (the static-repo index) still lists `repository.tony7bones` so that anyone on the legacy static repo auto-updates to the virtual proxy. The proxy itself does NOT read `addons/addons.xml` at runtime — it serves from its local `127.0.0.1` server driven by `repository.json`.

### Source files — `_tools/repo-sources/`

Reference copies of `addon.xml` / scripts for the installer and the bootstrap add-on, kept for rebuilding a zip by hand. They are **not** read by the generator and are not the source of truth for a release — the canonical add-on source is `addons/repository.tony7bones/` on `main`. `_tools/make_custom_m3u.py` is unrelated IPTV tooling.

### Generated files

The following files are **generated** by `generate_repo.py` and must be committed:

- `addons/addons.xml`, `addons/addons.xml.sha256`, `addons/addons.xml.md5`
- Per-addon `index.html` and zip files under `addons/<addon-id>/`
- The served canvas mirror at the repo ROOT: the `repositories/ media/ iptv/ rss/` copies of `dropbox/`, each with a Kodi `index.html` per folder
- The root `index.html` (the bare-URL canvas listing — the generator OWNS it)

Always run `python3 _tools/generate_repo.py` locally and commit the output before pushing. CI validates that generated files are up to date and will fail if they are stale.

### Shared stylesheet

`style.css` at the repo root holds the dark theme used by any styled user-facing page. The directory-listing pages the generator writes (via `_make_index()`) intentionally use HTML 3.2 format for Kodi parser compatibility and do NOT apply the stylesheet.

### Generator — `_tools/generate_repo.py`

The generator reads from the two source trees and writes the served output (an INPUT/OUTPUT split). Key functions:

- `process_addons(scan_dir)` — builds a reproducible zip + a per-addon HTML 3.2 index for each add-on dir under `scan_dir`, returns the `<addon>` roots for `addons.xml`, and skips `hosted/`.
- `write_addons_xml(roots)` — writes `addons/addons.xml` + `.sha256` + `.md5`.
- `mirror_canvas()` — mirrors `dropbox/` -> the repo ROOT 1:1, honoring `.gitignore` and pruning root dirs that are no longer in `dropbox/`; returns the canvas listing.
- `_index_tree(top)` — writes a Kodi HTML 3.2 index into `top` and every subdir.
- `write_root_index(canvas_listing)` — generates the bare-URL root `index.html` (the canvas 1:1 plus the install zip).
- `_inject_install_zip_into_repositories()` — copies the root proxy installer zip into the SERVED `repositories/` so it is browsable in the canvas; `dropbox/` stays pristine.
- `generate()` — orchestrates everything.

(The old `sync_dropbox`, `generate_scripts_index`, `generate_media_index`, `generate_asset_indexes`, `_styled_page`, and `_fmt_date` functions were removed, and the old "the root `index.html` is hand-crafted, never overwrite" rule is gone — the root index is now generated.)

### CI — `.github/workflows/generate_repo.yml`

Runs the full `_tools/` test suite, `ruff`, the generator + `git status --porcelain` staleness check, and the version-consistency gate (main only). **CI never commits anything back to main** — it only validates; if generated files are stale the author must run the generator (or `deploy.py`) and commit. This is why generated zips are deterministic: a non-reproducible zip would make CI flag stale files on every run.

### Adding a new Kodi add-on

1. Create `addons/<addon-id>/addon.xml` following the Kodi addon.xml schema and add any source files
2. Run `python3 _tools/generate_repo.py` — this builds the addon zip and updates `addons.xml`
3. `git add addons/<addon-id>/ addons/addons.xml addons/addons.xml.sha256 addons/addons.xml.md5`
4. Commit and push

### Adding a new repository installer zip

1. Drop the `.zip` into `dropbox/repositories/` (the canvas — never into the served root)
2. Run `python3 _tools/generate_repo.py` (it mirrors the canvas and regenerates the served `repositories/index.html`)
3. Commit the new zip under `dropbox/repositories/` plus the regenerated served `repositories/`

### Adding images to media

1. Drop the image into `dropbox/media/`
2. Run `python3 _tools/generate_repo.py`
3. Commit the new image under `dropbox/media/` plus the regenerated served `media/`

### Kodi source URL

**`https://tony7bones.github.io/`** (the root). Users add this as a file-manager source, then install `repository.tony7bones-<version>.zip` from it. This URL must never change — only the zip filename's version moves. The legacy static endpoint `https://tony7bones.github.io/addons/addons.xml` exists for migration but is not the install path.

Note: the `repository.tony7bones` add-on is the virtual proxy and is released only via `_tools/deploy.py` (single-branch: it bumps `main` and tags, then pushes `main + tag`). The "adding a new add-on / zip" steps above are for _other_ content (third-party repos, scripts, images) and do not bump `repository.tony7bones`. After any of them, the pre-push hook will run tests + lint + staleness + consistency before the push is accepted.
