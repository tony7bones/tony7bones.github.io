"""Unit tests for the Foundation layer (Phase 2b).

``tony7bones.setup.foundation.apply_foundation`` is the Layer 0 entry point: it
installs the Estuary MOD V2 skin + the MOD V2+ patch closure (direct-extracting the
two proxy-invisible deps — ``script.module.pvr.artwork`` + our own
``script.tony7bones.modv2plus`` — BEFORE the closure resolve), then runs the two
content-free base-config steps (File-Manager sources + the Estuary home-menu trim),
and returns a ``LayerResult`` REQUESTING skin activation + restart from the
orchestrator. It deliberately does NOT set ``lookandfeel.skin`` — that stays the
orchestrator's terminal seam.

These tests drive ``apply_foundation`` (and the lifted ``_install_skin`` body)
DIRECTLY against the shared fake-Kodi ``boot`` fixture (conftest.py) — the same
real engine the bootstrap suite uses, reached via ``boot.mod._foundation`` (the
foundation module the bootstrap imports under the fake Kodi). This is the
behaviour-preserving oracle for the move: the foundation bodies must land the SAME
state the monolith's inline ``_install_skin`` / ``_add_file_sources`` /
``_trim_home_menu`` did. The whole-``run()`` ordering is pinned separately by the
modular_setup characterization snapshot; here we pin the layer in isolation.
"""

from __future__ import annotations

from pathlib import Path
from xml.etree import ElementTree as ET

HERE = Path(__file__).parent

# Camel-case ids the home-trim sets (the part that survives the restart), and the
# four kept ids it must never set.
_HIDE_CAMEL = [
    "HomeMenuNoMovieButton",
    "HomeMenuNoTVShowButton",
    "HomeMenuNoMusicButton",
    "HomeMenuNoMusicVideoButton",
    "HomeMenuNoRadioButton",
    "HomeMenuNoPicturesButton",
    "HomeMenuNoVideosButton",
    "HomeMenuNoGamesButton",
]
_HIDE_LOW = [c.lower() for c in _HIDE_CAMEL]


def _foundation(boot):
    """The foundation module bound under the fake Kodi (via the bootstrap)."""
    return boot.mod._foundation


def _stub_success(boot, monkeypatch):
    """Stub the skin closure + extract so the skin reports INSTALLED (the ok=True
    path the bare fake-Kodi index can't reach — skin.estuary.modv2 isn't in it).
    Returns (sel_calls, extracted) recording the ordered calls."""
    fnd = _foundation(boot)
    sel_calls = []
    extracted = []

    def _sel(selected, official_base, disable_ids, dialog, log):
        sel_calls.append(list(selected))
        for aid in selected:
            boot.state["installed"].add(aid)
        return len(selected)

    def _extract(url, dialog, pct, log):
        extracted.append(url)
        if "pvr.artwork" in url:
            boot.state["installed"].add(fnd.PVR_ARTWORK_ID)
        if "modv2plus" in url:
            boot.state["installed"].add(fnd.MODV2PLUS_ID)
        return True

    monkeypatch.setattr(fnd, "install_selection", _sel)
    monkeypatch.setattr(fnd, "extract_zip", _extract)
    monkeypatch.setattr(fnd, "install_with_deps", lambda *a, **k: True)
    monkeypatch.setattr(
        fnd, "_latest_zip_url", lambda aid: "http://local/{}-9.9.9.zip".format(aid)
    )
    return sel_calls, extracted


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


def _files_sources(boot):
    root = ET.parse(boot.sources_xml).getroot()
    files = root.find("files")
    assert files is not None, "<files> section must exist"
    return [(s.findtext("name"), s.findtext("path")) for s in files.findall("source")]


