"""Unit tests for the Add-ons layer (Phase 2c).

``tony7bones.setup.addons`` holds the LIFTED bodies of the monolith's
``_install_base`` (base repos + apps), ``_install_video`` (curated video add-ons,
incl. the install-then-disable of ``plugin.video.dailymotion_com``), and the RSS
env-writer (``_apply_rss_from_env``) out of
``script.tony7bones.bootstrap/default.py`` — behaviour-identical. It also adds the
composed ``apply_addons`` layer entry point (install + config together), which the
Express orchestrator drives.

NOTE (weather-into-Foundation): the WEATHER provider + env-driven location config
(weather.multi install + ``_apply_weather_from_env`` + the core weather.addon
setting) MOVED OUT of the Add-ons layer INTO the Foundation layer — weather is part
of the branded look (the MOD V2 skin renders a weather readout + a Weather menu
item), not content. The weather unit tests moved with it to test_setup_foundation.py
/ test_run_foundation.py; the Add-ons layer now owns only RSS config.

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


def _rss_path(boot):
    return boot.mod.xbmcvfs.translatePath("special://home/userdata/RssFeeds.xml")


# --------------------------------------------------------------------------- #
# _install_base — base repos + apps install (real engine).
# --------------------------------------------------------------------------- #
def test_install_base_installs_all_repos_and_apps(boot):
    """The base install extracts + enables all 12 repos PLUS our own proxy repo
    (repository.tony7bones), and installs the 2 base apps with their closure through
    the real engine. Returns (repo_ok, fp_ok, app_ok, canceled) = (12, 1, 2, False)
    — fp_ok == 1 is the proxy repo (first-party plumbing).

    The base apps are now 2 (ezmaintenanceplus, realdebrid) — pvr.iptvsimple's
    install moved OUT of the base ADDONS into apply_iptv (Phase 3a) AND weather.multi
    moved OUT into apply_foundation (weather-into-Foundation). Both are still installed
    by a full run (pvr via the IPTV layer, weather via Foundation), pinned by
    test_modular_setup.py's net-set equivalence invariant."""
    add = _addons(boot)
    repo_ok, fp_ok, app_ok, canceled = add._install_base(
        boot.mod.xbmcgui.DialogProgress()
    )
    assert (repo_ok, fp_ok, app_ok, canceled) == (12, 1, 2, False)
    assert len(add.ADDONS) == 2 and "pvr.iptvsimple" not in add.ADDONS, (
        "pvr.iptvsimple must have moved out of the base ADDONS list (Phase 3a)"
    )
    assert "weather.multi" not in add.ADDONS, (
        "weather.multi must have moved out of the base ADDONS into Foundation"
    )
    # Every repo zip is extracted on disk (membership keyed on the inner id; the
    # pre-existing repository.diggz vs repository.diggz.zip quirk is faithfully
    # pinned by the characterization snapshot, so allow either spelling here).
    for _zip, rid in add.REPO_ZIPS:
        assert rid in boot.state["extracted"] or rid + ".zip" in boot.state["extracted"]
    # Our own proxy repo is established as an installed, enabled add-on (the lifeline).
    assert add.PROXY_REPO_ID in boot.state["installed"], (
        "the base install must establish our proxy repo repository.tony7bones"
    )
    # The two base apps install (with their closure) and end up enabled/installed.
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
    URL (the first-party loop — empty in production, exercised here). fp_ok == 2
    here: the modv2plus first-party AND our own proxy repo (repository.tony7bones)
    are both direct-extracted via _latest_zip_url + extract_zip (the proxy resolved
    through the same stubbed _latest_zip_url)."""
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
    assert fp_ok == 2 and canceled is False
    assert any("script.tony7bones.modv2plus-1.2.3.zip" in u for u in extracts)
    # Our proxy repo is direct-extracted too (same _latest_zip_url mechanism).
    assert any(f"{add.PROXY_REPO_ID}-1.2.3.zip" in u for u in extracts), (
        "the proxy repo must be direct-extracted alongside the first-party add-ons"
    )


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
    # 12 repo zips + 1 proxy-repo zip (repository.tony7bones) = 13 extract_zip calls;
    # the proxy URL resolves through the (unstubbed) _latest_zip_url (the fake
    # urlopen returns a version), so the addons.extract_zip patch is driven for it too.
    assert repo_ok == 12 and len(extracts) == 13, "addons.extract_zip patch must apply"
    assert any(add.PROXY_REPO_ID in u for u in extracts), (
        "the proxy repo extract must route through the patched addons.extract_zip"
    )
    # 2 base apps (pvr.iptvsimple -> IPTV layer; weather.multi -> Foundation); the
    # install_with_deps patch is driven once per base app, in ADDONS order.
    assert app_ok == 2 and deps == list(add.ADDONS), (
        "addons.install_with_deps patch must apply to every base app"
    )


# --------------------------------------------------------------------------- #
# install_repos — the reusable repo-install loop extracted out of _install_base
# (Phase 5a) so the Foundation layer can establish all our repos independently.
# --------------------------------------------------------------------------- #
def test_install_repos_extracts_and_enables_all_repos(boot):
    """install_repos extracts + registers + enables all 12 REPO_ZIPS (no first-party
    in production) PLUS our own proxy repo. Returns
    (repo_ok, fp_ok, step, canceled) = (12, 1, step, False) — fp_ok == 1 is the
    proxy repo (repository.tony7bones), direct-extracted as first-party plumbing."""
    add = _addons(boot)
    repo_ok, fp_ok, step, canceled = add.install_repos(
        boot.mod.xbmcgui.DialogProgress()
    )
    assert (repo_ok, fp_ok, canceled) == (12, 1, False)
    # 12 repos + 0 first-party + the register-and-enable step (the proxy repo is
    # extracted INSIDE the register step's range, so it does not advance `step`).
    assert step == 12 + 0 + 1
    for _zip, rid in add.REPO_ZIPS:
        assert rid in boot.state["extracted"] or rid + ".zip" in boot.state["extracted"]


def test_install_repos_installs_our_proxy_repo(boot):
    """install_repos establishes our OWN proxy repo (repository.tony7bones) as an
    installed, enabled add-on — first-party plumbing / the lifeline (updates / the
    proxy / future opt-ins). MUTATION: if the proxy-repo extract+enable is dropped
    from install_repos, repository.tony7bones is absent from `installed` and this
    fails. The proxy zip is resolved live via _latest_zip_url (the same mechanism
    modv2plus uses) and the fake urlopen builds a real zip whose inner id is
    repository.tony7bones."""
    add = _addons(boot)
    add.install_repos(boot.mod.xbmcgui.DialogProgress())
    assert add.PROXY_REPO_ID == "repository.tony7bones"
    assert add.PROXY_REPO_ID in boot.state["extracted"], (
        "the proxy repo installer zip must be direct-extracted"
    )
    assert add.PROXY_REPO_ID in boot.state["installed"], (
        "the proxy repo must be enabled (installed) — the lifeline plumbing"
    )


def test_install_repos_proxy_idempotent_when_already_installed(boot, monkeypatch):
    """install_repos no-ops the proxy extract when it is ALREADY installed (re-entry):
    is_installed short-circuits so a second run re-extracts nothing for the proxy."""
    add = _addons(boot)
    boot.state["installed"].add(add.PROXY_REPO_ID)
    boot.state["extracted"].discard(add.PROXY_REPO_ID)
    repo_ok, fp_ok, _step, _c = add.install_repos(boot.mod.xbmcgui.DialogProgress())
    # The proxy was already installed -> not re-extracted, so it is NOT counted in fp_ok.
    assert fp_ok == 0 and repo_ok == 12
    assert add.PROXY_REPO_ID not in boot.state["extracted"], (
        "an already-installed proxy repo must not be re-extracted (idempotent)"
    )


def test_install_base_equals_install_repos_plus_apps(boot, monkeypatch):
    """BEHAVIOUR-PRESERVING extraction: _install_base is install_repos() + the
    base-apps install. Spy install_repos to prove _install_base delegates to it for
    the repo stage (and still installs the 2 base apps after it). MUTATION: if the
    repo loop were inlined again instead of delegating, install_repos would not be
    called and this fails."""
    add = _addons(boot)
    calls = []
    real = add.install_repos

    def _spy(dialog, **kwargs):
        calls.append(kwargs)
        return real(dialog, **kwargs)

    monkeypatch.setattr(add, "install_repos", _spy)
    repo_ok, fp_ok, app_ok, canceled = add._install_base(
        boot.mod.xbmcgui.DialogProgress()
    )
    assert len(calls) == 1, (
        "_install_base must delegate the repo stage to install_repos"
    )
    # The same net (repo_ok, fp_ok, app_ok, canceled) — 12 repos, 1 proxy repo
    # (fp_ok), 2 base apps now.
    assert (repo_ok, fp_ok, app_ok, canceled) == (12, 1, 2, False)


def test_install_base_aborts_when_install_repos_cancels(boot, monkeypatch):
    """If install_repos reports a mid-loop cancel, _install_base returns canceled=True
    and never reaches the apps loop (the monolith's per-repo cancel semantics,
    preserved through the extraction)."""
    add = _addons(boot)
    apps = []
    monkeypatch.setattr(add, "install_repos", lambda dialog, **k: (3, 0, 4, True))
    monkeypatch.setattr(
        add, "install_with_deps", lambda aid, *a, **k: apps.append(aid) or True
    )
    repo_ok, fp_ok, app_ok, canceled = add._install_base(
        boot.mod.xbmcgui.DialogProgress()
    )
    assert canceled is True and repo_ok == 3 and app_ok == 0
    assert apps == [], "a cancelled repo stage must skip the apps loop entirely"


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
# Weather config MOVED to Foundation (test_run_foundation.py / test_setup_foundation
# .py). The Add-ons layer no longer has _apply_weather_from_env / _resolve_weather_
# location / _set_weather_settings — see those files for the weather coverage.
# --------------------------------------------------------------------------- #


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


# --------------------------------------------------------------------------- #
# apply_addons — the composed Layer 2 entry point (install + config).
# --------------------------------------------------------------------------- #
def test_apply_addons_returns_addons_layerresult_on_success(boot, monkeypatch):
    """The composed layer installs base + video, writes RSS, and returns a
    LayerResult(layer='addons', ok=True) recording the installed ids + the
    install-then-disable set, requesting a restart. (Weather is NOT this layer's job
    — it moved to Foundation.)"""
    add = _addons(boot)

    def _sel(selected, official_base, disable_ids, dialog, log):
        return len(selected)

    monkeypatch.setattr(add, "install_selection", _sel)

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
    # config ran: RSS feed written (weather is Foundation's job, not here)
    assert os.path.exists(_rss_path(boot))
    # the Add-ons layer must NOT install weather.multi (Foundation does)
    assert "weather.multi" not in res.installed


def test_apply_addons_cancel_is_not_ok_and_skips_config(boot, monkeypatch):
    """A cancelled base install -> ok=False, no restart requested, and the RSS config
    is SKIPPED (the monolith aborts with no summary on cancel)."""
    add = _addons(boot)
    rss_calls = []
    monkeypatch.setattr(
        add, "_install_base", lambda dialog: (3, 0, 0, True)
    )  # canceled
    monkeypatch.setattr(add, "_apply_rss_from_env", lambda env: rss_calls.append(env))
    res = add.apply_addons({"RSS_FEEDS": "http://a/feed"}, dialog=None, log=None)
    assert res.ok is False
    assert res.needs_restart is False
    assert rss_calls == [], "config must not run on a cancelled install"
    assert not os.path.exists(_rss_path(boot))


def test_apply_addons_records_failed_apps(boot, monkeypatch):
    """When fewer apps install than requested, the shortfall is recorded in
    failed{} so the orchestrator can decide before restarting (not always-empty)."""
    add = _addons(boot)
    # base: all repos ok, only 1 of the 2 apps ok; video: 0.
    monkeypatch.setattr(add, "_install_base", lambda dialog: (12, 0, 1, False))
    monkeypatch.setattr(add, "_install_video", lambda dialog: 0)
    monkeypatch.setattr(add, "_apply_rss_from_env", lambda env: None)
    res = add.apply_addons({}, dialog=None, log=None)
    assert res.ok is True  # not cancelled -> ok (degraded)
    assert res.installed.get(add.ADDONS[0]) == "installed"
    assert res.failed.get(add.ADDONS[1]) == "install failed"
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
    monkeypatch.setattr(add, "_apply_rss_from_env", lambda env: None)
    res = add.apply_addons({}, dialog=None, log=None)
    assert res.installed == {} and res.failed == {}
    assert res.already_done is True


def test_apply_addons_none_env_is_safe(boot, monkeypatch):
    """env=None is treated as the empty env: no RSS write — never a crash. (Weather
    config moved to Foundation, so this layer touches no weather settings.)"""
    add = _addons(boot)
    monkeypatch.setattr(add, "install_selection", lambda s, *a, **k: len(s))
    res = add.apply_addons(None, dialog=boot.mod.xbmcgui.DialogProgress(), log=None)
    assert res.ok is True
    assert not os.path.exists(_rss_path(boot))  # no RSS_FEEDS -> no write


# --------------------------------------------------------------------------- #
# _set_setting + the CORE setting apply_addons owns (the RSS toggle). The weather
# provider core setting moved to Foundation (weather-into-Foundation).
# --------------------------------------------------------------------------- #
def test_set_setting_emits_jsonrpc_and_reports_ok(boot):
    """_set_setting sends a Settings.SetSettingValue JSON-RPC and returns True on a
    `"result":true` reply (the fake jsonrpc returns `{}` -> False; patch a true
    reply to exercise the OK branch)."""
    add = _addons(boot)
    # Default fake jsonrpc returns "{}" -> no '"result":true' -> False.
    assert add._set_setting("lookandfeel.enablerssfeeds", True) is False
    assert _settings_set(boot).get("lookandfeel.enablerssfeeds") is True


def test_set_setting_true_reply_is_ok(boot, monkeypatch):
    """A `"result":true` JSON-RPC reply makes _set_setting return True."""
    add = _addons(boot)
    monkeypatch.setattr(add.xbmc, "executeJSONRPC", lambda s: '{"result":true}')
    assert add._set_setting("lookandfeel.enablerssfeeds", True) is True


def test_apply_addons_sets_rss_core_setting_not_weather(boot, monkeypatch):
    """apply_addons emits the RSS-enable core setting (lookandfeel.enablerssfeeds ->
    True) and does NOT set the weather provider (weather.addon) — the weather provider
    core setting moved to Foundation (weather-into-Foundation)."""
    add = _addons(boot)
    monkeypatch.setattr(add, "install_selection", lambda s, *a, **k: len(s))
    add.apply_addons({}, dialog=boot.mod.xbmcgui.DialogProgress(), log=None)
    s = _settings_set(boot)
    assert s.get(add.RSS_ENABLE_SETTING) is True
    assert add.RSS_ENABLE_SETTING == "lookandfeel.enablerssfeeds"
    assert "weather.addon" not in s, (
        "the Add-ons layer must NOT set the weather provider (moved to Foundation)"
    )


def test_apply_addons_cancel_skips_core_settings(boot, monkeypatch):
    """On a cancelled base install, apply_addons skips the WHOLE config block — the
    RSS core setting is NOT emitted either (the monolith aborts with no config)."""
    add = _addons(boot)
    monkeypatch.setattr(add, "_install_base", lambda dialog: (3, 0, 0, True))
    add.apply_addons({}, dialog=None, log=None)
    s = _settings_set(boot)
    assert add.RSS_ENABLE_SETTING not in s
    assert "weather.addon" not in s
