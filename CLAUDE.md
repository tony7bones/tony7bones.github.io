# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repo is

A GitHub Pages site (`tony7bones.github.io`) that hosts a Kodi add-on repository. The site is static — no bundler, no runtime. Python tooling under `_tools/` generates everything; `package.json` is only a script-runner wrapper.

The repository add-on, `repository.tony7bones`, is a **virtual repository** built on i96751414's `repository.github` engine: once installed in Kodi it runs a local HTTP proxy (`127.0.0.1:61234`) that streams add-on metadata and zips live from GitHub at runtime, driven by a `repository.json` manifest. There are no committed per-add-on zips for the third-party repos it lists.

**Install URL (must stay constant): `https://tony7bones.github.io/`** (the root). The root `index.html` is **generated** and lists ONLY the canvas folders (`repositories/ media/ iptv/ rss/`) for file-manager browsing — a clean 1:1 of `dropbox/`. The installer `repository.tony7bones-<version>.zip` is still **served at the root** (the proxy self-update fetches it there) but is **deliberately not listed** in the bare-URL view; users install it by browsing into `repositories/`, where the generator injects a copy. Cache-busting comes ONLY from the versioned zip _filename_ — never from versioned paths, because Kodi cannot follow a moving base URL.

### Two source trees: `dropbox/` (canvas) and `addons/` (add-on tree)

The repo has two pristine, committed source trees, each with a different job:

- **`dropbox/`** — the owner's **pristine human canvas**. It holds ONLY hand-authored installable content (`repositories/` third-party repo installer zips, `media/`, `iptv/`, `rss/`) and NEVER any generated files (no `index.html`, no checksums). The build **mirrors `dropbox/` 1:1 to the repo ROOT**, which is what GitHub Pages serves at the bare URL `https://tony7bones.github.io/`. Pointing Kodi's File Manager at the bare URL therefore shows exactly the canvas: `repositories/ media/ iptv/ rss/` plus the install zip and a generated Kodi index per folder. The mirror **honors `.gitignore`**, so a secret-bearing source file (e.g. `dropbox/iptv/instance-settings*.xml`) lives in the canvas for local use but is never copied into the served tree or any listing.
- **`addons/`** — the machine/add-on tree. It holds the first-party add-on source, the proxy source at `addons/repository.tony7bones/`, the built per-addon zips, `addons.xml`/`.sha256`/`.md5`, and the mirrored third-party-repo trees under `addons/hosted/<id>/`. The virtual proxy fetches add-on metadata and zips from `main` via raw.githubusercontent (`.../main/addons/...` and `.../main/addons/hosted/<id>/`). The `addons/` tree is NOT listed at the bare URL.

### Single branch — `main` only

Everything lives on `main` and the proxy fetches everything from `main` via raw.githubusercontent. `main` is served by GitHub Pages and holds the root installer zip(s), the generated root `index.html`, the served canvas (mirrored from `dropbox/`), the `addons/` tree (add-on source + the proxy source at `addons/repository.tony7bones/` + the mirrored third-party-repo trees under `addons/hosted/<id>/`), and all `_tools/`.

A proxy release bumps the version in one place — `addons/repository.tony7bones/addon.xml` — which is **both** the installed-addon metadata and the proxy's self-update version source. `python3 _tools/release.py --proxy` does this atomically and pushes `main + tag` (delegating to the proven `_tools/deploy.py` transaction — see "Releasing" below).

> The `virtual-repo` branch is **retired** (the single-branch migration moved its `hosted/<id>/` trees to `addons/hosted/` on main and consolidated the self-update source into the main `addon.xml`). It may still exist as a fallback but is **unreferenced** by all shipped manifests and tooling — do not add anything to it. `hybrid-repo` is an abandoned experiment — ignore it.

### First-party add-ons (current)

Besides the proxy, the repo ships two first-party Setup/library add-ons plus the Estuary MOD V2+ skin patch — **four** first-party add-ons in total (counting the proxy). Current shipped versions on `main`: `repository.tony7bones` 2.2.1, `script.tony7bones.bootstrap` 1.7.0, `script.tony7bones.modv2plus` 1.4.8, `script.module.tony7bones` 1.4.0.

