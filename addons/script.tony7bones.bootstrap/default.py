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

MY_ID = "script.tony7bones.bootstrap"

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
# File-Manager sources (base-only configuration + merge)
# --------------------------------------------------------------------------- #
# (display name, path). The "special://kodi" source's path is the Android/Fire
# Stick internal storage dir — we try to create it (harmless no-op off Android)
# but always add the source entry regardless.
# Our repo's bare URL is special: ANY existing source pointing at it (with OR
# without a trailing slash, under ANY label) is NORMALIZED to REPO_SOURCE_NAME +
# the canonical REPO_SOURCE_URL by _add_file_sources (not just deduped).
REPO_SOURCE_NAME = ".tony.7.bones"
REPO_SOURCE_URL = "https://tony7bones.github.io/"
FILE_SOURCES = [
    ("special://home", "special://home"),
    ("special://kodi", "/storage/emulated/0/kodi/"),
    (REPO_SOURCE_NAME, REPO_SOURCE_URL),
]


def _sources_xml_path():
    """Resolve the absolute path to userdata/sources.xml via xbmcvfs."""
    p = xbmcvfs.translatePath("special://profile/sources.xml")
    if not p:
        p = xbmcvfs.translatePath("special://home/userdata/sources.xml")
    return p


def _make_files_source(parent, name, path):
    """Append a standard <source> entry to the given <files> element."""
    src = ET.SubElement(parent, "source")
    ET.SubElement(src, "name").text = name
    p = ET.SubElement(src, "path")
    p.set("pathversion", "1")
    p.text = path
    ET.SubElement(src, "allowsharing").text = "true"


def _add_file_sources():
    """Add our File-Manager sources to userdata/sources.xml.

    Edits the <files> section in place: creates the file/structure if missing,
    PRESERVES every existing source, and DEDUPES new ones on both name and path so
    a second run adds nothing. Special case — the repo source is NORMALIZED: any
    existing source whose path is our bare URL (with or without a trailing slash,
    under ANY label) is renamed to REPO_SOURCE_NAME with the canonical
    REPO_SOURCE_URL, and slash-variant duplicates collapse to one. For the Android
    internal-storage path we attempt mkdirs first (guarded) but add the source
    entry either way. Fully defensive: any error is logged and the rest of setup
    continues. The end-of-setup restart is what makes Kodi pick up the new sources
    (it caches sources.xml at startup).
    """
    try:
        xml_path = _sources_xml_path()

        # Parse the existing file, or start a fresh <sources> tree.
        root = None
        if xml_path and os.path.exists(xml_path):
            try:
                root = ET.parse(xml_path).getroot()
            except ET.ParseError as e:
                _log(f"sources.xml malformed, recreating: {e}", xbmc.LOGERROR)
                root = None
        if root is None or root.tag != "sources":
            root = ET.Element("sources")

        # Ensure a <files> section with a leading <default> element exists.
        files = root.find("files")
        if files is None:
            files = ET.SubElement(root, "files")
        if files.find("default") is None:
            # Prepend <default> so the section matches Kodi's canonical shape.
            default = ET.Element("default")
            files.insert(0, default)

        changed = False
        # Normalize the repo source: ANY existing <files> source whose path is our
        # bare URL — with OR without a trailing slash, under ANY label — is renamed
        # to the canonical REPO_SOURCE_NAME + REPO_SOURCE_URL. Deliberate (not a
        # dedupe): claim the repo source under one known name however it was added.
        repo_key = REPO_SOURCE_URL.rstrip("/")
        for s in files.findall("source"):
            if (s.findtext("path") or "").strip().rstrip("/") == repo_key:
                name_el = s.find("name")
                if name_el is None:
                    name_el = ET.SubElement(s, "name")
                if name_el.text != REPO_SOURCE_NAME:
                    name_el.text = REPO_SOURCE_NAME
                    changed = True
                path_el = s.find("path")
                if (
                    path_el is not None
                    and (path_el.text or "").strip() != REPO_SOURCE_URL
                ):
                    path_el.text = REPO_SOURCE_URL
                    changed = True
        # Collapse any duplicates the normalization produced (e.g. both slash
        # variants existed) down to a single canonical repo source.
        seen_repo = False
        for s in list(files.findall("source")):
            is_repo = (s.findtext("name") or "") == REPO_SOURCE_NAME and (
                s.findtext("path") or ""
            ).strip() == REPO_SOURCE_URL
            if is_repo:
                if seen_repo:
                    files.remove(s)
                    changed = True
                else:
                    seen_repo = True

        # Existing names/paths in <files> — dedupe new sources against both.
        have_names = {
            (s.findtext("name") or "").strip() for s in files.findall("source")
        }
        have_paths = {
            (s.findtext("path") or "").strip() for s in files.findall("source")
        }

        added = 0
        for name, path in FILE_SOURCES:
            # The Android internal-storage dir: try to create it, guarded.
            if path == "/storage/emulated/0/kodi/":
                try:
                    if not xbmcvfs.exists(path):
                        xbmcvfs.mkdirs(path)
                except Exception as e:  # noqa: BLE001 - non-Android: harmless
                    _log(
                        f"mkdirs {path} skipped (expected off Android): {e}",
                        xbmc.LOGINFO,
                    )
            if name in have_names or path in have_paths:
                continue  # dedupe: already present by name or path
            _make_files_source(files, name, path)
            have_names.add(name)
            have_paths.add(path)
            added += 1

        if added or changed:
            data = ET.tostring(root, encoding="unicode")
            with open(xml_path, "w", encoding="utf-8") as f:
                f.write(data)
            _log(f"file sources updated ({added} added) in {xml_path}", xbmc.LOGINFO)
        else:
            _log("file sources already present (no change)", xbmc.LOGINFO)
    except Exception as e:  # noqa: BLE001 - never abort the rest of setup
        _log(f"_add_file_sources failed (non-fatal): {e}", xbmc.LOGERROR)


