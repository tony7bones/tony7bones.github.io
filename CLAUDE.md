# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repo is

A GitHub Pages site (`tony7bones.github.io`) that hosts a Kodi add-on repository. The site is static — no bundler, no runtime. Python tooling under `_tools/` generates everything; `package.json` is only a script-runner wrapper.

The repository add-on, `repository.tony7bones`, is a **virtual repository** built on i96751414's `repository.github` engine: once installed in Kodi it runs a local HTTP proxy (`127.0.0.1:61234`) that streams add-on metadata and zips live from GitHub at runtime, driven by a `repository.json` manifest. There are no committed per-add-on zips for the third-party repos it lists.

**Install URL (must stay constant): `https://tony7bones.github.io/`** (the root). The root `index.html` exposes a Kodi-parseable link to `repository.tony7bones-<version>.zip` (the installer) plus a `repo/` link for file-manager browsing. Cache-busting comes ONLY from the versioned zip _filename_ — never from versioned paths, because Kodi cannot follow a moving base URL.

### Single branch — `main` only

Everything lives on `main` and the proxy fetches everything from `main` via raw.githubusercontent. `main` is served by GitHub Pages and holds the root installer zip(s), root `index.html`, the static browsable area under `repo/`, the proxy add-on source at `repo/repository.tony7bones/`, the mirrored third-party-repo trees under `repo/hosted/<id>/`, and all `_tools/`.

A release bumps the version in one place — `repo/repository.tony7bones/addon.xml` — which is **both** the installed-addon metadata and the proxy's self-update version source. `_tools/deploy.py` does this atomically and pushes `main + tag` (see below).

> The `virtual-repo` branch is **retired** (the single-branch migration moved its `hosted/<id>/` trees to `repo/hosted/` on main and consolidated the self-update source into the main `addon.xml`). It may still exist as a fallback but is **unreferenced** by all shipped manifests and tooling — do not add anything to it. `hybrid-repo` is an abandoned experiment — ignore it.

### First-party add-ons (current)

Besides the proxy, the repo ships three first-party add-ons plus the Estuary MOD V2+ skin patch:

- `script.module.tony7bones` — a Python **library** (`xbmc.python.module`, invisible on the home screen) holding the shared install machinery (HTTP fetch, addons.xml index load/parse/merge, the dependency-closure resolvers, zip extract, enable/disable, add-on `origin` stamping, source-repo enabling, self-uninstall, restart, platform detection). The two Setups `<requires>` it, so Kodi auto-installs it from the repo.
- `script.tony7bones.bootstrap` — "Tony.7.Bones Setup", the one-tap base install; front-loads an optional video step (prompt + multiselect), runs unattended, one summary, one restart, then self-uninstalls.
- `script.tony7bones.video` — "Video Add-ons Setup", the standalone video installer; its `install_selected()` is the shared entry point the base Setup chains.
- `script.tony7bones.modv2plus` — "Estuary MOD V2+", the lean patch that customizes `skin.estuary.modv2` (gear-menu reorder, a "Tony.7.Bones MOD V2+" Skin Settings category with per-item toggles, crisp white nav wordmark, thin clock, Outline HD weather icons). Run by hand — it offers **Apply / Restore** (Restore confirms first) — after installing/updating the skin. Built FRESH from the current omega source each release; replaced the retired `script.tony7bones.modv2.patch`. Full dev cycle + lessons: `docs/playbooks/modv2plus-dev-cycle-and-lessons.md`.

### What the base Setup does after installing (`script.tony7bones.bootstrap/default.py`)

After the (optional video) install and before the single end-of-setup restart, `run()` applies a sequence of **base-box configuration** steps — each defensive (logged, never aborts the run), set before the restart so Kodi re-reads them:

