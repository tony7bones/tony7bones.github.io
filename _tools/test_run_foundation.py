"""Tests for run_foundation — the Foundation orchestrator (Phase 5a).

``run_foundation`` makes Foundation an INDEPENDENTLY-RUNNABLE layer: a skin-only
deliverable. Stop here = a pristine, branded Kodi with ZERO content.

What it MUST do:
  * install ALL our source repos (the 12 REPO_ZIPS — plumbing, not content) via the
    extracted ``install_repos`` so the skin closure resolves from them;
  * install the skin closure (skin.estuary.modv2 + skinshortcuts +
    image.resource.select + the proxy-invisible script.module.pvr.artwork + our
    script.tony7bones.modv2plus + Outline-HD weather icons) via ``apply_foundation``;
  * register the File-Manager sources (incl. the ``.tony.7.bones`` proxy source) +
    trim the home menu;
  * set ``lookandfeel.skin`` LAST, restart once, then self-uninstall.

What it MUST NOT do — the content-free invariant (the heart of this phase):
  * NO base apps (script.ezmaintenanceplus / script.realdebrid / weather.multi);
  * NO curated video (plugin.video.pov / the-loop / sporthdme / youtube);
  * NO pvr.iptvsimple, NO IPTV instance-settings.

These tests drive ``run_foundation`` against the shared fake-Kodi ``boot`` fixture
(conftest.py) — the same real engine the Express orchestrator tests use — and assert
both halves: ALL repos + the skin closure install, and ZERO content add-ons leak in.

Mutation proof (the two killers this phase demands):
  * ``test_run_foundation_installs_all_repos`` — if ``install_repos`` is dropped from
    ``run_foundation`` (or a repo is missing from REPO_ZIPS) the repo set shrinks and
    this fails.
  * ``test_run_foundation_installs_zero_content`` — if ``run_foundation`` ever called
    ``apply_addons`` or ``apply_iptv`` (a content add-on leaking into Foundation),
    a base/video/PVR id would appear in the installed set and this fails.
"""

from __future__ import annotations

import json


def _settings_set(boot):
    """{setting_id: value} from captured Settings.SetSettingValue JSON-RPC calls."""
    out = {}
    for s in boot.state["jsonrpc"]:
        try:
            d = json.loads(s)
        except ValueError:
            continue
        if d.get("method") == "Settings.SetSettingValue":
            out[d["params"]["setting"]] = d["params"]["value"]
    return out


def _stub_skin_success(boot, monkeypatch):
    """Make the skin closure install (the bare fake index can't resolve
    skin.estuary.modv2). Patch the SKIN layer's primitives (run_foundation calls
    apply_skin via the BARE form, so the layer resolves install_selection/
    extract_zip from the skin module's globals) AND the FOUNDATION layer's
    install_with_deps (weather.multi + autocomplete). Repos still go through the
    REAL engine (extract_zip on the addons module / the fake urlopen builds real
    zips), so the repo installs are genuine, not stubbed."""

    def _sel(selected, official_base, disable_ids, dialog, log):
        # The real install_selection enables the source repos as part of resolving a
        # closure (repos.enable_source_repos) — that is what lands repository.diggz.zip
        # in `installed` (it enables by the zip's inner addon.xml id). Mirror it so the
        # stub faithfully reproduces the full-run repo-enable behaviour.
        from tony7bones import enable_source_repos

        enable_source_repos(log)
        for aid in selected:
            boot.state["extracted"].add(aid)
            boot.state["installed"].add(aid)
        for aid in disable_ids:
            boot.state["installed"].add(aid)
            boot.state["disabled"].add(aid)
        return len(selected)

    def _extract_skin(url, dialog, pct, log):
        # The skin-closure direct-extracts (pvr.artwork + modv2plus); record them.
        if "pvr.artwork" in url:
            boot.state["installed"].add(boot.mod.PVR_ARTWORK_ID)
        if "modv2plus" in url:
            boot.state["installed"].add(boot.mod.MODV2PLUS_ID)
        return True

    def _install_with_deps(addon_id, dialog, extra_bases, official_base, log):
        # Foundation installs weather.multi (the branded-look weather provider) via
        # install_with_deps; record it so the weather-install assertion can see it,
        # and treat pvr.artwork deps / outline-hd as installed too.
        boot.state["installed"].add(addon_id)
        return True

    skn = boot.mod._skin
    fnd = boot.mod._foundation
    monkeypatch.setattr(skn, "install_selection", _sel)
    monkeypatch.setattr(skn, "extract_zip", _extract_skin)
    monkeypatch.setattr(skn, "install_with_deps", _install_with_deps)
    monkeypatch.setattr(
        skn, "_latest_zip_url", lambda aid: f"http://local/{aid}-9.9.9.zip"
    )
    monkeypatch.setattr(fnd, "install_with_deps", _install_with_deps)
    # Don't actually restart.
    monkeypatch.setattr(boot.mod, "restart_kodi", lambda *a, **k: None)


