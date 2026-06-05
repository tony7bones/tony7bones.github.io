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

This Setup can optionally chain the Video Add-ons Setup: two prompts are
FRONT-LOADED before any install (a yes/no, default No, then the video
multiselect), and the whole run — base install plus the chosen video apps — runs
unattended in this one script with a single combined summary and a single
restart.

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
    extract_zip,
    install_with_deps,
    restart_kodi,
    self_uninstall,
    update_local_addons,
)
from tony7bones import enable as _enable

MY_ID = "script.tony7bones.bootstrap"

REPO_BASE = "https://tony7bones.github.io/repo/repositories/"
STATIC_BASE = "https://tony7bones.github.io/repo"

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

# First-party add-on ids on our Pages — direct extract, version resolved live.
# Deliberately empty (the Estuary MOD V2 patch is manual-only); run() simply
# skips the first-party loop.
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
# (display name, path). The second path is the Android/Fire Stick internal
# storage dir — we try to create it (harmless no-op off Android) but always add
# the source entry regardless.
FILE_SOURCES = [
    ("Kodi home directory", "special://home"),
    ("Kodi sources directory", "/storage/emulated/0/kodi/"),
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
    PRESERVES every existing source, and DEDUPES on both name and path so a second
    run adds nothing. For the Android internal-storage path we attempt mkdirs
    first (guarded) but add the source entry either way. Fully defensive: any
    error is logged and the rest of setup continues. The end-of-setup restart is
    what makes Kodi pick up the new sources (it caches sources.xml at startup).
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

        # Existing names/paths in <files> — dedupe against both.
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

        if added:
            data = ET.tostring(root, encoding="unicode")
            with open(xml_path, "w", encoding="utf-8") as f:
                f.write(data)
            _log(f"added {added} file source(s) to {xml_path}", xbmc.LOGINFO)
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
# the Android/Fire-Stick "Kodi sources directory" tree (note the exact
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


def _configure_box():
    """Apply the base box's weather + interface preferences:
      * weather provider  -> Multi Weather (weather.addon)
      * Multi Weather location 1 -> Sacramento, CA, US (name + coords)
      * RSS news ticker   -> ON (lookandfeel.enablerssfeeds)
      * device files      -> copied from the device into userdata if present
        (guarded copies: custom RssFeeds.xml, plus pvr.iptvsimple's
        instance-settings-1.xml and customTVGroups-Network24.xml — runs here
        AFTER the base install, so pvr.iptvsimple already exists)
      * Estuary top bar   -> show weather info (Skin.SetBool, persists on restart)
    Defensive: any failure is logged and swallowed; never aborts the run."""
    try:
        _set_setting("weather.addon", WEATHER_ADDON)
        _set_setting("lookandfeel.enablerssfeeds", True)
        _set_weather_location()
        # Copy the user's device files into userdata (guarded; skips any missing).
        _copy_device_files()
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
# Optional video chaining — front-loaded prompts (see video module for config)
# --------------------------------------------------------------------------- #
# Imported lazily inside run() so this base Setup still imports cleanly if the
# video Setup is not installed; the prompts are shown BEFORE any install so the
# whole run is unattended afterwards.


def _ask_also_video():
    """Front-loaded yes/no: 'Include video add-ons?'.

    DEFAULTS TO NO (opt-in): the No button is pre-focused via Kodi's
    defaultbutton=DLG_YESNO_NO_BTN. Both the constant and the kwarg exist on
    Kodi 21 Omega (verified on the box). We fall back gracefully on any older
    Kodi that lacks either — a plain yesno whose No is the right-hand (default)
    button. Returns True only if the user explicitly chose Yes.
    """
    title = "Tony.7.Bones Setup"
    msg = "Include video add-ons?"
    no_btn = getattr(xbmcgui, "DLG_YESNO_NO_BTN", None)
    if no_btn is not None:
        try:
            return bool(
                xbmcgui.Dialog().yesno(
                    title, msg, yeslabel="Yes", nolabel="No", defaultbutton=no_btn
                )
            )
        except TypeError:
            pass  # older Kodi without the defaultbutton kwarg — fall through
    return bool(xbmcgui.Dialog().yesno(title, msg, yeslabel="Yes", nolabel="No"))


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
    # Front-load the optional video chaining prompts BEFORE any install, so the
    # rest of the run is unattended. Default is No (opt-in). If Yes, the video
    # multiselect is shown up front and the selection captured; the actual video
    # install happens after the base install, in this one script.
    video = None  # the video Setup's default.py module, imported only if chosen
    video_selected = []  # list of chosen video app ids
    video_load_failed = False  # Yes was chosen but the video Setup couldn't load
    if _ask_also_video():
        # The video chaining reuses the Video Add-ons Setup add-on's config and
        # install logic, so that add-on must be present on the box to load it. On
        # a fresh box the user has only installed our repo + run THIS base Setup,
        # so script.tony7bones.video is usually NOT installed yet. Fetch it (and
        # its shared library) by direct extract from our Pages repo BEFORE trying
        # to load it — otherwise the prompt is answered Yes but the whole video
        # step silently vanishes (the original one-shot bug). If it still can't be
        # loaded we record that and surface it in the summary, never silently drop.
        _ensure_video_setup_installed()
        video = _load_video_module()
        if video is None:
            video_load_failed = True
        else:
            labels = [label for label, _aid in video.APPS]
            choices = xbmcgui.Dialog().multiselect(
                "Video Add-ons Setup", labels, preselect=video.PRESELECT
            )
            # Cancelled/empty multiselect → run base only (today's behaviour).
            if choices:
                video_selected = [video.APPS[i][1] for i in choices]

    dialog = xbmcgui.DialogProgress()
    dialog.create("Tony.7.Bones Setup", "Starting setup...")

    # --- base install ---
    repo_ok, fp_ok, app_ok, canceled = _install_base(dialog)
    if canceled:
        # User cancelled the progress dialog mid-install: abort cleanly with NO
        # summary, NO self-uninstall, NO restart (exactly today's behaviour). The
        # partial install is harmless and re-running Setup completes it.
        return dialog.close()

    # --- optional video install (unattended, in this one script) ---
    video_installed = video_total = 0
    if video is not None and video_selected:
        video_installed, video_total = _install_video(video, video_selected, dialog)

    dialog.close()

    # --- one combined summary ---
    lines = [
        f"Repos: {repo_ok}/{len(REPO_ZIPS)}",
        f"Patches: {fp_ok}/{len(FIRST_PARTY)}",
        f"Apps: {app_ok}/{len(ADDONS)}",
    ]
    if video_total:
        lines.append(f"Video add-ons: {video_installed}/{video_total}")
    elif video_load_failed:
        # Yes was chosen but the Video Add-ons Setup could not be installed/loaded
        # — say so plainly instead of silently dropping the whole video step.
        lines.append("Video add-ons: could not load Video Setup (skipped)")
    lines.append("Open Add-ons to finish any remaining setup.")
    xbmcgui.Dialog().ok("Tony.7.Bones Setup", "\n".join(lines))

    # Run once, then disappear. Done AFTER the summary; never raises.
    self_uninstall(MY_ID, _log)
    # If we chained the Video Add-ons Setup, remove ITS tile too (the standalone
    # video run removes itself; the chained run never reaches that code, so the
    # base run cleans it up here). The shared library is a hidden module add-on
    # and is deliberately LEFT installed. Guarded + never-raises by self_uninstall.
    if video is not None and video_selected:
        self_uninstall("script.tony7bones.video", _log)
    # Add our File-Manager sources (Kodi home + sources dirs) — before the restart.
    _add_file_sources()
    # Trim the stock Estuary home menu — before the restart so Estuary re-reads it.
    _trim_home_menu()
    # Weather provider + Sacramento location, RSS ticker on (custom feeds if
    # present), top-bar weather on.
    _configure_box()
    # ONE restart finalises every freshly extracted add-on AND the self-removal.
    restart_kodi("Tony.7.Bones Setup", _log)


VIDEO_ID = "script.tony7bones.video"
MODULE_ID = "script.module.tony7bones"


def _video_default_py_path():
    """Absolute path to the installed Video Add-ons Setup's default.py."""
    return xbmcvfs.translatePath(f"special://home/addons/{VIDEO_ID}/default.py")


def _module_init_py_path():
    """Absolute path to the installed shared library's package __init__.py."""
    return xbmcvfs.translatePath(
        f"special://home/addons/{MODULE_ID}/lib/tony7bones/__init__.py"
    )


def _ensure_video_setup_installed():
    """Make sure the Video Add-ons Setup add-on (and its shared library) are on
    the box so the one-shot can load and reuse them.

    On a fresh box the user installs our repo and runs THIS base Setup; the Video
    Add-ons Setup add-on is usually not installed yet. Without it _load_video_module()
    returns None and the chosen video step silently vanishes (the one-shot bug).
    So when the user opts into video we direct-extract script.tony7bones.video
    (and script.module.tony7bones if missing) from our Pages repo — the same
    download+extract+rescan+enable path the rest of Setup uses, no blocking
    InstallAddon modal — then enable them. Idempotent: anything already present
    is skipped. Defensive: any failure is logged and swallowed; _load_video_module()
    then reports the load failure and run() surfaces it in the summary.
    """
    try:
        # The shared library underpins the video module's imports — fetch it first
        # if it is somehow absent (normally installed already as our dependency).
        if not os.path.isfile(_module_init_py_path()):
            url = _latest_zip_url(MODULE_ID)
            if url:
                extract_zip(url, None, 100, _log)
        # The video Setup add-on itself.
        if not os.path.isfile(_video_default_py_path()):
            url = _latest_zip_url(VIDEO_ID)
            if url:
                _log(f"fetching {VIDEO_ID} for one-shot video chaining", xbmc.LOGINFO)
                extract_zip(url, None, 100, _log)
        # Rescan + enable so the freshly extracted dirs register and load.
        update_local_addons()
        xbmc.sleep(2000)
        _enable(MODULE_ID)
        _enable(VIDEO_ID)
    except Exception as e:  # noqa: BLE001 - best-effort; _load_video_module reports
        _log(f"_ensure_video_setup_installed failed (non-fatal): {e}", xbmc.LOGERROR)


def _load_video_module():
    """Import the installed Video Add-ons Setup's default.py as a module so its
    config (APPS / PRESELECT / DISABLE_AFTER_INSTALL) and helpers can be reused.

    Returns the module, or None if the video Setup is not installed on the box.
    The video default.py is __main__-guarded, so importing it runs no install.
    """
    try:
        import importlib.util

        path = xbmcvfs.translatePath(
            "special://home/addons/script.tony7bones.video/default.py"
        )
        if not os.path.isfile(path):
            _log("video Setup not installed; running base only", xbmc.LOGINFO)
            return None
        spec = importlib.util.spec_from_file_location("video_setup", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    except Exception as e:  # noqa: BLE001 - video chaining is best-effort
        _log(f"could not load video Setup (running base only): {e}", xbmc.LOGERROR)
        return None


def _install_video(video, selected, dialog):
    """Install the chosen video apps + closure via the video Setup's own logic,
    sharing this run's progress dialog. Returns (installed_ok, total_selected).

    Delegates to video.install_selected(), the standalone-and-chained entry point
    the video module exposes, so the chained path and the standalone path run the
    exact same code. No separate restart/self-uninstall happens here — the base
    run owns the single restart and the video Setup's tile is removed by the base
    run too (see run())."""
    try:
        installed_ok = video.install_selected(selected, dialog)
        return installed_ok, len(selected)
    except Exception as e:  # noqa: BLE001 - a video failure must not abort base
        _log(f"video install failed (non-fatal): {e}", xbmc.LOGERROR)
        return 0, len(selected)


if __name__ == "__main__":
    run()
