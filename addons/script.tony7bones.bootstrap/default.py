"""Tony.7.Bones Setup — one-tap install for a fresh Kodi box.

Installs by add-on id only. No display-name labels.

run():
  * extracts the repo installer zips (direct download)
  * installs each requested app together with its full dependency closure by
    direct download + extract, then registers + enables every add-on through
    Kodi's add-on manager so the apps actually function.
  * adds the File-Manager sources, trims the Estuary home menu, then removes
    ITSELF (run once, then disappear) so no Setup tile lingers on the home
    screen — the end-of-setup restart de-registers it cleanly. It stays in the
    Tony.7.Bones repo for one-tap reinstall whenever needed.

The shared install machinery (HTTP fetch, addons.xml index load/resolve, zip
extract, enable, self-uninstall, restart, platform detection) lives in the
script.module.tony7bones library; this file holds only the base box's own
configuration and the two base-only steps (file sources + Estuary home trim).

Why not Kodi's InstallAddon builtin: on Omega it calls a *modal* installer on
the GUI thread that pops a blocking yes/no and never returns when driven from a
script — the GUI locks. So the library resolves the dependency closure itself
from the repos' addons.xml and extracts every zip directly, then enables each
add-on — which inserts it into Kodi's installed table and makes it runnable.

No unknown-sources prompt: the script never toggles the unknown-sources setting
(it has no bearing on the direct-extract + enable path used here).

Binary (platform-specific) add-ons — e.g. pvr.iptvsimple and the inputstream.*
clients it needs — are resolved per-platform: the library detects this machine's
Kodi platform string at runtime and picks the matching official-repo entry.

This Setup also installs a curated set of video add-ons (POV, The Loop, Sports
HD, YouTube) unattended — no picker — as part of the one-tap run, with a combined
summary and a single restart. Each resolves its full dependency closure from the
source repos installed above plus the official repo; origins are stamped.

No secrets are embedded in this script.
"""

import json

# os is no longer called by THIS module's own code (the env deletes moved to
# tony7bones.setup.env.delete_box_envs in Phase N1), but the env-lifecycle tests
# reach the SHARED os module object through this module (boot.mod.os.remove —
# patching it reaches env._os.remove, the same xbmcvfs-style trick documented
# below). Keep the re-export.
import os  # noqa: F401 - shared-module patch point for tests (see above)

import xbmc
import xbmcgui

MY_ID = "script.tony7bones.bootstrap"

# ---------------------------------------------------------------------------- #
# Shared-library compatibility guard (Phase 6). REQUIRED_SETUP_API is the
# setup-API capability level this bootstrap NEEDS from script.module.tony7bones;
# the library declares the level it SHIPS (tony7bones.setup.SETUP_API). A
# too-old library paired with a too-new bootstrap (a cross-gate update skew, or
# a sideload that bypassed Kodi's <requires> check — our own direct-extract
# install path does exactly that) must fail LOUD AND HONEST at launch, never
# crash weird mid-install. The guard runs BEFORE the real library imports below
# so the failure is one honest dialog + log line + RuntimeError instead of a
# cryptic ImportError deep in a gate.
# ---------------------------------------------------------------------------- #
# Level 2 (Phase N1): run() depends on the library's ordered env-source helpers
# (tony7bones.setup.env.box_env_paths / read_first_env / delete_box_envs).
# Level 3 (Phase N1.1): the device-resident master env + scaffold helpers
# (env.deletable_env_paths / scaffold_master_env / master_env_paths).
REQUIRED_SETUP_API = 3


def _require_setup_library():
    """Verify the installed shared library carries the setup API this bootstrap
    needs. Returns silently when compatible; otherwise logs ERROR, shows ONE
    honest "update the library from the repository" dialog, and raises."""
    detail = None
    try:
        import importlib

        # A genuinely old library is missing the setup modules outright —
        # probe the newest capability surface the bootstrap depends on.
        importlib.import_module("tony7bones.setup.probes")
        from tony7bones import setup as _setup_probe

        api = int(getattr(_setup_probe, "SETUP_API", 0))
        if api >= REQUIRED_SETUP_API:
            return
        detail = "library SETUP_API {} < required {}".format(api, REQUIRED_SETUP_API)
    except Exception as e:  # noqa: BLE001 - any import failure = incompatible
        detail = "library import failed: {}".format(e)
    installed = "unknown"
    try:
        import xbmcaddon

        installed = xbmcaddon.Addon("script.module.tony7bones").getAddonInfo("version")
    except Exception:  # noqa: BLE001 - version is informational only
        pass
    xbmc.log(
        "[{}] shared library INCOMPATIBLE: {} "
        "(installed script.module.tony7bones: {})".format(MY_ID, detail, installed),
        xbmc.LOGERROR,
    )
    try:
        xbmcgui.Dialog().ok(
            "Tony.7.Bones Setup",
            "\n".join(
                [
                    "Setup needs a newer version of its shared library",
                    "(script.module.tony7bones, installed: {}).".format(installed),
                    "",
                    "Update it from the Tony.7.Bones repository,",
                    "then run Setup again.",
                ]
            ),
        )
    except Exception:  # noqa: BLE001 - the dialog must not mask the real error
        pass
    raise RuntimeError(
        "script.tony7bones.bootstrap requires a newer script.module.tony7bones "
        "({})".format(detail)
    )


_require_setup_library()

# Shared install library (script.module.tony7bones). All the generic machinery
# lives here; this file keeps only the base box's configuration + base-only steps.
from tony7bones import (  # noqa: E402 - deliberately after the compat guard
    activate_skin,
    extract_zip,
    install_selection,
    install_with_deps,
    is_installed,
    restart_kodi,
    self_uninstall,
    update_local_addons,
)
from tony7bones import enable as _enable  # noqa: E402

# Per-device .env parsing moved into the shared sublibrary (Phase 2a); re-export
# the same three names here so every existing reference and every test that
# reaches them via this module (boot.mod.parse_env / read_box_env / split_list)
# keeps working unchanged. Listed in __all__ so they are not pruned as "unused"
# (this module re-exports them, but does call read_box_env in run()).
from tony7bones.setup import env as _env_mod  # noqa: E402
from tony7bones.setup.env import parse_env, read_box_env, split_list  # noqa: E402

# The Foundation layer (skin closure + file-sources + home-trim) moved into the
# shared sublibrary (Phase 2b). The lifted bodies + the layer entry point live in
# tony7bones.setup.foundation; this module keeps thin shims (below) that delegate
# to them so every existing reference and test (boot.mod._install_skin /
# _add_file_sources / _trim_home_menu / _latest_zip_url + the SKIN_ID/PVR_ARTWORK
# constants) keeps working unchanged, and run() calls apply_foundation in the
# EXACT slot those three functions occupied.
from tony7bones.setup import foundation as _foundation  # noqa: E402
from tony7bones.setup.foundation import apply_foundation  # noqa: E402

# The ADD-ONS layer (base repos + apps install, curated video install, env-driven
# weather + RSS writers) moved into the shared sublibrary (Phase 2c). The lifted
# bodies + the layer entry point live in tony7bones.setup.addons; this module keeps
# thin re-export shims (below) that run() and _configure_box call in their EXISTING
# slots so the characterization snapshot stays byte-identical (the interleaving
# constraint: base/video install EARLY, weather/RSS config LATE in _configure_box).
# The moved bodies resolve their install primitives from the addons module globals,
# so the few run()-driven tests that stubbed the base/video path patch addons.* (the
# repointed boot.mod patches) — NO new deps-injection seam (Tech-debt ledger).
from tony7bones.setup import addons as _addons  # noqa: E402
from tony7bones.setup.addons import apply_addons  # noqa: E402

# The IPTV layer's in-Kodi CONFIG half (the pvr.iptvsimple instance-settings
# enforcement + the device→userdata file copies) moved into the shared sublibrary
# (Phase 2d). The lifted bodies + the layer entry point live in
# tony7bones.setup.iptv; this module keeps thin re-export shims (below) that
# _configure_box calls in their EXISTING slots (copy then enforce — the copy
# BEFORE the enforce so it patches the copied file) so the characterization
# snapshot stays byte-identical. These bodies touch only xbmc/xbmcvfs/os/ET (no
# monkeypatched install primitives), so a plain re-export is behaviour-identical —
# no deps-injection seam (Tech-debt ledger). NOTE: Phase 2d is CONFIG-ONLY; the
# pvr.iptvsimple INSTALL stays in the base ADDONS list (its move to the IPTV gate
# is the deliberate behaviour change reserved for Phase 3).
from tony7bones.setup import iptv as _iptv  # noqa: E402
from tony7bones.setup.iptv import apply_iptv  # noqa: E402

# Installed-state done-probes for the Guided wizard (Phase 5d). The wizard
# resumes via the box's ACTUAL state (skin active / instance file present /
# per-id is_installed) — never marker files — so a crash, a declined restart,
# or a reverted skin all self-heal by re-offering the incomplete gate.
from tony7bones.setup import probes as _probes  # noqa: E402

# Re-exported public names (env parsing now lives in tony7bones.setup.env; the
# Foundation layer entry point in tony7bones.setup.foundation; the Add-ons layer in
# tony7bones.setup.addons).
__all__ = [
    "apply_addons",
    "apply_foundation",
    "apply_iptv",
    "parse_env",
    "read_box_env",
    "run_addons",
    "run_foundation",
    "run_foundation_setup",
    "run_guided",
    "run_iptv",
    "split_list",
]

# Index bases + repo/app/video constants — MOVED to the Add-ons layer
# (tony7bones.setup.addons, Phase 2c). Re-exported here so every existing
# reference and test (boot.mod.REPO_ZIPS / ADDONS / VIDEO_APPS / OFFICIAL_BASE …)
# keeps working unchanged and there is a single source of truth.
REPO_BASE = _addons.REPO_BASE
STATIC_BASE = _addons.STATIC_BASE
OFFICIAL_BASE = _addons.OFFICIAL_BASE
PENO64_BASE = _addons.PENO64_BASE
REPO_ZIPS = _addons.REPO_ZIPS
FIRST_PARTY = _addons.FIRST_PARTY
ADDONS = _addons.ADDONS