# --------------------------------------------------------------------------- #
# apply_foundation — the LayerResult contract
# --------------------------------------------------------------------------- #
def test_apply_foundation_returns_foundation_layerresult_on_success(boot, monkeypatch):
    """ok=True (skin installed), needs_skin_activation + needs_restart REQUESTED,
    SKIN_ID recorded in installed, layer tag is 'foundation'."""
    _stub_success(boot, monkeypatch)
    fnd = _foundation(boot)
    res = fnd.apply_foundation({}, dialog=None, log=boot.mod._log)

    assert res.layer == "foundation"
    assert res.ok is True
    assert res.needs_skin_activation is True
    assert res.needs_restart is True
    assert fnd.SKIN_ID in res.installed
    assert res.failed == {}


def test_apply_foundation_ok_mirrors_install_skin_bool_on_failure(boot):
    """On the bare fake-Kodi index the skin closure can't resolve, so the lifted
    _install_skin returns False — apply_foundation.ok must mirror that exactly
    (the orchestrator only activates the skin when ok), with SKIN_ID in failed.
    needs_skin_activation/needs_restart are still REQUESTED regardless."""
    fnd = _foundation(boot)
    res = fnd.apply_foundation({}, dialog=None, log=boot.mod._log)

    assert res.ok is False, "bare index cannot install the skin -> ok mirrors False"
    assert fnd.SKIN_ID in res.failed
    assert fnd.SKIN_ID not in res.installed
    assert res.needs_skin_activation is True
    assert res.needs_restart is True


def test_apply_foundation_does_not_set_lookandfeel_skin(boot, monkeypatch):
    """The activate-skin invariant: the Foundation layer NEVER sets
    lookandfeel.skin (that is the orchestrator's terminal seam). Even on the
    success path it only REQUESTS activation."""
    _stub_success(boot, monkeypatch)
    fnd = _foundation(boot)
    fnd.apply_foundation({}, dialog=None, log=boot.mod._log)
    assert "lookandfeel.skin" not in _settings_set(boot), (
        "apply_foundation must not set lookandfeel.skin — orchestrator owns it"
    )


# --------------------------------------------------------------------------- #
# Skin install: direct-extract-before-resolve + enable
# --------------------------------------------------------------------------- #
def test_apply_foundation_direct_extracts_both_proxy_invisible_deps(boot, monkeypatch):
    """pvr.artwork (GitHub-only) AND our modv2plus patch (proxy-only) are both
    direct-extracted — the closure resolver can't see them."""
    _sel_calls, extracted = _stub_success(boot, monkeypatch)
    fnd = _foundation(boot)
    fnd.apply_foundation({}, dialog=None, log=boot.mod._log)
    assert any("script.module.pvr.artwork-2.2.10.zip" in u for u in extracted), (
        "pvr.artwork must be direct-extracted from the hosted mirror"
    )
    assert any("script.tony7bones.modv2plus" in u for u in extracted), (
        "modv2plus must be direct-extracted (resolver can't see our proxy)"
    )


def test_apply_foundation_extracts_deps_before_closure_resolve(boot, monkeypatch):
    """ORDER invariant: both proxy-invisible deps are direct-extracted BEFORE the
    skin closure resolves via install_selection. install_selection records into
    `order`; the extracts must already be present when it fires."""
    fnd = _foundation(boot)
    order = []

    def _sel(selected, official_base, disable_ids, dialog, log):
        order.append(("select", list(selected), list(extracted)))
        for aid in selected:
            boot.state["installed"].add(aid)
        return len(selected)

    extracted = []

    def _extract(url, dialog, pct, log):
        extracted.append(url)
        order.append(("extract", url))
        if "pvr.artwork" in url:
            boot.state["installed"].add(fnd.PVR_ARTWORK_ID)
        if "modv2plus" in url:
            boot.state["installed"].add(fnd.MODV2PLUS_ID)
        return True

    monkeypatch.setattr(fnd, "install_selection", _sel)
    monkeypatch.setattr(fnd, "extract_zip", _extract)
    monkeypatch.setattr(fnd, "install_with_deps", lambda *a, **k: True)
    monkeypatch.setattr(
        fnd, "_latest_zip_url", lambda aid: "http://local/{}-9.9.9.zip".format(aid)
    )
    fnd.apply_foundation({}, dialog=None, log=boot.mod._log)

    sel_idx = next(i for i, e in enumerate(order) if e[0] == "select")
    extract_urls_before = [e[1] for e in order[:sel_idx] if e[0] == "extract"]
    assert any("pvr.artwork" in u for u in extract_urls_before), (
        "pvr.artwork must be extracted BEFORE install_selection resolves the closure"
    )
    assert any("modv2plus" in u for u in extract_urls_before), (
        "modv2plus must be extracted BEFORE install_selection resolves the closure"
    )
    # the select call itself saw both extracts already done
    _kind, _selected, extracted_at_select = order[sel_idx]
    assert any("pvr.artwork" in u for u in extracted_at_select)
    assert any("modv2plus" in u for u in extracted_at_select)


