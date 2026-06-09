"""Characterization golden-snapshot of the monolithic Setup ``run()``.

This pins the CURRENT observable behaviour of the one-shot
``script.tony7bones.bootstrap`` ``default.py`` ``run()`` as the oracle the later
modular-setup phases must reproduce ("Express must reproduce the monolith"). It
drives ``run()`` under the shared fake-Kodi ``boot`` fixture (conftest.py) and
captures a stable, diff-friendly snapshot of its observable effect that is
asserted equal to a committed expected file (``modular_setup_snapshot.json``),
PLUS a set of focused RUNTIME assertions (below) that pin the terminal wiring the
snapshot alone cannot.

TWO snapshots are pinned, because the bare fake-Kodi fixture cannot resolve the
video add-ons or the Estuary MOD V2 skin closure (they are not in the fixture's
fake repo index), so a bare run takes run()'s "skin FAILED / 0 video" path:

* ``bare`` — run() over the fixture's REAL engine. The base repos + apps + their
  full dependency closure install for real (proxy-invisible pvr.artwork and the
  modv2plus patch direct-extract); video resolves to 0 and the skin reports
  FAILED, so ``activate_skin`` does NOT fire. This pins the real install engine's
  exact id set, enable order, settings, summary, and config-file writes.
* ``full`` — run() with the video + skin pieces stubbed to succeed (the same
  technique test_bootstrap.py's skin/video tests use). This drives run() all the
  way through the terminal seam: the skin installs, ``activate_skin`` fires,
  ``lookandfeel.skin`` is written LAST, and the bootstrap's OWN add-on directory
  is pre-created so the real ``self_uninstall`` deletion is observable. This pins
  the activate-skin-before-restart cadence AND the self-uninstall the bare path
  can't reach.

What each snapshot field captures (and why each representation is chosen):

* ``installed`` / ``extracted`` / ``disabled`` — the resulting add-on-id sets,
  SORTED. Membership is what matters, not the order Kodi scanned them (Python
  ``set``s in the fake — their order is not meaningful).
* ``enable_sequence`` — the ORDERED ``Addons.SetAddonEnabled`` (id, enabled)
  list. ORDER-SENSITIVE: repos enable before apps, the skin closure after; a
  regression that reordered enable-before-extract is exactly what this catches.
* ``settings`` — the ORDERED ``Settings.SetSettingValue`` calls. The terminal
  ``lookandfeel.skin`` MUST be LAST (the activate-skin invariant), so order is
  load-bearing.
* ``builtins`` — the ORDERED meaningful ``executebuiltin`` calls (UpdateLocalAddons,
  the eight Skin.SetBool home-trim toggles + the weather top-bar toggle). The
  restart builtin (``RestartApp()``) is deliberately NOT in this list — it is
  pinned at runtime instead (see below) so the snapshot stays free of the
  yesno-acceptance test artifact.
* ``summary`` — the final ``Dialog().ok`` summary text (Repos/Apps/Video/skin
  counts) — the user-visible contract of a completed run.
* ``self_uninstalled`` — whether run() deleted its OWN add-on directory by the
  end. In the ``full`` snapshot the fixture pre-creates that dir, so this captures
  the REAL ``self_uninstall`` effect (True). In ``bare`` the dir is absent, so
  ``self_uninstall`` is a guarded no-op and this is False — that asymmetry is
  intentional and documents the gating.
* ``files`` — sources.xml + the Estuary home-trim settings + weather.multi
  settings, parsed into id->value maps so the assert diffs on MEANING, not XML
  byte layout.

What the SNAPSHOT deliberately does NOT capture, and why:

* No raw URLs / zip filenames — those embed the host's binary platform tag
  (osx-arm64 vs osx-x86_64) and the live modv2plus version, making the snapshot
  host- and release-dependent. Add-on IDS are platform-independent, so we pin
  ids, not download URLs. (The snapshot is generated + the gate run on the same
  machine; the id set itself is arch-independent.)
* No timestamps, durations, or progress percentages — non-deterministic noise.
* No instance-settings / RssFeeds files — on a no-env desktop run those steps are
  guarded no-ops; the env-driven IPTV/RSS behaviour is already pinned by
  test_bootstrap.py.

What is pinned by the RUNTIME assertions instead of the snapshot (these survive a
``run()`` decomposition, because they observe the real imported symbols at call
time rather than grepping ``default.py`` source — they replace the source-grep
order tests in test_bootstrap.py that will be deleted when ``run()`` is split):

* ``test_full_run_sets_lookandfeel_skin_last`` — ``lookandfeel.skin`` is the LAST
  core setting and is written exactly once (the activate-skin invariant).
* ``test_bare_run_does_not_activate_skin`` — a FAILED skin is never activated.
* ``test_full_run_restarts_once_after_summary`` — run() invokes the desktop
  restart EXACTLY ONCE and AFTER the summary ``Dialog().ok`` (the restart is
  driven for real by accepting the fixture's yesno, and spied via the imported
  ``restart_kodi`` symbol so removing the call makes the assertion fail).
* ``test_full_run_self_uninstalls_after_summary`` — run() self-uninstalls exactly
  once, after the summary and before the restart (spied via the imported
  ``self_uninstall`` symbol).
* ``test_cancel_path_does_nothing_terminal`` — when the progress dialog is
  cancelled mid-install, run() writes NO ``lookandfeel.skin``, fires NO restart,
  does NO self-uninstall (its dir survives), and shows NO success summary.

Determinism: sets are sorted, no timestamps. The snapshot is byte-stable across
runs. To regenerate after an INTENTIONAL behaviour change, set
``UPDATE_SNAPSHOT=1`` (refused under CI so the gate can never self-baseline).
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest

SNAPSHOT_PATH = Path(__file__).parent / "modular_setup_snapshot.json"


def _decode_jsonrpc(raw_calls):
    """Split captured JSON-RPC strings into (enable_sequence, settings).

    enable_sequence: ordered [{"id":..., "enabled":bool}] from SetAddonEnabled.
    settings:        ordered [{"setting":..., "value":...}] from SetSettingValue.
    Order is preserved exactly as run() emitted them (load-bearing).
    """
    enable_sequence = []
    settings = []
    for raw in raw_calls:
        try:
            d = json.loads(raw)
        except (ValueError, TypeError):
            continue
        method = d.get("method")
        params = d.get("params", {})
        if method == "Addons.SetAddonEnabled":
            enable_sequence.append(
                {
                    "id": params.get("addonid"),
                    "enabled": bool(params.get("enabled", True)),
                }
            )
        elif method == "Settings.SetSettingValue":
            settings.append(
                {"setting": params.get("setting"), "value": params.get("value")}
            )
    return enable_sequence, settings


def _settings_xml_to_map(path):
    """Parse a Kodi <settings> file into an ordered {id: text} dict (or None)."""
    if not os.path.exists(path):
        return None
    root = ET.parse(path).getroot()
    return {(s.get("id") or ""): (s.text or "") for s in root.findall("setting")}


def _sources_to_list(path):
    """Parse sources.xml <files> into an ordered [{name, path}] list (or None)."""
    if not os.path.exists(path):
        return None
    root = ET.parse(path).getroot()
    files = root.find("files")
    if files is None:
        return None
    return [
        {"name": s.findtext("name"), "path": s.findtext("path")}
        for s in files.findall("source")
    ]


def _bootstrap_dir(boot):
    """Path of the bootstrap add-on's OWN directory (self_uninstall's target)."""
    return boot.addons / boot.mod.MY_ID


def _reduce(boot):
    """Reduce the post-run() fake-Kodi state to a stable, diff-friendly dict.

    ``self_uninstalled`` is computed from whether the bootstrap's OWN add-on dir is
    gone AFTER run(): in the ``full`` path the caller pre-creates it so the real
    ``self_uninstall`` deletion is observable (True); in ``bare`` it is never
    created, so ``self_uninstall`` no-ops and this is False. Deleting the
    ``self_uninstall(...)`` call from run() flips ``full`` to False and fails the
    snapshot — that is the regression this field exists to catch.
    """
    state = boot.state
    enable_sequence, settings = _decode_jsonrpc(state["jsonrpc"])
    # Skip the synthetic DialogProgress.close marker (a test artifact, not an
    # executebuiltin run() actually issues).
    builtins = [b for b in state["builtins"] if b != "DialogProgress.close"]
    weather_path = boot.mod._weather_multi_settings_path()
    return {
        "installed": sorted(state["installed"]),
        "extracted": sorted(state["extracted"]),
        "disabled": sorted(state["disabled"]),
        "enable_sequence": enable_sequence,
        "settings": settings,
        "builtins": builtins,
        "summary": list(state["ok"][-1]) if state["ok"] else None,
        "self_uninstalled": not _bootstrap_dir(boot).exists(),
        "files": {
            "sources_xml": _sources_to_list(str(boot.sources_xml)),
            "estuary_settings": _settings_xml_to_map(str(boot.estuary_settings)),
            "weather_multi_settings": _settings_xml_to_map(weather_path),
        },
    }


def _stub_skin_and_video_success(boot, monkeypatch):
    """Make the video + skin pieces install successfully (mirrors the technique in
    test_bootstrap.py's skin/video tests), so run() reaches the terminal
    activate-skin seam. The base repos/apps still install through the real engine.
    """

    def _sel(selected, official_base, disable_ids, dialog, log):
        for aid in selected:
            boot.state["extracted"].add(aid)
            boot.state["installed"].add(aid)
        for aid in disable_ids:
            boot.state["installed"].add(aid)
            boot.state["disabled"].add(aid)
        return len(selected)

    def _extract(url, dialog, pct, log):
        if "pvr.artwork" in url:
            boot.state["extracted"].add(boot.mod.PVR_ARTWORK_ID)
            boot.state["installed"].add(boot.mod.PVR_ARTWORK_ID)
        if "modv2plus" in url:
            boot.state["extracted"].add(boot.mod.MODV2PLUS_ID)
            boot.state["installed"].add(boot.mod.MODV2PLUS_ID)
        return True

    monkeypatch.setattr(boot.mod, "install_selection", _sel)
    monkeypatch.setattr(boot.mod, "extract_zip", _extract)
    monkeypatch.setattr(boot.mod, "install_with_deps", lambda *a, **k: True)
    monkeypatch.setattr(
        boot.mod, "_latest_zip_url", lambda aid: f"http://local/{aid}-9.9.9.zip"
    )


def _assert_or_write(key, snapshot):
    """Compare `snapshot` against the committed expected[key].

    Writing the baseline is GATED on an explicit ``UPDATE_SNAPSHOT=1`` and NOTHING
    else. A missing file or a missing key in NORMAL mode is a hard failure, never a
    silent rebaseline+green-pass — that would let a regression that drops a whole
    snapshot key (or a fresh clone with no baseline) write its own oracle and pass.
    ``UPDATE_SNAPSHOT=1`` is additionally REFUSED when ``CI`` is set, so a CI run
    can never self-baseline (CI is a validator, never a generator).
    """
    refresh = os.environ.get("UPDATE_SNAPSHOT") == "1"
    if refresh and os.environ.get("CI"):
        pytest.fail(
            "refusing UPDATE_SNAPSHOT=1 under CI: CI must validate the committed "
            "snapshot, never regenerate it. Regenerate locally and commit the diff."
        )

    if refresh:
        # The ONLY write path. Merge this key into the (possibly new) file and
        # return without asserting — regeneration is an explicit, local-only act.
        expected_all = {}
        if SNAPSHOT_PATH.exists():
            expected_all = json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))
        expected_all[key] = snapshot
        SNAPSHOT_PATH.write_text(
            json.dumps(expected_all, indent=2, sort_keys=False) + "\n",
            encoding="utf-8",
        )
        return

    if not SNAPSHOT_PATH.exists():
        pytest.fail(
            f"snapshot file missing: {SNAPSHOT_PATH.name}; regenerate with "
            "UPDATE_SNAPSHOT=1"
        )
    expected_all = json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))
    if key not in expected_all:
        pytest.fail(f"snapshot missing key {key!r}; regenerate with UPDATE_SNAPSHOT=1")

    assert snapshot == expected_all[key], (
        f"run() observable behaviour drifted from the committed '{key}' golden "
        "snapshot. If this change is INTENTIONAL, regenerate with "
        "UPDATE_SNAPSHOT=1 and review the diff in modular_setup_snapshot.json."
    )


def _precreate_bootstrap_dir(boot):
    """Lay down the bootstrap add-on's OWN dir (with an addon.xml) so the real
    ``self_uninstall`` has something to delete and the deletion is observable."""
    mine = _bootstrap_dir(boot)
    mine.mkdir(parents=True, exist_ok=True)
    (mine / "addon.xml").write_text(f'<addon id="{boot.mod.MY_ID}"/>')
    return mine


def test_run_bare_matches_golden_snapshot(boot):
    """Pin run() over the fixture's REAL engine (base install for real; video=0,
    skin=FAILED because the fake index can't resolve them). The 'Express must
    reproduce the monolith' oracle for the install engine: a dropped add-on,
    reordered enable, changed settings/summary, or different config-file write
    fails this loudly. The bootstrap's own dir is pre-created so ``self_uninstalled``
    is a real deletion signal (self_uninstall runs even on the skin-FAILED path —
    it is not gated on skin_ok, only activate_skin is)."""
    _precreate_bootstrap_dir(boot)
    boot.mod.run()
    _assert_or_write("bare", _reduce(boot))


def test_run_full_success_matches_golden_snapshot(boot, monkeypatch):
    """Pin run() driven all the way through the terminal seam (video + skin stubbed
    to succeed), so the activate-skin-before-restart cadence is captured:
    lookandfeel.skin is written LAST. The bootstrap's own add-on dir is pre-created
    so the real self_uninstall deletion is captured as ``self_uninstalled: true``.
    The oracle for the orchestrator seam."""
    _stub_skin_and_video_success(boot, monkeypatch)
    _precreate_bootstrap_dir(boot)
    boot.mod.run()
    _assert_or_write("full", _reduce(boot))


def test_full_run_sets_lookandfeel_skin_last(boot, monkeypatch):
    """Guard the load-bearing invariant directly: when the skin installs,
    lookandfeel.skin must be the LAST core setting run() writes (activate-skin
    fires immediately before the restart) and must be set exactly once. Pinned
    separately so a reordering regression names itself."""
    _stub_skin_and_video_success(boot, monkeypatch)
    boot.mod.run()
    _enable_seq, settings = _decode_jsonrpc(boot.state["jsonrpc"])
    assert settings, "run() must emit core settings"
    last = settings[-1]
    assert last["setting"] == "lookandfeel.skin", (
        f"lookandfeel.skin must be the final core setting, got {last['setting']!r}"
    )
    assert last["value"] == boot.mod.SKIN_ID
    skin_calls = [s for s in settings if s["setting"] == "lookandfeel.skin"]
    assert len(skin_calls) == 1, "lookandfeel.skin must be set exactly once"


def test_bare_run_does_not_activate_skin(boot):
    """Characterize the bare path honestly: with the skin unresolved (FAILED),
    run() must NOT write lookandfeel.skin — activate_skin is gated on skin_ok. This
    pins that run() never activates a skin it failed to install."""
    boot.mod.run()
    _enable_seq, settings = _decode_jsonrpc(boot.state["jsonrpc"])
    assert not any(s["setting"] == "lookandfeel.skin" for s in settings), (
        "bare run must not activate a skin that reported FAILED"
    )


# --------------------------------------------------------------------------- #
# RUNTIME wiring of the terminal seam (restart + self-uninstall).
#
# These replace the source-grep order tests in test_bootstrap.py
# (test_restart_comes_after_success_summary,
# test_self_uninstall_runs_after_summary_and_before_restart) which read
# default.py text and will go stale the moment run() is decomposed. We instead
# SPY on the imported ``restart_kodi`` / ``self_uninstall`` symbols that run()
# actually calls, so the assertion is a real runtime observation: deleting the
# call from run() (in any refactor) makes the spy record zero invocations and
# fails the test. Each spy records ``len(boot.state["ok"])`` at call time, which
# is the number of summary Dialog().ok dialogs shown so far — proving the call
# happens AFTER the summary, not by reading source order.
# --------------------------------------------------------------------------- #
def _spy(monkeypatch, boot, name):
    """Replace boot.mod.<name> with a spy that delegates to the real symbol and
    records (call_count, ok_dialogs_shown_at_call_time)."""
    real = getattr(boot.mod, name)
    log = {"calls": 0, "ok_at_call": []}

    def _wrapped(*a, **k):
        log["calls"] += 1
        log["ok_at_call"].append(len(boot.state["ok"]))
        return real(*a, **k)

    monkeypatch.setattr(boot.mod, name, _wrapped)
    return log


def test_full_run_restarts_once_after_summary(boot, monkeypatch):
    """run() must invoke the (desktop) restart EXACTLY ONCE and AFTER the summary.

    Two independent observations pin this:
    * The imported ``restart_kodi`` symbol is called exactly once, and at the
      moment of the call the summary Dialog().ok has already been shown
      (ok_at_call >= 1) — so it is after the summary.
    * The fixture's restart yesno is overridden to ACCEPT, so the REAL
      restart_kodi runs through to ``RestartApp()`` — proving the wiring reaches
      the actual restart builtin exactly once, not just the helper.
    Deleting the restart_kodi(...) call from run() drops the spy count to 0 and
    the RestartApp() builtin disappears — both halves fail.
    """
    _stub_skin_and_video_success(boot, monkeypatch)
    # Accept the end-of-setup restart prompt so the real RestartApp() fires.
    monkeypatch.setattr(
        boot.mod.xbmcgui.Dialog,
        "yesno",
        lambda self, title, msg, **k: (
            bool(boot.state.get("also_video", False))
            if msg.startswith("Include video")
            else True
        ),
    )
    log = _spy(monkeypatch, boot, "restart_kodi")
    boot.mod.run()

    assert log["calls"] == 1, "run() must invoke restart_kodi exactly once"
    assert log["ok_at_call"] == [1], (
        "restart must be invoked AFTER the single summary Dialog().ok "
        f"(ok dialogs shown at call time: {log['ok_at_call']})"
    )
    restarts = [b for b in boot.state["builtins"] if b == "RestartApp()"]
    assert restarts == ["RestartApp()"], (
        "the accepted desktop restart must reach RestartApp() exactly once, "
        f"got {restarts}"
    )


def test_full_run_self_uninstalls_after_summary(boot, monkeypatch):
    """run() must self-uninstall EXACTLY ONCE and AFTER the summary, before the
    restart. Spied on the imported ``self_uninstall`` symbol so a refactor that
    drops the call is caught at runtime (spy count -> 0)."""
    _stub_skin_and_video_success(boot, monkeypatch)
    _precreate_bootstrap_dir(boot)
    log = _spy(monkeypatch, boot, "self_uninstall")
    boot.mod.run()

    assert log["calls"] == 1, "run() must invoke self_uninstall exactly once"
    assert log["ok_at_call"] == [1], (
        "self_uninstall must be invoked AFTER the summary Dialog().ok "
        f"(ok dialogs shown at call time: {log['ok_at_call']})"
    )
    # The real self_uninstall (spy delegates to it) removed the dir.
    assert not _bootstrap_dir(boot).exists(), (
        "self_uninstall must delete the bootstrap's own add-on directory"
    )


# --------------------------------------------------------------------------- #
# GAP 4 — the cancel/abort path is a no-op for every terminal effect.
# --------------------------------------------------------------------------- #
def test_cancel_path_does_nothing_terminal(boot, monkeypatch):
    """When the progress dialog is cancelled mid-install, run() must abort cleanly:
    NO lookandfeel.skin write, NO restart, NO self-uninstall (its dir survives),
    and NO success summary. Pins run()'s early-return contract at runtime."""
    # Stub the success pieces so that IF the cancel guard were broken, the skin
    # path would otherwise fire — making this a real test of the guard, not of an
    # already-failing skin path.
    _stub_skin_and_video_success(boot, monkeypatch)
    mine = _precreate_bootstrap_dir(boot)
    # Cancel the progress dialog as soon as it is polled.
    monkeypatch.setattr(
        boot.mod.xbmcgui.DialogProgress, "iscanceled", lambda self: True
    )
    restart_spy = _spy(monkeypatch, boot, "restart_kodi")
    uninstall_spy = _spy(monkeypatch, boot, "self_uninstall")

    boot.mod.run()  # must not raise

    _enable_seq, settings = _decode_jsonrpc(boot.state["jsonrpc"])
    assert not any(s["setting"] == "lookandfeel.skin" for s in settings), (
        "cancelled run must not activate a skin"
    )
    assert restart_spy["calls"] == 0, "cancelled run must not restart"
    assert "RestartApp()" not in boot.state["builtins"], (
        "cancelled run must not reach RestartApp()"
    )
    assert uninstall_spy["calls"] == 0, "cancelled run must not self-uninstall"
    assert mine.exists(), (
        "cancelled run must leave the bootstrap's own add-on directory intact"
    )
    assert boot.state["ok"] == [], "cancelled run must show no success summary"