# Estuary MOD V2 skin + the MOD V2+ patch — installed + activated by the one-shot.
SKIN_ID = "skin.estuary.modv2"
MODV2PLUS_ID = "script.tony7bones.modv2plus"
OUTLINE_HD_ID = "resource.images.weathericons.outline-hd"
# script.module.pvr.artwork is a hard requirement of the skin but is b-jesch's own
# GitHub module — not in Kodinerds/official, and the closure resolver SKIPS our
# 127.0.0.1 proxy (repos.py), so it would resolve as "missing". We direct-extract
# it (+ its requests/simplecache deps from official) BEFORE the closure resolve so
# the skin's dependency check is satisfied. The mirror is served at our Pages
# /addons/hosted/ (raw.githubusercontent equivalent for the proxy).
HOSTED_BASE = "https://tony7bones.github.io/addons/hosted"
PVR_ARTWORK_ID = "script.module.pvr.artwork"
PVR_ARTWORK_ZIP = "script.module.pvr.artwork-2.2.10.zip"
PVR_ARTWORK_DEPS = ["script.module.requests", "script.module.simplecache"]


def _log(msg, level=xbmc.LOGINFO):
    xbmc.log(f"[{MY_ID}] {msg}", level)


def _latest_zip_url(addon_id):
    """Resolve a first-party add-on's current zip URL from its static addon.xml."""
    import re
    import urllib.request

    base = f"{STATIC_BASE}/{addon_id}"
    try:
        with urllib.request.urlopen(f"{base}/addon.xml", timeout=15) as r:
            xml = r.read().decode("utf-8", "replace")
        m = re.search(r'<addon\b[^>]*\bversion="([^"]+)"', xml)
        if m:
            return f"{base}/{addon_id}-{m.group(1)}.zip"
    except Exception as e:  # noqa: BLE001
        _log(f"cannot resolve {addon_id}: {e}", xbmc.LOGERROR)
    return None


# --------------------------------------------------------------------------- #
# File-Manager sources + Estuary home-menu trim — MOVED to the Foundation layer
# (tony7bones.setup.foundation, Phase 2b). The bodies + their constants/helpers
# (REPO_SOURCE_*, FILE_SOURCES, _sources_xml_path, _make_files_source,
# ESTUARY_HIDE_SETTINGS, _estuary_settings_path, _trim_home_menu_setbool/writefile)
# now live there VERBATIM; these are thin re-export shims so every existing
# reference and test (boot.mod._add_file_sources / _trim_home_menu) keeps working,
# and apply_foundation runs them in the same slot they occupied in run(). Both
# touch only xbmc/xbmcvfs (no monkeypatched install primitives), so a plain
# re-export is behaviour-identical.
# --------------------------------------------------------------------------- #
_add_file_sources = _foundation._add_file_sources
_trim_home_menu = _foundation._trim_home_menu

# Still referenced by _configure_box's top-bar-weather guard (it only sets the
# Estuary skin bool on the stock Estuary skin) — kept here, mirrored in foundation.
ESTUARY_SKIN_ID = "skin.estuary"


# --------------------------------------------------------------------------- #
# Base box configuration — weather + interface preferences applied after the
# install, before the restart. Each step is defensive (logged, never aborts).
# --------------------------------------------------------------------------- #
# The WEATHER provider constants + the weather env-writers MOVED to the Foundation
# layer (tony7bones.setup.foundation) — weather is part of the branded look, not
# content. The RSS env-writer stays in the Add-ons layer. Re-exported here so every
# existing reference and test (boot.mod.WEATHER_ADDON / WEATHER_LOCATION /
# _apply_weather_from_env / _apply_rss_from_env / _resolve_weather_location /
# _set_weather_settings / _set_weather_location / _weather_multi_settings_path)
# keeps working unchanged. The IPTV + device-copy halves of _configure_box stay
# here (they go to apply_iptv in Phase 2d).
WEATHER_ADDON = _foundation.WEATHER_ADDON  # Multi Weather (installed by Foundation)
WEATHER_LOCATION = _foundation.WEATHER_LOCATION
_weather_multi_settings_path = _foundation._weather_multi_settings_path
_set_weather_settings = _foundation._set_weather_settings
_set_weather_location = _foundation._set_weather_location
_resolve_weather_location = _foundation._resolve_weather_location
_apply_weather_from_env = _foundation._apply_weather_from_env
_apply_rss_from_env = _addons._apply_rss_from_env
SHOW_WEATHERINFO = "show_weatherinfo"  # Estuary skin bool: weather in the top bar

# Device → userdata file copies — MOVED to the IPTV layer (tony7bones.setup.iptv,
# Phase 2d). Re-exported here so every existing reference and test
# (boot.mod.DEVICE_FILE_COPIES) keeps working unchanged and there is a single
# source of truth. _configure_box calls _copy_device_files (below) in the SAME slot
# it occupied (BEFORE the IPTV instance-settings enforce). The copy loop touches
# only xbmcvfs/os, so a plain re-export is behaviour-identical.
DEVICE_FILE_COPIES = _iptv.DEVICE_FILE_COPIES


def _set_setting(setting_id, value):
    """Set a core Kodi setting via JSON-RPC. Returns True on a clean OK."""
    resp = xbmc.executeJSONRPC(
        json.dumps(
            {
                "jsonrpc": "2.0",
                "method": "Settings.SetSettingValue",
                "params": {"setting": setting_id, "value": value},
                "id": 1,
            }
        )
    )
    return '"result":true' in (resp or "")


# --------------------------------------------------------------------------- #
# Per-device config (tony7bones.env) parsing.
# --------------------------------------------------------------------------- #
# The implementations of parse_env / read_box_env / split_list moved VERBATIM
# into the shared `tony7bones.setup.env` sublibrary (Phase 2a); they are imported
# at the top of this file and re-exported below so every existing reference (and
# every test that reaches them via `boot.mod.parse_env` / `read_box_env` /
# `split_list`) keeps working unchanged. Pure-Python + no Kodi deps; NEVER log a
# parsed value.


# The weather/RSS env-writers + their helpers (_weather_multi_settings_path /
# _set_weather_settings / _set_weather_location / _resolve_weather_location /
# _apply_weather_from_env / _apply_rss_from_env) MOVED to the Add-ons layer
# (tony7bones.setup.addons, Phase 2c) and are re-exported above. _configure_box
# calls _apply_weather_from_env / _apply_rss_from_env in the same slot they
# occupied (weather/RSS config runs LATE, after the early base/video install —
# the interleaving constraint).


# --------------------------------------------------------------------------- #
# Device→userdata file copies + the pvr.iptvsimple instance-settings enforcement
# — MOVED to the IPTV layer (tony7bones.setup.iptv, Phase 2d). The bodies +
# their constants/helper (_copy_one_device_file / _copy_device_files /
# DEVICE_FILE_COPIES / IPTV_INSTANCE_SETTINGS_SPECIAL / IPTV_TV_GROUP_MODE_* /
# IPTV_CUSTOM_TV_GROUPS_FILE_* / IPTV_TV_CHANNEL_GROUPS_ONLY_KEY /
# _set_instance_setting / _ensure_iptv_custom_tv_groups) now live there VERBATIM;
# these are thin re-export shims so every existing reference and test
# (boot.mod._copy_device_files / _ensure_iptv_custom_tv_groups / the IPTV_*
# constants) keeps working unchanged, and _configure_box runs them in the SAME
# slots they occupied (copy BEFORE the IPTV enforce). Both touch only
# xbmc/xbmcvfs/os/ET (no monkeypatched install primitives), so a plain re-export
# is behaviour-identical. Phase 2d is CONFIG-ONLY: the pvr.iptvsimple INSTALL
# stays in the base ADDONS list (its move to the IPTV gate is the deliberate
# Phase-3 behaviour change).
# --------------------------------------------------------------------------- #
# xbmcvfs is no longer referenced by THIS module's own code (the bodies that used
# it moved to the IPTV/Add-ons layers), but several tests reach the fake-Kodi
# module through this module — e.g. monkeypatch.setattr(boot.mod.xbmcvfs, "copy",
# ...) and boot.mod.xbmcvfs.translatePath(...). Re-export the SAME module object
# the moved bodies import so those patches still reach the moved code and
# boot.mod.xbmcvfs resolves unchanged. (Patching the shared module object mutates
# it everywhere it is imported, so a test patch on boot.mod.xbmcvfs.copy reaches
# iptv.xbmcvfs.copy.)
xbmcvfs = _iptv.xbmcvfs

_copy_one_device_file = _iptv._copy_one_device_file
_copy_device_files = _iptv._copy_device_files

IPTV_INSTANCE_SETTINGS_SPECIAL = _iptv.IPTV_INSTANCE_SETTINGS_SPECIAL
IPTV_TV_GROUP_MODE_KEY = _iptv.IPTV_TV_GROUP_MODE_KEY
IPTV_TV_GROUP_MODE_CUSTOM = _iptv.IPTV_TV_GROUP_MODE_CUSTOM
IPTV_CUSTOM_TV_GROUPS_FILE_KEY = _iptv.IPTV_CUSTOM_TV_GROUPS_FILE_KEY
IPTV_CUSTOM_TV_GROUPS_FILE_VALUE = _iptv.IPTV_CUSTOM_TV_GROUPS_FILE_VALUE
IPTV_TV_CHANNEL_GROUPS_ONLY_KEY = _iptv.IPTV_TV_CHANNEL_GROUPS_ONLY_KEY
_set_instance_setting = _iptv._set_instance_setting
_ensure_iptv_custom_tv_groups = _iptv._ensure_iptv_custom_tv_groups
# The IPTV layer's own PVR backend id (Phase 3a moved its install into apply_iptv);
# run_iptv's summary reads the per-backend state from the LayerResult by this id.
PVR_BACKEND_ID = _iptv.PVR_BACKEND_ID


