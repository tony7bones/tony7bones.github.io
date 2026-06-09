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
from xml.etree import ElementTree as ET

import xbmc
import xbmcgui
import xbmcvfs

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

MY_ID = "script.tony7bones.bootstrap"

# Re-exported public names (env parsing now lives in tony7bones.setup.env;
# the Foundation layer entry point in tony7bones.setup.foundation).
__all__ = ["apply_foundation", "parse_env", "read_box_env", "split_list"]

REPO_BASE = "https://tony7bones.github.io/repositories/"
STATIC_BASE = "https://tony7bones.github.io/addons"

# Add-on index base urls for the closure. The two peno64 apps live in peno64;
# their module dependencies, the weather add-on, and the binary PVR/inputstream
# clients all live in the official Kodi repo. The library's resolver walks
# <requires>/<import> recursively across both (peno64 first, official last).
OFFICIAL_BASE = "https://mirrors.kodi.tv/addons/omega"
PENO64_BASE = (
    "https://raw.githubusercontent.com/peno64/repository.peno64/master/repo/zips"
)

# Repo installer zips: (zip filename, addon id).
REPO_ZIPS = [
    ("repository.709-1.0.2.zip", "repository.709"),
    ("repository.bugatsinho-2.8.zip", "repository.bugatsinho"),
    ("repository.cocoscrapers-1.0.1.zip", "repository.cocoscrapers"),
    ("repository.diggz.zip", "repository.diggz"),
    ("repository.ivarbrandt-1.0.3.zip", "repository.ivarbrandt"),
    ("repository.kodifitzwell-0.0.1.zip", "repository.kodifitzwell"),
    ("repository.kodinerds-7.0.1.7.zip", "repository.kodinerds"),
    ("repository.loop-3.0.4.zip", "repository.loop"),
    ("repository.Magnetic-1.1.0b.zip", "repository.Magnetic"),
    ("repository.peno64-1.5.zip", "repository.peno64"),
    ("repository.redwizard-1.2.2.zip", "repository.redwizard"),
    ("repository.umbrella-2.2.6.zip", "repository.umbrella"),
]

# First-party add-on ids installed by the generic direct-extract loop. Empty:
# the MOD V2 skin + the MOD V2+ patch add-on are installed by _install_skin
# (which handles their proxy-invisible deps + activation), not this loop.
FIRST_PARTY = []

# Apps installed (with dependency closure) by direct extract, in order.
#   * script.ezmaintenanceplus / script.realdebrid — peno64 (python).
#   * weather.multi — official repo (pure python; pulls python module deps).
#   * pvr.iptvsimple — official repo (BINARY; pulls binary inputstream deps).
ADDONS = [
    "script.ezmaintenanceplus",
    "script.realdebrid",
    "weather.multi",
    "pvr.iptvsimple",
]

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
WEATHER_ADDON = "weather.multi"  # Multi Weather (installed in ADDONS)
# Multi Weather fetches the forecast from https://weather.yahoo.com/<loc1_url>, so
# loc1_url is the LOAD-BEARING field: with it empty the add-on logs "empty location
# url" and clears its props (no fetch), regardless of name/lat/lon. The url format
# the add-on itself writes is "<country>/<region>/<town>" lowercased with spaces
# turned to dashes — for Sacramento that is "us/ca/sacramento". lat/lon are only
# used by the optional Weatherbit/OpenWeatherMap providers (off by default) and the
# name is just the display label. Pre-writing all four skips the interactive geocode
# search (RunScript(weather.multi,loc1)).
WEATHER_LOCATION = {
    "loc1_name": "Sacramento, CA, US",
    "loc1_url": "us/ca/sacramento",
    "loc1_lat": "38.5816",
    "loc1_lon": "-121.4944",
}
SHOW_WEATHERINFO = "show_weatherinfo"  # Estuary skin bool: weather in the top bar