- `repository.tony7bones` — the virtual proxy repository (runs the local `127.0.0.1:61234` server).
- `script.module.tony7bones` — a Python **library** (`xbmc.python.module`, invisible on the home screen) holding the shared install machinery (HTTP fetch, addons.xml index load/parse/merge, the dependency-closure resolvers, zip extract, enable/disable, add-on `origin` stamping, source-repo enabling, the curated-video installer `install_selection()`, self-uninstall, restart, platform detection). The Setup `<requires>` it, so Kodi auto-installs it from the repo.
- `script.tony7bones.bootstrap` — "Tony.7.Bones Setup", the **modular** Setup (1.7.0). The shipped `run()` reads the per-device env once (from the ORDERED env sources — see the per-device `.env` model below) and routes: **NO env anywhere → the Guided wizard** (`run_guided({})` — the remote-only no-computer user lands in the wizard, which carries an "Install everything with defaults" one-tap escape equal to the old no-env Express); env present with `SETUP_MODE=guided` → the Guided wizard (`run_guided` — multi-gate, per-gate restarts, Model A lifecycle: each gate leaves a complete working box, the env survives until Finish, Finish self-uninstalls); env present with any other/no `SETUP_MODE` value → **Express** (`run_express`) — the one-tap unattended path, behavior-identical to the pre-modular one-shot: it composes the three layers (Foundation / Add-ons / IPTV), installs the base repos + apps plus the curated video add-ons, **installs AND activates the Estuary MOD V2 skin** (the MOD V2+ patch auto-applies after the restart via modv2plus's boot service — see below), applies the base-box configuration, shows one summary, restarts once, then self-uninstalls. The three layers are ALSO independently runnable (`run_foundation` / `run_iptv` / `run_addons`), each re-entrant and each leaving a complete working box.
- `script.tony7bones.modv2plus` — "Estuary MOD V2+", the lean patch that customizes `skin.estuary.modv2` (gear-menu reorder, a "Tony.7.Bones MOD V2+" Skin Settings category with per-item toggles, crisp white nav wordmark, thin clock, Outline HD weather icons, plain Power/Settings/Search backgrounds). It ships a **boot service** (`service.py`, `xbmc.service` extension) that auto-applies the patch once MOD V2 is the active skin AND it is not already patched, and re-applies after a MOD V2 skin update overwrites the patched files with stock. As of 1.4.7 the boot service is also **settings-aware**: the look settings (`show_weatherinfo`, `WeatherIcons`→Outline HD, `enable_power/settings/search_background`, `powermenu_list`) are written **straight to `settings.xml` on Apply** — because `Skin.SetBool`/`SetString` only flush on a CLEAN shutdown, so a first boot lost them — and the service re-applies any that are missing. **Manual Apply / Restore still exist** (the in-skin category buttons and a chooser; Restore confirms first). Built FRESH from the current omega source each release; replaced the retired `script.tony7bones.modv2.patch`. Full dev cycle + lessons: `docs/playbooks/modv2plus-dev-cycle-and-lessons.md`.

> The standalone `script.tony7bones.video` ("Video Add-ons Setup") add-on has been **removed**. Its install logic was folded into the shared library as `install_selection(selected, official_base, disable_ids, dialog, log)`, which the Setup now calls directly to install the curated video add-ons unattended.

### What the base Setup does after installing (`script.tony7bones.bootstrap/default.py`)

`run()` installs the base repos + apps, the curated video add-ons (`_install_video`), then the Estuary MOD V2 skin (`_install_skin`). After that, before the single end-of-setup restart, it applies a sequence of **base-box configuration** steps — each defensive (logged, never aborts the run), set before the restart so Kodi re-reads them:

- `_add_file_sources()` — merge File-Manager sources into `sources.xml` (deduped).
- `_trim_home_menu()` — hide all but TV / Add-ons / Favourites / Weather on stock Estuary. Because `Skin.SetBool` only flushes on a CLEAN shutdown, the toggles are written directly into `settings.xml` so they survive the restart (the in-memory set backs it up) — same lesson modv2plus 1.4.7 encodes for its look settings.
- `_configure_box()` — weather + interface prefs, now driven by the **per-device `.env`** (see below): provider → `weather.multi`, RSS ticker on, top-bar weather (`Skin.SetBool(show_weatherinfo)`), then `_copy_device_files()` + `_ensure_iptv_custom_tv_groups(box_env)`. It reads the per-device env from the ORDERED env sources (see the per-device `.env` model below — provisioner-pushed `tony7bones.env` first), then applies it via `_apply_weather_from_env` / `_ensure_iptv_custom_tv_groups(box_env)` / `_apply_rss_from_env`; at the terminal op (Express completion / Guided Finish) the **deletable** envs — the derived pushes and the profile-local env — are removed so no machine-derived secret lingers, while the device-resident MASTER `.env.<device>` is **never deleted**. Weather locations (up to 5), the Weatherbit/OWM keys, IPTV custom groups + m3u/EPG, and RSS feeds all come from the env — the location is **env-driven, NOT a hardcoded Sacramento constant** (note `loc1_url` is the field weather.multi actually fetches by, NOT lat/lon). (The IPTV half of this lives in the shared library's `tony7bones.setup.iptv` layer — see "IPTV is two halves" below — and `_configure_box`'s legacy IPTV slot runs inside the same PVR-disabled config window.)

  **Per-device `.env` model.** One `.env.<device>` per box is the source of truth for that box's weather, IPTV, RSS, and device name/web/settings-level — either a gitignored copy in the repo (the provisioner path) or a device-resident MASTER on the box itself. There are **THREE first-class delivery modes** (owner contract): (1) the **adb provisioner** derives a per-device `tony7bones.env` and pushes it to `BOX_ENV_PATH`; (2) a **self-contained, device-resident MASTER** — the user's own `.env.<device>` placed (downloader app, USB, share — no adb) at the device root, read with provisioner-parity derivation (`derive_master_env`: `DEVICE_IP` dropped, `IPTV_STAGING_DIR` injected iff the sibling `iptv/` staging exists) and **NEVER deleted** (`deletable_env_paths` excludes every master structurally — a Kodi wipe-and-redo works forever off the same file); (3) **no env anywhere → the Guided wizard**, and Setup **scaffolds** the comment-disabled master template `env.<device-name>` (no leading dot, the owner's convention; from the bundled `.env.device.example` resource, placeholders only, never overwrites) at the BRAND ROOT for the user to fill in and re-run. The **brand root** is `/storage/emulated/0/_T7B/` — where the owner PLACES the device-resident master `env.<device>` (dot-optional) and where Setup scaffolds it; the **staging tree** `/storage/emulated/0/_T7B/kodi/` (layout: `backups/ iptv/ media/ repositories/ rss/ scripts/`) sits one level below; the old `/storage/emulated/0/kodi/tony.7.bones/` root is a read-only **LEGACY fallback** (read last, never written). `BOX_ENV_PATH=/storage/emulated/0/_T7B/kodi/tony7bones.env`. The **env-source order** (`setup/env.py box_env_paths`): the pushed derived `tony7bones.env` (canonical staging → legacy) → the device-resident MASTER `env.*` candidates (brand root → staging → legacy root, sorted) → the profile-local persisted env (the Phase-N2 collector's home). Derived-before-master because a fresh provisioner push is a deliberate provisioning act that outranks the standing identity. Only the derived pushes + the profile-local env are terminal-deletable. **Shipped:** both the routing + ordered-env-sources generalization (N1) AND the `_T7B` brand root + the persistent device-resident master + the no-env scaffold (N1.1) are **released to `main`** — N1 as bootstrap 1.6.0 / library 1.3.0 (2026-06-10), N1.1 as bootstrap 1.7.0 / library 1.4.0 (2026-06-10, merge `4ce11ec`; live-proven end-to-end on the Office Fire TV off the device-resident master alone, which survived untouched). The committed `.env.device.example` is the **only** tracked `.env*` — a placeholder template (`.gitignore` un-ignores it, and `test_secret_leak.py` allowlists it via `_EXAMPLE_ENVS`).

**Skin install + activation (`_install_skin`).** The closure resolver SKIPS our `127.0.0.1` proxy (`repos.py`), so two add-ons it cannot see are direct-extracted first: `script.module.pvr.artwork` (b-jesch's GitHub-only module, a hard skin requirement; its `requests`/`simplecache` deps come from the official repo) AND our own first-party `script.tony7bones.modv2plus` (version resolved live via `_latest_zip_url`, plus its Outline HD weather-icon dep from official). The rest of the MOD V2 skin closure (skin + skinshortcuts + image.resource.select) is installed via `install_selection([SKIN_ID])` from the installed repos. Then everything direct-extracted is rescanned, settled, and **enabled** so the skin is a registered, enabled choice. `lookandfeel.skin` is set **LAST, in `run()` immediately before the restart** — NOT inside `_install_skin` — because a long gap between the skin-set and the restart lets Kodi's "Keep this skin?" safety timeout silently revert it to stock Estuary. The restart boots into MOD V2; modv2plus's boot service then auto-applies the patch (the patch can only run with MOD V2 active, by which point Setup is gone).

**Curated video add-ons** (`VIDEO_APPS`): POV, The Loop, Sports HD, YouTube. `plugin.video.dailymotion_com` is **install-then-disabled** (`VIDEO_DISABLE_AFTER`) because The Loop declares it as a required import nobody here uses — installing satisfies the dep check, disabling means it never runs and survives Loop updates with no re-patching. (Umbrella was dropped.)

**Restart is platform-specific.** Desktop Kodi self-restarts (`RestartApp`). On Fire TV / Android, Kodi cannot self-restart, so Setup prompts the user to close Kodi and reopen it; on reopen MOD V2 is the active skin and the modv2plus service applies the patch.

**Provisioner (`_tools/provision-kodi.sh <device>`).** A one-command, pre-Setup box bring-up over adb. It reads `.env.<device>`, wipes Kodi, then seeds `guisettings.xml` **before Kodi starts** (web server, device name, settings level, `addons.unknownsources=true`, `addons.updatemode=1`), and derives + pushes the per-device `tony7bones.env` to `BOX_ENV_PATH` for the bootstrap to consume (since N1.1 the push target is under the canonical `_T7B/kodi/` staging root; never the legacy root). Since N1 it **ABORTS pre-Setup on a failed env push** — a no-env launch now opens the Guided wizard, which this unattended script must not drive. For a **non-rooted Fire OS 11 Stick** (adb can't write the `Android/data` sandbox), set a per-device `KODI_DATA_PATH` pointing OUTSIDE `Android/data` (e.g. `/sdcard/kodi_data/.kodi`): the provisioner then relocates Kodi data to writable `/sdcard` via `/sdcard/xbmc_env.properties` (`xbmc.data=/sdcard/kodi_data`) + appops `MANAGE_EXTERNAL_STORAGE`, and auto-retries the first-launch settings bounce. Method doc: `docs/playbooks/firetv-stick-scoped-storage-provisioning.md`. All 5 boxes are provisioned (Bedroom, Office, Shield, Travelstick, Travelstick 2).

**Onboarding self-creates the device tree.** Setup CREATES the canonical `_T7B/kodi/{backups,iptv,media,repositories,rss}` staging tree if it does not already exist on the box — `run()` calls `tony7bones.setup.env.ensure_device_dirs()` ONCE, EARLY (before any env read or config) on EVERY entry path, so it covers Express AND Guided AND a no-env wizard box (a box the adb provisioner never touched still gets its folders). Idempotent (`makedirs(..., exist_ok=True)`, per-dir `isdir` short-circuit), fully guarded/non-fatal (a read-only fs or off-Kodi desktop where `/storage` can't exist is logged + swallowed), and it NEVER creates or touches the master `.env.<device>` (the scaffold owns that). The five subdirs are the single source of truth `DEVICE_STAGING_SUBDIRS` (mirrors the canonical layout in `docs/directory_structure.txt`); the provisioner `mkdir -p`s the SAME five (belt-and-suspenders for the computer path). NOTE: because onboarding now always creates an EMPTY `iptv/`, `derive_master_env` injects `IPTV_STAGING_DIR` only when that dir is NON-EMPTY (real staged artifacts) — an empty `iptv/` must not make a `DEVICE_IP`-only master look configured.

**Device→userdata file convention.** `DEVICE_FILE_COPIES` copies user-placed files from the device path `/storage/emulated/0/_T7B/kodi/{rss,iptv}/…` (canonical root, N1.1 — it ALSO reads the legacy `/storage/emulated/0/kodi/tony.7.bones/{rss,iptv}/…`, canonical first) into `userdata/` (RssFeeds.xml) and `userdata/addon_data/pvr.iptvsimple/…` (instance-settings-1.xml, channelGroups/customTVGroups-\*.xml). Each copy is **guarded** (no-ops if the source is absent, so desktop runs skip cleanly), **creates dest dirs, and overwrites**. The real copy only happens on the device; on the dev Mac only the guarded-skip path runs live — the copy logic is proven by unit tests, not live verification (state this honestly). The per-device `tony7bones.env` and the device-resident master live at the **same** device root; RSS / IPTV / weather are driven by the env, while `DEVICE_FILE_COPIES` still handles any user-placed device files. The device `iptv/` dir is ALSO where the provisioner stages the HOST-BUILT IPTV artifacts (see below).

**IPTV is two halves (shipped — Express composes the in-Kodi half via the IPTV layer, and `run_iptv` runs it standalone):**

- **Host half — `_tools/build_iptv.py`** (run by the provisioner, step 4b, or by hand): per `IPTV_<N>_*` env block it fetches the provider playlist (**m3u** mode) or **synthesizes** one via the Xtream `player_api` (**xtream** mode — pvr.iptvsimple Omega has NO native Xtream connection and some panels block `get.php`), applies the full curation grammar (`SOURCE > Display Label | sort` group selection/relabel/sort, `IPTV_<N>_FAVORITES` via multi-group tagging, dead favorite-icon healing), and emits three artifacts per provider (`<Token>.m3u`, `customTVGroups-<Token>.xml`, `instance-settings-<N>.xml`) into gitignored `iptv-build/<device>/`. The provisioner pushes the dir to the device `iptv/` staging and appends **`IPTV_STAGING_DIR`** to the derived `tony7bones.env` (no default — the key exists iff staging landed).
- **In-Kodi half — `apply_iptv`** (`tony7bones.setup.iptv` in the shared library): installs the pvr backend (or fails loud), then — **inside a PVR-disabled config window** — consumes the staged artifacts per provider (parse-based, validates side-files, rewrites `m3uPath` to the translated absolute path), falling back per-provider to the direct-env enforce. One `pvr.iptvsimple` **instance** per `IPTV_<N>_*` provider (`instance-settings-<N>.xml` + per-provider `customTVGroups-*.xml` + the `kodi_addon_instance_*` identity keys); the legacy single-instance keys map to provider 1, byte-compatible with shipped boxes. Full playbook: `docs/playbooks/iptv-channel-customization.md`.

**Non-obvious Kodi constraints encoded here (don't relearn them the hard way):**

- **pvr.iptvsimple _instance_ settings cannot be set via JSON-RPC** — `Settings.SetSettingValue` reaches only CORE Kodi settings. Instance settings (TV group mode, custom-groups file, m3u/EPG) live ONLY in `addon_data/pvr.iptvsimple/instance-settings-<N>.xml` (one per `IPTV_<N>_*` provider; the legacy single-instance keys map to provider 1), read at startup.
- **A live PVR client CLOBBERS direct instance-settings writes** — on shutdown it flushes its stale in-memory defaults back over the file (this shipped an unconfigured box once). Write inside the **PVR-disabled config window** (`_pause_pvr_for_config` / `_resume_pvr_after_config`: disable → settle → write → re-enable in a `finally`, which forces a re-read). This is one instance of a general class (with the `Skin.SetBool` / modv2plus look-settings lessons) — the full pattern: `docs/playbooks/kodi-settings-clobber.md`.
- **Hiding a single PVR channel group (e.g. "All channels") is NOT automatable from Setup** — the flag is `channelgroups.bIsHidden` in the PVR DB (`userdata/Database/TV<N>.db`), and that row only exists AFTER pvr.iptvsimple syncs channels post-restart; no JSON-RPC/core setting toggles it. It stays a one-time manual step (PVR & Live TV → Channels → Group manager).

The proxy serves add-ons from its **baked** `resources/repository.json` (read locally by `lib/service.py`), not `addons/addons.xml`. To add/change a served add-on, edit the single `repository.json` at `addons/repository.tony7bones/resources/` (for a mirrored third-party repo, drop its `addon.xml`/zip under `addons/hosted/<id>/` and point `asset_prefix` at `.../{ref}/addons/hosted/{id}/` with `"branch": "main"`) and release the proxy. (Note: the `repository.peno64` entry legitimately keeps `/repo/` in its URLs because that is peno64's OWN upstream repo layout — not our `addons/` tree.)

> Detailed operating guidance lives in the playbooks and the agent skill:
>
> - `docs/playbooks/kodi-install-mechanics.md` — install on Omega without blocking prompts (direct-extract + `SetAddonEnabled`, origin stamping, optional/required deps, platform binaries, self-uninstall, Estuary skin/home-menu, file sources).
> - `docs/playbooks/release-and-deploy.md` — the two release paths + the GitHub Pages skip-build gotcha + determinism.
> - `docs/playbooks/local-kodi-verification.md` — drive the real local Kodi; **honest** verification (prove non-empty `GetDirectory` + rendered menu, not just "no ImportError"; incl. the PVR/IPTV recipes — group/channel counts, icon audit, restart-survival).
> - `docs/playbooks/kodi-settings-clobber.md` — **the "Kodi clobbers direct settings writes" class** (three known instances: Estuary skin bools, modv2plus look settings, pvr.iptvsimple instance settings) and the two fix mechanisms (write-direct-vs-clean-shutdown; disable-the-consumer-around-the-write).
> - `docs/playbooks/kodi-vfs-cannot-read-foreign-local-files.md` - Kodi's VFS can silently return empty reads (never an exception) for a local file a DIFFERENT, non-VFS writer produced, even though `xbmcvfs.Stat()` on it reports the correct size the whole time (confirmed on tvOS/Apple TV, script.ezmaintenanceplusplus's backup copy); the fix reads a local source with plain Python I/O instead of `xbmcvfs`, never the reverse.
> - `docs/playbooks/iptv-channel-customization.md` — the env-driven IPTV curation pipeline (two halves: host `build_iptv.py` + in-Kodi apply; m3u vs xtream; groups/favorites grammar; icon healing; honest stream verification).
> - `docs/playbooks/one-shot-and-architecture.md` — the first-party add-on architecture and the one-shot flow.
> - `docs/playbooks/modv2plus-dev-cycle-and-lessons.md` — **MOD V2+ patch: the ADB-on-real-Fire-TV dev cycle + hard-won lessons** (Mac ≠ device; build from current omega; the `WeatherIcons` skin-string mechanism; default-on opt-out flags; logo wordmark-vs-mark; JSON-RPC limits; XBTF extraction; safety).
> - `docs/playbooks/firetv-adb-dev.md` — command-level runbook for driving the Office Fire TV over ADB + JSON-RPC (`_tools/firetv.sh`).
> - `docs/playbooks/firetv-stick-scoped-storage-provisioning.md` — **provision a non-rooted Fire OS 11 Stick over adb** via the Jocala/adbLink data-relocation trick (`xbmc_env.properties` → `/sdcard/kodi_data`) and the provisioner's auto-detected Fire-OS mode (`KODI_DATA_PATH`).
> - `.claude/skills/ezm-backup-doctor/SKILL.md` - triage guide for script.ezmaintenanceplusplus backup/restore copy failures (size mismatch, VfsCopyError, the local-read VFS bug, the NFS port-baking bug, the settle race).
> - `docs/playbooks/quick-backup-test-provisioning.md` - get a freshly wiped Kodi box ready to install and run an add-on (e.g. EZ Maintenance++) without the full curated Setup or any manual permission/rename friction; a documented plan (not yet a script) built on `provision-kodi.sh`'s proven guisettings-seed mechanism.
> - `.claude/skills/kodi-super-agent/SKILL.md` — distilled agent operating guide.
> - `docs/plans/modular-setup.md` — the design + phase log of the modular "0-1-2" Setup rewrite (**MERGED to `main` 2026-06-10 — this is the shipped Setup**). Historical record + the contract; the no-computer-setup track continues in `docs/plans/no-computer-setup.md`.
> - `docs/plans/` (the rest) — historical design docs (implemented).

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

# Publish canvas-only changes (dropbox/ edits) WITHOUT a proxy release:
# regenerate, commit, push main. Refuses to publish credential-like content to
# the public site unless --allow-secrets. Use this, NOT deploy.py, for canvas.
python3 _tools/publish_canvas.py -m "Add foo repo zip to canvas"   # npm run publish
python3 _tools/publish_canvas.py -m "..." --dry-run                # npm run publish:dry

# Release ANY add-on — one command (see "Releasing" below)
python3 _tools/release.py --dry-run                 # script.* add-ons: preview the plan
python3 _tools/release.py                            # script.*: bump+news+lockstep+commit
python3 _tools/release.py --proxy --news "..."       # the repository.tony7bones proxy
```

Test files map to what they cover (all tests import the add-on `default.py` under **mocked Kodi modules** — `run()` is `__main__`-guarded, so importing is side-effect-free, and the install/resolve logic is exercised directly with fake `xbmc*`):

| Test file                | Covers                                                                                                                    |
| ------------------------ | ------------------------------------------------------------------------------------------------------------------------- |
| `test_bootstrap.py`      | `script.tony7bones.bootstrap` (base Setup + the unattended one-shot, incl. the curated video step)                        |
| `test_module.py`         | `script.module.tony7bones` (shared install library, incl. `install_selection`)                                            |
| `test_modv2plus.py`      | `script.tony7bones.modv2plus` (the Estuary MOD V2+ skin patch + the auto-apply boot service)                              |
| `test_proxy.py`          | `repository.tony7bones` proxy engine (version math, manifest validators, tag/URL resolution, cache, platform)             |
| `test_deploy.py`         | `deploy.py` / `release_lib.py` (proxy release; sandbox end-to-end with a bare remote)                                     |
| `test_release.py`        | `release.py` (the unified release tool: script.\* bump/news/lockstep + the `--proxy` delegation to deploy.py)             |
| `test_release_detect.py` | `release_detect.py` (the shared `changed_addons` detector — tool/gate agreement)                                          |
| `test_check_versions.py` | the per-add-on version-bump gate                                                                                          |
| `test_generate_repo.py`  | the generator (zips, indexes, canvas mirror, determinism)                                                                 |
| `test_publish_canvas.py` | `publish_canvas.py` (the canvas-only publish path: staged-diff parse + the secret guard)                                  |
| `test_secret_leak.py`    | no secret artifact/value reaches the tracked tree (allowlists `.env.example` / `.env.device.example` via `_EXAMPLE_ENVS`) |

## Releasing

> **Restore points.** The pre-modular-merge `main` (the shipped 3.0 one-shot state, bootstrap 1.4.0 / library 1.1.3 / modv2plus 1.4.7) is tagged `main-pre-modular-2026-06-10`; the hardware-proven 3.0 one-shot state is `perfectly-working-2026-06-06`; the pre-3.0 `main` is `main-rollback-2026-06-06`; the current repository-add-on release is `v2.2.1`. Current shipped `script.*` versions on `main`: bootstrap 1.8.0 / library 1.5.0 / modv2plus 1.4.8 (read live from the manifests — never hand-maintained). Use these to roll back if a release regresses the box.

**`python3 _tools/release.py` is THE release command for BOTH paths** (full detail in `docs/playbooks/release-and-deploy.md`). It detects what changed, computes the next version, drafts the news, raises the lockstep, regenerates, gates, and commits — **no hand-edited `addon.xml`, no hand-written `<news>`, no hand-raised `<import>`, no hand-edited tests.** Every release still MUST bump the version (Kodi auto-upgrades by version number only, so same-version byte changes silently break upgrades) — the tool computes the correct bump, it never skips it. The bump rule is enforced automatically and in CI (`check_versions.py` runs in both the pre-push hook and CI on main).

The one tool routes between two **modes**:

- **The `script.*` / `script.module.*` add-ons** (`script.module.tony7bones`, `script.tony7bones.bootstrap`, `script.tony7bones.modv2plus`) — the default mode:

  ```bash
  python3 _tools/release.py                 # minor-bump every changed add-on, commit on the branch, STOP
  python3 _tools/release.py --dry-run       # show the plan (incl. WHICH files changed), change nothing
  python3 _tools/release.py --patch         # patch instead of the minor default (or --major / --version X.Y.Z)
  python3 _tools/release.py --addon script.module.tony7bones --version 1.6.0
  python3 _tools/release.py --news "script.tony7bones.bootstrap=Fix first-boot race"  # override the drafted news
  python3 _tools/release.py --push          # also push the branch (default: commit only, keep the merge→main flow)
  python3 _tools/release.py check           # the script-side consistency gate only
  ```

  Detects changed add-ons vs `origin/main` (the **shared** `release_detect.changed_addons`, the SAME detector the pre-push gate uses — they can never disagree), computes the next version (MINOR default; single-digit, monotonic, 9.9.9 ceiling), auto-drafts + **PREPENDS** the `<news>` (rolling cap ~6, idempotent), raises the lockstep `<import>` atomically when the library bumps (each dependent's import → new library version AND the dependent bumps, one commit; a library-scoped run auto-includes the dependent), regenerates deterministically, runs the script-side consistency gate (well-formed / single-digit / monotonic / lockstep `==`), commits `chore(release): …` on the branch, then **STOPS** (no auto-push; `--push` is opt-in). Idempotent — a re-run with no new source edit is a no-op, never a double-bump. Refuses when behind origin or at the version ceiling.

- **The repository add-on (`repository.tony7bones`)** — the virtual proxy; `--proxy` (auto-routed when the proxy is the only changed add-on):

  ```bash
  python3 _tools/release.py --proxy --news "What changed"     # patch bump (proxy default)
  python3 _tools/release.py --proxy --minor --news "..."      # or --major / --version X.Y.Z
  python3 _tools/release.py --proxy --news "..." --dry-run     # preview the plan, change nothing
  python3 _tools/release.py --proxy --news "..." --no-push     # local commit + tag only
  ```

  The proxy release **IS the push** (tag + atomic push + Pages force-build + live verify), because the self-update fetches the new zip live. `release.py --proxy` **delegates to `deploy.py`'s proven transaction** (`deploy.deploy` — the exact hardware-proven code that has shipped every proxy release; not a reimplementation): bump → build deterministically → sync the three version-bearing locations (main `addons/repository.tony7bones/addon.xml` — which doubles as the proxy self-update source — the root zip filename, and the git tag) → commit main → tag → `git push --atomic main <tag>` → force a GitHub Pages build → verify live. The root `index.html` is the bare-URL canvas listing and **deliberately does NOT list the install zip** — the consistency gate reads the shipped version from the **root zip filename** instead. Any failure before the push rolls main and the tag back. Refuses on a dirty tree, off main, behind origin, or a non-greater version. The version lives ONLY in `addon.xml`; `package.json` deliberately does not mirror it.

  `deploy.py` remains a **fully-working independent entry point** (`release.py --proxy` is a thin front door onto the identical transaction — `test_deploy.py` passes unchanged, and a parity test proves the resulting tree + remote are identical whichever entry point is used). The npm wrappers still call `deploy.py`: `npm run deploy -- --news "..."`, `deploy:dry`, `deploy:minor`, `deploy:major`, `deploy:local` (`--no-push`), `check`, `verify`.

The release tooling is split for testability: `_tools/release_lib.py` (pure version math + file transforms + the single-source-of-truth `DeployPlan`; the lockstep/news transforms `set_import_version` / `prepend_addon_news`), `_tools/release_detect.py` (the ONE shared `changed_addons` detector behind both the tool and the gate), `_tools/check_consistency.py` (the proxy 3-location gate; reused by the hook, CI, and the proxy transaction), `_tools/deploy.py` (the proxy orchestrator), `_tools/release.py` (the unified tool + the script-side consistency gate), with `_tools/test_deploy.py` / `_tools/test_release.py` / `_tools/test_release_detect.py` (unit + bare-remote sandbox e2e).

## Gates (pre-push hook)

`.githooks/pre-push` blocks a push unless tests pass, lint is clean, generated files
are up to date, the proxy's three version locations agree and are tagged
(`check_consistency.py`), and every changed add-on bumped its version
(`check_versions.py`, the per-add-on monotonic gate). Install once
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
main** — including the per-add-on version-bump gate (`check_versions.py`) on main,
so the "every changed add-on bumped" guarantee no longer lives only in the pre-push
hook. The old `.pre-commit-config.yaml` (pytest on commit) still works if installed.

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
- `write_root_index(canvas_listing)` — generates the bare-URL root `index.html` (the canvas 1:1; the install zip is served at the root but deliberately NOT listed — install via `repositories/`).
- `_inject_install_zip_into_repositories()` — copies the root proxy installer zip into the SERVED `repositories/` so it is browsable in the canvas; `dropbox/` stays pristine.
- `generate()` — orchestrates everything.

(The old `sync_dropbox`, `generate_scripts_index`, `generate_media_index`, `generate_asset_indexes`, `_styled_page`, and `_fmt_date` functions were removed, and the old "the root `index.html` is hand-crafted, never overwrite" rule is gone — the root index is now generated.)

### CI — `.github/workflows/generate_repo.yml`

Runs the full `_tools/` test suite, `ruff`, the generator + `git status --porcelain` staleness check, and the version-consistency gate (main only). **CI never commits anything back to main** — it only validates; if generated files are stale the author must run the generator (or `deploy.py`) and commit. This is why generated zips are deterministic: a non-reproducible zip would make CI flag stale files on every run. To stay deterministic the generator excludes build-time cruft dirs (`_CRUFT_DIRS`: `__pycache__`, `.ruff_cache`, `.pytest_cache`, `.mypy_cache`) from every zip/index/mirror — otherwise a lint/test cache left in an add-on source dir gets baked into the zip and silently flips CI red (this happened to `script.tony7bones.modv2plus-1.4.7.zip`, which shipped a stray `.ruff_cache/`).

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

Note: the `repository.tony7bones` add-on is the virtual proxy and is released via `python3 _tools/release.py --proxy` (which delegates to `_tools/deploy.py`'s proven transaction; running `deploy.py` directly still works identically) — single-branch: it bumps `main` and tags, then pushes `main + tag`. The "adding a new add-on / zip" steps above are for _other_ content (third-party repos, scripts, images) and do not bump `repository.tony7bones`. After any of them, the pre-push hook will run tests + lint + staleness + consistency before the push is accepted.