# The per-device config the provisioner derives from the owner's master .env and
# pushes to the box. The ORCHESTRATOR (`run()`) reads it once, passes the parsed
# dict into `_configure_box`, and owns the read-then-DELETE so its secrets do not
# linger on the box — `_configure_box` is a pure consumer that never touches the
# file. (Owning the lifecycle in one coordinator is what lets a future multi-gate
# Guided flow share the env across gates instead of deleting it mid-run.)
# Phase N1: the constant MOVED to tony7bones.setup.env (single source of truth
# for the ordered env-source list); re-exported here, same value, so every
# existing reference and test (boot.mod.BOX_ENV_PATH — incl. the monkeypatched
# staging the env tests use) keeps working unchanged. N1.1: it now points under
# the CANONICAL device root /storage/emulated/0/_T7B/kodi/ (the legacy
# kodi/tony.7.bones/ push path is still read second — see env.box_env_paths).
BOX_ENV_PATH = _env_mod.BOX_ENV_PATH


# The canonical device-staging tree onboarding self-creates (N1.1+). Re-exported
# from the shared sublibrary so there is one source of truth (the constant
# mirrors docs/directory_structure.txt) and every reference / test reaches them
# via boot.mod. run() calls _ensure_device_dirs() ONCE, EARLY (before any env
# read or config), so it covers Express AND Guided AND a no-env wizard box.
DEVICE_STAGING_SUBDIRS = _env_mod.DEVICE_STAGING_SUBDIRS


def _ensure_device_dirs():
    """Create the canonical ``_T7B/kodi/{backups,iptv,media,repositories,rss}``
    tree if it does not exist on this box — idempotent, guarded, non-fatal
    (logged + swallowed where ``/storage`` cannot exist, e.g. desktop dev). Runs
    on EVERY onboarding entry path (Express + Guided + the standalone layers go
    through ``run()``), regardless of whether an env exists, so a no-computer
    wizard box still gets its folders. Resolves THIS module's ``BOX_ENV_PATH``
    late so a test's monkeypatched staging is honored. Does NOT touch the master
    env. Returns the dirs actually created (for the log)."""
    return _env_mod.ensure_device_dirs(primary=BOX_ENV_PATH, log=_log)


def _box_env_paths():
    """The ORDERED env-source candidates (Phase N1, N1.1): the provisioner's
    pushed file (``BOX_ENV_PATH`` under the ``_T7B/kodi`` staging tree — wins
    when present, so the provisioned path is byte-compatible), then the LEGACY
    push path (pre-``_T7B`` boxes), then the device-resident MASTER
    candidates (``env.*`` / ``.env.*``, dot-optional — brand root → staging
    tree → legacy root, the persistent identity, never deleted), then the
    profile-local persisted env the on-box collector
    writes (``env.PROFILE_ENV_SPECIAL``). Resolves THIS module's
    ``BOX_ENV_PATH`` global late so a test's monkeypatched staging is honored.
    The multiple-masters warning logs FILE PATHS only, never values."""
    return _env_mod.box_env_paths(
        primary=BOX_ENV_PATH, log=lambda m: _log(m, xbmc.LOGWARNING)
    )


def _deletable_box_env_paths():
    """The env candidates the TERMINAL ops may delete (N1.1 delete split):
    the derived pushes (both roots) + the profile-local collector env. The
    device-resident MASTER is NEVER deleted — wipe-and-redo must work forever
    off it."""
    return _env_mod.deletable_env_paths(primary=BOX_ENV_PATH)


def _configure_box(box_env=None):
    """Apply the base box's weather + interface preferences:
      * weather provider  -> Multi Weather (weather.addon)
      * Multi Weather location 1 -> Sacramento, CA, US (name + coords)
      * RSS news ticker   -> ON (lookandfeel.enablerssfeeds)
      * device files      -> copied from the device into userdata if present
        (guarded copies: custom RssFeeds.xml, plus pvr.iptvsimple's
        instance-settings-1.xml and customTVGroups-Network24.xml — runs here
        AFTER the base install, so pvr.iptvsimple already exists)
      * IPTV custom groups -> enforce tvGroupMode=Custom + the custom-TV-groups
        file path in pvr.iptvsimple's instance-settings-1.xml (after the copy)
      * Estuary top bar   -> show weather info (Skin.SetBool, persists on restart)

    `box_env` is the already-parsed per-device env dict (or None/{} when no env
    was pushed). It is PASSED IN by the orchestrator — `_configure_box` neither
    reads nor deletes the env file; that lifecycle belongs to `run()`.
    Defensive: any failure is logged and swallowed; never aborts the run."""
    try:
        box_env = box_env or {}
        _set_setting("weather.addon", WEATHER_ADDON)
        _set_setting("lookandfeel.enablerssfeeds", True)
        # Weather: env-driven (up to 5 resolved locations + the upgrade keys),
        # falling back to the keyless Sacramento default when no env is present.
        _apply_weather_from_env(box_env)
        # Device-copy + IPTV enforce run inside the PVR-DISABLED window (the Phase
        # 5b·1 clobber fix): both write pvr.iptvsimple's instance-settings files
        # directly, and a LIVE pvr client (installed + enabled EARLY by the base
        # step in this legacy monolith order) flushes its stale in-memory defaults
        # back over direct file writes. Guarded: a box without pvr installed
        # pauses nothing (the helpers no-op, and the resume only runs if paused).
        paused = _iptv._pause_pvr_for_config()
        try:
            # Copy the user's device files into userdata (guarded; skips missing).
            _copy_device_files()
            # IPTV from env: generate groups + inject m3u/epg, then enforce group
            # mode (gated on the groups file). Falls back to the device-copied
            # file / no-op.
            _ensure_iptv_custom_tv_groups(box_env)
        finally:
            if paused:
                _iptv._resume_pvr_after_config()
        # RSS ticker feeds from env (writes userdata/RssFeeds.xml; else no-op).
        _apply_rss_from_env(box_env)
        # The top-bar toggle is an Estuary skin bool; set it live so the restart
        # persists it (Kodi rewrites skin settings.xml from memory on shutdown).
        skin = ""
        try:
            skin = xbmc.getSkinDir() or ""
        except Exception:  # noqa: BLE001
            skin = ""
        if not skin or skin == ESTUARY_SKIN_ID:
            xbmc.executebuiltin(f"Skin.SetBool({SHOW_WEATHERINFO})")
        _log(
            "_configure_box: weather provider/location set, RSS on, "
            "device files copied if present, top-bar weather on"
        )
    except Exception as e:  # noqa: BLE001 - never abort the rest of setup
        _log(f"_configure_box failed (non-fatal): {e}", xbmc.LOGERROR)


# --------------------------------------------------------------------------- #
# Curated video add-ons — installed unattended (no picker) in the one-tap run.
# The VIDEO_APPS / VIDEO_DISABLE_AFTER constants + _install_video MOVED to the
# Add-ons layer (tony7bones.setup.addons, Phase 2c). Re-exported here so every
# existing reference and test (boot.mod.VIDEO_APPS / VIDEO_DISABLE_AFTER /
# _install_video) keeps working unchanged. _install_video resolves install_selection
# from the addons module globals; the run()-driven video tests that stubbed it patch
# addons.install_selection (the repointed boot.mod patch) — NO new deps-injection
# seam (Tech-debt ledger). run() calls _install_video in the SAME early slot.
# --------------------------------------------------------------------------- #
VIDEO_APPS = _addons.VIDEO_APPS
VIDEO_DISABLE_AFTER = _addons.VIDEO_DISABLE_AFTER
_install_video = _addons._install_video


class _BootSkinDeps:
    """The install primitives the Foundation skin step needs, resolved LIVE from
    THIS module's globals on every access. Injected into
    foundation._install_skin so a run() driven through monkeypatched
    boot.mod.install_selection / extract_zip / install_with_deps / _latest_zip_url
    routes through the patched functions — behaviour-identical to the monolith,
    which resolved those names in this module. (Late binding via __getattr__ on a
    name->global map is what lets monkeypatch.setattr(boot.mod, ...) take effect.)"""

    # name (as foundation calls it) -> (this module's global name, import default).
    # __getattr__ reads globals() FIRST so monkeypatch.setattr(boot.mod, ...) wins
    # (late binding); the import default is the captured object, present so the
    # imports are real references (ruff) and a fallback if the global is absent.
    # is_installed in particular MUST stay imported — _install_skin no-ops silently
    # without it (the ruff-fix-hook footgun the bootstrap test pins).
    _MAP = {
        "install_selection": ("install_selection", install_selection),
        "install_with_deps": ("install_with_deps", install_with_deps),
        "extract_zip": ("extract_zip", extract_zip),
        "is_installed": ("is_installed", is_installed),
        "update_local_addons": ("update_local_addons", update_local_addons),
        "enable": ("_enable", _enable),
        "latest_zip_url": ("_latest_zip_url", None),
    }

    def __getattr__(self, name):
        entry = self._MAP.get(name)
        if entry is None:
            raise AttributeError(name)
        gname, default = entry
        return globals().get(gname, default)


def _install_skin(dialog):
    """Install Estuary MOD V2 + the MOD V2+ patch — thin shim over the Foundation
    layer's lifted body (tony7bones.setup.foundation._install_skin).

    The body MOVED into the shared sublibrary (Phase 2b); this shim forwards THIS
    module's (monkeypatchable) install primitives via _BootSkinDeps so behaviour —
    including every test that patches boot.mod.install_selection / extract_zip /
    _latest_zip_url and drives run() — is identical to the monolith. Returns True
    if the skin installed; never raises. lookandfeel.skin is still set LAST in
    run() (the activate-skin invariant), not here."""
    return _foundation._install_skin(dialog, deps=_BootSkinDeps())


