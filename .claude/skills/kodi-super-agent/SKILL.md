---
name: kodi-super-agent
description: >-
  Kodi Super Agent Developer for the Tony.7.Bones repository
  (tony7bones.github.io). Load when working anywhere in this repo on Kodi
  add-on tasks — installing add-ons via the Setup script, building/editing the
  script.module.tony7bones shared library or the bootstrap Setup,
  releasing any add-on with release.py (script.* add-ons or the
  repository.tony7bones proxy via --proxy), adding an entry to repository.json, debugging the local
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
- The four first-party add-ons (shipped versions on `main` — auto-derived from
  the manifests; `release.py` keeps them bumped, the gates verify it):
  - `repository.tony7bones` **2.2.1** — the virtual proxy repository (local
    `127.0.0.1:61234` server; released via `release.py --proxy`, which delegates
    to `deploy.py`'s transaction).
  - `script.module.tony7bones` **1.5.0** — shared LIBRARY (`xbmc.python.module`,
    hidden); holds all the generic install machinery incl. `install_selection`
    plus the modular `setup/` layers (`foundation` / `iptv` / `addons`, `env`,
    `probes`).
  - `script.tony7bones.bootstrap` **1.8.0** — "Tony.7.Bones Setup", the
    **modular** Setup. `run()` reads the per-device env from the ORDERED env
    sources and routes: **no env anywhere → the Guided wizard** (`run_guided({})`
    — with an "Install everything with defaults" one-tap escape equal to the old
    no-env Express); env + `SETUP_MODE=guided` → the Guided wizard (multi-gate,
    per-gate restarts, Model A: each gate leaves a complete working box, env
    survives until Finish, Finish self-uninstalls); env + any other/no
    `SETUP_MODE` → unattended **Express** (`run_express` — repos + apps + curated
    video + MOD V2 skin install/activate + base-box config, one summary, one
    restart, self-uninstall). The three layers are ALSO independently runnable
    (`run_foundation` / `run_iptv` / `run_addons`), each re-entrant.
  - `script.tony7bones.modv2plus` **1.4.8** — "Estuary MOD V2+" skin patch. Has a
    **boot service** (`service.py`) that auto-applies the patch the first time
    MOD V2 is the active skin (and re-applies after a MOD V2 update), plus a
    manual Apply/Restore chooser + in-tab buttons for hand use. 1.4.7 added
    first-boot look-settings persistence (writes `settings.xml` directly; the
    boot service is settings-aware).
- **Current track — `no-computer-setup`** (plan: `docs/plans/no-computer-setup.md`;
  live state: `TASKS.md`). N1 (no-env→wizard routing + ordered env sources) is
  RELEASED to `main` (1.6.0/1.3.0, 2026-06-10). **N1.1 is committed on the branch,
  UNRELEASED:** the canonical `_T7B` device root + the persistent device-resident
  master env + the no-env scaffold (live-proven on the Office Fire TV). Next: N2,
  the on-box config collector. The modular-setup rewrite itself is SHIPPED —
  `docs/plans/modular-setup.md` is the historical record.
- **Retired — do not reference:** the standalone `script.tony7bones.video` (its
  install logic is folded into the shared library as `install_selection`), and
  `script.tony7bones.modv2.patch` (replaced by `script.tony7bones.modv2plus`).
- Structure: `dropbox/` is the pristine human canvas, mirrored 1:1 to the repo
  ROOT and served at the bare URL `https://tony7bones.github.io/` (the Kodi File
  Manager source). `addons/` holds add-on source + built zips + `addons.xml` +
  `hosted/` and is what the proxy fetches via raw.githubusercontent.
  `generate_repo.py` compiles `dropbox/` → root and `addons/` → zips.
- **Per-device `.env` config:** one `.env.<device>` per box drives weather
  (5 locations + keys), IPTV (multi-provider `IPTV_<N>_*` blocks), RSS, and
  device name/web/settings-level. **THREE first-class delivery modes** (owner
  contract): (1) the adb provisioner derives + pushes `tony7bones.env`;
  (2) a self-contained, device-resident MASTER `.env.<device>` placed at the
  device root by any means (no adb); (3) no env → the Guided wizard (Setup
  scaffolds the comment-disabled master template for fill-in-and-re-run; N1.1).
  - **Device roots (N1.1, RELEASED to `main` — bootstrap 1.7.0 / library 1.4.0):**
    the owner PLACES the master `env.<device>` (dot-optional) at the BRAND ROOT
    `/storage/emulated/0/_T7B/`; the STAGING tree `/storage/emulated/0/_T7B/kodi/`
    (layout `backups/ iptv/ media/
repositories/ rss/ scripts/`) is one level below. The old
    `/storage/emulated/0/kodi/tony.7.bones/` root is a read-only LEGACY
    fallback — read last, NEVER written (no push, no scaffold).
  - **Env-source order** (`setup/env.py box_env_paths`): pushed derived
    `tony7bones.env` (canonical staging → legacy) → device-resident
    MASTER `env.*` (brand root → staging → legacy, sorted) → profile-local
    persisted env. Derived-before-master: a fresh push outranks the standing
    identity.
  - **The MASTER is PERSISTENT — never delete it.** `deletable_env_paths`
    structurally excludes every master; terminal ops delete only the derived
    pushes + the profile-local env. A Kodi wipe-and-redo must keep working off
    the same master file forever.
  - The committed placeholder template is `.env.device.example` (the only
    tracked `.env*`).

## Golden rules — install (Kodi 21 Omega)

→ all in `docs/playbooks/kodi-install-mechanics.md`

1. **Never `InstallAddon(...)` from a script** — it pops a blocking modal and
   deadlocks. Install by direct download+extract → `UpdateLocalAddons()` →
   JSON-RPC `Addons.SetAddonEnabled`. (No JSON-RPC install method exists on Omega.)
2. **Stamp `origin`** into `Addons<NN>.db` after enabling + enable the source
   repos. Blank origin = "unknown source" → The Loop modal-locks, POV menu is empty.
3. **Never toggle `addons.unknownsources` at RUNTIME** — direct-extract doesn't
   need it and a live toggle pops a warning. The **provisioner** instead
   pre-seeds `unknownsources=true` (+ `updatemode=1`) into `guisettings.xml`
   while Kodi is DOWN — a pre-boot file seed, not a runtime toggle.
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
10. **Kodi clobbers settings writes — a general class**
    (→ `docs/playbooks/kodi-settings-clobber.md`). A live component (skin,
    PVR client) holds settings in memory and flushes at lifecycle events, so a
    direct file write gets clobbered OR an in-memory set gets lost. Three known
    instances, two mechanisms:
    - Estuary skin bools: `Skin.SetBool(...)` is in-memory and only flushes on a
      CLEAN shutdown — right before an orderly restart, LOST on a first boot.
      modv2plus 1.4.7 therefore writes `settings.xml` directly for look settings
      (the settings-aware boot service reconciles); the home-trim applies BOTH
      mechanisms.
    - **pvr.iptvsimple instance settings: write them only inside the
      PVR-DISABLED config window** (`_pause_pvr_for_config` /
      `_resume_pvr_after_config` in `tony7bones.setup.iptv`: disable → settle →
      write → re-enable in a `finally`) — a live client otherwise flushes stale
      in-memory defaults over your write on shutdown. The re-enable forces a
      re-read, so fresh clients start from YOUR file.
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
14. **Wipe-and-test on a real fresh Kodi is mandatory** before shipping Setup —
    it catches integration bugs (skin-revert, proxy-invisible deps,
    enable-before-set) that unit tests with mocked `xbmc*` cannot.

## Provisioning (per-device, pre-boot)

→ `docs/playbooks/firetv-stick-scoped-storage-provisioning.md`

- **`_tools/provision-kodi.sh <device>`** reads `.env.<device>`, wipes the box,
  and seeds `guisettings.xml` (web server, device name, settings level,
  `addons.unknownsources=true`, `addons.updatemode=1`) **before Kodi starts** —
  an offline file seed, never a runtime toggle (see install rule 3). It then
  derives + pushes `tony7bones.env` to `BOX_ENV_PATH` (under the canonical
  `_T7B/kodi/` root on the `no-computer-setup` branch) and **ABORTS pre-Setup
  if the env push fails** — a no-env launch opens the Guided wizard, which
  this unattended script must not drive.
- **Fire OS 11 Stick relocation:** a non-rooted Fire OS 11 Stick can't run Kodi
  out of `Android/data`. A per-device `KODI_DATA_PATH` outside `Android/data`
  triggers relocation to writable `/sdcard` via `xbmc_env.properties`
  (`xbmc.data=/sdcard/kodi_data`) + an appops `MANAGE_EXTERNAL_STORAGE` grant +
  a first-launch retry. All 5 boxes are provisioned this way.

## IPTV — two halves (shipped)

→ `docs/playbooks/iptv-channel-customization.md`

- **Host half — `_tools/build_iptv.py`** (provisioner step 4b, or by hand:
  `python3 _tools/build_iptv.py --env .env.<device> --out iptv-build/<device>`).
  Per `IPTV_<N>_*` env block: fetch the m3u OR synthesize one via the Xtream
  `player_api` (pvr.iptvsimple Omega has NO native Xtream mode; some panels
  block `get.php`), apply the groups grammar (`SOURCE > Display Label | sort`),
  favorites (multi-group tagging, `id:` pins, dead-icon healing), and emit
  per provider: `<Token>.m3u` + `customTVGroups-<Token>.xml` +
  `instance-settings-<N>.xml` into **gitignored** `iptv-build/<device>/`. The
  provisioner pushes that dir to the device `iptv/` staging (under the
  canonical `_T7B/kodi/` root on the branch; legacy root read as fallback) and
  appends **`IPTV_STAGING_DIR`** to `tony7bones.env` (no default — present iff
  staged). A device-resident master gets the same key injected at read time iff
  its sibling `iptv/` dir exists (`derive_master_env`).
- **In-Kodi half — `apply_iptv`** (`tony7bones.setup.iptv`): installs the pvr
  backend or fails loud, then INSIDE the PVR-disabled window consumes staging
  per provider (parse-based, side-files validated, `m3uPath` rewritten to the
  translated absolute path), falling back per-provider to the direct-env
  enforce. One pvr.iptvsimple INSTANCE per provider (`instance-settings-<N>.xml`
  - identity keys); legacy single-instance keys = provider 1.
- **Staged artifacts carry creds** (every channel URL embeds user/pass) — they
  live only in gitignored `iptv-build/` and on the box; `test_secret_leak.py`
  bans any tracked `*.m3u`.
- Verify IPTV honestly: JSON-RPC `PVR.GetChannelGroups` + `PVR.GetChannels`
  (with `"properties":["icon"]`) counts vs the builder's, AND restart-survival
  across a clean shutdown (the clobber class only shows there).

## Golden rules — release

→ all in `docs/playbooks/release-and-deploy.md`

- **One command for BOTH paths: `python3 _tools/release.py`.** It detects what
  changed, computes the bump, drafts+prepends news, raises the lockstep,
  regenerates, gates, commits. NO hand-edited `addon.xml` / news / `<import>` /
  tests (the version tests are de-pinned to relational asserts).
- **Mode A — `script.*` / `script.module.*` add-on (default):**
  `python3 _tools/release.py` → minor-bump every changed add-on, auto-news,
  lockstep raise (library bump auto-raises + bumps every dependent in one
  commit), regen, script-side consistency gate, commit **on the branch**, STOP.
  `--dry-run` / `--patch` / `--major` / `--version X.Y.Z` / `--addon <id>` /
  `--news "id=line"` / `--push` (opt-in) / `check`. Idempotent (re-run = no-op,
  never double-bump); refuses behind-origin or at the 9.9.9 ceiling.
- **Mode B — `repository.tony7bones` proxy:** `python3 _tools/release.py --proxy
--news "…"` (auto-routed when the proxy is the only changed add-on). It IS the
  push — **delegates to `deploy.py`'s proven transaction** (not a reimplementation;
  `deploy.py` still works identically and `npm run deploy:*` still call it): syncs
  the 3 version locations on `main` (the main `addon.xml` is also the proxy
  self-update source), builds deterministically, commits main, tags, pushes
  `main + tag`, forces a Pages build, verifies live. `--minor`/`--major`/
  `--version`/`--dry-run`/`--no-push`.