def test_apply_foundation_resolves_skin_closure_via_install_selection(
    boot, monkeypatch
):
    """The skin itself (skin.estuary.modv2) resolves via install_selection from the
    installed repos — exactly the [SKIN_ID] selection the monolith used."""
    sel_calls, _extracted = _stub_success(boot, monkeypatch)
    fnd = _foundation(boot)
    fnd.apply_foundation({}, dialog=None, log=boot.mod._log)
    assert [fnd.SKIN_ID] in sel_calls


def test_apply_foundation_enables_skin_closure_after_extract(boot, monkeypatch):
    """After the closure + 3s settle, pvr.artwork, modv2plus, and the skin are all
    ENABLED (registered + enabled is what lets the orchestrator activate the skin
    without Kodi reverting to stock Estuary)."""
    _stub_success(boot, monkeypatch)
    fnd = _foundation(boot)
    fnd.apply_foundation({}, dialog=None, log=boot.mod._log)
    for aid in (fnd.PVR_ARTWORK_ID, fnd.MODV2PLUS_ID, fnd.SKIN_ID):
        assert aid in boot.state["installed"], f"{aid} must be enabled/installed"


# --------------------------------------------------------------------------- #
# File-Manager sources
# --------------------------------------------------------------------------- #
def test_apply_foundation_writes_file_sources(boot, monkeypatch):
    """The three File-Manager sources land in sources.xml (the lifted
    _add_file_sources body)."""
    _stub_success(boot, monkeypatch)
    fnd = _foundation(boot)
    assert not boot.sources_xml.exists()
    fnd.apply_foundation({}, dialog=None, log=boot.mod._log)
    entries = dict(_files_sources(boot))
    assert entries["special://home"] == "special://home"
    assert entries["special://kodi"] == "/storage/emulated/0/kodi/"
    assert entries[".tony.7.bones"] == "https://tony7bones.github.io/"


# --------------------------------------------------------------------------- #
# Estuary home-menu trim (both mechanisms)
# --------------------------------------------------------------------------- #
def test_apply_foundation_trims_home_menu_setbool(boot, monkeypatch):
    """The eight Skin.SetBool hide-toggles fire on the active Estuary skin (the
    live-memory mechanism that survives the restart)."""
    _stub_success(boot, monkeypatch)
    fnd = _foundation(boot)
    fnd.apply_foundation({}, dialog=None, log=boot.mod._log)
    for camel in _HIDE_CAMEL:
        assert f"Skin.SetBool({camel})" in boot.state["builtins"], (
            f"missing home-trim toggle for {camel}"
        )
    # the four kept items are never hidden
    for keep in ("HomeMenuNoProgramsButton", "HomeMenuNoTVButton"):
        assert f"Skin.SetBool({keep})" not in boot.state["builtins"]


def test_apply_foundation_trims_home_menu_writefile(boot, monkeypatch):
    """The settings.xml belt-and-suspenders fallback writes the eight lowercase
    hide-bools = true (the lifted _trim_home_menu_writefile body)."""
    _stub_success(boot, monkeypatch)
    fnd = _foundation(boot)
    fnd.apply_foundation({}, dialog=None, log=boot.mod._log)
    assert boot.estuary_settings.exists(), "estuary settings.xml must be written"
    vals = {
        s.get("id"): (s.text or "")
        for s in ET.parse(boot.estuary_settings).getroot().findall("setting")
    }
    for low in _HIDE_LOW:
        assert vals.get(low) == "true", f"{low} must be set true"