# The base install (repos + first-party + apps) MOVED to the Add-ons layer
# (tony7bones.setup.addons, Phase 2c). Re-exported here so every existing reference
# and test (boot.mod._install_base) keeps working unchanged. It resolves its install
# primitives (extract_zip / install_with_deps / update_local_addons / enable /
# _latest_zip_url) from the addons module globals; the run()-driven tests that
# stubbed the base path patch addons.* (the repointed boot.mod patches) — NO new
# deps-injection seam (Tech-debt ledger). run() calls _install_base in the SAME early
# slot (before video, before apply_foundation) so the interleaving is unchanged.
_install_base = _addons._install_base

# The reusable repo-install loop (extract + register + enable all REPO_ZIPS +
# FIRST_PARTY) EXTRACTED out of _install_base (Phase 5a) so the Foundation layer can
# establish ALL our repos independently — the skin closure resolves from them.
# Re-exported here so run_foundation (and any test) can reach it via boot.mod.
install_repos = _addons.install_repos


def _count_installed(result, ids):
    """How many of `ids` the layer reports installed (state != failed)."""
    return sum(1 for aid in ids if aid in result.installed)


def run_express(box_env=None):
    """The Express orchestrator — the one-shot path (``run()`` delegates here).

    Phase 3a: ``run_express`` drives the three COMPOSED layers as UNITS, in a
    dependency-correct order, and owns the terminal seam + the env lifecycle + the
    summary + the self-uninstall. This is the first deliberate behaviour change —
    the operation ORDER becomes LAYERED (each ``apply_*`` runs install+config
    together) instead of the monolith's INTERLEAVED order (base/video install EARLY,
    weather/IPTV/RSS config LATE). The NET END-STATE is unchanged (proven by the
    equivalence test in test_modular_setup.py); only the order/timing differs.

    Order rationale (dependency-correct):
      1. ``apply_addons`` — base source repos + base apps + curated video + the
         env-driven weather/RSS. Must run FIRST: the Foundation skin closure resolves
         the Estuary MOD V2 skin from the installed source repos (Kodinerds etc.), so
         the repos must exist before the skin install. A user cancel here aborts the
         whole run cleanly (no summary/uninstall/restart) — exactly the monolith's
         early-return contract.
      2. ``apply_foundation`` — the Estuary MOD V2 skin + MOD V2+ patch closure (it
         direct-extracts the proxy-invisible pvr.artwork + modv2plus first, then
         resolves the rest from the repos addons installed in step 1), then the two
         content-free base-config steps (File-Manager sources + Estuary home-trim).
         It does NOT set ``lookandfeel.skin`` — that is the orchestrator's terminal
         seam below (set LAST).
      3. ``apply_iptv`` — install pvr.iptvsimple (its INSTALL moved here from the
         base ADDONS in Phase 3a; install-or-fail-loud) + the device-file copy +
         the instance-settings enforce.

    The per-device env is read ONCE by ``run()`` and passed in here; this
    orchestrator deletes it (in ``run()``) only AFTER the last layer, so a future
    multi-gate Guided flow can share it. The skin is activated LAST (only if
    Foundation reached ``ok``) immediately before the single restart, so Kodi's
    "Keep this skin?" timeout cannot silently revert it.

    Returns the three LayerResults (addons, foundation, iptv) for inspection /
    testing; ``None`` for the layers skipped on a mid-install cancel.
    """
    box_env = box_env or {}
    dialog = xbmcgui.DialogProgress()
    dialog.create("Tony.7.Bones Setup", "Starting setup...")

    # --- Layer 2 (Add-ons): base repos + apps + curated video + weather/RSS ---
    # FIRST, because the Foundation skin closure resolves from the source repos this
    # layer installs. A cancelled base install is the only abort path (ok=False).
    addons_res = apply_addons(box_env, dialog=dialog, log=_log)
    if not addons_res.ok:
        # User cancelled mid-install: abort cleanly with NO summary, NO
        # self-uninstall, NO restart. The partial install is harmless and
        # re-running Setup completes it (the monolith's early-return contract).
        dialog.close()
        return addons_res, None, None

    # --- Layer 0 (Foundation): Estuary MOD V2 skin closure + sources + home-trim ---
    # AFTER add-ons so the source repos the skin closure resolves from exist. The
    # seam is killed here (Tech-debt ledger): the orchestrator calls the BARE form —
    # no install_skin=/add_file_sources=/trim_home_menu= injection — so the layer
    # uses its own _SkinDeps (resolved from foundation's globals).
    foundation_res = apply_foundation(box_env, dialog=dialog, log=_log)

    # --- Layer 1 (IPTV): install pvr.iptvsimple (or fail loud) + config ---
    # Its pvr.iptvsimple INSTALL moved here from the base ADDONS in Phase 3a — so in
    # a full Express run the NET installed set is unchanged (pvr still installed,
    # just via this layer). Also drives the device-file copy + instance-settings.
    iptv_res = apply_iptv(box_env, dialog=dialog, log=_log)

    # The top-bar weather toggle was an Estuary skin bool set inline in the
    # monolith's _configure_box; keep it as an orchestrator step (it persists on the
    # restart). Guard: only meaningful on the stock Estuary skin.
    skin = ""
    try:
        skin = xbmc.getSkinDir() or ""
    except Exception:  # noqa: BLE001
        skin = ""
    if not skin or skin == ESTUARY_SKIN_ID:
        xbmc.executebuiltin(f"Skin.SetBool({SHOW_WEATHERINFO})")

    dialog.close()

    skin_ok = foundation_res.ok

    # --- one combined summary (same Repos/Apps/Video/skin contract; + IPTV) ---
    repo_ok = _count_installed(addons_res, [rid for _z, rid in REPO_ZIPS])
    app_ok = _count_installed(addons_res, ADDONS)
    video_ok = _count_installed(addons_res, VIDEO_APPS)
    iptv_ok = iptv_res.ok and bool(iptv_res.installed)
    xbmcgui.Dialog().ok(
        "Tony.7.Bones Setup",
        "\n".join(
            [
                f"Repos: {repo_ok}/{len(REPO_ZIPS)}",
                f"Apps: {app_ok}/{len(ADDONS)}",
                f"Video add-ons: {video_ok}/{len(VIDEO_APPS)}",
                "IPTV: {}".format("installed" if iptv_ok else "skipped"),
                "Estuary MOD V2: {}".format("installed" if skin_ok else "FAILED"),
                "Restart will finish setup.",
            ]
        ),
    )

    # Run once, then disappear (after the summary; never raises). The shared
    # library is a hidden module add-on and is deliberately LEFT installed.
    self_uninstall(MY_ID, _log)

    # Activate MOD V2 LAST — immediately before the restart. activate_skin sets
    # lookandfeel.skin AND clicks "Yes" on Kodi's "Keep this skin?" confirm
    # (control 11 of the yes/no dialog) so the change COMMITS. Without that accept
    # the dialog defaults to revert on its timeout and the box boots stock Estuary
    # (a real Fire TV install hit exactly this). The restart then boots into MOD V2
    # and modv2plus's service auto-applies the patch.
    if skin_ok:
        activate_skin(SKIN_ID, _log)
    # ONE restart finalises every freshly extracted add-on AND the self-removal.
    restart_kodi("Tony.7.Bones Setup", _log)
    return addons_res, foundation_res, iptv_res


# IPTV env detection — MOVED to the shared sublibrary (tony7bones.setup.env,
# Phase 6) so the installed-state probes can use the same gate for
# assert_box_complete without importing the bootstrap. Semantics unchanged: an
# IPTV provider is configured when the per-device env carries a PLAYLIST SOURCE
# (``IPTV_<N>_M3U`` / ``IPTV_<N>_PORTAL`` or the single-instance ``IPTV_M3U`` /
# ``IPTV_PORTAL``) with a non-empty value; ``IPTV_EPG`` / ``IPTV_GROUPS`` alone
# do NOT count (no playlist = no channels). Re-exported here so every existing
# reference and test (boot.mod._env_has_iptv / _IPTV_PROVIDER_KEY) keeps
# working unchanged and there is a single source of truth.
_IPTV_PROVIDER_KEY = _env_mod._IPTV_PROVIDER_KEY
_env_has_iptv = _env_mod.env_has_iptv


def _foundation_core(box_env, dialog):
    """The shared Foundation install body both Foundation runners call.

    Installs ALL our source repos (incl. our own ``repository.tony7bones`` proxy repo)
    via ``install_repos``, then runs ``apply_foundation`` (the Estuary MOD V2 skin
    closure + the proxy-invisible pvr.artwork/modv2plus direct-extracts + Outline-HD +
    weather.multi + the keyboard autocomplete utility + File-Manager sources + the
    home-menu trim), then sets the top-bar weather skin bool. It does NOT set
    ``lookandfeel.skin`` and does NOT restart — the terminal seam belongs to the
    caller (``run_foundation`` / ``run_foundation_setup``), which sets the skin LAST
    and restarts ONCE so the env can be shared across an IPTV chain without a premature
    restart. Returns the Foundation ``LayerResult``.

    Factored out so ``run_foundation`` (pure skin-only) and ``run_foundation_setup``
    (skin + optional IPTV chain) share ONE install seam and can never drift apart.
    """
    box_env = box_env or {}
    # 1. ALL our source repos + our own proxy repo (plumbing) — the skin closure
    #    resolves from them, and the proxy repo is the lifeline (updates/opt-ins).
    install_repos(dialog)

    # 2. the Foundation layer: skin closure + modv2plus/pvr.artwork direct-extract +
    #    Outline-HD + weather.multi + autocomplete + File-Manager sources (incl. the
    #    .tony.7.bones proxy source) + home-trim. ZERO content. Does NOT set
    #    lookandfeel.skin (the caller's seam owns that).
    foundation_res = apply_foundation(box_env, dialog=dialog, log=_log)

    # The top-bar weather toggle is an Estuary skin bool (persists on the restart);
    # only meaningful on the stock Estuary skin — keep it as an orchestrator step.
    skin = ""
    try:
        skin = xbmc.getSkinDir() or ""
    except Exception:  # noqa: BLE001
        skin = ""
    if not skin or skin == ESTUARY_SKIN_ID:
        xbmc.executebuiltin(f"Skin.SetBool({SHOW_WEATHERINFO})")

    return foundation_res