- **Add a served add-on:** edit the single `repository.json`
  (`addons/repository.tony7bones/resources/`); for a mirrored third-party repo drop
  its `addon.xml`/zip under `addons/hosted/<id>/` with `"branch": "main"` +
  `asset_prefix` `.../{ref}/addons/hosted/{id}/`, then `release.py --proxy`.
- **Pages gotcha:** Pages often skips the build → live-verify times out. The proxy
  transaction forces a build automatically; by hand:
  `gh api --method POST repos/tony7bones/tony7bones.github.io/pages/builds`, then
  poll the root zip for HTTP 200. (Add-on zips + `addons/hosted/**` come from
  raw.githubusercontent — instant; only the installer zip rides Pages.)
- **`virtual-repo` is retired** — single branch now; do not write to it.
- **Determinism:** `generate_repo.py` excludes `__pycache__`; if a zip churns by
  mtime, commit → regenerate → `git commit --amend --no-edit` → confirm a second
  regenerate is clean.
- Gates: `.githooks/pre-push` (tests, ruff, staleness, consistency, per-add-on
  version bump). CI validates on `main` only (incl. the per-add-on version-bump
  gate `check_versions.py`), never commits. `docs/**` + `.claude/**`
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

## Standing owner rules — device work (non-negotiable)

- **Always foreground Kodi on Fire devices before driving it:**
  `am start -n org.xbmc.kodi/.Splash` (idempotent). Backgrounded Kodi still
  answers JSON-RPC, but key events and screencaps hit the launcher — a silent
  false-verify.
- **Never run old code on a device.** Before any device run, push the CURRENT
  working-tree add-on code to the box (or install from the live repo when
  testing the production path) — a stale add-on on the box invalidates the
  whole verify.
- **Device runs are SYNCHRONOUS.** Drive a real box step-by-step in the current
  session and watch each step land; don't fire-and-forget or background a
  device sequence.

## Restore points

Pre-modular-merge `main` (the shipped 3.0 one-shot state):
`main-pre-modular-2026-06-10`. Hardware-proven 3.0 one-shot:
`perfectly-working-2026-06-06`; rollback safety net `main-rollback-2026-06-06`.
Current repo-add-on release: `v2.2.1`. Older: `clean-setup-1.0.17`,
`perfectly-working-2026-06-04`. Make a tag for any known-good state before
risky work.
