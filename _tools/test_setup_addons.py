"""Unit tests for the Add-ons layer (Phase 2c).

``tony7bones.setup.addons`` holds the LIFTED bodies of the monolith's
``_install_base`` (base repos + apps) and ``_install_video`` (curated video
add-ons, incl. the install-then-disable of ``plugin.video.dailymotion_com``) out
of ``script.tony7bones.bootstrap/default.py`` — behaviour-identical. It also adds
the composed ``apply_addons`` layer entry point (install-only content), which the
Express orchestrator drives.

NOTE (weather + RSS -> Foundation): both the WEATHER provider + env-driven
location config (weather.multi install + ``_apply_weather_from_env`` + the core
weather.addon setting) AND the RSS news-ticker config (``_apply_rss_from_env`` +
the core lookandfeel.enablerssfeeds setting) MOVED OUT of the Add-ons layer INTO
the Foundation layer — both are part of the branded look (the MOD V2 skin
renders a weather readout + a Weather menu item, and the ticker is a skin-level
toggle), not content. Their unit tests moved with them to
test_setup_foundation.py / test_run_foundation.py; the Add-ons layer now installs
content only (base repos/apps + curated video).

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
    (repository.tony7bones), and installs the 1 base app with its closure through
    the real engine. Returns (repo_ok, fp_ok, app_ok, canceled) = (12, 1, 1, False)
    — fp_ok == 1 is the proxy repo (first-party plumbing).

    The base apps are now just realdebrid (Decision C: peno64's PLAIN backup fork
    script.ezmaintenanceplus was removed — the Setup was installing the WRONG
    backup tool; the correct `++` fork is installed by the separate Backup layer
    instead) — pvr.iptvsimple's install moved OUT of the base ADDONS into
    apply_iptv (Phase 3a) AND weather.multi moved OUT into apply_foundation
    (weather-into-Foundation). Both are still installed by a full run (pvr via the
    IPTV layer, weather via Foundation), pinned by test_modular_setup.py's net-set
    equivalence invariant."""
    add = _addons(boot)
    repo_ok, fp_ok, app_ok, canceled = add._install_base(
        boot.mod.xbmcgui.DialogProgress()
    )
    assert (repo_ok, fp_ok, app_ok, canceled) == (12, 1, 1, False)
    assert len(add.ADDONS) == 1 and "pvr.iptvsimple" not in add.ADDONS, (
        "pvr.iptvsimple must have moved out of the base ADDONS list (Phase 3a)"
    )
    assert "script.ezmaintenanceplus" not in add.ADDONS, (
        "peno64's plain backup fork must be gone from the base ADDONS (Decision C)"
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
    # 1 base app (realdebrid; pvr.iptvsimple -> IPTV layer; weather.multi ->
    # Foundation; peno64's plain backup fork removed, Decision C); the
    # install_with_deps patch is driven once per base app, in ADDONS order.
    assert app_ok == 1 and deps == list(add.ADDONS), (
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
    the repo stage (and still installs the 1 base app after it). MUTATION: if the
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
    # (fp_ok), 1 base app now (Decision C).
    assert (repo_ok, fp_ok, app_ok, canceled) == (12, 1, 1, False)


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
# Weather + RSS config MOVED to Foundation (test_run_foundation.py /
# test_setup_foundation.py). The Add-ons layer no longer has
# _apply_weather_from_env / _resolve_weather_location / _set_weather_settings /
# _apply_rss_from_env / _set_setting / RSS_ENABLE_SETTING — see those files for
# the weather + RSS coverage.
# --------------------------------------------------------------------------- #


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
# apply_addons — the composed Layer 2 entry point (install-only content).
# --------------------------------------------------------------------------- #
def test_apply_addons_returns_addons_layerresult_on_success(boot, monkeypatch):
    """The composed layer installs base + video and returns a
    LayerResult(layer='addons', ok=True) recording the installed ids + the
    install-then-disable set, requesting a restart. (Weather + RSS are NOT this
    layer's job — both moved to Foundation.)"""
    add = _addons(boot)

    def _sel(selected, official_base, disable_ids, dialog, log):
        return len(selected)

    monkeypatch.setattr(add, "install_selection", _sel)

    res = add.apply_addons(
        {},
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
    # the Add-ons layer must NOT install weather.multi (Foundation does)
    assert "weather.multi" not in res.installed


def test_apply_addons_never_writes_rss_or_core_settings(boot, monkeypatch):
    """apply_addons no longer touches RSS at all (moved to Foundation): passing
    RSS_FEEDS in the env has no effect and no Settings.SetSettingValue call is
    emitted from this layer."""
    add = _addons(boot)
    monkeypatch.setattr(add, "install_selection", lambda s, *a, **k: len(s))
    add.apply_addons(
        {"RSS_FEEDS": "http://a/feed"},
        dialog=boot.mod.xbmcgui.DialogProgress(),
        log=None,
    )
    assert not os.path.exists(_rss_path(boot))
    assert _settings_set(boot) == {}


def test_apply_addons_cancel_is_not_ok(boot, monkeypatch):
    """A cancelled base install -> ok=False, no restart requested."""
    add = _addons(boot)
    monkeypatch.setattr(
        add, "_install_base", lambda dialog: (3, 0, 0, True)
    )  # canceled
    res = add.apply_addons({}, dialog=None, log=None)
    assert res.ok is False
    assert res.needs_restart is False


def test_apply_addons_records_failed_apps(boot, monkeypatch):
    """When fewer apps install than requested, the shortfall is recorded in
    failed{} so the orchestrator can decide before restarting (not always-empty)."""
    add = _addons(boot)
    # base: all repos ok, 0 of the 1 base app ok (Decision C: ADDONS has just
    # realdebrid now); video: 0.
    monkeypatch.setattr(add, "_install_base", lambda dialog: (12, 0, 0, False))
    monkeypatch.setattr(add, "_install_video", lambda dialog: 0)
    res = add.apply_addons({}, dialog=None, log=None)
    assert res.ok is True  # not cancelled -> ok (degraded)
    assert res.failed.get(add.ADDONS[0]) == "install failed"
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
    res = add.apply_addons({}, dialog=None, log=None)
    assert res.installed == {} and res.failed == {}
    assert res.already_done is True


def test_apply_addons_none_env_is_safe(boot, monkeypatch):
    """env=None is treated as the empty env — never a crash. (Weather + RSS config
    moved to Foundation, so this layer touches no weather/RSS settings.)"""
    add = _addons(boot)
    monkeypatch.setattr(add, "install_selection", lambda s, *a, **k: len(s))
    res = add.apply_addons(None, dialog=boot.mod.xbmcgui.DialogProgress(), log=None)
    assert res.ok is True