def run_foundation(box_env=None):
    """The Foundation orchestrator — install Layer 0 ONLY (a skin-only deliverable).

    Stop here = a pristine, BRANDED Kodi with ZERO content: the Estuary MOD V2 skin
    (+ the MOD V2+ patch, applied post-restart by modv2plus's boot service), the
    skin's required dependency closure, ALL our source repositories (plumbing, not
    content), the File-Manager sources, and a trimmed home menu — and NOTHING else.

    Foundation is content-free BY CONSTRUCTION: it does NOT call ``apply_addons``
    (no base apps ezmaintenanceplus / realdebrid / weather.multi, no curated video
    POV / Loop / Sports HD / YouTube, no weather/RSS) and does NOT call ``apply_iptv``
    (no pvr.iptvsimple, no IPTV). The ONLY add-ons it installs are the skin closure
    (skin.estuary.modv2 + skinshortcuts + image.resource.select + the proxy-invisible
    script.module.pvr.artwork + our script.tony7bones.modv2plus + the Outline-HD
    weather icons) on top of the source repos.

    Order rationale (dependency-correct):
      1. ``install_repos`` — extract + register + enable ALL our source repos (the 12
         REPO_ZIPS). The Estuary MOD V2 skin closure resolves the skin + skinshortcuts
         + image.resource.select from these installed repos (Kodinerds etc.), so they
         MUST exist before the skin install. ``repository.tony7bones`` (the virtual
         proxy) is the HOST add-on shipping this Setup — already installed/running —
         and is additionally registered as the ``.tony.7.bones`` File-Manager SOURCE
         by ``apply_foundation``'s ``_add_file_sources`` below, so the proxy repo is
         fully established without re-installing the host.
      2. ``apply_foundation`` — the skin closure (it direct-extracts the proxy-invisible
         pvr.artwork + modv2plus FIRST, then resolves the rest from the repos installed
         in step 1) + the two content-free base-config steps (File-Manager sources +
         the Estuary home-trim). It does NOT set ``lookandfeel.skin`` — that is the
         terminal seam below (set LAST).
      3. set ``lookandfeel.skin`` LAST (only if Foundation reached ``ok``), then ONE
         restart, then self-uninstall (skin-only = done).

    The skin is activated LAST, immediately before the single restart, so Kodi's
    "Keep this skin?" timeout cannot silently revert it. After the restart MOD V2 is
    active and modv2plus's boot service auto-applies the patch (the Setup is gone by
    then). Returns the Foundation ``LayerResult``.
    """
    box_env = box_env or {}
    dialog = xbmcgui.DialogProgress()
    dialog.create("Tony.7.Bones Setup", "Installing Foundation...")

    # Repos (incl. our proxy repo) + the Foundation layer (skin/weather/menu/
    # autocomplete) — the shared install seam. PURE skin-only: this runner NEVER
    # touches IPTV (apply_iptv is reserved for run_foundation_setup).
    foundation_res = _foundation_core(box_env, dialog)

    dialog.close()

    skin_ok = foundation_res.ok
    # Repos are plumbing (install_repos installs them; they are not recorded in
    # foundation_res.installed, which holds the skin id). The summary reports the
    # branded-box result — skin install + "repositories + sources installed".
    xbmcgui.Dialog().ok(
        "Tony.7.Bones Setup",
        "\n".join(
            [
                "Foundation (skin-only):",
                "Estuary MOD V2: {}".format("installed" if skin_ok else "FAILED"),
                "Repositories + sources installed.",
                "Restart will finish setup.",
            ]
        ),
    )

    # Run once, then disappear (after the summary; never raises). The shared
    # library is a hidden module add-on and is deliberately LEFT installed.
    self_uninstall(MY_ID, _log)

    # Activate MOD V2 LAST — immediately before the restart (the activate-skin
    # invariant). Only when Foundation reached ok.
    if skin_ok:
        activate_skin(SKIN_ID, _log)
    # ONE restart finalises every freshly extracted add-on AND the self-removal.
    restart_kodi("Tony.7.Bones Setup", _log)
    return foundation_res


def run_foundation_setup(box_env=None):
    """Foundation + an env-gated IPTV chain — the skin-with-optional-live-TV runner.

    Composes the SAME Foundation install seam as ``run_foundation`` (``_foundation_core``
    → repos incl. our proxy repo + the skin/weather/menu/autocomplete layer) and THEN,
    **iff the per-device env carries IPTV provider values** (``_env_has_iptv`` — any
    ``IPTV_<N>_M3U`` / ``IPTV_<N>_PORTAL`` or the single-instance ``IPTV_M3U`` /
    ``IPTV_PORTAL`` / ``IPTV_EPG``), chains the IPTV layer: ``apply_iptv`` installs
    pvr.iptvsimple (+ its binary inputstream closure) and writes the instance-settings
    (custom group mode + the env's m3u/epg). With NO IPTV env it stops at the skin-only
    box — byte-identical to ``run_foundation`` (no pvr.iptvsimple, no IPTV).

    Terminal seam (shared, owned HERE — never in a layer): set ``lookandfeel.skin``
    LAST (only when Foundation reached ``ok``), restart ONCE, then self-uninstall. The
    skin is activated immediately before the restart so Kodi's "Keep this skin?"
    timeout cannot silently revert it; the single restart finalises every freshly
    extracted add-on (skin + optionally pvr.iptvsimple) AND the self-removal. The env
    is read ONCE upstream (``run()``) and shared across both the Foundation and IPTV
    layers here before any restart, so the IPTV chain is never starved.

    NOT wired into the shipped ``run()`` yet (still ``run_express``); this is a new
    entry point for the modular flow. Returns ``(foundation_res, iptv_res)`` —
    ``iptv_res`` is ``None`` when the env has no IPTV provider (the skin-only path).
    """
    box_env = box_env or {}
    dialog = xbmcgui.DialogProgress()
    dialog.create("Tony.7.Bones Setup", "Installing Foundation...")

    # Foundation install seam (repos incl. proxy + skin/weather/menu/autocomplete).
    foundation_res = _foundation_core(box_env, dialog)

    # IPTV auto-chain — ONLY when the env actually carries a provider playlist source.
    # With none, this stays a pure skin-only box (identical to run_foundation).
    iptv_res = None
    if _env_has_iptv(box_env):
        iptv_res = apply_iptv(box_env, dialog=dialog, log=_log)

    dialog.close()

    skin_ok = foundation_res.ok
    iptv_ok = bool(iptv_res and iptv_res.ok and iptv_res.installed)
    lines = [
        "Foundation:",
        "Estuary MOD V2: {}".format("installed" if skin_ok else "FAILED"),
        "Repositories + sources installed.",
    ]
    if iptv_res is not None:
        lines.append("IPTV: {}".format("installed" if iptv_ok else "skipped"))
    lines.append("Restart will finish setup.")
    xbmcgui.Dialog().ok("Tony.7.Bones Setup", "\n".join(lines))

    # Run once, then disappear (after the summary; never raises).
    self_uninstall(MY_ID, _log)

    # Activate MOD V2 LAST — immediately before the restart (the activate-skin
    # invariant). Only when Foundation reached ok.
    if skin_ok:
        activate_skin(SKIN_ID, _log)
    # ONE restart finalises every freshly extracted add-on AND the self-removal.
    restart_kodi("Tony.7.Bones Setup", _log)
    return foundation_res, iptv_res


