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