# Device → userdata file copies. The user places these files on the device under
# the Android/Fire-Stick /storage/emulated/0/kodi/ tree (note the exact
# "tony.7.bones" spelling); Setup copies each one into Kodi's userdata over any
# default. Every file is USER-PROVIDED — Setup never downloads or creates them; it
# only copies each when present, overwriting the destination. They carry the
# user's private config and land in userdata/addon_data ONLY, never the repo.
#
# Each entry is (source-on-device, destination special:// path):
#   * the home-screen RSS news ticker feeds (over Kodi's default RssFeeds.xml)
#   * pvr.iptvsimple's instance settings (the IPTV add-on is already installed by
#     the base step, so addon_data/pvr.iptvsimple/ may need creating)
#   * pvr.iptvsimple's custom TV channel groups (the channelGroups/ subdir won't
#     exist on a fresh box — the copy creates it)
DEVICE_FILE_COPIES = [
    (
        "/storage/emulated/0/kodi/tony.7.bones/rss/RssFeeds.xml",
        "special://home/userdata/RssFeeds.xml",
    ),
    (
        "/storage/emulated/0/kodi/tony.7.bones/iptv/instance-settings-1.xml",
        "special://home/userdata/addon_data/pvr.iptvsimple/instance-settings-1.xml",
    ),
    (
        "/storage/emulated/0/kodi/tony.7.bones/iptv/customTVGroups-Network24.xml",
        "special://home/userdata/addon_data/pvr.iptvsimple/channelGroups/"
        "customTVGroups-Network24.xml",
    ),
]


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


def _weather_multi_settings_path():
    """Absolute path to Multi Weather's per-profile settings.xml."""
    return xbmcvfs.translatePath(
        "special://profile/addon_data/weather.multi/settings.xml"
    )


def _set_weather_settings(settings):
    """Write each id->value in `settings` into Multi Weather's settings.xml,
    creating the file/dir if missing and PRESERVING every other existing setting.
    Idempotent; written version="2" (the add-on reads settings by id)."""
    xml_path = _weather_multi_settings_path()
    os.makedirs(os.path.dirname(xml_path), exist_ok=True)
    root = None
    if os.path.exists(xml_path):
        try:
            root = ET.parse(xml_path).getroot()
        except ET.ParseError:
            root = None
    if root is None or root.tag != "settings":
        root = ET.Element("settings")
        root.set("version", "2")
    by_id = {s.get("id"): s for s in root.findall("setting") if s.get("id")}
    for sid, val in settings.items():
        el = by_id.get(sid)
        if el is None:
            el = ET.SubElement(root, "setting")
            el.set("id", sid)
            by_id[sid] = el
        el.text = val
    with open(xml_path, "w", encoding="utf-8") as f:
        f.write(ET.tostring(root, encoding="unicode"))


def _set_weather_location():
    """Fallback: Multi Weather location 1 = Sacramento (the keyless default used
    when the env provides no resolvable locations). loc1_url is the field the
    add-on fetches by. Idempotent; preserves other settings."""
    _set_weather_settings(WEATHER_LOCATION)
    _log("_configure_box: wrote Multi Weather default location (Sacramento)")


def _resolve_weather_location(query, timeout=10, tries=2):
    """Resolve a city name / zipcode to a Multi Weather location via Yahoo's
    search-assist API (the trailing-slash endpoint — no redirect needed). Returns
    {name,url,lat,lon} or None on any failure (the caller falls back). Retries the
    network call; never raises. Mirrors how the add-on's own search builds the
    fields: name "Town, Region, Country"; url "country/region/town"."""
    import json as _json
    import urllib.parse as _uparse
    import urllib.request as _ureq

    api = (
        "https://weather.yahoo.com/_atmos/api/search-assist/locations/?query="
        + _uparse.quote(query)
    )
    req = _ureq.Request(
        api, headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"}
    )
    for _ in range(tries):
        try:
            with _ureq.urlopen(req, timeout=timeout) as resp:
                data = _json.loads(resp.read().decode("utf-8"))
            for sug in data.get("suggestions", []):
                loc = sug.get("location") or {}
                town = loc.get("town") or {}
                region = loc.get("region") or {}
                code = region.get("code") or region.get("name") or ""
                country = (loc.get("country") or {}).get("code") or ""
                name = town.get("name")
                if not (name and country and town.get("latitude") is not None):
                    continue
                return {
                    "name": "%s, %s, %s" % (name, code, country),
                    "url": "%s/%s/%s"
                    % (
                        country.lower(),
                        str(code).lower().replace(" ", "-"),
                        name.lower().replace(" ", "-"),
                    ),
                    "lat": str(town["latitude"]),
                    "lon": str(town["longitude"]),
                }
            return None
        except Exception:  # noqa: BLE001 - best-effort; caller falls back
            continue
    return None


