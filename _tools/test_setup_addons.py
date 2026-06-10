"""Unit tests for the Add-ons layer (Phase 2c).

``tony7bones.setup.addons`` holds the LIFTED bodies of the monolith's
``_install_base`` (base repos + apps), ``_install_video`` (curated video add-ons,
incl. the install-then-disable of ``plugin.video.dailymotion_com``), and the
weather + RSS env-writers (``_apply_weather_from_env`` / ``_apply_rss_from_env``)
out of ``script.tony7bones.bootstrap/default.py`` — behaviour-identical. It also
adds the composed ``apply_addons`` layer entry point (install + config together),
which the Phase-4 orchestrator will adopt; ``run()`` does NOT call it yet (it keeps
calling the individual bodies in their existing interleaved slots so the
characterization snapshot stays byte-identical).

These tests drive the addons module DIRECTLY against the shared fake-Kodi ``boot``
fixture (conftest.py) — the same real engine the bootstrap suite uses, reached via
``boot.mod._addons`` (the addons module the bootstrap imports under the fake Kodi).
This is the behaviour-preserving oracle for the move: the lifted bodies must land
the SAME state the monolith's inline functions did. The whole-``run()`` interleaving
is pinned separately by the modular_setup characterization snapshot; here we pin the
layer (and its parts) in isolation. No deps-injection seam — the moved bodies resolve
their install primitives from the addons module globals, so the tests patch
``addons.*`` directly (the repointed boot.mod patches).
"""

from __future__ import annotations

import os
from xml.etree import ElementTree as ET


def _addons(boot):
    """The addons module bound under the fake Kodi (via the bootstrap)."""
    return boot.mod._addons


def _settings_set(boot):
    """{setting_id: value} from captured Settings.SetSettingValue JSON-RPC calls."""
    import json

    out = {}
    for s in boot.state["jsonrpc"]:
        try:
            d = json.loads(s)
        except ValueError:
            continue
        if d.get("method") == "Settings.SetSettingValue":
            out[d["params"]["setting"]] = d["params"]["value"]
    return out


def _weather_settings(boot):
    """Multi Weather settings.xml as {id: text} (or {} if unwritten)."""
    add = _addons(boot)
    path = add._weather_multi_settings_path()
    if not os.path.exists(path):
        return {}
    root = ET.parse(path).getroot()
    return {s.get("id"): (s.text or "") for s in root.findall("setting")}


def _rss_path(boot):
    return boot.mod.xbmcvfs.translatePath("special://home/userdata/RssFeeds.xml")


# --------------------------------------------------------------------------- #
# _install_base — base repos + apps install (real engine).
# --------------------------------------------------------------------------- #
def test_install_base_installs_all_repos_and_apps(boot):
    """The base install extracts + enables all 12 repos and installs the 3 base
    apps with their closure through the real engine (the bare fake index resolves
    them). Returns (repo_ok, fp_ok, app_ok, canceled) = (12, 0, 3, False).

    Phase 3a: the base apps are now 3 (ezmaintenanceplus, realdebrid, weather.multi)
    — pvr.iptvsimple's install moved OUT of the base ADDONS into apply_iptv, so it is
    no longer installed by _install_base. A full run still installs it via the IPTV
    layer (pinned by test_modular_setup.py's net-set equivalence invariant)."""
    add = _addons(boot)
    repo_ok, fp_ok, app_ok, canceled = add._install_base(
        boot.mod.xbmcgui.DialogProgress()
    )
    assert (repo_ok, fp_ok, app_ok, canceled) == (12, 0, 3, False)
    assert len(add.ADDONS) == 3 and "pvr.iptvsimple" not in add.ADDONS, (
        "pvr.iptvsimple must have moved out of the base ADDONS list (Phase 3a)"
    )
    # Every repo zip is extracted on disk (membership keyed on the inner id; the
    # pre-existing repository.diggz vs repository.diggz.zip quirk is faithfully
    # pinned by the characterization snapshot, so allow either spelling here).
    for _zip, rid in add.REPO_ZIPS:
        assert rid in boot.state["extracted"] or rid + ".zip" in boot.state["extracted"]
    # The four base apps install (with their closure) and end up enabled/installed.
    for aid in add.ADDONS:
        assert aid in boot.state["installed"], f"{aid} must install"


