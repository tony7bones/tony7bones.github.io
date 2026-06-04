---
name: kodi-super-agent
description: >-
  Kodi Super Agent Developer for the Tony.7.Bones repository
  (tony7bones.github.io). Load when working anywhere in this repo on Kodi
  add-on tasks — installing add-ons via the Setup scripts, building/editing the
  script.module.tony7bones shared library or the bootstrap/video Setups,
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
- The add-ons: `repository.tony7bones` (virtual proxy), `script.module.tony7bones`
  (shared LIBRARY, invisible), `script.tony7bones.bootstrap` ("Tony.7.Bones
  Setup"), `script.tony7bones.video` ("Video Add-ons Setup"),
  `script.tony7bones.modv2.patch` (manual-only skin patch).

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

## Golden rules — release

→ all in `docs/playbooks/release-and-deploy.md`

- **Path A — `script.*` / `script.module.*` add-on:** edit `addon.xml` version +
  news → `python3 _tools/generate_repo.py` → commit regenerated files → `git push`.
  NOT deploy.py.
- **Path B — `repository.tony7bones`:** `python3 _tools/deploy.py --news "…"` — it
  syncs the 5 version locations across both branches, builds deterministically,
  commits main + virtual-repo (worktree), tags, atomic-pushes, verifies live.
- **Add a served add-on:** edit BOTH `repository.json` copies (main `resources/` +
  virtual-repo root) then `deploy.py` so the baked manifest ships.
- **Pages gotcha:** Pages often skips the build → live-verify times out.
  `gh api --method POST repos/tony7bones/tony7bones.github.io/pages/builds`, then
  poll the root zip for HTTP 200. (Add-on zips come from raw.githubusercontent —
  instant; only the installer zip rides Pages.)
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

Tags `clean-setup-1.0.17` and `perfectly-working-2026-06-04`. Make a tag for any
known-good state before risky work.
