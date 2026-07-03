"""apply_foundation — Layer 0 (Foundation) of the modular setup.

The Foundation layer is the CONTENT-FREE prerequisite phase: it installs ALL our
source repos' plumbing (the File-Manager sources, incl. the mini's KodiShare/
KodiBackup NFS shares and our own proxy source), the on-screen-keyboard
autocomplete QoL utility (script.module.autocompletion), and the branded-look
env-driven config that every later phase's box should already have — Multi
Weather (weather.multi + the env-driven location writer + the core weather.addon
setting) and the RSS news ticker (the core lookandfeel.enablerssfeeds setting +
the env-driven RssFeeds.xml writer). It installs NO skin, NO video, NO PVR — the
Estuary MOD V2 skin closure + the home-menu trim moved OUT to the Skin layer
(``tony7bones.setup.skin``, plan section 3.1/3.3): the skin is curatorial
branding, not a Foundation prerequisite.

This module holds the ``_add_file_sources`` body LIFTED VERBATIM out of
``script.tony7bones.bootstrap/default.py`` (Phase 2b), behaviour-identical.
``default.py`` keeps a thin shim that delegates here so every existing reference
and test (``boot.mod._add_file_sources``) keeps working unchanged.

This module assumes the base repos are ALREADY installed (``run()`` still installs
them via ``_install_base``/``install_repos`` before calling ``apply_foundation``).
Layer independence (the layer installing its own repos) is a LATER phase and is
deliberately NOT added here.
"""

import json
import os
import re
from xml.etree import ElementTree as ET

import xbmc
import xbmcvfs

from tony7bones import install_with_deps

from .env import split_list
from .result import LayerResult

# --------------------------------------------------------------------------- #
# Index bases + add-on ids (lifted verbatim from default.py).
# --------------------------------------------------------------------------- #
STATIC_BASE = "https://tony7bones.github.io/addons"
OFFICIAL_BASE = "https://mirrors.kodi.tv/addons/omega"

# On-screen-keyboard autocomplete — a QoL UTILITY (NOT content). On a branded box it
# helps the user type into the keyboard (search boxes, IPTV portal/login fields). It
# is a pure-python module add-on in the OFFICIAL Kodi repo (repository.xbmc.org); we
# resolve + install it through the closure resolver (install_with_deps, official base)
# so Foundation lands it alongside the branded look. It runs nothing on its own — Kodi
# wires it in as the keyboard's autocomplete provider — so installing it is safe on a
# content-free box (it is plumbing, like the skin's own dependency modules).
AUTOCOMPLETE_ID = "script.module.autocompletion"

MY_ID = "script.tony7bones.bootstrap"


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

# --------------------------------------------------------------------------- #
# The mini's NFS shares — port-free by construction (kills the `:2049` class).
# --------------------------------------------------------------------------- #
# Kodi/libnfs NFS URLs take NO port (2049/111 is the libnfs default); an explicit
# `:2049` broke the write with VfsCopyError — that bug came from hand-typing the
# share into File Manager. `_nfs_url` is the ONE place any NFS URL is built or
# sanitized in this codebase, so that class of bug cannot recur here.
_NFS_PORT_RE = re.compile(r"^nfs://([^/:]+):\d+(/.*)?$")


def _nfs_url(host_or_url, path=None):
    """Build a port-free ``nfs://`` URL from ``(host, path)``, or SANITIZE an
    existing ``nfs://...`` URL (called with just one arg) by stripping any
    ``:<port>`` after the host. Either way the result never contains a port —
    a unit test asserts this invariant across every NFS URL this module emits.
    """
    if path is None:
        m = _NFS_PORT_RE.match(host_or_url or "")
        if m:
            return "nfs://" + m.group(1) + (m.group(2) or "")
        return host_or_url
    host = str(host_or_url).split(":", 1)[0]
    return "nfs://{}/{}".format(host, str(path).lstrip("/"))


