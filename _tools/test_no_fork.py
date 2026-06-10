"""The Phase 5d invariants: NO-FORK, restart cadence, and end-state equivalence.

The plan's keystone test file (`docs/plans/modular-setup.md` → Test strategy):

* **No-fork** — Guided and Express drive the IDENTICAL layer functions with the
  IDENTICAL env argument. There is exactly ONE ``apply_foundation`` /
  ``apply_iptv`` / ``apply_addons`` body; the two cadences may only differ in
  WHEN they call them and when they restart. (The known, documented
  non-difference: the Guided Foundation gate calls ``install_repos`` directly
  — via ``_foundation_core``, the live-proven run_foundation seam — because in
  gate order Foundation runs FIRST and the skin closure needs the repos;
  Express gets the very same ``addons.install_repos`` loop INSIDE
  ``apply_addons → _install_base``. Same function object, different call site —
  plumbing, not a fork; the end-state tests prove the net result identical.)
* **Restart cadence** — Express restarts exactly ONCE at the end; Guided
  restarts once per gate (3 across a full walk) + once at terminal Finish (the
  self-uninstall finaliser every shipped runner uses). In BOTH cadences the
  skin activation is IMMEDIATELY followed by its restart (the
  activate-then-restart terminal op — the keep-skin-revert invariant).
* **Model A at the walk level** — ``self_uninstall`` fires ZERO times across
  the three Guided gates and exactly once at Finish (mutation killer:
  re-adding self-uninstall to any gate body fails here too).
* **End-state equivalence** — "Express end-state == cumulative Guided
  end-state", proven twice:
    1. REAL ENGINE (bare fixture): the cumulative Guided gates' net installed
       set equals ``EXPECTED_NET_INSTALLED`` — the same frozen constant the
       Express ``run()`` is pinned against (test_modular_setup.py), so the two
       cadences are equal by transitivity against a constant that cannot be
       silently rebaselined.
    2. FULL-SUCCESS (skin/video stubbed exactly like the golden snapshot's
       ``full`` path): a complete Express run and a complete Guided walk are
       reduced to {installed, disabled, core settings, skin builtins, every
       profile file} and compared for EQUALITY in one test (a fresh fake world
       per cadence via a state+profile reset).
"""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import sys
from pathlib import Path

# Shared assets from the snapshot suite: the frozen net-set constant and the
# full-success stub technique (loaded by path so this file never depends on
# pytest's rootdir-relative import behaviour).
_TMS_PATH = Path(__file__).parent / "test_modular_setup.py"
_spec = importlib.util.spec_from_file_location("_tms_for_no_fork", _TMS_PATH)
_tms = importlib.util.module_from_spec(_spec)
sys.modules["_tms_for_no_fork"] = _tms
_spec.loader.exec_module(_tms)
EXPECTED_NET_INSTALLED = _tms.EXPECTED_NET_INSTALLED
_stub_skin_and_video_success = _tms._stub_skin_and_video_success

_ENV = {
    "SETUP_MODE": "guided",
    "IPTV_M3U": "http://provider.example/playlist.m3u",
    "RSS_FEEDS": "http://feeds.example/a.xml",
}


def _settings_map(boot):
    out = {}
    for s in boot.state["jsonrpc"]:
        try:
            d = json.loads(s)
        except ValueError:
            continue
        if d.get("method") == "Settings.SetSettingValue":
            out[d["params"]["setting"]] = d["params"]["value"]
    return out


def _script_probes(boot, monkeypatch):
    """Scripted done-flags standing in for the between-gate restarts (a unit
    test cannot reboot the fake Kodi; probe correctness is proven in
    test_setup_probes.py). Returns the flags dict the test flips per gate."""
    flags = {"foundation": False, "iptv": False, "addons": False}
    monkeypatch.setattr(
        boot.mod._probes, "foundation_done", lambda: flags["foundation"]
    )
    monkeypatch.setattr(boot.mod._probes, "iptv_done", lambda env: flags["iptv"])
    monkeypatch.setattr(boot.mod._probes, "addons_done", lambda: flags["addons"])
    return flags