# --------------------------------------------------------------------------- #
# Estuary home-menu trim (base-only configuration + merge)
# --------------------------------------------------------------------------- #
# Each home item in Estuary's xml/Home.xml is gated by
#   <visible>!Skin.HasSetting(HomeMenuNo<X>Button)</visible>,
# so setting the matching skin BOOLEAN true HIDES that item. We hide eight and
# leave the four we keep (TV/Live TV, Add-ons/Programs, Favourites, Weather)
# visible. Two ids per item: the camel-case ID the skin XML / Skin.SetBool use,
# and the LOWERCASE id the skin persists into settings.xml. Skin.HasSetting() is
# case-insensitive, so the skin reads either back.
#
# Both mechanisms are applied: Skin.SetBool() sets the in-memory value (which the
# shutdown persists, surviving the restart), and a direct settings.xml merge is
# the belt-and-suspenders fallback (covers a not-yet-loaded skin, preserves all
# other settings).
ESTUARY_SKIN_ID = "skin.estuary"

ESTUARY_HIDE_SETTINGS = [
    ("HomeMenuNoMovieButton", "homemenunomoviebutton"),  # Movies
    ("HomeMenuNoTVShowButton", "homemenunotvshowbutton"),  # TV shows
    ("HomeMenuNoMusicButton", "homemenunomusicbutton"),  # Music
    ("HomeMenuNoMusicVideoButton", "homemenunomusicvideobutton"),  # Music videos
    ("HomeMenuNoRadioButton", "homemenunoradiobutton"),  # Radio
    ("HomeMenuNoPicturesButton", "homemenunopicturesbutton"),  # Pictures
    ("HomeMenuNoVideosButton", "homemenunovideosbutton"),  # Videos
    ("HomeMenuNoGamesButton", "homemenunogamesbutton"),  # Games
]