def test_apply_foundation_runs_steps_in_skin_sources_trim_order(boot, monkeypatch):
    """The layer drives its three injected steps in the SAME order the monolith
    ran them inline in run(): skin install, then file sources, then home trim."""
    fnd = _foundation(boot)
    order = []
    res = fnd.apply_foundation(
        {},
        dialog=None,
        log=boot.mod._log,
        install_skin=lambda dialog: order.append("skin") or True,
        add_file_sources=lambda: order.append("sources"),
        trim_home_menu=lambda: order.append("trim"),
    )
    assert order == ["skin", "sources", "trim"]
    assert res.ok is True  # injected install_skin returned True


# --------------------------------------------------------------------------- #
# Injection: run() forwards the bootstrap's monkeypatchable shims
# --------------------------------------------------------------------------- #
def test_apply_foundation_uses_injected_step_functions(boot):
    """When run() injects its own step shims, apply_foundation uses THOSE (not its
    module-default bodies) — the behaviour-preservation hook that keeps
    boot.mod-level monkeypatches effective for the run()-driven path."""
    fnd = _foundation(boot)
    marker = {"skin": False, "sources": False, "trim": False}

    def _skin(dialog):
        marker["skin"] = True
        return False  # FAILED -> ok must mirror this

    res = fnd.apply_foundation(
        {},
        dialog=None,
        log=boot.mod._log,
        install_skin=_skin,
        add_file_sources=lambda: marker.__setitem__("sources", True),
        trim_home_menu=lambda: marker.__setitem__("trim", True),
    )
    assert marker == {"skin": True, "sources": True, "trim": True}
    assert res.ok is False  # injected install_skin returned False
    assert fnd.SKIN_ID in res.failed


# --------------------------------------------------------------------------- #
# Weather into Foundation (weather-into-Foundation change). The weather provider
# install + env-driven location config MOVED out of the Add-ons layer into
# Foundation — weather is part of the branded look (the MOD V2 skin renders a
# weather readout + a Weather home-menu item). The unit tests for the lifted
# weather helpers moved here with them.
# --------------------------------------------------------------------------- #
def _weather_settings(boot):
    """Multi Weather settings.xml as {id: text} (or {} if unwritten)."""
    import os
    from xml.etree import ElementTree as ET

    path = _foundation(boot)._weather_multi_settings_path()
    if not os.path.exists(path):
        return {}
    root = ET.parse(path).getroot()
    return {s.get("id"): (s.text or "") for s in root.findall("setting")}


def _stub_skin_only(boot, monkeypatch):
    """Like _stub_success, but install_with_deps RECORDS weather.multi (so the
    Foundation weather-install assertion can see it lands) instead of a blanket True."""
    _stub_success(boot, monkeypatch)

    def _iwd(addon_id, dialog, extra_bases, official_base, log):
        boot.state["installed"].add(addon_id)
        return True

    monkeypatch.setattr(boot.mod._foundation, "install_with_deps", _iwd)


