---
name: kodi-super-agent
description: >-
  Kodi Super Agent Developer for the Tony.7.Bones repository
  (tony7bones.github.io). Load when working anywhere in this repo on Kodi
  add-on tasks — installing add-ons via the Setup script, building/editing the
  script.module.tony7bones shared library or the bootstrap Setup,
  releasing repository.tony7bones with deploy.py, releasing the script.* add-ons
  via generate_repo.py, adding an entry to repository.json, debugging the local
  Kodi 21 Omega install, or verifying behaviour on the real local Kodi. Triggers
  on Kodi add-on install / dependency-closure / origin / release / deploy /
  GitHub Pages / verification work in this project.
---

# Kodi Super Agent Developer

Operating guide for the Tony.7.Bones Kodi repository. Read the matching
playbook in `docs/playbooks/` before acting on any rule below — they carry the
WHY and the exact code locations.

## Orientation (read first)

- Project overview, branches, releases: repo-root `CLAUDE.md` + `README.md`.
- Architecture & one-shot flow: `docs/playbooks/one-shot-and-architecture.md`.
- The four first-party add-ons (current versions):
  - `repository.tony7bones` **2.2.1** — the virtual proxy repository (local
    `127.0.0.1:61234` server; released via `deploy.py`).
  - `script.module.tony7bones` **1.1.0** — shared LIBRARY (`xbmc.python.module`,
    hidden); holds all the generic install machinery incl. `install_selection`.
  - `script.tony7bones.bootstrap` **1.3.0** — "Tony.7.Bones Setup", the one-shot.
    In ONE unattended run it installs the source repos + base apps + the curated
    video add-ons (POV, The Loop, Sports HD, YouTube, no picker), applies the
    base-box config, **AND installs + activates the Estuary MOD V2 skin + the
    MOD V2+ patch**, then self-uninstalls and restarts once.
  - `script.tony7bones.modv2plus` **1.4.0** — "Estuary MOD V2+" skin patch. Has a
    **boot service** (`service.py`) that auto-applies the patch the first time
    MOD V2 is the active skin (and re-applies after a MOD V2 update), plus a
    manual Apply/Restore chooser + in-tab buttons for hand use.
- **Retired — do not reference:** the standalone `script.tony7bones.video` (its
  install logic is folded into the shared library as `install_selection`), and
  `script.tony7bones.modv2.patch` (replaced by `script.tony7bones.modv2plus`).
- Structure: `dropbox/` is the pristine human canvas, mirrored 1:1 to the repo
  ROOT and served at the bare URL `https://tony7bones.github.io/` (the Kodi File
  Manager source). `addons/` holds add-on source + built zips + `addons.xml` +
  `hosted/` and is what the proxy fetches via raw.githubusercontent.
  `generate_repo.py` compiles `dropbox/` → root and `addons/` → zips.

## Golden rules — install (Kodi 21 Omega)

→ all in `docs/playbooks/kodi-install-mechanics.md`

1. **Never `InstallAddon(...)` from a script** — it pops a blocking modal and
   deadlocks. Install by direct download+extract → `UpdateLocalAddons()` →
   JSON-RPC `Addons.SetAddonEnabled`. (No JSON-RPC install method exists on Omega.)
2. **Stamp `origin`** into `Addons<NN>.db` after enabling + enable the source
   repos. Blank origin = "unknown source" → The Loop modal-locks, POV menu is empty.
3. **Don't toggle `addons.unknownsources`** — irrelevant to direct-extract and it
   pops a warning.
4. **Skip `optional="true"` deps** — Kodi installs them on-demand (this is why
   Google Drive was being pulled via resolveurl).
5. **Install-then-disable** an unwanted REQUIRED dep (The Loop → Dailymotion):
   keeps the dep check satisfied, survives the app's updates; don't patch manifests.
6. **Platform-correct binaries** — detect the platform tag at runtime
   (`system.platform_tag()`); pick the matching official-repo `<platform>`/`<path>`
   entry. Never hardcode.
7. **Closure** — walk `requires/import` recursively, deps before dependents, skip
   `xbmc.*`/`kodi.*`; highest-version-wins across third-party repos, official
   preferred for shared `script.module.*`.
8. **Self-uninstall** = delete your own dir (basename-guarded), let the restart
   finalise. **Restart** platform-correct (`RestartApp()` desktop / `Quit()`
   Android). Keep the library installed.
