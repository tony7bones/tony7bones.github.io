---
name: kodi-super-agent
description: >-
  Kodi Super Agent Developer for the Tony.7.Bones repository
  (tony7bones.github.io). Load when working anywhere in this repo: releasing an
  add-on with release.py, editing the static catalog manifest
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
  add-on zips and materialized art under `/static/<id>/`. Currently 26 entries
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
  - `addons/script.ezmaintenanceplusplus/` - a LEGACY-COMPAT stub (`addon.xml` +
    a built zip, listed in the legacy `addons/addons.xml`), kept so an old engine
    bundle that referenced this path still resolves. The real source is in the
    sibling repo `~/Code/moquette/kodi/ezmpp`; the actual served
    metadata mirror is `addons/hosted/script.ezmaintenanceplusplus/` (below). Do
    not resurrect the deleted full-source copy here.
  - **One `addons/hosted/<id>/` entry is a metadata-only mirror of OUR OWN
    add-on**, with source in a sibling repo: `script.ezmaintenanceplusplus`
    (`~/Code/moquette/kodi/ezmpp`). The catalog points its `assets.zip`
    at that repo's GitHub Release asset. Fix bugs and add tests in the
    sibling repo; only bump the hosted metadata + re-release here. A
    `git status` / "commits to push" question about the skin or EZM++ almost
    always resolves in the OTHER repo. EZM++ triage:
    `~/Code/moquette/kodi/.claude/skills/apple-tv/SKILL.md`.
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
- **Still present, pending extraction (active P1, see `TASKS.md`):** the IPTV
  builder `_tools/build_iptv.py` (+ `make_custom_m3u.py`) and the device
  provisioner `_tools/provision-kodi.sh` predate the static conversion and are
  scheduled to move to a private repo. They are not part of the static release
  path; leave them alone unless working the extraction task.

## Golden rules - release

-> `docs/playbooks/release-and-deploy.md`

- **One command for EVERY add-on: `python3 _tools/release.py`.** The static
  repository add-on releases the SAME way as any other; there is no separate
  proxy path. The tool detects what changed vs `origin/main` (the shared
  `release_detect.changed_addons`, the SAME detector the pre-push gate uses),
  computes the bump (MINOR default), drafts + PREPENDS the `<news>`, regenerates
  deterministically, runs the script-side consistency gate, and commits
  `chore(release): ...` **on the branch**, then STOPS. NO hand-edited
  `addon.xml` / news / tests.
  - Flags: `--dry-run` / `--patch` / `--minor` / `--major` / `--version X.Y.Z` /
    `--addon <id>` / `--news "id=line"` / `--push` (opt-in) / `check`.
  - Idempotent (a re-run with no new source edit is a no-op, never double-bumps);
    refuses when behind origin or at the 9.9.9 single-digit ceiling. Add-ons are
    independent - there is no shared library, so a change to one never forces a
    bump of another. An add-on already on a legacy date-stamped scheme (EZM++'s
    `2026.07.x`) is compared within that scheme (loose, Kodi-comparable), never
    forced onto single-digit `X.Y.Z`.
- **On push, CI builds and deploys the static site** (`.github/workflows/pages.yml`):
  build -> deploy to Pages -> `verify_live_site.py` fetches the catalog + md5 +
  zips through the exact public URLs Kodi uses and fails loud on any mismatch.
  A red CI never deploys; the site keeps serving the last known-good version.
- **Add or change a served add-on:** edit the manifest `_tools/catalog.json`.
  For a mirrored third-party repo, drop its `addon.xml`/zip under
  `addons/hosted/<id>/` and add its `catalog.json` entry (`static_catalog.py`
  classifies each entry: first-party build / hosted mirror / hybrid / streamed /
  release-asset). Then release.
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
  main). CI (`generate_repo.yml`) re-runs tests/lint/staleness + the version-bump
  gate on `main` and NEVER commits back. `docs/**` + `.claude/**` are outside
  the CI path filter.

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
