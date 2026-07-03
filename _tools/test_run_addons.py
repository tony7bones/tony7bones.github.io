"""Tests for run_addons — the standalone Add-ons orchestrator (Phase 5c).

``run_addons`` makes the Add-ons layer INDEPENDENTLY-RUNNABLE: the opinionated
curated content set (base apps + POV / The Loop / Sports HD / YouTube) as an
opt-in layer on top of an existing Foundation. Stop here = the full box.

What it MUST do:
  * drive the SAME ``apply_addons`` the Express one-shot drives (the no-fork
    invariant) — base source repos + base apps + curated video (incl. the
    install-then-disable of plugin.video.dailymotion_com);
  * show an HONEST summary (per-stage counts from the LayerResult), then
    self-uninstall, then ONE platform-aware restart — in that order.

What it MUST NOT do — the layer invariants (the heart of this phase):
  * NO skin touch: no ``activate_skin``, no ``lookandfeel.skin``, no
    ``Skin.SetBool`` (re-setting the skin re-arms Kodi's "Keep this skin?"
    revert timeout; Foundation owns the active skin);
  * NO orchestrator-level ``install_repos`` call (Foundation owns plumbing —
    the LAYER's own base step keeps its historical idempotent repo loop, shared
    verbatim with Express);
  * NO ``apply_foundation`` / ``apply_iptv`` (one layer per runner — no skin
    closure, no weather install, no pvr.iptvsimple, no IPTV instance-settings).

These tests drive ``run_addons`` against the shared fake-Kodi ``boot`` fixture
(conftest.py) — the same real engine the Express and Foundation orchestrator
tests use. The bare fixture is a FOUNDATION-LESS box, so every real-engine test
here also proves the decided Foundation-missing semantics: the curated content
still lands (apply_addons installs the source repos itself), no probe-and-abort.

Mutation proof (the killers this phase demands):
  * ``test_run_addons_installs_curated_set`` — drop the ``apply_addons`` call (or
    a video id from VIDEO_APPS) and the curated set is absent.
  * ``test_run_addons_never_touches_skin`` / ``..._no_skin_or_plumbing_calls`` —
    add an ``activate_skin`` / ``lookandfeel.skin`` / ``install_repos`` call to
    the orchestrator body and these fail.
  * ``test_run_addons_installs_no_foundation_or_iptv`` — call a foreign layer
    and its ids leak into the installed set.
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


def _stub_video_success(boot, monkeypatch, video_ok=None):
    """Make the curated-video stage install (the bare fake index can't resolve
    POV/Loop/SportsHD/YouTube). Patches install_selection on the ADD-ONS layer
    module (apply_addons' _install_video resolves it from addons' globals). The
    base repos + apps still go through the REAL engine (the fake urlopen builds
    real zips and the fake index resolves the app closures), so those installs
    are genuine, not stubbed. ``video_ok`` caps how many video apps "install"
    (None = all), for the honest-summary partial-failure test."""

    def _sel(selected, official_base, disable_ids, dialog, log):
        # The real install_selection enables the source repos as part of resolving
        # a closure (repos.enable_source_repos); mirror it so the stub faithfully
        # reproduces the full-run repo-enable behaviour.
        from tony7bones import enable_source_repos

        enable_source_repos(log)
        n = len(selected) if video_ok is None else min(video_ok, len(selected))
        for aid in selected[:n]:
            boot.state["extracted"].add(aid)
            boot.state["installed"].add(aid)
        if n:
            for aid in disable_ids:
                boot.state["installed"].add(aid)
                boot.state["disabled"].add(aid)
        return n

    monkeypatch.setattr(boot.mod._addons, "install_selection", _sel)
    # Don't actually restart.
    monkeypatch.setattr(boot.mod, "restart_kodi", lambda *a, **k: None)


def _fake_ok_result(boot):
    """A minimal successful Add-ons LayerResult for orchestrator-only tests."""
    from tony7bones.setup.result import LayerResult

    return LayerResult(layer="addons", ok=True, installed={}, needs_restart=True)


# Foundation/IPTV add-on ids that must NEVER be installed by the Add-ons runner.
_FOUNDATION_IDS = [
    "skin.estuary.modv2",
    "script.tony7bones.modv2plus",
    "script.module.pvr.artwork",
    "resource.images.weathericons.outline-hd",
    "weather.multi",
    "script.module.autocompletion",
]
_PVR_IDS = ["pvr.iptvsimple", "inputstream.ffmpegdirect"]


def _repo_installed(boot, rid):
    """Whether a repo id landed in `installed`, honoring the pre-existing
    repository.diggz vs repository.diggz.zip quirk (the zip's inner id carries
    the .zip suffix, faithfully pinned by the characterization snapshot)."""
    return rid in boot.state["installed"] or rid + ".zip" in boot.state["installed"]


# --------------------------------------------------------------------------- #
# run_addons returns the Add-ons LayerResult.
# --------------------------------------------------------------------------- #
def test_run_addons_returns_addons_layerresult(boot, monkeypatch):
    """run_addons returns the Add-ons LayerResult (layer='addons', ok=True on a
    non-cancelled run, needs_restart requested)."""
    _stub_video_success(boot, monkeypatch)
    res = boot.mod.run_addons({})
    assert res.layer == "addons"
    assert res.ok is True
    assert res.needs_restart is True


# --------------------------------------------------------------------------- #
# The curated set lands (mutation killer #1: drop apply_addons / a video id).
# --------------------------------------------------------------------------- #
def test_run_addons_installs_curated_set(boot, monkeypatch):
    """The full curated content set lands: BOTH base apps and ALL FOUR curated
    video add-ons installed + enabled, plugin.video.dailymotion_com installed
    then DISABLED (the install-then-disable contract). MUTATION: dropping the
    apply_addons call (or any id from ADDONS/VIDEO_APPS) fails here."""
    _stub_video_success(boot, monkeypatch)
    res = boot.mod.run_addons({})

    for aid in boot.mod.ADDONS:
        assert aid in boot.state["installed"], f"base app {aid} must install"
        assert res.installed.get(aid) == "installed"
    for aid in boot.mod.VIDEO_APPS:
        assert aid in boot.state["installed"], f"video app {aid} must install"
        assert res.installed.get(aid) == "installed"
    # install-then-disable: dailymotion is INSTALLED (dep check satisfied) and
    # DISABLED (never runs) — recorded as state "disabled" in the LayerResult.
    assert "plugin.video.dailymotion_com" in boot.state["installed"]
    assert "plugin.video.dailymotion_com" in boot.state["disabled"]
    assert res.installed.get("plugin.video.dailymotion_com") == "disabled"


def test_run_addons_installs_repos_on_foundationless_box(boot, monkeypatch):
    """The decided Foundation-missing semantics: on a box WITHOUT Foundation (the
    bare fixture) run_addons still works — apply_addons' base step installs the
    source repos itself, so the content closures resolve. No probe-and-abort."""
    _stub_video_success(boot, monkeypatch)
    boot.mod.run_addons({})
    for _z, rid in boot.mod.REPO_ZIPS:
        assert _repo_installed(boot, rid), (
            f"repo {rid} must install (the layer's own idempotent base step)"
        )


# --------------------------------------------------------------------------- #
# The no-skin-touch invariant (mutation killer #2).
# --------------------------------------------------------------------------- #
def test_run_addons_never_touches_skin(boot, monkeypatch):
    """run_addons NEVER touches the skin: activate_skin is not called,
    lookandfeel.skin is not set, and no Skin.Set* builtin is issued — re-setting
    the skin would re-arm Kodi's "Keep this skin?" revert timeout (Foundation
    owns the active skin). MUTATION: add any skin call to the orchestrator and
    this fails."""
    _stub_video_success(boot, monkeypatch)
    activated = []
    monkeypatch.setattr(boot.mod, "activate_skin", lambda *a, **k: activated.append(a))
    boot.mod.run_addons({})

    assert activated == [], "run_addons must never call activate_skin"
    settings = _settings_set(boot)
    assert "lookandfeel.skin" not in settings, (
        "run_addons must never set lookandfeel.skin"
    )
    skin_builtins = [b for b in boot.state["builtins"] if b.startswith("Skin.Set")]
    assert skin_builtins == [], (
        f"run_addons must issue no Skin.Set* builtin; got {skin_builtins}"
    )


# --------------------------------------------------------------------------- #
# One layer per runner: no Foundation, no IPTV (installed-set proof).
# --------------------------------------------------------------------------- #
def test_run_addons_installs_no_foundation_or_iptv(boot, monkeypatch):
    """run_addons installs NONE of the Foundation closure (skin / modv2plus /
    pvr.artwork / outline-hd / weather.multi / autocomplete) and NO PVR backend,
    and writes NO IPTV instance-settings — at the REAL-engine level. MUTATION:
    calling apply_foundation or apply_iptv from the orchestrator leaks an id
    here and fails."""
    import os

    _stub_video_success(boot, monkeypatch)
    boot.mod.run_addons({})

    leaked = [
        aid for aid in _FOUNDATION_IDS + _PVR_IDS if aid in boot.state["installed"]
    ]
    assert leaked == [], f"run_addons leaked foreign-layer add-ons: {leaked}"
    iptv_path = boot.mod.xbmcvfs.translatePath(boot.mod.IPTV_INSTANCE_SETTINGS_SPECIAL)
    assert not os.path.exists(iptv_path), (
        "run_addons must not write pvr.iptvsimple instance-settings"
    )
    # weather is Foundation's job (Phase 5a·2): no provider set, no location write.
    assert "weather.addon" not in _settings_set(boot), (
        "the weather provider core setting belongs to Foundation"
    )


def test_run_addons_orchestrator_no_skin_or_plumbing_calls(boot, monkeypatch):
    """STRUCTURAL invariant on the orchestrator BODY (apply_addons stubbed out):
    run_addons itself calls neither install_repos (Foundation owns plumbing; the
    layer's internal base step is apply_addons' own) nor apply_foundation /
    apply_iptv / activate_skin. MUTATION: adding any such call to the body —
    e.g. mirroring _foundation_core's install_repos(dialog) — fails here even
    though the layer call is stubbed."""
    called = []
    monkeypatch.setattr(boot.mod, "apply_addons", lambda *a, **k: _fake_ok_result(boot))
    for name in ("install_repos", "apply_foundation", "apply_iptv", "activate_skin"):
        monkeypatch.setattr(boot.mod, name, lambda *a, _n=name, **k: called.append(_n))
    monkeypatch.setattr(boot.mod, "restart_kodi", lambda *a, **k: None)
    boot.mod.run_addons({})
    assert called == [], (
        f"the run_addons body must make no skin/plumbing/foreign-layer call; "
        f"got {called}"
    )


# --------------------------------------------------------------------------- #
# The terminal seam: summary -> self-uninstall -> ONE restart, restart LAST.
# --------------------------------------------------------------------------- #
def test_run_addons_self_uninstalls_after_summary_before_restart(boot, monkeypatch):
    """run_addons self-uninstalls exactly once, AFTER the summary Dialog().ok and
    BEFORE the restart (the terminal-seam ordering shared with run_foundation)."""
    events = []
    _stub_video_success(boot, monkeypatch)

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
    boot.mod.run_addons({})

    assert events == ["summary", "self_uninstall", "restart"], (
        f"order must be summary -> self_uninstall -> restart, got {events}"
    )


def test_run_addons_restarts_exactly_once(boot, monkeypatch):
    """ONE restart, via the existing platform-aware primitive (restart_kodi) —
    honoring the layer's needs_restart request, never more than once."""
    restarts = []
    _stub_video_success(boot, monkeypatch)
    monkeypatch.setattr(boot.mod, "restart_kodi", lambda *a, **k: restarts.append(a))
    boot.mod.run_addons({})
    assert len(restarts) == 1, f"exactly one restart, got {len(restarts)}"