def _apply_weather_from_env(box_env):
    """Drive Multi Weather from the per-device env: resolve up to 5
    WEATHER_LOCATIONS (city names or zipcodes) via Yahoo, write loc1..N (+ clear
    the unused slots), and enable the optional Weatherbit / OpenWeatherMap upgrade
    layers when their keys are present. Falls back to the hardcoded Sacramento
    default when no env locations are given OR none resolve — NEVER writes an empty
    loc_url. Defensive: logs counts/flags only (never secret values); never raises.
    """
    try:
        wanted = split_list(box_env.get("WEATHER_LOCATIONS", ""))[:5]
        settings = {}
        resolved = 0
        for query in wanted:
            loc = _resolve_weather_location(query)
            if not loc or not loc.get("url"):
                _log(
                    "_apply_weather: a location did not resolve — skipped",
                    xbmc.LOGWARNING,
                )
                continue
            resolved += 1
            settings["loc%d_name" % resolved] = loc["name"]
            settings["loc%d_url" % resolved] = loc["url"]
            settings["loc%d_lat" % resolved] = loc["lat"]
            settings["loc%d_lon" % resolved] = loc["lon"]
        if resolved == 0:
            settings.update(WEATHER_LOCATION)  # Sacramento default — never empty
            resolved = 1
        else:
            for j in range(resolved + 1, 6):  # clear stale higher-numbered slots
                for fld in ("name", "url", "lat", "lon"):
                    settings["loc%d_%s" % (j, fld)] = ""
        wbit = (box_env.get("WEATHERBIT_API_KEY") or "").strip()
        owm = (box_env.get("OWM_API_KEY") or "").strip()
        if wbit:
            settings["WAdd"] = "true"
            settings["API"] = wbit
        if owm:
            settings["WMaps"] = "true"
            settings["MAPAPI"] = owm
        _set_weather_settings(settings)
        _log(
            "_apply_weather: %d location(s) written; weatherbit=%s owm=%s"
            % (resolved, bool(wbit), bool(owm))
        )
    except Exception as e:  # noqa: BLE001 - never abort the rest of setup
        _log(f"_apply_weather failed (non-fatal): {e}", xbmc.LOGERROR)


def _apply_rss_from_env(box_env):
    """Generate userdata/RssFeeds.xml from the env's RSS_FEEDS (+ RSS_INTERVAL).
    No-op when RSS_FEEDS is absent (a device-copied file / the Kodi default stands).
    Feed URLs are not secret. Defensive: logged, never raises."""
    feeds = split_list(box_env.get("RSS_FEEDS", ""))
    if not feeds:
        return
    try:
        interval = (box_env.get("RSS_INTERVAL") or "30").strip() or "30"
        path = xbmcvfs.translatePath("special://home/userdata/RssFeeds.xml")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        root = ET.Element("rssfeeds")
        rset = ET.SubElement(root, "set")
        rset.set("id", "1")
        for url in feeds:
            feed = ET.SubElement(rset, "feed")
            feed.set("updateinterval", interval)
            feed.text = url
        with open(path, "w", encoding="utf-8") as f:
            f.write(ET.tostring(root, encoding="unicode"))
        _log("_apply_rss: wrote %d RSS feed(s) (interval %s)" % (len(feeds), interval))
    except Exception as e:  # noqa: BLE001 - never abort the rest of setup
        _log(f"_apply_rss failed (non-fatal): {e}", xbmc.LOGERROR)


def _copy_one_device_file(src, dst_special):
    """Copy a single USER-PROVIDED device file into userdata, guarded.

    FROM the device path `src`, TO the translated `dst_special` — creating the
    destination directory if missing (fresh boxes lack addon_data/pvr.iptvsimple/
    and its channelGroups/ subdir) and OVERWRITING the destination if it exists.
    GUARDED: if the source is absent (e.g. on desktop, or the user hasn't placed
    it) this logs and skips — it never errors. Idempotent."""
    if not xbmcvfs.exists(src):
        _log(
            f"_configure_box: device file not found, skipping: {src}",
            xbmc.LOGINFO,
        )
        return
    dst = xbmcvfs.translatePath(dst_special)
    # Create the destination directory tree if it doesn't exist yet.
    dst_dir = os.path.dirname(dst)
    if dst_dir and not xbmcvfs.exists(dst_dir):
        xbmcvfs.mkdirs(dst_dir)
    # xbmcvfs.copy overwrites an existing destination.
    if xbmcvfs.copy(src, dst):
        _log(f"_configure_box: copied device file {src} -> {dst}")
    else:
        _log(
            f"_configure_box: xbmcvfs.copy reported failure copying {src} -> {dst}",
            xbmc.LOGERROR,
        )