def run_addons(box_env=None):
    """The Add-ons orchestrator — apply Layer 2 ONLY (the curated content set).

    The 0-1-2 model's "stopped at skin-only, later adds the curated content"
    story (Phase 5c): a thin standalone runner that drives the SAME ``apply_addons``
    the Express one-shot drives (the no-fork invariant) on top of an EXISTING
    Foundation box, then owns the terminal seam: honest summary → self-uninstall →
    ONE platform-aware restart. Stop here = the full box.

    Body (mirrors ``run_foundation``'s proven shape):
      1. progress dialog → ``apply_addons(box_env)`` — the base source repos + base
         apps (script.ezmaintenanceplus / script.realdebrid), the curated video
         add-ons (POV, The Loop, Sports HD, YouTube; ``plugin.video.dailymotion_com``
         install-then-DISABLED) with full dependency closures + origin stamps, the
         RSS core toggle + the env-driven RSS feeds.
      2. summary dialog — honest per-stage counts straight from the LayerResult
         (a partial failure shows as e.g. "Video add-ons: 2/4", never "success").
      3. ``self_uninstall`` then ONE ``restart_kodi`` (platform-aware: desktop
         self-restarts, Android prompts close+reopen) — the restart finalises the
         freshly extracted add-ons AND the self-removal, honoring the layer's
         ``needs_restart`` request.

    What it must NOT do (the layer invariants):
      * NO skin touch — no ``activate_skin``, no ``lookandfeel.skin``, no
        ``Skin.SetBool``. Foundation owns the active skin; re-setting it would
        re-arm Kodi's "Keep this skin?" revert timeout for no reason, and the
        top-bar weather bool belongs to Foundation (stock Estuary) / the
        modv2plus settings-aware service (MOD V2).
      * NO orchestrator-level ``install_repos`` call — Foundation owns plumbing.
        (``apply_addons``'s own base step still runs its historical idempotent
        repo loop internally; on a Foundation box every repo extract
        short-circuits. That is the layer's proven self-sufficiency, shared
        verbatim with Express — not a fork.)
      * NO ``apply_foundation`` / ``apply_iptv`` — one layer per runner.

    Foundation-missing semantics (decided, not probed): run on a box WITHOUT
    Foundation, the curated content still lands and works — ``apply_addons``'s base
    step installs the source repos itself, so the video closures resolve; the box
    simply is not branded (stock Estuary, no MOD V2/weather). No probe-and-abort:
    the layer is additive and re-entrant, and a later ``run_foundation`` completes
    the branding with no redo (re-entrancy via installed-state).

    Env lifecycle: same coordinator pattern as ``run()`` — the DRIVER reads the
    per-device env ONCE (``read_box_env(BOX_ENV_PATH)``), passes the dict in, and
    deletes the env file only after a successful (non-cancelled) run. Precondition
    for the later-opt-in story: the provisioner (or a lighter re-stage) must have
    re-pushed ``tony7bones.env`` to the box — Foundation's earlier run consumed and
    deleted the original.

    Failure semantics: a user CANCEL mid-install (``ok=False``, the only not-ok
    path in ``apply_addons``) aborts cleanly — NO summary, NO self-uninstall, NO
    restart; the partial install is harmless and a re-run completes it (the
    monolith's early-return contract, same as ``run_express``). Per-add-on install
    failures stay non-fatal: the summary reports the honest counts and the box
    still completes (restart once). Re-entry is safe by construction —
    ``extract_zip`` / ``install_selection``'s ``is_installed`` probes short-circuit
    an already-provisioned box; the disable-after set is re-applied (idempotent).

    NOT wired into the shipped ``run()`` (still ``run_express``); a new entry
    point for the modular flow. Returns the Add-ons ``LayerResult``.
    """
    box_env = box_env or {}
    dialog = xbmcgui.DialogProgress()
    dialog.create("Tony.7.Bones Setup", "Installing Add-ons...")

    # Layer 2 ONLY — the same apply_addons Express drives (no forked install
    # logic). It owns repos+apps+video install, origin stamps, the
    # install-then-disable set, the RSS core toggle + env-driven RSS feeds.
    addons_res = apply_addons(box_env, dialog=dialog, log=_log)
    if not addons_res.ok:
        # User cancelled mid-install: abort cleanly with NO summary, NO
        # self-uninstall, NO restart (the monolith's early-return contract).
        # The driver leaves the env intact so a re-run can complete the box.
        dialog.close()
        return addons_res

    dialog.close()

    # Honest summary — per-stage counts straight from the LayerResult (the same
    # Repos/Apps/Video contract as the Express summary; no IPTV/skin lines here,
    # those layers have their own runners).
    repo_ok = _count_installed(addons_res, [rid for _z, rid in REPO_ZIPS])
    app_ok = _count_installed(addons_res, ADDONS)
    video_ok = _count_installed(addons_res, VIDEO_APPS)
    xbmcgui.Dialog().ok(
        "Tony.7.Bones Setup",
        "\n".join(
            [
                "Add-ons (curated content):",
                f"Repos: {repo_ok}/{len(REPO_ZIPS)}",
                f"Apps: {app_ok}/{len(ADDONS)}",
                f"Video add-ons: {video_ok}/{len(VIDEO_APPS)}",
                "Restart will finish setup.",
            ]
        ),
    )

    # Run once, then disappear (after the summary; never raises). The shared
    # library is a hidden module add-on and is deliberately LEFT installed.
    self_uninstall(MY_ID, _log)

    # ONE restart finalises every freshly extracted add-on AND the self-removal.
    # NO skin activation here — Foundation owns the active skin (re-setting
    # lookandfeel.skin would re-arm the "Keep this skin?" revert timeout).
    restart_kodi("Tony.7.Bones Setup", _log)
    return addons_res


def run_iptv(box_env=None):
    """The IPTV orchestrator — apply Layer 1 ONLY (live TV on an existing box).

    The 0-1-2 model's "stopped at skin-only, later adds live TV" story
    (Phase 5b·3): a thin standalone runner that drives the SAME ``apply_iptv``
    the Express one-shot drives (the no-fork invariant) on top of an EXISTING
    Foundation box, then owns the terminal seam: honest summary →
    self-uninstall → ONE platform-aware restart. Stop here = branded Kodi +
    your live TV.

    Body (mirrors ``run_foundation``/``run_addons``'s proven shape):
      1. progress dialog → ``apply_iptv(box_env)`` — install pvr.iptvsimple
         (+ its binary inputstream closure, platform-resolved from the OFFICIAL
         repo) or FAIL LOUD, then — inside the PVR-DISABLED config window (the
         5b·1 clobber fix) — the guarded device-file copy and ONE
         ``instance-settings-<N>.xml`` per env provider: the HOST-BUILT staged
         artifacts first when the env carries ``IPTV_STAGING_DIR`` (curated
         playlist + display-label groups + ready instance file — the only path
         a portal-API provider can land through), per-provider fallback to the
         direct-env enforce.
      2. summary dialog — honest, straight from the LayerResult: the backend
         state plus whether instance settings were actually WRITTEN this run
         ("unchanged" when the env carries no provider or the files were
         already correct — never a false "configured").
      3. ``self_uninstall`` then ONE ``restart_kodi`` (platform-aware) — the
         restart finalises the freshly extracted backend AND the self-removal,
         honoring the layer's ``needs_restart`` request (pvr.iptvsimple reads
         instance settings at startup).

    What it must NOT do (the layer invariants):
      * NO skin touch — no ``activate_skin``, no ``lookandfeel.skin``, no
        ``Skin.SetBool``. Foundation owns the active skin; re-setting it would
        re-arm Kodi's "Keep this skin?" revert timeout for no reason.
      * NO ``install_repos`` — Foundation owns plumbing. ``apply_iptv``
        resolves its backend's platform closure straight from the OFFICIAL
        repo (``iptv.OFFICIAL_BASE``), so it needs none of our source repos;
        on a Foundation-less box the backend still installs and the config
        still lands (the box simply is not branded — same tolerant
        Foundation-missing semantics as ``run_addons``, no probe-and-abort).
      * NO ``apply_foundation`` / ``apply_addons`` — one layer per runner.

    Env lifecycle: same coordinator pattern as ``run()`` — the DRIVER reads the
    per-device env ONCE (``read_box_env(BOX_ENV_PATH)``), passes the dict in,
    and deletes the env file only after a successful (``ok``) run. PRECONDITION
    for the later-opt-in story: the provisioner (or a lighter re-stage) must
    have re-pushed ``tony7bones.env`` AND the staged ``iptv/`` artifacts to the
    box — Foundation's earlier run consumed and deleted the original env, and
    the staged curated artifacts only exist where the host build put them
    (provisioner step 4b: build → push → ``IPTV_STAGING_DIR``). No new
    transport is invented here.

    Failure semantics (``ok=False`` — the backend did not install, the ONE
    hard-failure path in ``apply_iptv``; there is NO user-cancel path through
    this layer by construction — ``install_with_deps`` never polls the
    dialog's cancel button, unlike the Add-ons layer's per-repo loop): the
    summary says FAILED and that nothing was configured (``apply_iptv`` wrote
    no instance-settings — fail-loud means no half-config), then the runner
    still self-uninstalls and restarts ONCE — the box is unchanged except
    possibly extracted-but-disabled bits, so the restart lands on the same
    working Foundation box, never a broken one. The driver leaves the env
    intact (delete-only-on-ok) and Foundation guarantees our proxy repo is
    installed, so the retry is a one-tap Setup reinstall + re-run.
    Per-provider config failures stay defensive inside the layer (logged,
    skipped; the other providers still apply).

    Re-entry is safe by construction: the backend ``is_installed``
    short-circuits, staged consumption is always-apply (identical bytes,
    inside the PVR-disabled window), and the direct-env enforce is
    write-only-if-changed — a second identical run reports
    ``already_done=True`` (backend present, nothing newly written) and leaves
    the box state byte-identical.

    NOT wired into the shipped ``run()`` (still ``run_express``); a new entry
    point for the modular flow (wired by Phase 5d). Returns the IPTV
    ``LayerResult``.
    """
    box_env = box_env or {}
    dialog = xbmcgui.DialogProgress()
    dialog.create("Tony.7.Bones Setup", "Installing IPTV...")

    # Layer 1 ONLY — the same apply_iptv Express drives (no forked install
    # logic). It owns the backend install-or-fail-loud, the PVR-disabled
    # config window, staged-first consumption, and the N-provider enforce.
    iptv_res = apply_iptv(box_env, dialog=dialog, log=_log)

    dialog.close()

    # Honest summary — straight from the LayerResult. "configured" means the
    # enforce actually WROTE instance-settings this run; "installed" means the
    # backend landed but nothing was written (no env provider, or the files
    # were already correct) — say "unchanged", never claim fresh config.
    if iptv_res.ok:
        configured = iptv_res.installed.get(PVR_BACKEND_ID) == "configured"
        lines = [
            "IPTV (live TV):",
            "pvr.iptvsimple: installed",
            "Instance settings: {}".format(
                "written" if configured else "unchanged (none in env, or already set)"
            ),
            "Restart will finish setup.",
        ]
    else:
        # Fail-loud contract: the backend did not install and apply_iptv wrote
        # NO instance-settings. Say so; the restart below lands on the box as
        # it was (re-run = reinstall Setup from our repo; the env is kept by
        # the driver's delete-only-on-ok).
        lines = [
            "IPTV (live TV):",
            "pvr.iptvsimple: FAILED",
            "No instance settings were written.",
            "Re-run Setup to retry after the restart.",
        ]
    xbmcgui.Dialog().ok("Tony.7.Bones Setup", "\n".join(lines))

    # Run once, then disappear (after the summary; never raises). The shared
    # library is a hidden module add-on and is deliberately LEFT installed.
    self_uninstall(MY_ID, _log)

    # ONE restart finalises the freshly extracted backend AND the self-removal
    # (pvr.iptvsimple reads instance settings at startup — the layer's
    # needs_restart request). NO skin activation here — Foundation owns the
    # active skin (re-setting lookandfeel.skin would re-arm the "Keep this
    # skin?" revert timeout).
    restart_kodi("Tony.7.Bones Setup", _log)
    return iptv_res


