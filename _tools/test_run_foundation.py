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
    skin.estuary.modv2). Patch the LAYER modules + the bootstrap module's primitives
    (run_foundation calls apply_foundation via the BARE form, so the layer resolves
    install_selection/extract_zip from foundation's globals). Repos still go through
    the REAL engine (extract_zip on the addons module / the fake urlopen builds real
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

    fnd = boot.mod._foundation
    monkeypatch.setattr(fnd, "install_selection", _sel)
    monkeypatch.setattr(fnd, "extract_zip", _extract_skin)
    monkeypatch.setattr(fnd, "install_with_deps", lambda *a, **k: True)
    monkeypatch.setattr(
        fnd, "_latest_zip_url", lambda aid: f"http://local/{aid}-9.9.9.zip"
    )
    # Don't actually restart.
    monkeypatch.setattr(boot.mod, "restart_kodi", lambda *a, **k: None)


# Content add-on ids that must NEVER be installed by Foundation.
_BASE_APPS = ["script.ezmaintenanceplus", "script.realdebrid", "weather.multi"]
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


def test_run_foundation_writes_no_iptv_or_weather(boot, monkeypatch):
    """No IPTV instance-settings and no weather/RSS core settings are written —
    Foundation does not touch pvr.iptvsimple's instance file and does not set the
    weather provider / RSS-enable core settings (those are Add-ons/IPTV layer work)."""
    _stub_skin_success(boot, monkeypatch)
    boot.mod.run_foundation({})

    settings = _settings_set(boot)
    assert "weather.addon" not in settings, (
        "Foundation must not set the weather provider"
    )
    assert "lookandfeel.enablerssfeeds" not in settings, (
        "Foundation must not enable the RSS ticker (Add-ons layer work)"
    )
    iptv_path = boot.mod.xbmcvfs.translatePath(boot.mod.IPTV_INSTANCE_SETTINGS_SPECIAL)
    import os

    assert not os.path.exists(iptv_path), (
        "Foundation must not write pvr.iptvsimple instance-settings"
    )


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