def test_install_base_cancel_aborts_midway(boot, monkeypatch):
    """A cancelled progress dialog mid-install returns canceled=True (run() then
    aborts with no summary — the monolith's early-return contract)."""
    add = _addons(boot)

    class _Cancel:
        def create(self, *a):
            pass

        def update(self, *a):
            pass

        def iscanceled(self):
            return True

        def close(self):
            pass

    repo_ok, fp_ok, app_ok, canceled = add._install_base(_Cancel())
    assert canceled is True


def test_install_base_cancel_during_apps(boot, monkeypatch):
    """Cancelling AFTER the repos (during the app-install loop) returns canceled=True
    with the repos counted (the app-loop cancel branch)."""
    add = _addons(boot)
    polls = {"n": 0}

    class _LateCancel:
        def create(self, *a):
            pass

        def update(self, *a):
            pass

        def iscanceled(self):
            # Let all 12 repo polls pass, then cancel on the first app poll.
            polls["n"] += 1
            return polls["n"] > 12

        def close(self):
            pass

    repo_ok, _fp, _app, canceled = add._install_base(_LateCancel())
    assert canceled is True and repo_ok == 12


def test_install_base_installs_first_party_when_present(boot, monkeypatch):
    """When FIRST_PARTY is non-empty each id is direct-extracted via its live zip
    URL (the first-party loop — empty in production, exercised here)."""
    add = _addons(boot)
    extracts = []
    monkeypatch.setattr(add, "FIRST_PARTY", ["script.tony7bones.modv2plus"])
    monkeypatch.setattr(
        add, "_latest_zip_url", lambda aid: f"http://local/{aid}-1.2.3.zip"
    )
    monkeypatch.setattr(
        add, "extract_zip", lambda url, *a, **k: extracts.append(url) or True
    )
    _repo, fp_ok, _app, canceled = add._install_base(boot.mod.xbmcgui.DialogProgress())
    assert fp_ok == 1 and canceled is False
    assert any("script.tony7bones.modv2plus-1.2.3.zip" in u for u in extracts)


def test_install_base_resolves_primitives_from_addons_globals(boot, monkeypatch):
    """No deps-injection seam: _install_base reads extract_zip / install_with_deps
    from the addons module globals, so patching addons.* drives it (the repointed
    boot.mod patch). Stub both to count calls and prove the patch takes effect."""
    add = _addons(boot)
    extracts = []
    deps = []
    monkeypatch.setattr(
        add, "extract_zip", lambda url, *a, **k: extracts.append(url) or True
    )
    monkeypatch.setattr(
        add, "install_with_deps", lambda aid, *a, **k: deps.append(aid) or True
    )
    repo_ok, _fp, app_ok, _c = add._install_base(boot.mod.xbmcgui.DialogProgress())
    assert repo_ok == 12 and len(extracts) == 12, "addons.extract_zip patch must apply"
    # 3 base apps post-Phase-3a (pvr.iptvsimple moved to the IPTV layer); the
    # install_with_deps patch is driven once per base app, in ADDONS order.
    assert app_ok == 3 and deps == list(add.ADDONS), (
        "addons.install_with_deps patch must apply to every base app"
    )


# --------------------------------------------------------------------------- #
# _install_video — curated video + install-then-disable.
# --------------------------------------------------------------------------- #
def test_install_video_installs_four_apps_and_disables_dailymotion(boot, monkeypatch):
    """The video step installs VIDEO_APPS via install_selection and passes the
    install-then-disable set (plugin.video.dailymotion_com)."""
    add = _addons(boot)
    calls = []

    def _sel(selected, official_base, disable_ids, dialog, log):
        calls.append((list(selected), set(disable_ids)))
        return len(selected)

    monkeypatch.setattr(add, "install_selection", _sel)
    n = add._install_video(boot.mod.xbmcgui.DialogProgress())
    assert n == 4
    assert calls[0][0] == [
        "plugin.video.pov",
        "plugin.video.the-loop",
        "plugin.video.sporthdme",
        "plugin.video.youtube",
    ]
    assert "plugin.video.dailymotion_com" in calls[0][1]