# Content add-on ids that must NEVER be installed by Foundation.
# NOTE (weather-into-Foundation): weather.multi is NO LONGER content — it moved INTO
# Foundation (branded look: the MOD V2 skin renders a weather readout + Weather menu
# item). So it is intentionally absent from this list; Foundation installing it is
# expected and asserted separately (test_run_foundation_installs_weather).
_BASE_APPS = ["script.ezmaintenanceplus", "script.realdebrid"]
_VIDEO_APPS = [
    "plugin.video.pov",
    "plugin.video.the-loop",
    "plugin.video.sporthdme",
    "plugin.video.youtube",
]
_PVR = ["pvr.iptvsimple", "inputstream.ffmpegdirect"]
_CONTENT_IDS = _BASE_APPS + _VIDEO_APPS + _PVR


# --------------------------------------------------------------------------- #
# run_foundation returns a Foundation LayerResult.
# --------------------------------------------------------------------------- #
def test_run_foundation_returns_foundation_layerresult(boot, monkeypatch):
    """run_foundation returns the Foundation LayerResult (layer='foundation', ok=True
    when the skin installs)."""
    _stub_skin_success(boot, monkeypatch)
    res = boot.mod.run_foundation({})
    assert res.layer == "foundation"
    assert res.ok is True
    assert boot.mod.SKIN_ID in res.installed


def test_merged_foundation_result_preserves_distinct_keys_from_both_layers(
    boot, monkeypatch
):
    """_merged_foundation_result unions the Foundation-config and Skin-closure
    installed{}/failed{} dicts — proves no key is silently dropped when both
    layers report distinct ids (weather.multi/autocomplete from Foundation,
    SKIN_ID from Skin). A future id COLLISION between the two layers would
    silently favor the second dict's value under plain dict-union; this test
    exists so a future edit that narrows either layer's id set is caught."""
    _stub_skin_success(boot, monkeypatch)
    res = boot.mod.run_foundation({})
    assert res.installed.get("weather.multi") == "installed"
    assert res.installed.get("script.module.autocompletion") == "installed"
    assert res.installed.get(boot.mod.SKIN_ID) == "installed"
    # sanity: the three ids are genuinely distinct (the union has no collision
    # to hide today) — if this ever fails, _merged_foundation_result's dict
    # union needs a real conflict-resolution policy, not silent overwrite.
    ids = ("weather.multi", "script.module.autocompletion", boot.mod.SKIN_ID)
    assert len(set(ids)) == len(ids)


# --------------------------------------------------------------------------- #
# ALL repos install (mutation killer #1: drop install_repos / a repo from REPO_ZIPS).
# --------------------------------------------------------------------------- #
def _repo_installed(boot, rid):
    """Whether a repo id landed in `installed`, honoring the pre-existing
    repository.diggz vs repository.diggz.zip quirk (the zip's inner id carries the
    .zip suffix, faithfully pinned by the characterization snapshot)."""
    return rid in boot.state["installed"] or rid + ".zip" in boot.state["installed"]


def test_run_foundation_installs_all_repos(boot, monkeypatch):
    """ALL 12 REPO_ZIPS are extracted + enabled by run_foundation (the source repos
    the skin closure resolves from — plumbing, not content). MUTATION: removing the
    install_repos() call (or a repo id from REPO_ZIPS) shrinks this set and fails."""
    _stub_skin_success(boot, monkeypatch)
    boot.mod.run_foundation({})

    repo_ids = {rid for _z, rid in boot.mod.REPO_ZIPS}
    assert len(repo_ids) == 12, "REPO_ZIPS must list all 12 source repos"
    missing = [rid for rid in repo_ids if not _repo_installed(boot, rid)]
    assert not missing, (
        f"Foundation must install ALL our repos; missing: {sorted(missing)}"
    )


