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
import os

import xbmc
import xbmcgui

# Shared install library (script.module.tony7bones). All the generic machinery
# lives here; this file keeps only the base box's configuration + base-only steps.
from tony7bones import (
    activate_skin,
    extract_zip,
    install_selection,
    install_with_deps,
    is_installed,
    restart_kodi,
    self_uninstall,
    update_local_addons,
)
from tony7bones import enable as _enable

# Per-device .env parsing moved into the shared sublibrary (Phase 2a); re-export
# the same three names here so every existing reference and every test that
# reaches them via this module (boot.mod.parse_env / read_box_env / split_list)
# keeps working unchanged. Listed in __all__ so they are not pruned as "unused"
# (this module re-exports them, but does call read_box_env in run()).
from tony7bones.setup.env import parse_env, read_box_env, split_list

# The Foundation layer (skin closure + file-sources + home-trim) moved into the
# shared sublibrary (Phase 2b). The lifted bodies + the layer entry point live in
# tony7bones.setup.foundation; this module keeps thin shims (below) that delegate
# to them so every existing reference and test (boot.mod._install_skin /
# _add_file_sources / _trim_home_menu / _latest_zip_url + the SKIN_ID/PVR_ARTWORK
# constants) keeps working unchanged, and run() calls apply_foundation in the
# EXACT slot those three functions occupied.
from tony7bones.setup import foundation as _foundation
from tony7bones.setup.foundation import apply_foundation

# The ADD-ONS layer (base repos + apps install, curated video install, env-driven
# weather + RSS writers) moved into the shared sublibrary (Phase 2c). The lifted
# bodies + the layer entry point live in tony7bones.setup.addons; this module keeps
# thin re-export shims (below) that run() and _configure_box call in their EXISTING
# slots so the characterization snapshot stays byte-identical (the interleaving
# constraint: base/video install EARLY, weather/RSS config LATE in _configure_box).
# The moved bodies resolve their install primitives from the addons module globals,
# so the few run()-driven tests that stubbed the base/video path patch addons.* (the
# repointed boot.mod patches) — NO new deps-injection seam (Tech-debt ledger).
from tony7bones.setup import addons as _addons
from tony7bones.setup.addons import apply_addons

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
from tony7bones.setup import iptv as _iptv
from tony7bones.setup.iptv import apply_iptv

MY_ID = "script.tony7bones.bootstrap"

