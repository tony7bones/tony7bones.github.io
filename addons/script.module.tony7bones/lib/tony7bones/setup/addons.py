"""apply_addons — Layer 2 (Add-ons) of the modular setup.

The Add-ons layer is the curated content gate: the base source repos + base apps
(install_base), the curated video add-ons (install_video, incl. the install-then-
disable of ``plugin.video.dailymotion_com``), and the env-driven weather + RSS
writers (apply_weather_from_env / apply_rss_from_env). Stop here = the full box.

This module holds the bodies LIFTED VERBATIM out of
``script.tony7bones.bootstrap/default.py`` (Phase 2c) — ``_install_base`` /
``_install_video`` / ``_apply_weather_from_env`` / ``_apply_rss_from_env`` (+ their
helpers/constants), behaviour-identical. ``default.py`` now keeps thin re-export
shims that delegate here so every existing reference and test
(``boot.mod._install_base`` / ``_install_video`` / ``_apply_weather_from_env`` /
``_apply_rss_from_env`` + ``VIDEO_APPS`` / ``ADDONS`` / ``_weather_multi_settings_path``
…) keeps working unchanged.

THE INTERLEAVING CONSTRAINT (the hard part — read before touching ``run()``).
In the monolith ``run()`` the order is: base install -> video install ->
``apply_foundation`` -> summary/self-uninstall -> ``_configure_box`` (weather/IPTV/
RSS) -> activate-skin -> restart. So the base/video INSTALL runs EARLY and the
weather/RSS CONFIG runs LATE, interleaved with the Foundation layer and the
terminal seam. ``run()`` MUST keep calling the individual install/config bodies in
those EXACT slots (via the ``default.py`` shims) so the characterization snapshot
stays byte-identical. The composed ``apply_addons`` below runs install+config
TOGETHER and is provided for the Phase-4 orchestrator (which will reorder with a
deliberate snapshot update); it is NOT called from ``run()`` yet.

NO deps-injection seam (Tech-debt ledger, Phase 2b). The moved bodies resolve their
install primitives from THIS module's globals (``extract_zip`` / ``install_with_deps``
/ ``install_selection`` / ``update_local_addons`` / ``enable`` / ``_latest_zip_url``).
A ``run()``-driven test that wants to stub those for the base/video path patches
them on THIS module (``addons.*``), not via an injected ``deps`` object — the few
legacy ``boot.mod.*`` patches were repointed here. (The Foundation layer's
``_BootSkinDeps`` seam stays transitional and is killed at the Phase-4 orchestrator.)
"""

import os
from xml.etree import ElementTree as ET

import xbmc
import xbmcvfs

from tony7bones import (
    extract_zip,
    install_selection,
    install_with_deps,
    update_local_addons,
)
from tony7bones import enable as _enable

from .env import split_list
from .result import LayerResult

MY_ID = "script.tony7bones.bootstrap"

# --------------------------------------------------------------------------- #
# Index bases + add-on ids (lifted verbatim from default.py).
# --------------------------------------------------------------------------- #
STATIC_BASE = "https://tony7bones.github.io/addons"
REPO_BASE = "https://tony7bones.github.io/repositories/"
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
# the MOD V2 skin + the MOD V2+ patch add-on are installed by the Foundation layer
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

# Curated video add-ons — installed unattended (no picker) in the one-tap run.
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
# Base install (repos + first-party + apps).
# --------------------------------------------------------------------------- #
def _install_base(dialog):
    """Run the base install: repos + first-party + apps. Returns (repo_ok, fp_ok,
    app_ok, canceled). Shares the progress dialog with the (optional) video stage
    so the user sees one continuous progress bar. `canceled` is True if the user
    cancelled the progress dialog mid-install (run() then aborts with no summary,
    exactly today's behaviour).

    Resolves its install primitives (extract_zip / _latest_zip_url /
    update_local_addons / enable / install_with_deps) from THIS module's globals,
    so a test that stubs the base path patches them here (addons.*) — no injected
    deps seam (Tech-debt ledger)."""
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


# --------------------------------------------------------------------------- #
# Curated video add-ons — installed unattended (no picker).
# --------------------------------------------------------------------------- #
def _install_video(dialog):
    """Install the curated video add-ons + their closure, unattended.

    Delegates to the shared library's install_selection (folded in from the
    retired standalone Video Add-ons Setup): enable the source repos, build the
    combined index from the installed repos + the official repo, resolve the
    closure for VIDEO_APPS, extract/enable/origin-stamp it, and apply the
    install-then-disable set. Shares this run's progress dialog. Returns how many
    of VIDEO_APPS ended up installed. Never raises — a video failure must not
    abort the box.

    Resolves install_selection from THIS module's globals, so a run()-driven test
    that stubs the video path patches addons.install_selection (the repointed
    boot.mod patch) — no injected deps seam."""
    try:
        return install_selection(
            VIDEO_APPS, OFFICIAL_BASE, VIDEO_DISABLE_AFTER, dialog, _log
        )
    except Exception as e:  # noqa: BLE001 - video failure must not abort the run
        _log(f"video install failed (non-fatal): {e}", xbmc.LOGERROR)
        return 0