def test_run_foundation_repos_are_enabled(boot, monkeypatch):
    """The repos are not just extracted but REGISTERED + ENABLED (install_repos runs
    update_local_addons + enable on each rid) — proven by the fake engine, which only
    moves an id into `installed` on an enable of an extracted add-on."""
    _stub_skin_success(boot, monkeypatch)
    boot.mod.run_foundation({})
    for _z, rid in boot.mod.REPO_ZIPS:
        assert _repo_installed(boot, rid), f"repo {rid} must be enabled"


# --------------------------------------------------------------------------- #
# The skin closure + modv2plus install.
# --------------------------------------------------------------------------- #
def test_run_foundation_installs_skin_closure_and_modv2plus(boot, monkeypatch):
    """The skin + the proxy-invisible direct-extracts (pvr.artwork + modv2plus) land
    — the branded box's add-ons."""
    _stub_skin_success(boot, monkeypatch)
    boot.mod.run_foundation({})
    for aid in (boot.mod.SKIN_ID, boot.mod.PVR_ARTWORK_ID, boot.mod.MODV2PLUS_ID):
        assert aid in boot.state["installed"], f"{aid} must be installed by Foundation"


# --------------------------------------------------------------------------- #
# ZERO content (mutation killer #2: a content layer leaking into Foundation).
# --------------------------------------------------------------------------- #
def test_run_foundation_installs_zero_content(boot, monkeypatch):
    """The CONTENT-FREE invariant: run_foundation installs NONE of the base apps,
    curated video add-ons, or the PVR backend. MUTATION: if run_foundation ever
    called apply_addons or apply_iptv, a content id would appear here and this fails.
    This is the heart of the skin-only deliverable."""
    _stub_skin_success(boot, monkeypatch)
    boot.mod.run_foundation({})

    leaked = [aid for aid in _CONTENT_IDS if aid in boot.state["installed"]]
    assert leaked == [], (
        f"Foundation must install ZERO content add-ons; leaked: {leaked}. "
        "run_foundation must NOT call apply_addons (base apps/video) or apply_iptv."
    )


def test_run_foundation_does_not_call_content_layers(boot, monkeypatch):
    """Spy the content layer entry points — run_foundation must call NEITHER
    apply_addons NOR apply_iptv (the structural guarantee behind the zero-content
    end-state). Belt-and-suspenders to the installed-set assertion."""
    called = []
    monkeypatch.setattr(
        boot.mod, "apply_addons", lambda *a, **k: called.append("apply_addons")
    )
    monkeypatch.setattr(
        boot.mod, "apply_iptv", lambda *a, **k: called.append("apply_iptv")
    )
    _stub_skin_success(boot, monkeypatch)
    boot.mod.run_foundation({})
    assert called == [], (
        f"run_foundation must not call any content layer; called: {called}"
    )


def test_run_foundation_writes_no_iptv(boot, monkeypatch):
    """No IPTV instance-settings are written — Foundation does not touch
    pvr.iptvsimple's instance file (that is IPTV layer work). Weather + RSS ARE
    now Foundation's job and are asserted positively elsewhere."""
    _stub_skin_success(boot, monkeypatch)
    boot.mod.run_foundation({})

    iptv_path = boot.mod.xbmcvfs.translatePath(boot.mod.IPTV_INSTANCE_SETTINGS_SPECIAL)
    import os

    assert not os.path.exists(iptv_path), (
        "Foundation must not write pvr.iptvsimple instance-settings"
    )


# --------------------------------------------------------------------------- #
# Weather into Foundation: a skin-only box must have WORKING weather (the MOD V2
# skin renders a weather readout + a Weather menu item). Foundation installs
# weather.multi AND configures it (provider + keyless-default location).
# --------------------------------------------------------------------------- #
def _weather_settings(boot):
    """Multi Weather settings.xml as {id: text} (or {} if unwritten)."""
    import os
    from xml.etree import ElementTree as ET

    path = boot.mod._foundation._weather_multi_settings_path()
    if not os.path.exists(path):
        return {}
    root = ET.parse(path).getroot()
    return {s.get("id"): (s.text or "") for s in root.findall("setting")}


def test_run_foundation_installs_weather(boot, monkeypatch):
    """Foundation installs weather.multi — the branded-look weather provider (moved
    out of the Add-ons base ADDONS). MUTATION: if Foundation stops installing weather
    (the _apply_weather call dropped), weather.multi is absent and this fails."""
    _stub_skin_success(boot, monkeypatch)
    res = boot.mod.run_foundation({})
    assert "weather.multi" in boot.state["installed"], (
        "Foundation must install weather.multi (the branded-look weather provider)"
    )
    assert res.installed.get("weather.multi") == "installed", (
        "the Foundation LayerResult must record weather.multi installed"
    )