# --------------------------------------------------------------------------- #
# Honest summary — counts straight from the LayerResult.
# --------------------------------------------------------------------------- #
def test_run_addons_summary_reports_honest_counts(boot, monkeypatch):
    """The summary reports the real per-stage counts (Repos x/12, Apps x/2,
    Video x/4) from the LayerResult — full success here."""
    _stub_video_success(boot, monkeypatch)
    boot.mod.run_addons({})
    assert boot.state["ok"], "the summary dialog must be shown"
    title, msg = boot.state["ok"][-1]
    assert title == "Tony.7.Bones Setup"
    assert f"Repos: {len(boot.mod.REPO_ZIPS)}/{len(boot.mod.REPO_ZIPS)}" in msg
    assert f"Apps: {len(boot.mod.ADDONS)}/{len(boot.mod.ADDONS)}" in msg
    assert (
        f"Video add-ons: {len(boot.mod.VIDEO_APPS)}/{len(boot.mod.VIDEO_APPS)}" in msg
    )
    assert "Restart will finish setup." in msg


def test_run_addons_summary_honest_on_partial_video_failure(boot, monkeypatch):
    """A partial video failure shows the HONEST count (e.g. 'Video add-ons: 2/4'),
    never a false success — and the box still completes (summary + uninstall +
    restart; install failures are non-fatal, matching Express)."""
    events = []
    _stub_video_success(boot, monkeypatch, video_ok=2)
    monkeypatch.setattr(
        boot.mod, "self_uninstall", lambda *a, **k: events.append("self_uninstall")
    )
    monkeypatch.setattr(
        boot.mod, "restart_kodi", lambda *a, **k: events.append("restart")
    )
    res = boot.mod.run_addons({})
    _title, msg = boot.state["ok"][-1]
    assert "Video add-ons: 2/4" in msg, f"summary must be honest, got: {msg}"
    assert res.ok is True, "a partial failure is non-fatal (not a cancel)"
    assert len(res.failed) == 2, "the two missing video apps must be in failed"
    assert events == ["self_uninstall", "restart"], "the box still completes"


