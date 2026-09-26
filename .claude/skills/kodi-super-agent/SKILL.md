---
name: kodi-super-agent
description: >-
  Kodi Super Agent Developer for the Tony.7.Bones repository
  (tony7bones.github.io). Load when working anywhere in this repo: bumping
  repository.tony7bones, editing the static catalog manifest
  (_tools/catalog.json), building/deploying the static site, adding a hosted
  third-party mirror, debugging the local Kodi 21 Omega install, or verifying
  behaviour on the real local Kodi. Triggers on Kodi add-on release / static
  catalog / GitHub Pages / verification work in this project.
---

# Kodi Super Agent Developer

Operating guide for the Tony.7.Bones Kodi repository. This repo is a STATIC
Kodi add-on repository served by GitHub Pages; there is no on-box service and
no proxy engine. Read the matching playbook in `docs/playbooks/` before acting
on a rule below - they carry the WHY and the exact code locations.

## Orientation (read first)

- Project overview + architecture: repo-root `CLAUDE.md` + `README.md`.
- **What it is:** a static Kodi repository at `https://tony7bones.github.io/`.
  The add-on `repository.tony7bones` (3.0.0) is a normal static-only repository
  add-on: its `addon.xml` declares ONE `<dir>` pointing at
  `https://tony7bones.github.io/static/addons.xml` (+ `.md5` + a `zip="true"`
  datadir). Kodi reads metadata and zips from that static tree as plain files.
  NO `xbmc.service`, NO `127.0.0.1` proxy, NO `repository.github` engine.
- **The static catalog** (`/static/`): `addons.xml` + `addons.xml.md5` + per
  add-on zips and materialized art under `/static/<id>/`. Currently 28 entries
  (verify: `python3 -c "import json;print(len(json.load(open('_tools/catalog.json'))))"`).
  Built in CI by `_tools/build_site.py` -> `_tools/static_catalog.py` from the
  manifest `_tools/catalog.json`, then deployed via GitHub Pages.
- **Two source trees:**
  - `dropbox/` is the pristine human canvas (hand-authored `repositories/
    media/ iptv/ rss/`, NEVER generated files). The build mirrors it 1:1 to the
    repo ROOT, which Pages serves at the bare URL `https://tony7bones.github.io/`
    (the Kodi File Manager source). The mirror honors `.gitignore`, so a
    secret-bearing file (e.g. `dropbox/iptv/instance-settings*.xml`) stays local
    and never reaches the served tree.
  - `addons/` holds the add-on source, built zips, `addons.xml`, and the
    mirrored third-party-repo trees under `addons/hosted/<id>/`. Not listed at
    the bare URL.
- **Live add-ons:**
  - `addons/repository.tony7bones/` - the static-only repository add-on (3.0.0).
  - `addons/script.ezmaintenanceplusplus/` was DELETED 2026-07-20 (`08d9a3d`).
    Do not recreate it and do not resurrect the deleted full-source copy.
  - **Our own add-ons have NO copy in this repo at all** (since 2026-09-26):
    `script.ezmaintenanceplusplus` (source `~/Code/moquette/kodi/ezmpp`,
    `moquette/kodi-ezmpp`), `skin.estuary.pov` and `service.tvos.pythonfix`
    (source `~/Code/moquette/kodi/estuary-pov`, `moquette/kodi-estuary-pov`).
    `_tools/static_catalog.py` resolves each from its latest GitHub release at
    build time (`v{version}` for ezmpp; the namespaced `{id}-v{version}` for
    the estuary-pov pair) and takes `addon.xml` and art from the zip.
    `plugin.video.pov` (not ours) is resolved the same way from upstream's
    `packages/addons.xml` (`upstream_index`). Fix bugs and add tests in the
    sibling repo; a version bump pushed there IS the release, its CI dispatches
    this hub, nothing is bumped here. A `git status` / "commits to push"
    question about the skin or EZM++ almost always resolves in the OTHER repo.
    EZM++ triage: `~/Code/moquette/kodi/.claude/skills/apple-tv/SKILL.md`.