def test_run_foundation_sets_weather_provider(boot, monkeypatch):
    """Foundation sets the CORE weather.addon provider to weather.multi (so the MOD
    V2 skin's weather readout has a provider). MUTATION: drop the provider set and
    this fails."""
    _stub_skin_success(boot, monkeypatch)
    boot.mod.run_foundation({})
    settings = _settings_set(boot)
    assert settings.get("weather.addon") == "weather.multi", (
        "Foundation must set the core weather provider to weather.multi"
    )


def test_run_foundation_writes_keyless_default_location(boot, monkeypatch):
    """With no env locations, Foundation writes the keyless Sacramento default —
    loc1_url is the LOAD-BEARING field weather.multi fetches by; it must be non-empty
    so the branded box has working weather out of the box."""
    _stub_skin_success(boot, monkeypatch)
    # no resolvable env locations -> the keyless Sacramento fallback
    monkeypatch.setattr(
        boot.mod._foundation, "_resolve_weather_location", lambda q, **k: None
    )
    boot.mod.run_foundation({})
    wx = _weather_settings(boot)
    assert wx.get("loc1_url") == "us/ca/sacramento", (
        "Foundation must write the keyless Sacramento default location"
    )
    assert wx.get("loc1_url"), "loc1_url must never be empty (the load-bearing field)"


def test_run_foundation_writes_env_weather_locations(boot, monkeypatch):
    """When the env supplies WEATHER_LOCATIONS, Foundation resolves + writes them
    (env-driven, not the hardcoded Sacramento). Proves the env weather config landed
    in Foundation."""
    _stub_skin_success(boot, monkeypatch)
    monkeypatch.setattr(
        boot.mod._foundation,
        "_resolve_weather_location",
        lambda q, **k: {
            "name": "Reno, NV, US",
            "url": "us/nv/reno",
            "lat": "39.5",
            "lon": "-119.8",
        },
    )
    boot.mod.run_foundation({"WEATHER_LOCATIONS": "Reno, NV"})
    wx = _weather_settings(boot)
    assert wx.get("loc1_url") == "us/nv/reno", (
        "Foundation must write the env-resolved weather location"
    )


# --------------------------------------------------------------------------- #
# RSS into Foundation: the news ticker is branded-look config (a skin-level
# toggle), same as weather, so it moved here from the Add-ons layer too.
# --------------------------------------------------------------------------- #
def test_run_foundation_enables_rss_ticker(boot, monkeypatch):
    """Foundation sets the core RSS-enable setting. MUTATION: if Foundation stops
    calling _apply_rss (the toggle set dropped), this fails."""
    _stub_skin_success(boot, monkeypatch)
    boot.mod.run_foundation({})
    settings = _settings_set(boot)
    assert settings.get("lookandfeel.enablerssfeeds") is True, (
        "Foundation must enable the RSS ticker"
    )


def test_run_foundation_writes_env_rss_feeds(boot, monkeypatch):
    """When the env supplies RSS_FEEDS, Foundation writes userdata/RssFeeds.xml —
    proves the env-driven RSS writer landed in Foundation (moved from Add-ons)."""
    from xml.etree import ElementTree as ET

    _stub_skin_success(boot, monkeypatch)
    boot.mod.run_foundation({"RSS_FEEDS": "http://feeds.example/a.xml"})
    rss_path = boot.mod.xbmcvfs.translatePath("special://home/userdata/RssFeeds.xml")
    feeds = [f.text for f in ET.parse(rss_path).getroot().iter("feed")]
    assert feeds == ["http://feeds.example/a.xml"]


# --------------------------------------------------------------------------- #
# Foundation establishes the sources (incl. the .tony.7.bones proxy source).
# --------------------------------------------------------------------------- #
def test_run_foundation_adds_file_sources_incl_proxy(boot, monkeypatch):
    """apply_foundation's _add_file_sources runs — the File-Manager sources are
    written, INCLUDING the .tony.7.bones proxy repo source (how Foundation establishes
    repository.tony7bones: the host proxy is already running; this registers it as a
    source). Proves the proxy repo is established without re-installing the host."""
    from xml.etree import ElementTree as ET

    _stub_skin_success(boot, monkeypatch)
    boot.mod.run_foundation({})

    root = ET.parse(boot.sources_xml).getroot()
    files = root.find("files")
    names = {s.findtext("name") for s in files.findall("source")}
    paths = {s.findtext("path") for s in files.findall("source")}
    assert boot.mod._foundation.REPO_SOURCE_NAME in names, (
        "the .tony.7.bones proxy source must be added"
    )
    assert boot.mod._foundation.REPO_SOURCE_URL in paths