# The household mini's LAN address (constant default so this is zero-config for
# the one household this repo serves; env-overridable for reuse elsewhere).
MINI_HOST_DEFAULT = "192.168.7.2"
KODI_SHARE_PATH = "Users/moquette/Kodi/Share/"
KODI_BACKUP_PATH = "Users/moquette/Kodi/Backup/"
# Names match the mini's own SMB share names for recognizability — these are
# Kodi source LABELS only; the URL host is still the real IP, never a
# resolvable hostname.
KODI_SHARE_SOURCE_NAME = "KodiShare"
KODI_BACKUP_SOURCE_NAME = "KodiBackup"


def _mini_host(box_env):
    return (box_env.get("MINI_HOST") or "").strip() or MINI_HOST_DEFAULT


def kodi_share_url(box_env):
    """The mini's media share URL — ``KODI_SHARE_NFS`` env override if set
    (sanitized port-free regardless), else derived from ``MINI_HOST``."""
    override = (box_env.get("KODI_SHARE_NFS") or "").strip()
    return (
        _nfs_url(override)
        if override
        else _nfs_url(_mini_host(box_env), KODI_SHARE_PATH)
    )


def kodi_backup_url(box_env):
    """The mini's backup share URL — ``KODI_BACKUP_NFS`` env override if set
    (sanitized port-free regardless), else derived from ``MINI_HOST``."""
    override = (box_env.get("KODI_BACKUP_NFS") or "").strip()
    return (
        _nfs_url(override)
        if override
        else _nfs_url(_mini_host(box_env), KODI_BACKUP_PATH)
    )


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


def _normalized_path_key(path):
    """A comparison key for source normalization: strip a trailing slash, and
    for an ``nfs://`` URL also strip any ``:<port>`` — so a legacy `:2049`
    variant or a bare-vs-trailing-slash variant both match the canonical entry.
    """
    path = (path or "").strip()
    if path.startswith("nfs://"):
        path = _nfs_url(path)
    return path.rstrip("/")


def _normalize_source(files, canonical_name, canonical_url):
    """Collapse ANY existing ``<files>`` source that either points at
    ``canonical_url`` (port-stripped, trailing-slash-insensitive, under ANY
    label) OR already carries ``canonical_name`` (whatever URL it currently
    points at) onto ONE canonical entry named ``canonical_name`` at
    ``canonical_url``. Returns True if anything changed. Deliberate (not a
    dedupe): claim the source under one known name however it was added, AND
    repoint an already-claimed name at the CURRENT canonical URL.

    The by-name branch matters for a re-provisioned/host-migrated box: if
    ``MINI_HOST`` (or a ``KODI_SHARE_NFS``/``KODI_BACKUP_NFS`` override)
    changes between two runs, the OLD entry no longer matches the NEW
    canonical URL by path — without also matching by name, the stale entry
    would sit untouched forever (its name already satisfies the caller's
    dedupe-by-name check downstream, so the new URL would never get written,
    and the Foundation probe would re-offer the gate with no way to converge).
    Generalizes the original repo-source-only normalization to also cover the
    mini's NFS shares, which additionally must shed a legacy ``:2049``."""
    changed = False
    target_key = _normalized_path_key(canonical_url)
    for s in files.findall("source"):
        name_el = s.find("name")
        current_name = (name_el.text if name_el is not None else None) or ""
        path_matches = _normalized_path_key(s.findtext("path")) == target_key
        name_matches = current_name == canonical_name
        if not (path_matches or name_matches):
            continue
        if name_el is None:
            name_el = ET.SubElement(s, "name")
        if name_el.text != canonical_name:
            name_el.text = canonical_name
            changed = True
        path_el = s.find("path")
        if path_el is None:
            path_el = ET.SubElement(s, "path")
        if (path_el.text or "").strip() != canonical_url:
            path_el.text = canonical_url
            changed = True
    # Collapse any duplicates the normalization produced (e.g. both a :2049
    # variant AND a slash variant existed) down to a single canonical entry.
    seen = False
    for s in list(files.findall("source")):
        is_canonical = (s.findtext("name") or "") == canonical_name and (
            s.findtext("path") or ""
        ).strip() == canonical_url
        if is_canonical:
            if seen:
                files.remove(s)
                changed = True
            else:
                seen = True
    return changed