def test_install_video_failure_is_nonfatal(boot, monkeypatch):
    """A video install failure must not raise — _install_video swallows it and
    returns 0 (a video failure must never abort the box)."""
    add = _addons(boot)

    def _boom(*a, **k):
        raise RuntimeError("video boom")

    monkeypatch.setattr(add, "install_selection", _boom)
    assert add._install_video(boot.mod.xbmcgui.DialogProgress()) == 0


def test_video_disable_after_is_dailymotion_only(boot):
    """The install-then-disable set is exactly plugin.video.dailymotion_com."""
    add = _addons(boot)
    assert add.VIDEO_DISABLE_AFTER == {"plugin.video.dailymotion_com"}


# --------------------------------------------------------------------------- #
# _apply_weather_from_env — env-driven Multi Weather settings.
# --------------------------------------------------------------------------- #
def test_apply_weather_resolves_locations_and_keys(boot, monkeypatch):
    """Up to N resolved locations land as loc1..N (+ unused slots cleared), and the
    Weatherbit / OWM keys enable the optional upgrade layers."""
    add = _addons(boot)
    locs = {
        "Sacramento": {
            "name": "Sacramento, CA, US",
            "url": "us/ca/sacramento",
            "lat": "38.5",
            "lon": "-121.4",
        },
        "Reno": {
            "name": "Reno, NV, US",
            "url": "us/nv/reno",
            "lat": "39.5",
            "lon": "-119.8",
        },
    }
    monkeypatch.setattr(
        add,
        "_resolve_weather_location",
        lambda q, **k: next((v for n, v in locs.items() if n in q), None),
    )
    add._apply_weather_from_env(
        {
            "WEATHER_LOCATIONS": "Sacramento, CA; Reno, NV",
            "WEATHERBIT_API_KEY": "WBITKEY",
            "OWM_API_KEY": "OWMKEY",
        }
    )
    got = _weather_settings(boot)
    assert got["loc1_url"] == "us/ca/sacramento"
    assert got["loc2_url"] == "us/nv/reno"
    assert got["loc3_url"] == ""  # unused slot cleared, never stale
    assert got["WAdd"] == "true" and got["API"] == "WBITKEY"
    assert got["WMaps"] == "true" and got["MAPAPI"] == "OWMKEY"


def test_apply_weather_falls_back_to_sacramento_never_empty(boot, monkeypatch):
    """No resolvable env locations -> the keyless Sacramento default, NEVER an
    empty loc1_url (the load-bearing fetch field)."""
    add = _addons(boot)
    monkeypatch.setattr(add, "_resolve_weather_location", lambda q, **k: None)
    add._apply_weather_from_env({"WEATHER_LOCATIONS": "Nowhere, ZZ"})
    got = _weather_settings(boot)
    assert got["loc1_url"] == "us/ca/sacramento" and got["loc1_url"]
    assert "WAdd" not in got  # no keys -> no upgrade layer


def test_apply_weather_skips_unresolvable_keeps_resolved_no_gap(boot, monkeypatch):
    """An unresolvable location is skipped; the resolved one becomes loc1 (no gap)."""
    add = _addons(boot)
    monkeypatch.setattr(
        add,
        "_resolve_weather_location",
        lambda q, **k: (
            {"name": "Reno, NV, US", "url": "us/nv/reno", "lat": "39", "lon": "-119"}
            if "Reno" in q
            else None
        ),
    )
    add._apply_weather_from_env({"WEATHER_LOCATIONS": "Badtown; Reno, NV"})
    got = _weather_settings(boot)
    assert got["loc1_url"] == "us/nv/reno"
    assert got.get("loc2_url", "") == ""


def test_apply_weather_never_raises(boot, monkeypatch):
    """Defensive: any failure inside the writer is swallowed (never aborts setup)."""
    add = _addons(boot)

    def _boom(*a, **k):
        raise RuntimeError("boom")

    monkeypatch.setattr(add, "_set_weather_settings", _boom)
    add._apply_weather_from_env({"WEATHER_LOCATIONS": ""})  # must not raise