# --------------------------------------------------------------------------- #
# Weather (Multi Weather) — env-driven, with a keyless Sacramento fallback.
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


# --------------------------------------------------------------------------- #
# RSS news ticker — env-driven.
# --------------------------------------------------------------------------- #
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


# --------------------------------------------------------------------------- #
# The Add-ons layer entry point (composed install + config).
# --------------------------------------------------------------------------- #
def apply_addons(env, *, dialog=None, log=None):
    """Apply Layer 2 (Add-ons): the base source repos + base apps, the curated
    video add-ons (incl. the install-then-disable of plugin.video.dailymotion_com),
    and the env-driven weather + RSS writers — returning a LayerResult.

    Behaviour-preserving COMPOSITION of the monolith's ``_install_base`` /
    ``_install_video`` + the weather/RSS halves of ``_configure_box``. This runs
    install AND config together (install first, then config), which is the SHAPE
    the Phase-4 orchestrator wants. It is deliberately NOT called from ``run()``
    yet — ``run()`` keeps calling the individual bodies (via the bootstrap shims)
    in their EXISTING interleaved slots (base/video EARLY, weather/RSS LATE inside
    ``_configure_box``) so the characterization snapshot stays byte-identical.
    The orchestrator will adopt ``apply_addons`` with a deliberate snapshot update.

    The IPTV + device-copy parts of ``_configure_box`` are NOT here — they go to
    ``apply_iptv`` (Phase 2d). This layer touches only repos/apps/video + weather +
    RSS.

    Parameters
    ----------
    env
        The already-parsed per-device env dict (passed in by the orchestrator; the
        weather/RSS writers read WEATHER_LOCATIONS / WEATHERBIT_API_KEY /
        OWM_API_KEY / RSS_FEEDS / RSS_INTERVAL from it). ``None`` is treated as the
        empty env (the keyless Sacramento weather fallback, no RSS write).
    dialog
        The shared progress dialog (or ``None``); forwarded to the base + video
        install so the user sees one continuous progress bar.
    log
        The logging callable; reserved for future per-layer logging — the lifted
        bodies keep using this module's ``_log`` so their log lines stay identical
        to the monolith.

    Returns
    -------
    LayerResult
        ``layer="addons"``. ``ok`` is True unless the user cancelled the base
        install mid-run. ``installed`` records the base apps + repos + video apps
        that landed and ``failed`` records the apps that did not (so the
        orchestrator can decide before restarting). ``disabled`` add-ons (the
        install-then-disable set) are recorded in ``installed`` with state
        "disabled". ``already_done`` reflects a true no-op re-entry (nothing
        installed, nothing newly-failed) — NOT cargo-culted always-False.
        ``needs_restart=True`` is a REQUEST the orchestrator owns.
    """
    env = env or {}

    # --- install (base repos + apps, then curated video) ---
    repo_ok, _fp_ok, app_ok, canceled = _install_base(dialog)
    installed = {}
    failed = {}
    for i, (_zip_name, rid) in enumerate(REPO_ZIPS):
        # repo_ok counts the leading successes (extract loop is ordered); record
        # the ones that landed as installed, the rest as failed.
        (installed if i < repo_ok else failed)[rid] = (
            "installed" if i < repo_ok else "extract failed"
        )
    for i, aid in enumerate(ADDONS):
        (installed if i < app_ok else failed)[aid] = (
            "installed" if i < app_ok else "install failed"
        )

    video_ok = 0
    if not canceled:
        video_ok = _install_video(dialog)
        # install_selection installs VIDEO_APPS' closure + the disable-after set.
        for i, aid in enumerate(VIDEO_APPS):
            (installed if i < video_ok else failed)[aid] = (
                "installed" if i < video_ok else "video install failed"
            )
        # The install-then-disable set is a side effect of the video install
        # (The Loop pulls dailymotion); only stamp it when video actually
        # installed something, so a true no-op (no video apps installed) does not
        # spuriously report a "disabled" install and flip already_done.
        if video_ok:
            for aid in VIDEO_DISABLE_AFTER:
                installed[aid] = "disabled"

    # --- config (env-driven weather + RSS) ---
    if not canceled:
        _apply_weather_from_env(env)
        _apply_rss_from_env(env)

    # A cancelled base install is the only not-ok path (it aborts with no summary
    # in the monolith). NOTE: already_done here means "no work was CONFIGURED"
    # (empty install lists) — NOT "the box is already provisioned". The install
    # primitives don't distinguish already-present from freshly-installed, so on a
    # real re-entry against a set-up box `installed` is full and already_done is
    # False. True re-entry detection is the orchestrator's installed-state probes
    # (Phase 4), not this field — don't build idempotence on it.
    ok = not canceled
    already_done = ok and not installed and not failed
    detail = (
        "cancelled mid-install"
        if canceled
        else "repos=%d apps=%d video=%d" % (repo_ok, app_ok, video_ok)
    )
    return LayerResult(
        layer="addons",
        ok=ok,
        already_done=already_done,
        installed=installed,
        failed=failed,
        needs_restart=not canceled,
        detail=detail,
    )