# --------------------------------------------------------------------------- #
# The Guided wizard + the Model A lifecycle (Phase 5d).
# --------------------------------------------------------------------------- #
# The per-device env key that routes the shipped run() to the Guided wizard.
# ``SETUP_MODE=guided`` (case-insensitive) -> run_guided; ANY other value or the
# key absent -> Express, byte-identical to the pre-5d one-tap (the Fire TV
# default — panel decision #4). Why an env key and not a launch dialog: a
# chooser prompt (even with a timeout) would break the proven UNATTENDED
# one-tap and re-shape the characterization snapshot; the mode is a per-device
# PROVISIONING decision, exactly like everything else the env drives. The
# provisioner does NOT set it by default. (Owner-vetoable mechanism — the
# documented alternatives are a timeout launch dialog or a second launcher
# entry; see the Phase 5d log in docs/plans/modular-setup.md.)
SETUP_MODE_KEY = "SETUP_MODE"

# The wizard's gate order (the 0-1-2 model) and the user-facing offer labels.
_GATE_LABELS = {
    "foundation": "Install Foundation (Estuary MOD V2 skin + repositories)",
    "iptv": "Install IPTV (live TV)",
    "addons": "Install Add-ons (curated content)",
    "finish": "Finish — setup is complete, remove Setup",
}

# The NO-ENV wizard's one-tap escape (Phase N1, D1): the exact old no-env
# Express — run_express({}) with keyless-Yahoo weather and default RSS,
# including its self-uninstall + single restart. Offered ONLY on the no-env
# wizard (the remote-only user) while gates remain: an env-routed Guided box
# was deliberately provisioned for the interview, and its menu surface stays
# byte-identical to 5d. (OWNER-VETOABLE: the plan's D5 calls the entry
# conditional; "always show it" is the documented alternative.)
_DEFAULTS_LABEL = "Install everything with defaults"


def _delete_box_env():
    """Remove the per-device env file(s) (guarded; missing files are no-ops).

    The env's lifecycle in a GUIDED session: the file SURVIVES every gate (a
    gate restart must not starve the next gate — the panel's env-ownership
    rule) and is consumed only by the TERMINAL ops (Finish / Remove Setup),
    BEFORE their restart, so no secret lingers once the wizard is done. The
    Express path keeps its own delete in run() (after the last layer),
    unchanged. Phase N1: the delete covers the pushed ``BOX_ENV_PATH`` + the
    profile-local collector env so a terminal op leaves no machine-derived
    secret behind (Model A semantics). Phase N1.1: the delete set is the
    DELETABLE subset only — the device-resident master ``.env.*`` SURVIVES
    every terminal op (the persistent-identity contract)."""
    _env_mod.delete_box_envs(_deletable_box_env_paths())


def _next_gate(box_env):
    """The wizard's resume probe: the next undone gate, from INSTALLED STATE.

    Foundation -> IPTV (offered ONLY when the env carries a provider playlist
    source — ``_env_has_iptv``) -> Add-ons -> "finish". Each probe reads the
    box's actual state (tony7bones.setup.probes), never a marker file, so a
    crash / declined restart / reverted skin self-heals: the incomplete gate is
    simply re-offered and every layer is idempotent on re-entry."""
    box_env = box_env or {}
    if not _probes.foundation_done():
        return "foundation"
    if _env_has_iptv(box_env) and not _probes.iptv_done(box_env):
        return "iptv"
    if not _probes.addons_done():
        return "addons"
    return "finish"


def _guided_gate_foundation(box_env):
    """The Foundation GATE: the same install seam as ``run_foundation``
    (``_foundation_core`` — repos incl. our proxy repo + the skin closure +
    weather/menu/autocomplete) but with the MODEL A lifecycle: NO
    self-uninstall (the Setup tile IS the "continue setup" affordance), and the
    activate-skin-then-restart TERMINAL OP fires only on ``ok`` (never restart
    into a failed gate). The restart is the gate seam: the box it lands on is a
    complete, branded, zero-content Kodi."""
    dialog = xbmcgui.DialogProgress()
    dialog.create("Tony.7.Bones Setup", "Installing Foundation...")
    res = _foundation_core(box_env, dialog)
    dialog.close()

    xbmcgui.Dialog().ok(
        "Tony.7.Bones Setup",
        "\n".join(
            [
                "Foundation:",
                "Estuary MOD V2: {}".format("installed" if res.ok else "FAILED"),
                "Repositories + sources installed.",
                (
                    "Kodi will restart — reopen Setup to continue."
                    if res.ok
                    else "Nothing was activated. Run this step again to retry."
                ),
            ]
        ),
    )
    if res.ok:
        # Activate MOD V2 LAST, immediately before the per-gate restart — ONE
        # orchestrator-owned terminal op (the activate-skin invariant: a gap
        # lets Kodi's "Keep this skin?" timeout silently revert it).
        activate_skin(SKIN_ID, _log)
        restart_kodi("Tony.7.Bones Setup", _log)
    return res


def _guided_gate_iptv(box_env):
    """The IPTV GATE: the same ``apply_iptv`` Express drives (no-fork) with the
    Model A lifecycle — NO self-uninstall, NO skin touch (Foundation owns the
    active skin), honest summary, restart only on ``ok`` (a failed backend
    install changed nothing, so there is nothing for a restart to finalise and
    the user lands back on the wizard to retry/exit)."""
    dialog = xbmcgui.DialogProgress()
    dialog.create("Tony.7.Bones Setup", "Installing IPTV...")
    res = apply_iptv(box_env, dialog=dialog, log=_log)
    dialog.close()

    if res.ok:
        configured = res.installed.get(PVR_BACKEND_ID) == "configured"
        lines = [
            "IPTV (live TV):",
            "pvr.iptvsimple: installed",
            "Instance settings: {}".format(
                "written" if configured else "unchanged (none in env, or already set)"
            ),
            "Kodi will restart — reopen Setup to continue.",
        ]
    else:
        lines = [
            "IPTV (live TV):",
            "pvr.iptvsimple: FAILED",
            "No instance settings were written.",
            "Run this step again to retry.",
        ]
    xbmcgui.Dialog().ok("Tony.7.Bones Setup", "\n".join(lines))
    if res.ok:
        restart_kodi("Tony.7.Bones Setup", _log)
    return res


def _guided_gate_addons(box_env):
    """The Add-ons GATE: the same ``apply_addons`` Express drives (no-fork)
    with the Model A lifecycle — NO self-uninstall, NO skin touch, honest
    per-stage counts, restart only on ``ok``. A user CANCEL mid-install
    (``ok=False``, the layer's only not-ok path) aborts with NO summary and NO
    restart — the monolith's early-return contract; the partial install is
    harmless and re-offering the gate completes it."""
    dialog = xbmcgui.DialogProgress()
    dialog.create("Tony.7.Bones Setup", "Installing Add-ons...")
    res = apply_addons(box_env, dialog=dialog, log=_log)
    if not res.ok:
        dialog.close()
        return res
    dialog.close()

    repo_ok = _count_installed(res, [rid for _z, rid in REPO_ZIPS])
    app_ok = _count_installed(res, ADDONS)
    video_ok = _count_installed(res, VIDEO_APPS)
    xbmcgui.Dialog().ok(
        "Tony.7.Bones Setup",
        "\n".join(
            [
                "Add-ons (curated content):",
                f"Repos: {repo_ok}/{len(REPO_ZIPS)}",
                f"Apps: {app_ok}/{len(ADDONS)}",
                f"Video add-ons: {video_ok}/{len(VIDEO_APPS)}",
                "Kodi will restart — reopen Setup to continue.",
            ]
        ),
    )
    restart_kodi("Tony.7.Bones Setup", _log)
    return res


def _guided_finish(box_env=None):
    """The TERMINAL op — the ONLY place the Guided lifecycle removes Setup
    (Model A: self-uninstall on terminal Finish / explicit Remove Setup, never
    after a gate). Order matters: consume the env FIRST (no secret lingers and
    the delete cannot be lost to the restart), then self-uninstall, then ONE
    restart to finalise the removal (Kodi's next scan drops the deleted dir's
    rows — the same shipped mechanism every standalone runner uses).

    Before consuming anything it runs the ``assert_box_complete`` verification
    (Phase 6) and LOGS the honest outcome. INFORM, never block: Finish is only
    offered when every gate probes done, but an explicit Remove Setup on a
    half-built box is legal — the user must still be able to remove Setup, so
    an incomplete box logs a WARNING instead of aborting the removal."""
    try:
        state = _probes.assert_box_complete(box_env or {})
        _log("finish: box verified complete {}".format(state))
    except AssertionError as e:
        _log("finish: {}".format(e), xbmc.LOGWARNING)
    except Exception as e:  # noqa: BLE001 - the check must never block removal
        _log(
            "finish: completeness check failed (non-fatal): {}".format(e),
            xbmc.LOGWARNING,
        )
    _delete_box_env()
    self_uninstall(MY_ID, _log)
    restart_kodi("Tony.7.Bones Setup", _log)


_GATE_RUNNERS = {
    "foundation": _guided_gate_foundation,
    "iptv": _guided_gate_iptv,
    "addons": _guided_gate_addons,
}