# --------------------------------------------------------------------------- #
# _apply_rss_from_env — env-driven RssFeeds.xml.
# --------------------------------------------------------------------------- #
def test_apply_rss_writes_feeds_with_interval(boot):
    """RSS_FEEDS -> userdata/RssFeeds.xml with each feed at the RSS_INTERVAL."""
    add = _addons(boot)
    add._apply_rss_from_env(
        {"RSS_FEEDS": "http://a/feed; http://b/feed", "RSS_INTERVAL": "45"}
    )
    feeds = ET.parse(_rss_path(boot)).getroot().findall("set/feed")
    assert [f.text for f in feeds] == ["http://a/feed", "http://b/feed"]
    assert all(f.get("updateinterval") == "45" for f in feeds)


def test_apply_rss_noop_when_absent(boot):
    """No RSS_FEEDS -> no write (a device-copied file / the Kodi default stands)."""
    add = _addons(boot)
    add._apply_rss_from_env({})
    assert not os.path.exists(_rss_path(boot))


def test_apply_rss_default_interval_is_30(boot):
    """Absent RSS_INTERVAL defaults to 30 (the monolith's default)."""
    add = _addons(boot)
    add._apply_rss_from_env({"RSS_FEEDS": "http://a/feed"})
    feeds = ET.parse(_rss_path(boot)).getroot().findall("set/feed")
    assert feeds[0].get("updateinterval") == "30"


def test_apply_rss_never_raises(boot, monkeypatch):
    """Defensive: a write failure is swallowed (never aborts the rest of setup)."""
    add = _addons(boot)

    def _boom(*a, **k):
        raise OSError("disk full")

    monkeypatch.setattr(add.os, "makedirs", _boom)
    add._apply_rss_from_env({"RSS_FEEDS": "http://a/feed"})  # must not raise
    assert not os.path.exists(_rss_path(boot))


# --------------------------------------------------------------------------- #
# Helpers exercised through the real engine (the conftest urlopen fake).
# --------------------------------------------------------------------------- #
def test_latest_zip_url_resolves_from_static_addon_xml(boot):
    """_latest_zip_url reads the static addon.xml and builds the versioned zip URL
    (the conftest fake serves an addon.xml at version 1.0.0)."""
    add = _addons(boot)
    url = add._latest_zip_url("script.tony7bones.modv2plus")
    assert url == (
        "https://tony7bones.github.io/addons/"
        "script.tony7bones.modv2plus/script.tony7bones.modv2plus-1.0.0.zip"
    )


def test_latest_zip_url_returns_none_on_error(boot, monkeypatch):
    """A network/parse failure -> None (logged, never raises)."""
    add = _addons(boot)

    def _boom(*a, **k):
        raise OSError("no network")

    monkeypatch.setattr("urllib.request.urlopen", _boom)
    assert add._latest_zip_url("script.whatever") is None


def test_resolve_weather_location_returns_none_on_bad_response(boot):
    """The conftest urlopen fake returns empty bytes for the Yahoo search-assist
    endpoint, so the JSON parse fails on every retry -> None (the caller then falls
    back to the Sacramento default). Exercises the real network/parse body."""
    add = _addons(boot)
    assert add._resolve_weather_location("Sacramento, CA") is None


def test_resolve_weather_location_parses_suggestions(boot, monkeypatch):
    """A well-formed search-assist response is parsed into {name,url,lat,lon} in the
    add-on's own field shape (name 'Town, Region, Country'; url 'country/region/town')."""
    import json as _json

    add = _addons(boot)
    payload = {
        "suggestions": [
            {
                "location": {
                    "town": {"name": "Reno", "latitude": 39.5, "longitude": -119.8},
                    "region": {"code": "NV"},
                    "country": {"code": "US"},
                }
            }
        ]
    }

    class _Resp:
        def read(self):
            return _json.dumps(payload).encode("utf-8")

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr("urllib.request.urlopen", lambda req, timeout=None: _Resp())
    loc = add._resolve_weather_location("Reno, NV")
    assert loc == {
        "name": "Reno, NV, US",
        "url": "us/nv/reno",
        "lat": "39.5",
        "lon": "-119.8",
    }


def test_set_weather_settings_recreates_malformed_file(boot):
    """A malformed Multi Weather settings.xml is replaced with a valid tree (the
    ET.ParseError recovery branch) while still writing the requested settings."""
    add = _addons(boot)
    path = add._weather_multi_settings_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write("<<not xml>>")
    add._set_weather_settings({"loc1_url": "us/ca/sacramento"})
    got = _weather_settings(boot)
    assert got["loc1_url"] == "us/ca/sacramento"


