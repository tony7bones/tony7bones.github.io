"""Unit tests for the Skin layer (plan section 3.3, Phase 4).

``tony7bones.setup.skin.apply_skin`` is the Skin layer entry point: it installs
the Estuary MOD V2 skin + the MOD V2+ patch closure (direct-extracting the two
proxy-invisible deps — ``script.module.pvr.artwork`` + our own
``script.tony7bones.modv2plus`` — BEFORE the closure resolve), then trims the
STOCK Estuary home menu, and returns a ``LayerResult`` REQUESTING skin
activation + restart from the orchestrator. It deliberately does NOT set
``lookandfeel.skin`` — that stays the orchestrator's terminal seam.

This layer was split OUT of the Foundation layer (``tony7bones.setup.
foundation``, which used to bundle the skin closure + trim alongside its
content-free config) — see ``docs/plans/automate-share-and-backup-config.md``
section 3.1/3.3: the skin is curatorial branding, not a Foundation prerequisite.
These tests are the direct descendants of ``test_setup_foundation.py``'s old
skin-closure tests, moved here with the code.

These tests drive ``apply_skin`` (and the lifted ``_install_skin`` body)
DIRECTLY against the shared fake-Kodi ``boot`` fixture (conftest.py) — the same
real engine the bootstrap suite uses, reached via ``boot.mod._skin`` (the skin
module the bootstrap imports under the fake Kodi). This is the
behaviour-preserving oracle for the move: the skin bodies must land the SAME
state the monolith's inline ``_install_skin`` / ``_trim_home_menu`` did. The
whole-``run()`` ordering is pinned separately by the modular_setup
characterization snapshot; here we pin the layer in isolation.
"""

from __future__ import annotations

from xml.etree import ElementTree as ET

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


def _skin(boot):
    """The skin module bound under the fake Kodi (via the bootstrap)."""
    return boot.mod._skin