9. A **repository** must not carry `xbmc.python.script`; a one-shot utility
   self-uninstalls; a shared lib is `xbmc.python.module` — all to avoid a
   permanent home tile.
10. Estuary skin settings: use `Skin.SetBool(...)` (in-memory, survives shutdown);
    a direct `settings.xml` write is clobbered on shutdown.
11. **The closure resolver SKIPS the `127.0.0.1` proxy** (`repos.py`). So any
    first-party / GitHub-only add-on the resolver can't see — `script.module.pvr.artwork`
    (b-jesch GitHub-only) and our own `script.tony7bones.modv2plus` — must be
    **DIRECT-extracted** (and its non-proxy deps pulled from official) BEFORE the
    closure resolve, never left to the resolver (it would report them "missing").
12. **Skin activation order matters:** set `lookandfeel.skin` **LAST**, immediately
    before the restart. A long gap between the skin-set and the restart lets Kodi's
    "Keep this skin?" safety timeout silently revert it to stock Estuary (a real
    bug the fresh-Kodi test caught). Also rescan + settle + **enable** a
    freshly-extracted skin first, or Kodi rejects the skin setting outright.
13. **The modv2plus boot service auto-applies the patch** once MOD V2 is the active
    skin after the restart — the patch can't run before the skin is live, and the
    Setup add-on is already gone by then. Don't try to apply the patch from Setup.
14. **Wipe-and-test on a real fresh Kodi is mandatory** before shipping the
    one-shot — it catches integration bugs (skin-revert, proxy-invisible deps,
    enable-before-set) that unit tests with mocked `xbmc*` cannot.

## Golden rules — release

→ all in `docs/playbooks/release-and-deploy.md`

- **Path A — `script.*` / `script.module.*` add-on:** edit `addon.xml` version +
  news → `python3 _tools/generate_repo.py` → commit regenerated files → `git push`.
  NOT deploy.py.
- **Path B — `repository.tony7bones` (single-branch):** `python3 _tools/deploy.py --news "…"`
  — it syncs the 4 version locations on `main` (the main `addon.xml` is also the
  proxy self-update source), builds deterministically, commits main, tags,
  pushes `main + tag`, forces a Pages build, verifies live.
- **Add a served add-on:** edit the single `repository.json`
  (`addons/repository.tony7bones/resources/`); for a mirrored third-party repo drop
  its `addon.xml`/zip under `addons/hosted/<id>/` with `"branch": "main"` +
  `asset_prefix` `.../{ref}/addons/hosted/{id}/`, then `deploy.py`.
- **Pages gotcha:** Pages often skips the build → live-verify times out.
  `deploy.py` now forces a build automatically; by hand:
  `gh api --method POST repos/tony7bones/tony7bones.github.io/pages/builds`, then
  poll the root zip for HTTP 200. (Add-on zips + `addons/hosted/**` come from
  raw.githubusercontent — instant; only the installer zip rides Pages.)
- **`virtual-repo` is retired** — single branch now; do not write to it.
- **Determinism:** `generate_repo.py` excludes `__pycache__`; if a zip churns by
  mtime, commit → regenerate → `git commit --amend --no-edit` → confirm a second
  regenerate is clean.
- Gates: `.githooks/pre-push` (tests, ruff, staleness, consistency, per-add-on
  version bump). CI validates on `main` only, never commits. `docs/**` + `.claude/**`
  are outside the CI path filter.

## Golden rule — verification

→ `docs/playbooks/local-kodi-verification.md`

- Kodi runs locally (`~/Library/Application Support/Kodi/`, log at
  `~/Library/Logs/kodi.log`); drive headless via JSON-RPC at
  `http://localhost:8080/jsonrpc`.
- **HONEST verification.** "Ran with no ImportError" is NOT proof — an add-on can
  run and show an empty menu. Prove: non-empty `Files.GetDirectory`, a browsable
  submenu, installed+enabled+**origin set** in `Addons33.db`, and the rendered
  menu via `TakeScreenshot`. Read the log for the real cause; don't guess.

## Restore points

Latest known-good (3.0 one-shot, live): `perfectly-working-2026-06-06` and the
rollback safety net `main-rollback-2026-06-06`. Older: `clean-setup-1.0.17`,
`perfectly-working-2026-06-04`. Make a tag for any known-good state before risky work.