- `_add_file_sources()` — merge File-Manager sources into `sources.xml` (deduped).
- `_trim_home_menu()` — hide all but TV / Add-ons / Favourites / Weather on stock Estuary via `Skin.SetBool` (the in-memory set is what survives the restart; a settings.xml merge backs it up).
- `_configure_box()` — weather + interface prefs: provider → `weather.multi`, **location 1 → Sacramento** (written into weather.multi's `addon_data`; note `loc1_url` is the field weather.multi actually fetches by, NOT lat/lon), RSS ticker on, top-bar weather (`Skin.SetBool(show_weatherinfo)`), then `_copy_device_files()` + `_ensure_iptv_custom_tv_groups()`.

**Device→userdata file convention.** `DEVICE_FILE_COPIES` copies user-placed files from the Fire Stick path `/storage/emulated/0/kodi/tony.7.bones/{rss,iptv}/…` into `userdata/` (RssFeeds.xml) and `userdata/addon_data/pvr.iptvsimple/…` (instance-settings-1.xml, channelGroups/customTVGroups-\*.xml). Each copy is **guarded** (no-ops if the source is absent, so desktop runs skip cleanly), **creates dest dirs, and overwrites**. The real copy only happens on the device; on the dev Mac only the guarded-skip path runs live — the copy logic is proven by unit tests, not live verification (state this honestly).

**Two non-obvious Kodi constraints encoded here (don't relearn them the hard way):**

- **pvr.iptvsimple _instance_ settings cannot be set via JSON-RPC** — `Settings.SetSettingValue` reaches only CORE Kodi settings. Instance settings (TV group mode, custom-groups file, m3u/EPG) live ONLY in `addon_data/pvr.iptvsimple/instance-settings-1.xml`; `_ensure_iptv_custom_tv_groups()` patches `tvGroupMode=2` (custom) + `customTvGroupsFile` there after the copy.
- **Hiding a single PVR channel group (e.g. "All channels") is NOT automatable from Setup** — the flag is `channelgroups.bIsHidden` in the PVR DB (`userdata/Database/TV<N>.db`), and that row only exists AFTER pvr.iptvsimple syncs channels post-restart; no JSON-RPC/core setting toggles it. It stays a one-time manual step (PVR & Live TV → Channels → Group manager).

The proxy serves add-ons from its **baked** `resources/repository.json` (read locally by `lib/service.py`), not `repo/addons.xml`. To add/change a served add-on, edit the single `repository.json` at `repo/repository.tony7bones/resources/` (for a mirrored third-party repo, drop its `addon.xml`/zip under `repo/hosted/<id>/` and point `asset_prefix` at `.../{ref}/repo/hosted/{id}/` with `"branch": "main"`) and release the proxy.

> Detailed operating guidance lives in the playbooks and the agent skill:
>
> - `docs/playbooks/kodi-install-mechanics.md` — install on Omega without blocking prompts (direct-extract + `SetAddonEnabled`, origin stamping, optional/required deps, platform binaries, self-uninstall, Estuary skin/home-menu, file sources).
> - `docs/playbooks/release-and-deploy.md` — the two release paths + the GitHub Pages skip-build gotcha + determinism.
> - `docs/playbooks/local-kodi-verification.md` — drive the real local Kodi; **honest** verification (prove non-empty `GetDirectory` + rendered menu, not just "no ImportError").
> - `docs/playbooks/one-shot-and-architecture.md` — the three-add-on architecture and the one-shot flow.
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
python3 -m pytest _tools/test_bootstrap.py::test_one_shot_yes_fetches_video_setup_when_absent -q

# Lint the Python tooling
ruff check _tools/
```

Test files map to what they cover (all tests import the add-on `default.py` under **mocked Kodi modules** — `run()` is `__main__`-guarded, so importing is side-effect-free, and the install/resolve logic is exercised directly with fake `xbmc*`):

| Test file                | Covers                                                                                                        |
| ------------------------ | ------------------------------------------------------------------------------------------------------------- |
| `test_bootstrap.py`      | `script.tony7bones.bootstrap` (base Setup + the one-shot orchestration)                                       |
| `test_video.py`          | `script.tony7bones.video` (Video Add-ons Setup)                                                               |
| `test_module.py`         | `script.module.tony7bones` (shared install library)                                                           |
| `test_proxy.py`          | `repository.tony7bones` proxy engine (version math, manifest validators, tag/URL resolution, cache, platform) |
| `test_deploy.py`         | `deploy.py` / `release_lib.py` (sandbox end-to-end with a bare remote)                                        |
| `test_check_versions.py` | the per-add-on version-bump gate                                                                              |
| `test_generate_repo.py`  | the generator (zips, indexes, determinism)                                                                    |

## Releasing

There are **two** release paths — pick the right one (full detail in `docs/playbooks/release-and-deploy.md`):

- **A `script.*` / `script.module.*` add-on** (`script.module.tony7bones`, `script.tony7bones.bootstrap`, `script.tony7bones.video`, `script.tony7bones.modv2plus`): bump its `repo/<id>/addon.xml` version (+ news), run `python3 _tools/generate_repo.py`, commit the regenerated files, `git push`. **Not** `deploy.py`. The pre-push hook enforces tests, ruff, generated-files freshness, version consistency on main, and a per-add-on version-bump (`check_versions.py`).
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
sync all four version-bearing locations (main `repo/repository.tony7bones/addon.xml`
— which doubles as the proxy self-update source — root zip filename, root
`index.html` link, git tag) → commit main → tag → `git push --atomic main <tag>` →
force a GitHub Pages build → verify live on Pages. Any failure before the push rolls
main and the tag back. It refuses to run on a dirty tree, when behind origin, or when
the new version is not greater than the current one. The version lives ONLY in
`addon.xml`; `package.json` deliberately does not mirror it.

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

### Content areas under `repo/`

| Path                      | Purpose                                                                                                                                                                                                                                                                                                                                                                    |
| ------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `repo/<addon-id>/`        | Any dir with an `addon.xml` becomes a zip and is listed in `addons.xml`. Currently: `repository.tony7bones` (the virtual proxy), `script.module.tony7bones` (the shared LIBRARY), `script.tony7bones.bootstrap` (Tony.7.Bones Setup), `script.tony7bones.video` (Video Add-ons Setup), and `script.tony7bones.modv2plus` (Estuary MOD V2+ skin patch).                     |
| `repo/repositories/`      | Stand-alone third-party repository installer zips. Not in `addons.xml` — Kodi installs them manually via file manager.                                                                                                                                                                                                                                                     |
| `repo/scripts/`           | One-shot script zips. Not in `addons.xml` — installed manually.                                                                                                                                                                                                                                                                                                            |
| `repo/media/`             | Images browsable from Kodi's file manager. `index.html` auto-generated.                                                                                                                                                                                                                                                                                                    |
| `repo/hosted/<id>/`       | Mirrored third-party-repo trees (`addon.xml` + zip) that the **proxy fetches from `main`** via raw.githubusercontent (the single-branch home of what used to be `virtual-repo:hosted/`). Static, committed by hand — NOT zipped or auto-indexed by the generator (`hosted` is a `_SPECIAL_DIRS` entry). Served by Pages too, but Pages-serving is irrelevant to the proxy. |
| `repo/iptv/`, `repo/rss/` | Arbitrary asset dirs. Any non-special dir without an `addon.xml` is recursively auto-indexed for file-manager browsing.                                                                                                                                                                                                                                                    |

`repo/addons.xml` (the static-repo index) still lists `repository.tony7bones` so that anyone on the legacy static repo auto-updates to the virtual proxy. The proxy itself does NOT read `repo/addons.xml` at runtime — it serves from its local `127.0.0.1` server driven by `repository.json`.

### Source files — `_tools/repo-sources/`

Reference copies of `addon.xml` / scripts for the installer and the two `script.tony7bones.*` add-ons, kept for rebuilding a zip by hand. They are **not** read by the generator and are not the source of truth for a release — the canonical add-on source is `repo/repository.tony7bones/` on `main`. `_tools/make_custom_m3u.py` is unrelated IPTV tooling.

### Generated files

The following files are **generated** by `generate_repo.py` and must be committed:

- `repo/addons.xml`, `repo/addons.xml.sha256`, `repo/addons.xml.md5`
- `repo/repositories/index.html`, `repo/scripts/index.html`, `repo/media/index.html`
- Per-addon `index.html` and zip files under `repo/<addon-id>/`

Always run `python3 _tools/generate_repo.py` locally and commit the output before pushing. CI validates that generated files are up to date and will fail if they are stale.

### Shared stylesheet

`style.css` at the repo root holds the dark theme used by all user-facing pages. It is referenced via absolute path `/style.css` so it works at any directory depth. The per-addon index pages (generated by `_make_index()`) intentionally use HTML 3.2 format for Kodi parser compatibility — do not apply the stylesheet there.

### Generator — `_tools/generate_repo.py`

All HTML generation (repositories index, scripts index, media index, per-addon indexes) lives here. Key functions:

- `process_addons()` — zips each addon dir (only if source is newer than existing zip), generates per-addon `index.html` (HTML 3.2, Kodi-compatible)
- `_styled_page()` — shared helper that returns a dark-themed HTML page using `/style.css`
- `generate_scripts_index()` — scans `repo/scripts/` for zips and writes its `index.html`
- `generate_media_index()` — scans `repo/media/` for images and writes its `index.html`
- `generate()` — orchestrates everything; `repo/index.html` is hand-crafted and never touched

### CI — `.github/workflows/generate_repo.yml`

Triggers on push touching `repo/**`, `_tools/**`, or `index.html`. Runs the full `_tools/` test suite, `ruff`, the generator + `git status --porcelain` staleness check, and the version-consistency gate (main only). **CI never commits anything back to main** — it only validates; if generated files are stale the author must run the generator (or `deploy.py`) and commit. This is why generated zips are deterministic: a non-reproducible zip would make CI flag stale files on every run.

### Adding a new Kodi add-on

1. Create `repo/<addon-id>/addon.xml` following the Kodi addon.xml schema and add any source files
2. Run `python3 _tools/generate_repo.py` — this zips the addon and updates `addons.xml`
3. `git add repo/<addon-id>/ repo/addons.xml repo/addons.xml.sha256 repo/addons.xml.md5`
4. Commit and push

### Adding a new repository installer zip

1. Drop the `.zip` into `repo/repositories/`
2. Run `python3 _tools/generate_repo.py`
3. Commit both the zip and the regenerated `repo/repositories/index.html`

### Adding a new script zip

1. Drop the `.zip` into `repo/scripts/`
2. Run `python3 _tools/generate_repo.py`
3. Commit both the zip and the regenerated `repo/scripts/index.html`

### Adding images to media

1. Drop the image into `repo/media/`
2. Run `python3 _tools/generate_repo.py`
3. Commit both the image and the regenerated `repo/media/index.html`

### Kodi source URL

**`https://tony7bones.github.io/`** (the root). Users add this as a file-manager source, then install `repository.tony7bones-<version>.zip` from it. This URL must never change — only the zip filename's version moves. The legacy static endpoint `https://tony7bones.github.io/repo/addons.xml` still exists for migration but is not the install path.

Note: the `repository.tony7bones` add-on is the virtual proxy and is released only via `_tools/deploy.py` (single-branch: it bumps `main` and tags, then pushes `main + tag`). The "adding a new add-on / zip" steps above are for _other_ content (third-party repos, scripts, images) and do not bump `repository.tony7bones`. After any of them, the pre-push hook will run tests + lint + staleness + consistency before the push is accepted.