def test_apply_weather_resolves_locations_and_keys(boot, monkeypatch):
    """Up to N resolved locations land as loc1..N (+ unused slots cleared), and the
    Weatherbit / OWM keys enable the optional upgrade layers."""
    fnd = _foundation(boot)
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
        fnd,
        "_resolve_weather_location",
        lambda q, **k: next((v for n, v in locs.items() if n in q), None),
    )
    fnd._apply_weather_from_env(
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
    """No resolvable env locations -> the keyless Sacramento default, NEVER an empty
    loc1_url (the load-bearing fetch field)."""
    fnd = _foundation(boot)
    monkeypatch.setattr(fnd, "_resolve_weather_location", lambda q, **k: None)
    fnd._apply_weather_from_env({"WEATHER_LOCATIONS": "Nowhere, ZZ"})
    got = _weather_settings(boot)
    assert got["loc1_url"] == "us/ca/sacramento" and got["loc1_url"]
    assert "WAdd" not in got  # no keys -> no upgrade layer


def test_apply_weather_skips_unresolvable_keeps_resolved_no_gap(boot, monkeypatch):
    """An unresolvable location is skipped; the resolved one becomes loc1 (no gap)."""
    fnd = _foundation(boot)
    monkeypatch.setattr(
        fnd,
        "_resolve_weather_location",
        lambda q, **k: (
            {"name": "Reno, NV, US", "url": "us/nv/reno", "lat": "39", "lon": "-119"}
            if "Reno" in q
            else None
        ),
    )
    fnd._apply_weather_from_env({"WEATHER_LOCATIONS": "Badtown; Reno, NV"})
    got = _weather_settings(boot)
    assert got["loc1_url"] == "us/nv/reno"
    assert got.get("loc2_url", "") == ""


def test_apply_weather_never_raises(boot, monkeypatch):
    """Defensive: any failure inside the writer is swallowed (never aborts setup)."""
    fnd = _foundation(boot)

    def _boom(*a, **k):
        raise RuntimeError("boom")

    monkeypatch.setattr(fnd, "_set_weather_settings", _boom)
    fnd._apply_weather_from_env({"WEATHER_LOCATIONS": ""})  # must not raise


def test_resolve_weather_location_returns_none_on_bad_response(boot):
    """The conftest urlopen fake returns empty bytes for the Yahoo search-assist
    endpoint, so the JSON parse fails on every retry -> None (the caller then falls
    back to the Sacramento default). Exercises the real network/parse body."""
    fnd = _foundation(boot)
    assert fnd._resolve_weather_location("Sacramento, CA") is None


def test_resolve_weather_location_parses_suggestions(boot, monkeypatch):
    """A well-formed search-assist response is parsed into {name,url,lat,lon} in the
    add-on's own field shape (name 'Town, Region, Country'; url 'country/region/town')."""
    import json as _json

    fnd = _foundation(boot)
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
    loc = fnd._resolve_weather_location("Reno, NV")
    assert loc == {
        "name": "Reno, NV, US",
        "url": "us/nv/reno",
        "lat": "39.5",
        "lon": "-119.8",
    }


def test_set_weather_settings_recreates_malformed_file(boot):
    """A malformed Multi Weather settings.xml is replaced with a valid tree (the
    ET.ParseError recovery branch) while still writing the requested settings."""
    import os

    fnd = _foundation(boot)
    path = fnd._weather_multi_settings_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write("<<not xml>>")
    fnd._set_weather_settings({"loc1_url": "us/ca/sacramento"})
    got = _weather_settings(boot)
    assert got["loc1_url"] == "us/ca/sacramento"


def test_set_weather_location_default_is_sacramento(boot):
    """The keyless fallback writes the Sacramento default location."""
    fnd = _foundation(boot)
    fnd._set_weather_location()
    got = _weather_settings(boot)
    assert got["loc1_url"] == "us/ca/sacramento"
    assert "Sacramento" in got["loc1_name"]


def test_apply_foundation_installs_and_configures_weather(boot, monkeypatch):
    """apply_foundation installs weather.multi + sets the core provider + writes the
    keyless default location — weather is now part of Foundation's branded box. The
    skin closure is stubbed (success); weather install records weather.multi via the
    install_with_deps stub, so weather.multi lands in the installed set."""
    _stub_skin_only(boot, monkeypatch)
    monkeypatch.setattr(
        boot.mod._foundation, "_resolve_weather_location", lambda q, **k: None
    )
    res = boot.mod._foundation.apply_foundation({}, dialog=None, log=boot.mod._log)
    assert "weather.multi" in boot.state["installed"], (
        "Foundation must install weather.multi"
    )
    assert res.installed.get("weather.multi") == "installed"
    assert _settings_set(boot).get("weather.addon") == "weather.multi"
    assert _weather_settings(boot)["loc1_url"] == "us/ca/sacramento"


def test_apply_foundation_weather_install_failure_is_non_fatal(boot, monkeypatch):
    """A weather install failure does NOT abort Foundation (skin still ok) — it is
    recorded in failed{} but the layer remains ok based on the SKIN install."""
    _stub_success(boot, monkeypatch)
    monkeypatch.setattr(
        boot.mod._foundation, "_resolve_weather_location", lambda q, **k: None
    )

    def _boom(addon_id, *a, **k):
        if addon_id == "weather.multi":
            raise RuntimeError("weather boom")
        return True

    monkeypatch.setattr(boot.mod._foundation, "install_with_deps", _boom)
    res = boot.mod._foundation.apply_foundation({}, dialog=None, log=boot.mod._log)
    assert res.ok is True, "a weather failure must not flip the layer (skin drives ok)"
    assert res.failed.get("weather.multi") == "weather install failed"


# --------------------------------------------------------------------------- #
# script.module.autocompletion — the on-screen-keyboard autocomplete QoL utility,
# installed by Foundation from the official repo (NOT content).
# --------------------------------------------------------------------------- #
def test_apply_foundation_installs_autocomplete(boot, monkeypatch):
    """Foundation installs script.module.autocompletion — the keyboard autocomplete
    QoL utility (helps search / IPTV portal+login typing). MUTATION: if Foundation
    stops installing it (the _install_autocomplete call dropped), it is absent from
    installed and this fails. install_with_deps records each addon (via _stub_skin_only)
    so the autocomplete install lands in the installed set."""
    _stub_skin_only(boot, monkeypatch)
    monkeypatch.setattr(
        boot.mod._foundation, "_resolve_weather_location", lambda q, **k: None
    )
    res = boot.mod._foundation.apply_foundation({}, dialog=None, log=boot.mod._log)
    assert boot.mod._foundation.AUTOCOMPLETE_ID == "script.module.autocompletion"
    assert "script.module.autocompletion" in boot.state["installed"], (
        "Foundation must install the keyboard autocomplete utility"
    )
    assert res.installed.get("script.module.autocompletion") == "installed", (
        "the Foundation LayerResult must record autocomplete installed"
    )


def test_apply_foundation_autocomplete_from_official_repo(boot, monkeypatch):
    """The autocomplete install resolves from the OFFICIAL Kodi repo (official base),
    via install_with_deps — proving it is fetched from repository.xbmc.org, not our
    proxy/third-party repos."""
    _stub_success(boot, monkeypatch)
    calls = []

    def _iwd(addon_id, dialog, extra_bases, official_base, log):
        calls.append((addon_id, official_base))
        boot.state["installed"].add(addon_id)
        return True

    monkeypatch.setattr(boot.mod._foundation, "install_with_deps", _iwd)
    monkeypatch.setattr(
        boot.mod._foundation, "_resolve_weather_location", lambda q, **k: None
    )
    boot.mod._foundation.apply_foundation({}, dialog=None, log=boot.mod._log)
    ac = [c for c in calls if c[0] == "script.module.autocompletion"]
    assert ac, "autocomplete must be installed via install_with_deps"
    assert ac[0][1] == boot.mod._foundation.OFFICIAL_BASE, (
        "autocomplete must resolve from the official Kodi repo"
    )


def test_apply_foundation_autocomplete_failure_is_non_fatal(boot, monkeypatch):
    """An autocomplete install failure does NOT abort Foundation (skin still drives
    ok) — it is recorded in failed{} but the layer remains ok."""
    _stub_success(boot, monkeypatch)
    monkeypatch.setattr(
        boot.mod._foundation, "_resolve_weather_location", lambda q, **k: None
    )

    def _boom(addon_id, *a, **k):
        if addon_id == "script.module.autocompletion":
            raise RuntimeError("autocomplete boom")
        return True

    monkeypatch.setattr(boot.mod._foundation, "install_with_deps", _boom)
    res = boot.mod._foundation.apply_foundation({}, dialog=None, log=boot.mod._log)
    assert res.ok is True, "an autocomplete failure must not flip the layer"
    assert res.failed.get("script.module.autocompletion") == (
        "autocomplete install failed"
    )