def test_run_foundation_trims_home_menu(boot, monkeypatch):
    """apply_foundation's _trim_home_menu runs — the eight hide-bools are set in the
    skin.estuary settings.xml (the trimmed, branded home menu)."""
    from xml.etree import ElementTree as ET

    _stub_skin_success(boot, monkeypatch)
    boot.mod.run_foundation({})

    assert boot.estuary_settings.exists(), "home-trim must write skin.estuary settings"
    root = ET.parse(boot.estuary_settings).getroot()
    ids = {s.get("id") for s in root.findall("setting")}
    assert "homemenunomoviebutton" in ids, "home-trim hide-bools must be written"


# --------------------------------------------------------------------------- #
# The terminal seam: skin activated LAST, then restart, then self-uninstall.
# --------------------------------------------------------------------------- #
def test_run_foundation_activates_skin_last_then_restarts(boot, monkeypatch):
    """The skin is activated LAST (lookandfeel.skin set) immediately before the
    restart — the activate-skin invariant (only when Foundation reached ok)."""
    _stub_skin_success(boot, monkeypatch)
    seq = []
    real_activate = boot.mod.activate_skin

    def _activate(*a, **k):
        seq.append("activate_skin")
        return real_activate(*a, **k)

    def _restart(*a, **k):
        seq.append("restart")
        seq.append(("skin_last", _settings_set(boot).get("lookandfeel.skin")))
        return None

    monkeypatch.setattr(boot.mod, "activate_skin", _activate)
    monkeypatch.setattr(boot.mod, "restart_kodi", _restart)
    boot.mod.run_foundation({})

    assert seq[0] == "activate_skin" and seq[1] == "restart", (
        f"skin must be activated immediately before the restart, got {seq}"
    )
    assert ("skin_last", boot.mod.SKIN_ID) in seq, (
        "lookandfeel.skin must be set (to MOD V2) before the restart"
    )


def test_run_foundation_self_uninstalls_after_summary_before_restart(boot, monkeypatch):
    """run_foundation self-uninstalls exactly once, AFTER the summary Dialog().ok and
    BEFORE the restart (skin-only = done — the restart finalises the removal)."""
    events = []
    _stub_skin_success(boot, monkeypatch)

    real_ok = boot.mod.xbmcgui.Dialog.ok

    def _ok(self, title, msg):
        events.append("summary")
        return real_ok(self, title, msg)

    monkeypatch.setattr(boot.mod.xbmcgui.Dialog, "ok", _ok)
    monkeypatch.setattr(
        boot.mod, "self_uninstall", lambda *a, **k: events.append("self_uninstall")
    )
    monkeypatch.setattr(
        boot.mod, "restart_kodi", lambda *a, **k: events.append("restart")
    )
    boot.mod.run_foundation({})

    assert events == ["summary", "self_uninstall", "restart"], (
        f"order must be summary -> self_uninstall -> restart, got {events}"
    )


def test_run_foundation_skin_not_activated_when_install_failed(boot, monkeypatch):
    """When the skin install fails (the bare fake index can't resolve it), Foundation
    is ok=False and the orchestrator does NOT set lookandfeel.skin — but it still
    restarts + self-uninstalls (the box completes; a failed skin is non-fatal)."""
    # Do NOT stub the skin closure: the bare index leaves skin.estuary.modv2
    # unresolved, so apply_foundation.ok is False.
    monkeypatch.setattr(boot.mod, "restart_kodi", lambda *a, **k: None)
    activated = []
    monkeypatch.setattr(boot.mod, "activate_skin", lambda *a, **k: activated.append(a))
    res = boot.mod.run_foundation({})
    assert res.ok is False
    assert activated == [], "lookandfeel.skin must NOT be set when the skin failed"
    # Repos still install even when the skin fails (they are independent plumbing).
    for _z, rid in boot.mod.REPO_ZIPS:
        assert _repo_installed(boot, rid), "repos install regardless of skin"
    # ZERO content at the REAL-resolve level (not just the stubbed path): even with
    # the real engine resolving the skin closure, NO content add-on may leak in.
    leaked = [aid for aid in _CONTENT_IDS if aid in boot.state["installed"]]
    assert leaked == [], f"real-engine Foundation leaked content: {leaked}"