def _add_file_sources(box_env):
    """Add our File-Manager sources to userdata/sources.xml.

    Edits the <files> section in place: creates the file/structure if missing,
    PRESERVES every existing source, and DEDUPES new ones on both name and path so
    a second run adds nothing. Three sources are NORMALIZED (not just deduped —
    see ``_normalize_source``): our repo's bare URL, and the mini's two NFS shares
    (KodiShare/KodiBackup — computed from ``box_env``'s ``MINI_HOST``/
    ``KODI_SHARE_NFS``/``KODI_BACKUP_NFS``, port-free by construction, killing the
    `:2049` class permanently). For the Android internal-storage path we attempt
    mkdirs first (guarded) but add the source entry either way. Fully defensive:
    any error is logged and the rest of setup continues. The end-of-setup restart
    is what makes Kodi pick up the new sources (it caches sources.xml at startup).
    """
    try:
        box_env = box_env or {}
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

        share_url = kodi_share_url(box_env)
        backup_url = kodi_backup_url(box_env)
        changed = False
        changed = _normalize_source(files, REPO_SOURCE_NAME, REPO_SOURCE_URL) or changed
        changed = _normalize_source(files, KODI_SHARE_SOURCE_NAME, share_url) or changed
        changed = (
            _normalize_source(files, KODI_BACKUP_SOURCE_NAME, backup_url) or changed
        )

        # Existing names/paths in <files> — dedupe new sources against both.
        have_names = {
            (s.findtext("name") or "").strip() for s in files.findall("source")
        }
        have_paths = {
            (s.findtext("path") or "").strip() for s in files.findall("source")
        }

        added = 0
        dynamic_sources = [
            (KODI_SHARE_SOURCE_NAME, share_url),
            (KODI_BACKUP_SOURCE_NAME, backup_url),
        ]
        for name, path in FILE_SOURCES + dynamic_sources:
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
# Weather (Multi Weather) — env-driven, with a keyless Sacramento fallback.
# --------------------------------------------------------------------------- #
# weather.multi is part of the BRANDED LOOK, not content: once the Skin layer's
# MOD V2 is active it renders the weather readout + the Weather home-menu item,
# so the weather provider belongs in Foundation as a prerequisite (moved here from
# the Add-ons base ADDONS in the weather-into-Foundation change) rather than in
# the Skin layer itself. Foundation installs the add-on (with its python module
# closure) AND configures it: sets the core weather.addon provider and writes the
# env-driven (or keyless Sacramento default) locations.
WEATHER_ADDON = "weather.multi"  # Multi Weather (installed by the Foundation layer)
WEATHER_PROVIDER_SETTING = "weather.addon"  # core setting -> WEATHER_ADDON
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


def _set_setting(setting_id, value):
    """Set a CORE Kodi setting via JSON-RPC. Returns True on a clean OK.

    Reaches only CORE settings (system/weather/lookandfeel/...) — add-on INSTANCE
    settings are not reachable this way. Used here to set the core weather.addon
    provider to Multi Weather."""
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
    _log("foundation weather: wrote Multi Weather default location (Sacramento)")


def _resolve_weather_location(query, timeout=10, tries=2):
    """Resolve a city name / zipcode to a Multi Weather location via Yahoo's
    search-assist API (the trailing-slash endpoint — no redirect needed). Returns
    {name,url,lat,lon} or None on any failure (the caller falls back). Retries the
    network call; never raises. Mirrors how the add-on's own search builds the
    fields: name "Town, Region, Country"; url "country/region/town"."""
    import json as _jsonl
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
                data = _jsonl.loads(resp.read().decode("utf-8"))
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