def test_set_weather_location_default_is_sacramento(boot):
    """The keyless fallback writes the Sacramento default location."""
    add = _addons(boot)
    add._set_weather_location()
    got = _weather_settings(boot)
    assert got["loc1_url"] == "us/ca/sacramento"
    assert "Sacramento" in got["loc1_name"]


# --------------------------------------------------------------------------- #
# apply_addons — the composed Layer 2 entry point (install + config).
# --------------------------------------------------------------------------- #
def test_apply_addons_returns_addons_layerresult_on_success(boot, monkeypatch):
    """The composed layer installs base + video, writes weather/RSS, and returns a
    LayerResult(layer='addons', ok=True) recording the installed ids + the
    install-then-disable set, requesting a restart."""
    add = _addons(boot)

    def _sel(selected, official_base, disable_ids, dialog, log):
        return len(selected)

    monkeypatch.setattr(add, "install_selection", _sel)
    monkeypatch.setattr(add, "_resolve_weather_location", lambda q, **k: None)

    res = add.apply_addons(
        {"RSS_FEEDS": "http://a/feed"},
        dialog=boot.mod.xbmcgui.DialogProgress(),
        log=boot.mod._log,
    )
    assert res.layer == "addons"
    assert res.ok is True
    assert res.needs_restart is True
    assert res.already_done is False
    # base apps + repos + video apps all recorded installed
    for aid in add.ADDONS:
        assert res.installed.get(aid) == "installed"
    for aid in add.VIDEO_APPS:
        assert res.installed.get(aid) == "installed"
    # the install-then-disable set is recorded as disabled
    assert res.installed.get("plugin.video.dailymotion_com") == "disabled"
    # config ran: weather (Sacramento fallback) + RSS feed written
    assert _weather_settings(boot)["loc1_url"] == "us/ca/sacramento"
    assert os.path.exists(_rss_path(boot))


def test_apply_addons_cancel_is_not_ok_and_skips_config(boot, monkeypatch):
    """A cancelled base install -> ok=False, no restart requested, and the
    weather/RSS config is SKIPPED (the monolith aborts with no summary on cancel)."""
    add = _addons(boot)
    weather_calls = []
    monkeypatch.setattr(
        add, "_install_base", lambda dialog: (3, 0, 0, True)
    )  # canceled
    monkeypatch.setattr(
        add, "_apply_weather_from_env", lambda env: weather_calls.append(env)
    )
    res = add.apply_addons({"RSS_FEEDS": "http://a/feed"}, dialog=None, log=None)
    assert res.ok is False
    assert res.needs_restart is False
    assert weather_calls == [], "config must not run on a cancelled install"
    assert not os.path.exists(_rss_path(boot))


def test_apply_addons_records_failed_apps(boot, monkeypatch):
    """When fewer apps install than requested, the shortfall is recorded in
    failed{} so the orchestrator can decide before restarting (not always-empty)."""
    add = _addons(boot)
    # base: all repos ok, only 2 of 4 apps ok; video: 0.
    monkeypatch.setattr(add, "_install_base", lambda dialog: (12, 0, 2, False))
    monkeypatch.setattr(add, "_install_video", lambda dialog: 0)
    monkeypatch.setattr(add, "_apply_weather_from_env", lambda env: None)
    monkeypatch.setattr(add, "_apply_rss_from_env", lambda env: None)
    res = add.apply_addons({}, dialog=None, log=None)
    assert res.ok is True  # not cancelled -> ok (degraded)
    assert res.installed.get(add.ADDONS[0]) == "installed"
    assert res.failed.get(add.ADDONS[2]) == "install failed"
    # all four video apps failed (0 installed)
    for aid in add.VIDEO_APPS:
        assert res.failed.get(aid) == "video install failed"