def _estuary_settings_path():
    """Absolute path to skin.estuary's per-profile settings.xml."""
    return xbmcvfs.translatePath(
        "special://profile/addon_data/skin.estuary/settings.xml"
    )


def _trim_home_menu_setbool():
    """Set the eight hide-booleans in the ACTIVE skin's live memory via
    Skin.SetBool. This is what survives the end-of-setup restart: Kodi rewrites
    settings.xml from memory on shutdown, so the in-memory true persists."""
    for camel, _low in ESTUARY_HIDE_SETTINGS:
        xbmc.executebuiltin(f"Skin.SetBool({camel})")


def _trim_home_menu_writefile():
    """Merge the eight hide-booleans (= true) into skin.estuary's settings.xml,
    creating the file/dir if missing and PRESERVING every other existing setting.
    Belt-and-suspenders behind _trim_home_menu_setbool(). Idempotent."""
    xml_path = _estuary_settings_path()
    os.makedirs(os.path.dirname(xml_path), exist_ok=True)

    root = None
    if os.path.exists(xml_path):
        try:
            root = ET.parse(xml_path).getroot()
        except ET.ParseError as e:
            _log(f"skin.estuary settings.xml malformed, recreating: {e}", xbmc.LOGERROR)
            root = None
    if root is None or root.tag != "settings":
        root = ET.Element("settings")

    by_id = {
        (s.get("id") or "").lower(): s for s in root.findall("setting") if s.get("id")
    }

    changed = 0
    for _camel, low in ESTUARY_HIDE_SETTINGS:
        el = by_id.get(low)
        if el is None:
            el = ET.SubElement(root, "setting")
            el.set("id", low)
            el.set("type", "bool")
            by_id[low] = el
        elif not el.get("type"):
            el.set("type", "bool")
        if (el.text or "").strip().lower() != "true":
            changed += 1
        el.text = "true"

    with open(xml_path, "w", encoding="utf-8") as f:
        f.write(ET.tostring(root, encoding="unicode"))
    _log(
        f"_trim_home_menu: wrote 8 hide-bools ({changed} changed) to {xml_path}",
        xbmc.LOGINFO,
    )


def _trim_home_menu():
    """Trim the stock Estuary home menu to TV, Add-ons, Favourites, Weather.

    Hides the other eight items by forcing each Estuary HomeMenuNo<X>Button
    boolean true. Applies BOTH mechanisms (Skin.SetBool live value + a settings.xml
    merge). Guard: only meaningful on the stock Estuary skin — when another skin
    is active this is a safe no-op. Idempotent and defensive (any failure is
    logged and swallowed; touches ONLY skin.estuary's settings).
    """
    try:
        skin = ""
        try:
            skin = xbmc.getSkinDir() or ""
        except Exception:  # noqa: BLE001 - older/edge Kodi: treat as unknown
            skin = ""
        if skin and skin != ESTUARY_SKIN_ID:
            _log(
                f"_trim_home_menu: active skin is {skin}, "
                "not skin.estuary — skipping (no-op)",
                xbmc.LOGINFO,
            )
            return
        _trim_home_menu_setbool()
        _trim_home_menu_writefile()
    except Exception as e:  # noqa: BLE001 - never abort the rest of setup
        _log(f"_trim_home_menu failed (non-fatal): {e}", xbmc.LOGERROR)


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
# The provisioner derives a per-device `tony7bones.env` (KEY=value, shell-style)
# from the owner's master .env and pushes it to the box; this reads it and feeds
# the values into the existing idempotent settings writers. Pure-Python + no Kodi
# deps so it is unit-testable in isolation. NEVER log a parsed value (secrets).
def parse_env(text):
    """Parse KEY=value config text into a dict. Tolerant of the real .env shape:
    blank lines and full-line `#` comments are ignored; a value may be single- or
    double-quoted (quotes stripped, inline `#` kept if inside quotes); an UNquoted
    value drops an inline `# comment`; CRLF is handled; a line without `=` is
    skipped. Values stay raw strings — callers split `;`-lists via split_list()."""
    env = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        val = val.strip()
        if val[:1] in ("'", '"'):
            val = val[1:].split(val[0], 1)[0]  # quoted body up to the closing quote
        else:
            val = val.split("#", 1)[0].strip()  # drop inline comment when unquoted
        if key:
            env[key] = val
    return env