def _stub_success(boot, monkeypatch):
    """Stub the skin closure + extract so the skin reports INSTALLED (the ok=True
    path the bare fake-Kodi index can't reach — skin.estuary.modv2 isn't in it).
    Returns (sel_calls, extracted) recording the ordered calls."""
    skn = _skin(boot)
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
            boot.state["installed"].add(skn.PVR_ARTWORK_ID)
        if "modv2plus" in url:
            boot.state["installed"].add(skn.MODV2PLUS_ID)
        return True

    monkeypatch.setattr(skn, "install_selection", _sel)
    monkeypatch.setattr(skn, "extract_zip", _extract)
    monkeypatch.setattr(skn, "install_with_deps", lambda *a, **k: True)
    monkeypatch.setattr(
        skn, "_latest_zip_url", lambda aid: "http://local/{}-9.9.9.zip".format(aid)
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


# --------------------------------------------------------------------------- #
# apply_skin — the LayerResult contract
# --------------------------------------------------------------------------- #
def test_apply_skin_returns_skin_layerresult_on_success(boot, monkeypatch):
    """ok=True (skin installed), needs_skin_activation + needs_restart REQUESTED,
    SKIN_ID recorded in installed, layer tag is 'skin'."""
    _stub_success(boot, monkeypatch)
    skn = _skin(boot)
    res = skn.apply_skin({}, dialog=None, log=boot.mod._log)

    assert res.layer == "skin"
    assert res.ok is True
    assert res.needs_skin_activation is True
    assert res.needs_restart is True
    assert skn.SKIN_ID in res.installed
    assert res.failed == {}


def test_apply_skin_ok_mirrors_install_skin_bool_on_failure(boot):
    """On the bare fake-Kodi index the skin closure can't resolve, so the lifted
    _install_skin returns False — apply_skin.ok must mirror that exactly (the
    orchestrator only activates the skin when ok), with SKIN_ID in failed.
    needs_skin_activation/needs_restart are still REQUESTED regardless."""
    skn = _skin(boot)
    res = skn.apply_skin({}, dialog=None, log=boot.mod._log)

    assert res.ok is False, "bare index cannot install the skin -> ok mirrors False"
    assert skn.SKIN_ID in res.failed
    assert skn.SKIN_ID not in res.installed
    assert res.needs_skin_activation is True
    assert res.needs_restart is True


def test_apply_skin_does_not_set_lookandfeel_skin(boot, monkeypatch):
    """The activate-skin invariant: the Skin layer NEVER sets lookandfeel.skin
    (that is the orchestrator's terminal seam). Even on the success path it only
    REQUESTS activation."""
    _stub_success(boot, monkeypatch)
    skn = _skin(boot)
    skn.apply_skin({}, dialog=None, log=boot.mod._log)
    assert "lookandfeel.skin" not in _settings_set(boot), (
        "apply_skin must not set lookandfeel.skin — orchestrator owns it"
    )


# --------------------------------------------------------------------------- #
# Skin install: direct-extract-before-resolve + enable
# --------------------------------------------------------------------------- #
def test_apply_skin_direct_extracts_both_proxy_invisible_deps(boot, monkeypatch):
    """pvr.artwork (GitHub-only) AND our modv2plus patch (proxy-only) are both
    direct-extracted — the closure resolver can't see them."""
    _sel_calls, extracted = _stub_success(boot, monkeypatch)
    skn = _skin(boot)
    skn.apply_skin({}, dialog=None, log=boot.mod._log)
    assert any("script.module.pvr.artwork-2.2.10.zip" in u for u in extracted), (
        "pvr.artwork must be direct-extracted from the hosted mirror"
    )
    assert any("script.tony7bones.modv2plus" in u for u in extracted), (
        "modv2plus must be direct-extracted (resolver can't see our proxy)"
    )


def test_apply_skin_extracts_deps_before_closure_resolve(boot, monkeypatch):
    """ORDER invariant: both proxy-invisible deps are direct-extracted BEFORE the
    skin closure resolves via install_selection. install_selection records into
    `order`; the extracts must already be present when it fires."""
    skn = _skin(boot)
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
            boot.state["installed"].add(skn.PVR_ARTWORK_ID)
        if "modv2plus" in url:
            boot.state["installed"].add(skn.MODV2PLUS_ID)
        return True

    monkeypatch.setattr(skn, "install_selection", _sel)
    monkeypatch.setattr(skn, "extract_zip", _extract)
    monkeypatch.setattr(skn, "install_with_deps", lambda *a, **k: True)
    monkeypatch.setattr(
        skn, "_latest_zip_url", lambda aid: "http://local/{}-9.9.9.zip".format(aid)
    )
    skn.apply_skin({}, dialog=None, log=boot.mod._log)

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


def test_apply_skin_resolves_skin_closure_via_install_selection(boot, monkeypatch):
    """The skin itself (skin.estuary.modv2) resolves via install_selection from the
    installed repos — exactly the [SKIN_ID] selection the monolith used."""
    sel_calls, _extracted = _stub_success(boot, monkeypatch)
    skn = _skin(boot)
    skn.apply_skin({}, dialog=None, log=boot.mod._log)
    assert [skn.SKIN_ID] in sel_calls


def test_apply_skin_enables_skin_closure_after_extract(boot, monkeypatch):
    """After the closure + 3s settle, pvr.artwork, modv2plus, and the skin are all
    ENABLED (registered + enabled is what lets the orchestrator activate the skin
    without Kodi reverting to stock Estuary)."""
    _stub_success(boot, monkeypatch)
    skn = _skin(boot)
    skn.apply_skin({}, dialog=None, log=boot.mod._log)
    for aid in (skn.PVR_ARTWORK_ID, skn.MODV2PLUS_ID, skn.SKIN_ID):
        assert aid in boot.state["installed"], f"{aid} must be enabled/installed"


# --------------------------------------------------------------------------- #
# Estuary home-menu trim (both mechanisms) — tightly coupled to the skin.
# --------------------------------------------------------------------------- #
def test_apply_skin_trims_home_menu_setbool(boot, monkeypatch):
    """The eight Skin.SetBool hide-toggles fire on the active Estuary skin (the
    live-memory mechanism that survives the restart)."""
    _stub_success(boot, monkeypatch)
    skn = _skin(boot)
    skn.apply_skin({}, dialog=None, log=boot.mod._log)
    for camel in _HIDE_CAMEL:
        assert f"Skin.SetBool({camel})" in boot.state["builtins"], (
            f"missing home-trim toggle for {camel}"
        )
    # the four kept items are never hidden
    for keep in ("HomeMenuNoProgramsButton", "HomeMenuNoTVButton"):
        assert f"Skin.SetBool({keep})" not in boot.state["builtins"]


def test_apply_skin_trims_home_menu_writefile(boot, monkeypatch):
    """The settings.xml belt-and-suspenders fallback writes the eight lowercase
    hide-bools = true (the lifted _trim_home_menu_writefile body)."""
    _stub_success(boot, monkeypatch)
    skn = _skin(boot)
    skn.apply_skin({}, dialog=None, log=boot.mod._log)
    assert boot.estuary_settings.exists(), "estuary settings.xml must be written"
    vals = {
        s.get("id"): (s.text or "")
        for s in ET.parse(boot.estuary_settings).getroot().findall("setting")
    }
    for low in _HIDE_LOW:
        assert vals.get(low) == "true", f"{low} must be set true"


def test_apply_skin_runs_steps_in_skin_trim_order(boot):
    """The layer drives its two injected steps in the SAME order the monolith
    ran them inline in run(): skin install, then home trim."""
    skn = _skin(boot)
    order = []
    res = skn.apply_skin(
        {},
        dialog=None,
        log=boot.mod._log,
        install_skin=lambda dialog: order.append("skin") or True,
        trim_home_menu=lambda: order.append("trim"),
    )
    assert order == ["skin", "trim"]
    assert res.ok is True  # injected install_skin returned True


# --------------------------------------------------------------------------- #
# Injection: run() forwards the bootstrap's monkeypatchable shims
# --------------------------------------------------------------------------- #
def test_apply_skin_uses_injected_step_functions(boot):
    """When run() injects its own step shims, apply_skin uses THOSE (not its
    module-default bodies) — the behaviour-preservation hook that keeps
    boot.mod-level monkeypatches effective for the run()-driven path."""
    skn = _skin(boot)
    marker = {"skin": False, "trim": False}

    def _install(dialog):
        marker["skin"] = True
        return False  # FAILED -> ok must mirror this

    res = skn.apply_skin(
        {},
        dialog=None,
        log=boot.mod._log,
        install_skin=_install,
        trim_home_menu=lambda: marker.__setitem__("trim", True),
    )
    assert marker == {"skin": True, "trim": True}
    assert res.ok is False  # injected install_skin returned False
    assert skn.SKIN_ID in res.failed