# --------------------------------------------------------------------------- #
# 1. The no-fork + cadence invariant (module spies).
# --------------------------------------------------------------------------- #
def test_no_fork_identical_layers_and_restart_cadence(boot, monkeypatch):
    """Guided and Express drive the SAME three apply_* functions, each EXACTLY
    once, with the SAME env object — and the cadences are: Express ONE restart
    (after self-uninstall, activation immediately before it), Guided one
    restart PER GATE (activation immediately before the Foundation gate's) and
    ZERO self-uninstalls until terminal Finish.

    MUTATIONS KILLED: forking a layer call (a gate calling anything but its
    apply_*), dropping a per-gate restart, adding a second Express restart,
    re-adding self-uninstall to a Guided gate, sliding any step between
    activate_skin and its restart."""
    from tony7bones.setup.result import LayerResult

    calls = []

    def _mk(layer):
        def _spy(env, *, dialog=None, log=None):
            calls.append((layer, id(env)))
            return LayerResult(
                layer=layer,
                ok=True,
                installed={"pvr.iptvsimple": "installed"} if layer == "iptv" else {},
                needs_skin_activation=(layer == "foundation"),
                needs_restart=True,
            )

        return _spy

    for layer in ("foundation", "iptv", "addons"):
        monkeypatch.setattr(boot.mod, f"apply_{layer}", _mk(layer))
    # Plumbing stub: the Guided Foundation gate's install_repos (the SAME
    # addons.install_repos Express runs inside apply_addons — see the module
    # docstring; stubbed here so the spy test observes ONLY the layer calls).
    monkeypatch.setattr(boot.mod, "install_repos", lambda *a, **k: (12, 1, 13, False))

    events = []
    monkeypatch.setattr(
        boot.mod, "restart_kodi", lambda *a, **k: events.append("restart")
    )
    monkeypatch.setattr(
        boot.mod, "activate_skin", lambda *a, **k: events.append("activate")
    )
    monkeypatch.setattr(
        boot.mod, "self_uninstall", lambda *a, **k: events.append("uninstall")
    )

    env = dict(_ENV)

    # --- Express: one shot ---
    boot.mod.run_express(env)
    express_calls, express_events = list(calls), list(events)
    calls.clear()
    events.clear()

    # --- Guided: the full walk, one gate per launch (probes scripted) ---
    flags = _script_probes(boot, monkeypatch)
    for gate in ("foundation", "iptv", "addons"):
        boot.state["select_queue"] = [0]
        assert boot.mod.run_guided(env) == f"gate:{gate}"
        flags[gate] = True  # the restart seam: the gate's work is now on-box
    guided_calls, guided_events = list(calls), list(events)
    calls.clear()
    events.clear()

    # --- Guided: terminal Finish ---
    boot.state["select_queue"] = [0]
    assert boot.mod.run_guided(env) == "finished"
    finish_events = list(events)

    # THE NO-FORK INVARIANT: identical layer set, each exactly once, same env.
    assert sorted(layer for layer, _ in express_calls) == [
        "addons",
        "foundation",
        "iptv",
    ]
    assert sorted(layer for layer, _ in guided_calls) == [
        "addons",
        "foundation",
        "iptv",
    ]
    assert {e for _, e in express_calls} == {e for _, e in guided_calls} == {id(env)}, (
        "both cadences must hand the layers the SAME env object"
    )

    # CADENCE: Express = self-uninstall, then activate immediately before the
    # single restart (the monolith's proven terminal seam).
    assert express_events == ["uninstall", "activate", "restart"], (
        f"Express terminal seam drifted: {express_events}"
    )
    # CADENCE: Guided = activate→restart at the Foundation gate, one restart
    # per following gate, ZERO uninstalls during gates (Model A).
    assert guided_events == ["activate", "restart", "restart", "restart"], (
        f"Guided per-gate cadence drifted: {guided_events}"
    )
    # Terminal Finish is the ONLY Guided self-uninstall, with its finaliser.
    assert finish_events == ["uninstall", "restart"], (
        f"Finish terminal op drifted: {finish_events}"
    )