def split_list(value, sep=";"):
    """Split a `sep`-delimited multi-value field; trim each item, drop empties."""
    return [item.strip() for item in (value or "").split(sep) if item.strip()]


def read_box_env(path):
    """Read + parse the per-device tony7bones.env at `path`. Returns {} when the
    file is absent or unreadable (the no-env fallback — never raises)."""
    try:
        with open(path, encoding="utf-8") as fh:
            return parse_env(fh.read())
    except OSError:
        return {}


def _weather_multi_settings_path():
    """Absolute path to Multi Weather's per-profile settings.xml."""
    return xbmcvfs.translatePath(
        "special://profile/addon_data/weather.multi/settings.xml"
    )


def _set_weather_location():
    """Pre-write Multi Weather location 1 (name + url + lat + lon) so it resolves
    and fetches without the interactive geocode search. loc1_url is the field the
    add-on actually fetches by (see WEATHER_LOCATION). Creates the file/dir if
    missing and PRESERVES every other existing setting. Idempotent.

    The file is written as version="2" (Kodi's current addon-settings on-disk
    format, which the add-on's own setSetting* writes through); the add-on reads
    settings by id regardless of the bundled resources/settings.xml schema version."""
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
    for sid, val in WEATHER_LOCATION.items():
        el = by_id.get(sid)
        if el is None:
            el = ET.SubElement(root, "setting")
            el.set("id", sid)
            by_id[sid] = el
        el.text = val
    with open(xml_path, "w", encoding="utf-8") as f:
        f.write(ET.tostring(root, encoding="unicode"))
    _log(f"_configure_box: wrote Multi Weather location 1 to {xml_path}")


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


def _ensure_iptv_custom_tv_groups():
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
    """
    try:
        groups_file = xbmcvfs.translatePath(IPTV_CUSTOM_TV_GROUPS_FILE_VALUE)
        if not os.path.exists(groups_file):
            _log(
                "_ensure_iptv_custom_tv_groups: custom-groups file absent "
                f"({groups_file}); leaving all-channels default (no tvGroupMode=2)"
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

        changed = _set_instance_setting(
            root, IPTV_TV_GROUP_MODE_KEY, IPTV_TV_GROUP_MODE_CUSTOM
        )
        changed = (
            _set_instance_setting(
                root,
                IPTV_CUSTOM_TV_GROUPS_FILE_KEY,
                IPTV_CUSTOM_TV_GROUPS_FILE_VALUE,
            )
            or changed
        )
        changed = (
            _set_instance_setting(root, IPTV_TV_CHANNEL_GROUPS_ONLY_KEY, "true")
            or changed
        )

        if changed:
            with open(xml_path, "w", encoding="utf-8") as f:
                f.write(ET.tostring(root, encoding="unicode"))
            _log(
                "_ensure_iptv_custom_tv_groups: set tvGroupMode=2 + "
                f"customTvGroupsFile + tvChannelGroupsOnly in {xml_path}"
            )
        else:
            _log("_ensure_iptv_custom_tv_groups: keys already correct (no change)")
    except Exception as e:  # noqa: BLE001 - never abort the rest of setup
        _log(
            f"_ensure_iptv_custom_tv_groups failed (non-fatal): {e}",
            xbmc.LOGERROR,
        )


def _configure_box():
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
    Defensive: any failure is logged and swallowed; never aborts the run."""
    try:
        _set_setting("weather.addon", WEATHER_ADDON)
        _set_setting("lookandfeel.enablerssfeeds", True)
        _set_weather_location()
        # Copy the user's device files into userdata (guarded; skips any missing).
        _copy_device_files()
        # Enforce IPTV custom-TV-groups keys on top of the copied file (1a/1b).
        _ensure_iptv_custom_tv_groups()
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