def _copy_device_files():
    """Copy each USER-PROVIDED device file in DEVICE_FILE_COPIES into userdata.

    Data-driven loop over (src, dst) pairs: the custom RSS feeds plus the
    pvr.iptvsimple instance settings and custom TV channel groups. Each copy
    creates its destination dir if missing, overwrites the destination if present,
    and is GUARDED — a missing source (or any per-file error) is logged and
    skipped, never aborting the rest of setup. Idempotent."""
    for src, dst_special in DEVICE_FILE_COPIES:
        try:
            _copy_one_device_file(src, dst_special)
        except Exception as e:  # noqa: BLE001 - one bad file must not abort the rest
            _log(
                f"_copy_device_files: copy {src} failed (non-fatal): {e}",
                xbmc.LOGERROR,
            )


# --------------------------------------------------------------------------- #
# pvr.iptvsimple instance-settings keys (1a/1b — TV custom groups)
# --------------------------------------------------------------------------- #
# pvr.iptvsimple stores its per-instance config in
#   addon_data/pvr.iptvsimple/instance-settings-1.xml
# (a <settings version="2"> file keyed by setting id). These two keys make the
# add-on serve the user's custom TV channel groups instead of "all channels":
#
#   * tvGroupMode = 2   -> "Custom groups" (schema enum: 0=ALL, 1=SOME, 2=CUSTOM,
#     confirmed in resources/instance-settings.xml, option label 30038)
#   * customTvGroupsFile -> the channelGroups/ file we copy from the device
#
# These are ADD-ON INSTANCE settings: Kodi's JSON-RPC Settings.SetSettingValue
# reaches only CORE settings (system.*, weather.*, …) and has no method for
# per-instance PVR add-on settings — so the only way to set them is to write the
# instance-settings file directly. We already COPY the user's file here; this
# step then ENFORCES the two keys on top of whatever was copied, so the box ends
# up correct even if the user's file omits or mis-sets them. If the copied file
# already has them, it's a no-op. The path uses the same special://userdata form
# the add-on itself writes (it resolves to the same channelGroups/ dir as the
# copy destination).
IPTV_INSTANCE_SETTINGS_SPECIAL = (
    "special://home/userdata/addon_data/pvr.iptvsimple/instance-settings-1.xml"
)
IPTV_TV_GROUP_MODE_KEY = "tvGroupMode"
IPTV_TV_GROUP_MODE_CUSTOM = "2"  # schema enum: 2 == CUSTOM_GROUPS
IPTV_CUSTOM_TV_GROUPS_FILE_KEY = "customTvGroupsFile"
IPTV_CUSTOM_TV_GROUPS_FILE_VALUE = (
    "special://userdata/addon_data/pvr.iptvsimple/channelGroups/"
    "customTVGroups-Network24.xml"
)
# "Only load TV channels in groups" — pvr.iptvsimple shows only channels that
# belong to a (custom) group, hiding the ungrouped firehose. Enforced true.
IPTV_TV_CHANNEL_GROUPS_ONLY_KEY = "tvChannelGroupsOnly"


def _set_instance_setting(root, setting_id, value):
    """Ensure <setting id="setting_id"> in `root` has exactly `value`.

    Updates the element in place if present (and drops the default="true" flag,
    since we're now overriding the default), creates it if missing. Returns True
    if anything changed, so the caller can skip a no-op write. Mirrors how Kodi's
    own settings writer stamps a user-set value."""
    el = None
    for s in root.findall("setting"):
        if s.get("id") == setting_id:
            el = s
            break
    changed = False
    if el is None:
        el = ET.SubElement(root, "setting")
        el.set("id", setting_id)
        changed = True
    # A user-set value is no longer the schema default.
    if el.get("default") is not None:
        el.attrib.pop("default", None)
        changed = True
    if (el.text or "") != value:
        el.text = value
        changed = True
    return changed