- **Single branch - `main` only**, served by GitHub Pages.
- **Retired - do NOT describe as live** (all deleted): the virtual proxy engine
  (`127.0.0.1:61234`, `repository.github`); the whole Setup add-on family
  (`script.tony7bones.bootstrap`, the shared library `script.module.tony7bones`,
  the skin patch `script.tony7bones.modv2plus`) and everything they did (the
  modular Setup, Express/Guided wizards, per-device `.env` model, in-Kodi IPTV
  apply, MOD V2 skin install/activation); and the proxy release tooling
  (`deploy.py`, `check_consistency.py`, `release.py --proxy`, the shared-library
  "lockstep"). Historical records live under `docs/plans/` and
  `docs/incident-*.md` - read them for context, never as current state.
- **Extracted:** the IPTV builder `_tools/build_iptv.py` moved to its own
  private repo `moquette/iptv` on 2026-07-17 and was removed here
  (`make_custom_m3u.py` followed it out 2026-09-26, untested and uncalled).
  `TASKS.md` was deleted 2026-07-21; there is no tracker, `git log` is the
  fact. The device provisioner `_tools/provision-kodi.sh` (self-declared
  BROKEN since 2026-07-19) and the adb helper `_tools/firetv.sh` were deleted
  2026-09-26; the meta-root `.claude/scripts/firetv-deploy.sh` is the live
  adb helper.

## Golden rules - release

-> `docs/playbooks/release-and-deploy.md`

- **The only add-on released here is `repository.tony7bones`.** Bump it by
  hand: raise the `version` attribute and prepend a `<news>` line in
  `addons/repository.tony7bones/addon.xml`, run `generate_repo.py`, commit the
  source and the generated output together, push `main`. The bump is ENFORCED
  by `check_versions.py` (pre-push hook, and CI against the push's `before`
  SHA): a push whose add-on source changed without a version increase is
  blocked. The automatic `release.py` (bump + news + commit) was deleted
  2026-09-26 with its 30s of sandbox tests; nothing ran it. Every other served
  add-on is resolved at build time and bumped in its own repo.
- **On push, CI builds and deploys the static site** (`.github/workflows/pages.yml`):
  build -> deploy to Pages -> `verify_live_site.py` fetches the catalog + md5 +
  zips through the exact public URLs Kodi uses and fails loud on any mismatch.
  A red CI never deploys; the site keeps serving the last known-good version.
- **Add or change a served add-on:** edit the manifest `_tools/catalog.json`.
  For a mirrored third-party repo, drop its `addon.xml`/zip under
  `addons/hosted/<id>/` and add its `catalog.json` entry (`static_catalog.py`
  classifies each entry: first-party build / hosted mirror / hybrid / streamed /
  release-asset). A `release-asset` entry and a `hybrid` entry with
  `upstream_index` get NO hosted directory: the build resolves them
  (`metadata_resolved_at_build`). Then release.
- **Determinism:** every zip is byte-reproducible (sorted members, 1980
  timestamps); `generate_repo.py` excludes `__pycache__`/`.ruff_cache`/etc. If a
  zip churns, regenerate -> commit -> confirm a second regenerate is clean. A
  non-deterministic zip trips the CI staleness gate.
- **Canvas-only changes** (`dropbox/` edits, no add-on release): `python3
  _tools/publish_canvas.py -m "..."` (commit + push; the CI deploy generates the
  served mirror; refuses to publish credential-like content unless
  `--allow-secrets`). `--dry-run` first.