def _install_skin(dialog):
    """Install + activate Estuary MOD V2 and the MOD V2+ patch, unattended.

    Two pieces are INVISIBLE to the closure resolver because it skips our
    127.0.0.1 proxy (repos.py): script.module.pvr.artwork (b-jesch GitHub-only)
    and our OWN first-party patch add-on script.tony7bones.modv2plus. Both are
    direct-extracted here. install_selection then resolves the rest of the skin's
    closure (skin.estuary.modv2 + skinshortcuts + image.resource.select from
    Kodinerds; pvr.artwork already satisfied) from the installed repos.

    Then we rescan + settle + enable everything we direct-extracted BEFORE setting
    lookandfeel.skin: a freshly-extracted skin must be registered AND enabled or
    Kodi silently rejects the skin setting and the box boots stock Estuary (the
    bug the fresh-Kodi test caught). The single end-of-Setup restart then activates
    MOD V2 (no "Keep this skin?" modal); modv2plus's boot service auto-applies the
    patch once MOD V2 is live. Returns True if the skin installed. Never raises.
    """
    try:
        if dialog is not None:
            dialog.update(0, "Installing Estuary MOD V2 skin...")
        # 1. pvr.artwork (GitHub-only, proxy-invisible) + its module deps, direct.
        if not is_installed(PVR_ARTWORK_ID):
            extract_zip(
                f"{HOSTED_BASE}/{PVR_ARTWORK_ID}/{PVR_ARTWORK_ZIP}", dialog, 100, _log
            )
        for dep in PVR_ARTWORK_DEPS:
            install_with_deps(dep, dialog, [], OFFICIAL_BASE, _log)
        # 2. our MOD V2+ patch add-on is proxy-only too -> direct-extract it (live
        #    version) + pull its outline-hd weather-icon dep from the official repo.
        if not is_installed(MODV2PLUS_ID):
            url = _latest_zip_url(MODV2PLUS_ID)
            if url:
                extract_zip(url, dialog, 100, _log)
        install_with_deps(OUTLINE_HD_ID, dialog, [], OFFICIAL_BASE, _log)
        # 3. the skin + its remaining closure from the installed repos + official.
        install_selection([SKIN_ID], OFFICIAL_BASE, set(), dialog, _log)
        # 4. rescan + settle + enable everything so the skin is a registered,
        #    enabled choice BEFORE we set it (else Kodi keeps stock Estuary).
        update_local_addons()
        xbmc.sleep(3000)
        for aid in (PVR_ARTWORK_ID, MODV2PLUS_ID, SKIN_ID):
            _enable(aid)
        xbmc.sleep(1000)
        # NOTE: lookandfeel.skin is set LAST in run(), immediately before the
        # restart — NOT here. A long gap between the skin-set and the restart lets
        # Kodi's "Keep this skin?" safety timeout silently revert the choice (the
        # bug the fresh-Kodi test caught); setting it right before the restart
        # persists it to guisettings on shutdown.
        return is_installed(SKIN_ID)
    except Exception as e:  # noqa: BLE001 - a skin failure must not abort the box
        _log(f"skin install failed (non-fatal): {e}", xbmc.LOGERROR)
        return False


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

    # --- Estuary MOD V2 skin + MOD V2+ patch: install + activate. The patch
    #     itself auto-applies via modv2plus's boot service once MOD V2 is live
    #     after the end-of-Setup restart (the patch cannot run before the skin is
    #     active, and Setup is gone by then). ---
    skin_ok = _install_skin(dialog)

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
    # Base-box configuration — applied before the restart so Kodi re-reads it:
    # file-manager sources, the Estuary home-menu trim, weather/RSS/top-bar.
    _add_file_sources()
    _trim_home_menu()
    _configure_box()
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