def _ensure_iptv_custom_tv_groups(box_env=None):
    """Enforce TV-group-mode=Custom + the custom-TV-groups file path in
    pvr.iptvsimple's instance-settings-1.xml (1a/1b).

    Runs AFTER _copy_device_files() (which may have copied the user's own
    instance-settings-1.xml). Reads the file if present, else starts a fresh
    <settings version="2"> tree, then ensures the two keys are correct and writes
    back only if something changed. The destination dir is created if absent (a
    fresh box without the copied file). Idempotent and fully defensive: any
    failure is logged and swallowed — never aborts the rest of setup. These keys
    cannot be set via JSON-RPC (it does not reach add-on instance settings), so a
    direct file write is the only mechanism.

    GATED: only enforces custom-group mode when the custom-groups file actually
    exists (copied from the device, or generated from the env's IPTV_GROUPS). On a
    no-env / no-file box, forcing tvGroupMode=2 at a MISSING file gives
    pvr.iptvsimple an empty channel list — so we leave the all-channels default.

    When `box_env` provides IPTV_GROUPS the groups file is GENERATED from it first
    (channel-group names only — not secret); IPTV_M3U/IPTV_EPG are injected as
    m3uUrl/epgUrl (+ remote path type); tvChannelGroupsOnly comes from
    IPTV_GROUPS_ONLY (default true). Secret values are never logged.
    """
    box_env = box_env or {}
    try:
        groups_file = xbmcvfs.translatePath(IPTV_CUSTOM_TV_GROUPS_FILE_VALUE)
        groups = split_list(box_env.get("IPTV_GROUPS", ""))
        if groups:
            os.makedirs(os.path.dirname(groups_file), exist_ok=True)
            groot = ET.Element("customChannelGroups")
            for name in groups:
                ET.SubElement(groot, "channelGroupName").text = name
            with open(groups_file, "w", encoding="utf-8") as f:
                f.write(ET.tostring(groot, encoding="unicode"))
            _log(
                "_ensure_iptv_custom_tv_groups: generated %d custom group(s) from env"
                % len(groups)
            )
        # The playlist SOURCE (m3u/epg) and the group MODE are independent: inject
        # the source whenever the env supplies it, but only force CUSTOM group mode
        # when the groups file exists (crit A — never tvGroupMode=2 at a missing
        # file). With neither, there's nothing to do — leave the all-channels default.
        m3u = (box_env.get("IPTV_M3U") or "").strip()
        epg = (box_env.get("IPTV_EPG") or "").strip()
        have_groups = os.path.exists(groups_file)
        if not (m3u or epg or have_groups):
            _log(
                "_ensure_iptv_custom_tv_groups: nothing to set (no m3u/epg, no "
                f"groups file {groups_file}) — leaving the all-channels default"
            )
            return
        xml_path = xbmcvfs.translatePath(IPTV_INSTANCE_SETTINGS_SPECIAL)
        os.makedirs(os.path.dirname(xml_path), exist_ok=True)

        root = None
        if os.path.exists(xml_path):
            try:
                root = ET.parse(xml_path).getroot()
            except ET.ParseError as e:
                _log(
                    f"_ensure_iptv_custom_tv_groups: instance-settings-1.xml "
                    f"malformed, recreating: {e}",
                    xbmc.LOGERROR,
                )
                root = None
        if root is None or root.tag != "settings":
            root = ET.Element("settings")
            root.set("version", "2")

        # Playlist source (provider creds — SECRET; never logged as values).
        changed = False
        if m3u:
            changed = _set_instance_setting(root, "m3uPathType", "1") or changed
            changed = _set_instance_setting(root, "m3uUrl", m3u) or changed
        if epg:
            changed = _set_instance_setting(root, "epgPathType", "1") or changed
            changed = _set_instance_setting(root, "epgUrl", epg) or changed
        # Custom group mode — ONLY when the groups file exists.
        only_val = "n/a"
        if have_groups:
            changed = (
                _set_instance_setting(
                    root, IPTV_TV_GROUP_MODE_KEY, IPTV_TV_GROUP_MODE_CUSTOM
                )
                or changed
            )
            changed = (
                _set_instance_setting(
                    root,
                    IPTV_CUSTOM_TV_GROUPS_FILE_KEY,
                    IPTV_CUSTOM_TV_GROUPS_FILE_VALUE,
                )
                or changed
            )
            only = (box_env.get("IPTV_GROUPS_ONLY", "true") or "true").strip().lower()
            only_val = "true" if only in ("true", "1", "yes", "on") else "false"
            changed = (
                _set_instance_setting(root, IPTV_TV_CHANNEL_GROUPS_ONLY_KEY, only_val)
                or changed
            )
        else:
            _log(
                "_ensure_iptv_custom_tv_groups: no groups file — m3u/epg set, group "
                "mode left at the all-channels default"
            )

        if changed:
            with open(xml_path, "w", encoding="utf-8") as f:
                f.write(ET.tostring(root, encoding="unicode"))
            _log(
                "_ensure_iptv_custom_tv_groups: groups=%s only=%s m3u=%s epg=%s in %s"
                % (have_groups, only_val, bool(m3u), bool(epg), xml_path)
            )
        else:
            _log("_ensure_iptv_custom_tv_groups: keys already correct (no change)")
    except Exception as e:  # noqa: BLE001 - never abort the rest of setup
        _log(
            f"_ensure_iptv_custom_tv_groups failed (non-fatal): {e}",
            xbmc.LOGERROR,
        )


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
# Curated video add-ons — installed unattended (no picker) in the one-tap run
# --------------------------------------------------------------------------- #
VIDEO_APPS = [
    "plugin.video.pov",
    "plugin.video.the-loop",
    "plugin.video.sporthdme",
    "plugin.video.youtube",
]
# Install-then-disable: The Loop declares plugin.video.dailymotion_com as a
# REQUIRED import nobody here uses. Installing it satisfies the dep check;
# disabling it afterwards means it never runs and survives Loop updates with no
# re-patching.
VIDEO_DISABLE_AFTER = {"plugin.video.dailymotion_com"}