# --------------------------------------------------------------------------- #
# Cancel semantics: the only abort path — no summary, no uninstall, no restart.
# --------------------------------------------------------------------------- #
def test_run_addons_cancel_aborts_cleanly(boot, monkeypatch):
    """A user cancel mid-install (the REAL dialog-cancel path through the engine)
    aborts cleanly: NO summary, NO self-uninstall, NO restart — the monolith's
    early-return contract (a re-run completes the partial install; the driver
    leaves the env intact)."""
    events = []
    monkeypatch.setattr(
        boot.mod.xbmcgui.DialogProgress, "iscanceled", lambda self: True
    )
    monkeypatch.setattr(
        boot.mod, "self_uninstall", lambda *a, **k: events.append("self_uninstall")
    )
    monkeypatch.setattr(
        boot.mod, "restart_kodi", lambda *a, **k: events.append("restart")
    )
    res = boot.mod.run_addons({})
    assert res.ok is False, "a cancelled run must report ok=False"
    assert boot.state["ok"] == [], "no summary on cancel"
    assert events == [], "no self-uninstall and no restart on cancel"


# --------------------------------------------------------------------------- #
# Env lifecycle: passed in, forwarded verbatim; the runner never reads/deletes.
# --------------------------------------------------------------------------- #
def test_run_addons_passes_env_through_verbatim(boot, monkeypatch):
    """The parsed env dict is forwarded to apply_addons VERBATIM (read-once is the
    driver's job); None is normalized to {} (the no-env desktop run)."""
    seen = []

    def _spy(env, *, dialog=None, log=None):
        seen.append(env)
        return _fake_ok_result(boot)

    monkeypatch.setattr(boot.mod, "apply_addons", _spy)
    monkeypatch.setattr(boot.mod, "restart_kodi", lambda *a, **k: None)
    env = {"RSS_FEEDS": "http://feeds.example/a.xml", "RSS_INTERVAL": "15"}
    boot.mod.run_addons(env)
    boot.mod.run_addons(None)
    assert seen[0] is env, "the env dict must be forwarded verbatim"
    assert seen[1] == {}, "None must normalize to the empty env"