# --------------------------------------------------------------------------- #
# 2. REAL-ENGINE end-state equivalence: cumulative Guided == EXPECTED net set.
# --------------------------------------------------------------------------- #
def test_guided_cumulative_net_set_equals_expected(boot, monkeypatch):
    """Driving the three Guided GATE BODIES over the bare REAL engine installs
    exactly ``EXPECTED_NET_INSTALLED`` — the same frozen constant a full
    Express ``run()`` is pinned against (test_modular_setup.py), so
    "Express end-state == cumulative Guided end-state" holds at the real-engine
    level by equality with a constant that cannot be silently rebaselined.

    (Gate BODIES, not the wizard menu: on the bare index the skin closure
    cannot resolve, so the real foundation probe would honestly re-offer the
    gate; the menu/probe logic is proven in test_run_guided.py — this test
    proves what the gates cumulatively DO to the box.)"""
    monkeypatch.setattr(boot.mod, "restart_kodi", lambda *a, **k: None)
    boot.mod._guided_gate_foundation({})
    boot.mod._guided_gate_iptv({})
    boot.mod._guided_gate_addons({})

    assert set(boot.state["installed"]) == set(EXPECTED_NET_INSTALLED), (
        "cumulative Guided net installed set drifted from the EXPECTED set "
        "(the Express-proven constant). MISSING="
        f"{sorted(EXPECTED_NET_INSTALLED - boot.state['installed'])} EXTRA="
        f"{sorted(boot.state['installed'] - EXPECTED_NET_INSTALLED)}"
    )
    # Same bare-run posture as Express: skin unresolved → never activated.
    assert "lookandfeel.skin" not in _settings_map(boot)
    # The shared core settings the layers own land identically.
    settings = _settings_map(boot)
    assert settings.get("weather.addon") == boot.mod.WEATHER_ADDON
    assert settings.get("lookandfeel.enablerssfeeds") is True


# --------------------------------------------------------------------------- #
# 3. FULL-SUCCESS end-state equivalence: Express world == Guided world.
# --------------------------------------------------------------------------- #
def _reduce_world(boot):
    """The comparable end-state of the fake box: add-on states, core settings,
    skin builtins, and EVERY profile file's bytes (sources.xml, the Estuary
    trim settings, weather settings, RssFeeds.xml, IPTV instance-settings…)."""
    profile = Path(boot.mod.xbmcvfs.translatePath("special://profile/"))
    files = {}
    for p in sorted(profile.rglob("*")):
        if p.is_file():
            files[str(p.relative_to(profile))] = p.read_text()
    return {
        "installed": sorted(boot.state["installed"]),
        "disabled": sorted(boot.state["disabled"]),
        "settings": _settings_map(boot),
        "skin_builtins": sorted(
            b for b in boot.state["builtins"] if b.startswith("Skin.")
        ),
        "files": files,
    }


def _reset_world(boot):
    """A fresh fake box (state + profile) within one test, so the two cadences
    each start from zero and the reductions are directly comparable."""
    for key in ("installed", "extracted", "disabled"):
        boot.state[key] = set()
    for key in ("builtins", "jsonrpc", "ok", "yesno", "select", "mkdirs"):
        boot.state[key] = []
    profile = Path(boot.mod.xbmcvfs.translatePath("special://profile/"))
    shutil.rmtree(profile, ignore_errors=True)
    os.makedirs(profile, exist_ok=True)


def test_express_end_state_equals_cumulative_guided_end_state(boot, monkeypatch):
    """THE EQUIVALENCE CHECK, head to head: a full-success Express run and a
    full-success cumulative Guided walk leave the box in the IDENTICAL reduced
    end-state — installed/disabled sets, every core setting (incl.
    ``lookandfeel.skin``), the Skin.Set* builtins, and every profile file
    byte-for-byte (weather, home-trim, sources, RSS feeds, IPTV instance
    settings). The skin/video pieces use the SAME stub technique as the golden
    snapshot's ``full`` path, applied identically to both cadences."""
    _stub_skin_and_video_success(boot, monkeypatch)
    monkeypatch.setattr(boot.mod, "restart_kodi", lambda *a, **k: None)

    env = dict(_ENV)

    # --- cadence A: Express, one shot ---
    boot.mod.run_express(env)
    express_world = _reduce_world(boot)

    # --- fresh box, cadence B: the Guided walk + Finish ---
    _reset_world(boot)
    flags = _script_probes(boot, monkeypatch)
    for gate in ("foundation", "iptv", "addons"):
        boot.state["select_queue"] = [0]
        assert boot.mod.run_guided(env) == f"gate:{gate}"
        flags[gate] = True
    boot.state["select_queue"] = [0]
    assert boot.mod.run_guided(env) == "finished"
    guided_world = _reduce_world(boot)

    assert express_world == guided_world, (
        "Express and cumulative Guided must leave the IDENTICAL box. Diff keys: "
        f"{[k for k in express_world if express_world[k] != guided_world.get(k)]}"
    )
    # Sanity that the comparison had teeth: the skin was activated and the
    # env-driven artifacts exist in BOTH worlds.
    assert express_world["settings"].get("lookandfeel.skin") == boot.mod.SKIN_ID
    assert any("instance-settings-1.xml" in f for f in express_world["files"])
    assert any("RssFeeds.xml" in f for f in express_world["files"])