def _install_video(dialog):
    """Install the curated video add-ons + their closure, unattended.

    Delegates to the shared library's install_selection (folded in from the
    retired standalone Video Add-ons Setup): enable the source repos, build the
    combined index from the installed repos + the official repo, resolve the
    closure for VIDEO_APPS, extract/enable/origin-stamp it, and apply the
    install-then-disable set. Shares this run's progress dialog. Returns how many
    of VIDEO_APPS ended up installed. Never raises — a video failure must not
    abort the box.
    """
    try:
        return install_selection(
            VIDEO_APPS, OFFICIAL_BASE, VIDEO_DISABLE_AFTER, dialog, _log
        )
    except Exception as e:  # noqa: BLE001 - video failure must not abort the run
        _log(f"video install failed (non-fatal): {e}", xbmc.LOGERROR)
        return 0


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


def _install_base(dialog):
    """Run the base install: repos + first-party + apps. Returns (repo_ok, fp_ok,
    app_ok, canceled). Shares the progress dialog with the (optional) video stage
    so the user sees one continuous progress bar. `canceled` is True if the user
    cancelled the progress dialog mid-install (run() then aborts with no summary,
    exactly today's behaviour)."""
    total = len(REPO_ZIPS) + len(FIRST_PARTY) + len(ADDONS) + 1
    step = 0
    repo_ok = fp_ok = app_ok = 0

    # 1. repos by direct extract
    for zip_name, _rid in REPO_ZIPS:
        step += 1
        if extract_zip(REPO_BASE + zip_name, dialog, int(step / total * 100), _log):
            repo_ok += 1
        if dialog.iscanceled():
            return repo_ok, fp_ok, app_ok, True

    # 2. first-party add-ons by direct extract
    for addon_id in FIRST_PARTY:
        step += 1
        url = _latest_zip_url(addon_id)
        if url and extract_zip(url, dialog, int(step / total * 100), _log):
            fp_ok += 1
        if dialog.iscanceled():
            return repo_ok, fp_ok, app_ok, True

    # 3. register + enable the repos and first-party add-ons.
    step += 1
    dialog.update(int(step / total * 100), "Registering add-ons...")
    update_local_addons()
    xbmc.sleep(3000)
    for _zip_name, rid in REPO_ZIPS:
        if rid:
            _enable(rid)
    for addon_id in FIRST_PARTY:
        _enable(addon_id)

    # 4. install each app with its dependency closure by direct extract.
    for addon_id in ADDONS:
        step += 1
        dialog.update(int(step / total * 100), f"Installing {addon_id}")
        if install_with_deps(addon_id, dialog, [PENO64_BASE], OFFICIAL_BASE, _log):
            app_ok += 1
        if dialog.iscanceled():
            return repo_ok, fp_ok, app_ok, True

    return repo_ok, fp_ok, app_ok, False


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