def test_run_addons_never_writes_rss(boot, monkeypatch):
    """RSS moved to the Foundation layer — run_addons must NOT enable the RSS
    ticker or write RssFeeds.xml, even when the env supplies RSS_FEEDS."""
    _stub_video_success(boot, monkeypatch)
    boot.mod.run_addons(
        {"RSS_FEEDS": "http://feeds.example/a.xml; http://feeds.example/b.xml"}
    )
    assert "lookandfeel.enablerssfeeds" not in _settings_set(boot), (
        "run_addons must not enable the RSS ticker (Foundation's job now)"
    )
    rss_path = boot.sources_xml.parent / "RssFeeds.xml"
    assert not rss_path.exists(), "run_addons must not write RssFeeds.xml"


# --------------------------------------------------------------------------- #
# Re-entry: a second run is safe by construction (no duplicates, no flips).
# --------------------------------------------------------------------------- #
def test_run_addons_reentry_second_run_is_clean(boot, monkeypatch):
    """Running run_addons twice leaves the box state IDENTICAL: the installed set
    does not change, dailymotion stays disabled (the disable-after re-apply is
    idempotent), and the second run still reports ok. NOTE: already_done stays
    False on re-entry by DESIGN — the install primitives don't distinguish
    already-present from freshly-installed (documented in apply_addons); true
    re-entry detection is the Phase-5d orchestrator's installed-state probes."""
    _stub_video_success(boot, monkeypatch)
    res1 = boot.mod.run_addons({})
    first_installed = set(boot.state["installed"])
    first_disabled = set(boot.state["disabled"])

    res2 = boot.mod.run_addons({})
    assert res2.ok is True
    assert res2.already_done is False  # documented semantics — see docstring
    assert set(boot.state["installed"]) == first_installed, (
        "re-entry must not change the installed set"
    )
    assert set(boot.state["disabled"]) == first_disabled, (
        "dailymotion must stay disabled on re-entry"
    )
    assert res1.failed == {} and res2.failed == {}