# Re-exported public names (env parsing now lives in tony7bones.setup.env; the
# Foundation layer entry point in tony7bones.setup.foundation; the Add-ons layer in
# tony7bones.setup.addons).
__all__ = [
    "apply_addons",
    "apply_foundation",
    "apply_iptv",
    "parse_env",
    "read_box_env",
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
# The WEATHER provider constants + the weather/RSS env-writers MOVED to the
# Add-ons layer (tony7bones.setup.addons, Phase 2c). Re-exported here so every
# existing reference and test (boot.mod.WEATHER_ADDON / WEATHER_LOCATION /
# _apply_weather_from_env / _apply_rss_from_env / _resolve_weather_location /
# _set_weather_settings / _set_weather_location / _weather_multi_settings_path)
# keeps working unchanged, and _configure_box calls them in the SAME slot they
# occupied. The IPTV + device-copy halves of _configure_box stay here (they go to
# apply_iptv in Phase 2d).
WEATHER_ADDON = _addons.WEATHER_ADDON  # Multi Weather (installed in ADDONS)
WEATHER_LOCATION = _addons.WEATHER_LOCATION
_weather_multi_settings_path = _addons._weather_multi_settings_path
_set_weather_settings = _addons._set_weather_settings
_set_weather_location = _addons._set_weather_location
_resolve_weather_location = _addons._resolve_weather_location
_apply_weather_from_env = _addons._apply_weather_from_env
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


# The per-device config the provisioner derives from the owner's master .env and
# pushes to the box. The ORCHESTRATOR (`run()`) reads it once, passes the parsed
# dict into `_configure_box`, and owns the read-then-DELETE so its secrets do not
# linger on the box — `_configure_box` is a pure consumer that never touches the
# file. (Owning the lifecycle in one coordinator is what lets a future multi-gate
# Guided flow share the env across gates instead of deleting it mid-run.)
BOX_ENV_PATH = "/storage/emulated/0/kodi/tony.7.bones/tony7bones.env"


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
        # Copy the user's device files into userdata (guarded; skips any missing).
        _copy_device_files()
        # IPTV from env: generate groups + inject m3u/epg, then enforce group mode
        # (gated on the groups file). Falls back to the device-copied file / no-op.
        _ensure_iptv_custom_tv_groups(box_env)
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


def run():
    dialog = xbmcgui.DialogProgress()
    dialog.create("Tony.7.Bones Setup", "Starting setup...")

    # --- base install (source repos + base apps) ---
    repo_ok, _fp_ok, app_ok, canceled = _install_base(dialog)
    if canceled:
        # User cancelled mid-install: abort cleanly with NO summary, NO
        # self-uninstall, NO restart. The partial install is harmless and
        # re-running Setup completes it.
        return dialog.close()

    # --- video add-ons (unattended — no picker, part of one-tap onboarding) ---
    video_ok = _install_video(dialog)

    # --- Foundation layer (Phase 2b): the Estuary MOD V2 skin + MOD V2+ patch
    #     closure, then the two content-free base-config steps (File-Manager
    #     sources + the Estuary home-menu trim). apply_foundation runs them in the
    #     EXACT slot _install_skin / _add_file_sources / _trim_home_menu occupied;
    #     it forwards THIS module's monkeypatchable step shims so a run() driven
    #     through patched install primitives is behaviour-identical to the monolith.
    #     The skin patch auto-applies via modv2plus's boot service once MOD V2 is
    #     live after the end-of-Setup restart (the patch cannot run before the skin
    #     is active, and Setup is gone by then). apply_foundation does NOT set
    #     lookandfeel.skin — that stays the terminal seam below (set LAST). ---
    foundation = apply_foundation(
        {},
        dialog=dialog,
        log=_log,
        install_skin=_install_skin,
        add_file_sources=_add_file_sources,
        trim_home_menu=_trim_home_menu,
    )
    skin_ok = foundation.ok

    dialog.close()

    # --- one combined summary ---
    xbmcgui.Dialog().ok(
        "Tony.7.Bones Setup",
        "\n".join(
            [
                f"Repos: {repo_ok}/{len(REPO_ZIPS)}",
                f"Apps: {app_ok}/{len(ADDONS)}",
                f"Video add-ons: {video_ok}/{len(VIDEO_APPS)}",
                "Estuary MOD V2: {}".format("installed" if skin_ok else "FAILED"),
                "Restart will finish setup.",
            ]
        ),
    )

    # Run once, then disappear (after the summary; never raises). The shared
    # library is a hidden module add-on and is deliberately LEFT installed.
    self_uninstall(MY_ID, _log)
    # The File-Manager sources + Estuary home-menu trim already ran inside
    # apply_foundation above (in the same slot they occupied in the monolith,
    # before the restart so Kodi re-reads them). Remaining base-box configuration:
    # weather/RSS/top-bar, env-driven.
    # The orchestrator owns the per-device env lifecycle: read it ONCE, pass the
    # parsed dict into the (now pure-consumer) _configure_box, then DELETE it here
    # after configuration completes — preserving today's effective timing (the env
    # was previously read+deleted inside _configure_box). On a no-env desktop run
    # read yields {} and the delete is a guarded no-op. Centralizing read+delete in
    # one coordinator is what lets a future multi-gate flow share the env safely.
    box_env = read_box_env(BOX_ENV_PATH)
    _configure_box(box_env)
    if box_env:
        try:
            os.remove(BOX_ENV_PATH)
        except OSError:
            pass
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


if __name__ == "__main__":
    run()