# --------------------------------------------------------------------------- #
# The two intentional Foundation additions — our own proxy repo + autocomplete.
# --------------------------------------------------------------------------- #
def test_run_foundation_installs_our_proxy_repo(boot, monkeypatch):
    """Foundation installs our OWN proxy repo (repository.tony7bones) — first-party
    plumbing / the lifeline (updates / the proxy / future opt-ins). It is established
    via install_repos (direct-extract of the installer zip + enable). MUTATION: drop
    the proxy install from install_repos and repository.tony7bones is absent here."""
    _stub_skin_success(boot, monkeypatch)
    boot.mod.run_foundation({})
    assert boot.mod._addons.PROXY_REPO_ID == "repository.tony7bones"
    assert "repository.tony7bones" in boot.state["installed"], (
        "Foundation must establish our proxy repo (the lifeline)"
    )


def test_run_foundation_installs_autocomplete(boot, monkeypatch):
    """Foundation installs script.module.autocompletion — the keyboard autocomplete
    QoL utility. MUTATION: drop the _install_autocomplete call and it is absent here.
    The _install_with_deps stub in _stub_skin_success records each installed addon."""
    _stub_skin_success(boot, monkeypatch)
    boot.mod.run_foundation({})
    assert "script.module.autocompletion" in boot.state["installed"], (
        "Foundation must install the keyboard autocomplete utility"
    )


# --------------------------------------------------------------------------- #
# _env_has_iptv — the IPTV auto-chain gate.
# --------------------------------------------------------------------------- #
def test_env_has_iptv_true_for_single_instance_m3u(boot):
    """The single-instance IPTV_M3U (non-empty) trips the gate."""
    assert boot.mod._env_has_iptv({"IPTV_M3U": "http://provider/playlist.m3u"}) is True


def test_env_has_iptv_true_for_indexed_m3u_and_portal(boot):
    """Multi-provider IPTV_<N>_M3U / IPTV_<N>_PORTAL keys trip the gate."""
    assert boot.mod._env_has_iptv({"IPTV_1_M3U": "http://p/1.m3u"}) is True
    assert boot.mod._env_has_iptv({"IPTV_2_PORTAL": "http://portal/"}) is True
    assert boot.mod._env_has_iptv({"IPTV_M3U": "", "IPTV_3_M3U": "http://p/3"}) is True


def test_env_has_iptv_false_for_empty_or_groups_only(boot):
    """No IPTV PLAYLIST source -> False: an empty env, an EMPTY IPTV_M3U value,
    IPTV_GROUPS alone (group names without a playlist), and IPTV_EPG alone (guide
    metadata = a channel-less PVR, not a usable source) all do NOT count."""
    assert boot.mod._env_has_iptv({}) is False
    assert boot.mod._env_has_iptv(None) is False
    assert boot.mod._env_has_iptv({"IPTV_M3U": ""}) is False
    assert boot.mod._env_has_iptv({"IPTV_M3U": "   "}) is False
    assert boot.mod._env_has_iptv({"IPTV_GROUPS": "Sports,News"}) is False
    assert boot.mod._env_has_iptv({"WEATHER_LOCATIONS": "Reno"}) is False
    # EPG alone is NOT a playlist source -> must not chain IPTV (GAP-2 decision).
    assert boot.mod._env_has_iptv({"IPTV_EPG": "http://epg/guide.xml"}) is False
    assert boot.mod._env_has_iptv({"IPTV_1_EPG": "http://epg/1.xml"}) is False


# --------------------------------------------------------------------------- #
# run_foundation_setup — Foundation + the env-gated IPTV chain.
# --------------------------------------------------------------------------- #
def _iptv_instance_path(boot):
    return boot.mod.xbmcvfs.translatePath(boot.mod.IPTV_INSTANCE_SETTINGS_SPECIAL)


def test_run_foundation_setup_without_iptv_is_skin_only(boot, monkeypatch):
    """With NO IPTV env, run_foundation_setup is IDENTICAL to skin-only Foundation:
    NO pvr.iptvsimple, NO IPTV instance-settings, and apply_iptv is never called.
    The installed set matches the skin-only deliverable (zero content)."""
    import os

    _stub_skin_success(boot, monkeypatch)
    called = []
    real_iptv = boot.mod.apply_iptv
    monkeypatch.setattr(
        boot.mod,
        "apply_iptv",
        lambda *a, **k: called.append("apply_iptv") or real_iptv(*a, **k),
    )
    fnd_res, iptv_res = boot.mod.run_foundation_setup({})
    assert fnd_res.layer == "foundation" and fnd_res.ok is True
    assert iptv_res is None, "no IPTV env -> the IPTV layer must be skipped"
    assert called == [], "apply_iptv must NOT be called without an IPTV provider env"
    assert "pvr.iptvsimple" not in boot.state["installed"], "no PVR backend"
    assert not os.path.exists(_iptv_instance_path(boot)), "no instance-settings written"
    # Same zero-content invariant as run_foundation.
    leaked = [aid for aid in _CONTENT_IDS if aid in boot.state["installed"]]
    assert leaked == [], f"skin-only path leaked content: {leaked}"