def run_guided(box_env=None):
    """The Guided wizard — the multi-gate, resumable Setup (Phase 5d).

    The panel's keystone: the orchestrator add-on PERSISTS across gates
    (Model A) — its home tile is the "continue setup" affordance — and
    self-uninstalls ONLY on terminal Finish or an explicit "Remove Setup".
    Each launch probes the box's INSTALLED STATE (never marker files) and
    offers the NEXT undone gate:

        Foundation -> IPTV (env-gated: offered only when the env carries a
        provider playlist source) -> Add-ons -> Finish

    One gate per launch; each gate restarts Kodi on success (per-gate cadence —
    desktop self-restarts, Fire TV shows the close-and-reopen notice), and each
    restart lands on a COMPLETE, WORKING box (skin-only after Foundation; + live
    TV after IPTV; the full box after Add-ons). Gates are UNATTENDED inside
    (the same prompt-free ``apply_*`` bodies Express drives — the no-fork
    invariant); the only prompts are BETWEEN gates: that is the wizard.

    Lifecycle rules this function owns:
      * NO self-uninstall after a gate — only ``_guided_finish`` (Finish, or a
        confirmed Remove Setup) removes the add-on.
      * The per-device env SURVIVES every gate (a later gate in a later session
        still needs it); it is consumed (deleted) only by the terminal op,
        BEFORE that op's restart. Re-running ``run()`` after each reopen
        re-reads the surviving env — which still carries ``SETUP_MODE=guided``,
        so the wizard self-resumes with no extra state.
      * Restart ONLY on a gate's ``ok`` (never restart into a failed gate); a
        FAILED gate returns to the wizard menu so the user can retry or exit.
      * A declined offer / dialog cancel exits cleanly: nothing installed,
        nothing removed, env + Setup intact (the decline-everything path).

    Degradation worth knowing (documented, accepted — RESHAPED by Phase N1):
    if the env file is LOST mid-flow (crash, manual delete), the next launch
    finds NO env and lands back in this wizard (no-env → Guided is the N1
    default), which self-resumes from installed state — strictly better than
    the pre-N1 silent Express completion; only env-driven config (weather
    keys, IPTV providers, RSS) is missing until an env producer re-supplies
    it. An env APPEARING mid-flow (a provisioner push while the wizard is
    open) is picked up on the NEXT launch — this launch keeps the dict it
    read at entry (read-once).

    The NO-ENV wizard (Phase N1 — the remote-only/no-computer user) adds ONE
    menu entry while gates remain: ``"Install everything with defaults"`` —
    the exact old no-env Express one-tap (``run_express({})``: same net
    install set, keyless-Yahoo weather, default RSS, self-uninstall + ONE
    restart). It is a TERMINAL op, so it also consumes any env file that
    appeared since launch (a guarded no-op in the normal no-env case). An
    env-routed wizard (``SETUP_MODE=guided``) never shows it — that menu is
    byte-identical to 5d.

    Returns an outcome string for tests/logs: ``"gate:<name>"`` (a gate ran —
    the restart seam follows on success), ``"finished"``, ``"removed"``,
    ``"defaults"`` (the no-env one-tap escape completed) or ``"exit"``.
    """
    box_env = box_env or {}
    no_env = not box_env
    while True:
        gate = _next_gate(box_env)
        options = [_GATE_LABELS[gate]]
        # The one-tap escape: no-env wizard only, and only while there is
        # still something to install (at "finish" it adds nothing).
        defaults_pick = None
        if no_env and gate != "finish":
            defaults_pick = len(options)
            options.append(_DEFAULTS_LABEL)
        remove_pick = len(options)
        options.append("Remove Setup")
        options.append("Exit (keep Setup)")
        pick = xbmcgui.Dialog().select("Tony.7.Bones Setup — Guided", options)
        if pick == 0:
            if gate == "finish":
                _log("guided: terminal Finish — removing Setup")
                _guided_finish(box_env)
                return "finished"
            _log(f"guided: running gate '{gate}'")
            res = _GATE_RUNNERS[gate](box_env)
            if res.ok:
                # The per-gate restart is in flight (or, on a declined desktop
                # restart prompt, deferred by the user). One gate per launch.
                return f"gate:{gate}"
            # FAILED gate: no restart happened and the box is unchanged —
            # fall through to the menu so the user can retry or exit.
            _log(f"guided: gate '{gate}' did not complete; back to the menu")
            continue
        if defaults_pick is not None and pick == defaults_pick:
            # The no-env one-tap escape (D1): the EXACT old no-env Express —
            # run_express({}) drives the three layers unattended, shows the
            # one summary, self-uninstalls, activates the skin, restarts ONCE.
            _log("guided: 'Install everything with defaults' — Express({})")
            addons_res, _foundation_res, _iptv_res = run_express({})
            if addons_res.ok:
                # Terminal op: consume any env that appeared since launch
                # (guarded no-op in the normal no-env case — Model A).
                _delete_box_env()
                return "defaults"
            # Mid-install cancel: the monolith's early-return contract —
            # nothing terminal happened; back to the menu.
            _log("guided: defaults run cancelled; back to the menu")
            continue
        if pick == remove_pick:
            if xbmcgui.Dialog().yesno(
                "Tony.7.Bones Setup",
                "Remove Setup from this box?\n\n"
                "Setup (and its saved device config) will be removed. You can "
                "reinstall it any time from the Tony.7.Bones repository.",
            ):
                _log("guided: explicit Remove Setup confirmed")
                _guided_finish(box_env)
                return "removed"
            continue  # declined — back to the menu
        # -1 (back/cancel) or "Exit": keep Setup + env; the tile resumes later.
        return "exit"


# The bundled master-env template (a byte-identical copy of the repo's
# committed `.env.device.example` — drift-pinned by test). Shipped as an add-on
# resource so the scaffold works with nothing but the installed Setup.
_ENV_TEMPLATE_RESOURCE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "resources", "env.device.example"
)


def _device_name():
    """Kodi's device name (``services.devicename`` — the same core setting the
    provisioner seeds), or ``""`` when unreadable (the scaffold's sanitizer
    falls back to the generic ``device``). Never raises."""
    try:
        resp = xbmc.executeJSONRPC(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "Settings.GetSettingValue",
                    "params": {"setting": "services.devicename"},
                }
            )
        )
        return str(json.loads(resp).get("result", {}).get("value") or "")
    except Exception:  # noqa: BLE001 - any failure = fall back to generic
        return ""


def _scaffold_master_env():
    """The N1.1 scaffold duty: with NO env anywhere, CREATE the device-resident
    master template ``env.<device-name>`` (NO leading dot — the owner's
    convention) at the BRAND ROOT (``_T7B/``) for the user to fill in and
    re-run. Placeholders only (every line comment-disabled — an unedited
    scaffold stays the no-env class); never overwrites; guarded and non-fatal
    where the brand root cannot exist (macOS/desktop: logged skip). Returns the
    created path or ``None``."""
    try:
        with open(_ENV_TEMPLATE_RESOURCE, encoding="utf-8") as fh:
            template = fh.read()
    except OSError as e:
        _log("scaffold: bundled template unreadable: {}".format(e), xbmc.LOGWARNING)
        return None
    return _env_mod.scaffold_master_env(
        _device_name(),
        template,
        primary=BOX_ENV_PATH,
        log=lambda m: _log("scaffold: {}".format(m)),
    )


def run():
    """Entry point — read the per-device env, route Express/Guided, own the env.

    The orchestrator owns the per-device env lifecycle: read it ONCE here (the
    FIRST non-empty env in the ordered source list — the provisioner's pushed
    ``BOX_ENV_PATH`` wins, then the profile-local collector env), pass the
    parsed dict down. Phase N1 routing (a strict superset of 5d's — D1):

        env ABSENT everywhere (read -> {})       -> run_guided({})   (N1 — the
                                                    no-computer/remote-only user)
        env present, no SETUP_MODE / other value -> run_express(env) (unchanged —
                                                    the provisioned one-tap)
        env present, SETUP_MODE=guided           -> run_guided(env)  (unchanged)

    The provisioned unattended one-tap CANNOT regress through this change: the
    provisioner always pushes an env before Setup runs (and since N1 it ABORTS
    when that push fails instead of silently degrading). The Guided wizard owns
    the env's TERMINAL delete (the file must survive every gate of a
    multi-session flow); the Express route deletes EVERY env candidate AFTER
    the last layer completes. On a mid-install CANCEL the env is LEFT intact
    (the layers never consumed it, so re-running Setup needs it) — mirroring
    the monolith, which returned before any env delete on cancel. Centralizing
    read+delete in one coordinator is what lets the multi-gate Guided flow
    share the env safely (an earlier gate must not delete the env a later gate
    needs).

    Before any of that, onboarding SELF-CREATES the canonical ``_T7B/kodi/``
    staging tree (``_ensure_device_dirs`` — guarded/idempotent) so a box the adb
    provisioner never touched (the no-computer path) still has the
    ``backups/ iptv/ media/ repositories/ rss/`` folders the device→userdata
    conventions expect. It runs FIRST, on EVERY route (Express AND Guided),
    regardless of whether an env is present.
    """
    _ensure_device_dirs()
    paths = _box_env_paths()
    # reader=read_box_env resolves THIS module's (monkeypatchable) name late —
    # the env-lifecycle tests spy on it; behaviour identical to the library's.
    box_env = _env_mod.read_first_env(paths, reader=read_box_env)
    if not box_env:
        # NO env anywhere: the remote-only user (no provisioner, no computer).
        # N1.1 scaffold duty: create the master template for them to fill in
        # and re-run, surface ONE unobtrusive line (a toast — the wizard's menu
        # itself stays untouched), then open the Guided wizard as before.
        created = _scaffold_master_env()
        if created:
            _log("no env found: master template scaffolded at {}".format(created))
            try:
                xbmcgui.Dialog().notification(
                    "Tony.7.Bones Setup",
                    "Config template created: {} — fill it in and re-run.".format(
                        created
                    ),
                )
            except Exception:  # noqa: BLE001 - a toast must never block the wizard
                pass
        run_guided({})
        return
    if (box_env.get(SETUP_MODE_KEY) or "").strip().lower() == "guided":
        run_guided(box_env)
        return
    addons_res, _foundation_res, _iptv_res = run_express(box_env)
    # Delete only after a non-cancelled run consumed the env (addons_res.ok is False
    # ONLY on a mid-install cancel — the abort path leaves the env for a re-run).
    # Covers the DELETABLE candidates (derived + profile-local) — the master
    # .env.* survives (N1.1: the persistent identity is never deleted).
    if addons_res.ok:
        _env_mod.delete_box_envs(_deletable_box_env_paths())


if __name__ == "__main__":
    run()