def _install_weather(dialog, *, install=None):
    """Install Multi Weather (weather.multi) + its python module closure, by direct
    extract from the official repo. weather.multi is the BRANDED LOOK's weather
    provider (the MOD V2 skin renders a weather readout + a Weather menu item), so
    Foundation owns its install (moved here from the Add-ons base ADDONS). Returns
    True if it installed. Never raises (a weather failure must not abort the box).

    ``install`` lets a test inject the install primitive; defaults to this module's
    ``install_with_deps``."""
    install = install or install_with_deps
    try:
        if dialog is not None:
            dialog.update(0, "Installing weather...")
        return bool(install(WEATHER_ADDON, dialog, [], OFFICIAL_BASE, _log))
    except Exception as e:  # noqa: BLE001 - weather failure must not abort the box
        _log(f"weather install failed (non-fatal): {e}", xbmc.LOGERROR)
        return False


def _apply_weather(box_env, dialog=None):
    """Install + configure Multi Weather for the branded box: install the add-on,
    set the core weather.addon provider, and write the env-driven (or keyless
    Sacramento default) locations. Returns True if weather.multi installed.
    Defensive: each step logged; never raises."""
    installed = _install_weather(dialog)
    _set_setting(WEATHER_PROVIDER_SETTING, WEATHER_ADDON)
    _apply_weather_from_env(box_env or {})
    return installed


# The CORE Kodi setting the Foundation layer owns (the RSS news-ticker toggle).
# RSS is env-driven CONFIG, not content, so it moved here alongside weather —
# both are part of the branded look the Foundation layer establishes, not the
# Add-ons layer's curated-content install.
RSS_ENABLE_SETTING = "lookandfeel.enablerssfeeds"  # -> True (ticker on)


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


def _apply_rss(box_env, dialog=None):
    """Set the RSS-enable core setting, then write the env-driven RSS feeds.
    Mirrors ``_apply_weather``'s shape so ``apply_foundation`` composes both
    branded-look config steps identically. Returns True (RSS has no install step,
    so there is no failure state to report — behaviour-identical to the
    monolith's unconditional RSS config)."""
    _set_setting(RSS_ENABLE_SETTING, True)
    _apply_rss_from_env(box_env or {})
    return True


def _install_autocomplete(dialog, *, install=None):
    """Install the on-screen-keyboard autocomplete module (QoL utility, NOT content),
    by closure resolve + direct extract from the OFFICIAL Kodi repo. It helps the user
    type into Kodi's keyboard (search / IPTV portal+login fields) and runs nothing on
    its own, so it is safe on a content-free Foundation box (plumbing, like the skin's
    own dependency modules). Returns True if it installed. Never raises (a QoL utility
    failing must not abort the box).

    ``install`` lets a test inject the install primitive; defaults to this module's
    ``install_with_deps``."""
    install = install or install_with_deps
    try:
        if dialog is not None:
            dialog.update(0, "Installing keyboard autocomplete...")
        return bool(install(AUTOCOMPLETE_ID, dialog, [], OFFICIAL_BASE, _log))
    except Exception as e:  # noqa: BLE001 - a QoL utility must not abort the box
        _log(f"autocomplete install failed (non-fatal): {e}", xbmc.LOGERROR)
        return False