def test_run_foundation_ignores_iptv_env(boot, monkeypatch):
    """run_foundation is PURE skin-only: even handed an IPTV-bearing env it must NEVER
    chain IPTV (that lives ONLY in run_foundation_setup). No pvr.iptvsimple, no
    instance-settings, apply_iptv never called. MUTATION GUARD: a future refactor that
    wired run_foundation to _env_has_iptv would slip past the {}-env zero-content tests
    but fails here."""
    import os

    _stub_skin_success(boot, monkeypatch)
    called = []
    monkeypatch.setattr(
        boot.mod, "apply_iptv", lambda *a, **k: called.append("apply_iptv")
    )
    res = boot.mod.run_foundation(
        {"IPTV_M3U": "http://provider/playlist.m3u", "IPTV_1_PORTAL": "http://portal/"}
    )
    assert res.layer == "foundation" and res.ok is True
    assert called == [], "run_foundation must NEVER call apply_iptv (pure skin-only)"
    assert "pvr.iptvsimple" not in boot.state["installed"], (
        "no PVR backend in pure Foundation"
    )
    assert not os.path.exists(_iptv_instance_path(boot)), (
        "no instance-settings in pure Foundation"
    )
    leaked = [aid for aid in _CONTENT_IDS if aid in boot.state["installed"]]
    assert leaked == [], f"run_foundation leaked content with an iptv env: {leaked}"


def test_run_foundation_setup_with_iptv_installs_pvr_and_writes_settings(
    boot, monkeypatch
):
    """WITH an IPTV provider env, run_foundation_setup chains apply_iptv: it installs
    pvr.iptvsimple (+ inputstream closure) and WRITES the instance-settings (m3u source
    from the env). MUTATION: if the IPTV chain were dropped (or always skipped), no
    PVR backend installs and no instance-settings file appears — this fails."""
    import os
    from xml.etree import ElementTree as ET

    _stub_skin_success(boot, monkeypatch)
    env = {"IPTV_M3U": "http://provider.example/playlist.m3u"}
    fnd_res, iptv_res = boot.mod.run_foundation_setup(env)

    assert fnd_res.ok is True
    assert iptv_res is not None and iptv_res.layer == "iptv" and iptv_res.ok is True
    assert "pvr.iptvsimple" in boot.state["installed"], (
        "the IPTV chain must install the PVR backend"
    )
    path = _iptv_instance_path(boot)
    assert os.path.exists(path), "the IPTV chain must write instance-settings"
    root = ET.parse(path).getroot()
    vals = {s.get("id"): (s.text or "") for s in root.findall("setting")}
    assert vals.get("m3uUrl") == "http://provider.example/playlist.m3u", (
        "the env's IPTV_M3U must land in the instance-settings"
    )


def test_run_foundation_setup_shares_install_seam_with_run_foundation(
    boot, monkeypatch
):
    """run_foundation_setup uses the SAME Foundation install seam (_foundation_core),
    so it installs the proxy repo + autocomplete + all repos too (no skin-only path
    regresses the additions). Belt-and-suspenders that the new runner did not fork."""
    _stub_skin_success(boot, monkeypatch)
    boot.mod.run_foundation_setup({})
    assert "repository.tony7bones" in boot.state["installed"]
    assert "script.module.autocompletion" in boot.state["installed"]
    for _z, rid in boot.mod.REPO_ZIPS:
        assert _repo_installed(boot, rid), (
            f"repo {rid} must install via the shared seam"
        )