- **Gates:** `.githooks/pre-push` (pytest, ruff, generate_repo staleness,
  `check_versions.py` per-add-on version bump, best-effort `sync_share.py` on
  main, which now mirrors only the share's `repositories/`). CI is ONE push
  workflow, `pages.yml`: on push it re-runs tests/lint/staleness + the
  version-bump gate, then builds, deploys and verifies live; on the daily cron
  and on `repository_dispatch` it skips the source gates and runs the artifact
  gates only. It has no path filter and NEVER commits back
  (`generate_repo.yml`, which duplicated it, was deleted 2026-09-26).
  `ci_failure_alert.yml` opens an owner-assigned issue on a red run;
  `pages_source_guard.yml` keeps the Pages source on "workflow". All three run
  on `ubuntu-26.04`.

## Golden rules - install mechanics (Kodi 21 Omega, general knowledge)

-> `docs/playbooks/kodi-install-mechanics.md`

These are hard-won Kodi facts that still apply to any install/verify work on a
box, even though the Setup add-on that used to encode them is retired:

- **Kodi clobbers direct settings writes - a general class**
  (-> `docs/playbooks/kodi-settings-clobber.md`). A live component (skin, PVR
  client) holds settings in memory and flushes at lifecycle events, so a direct
  file write gets clobbered OR an in-memory `Skin.SetBool` is lost on a first
  boot (it only flushes on a CLEAN shutdown). For `pvr.iptvsimple` INSTANCE
  settings, write only inside a PVR-disabled window (disable -> settle -> write
  -> re-enable), or a live client flushes stale defaults over your file on
  shutdown.
- **pvr.iptvsimple instance settings cannot be set via JSON-RPC** -
  `Settings.SetSettingValue` reaches only CORE Kodi settings; instance settings
  live only in `addon_data/pvr.iptvsimple/instance-settings-<N>.xml`.
- **Kodi's VFS can silently return empty reads** for a local file a different,
  non-VFS writer produced (confirmed on tvOS) - read a local source with plain
  Python I/O, never `xbmcvfs` on `special://`
  (-> `docs/playbooks/kodi-vfs-cannot-read-foreign-local-files.md`).
- **Restart is platform-specific:** desktop Kodi self-restarts (`RestartApp`);
  on Fire TV / Android and tvOS, `Quit()` only CLOSES - the user must reopen.

## Golden rule - verification

-> `docs/playbooks/local-kodi-verification.md`

- Kodi runs locally (`~/Library/Application Support/Kodi/`, log at
  `~/Library/Logs/kodi.log`); drive it headless via JSON-RPC at
  `http://localhost:8080/jsonrpc`.
- **HONEST verification.** "Ran with no ImportError" is NOT proof - an add-on
  can run and show an empty menu. Prove: non-empty `Files.GetDirectory`, a
  browsable submenu, installed + enabled in the add-on DB, and the rendered menu
  via `TakeScreenshot`. Read the log for the real cause; don't guess.
- **After a static release, verify from the consumer seat:** confirm
  `/static/addons.xml` + `.md5` and the changed zip URLs answer 200 with matching
  bytes (this is exactly what the CI `verify_live_site.py` job automates).

## Standing owner rules - device work (non-negotiable)

- **Always foreground Kodi on Fire devices before driving it:**
  `am start -n org.xbmc.kodi/.Splash` (idempotent). A backgrounded Kodi still
  answers JSON-RPC, but key events and screencaps hit the launcher - a silent
  false-verify.
- **Never run old code on a device.** Before any device run, install the CURRENT
  add-on from the live repo (or push the working-tree code) - a stale add-on on
  the box invalidates the whole verify.
- **Device runs are SYNCHRONOUS.** Drive a real box step-by-step in the current
  session and watch each step land; don't fire-and-forget.
- **Independent review before "done".** Any phase is declared done only after an
  independent QA + architecture review; self-verification is never sufficient.

## Restore points

Make a tag for any known-good state before risky work. The current static-only
state ships `repository.tony7bones` 3.0.0. Older pre-static/pre-modular tags
(`main-pre-modular-2026-06-10`, `perfectly-working-2026-06-06`,
`main-rollback-2026-06-06`) predate the static conversion and the add-on family
nuke - use them only to inspect history, not as a rollback target for the
current static repo.