def test_apply_addons_already_done_when_no_work_configured(boot, monkeypatch):
    """already_done means 'no work was CONFIGURED' (empty repo/app/video sets) —
    NOT 'box already provisioned' (install primitives can't tell already-present
    from freshly-installed). It is honestly computed, not cargo-culted always-False;
    real re-entry detection is the Phase-4 orchestrator's installed-state probes."""
    add = _addons(boot)
    monkeypatch.setattr(add, "REPO_ZIPS", [])
    monkeypatch.setattr(add, "ADDONS", [])
    monkeypatch.setattr(add, "VIDEO_APPS", [])
    monkeypatch.setattr(add, "_install_base", lambda dialog: (0, 0, 0, False))
    monkeypatch.setattr(add, "_install_video", lambda dialog: 0)
    monkeypatch.setattr(add, "_apply_weather_from_env", lambda env: None)
    monkeypatch.setattr(add, "_apply_rss_from_env", lambda env: None)
    res = add.apply_addons({}, dialog=None, log=None)
    assert res.installed == {} and res.failed == {}
    assert res.already_done is True


def test_apply_addons_none_env_is_safe(boot, monkeypatch):
    """env=None is treated as the empty env: the keyless Sacramento weather
    fallback, no RSS write — never a crash."""
    add = _addons(boot)
    monkeypatch.setattr(add, "install_selection", lambda s, *a, **k: len(s))
    monkeypatch.setattr(add, "_resolve_weather_location", lambda q, **k: None)
    res = add.apply_addons(None, dialog=boot.mod.xbmcgui.DialogProgress(), log=None)
    assert res.ok is True
    assert _weather_settings(boot)["loc1_url"] == "us/ca/sacramento"
    assert not os.path.exists(_rss_path(boot))  # no RSS_FEEDS -> no write


# --------------------------------------------------------------------------- #
# _set_setting + the two CORE settings apply_addons owns (Phase 3a).
# --------------------------------------------------------------------------- #
def test_set_setting_emits_jsonrpc_and_reports_ok(boot):
    """_set_setting sends a Settings.SetSettingValue JSON-RPC and returns True on a
    `"result":true` reply (the fake jsonrpc returns `{}` -> False; patch a true
    reply to exercise the OK branch)."""
    add = _addons(boot)
    # Default fake jsonrpc returns "{}" -> no '"result":true' -> False.
    assert add._set_setting("weather.addon", "weather.multi") is False
    assert _settings_set(boot).get("weather.addon") == "weather.multi"


def test_set_setting_true_reply_is_ok(boot, monkeypatch):
    """A `"result":true` JSON-RPC reply makes _set_setting return True."""
    add = _addons(boot)
    monkeypatch.setattr(add.xbmc, "executeJSONRPC", lambda s: '{"result":true}')
    assert add._set_setting("lookandfeel.enablerssfeeds", True) is True


def test_apply_addons_sets_weather_provider_and_rss_core_settings(boot, monkeypatch):
    """apply_addons emits the two CORE settings the monolith's _configure_box set
    inline — weather.addon -> weather.multi and lookandfeel.enablerssfeeds -> True —
    BEFORE the env-driven weather/RSS writers, so the net core-settings end-state is
    unchanged vs the monolith."""
    add = _addons(boot)
    monkeypatch.setattr(add, "install_selection", lambda s, *a, **k: len(s))
    monkeypatch.setattr(add, "_resolve_weather_location", lambda q, **k: None)
    add.apply_addons({}, dialog=boot.mod.xbmcgui.DialogProgress(), log=None)
    s = _settings_set(boot)
    assert s.get(add.WEATHER_PROVIDER_SETTING) == add.WEATHER_ADDON
    assert s.get(add.WEATHER_PROVIDER_SETTING) == "weather.multi"
    assert s.get(add.RSS_ENABLE_SETTING) is True
    assert add.RSS_ENABLE_SETTING == "lookandfeel.enablerssfeeds"


def test_apply_addons_cancel_skips_core_settings(boot, monkeypatch):
    """On a cancelled base install, apply_addons skips the WHOLE config block — the
    two core settings are NOT emitted either (the monolith aborts with no config)."""
    add = _addons(boot)
    monkeypatch.setattr(add, "_install_base", lambda dialog: (3, 0, 0, True))
    add.apply_addons({}, dialog=None, log=None)
    s = _settings_set(boot)
    assert add.WEATHER_PROVIDER_SETTING not in s
    assert add.RSS_ENABLE_SETTING not in s