# --------------------------------------------------------------------------- #
# The Foundation layer entry point.
# --------------------------------------------------------------------------- #
def apply_foundation(
    env,
    *,
    dialog=None,
    log,
    add_file_sources=None,
):
    """Apply Layer 0 (Foundation): the File-Manager sources (incl. the mini's
    KodiShare/KodiBackup NFS shares and our own proxy source), the branded-look
    weather provider (weather.multi) + env-driven locations, the RSS news ticker
    (core setting + env-driven RssFeeds.xml), and the on-screen-keyboard
    autocomplete QoL utility (script.module.autocompletion). Installs NO skin —
    that is the Skin layer's job now (``tony7bones.setup.skin.apply_skin``).

    Behaviour-preserving extraction of the monolith's ``_add_file_sources``
    body, plus weather + RSS config moved here from the Add-ons layer (both are
    branded-look config, not content).

    Parameters
    ----------
    env
        The already-parsed per-device env dict (passed in by the orchestrator; the
        weather/RSS writers read WEATHER_LOCATIONS / WEATHERBIT_API_KEY /
        OWM_API_KEY / RSS_FEEDS / RSS_INTERVAL from it). ``None`` is treated as the
        empty env (the keyless Sacramento weather fallback, no RSS write).
    dialog
        The shared progress dialog (or ``None``); forwarded to the weather/
        autocomplete installs.
    log
        The logging callable (e.g. the bootstrap's ``_log``); reserved for future
        per-layer logging — the lifted bodies keep using this module's ``_log`` so
        their log lines stay byte-identical to the monolith.
    add_file_sources
        The step function, injectable. Defaults to THIS module's lifted body
        (what the standalone foundation tests drive). The bootstrap injects ITS
        module-level shim so a ``run()`` driven through monkeypatched
        ``boot.mod.*`` install primitives still routes through the patched
        function — behaviour-identical to the monolith.

    Returns
    -------
    LayerResult
        ``layer="foundation"``; ``ok`` is always ``True`` — this layer is
        content-free, best-effort config with no user-cancelable step, unlike
        Add-ons' base install. Per-addon success/failure still lands in
        ``installed``/``failed`` (weather + autocomplete failures are non-fatal,
        matching the monolith); real re-entry/completion detection is the
        orchestrator's ``foundation_done()`` probe, not this field.
    """
    add_file_sources = add_file_sources or _add_file_sources

    # The content-free base-config step that used to run inline in run() right
    # after the skin install (now a Foundation-only concern; the skin no longer
    # lives in this layer).
    add_file_sources(env or {})

    # Weather is part of the BRANDED LOOK (once the Skin layer's MOD V2 is active
    # it renders a weather readout + a Weather home-menu item), so Foundation
    # installs + configures Multi Weather as a prerequisite (moved here from the
    # Add-ons base ADDONS). Install the add-on, set the core provider, and write
    # the env-driven (or keyless Sacramento default) locations. The Outline-HD
    # weather ICONS are installed by the Skin layer's closure and modv2plus's
    # apply points WeatherIcons at them — so the branded box has working weather
    # end-to-end once both layers have run.
    weather_ok = _apply_weather(env or {}, dialog)

    # RSS news ticker is also branded-look CONFIG (env-driven, no install step),
    # so it moved here alongside weather (from the Add-ons layer). Unconditional,
    # like the monolith's RSS config — no installed/failed entry (nothing installs).
    _apply_rss(env or {}, dialog)

    # On-screen-keyboard autocomplete — a QoL utility (NOT content) that helps the
    # user type into Kodi's keyboard (search / IPTV portal+login). Install it from
    # the official repo so the branded box has it out of the box. It runs nothing on
    # its own, so it is content-free-safe.
    autocomplete_ok = _install_autocomplete(dialog)

    installed = {}
    failed = {}
    if weather_ok:
        installed[WEATHER_ADDON] = "installed"
    else:
        failed[WEATHER_ADDON] = "weather install failed"
    if autocomplete_ok:
        installed[AUTOCOMPLETE_ID] = "installed"
    else:
        failed[AUTOCOMPLETE_ID] = "autocomplete install failed"
    return LayerResult(
        layer="foundation",
        ok=True,
        installed=installed,
        failed=failed,
        needs_restart=True,
        detail="repos+sources+weather+RSS+autocomplete configured",
    )