def test_run_foundation_setup_activates_skin_last_then_restarts(boot, monkeypatch):
    """run_foundation_setup sets lookandfeel.skin LAST and restarts ONCE, AFTER the
    IPTV chain — the terminal seam stays orchestrator-owned even with IPTV. The skin
    is the LAST core setting written before the single restart."""
    _stub_skin_success(boot, monkeypatch)
    seq = []
    real_activate = boot.mod.activate_skin
    monkeypatch.setattr(
        boot.mod,
        "activate_skin",
        lambda *a, **k: seq.append("activate") or real_activate(*a, **k),
    )

    def _restart(*a, **k):
        seq.append("restart")
        seq.append(("skin_last", _settings_set(boot).get("lookandfeel.skin")))

    monkeypatch.setattr(boot.mod, "restart_kodi", _restart)
    boot.mod.run_foundation_setup({"IPTV_M3U": "http://p/x.m3u"})
    assert seq[0] == "activate" and seq[1] == "restart", (
        f"skin must activate immediately before the single restart, got {seq}"
    )
    assert ("skin_last", boot.mod.SKIN_ID) in seq


def test_run_foundation_setup_self_uninstalls_after_summary_before_restart(
    boot, monkeypatch
):
    """run_foundation_setup self-uninstalls AFTER the summary and BEFORE the restart
    (the terminal-seam ordering, preserved for the new runner)."""
    events = []
    _stub_skin_success(boot, monkeypatch)
    real_ok = boot.mod.xbmcgui.Dialog.ok

    def _ok(self, title, msg):
        events.append("summary")
        return real_ok(self, title, msg)

    monkeypatch.setattr(boot.mod.xbmcgui.Dialog, "ok", _ok)
    monkeypatch.setattr(
        boot.mod, "self_uninstall", lambda *a, **k: events.append("self_uninstall")
    )
    monkeypatch.setattr(
        boot.mod, "restart_kodi", lambda *a, **k: events.append("restart")
    )
    boot.mod.run_foundation_setup({})
    assert events == ["summary", "self_uninstall", "restart"], (
        f"order must be summary -> self_uninstall -> restart, got {events}"
    )


def test_run_foundation_setup_multi_provider_env_one_instance_per_provider(
    boot, monkeypatch
):
    """Phase 5b·1 — the REAL per-device env shape through the chain: a numbered
    multi-provider env (m3u provider 1 + xtream provider 2) fires the IPTV gate;
    provider 1 lands in instance-settings-1.xml (m3u + custom groups from the
    `SOURCE > Label | sort` grammar's SOURCE side + the instance name); the
    xtream provider writes NO instance file (skipped in-Kodi — host-side m3u
    derivation is step 2); and pvr.iptvsimple ends ENABLED (the clobber-fix
    disable window must not leave it off)."""
    import os
    from xml.etree import ElementTree as ET

    _stub_skin_success(boot, monkeypatch)
    env = {
        "IPTV_1_NAME": "Network 24",
        "IPTV_1_MODE": "m3u",
        "IPTV_1_M3U": "http://iptv.example/1.m3u?password=p1",
        "IPTV_1_EPG": "http://iptv.example/1.xml",
        "IPTV_1_GROUPS": "USA ENTERTAINMENT > US Entertainment | sort; PPV EVENTS",
        "IPTV_2_NAME": "Streamvision",
        "IPTV_2_MODE": "xtream",
        "IPTV_2_PORTAL": "http://portal.example:8080",
        "IPTV_2_USER": "u",
        "IPTV_2_PASS": "p",
    }
    fnd_res, iptv_res = boot.mod.run_foundation_setup(env)
    assert fnd_res.ok is True
    assert iptv_res is not None and iptv_res.ok is True
    assert iptv_res.installed.get("pvr.iptvsimple") == "configured"
    assert "pvr.iptvsimple" in boot.state["installed"]
    assert "pvr.iptvsimple" not in boot.state["disabled"], (
        "the clobber-fix window must RE-ENABLE the backend"
    )
    one = boot.mod.xbmcvfs.translatePath(boot.mod._iptv._instance_settings_special(1))
    two = boot.mod.xbmcvfs.translatePath(boot.mod._iptv._instance_settings_special(2))
    assert os.path.exists(one), "provider 1 must write instance-settings-1.xml"
    assert not os.path.exists(two), "the xtream provider must be skipped in-Kodi"
    vals = {
        s.get("id"): (s.text or "") for s in ET.parse(one).getroot().findall("setting")
    }
    assert vals["m3uUrl"].endswith("password=p1")
    assert vals["kodi_addon_instance_name"] == "Network 24"
    assert vals["tvGroupMode"] == "2"
    gpath = boot.mod.xbmcvfs.translatePath(vals["customTvGroupsFile"])
    gtext = open(gpath).read()
    assert "USA ENTERTAINMENT" in gtext and "PPV EVENTS" in gtext
    assert "US Entertainment" not in gtext, "SOURCE side only — never the label"
