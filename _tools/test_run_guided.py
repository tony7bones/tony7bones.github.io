"""Tests for run_guided — the Guided wizard + the Model A lifecycle (Phase 5d).

The panel's keystone phase. What these tests pin:

MODEL A (the lifecycle — the #1 blocker all three panel lenses flagged):
  * the orchestrator add-on PERSISTS across gates — ``self_uninstall`` is NEVER
    called by a gate (mutation killer: re-adding self-uninstall to any gate
    body fails ``test_*_gate_never_self_uninstalls``);
  * Setup is removed ONLY by the terminal ops — Finish (the offered last step)
    or an explicit, CONFIRMED "Remove Setup";
  * the per-device env SURVIVES every gate (a mid-run delete would starve a
    later gate in the multi-session flow) and is consumed only by the terminal
    ops, BEFORE their restart.

THE WIZARD (resume-by-installed-state):
  * each launch offers the NEXT undone gate — Foundation → IPTV (offered only
    when the env carries a provider playlist source) → Add-ons → Finish —
    probed from the box's actual state (tony7bones.setup.probes), so a crash /
    declined restart / reverted skin self-heals by re-offering;
  * gates restart ONLY on ``ok`` (never restart into a failed gate; the wizard
    menu returns so the user can retry or exit);
  * declining everything exits cleanly — nothing installed, nothing removed.

ROUTING (the shipped ``run()`` — owner-vetoable mechanism, documented in the
phase log): ``SETUP_MODE=guided`` in the per-device env routes to the wizard;
an env WITHOUT the key (or any other value) runs Express byte-identically to
the pre-5d one-tap (the characterization snapshot + EXPECTED_NET_INSTALLED
pass UNCHANGED — proven in test_modular_setup.py, not re-proven here). Since
Phase N1 a launch with NO env anywhere ALSO routes to the wizard (the
no-computer path) — that matrix, the ordered env sources, and the no-env
menu's "Install everything with defaults" entry are pinned in
test_no_computer_routing.py.

The wizard dialogs are driven through the shared fake-Kodi ``boot`` fixture's
scripted queues: ``state["select_queue"]`` (menu picks) and
``state["yesno_queue"]`` (the Remove-Setup confirm).
"""

from __future__ import annotations

import json


def _stub_skin_success(boot, monkeypatch):
    """Make the SKIN closure install succeed (the fixture's bare index cannot
    resolve it) by stubbing ONLY the foundation module's install primitives —
    mirrors the snapshot suite's technique, but leaves the addons module REAL
    so ``install_repos`` (the gate's plumbing step) still drives the real
    engine and the repos genuinely land in the fake state."""

    def _sel(selected, official_base, disable_ids, dialog, log):
        # The real install_selection enables the source repos while resolving a
        # closure (repos.enable_source_repos) — that is what lands
        # repository.diggz.zip in `installed` (enabled by the zip's INNER
        # addon.xml id). Mirror it, exactly like test_run_foundation's stub.
        from tony7bones import enable_source_repos

        enable_source_repos(log)
        for aid in selected:
            boot.state["extracted"].add(aid)
            boot.state["installed"].add(aid)
        return len(selected)

    def _extract(url, dialog, pct, log):
        if "pvr.artwork" in url:
            boot.state["extracted"].add(boot.mod.PVR_ARTWORK_ID)
            boot.state["installed"].add(boot.mod.PVR_ARTWORK_ID)
        if "modv2plus" in url:
            boot.state["extracted"].add(boot.mod.MODV2PLUS_ID)
            boot.state["installed"].add(boot.mod.MODV2PLUS_ID)
        return True

    foundation = boot.mod._foundation
    monkeypatch.setattr(foundation, "install_selection", _sel, raising=False)
    monkeypatch.setattr(foundation, "extract_zip", _extract, raising=False)
    monkeypatch.setattr(
        foundation, "install_with_deps", lambda *a, **k: True, raising=False
    )
    monkeypatch.setattr(
        foundation,
        "_latest_zip_url",
        lambda aid: f"http://local/{aid}-9.9.9.zip",
        raising=False,
    )


def _settings_set(boot):
    out = {}
    for s in boot.state["jsonrpc"]:
        try:
            d = json.loads(s)
        except ValueError:
            continue
        if d.get("method") == "Settings.SetSettingValue":
            out[d["params"]["setting"]] = d["params"]["value"]
    return out


def _no_restart(boot, monkeypatch, events=None):
    monkeypatch.setattr(
        boot.mod,
        "restart_kodi",
        lambda *a, **k: events.append("restart") if events is not None else None,
    )


def _spy_self_uninstall(boot, monkeypatch, events):
    monkeypatch.setattr(
        boot.mod, "self_uninstall", lambda *a, **k: events.append("self_uninstall")
    )


def _simulate_foundation_done(boot, monkeypatch):
    """The post-Foundation-restart world: skin installed AND active."""
    boot.state["installed"].add(boot.mod.SKIN_ID)
    monkeypatch.setattr(boot.mod.xbmc, "getSkinDir", lambda: boot.mod.SKIN_ID)


def _simulate_addons_done(boot):
    for aid in list(boot.mod.ADDONS) + list(boot.mod.VIDEO_APPS):
        boot.state["installed"].add(aid)


def _stage_env_file(boot, monkeypatch, tmp_path, content="SETUP_MODE=guided\n"):
    """Point BOX_ENV_PATH at a real tmp file (the fake of the provisioner's
    pushed tony7bones.env) so env survive/delete assertions are REAL."""
    env_file = tmp_path / "tony7bones.env"
    env_file.write_text(content)
    monkeypatch.setattr(boot.mod, "BOX_ENV_PATH", str(env_file))
    return env_file


_IPTV_ENV = {"SETUP_MODE": "guided", "IPTV_M3U": "http://provider.example/x.m3u"}


# --------------------------------------------------------------------------- #
# The resume probe: the wizard offers the NEXT undone gate.
# --------------------------------------------------------------------------- #
def test_wizard_offers_foundation_on_fresh_box(boot, monkeypatch):
    """Fresh box → the first offer is the Foundation gate; declining (queue
    empty → -1/back) exits cleanly with nothing changed."""
    _no_restart(boot, monkeypatch)
    outcome = boot.mod.run_guided({})
    assert outcome == "exit"
    assert len(boot.state["select"]) == 1
    title, options = boot.state["select"][0]
    assert title.startswith("Tony.7.Bones Setup")
    assert options[0].startswith("Install Foundation")
    assert "Remove Setup" in options
    assert boot.state["installed"] == set(), "a declined offer must install nothing"


def test_wizard_offers_iptv_after_foundation_when_env_has_iptv(boot, monkeypatch):
    _no_restart(boot, monkeypatch)
    _simulate_foundation_done(boot, monkeypatch)
    boot.mod.run_guided(dict(_IPTV_ENV))
    _, options = boot.state["select"][0]
    assert options[0].startswith("Install IPTV")


def test_wizard_skips_iptv_gate_without_iptv_env(boot, monkeypatch):
    """The IPTV gate is ENV-GATED: with no provider playlist source in the env
    the wizard goes Foundation → Add-ons directly (never offers IPTV)."""
    _no_restart(boot, monkeypatch)
    _simulate_foundation_done(boot, monkeypatch)
    boot.mod.run_guided({"SETUP_MODE": "guided"})
    _, options = boot.state["select"][0]
    assert options[0].startswith("Install Add-ons")


def test_wizard_offers_addons_after_foundation_and_iptv(boot, monkeypatch):
    _no_restart(boot, monkeypatch)
    _simulate_foundation_done(boot, monkeypatch)
    monkeypatch.setattr(boot.mod._probes, "iptv_done", lambda env: True)
    boot.mod.run_guided(dict(_IPTV_ENV))
    _, options = boot.state["select"][0]
    assert options[0].startswith("Install Add-ons")


def test_wizard_offers_finish_when_all_gates_done(boot, monkeypatch):
    _no_restart(boot, monkeypatch)
    _simulate_foundation_done(boot, monkeypatch)
    _simulate_addons_done(boot)
    monkeypatch.setattr(boot.mod._probes, "iptv_done", lambda env: True)
    boot.mod.run_guided(dict(_IPTV_ENV))
    _, options = boot.state["select"][0]
    assert options[0].startswith("Finish")


def test_wizard_reoffers_foundation_after_skin_revert(boot, monkeypatch):
    """The self-heal: skin installed but silently reverted (the keep-skin
    race) → Foundation reads NOT done and is re-offered (idempotent re-run
    re-activates)."""
    _no_restart(boot, monkeypatch)
    boot.state["installed"].add(boot.mod.SKIN_ID)  # installed, but NOT active
    _simulate_addons_done(boot)
    boot.mod.run_guided({"SETUP_MODE": "guided"})
    _, options = boot.state["select"][0]
    assert options[0].startswith("Install Foundation")


def test_wizard_reoffers_incomplete_iptv_after_crash(boot, monkeypatch):
    """Mid-flow crash resume: backend installed but the enforce never wrote an
    instance file → the IPTV gate reads NOT done and is re-offered."""
    _no_restart(boot, monkeypatch)
    _simulate_foundation_done(boot, monkeypatch)
    boot.state["installed"].add("pvr.iptvsimple")  # half-state: no instance file
    boot.mod.run_guided(dict(_IPTV_ENV))
    _, options = boot.state["select"][0]
    assert options[0].startswith("Install IPTV")


# --------------------------------------------------------------------------- #
# The Foundation gate: Model A (no self-uninstall) + the terminal op.
# --------------------------------------------------------------------------- #
def test_foundation_gate_installs_and_keeps_setup(boot, monkeypatch, tmp_path):
    """Running the Foundation gate installs the layer (repos + skin closure),
    then activate-skin-THEN-restart as one terminal op — and NEVER
    self-uninstalls (Model A; mutation killer: add self_uninstall to the gate
    and this fails). The env file survives the gate (mutation killer: a gate
    deleting the env starves the next gate)."""
    events = []
    _stub_skin_success(boot, monkeypatch)
    env_file = _stage_env_file(boot, monkeypatch, tmp_path)
    _spy_self_uninstall(boot, monkeypatch, events)
    _no_restart(boot, monkeypatch, events)
    monkeypatch.setattr(
        boot.mod, "activate_skin", lambda *a, **k: events.append(("activate", a[0]))
    )
    boot.state["select_queue"] = [0]

    outcome = boot.mod.run_guided({"SETUP_MODE": "guided"})

    assert outcome == "gate:foundation"
    assert boot.mod.SKIN_ID in boot.state["installed"], "the skin closure must land"
    for _zip, rid in boot.mod.REPO_ZIPS:
        # repository.diggz lands as "repository.diggz.zip" — the pre-existing
        # double-extension quirk faithfully pinned since Phase 0 (the fake
        # urlopen derives the inner id from the zip filename). Tolerate it.
        assert rid in boot.state["installed"] or (
            f"{rid}.zip" in boot.state["installed"]
        ), f"repo {rid} must land (plumbing)"
    assert events == [("activate", boot.mod.SKIN_ID), "restart"], (
        "the gate's terminal seam is activate-skin THEN restart, exactly once, "
        f"with NO self_uninstall anywhere; got {events}"
    )
    assert env_file.exists(), "a gate must NEVER consume the per-device env"
    assert boot.state["ok"], "the gate summary must be shown"
    _title, msg = boot.state["ok"][-1]
    assert "Estuary MOD V2: installed" in msg
    assert "reopen Setup to continue" in msg


def test_failed_foundation_gate_no_restart_no_activate(boot, monkeypatch):
    """A FAILED gate never restarts and never activates the skin (the
    restart-only-on-ok rule: never restart into a failed gate); the wizard
    menu returns so the user can retry or exit."""
    events = []
    _spy_self_uninstall(boot, monkeypatch, events)
    _no_restart(boot, monkeypatch, events)
    monkeypatch.setattr(
        boot.mod, "activate_skin", lambda *a, **k: events.append("activate")
    )
    from tony7bones.setup.result import LayerResult

    monkeypatch.setattr(
        boot.mod,
        "apply_foundation",
        lambda env, **k: LayerResult(layer="foundation", ok=False),
    )
    boot.state["select_queue"] = [0]  # run the gate; menu returns; queue empty → exit

    outcome = boot.mod.run_guided({"SETUP_MODE": "guided"})

    assert outcome == "exit"
    assert events == [], "no restart / no activate / no uninstall on a failed gate"
    assert len(boot.state["select"]) == 2, "the wizard menu must return after a fail"
    _title, msg = boot.state["ok"][-1]
    assert "FAILED" in msg


# --------------------------------------------------------------------------- #
# The IPTV gate: same layer body, no skin touch, no self-uninstall.
# --------------------------------------------------------------------------- #
def test_iptv_gate_installs_backend_and_keeps_setup(boot, monkeypatch, tmp_path):
    events = []
    env_file = _stage_env_file(boot, monkeypatch, tmp_path)
    _simulate_foundation_done(boot, monkeypatch)
    _spy_self_uninstall(boot, monkeypatch, events)
    _no_restart(boot, monkeypatch, events)
    activated = []
    monkeypatch.setattr(boot.mod, "activate_skin", lambda *a, **k: activated.append(a))
    boot.state["select_queue"] = [0]

    outcome = boot.mod.run_guided(dict(_IPTV_ENV))

    assert outcome == "gate:iptv"
    assert "pvr.iptvsimple" in boot.state["installed"], "the layer owns its backend"
    assert events == ["restart"], (
        f"ONE restart, NO self_uninstall (Model A); got {events}"
    )
    assert activated == [] and "lookandfeel.skin" not in _settings_set(boot), (
        "the IPTV gate must never touch the skin"
    )
    assert env_file.exists(), "a gate must NEVER consume the per-device env"
    _title, msg = boot.state["ok"][-1]
    assert "pvr.iptvsimple: installed" in msg
    assert "Instance settings: written" in msg


def test_failed_iptv_gate_no_restart_menu_returns(boot, monkeypatch):
    """Backend install failure (the layer's fail-loud path): honest FAILED
    summary, NO restart (the box is unchanged — nothing to finalise), the menu
    returns for retry/exit. Setup + env stay (the retry needs both)."""
    events = []
    _simulate_foundation_done(boot, monkeypatch)
    _spy_self_uninstall(boot, monkeypatch, events)
    _no_restart(boot, monkeypatch, events)
    monkeypatch.setattr(boot.mod._iptv, "install_with_deps", lambda *a, **k: 0)
    boot.state["select_queue"] = [0]

    outcome = boot.mod.run_guided(dict(_IPTV_ENV))

    assert outcome == "exit"
    assert events == [], "no restart / no uninstall on a failed gate"
    assert len(boot.state["select"]) == 2, "the wizard menu must return after a fail"
    _title, msg = boot.state["ok"][-1]
    assert "pvr.iptvsimple: FAILED" in msg


# --------------------------------------------------------------------------- #
# The Add-ons gate: same layer body, cancel contract, no self-uninstall.
# --------------------------------------------------------------------------- #
def test_addons_gate_installs_and_keeps_setup(boot, monkeypatch, tmp_path):
    events = []
    env_file = _stage_env_file(boot, monkeypatch, tmp_path)
    _simulate_foundation_done(boot, monkeypatch)
    _spy_self_uninstall(boot, monkeypatch, events)
    _no_restart(boot, monkeypatch, events)
    boot.state["select_queue"] = [0]

    outcome = boot.mod.run_guided({"SETUP_MODE": "guided"})

    assert outcome == "gate:addons"
    for aid in boot.mod.ADDONS:
        assert aid in boot.state["installed"], f"base app {aid} must land"
    assert events == ["restart"], (
        f"ONE restart, NO self_uninstall (Model A); got {events}"
    )
    assert env_file.exists(), "a gate must NEVER consume the per-device env"
    _title, msg = boot.state["ok"][-1]
    assert "Add-ons (curated content):" in msg
    assert f"Apps: {len(boot.mod.ADDONS)}/{len(boot.mod.ADDONS)}" in msg


def test_addons_gate_cancel_aborts_clean(boot, monkeypatch, tmp_path):
    """A user CANCEL mid-install (the layer's only not-ok path) aborts with NO
    summary and NO restart — the monolith's early-return contract; the wizard
    menu returns and the env survives for the re-run."""
    events = []
    env_file = _stage_env_file(boot, monkeypatch, tmp_path)
    _simulate_foundation_done(boot, monkeypatch)
    _spy_self_uninstall(boot, monkeypatch, events)
    _no_restart(boot, monkeypatch, events)
    monkeypatch.setattr(boot.mod.xbmcgui.DialogProgress, "iscanceled", lambda s: True)
    boot.state["select_queue"] = [0]

    outcome = boot.mod.run_guided({"SETUP_MODE": "guided"})

    assert outcome == "exit"
    assert events == [], "cancel = clean abort: no restart, no uninstall"
    assert boot.state["ok"] == [], "cancel shows NO summary (early-return contract)"
    assert len(boot.state["select"]) == 2, "the wizard menu must return after cancel"
    assert env_file.exists(), "the env must survive a cancelled gate"


# --------------------------------------------------------------------------- #
# Terminal Finish: env consumed → self-uninstall → ONE restart (in that order).
# --------------------------------------------------------------------------- #
def test_finish_consumes_env_then_self_uninstalls_then_restarts(
    boot, monkeypatch, tmp_path
):
    """The ONLY self-uninstall in the Guided lifecycle. Order is load-bearing:
    env delete FIRST (the delete must not be lost to the restart), then
    self_uninstall, then exactly ONE restart. MUTATION: dropping any step or
    reordering fails here."""
    events = []
    env_file = _stage_env_file(boot, monkeypatch, tmp_path)
    _simulate_foundation_done(boot, monkeypatch)
    _simulate_addons_done(boot)
    monkeypatch.setattr(boot.mod._probes, "iptv_done", lambda env: True)
    real_remove = boot.mod.os.remove

    def _remove(path):
        if path == str(env_file):
            events.append("env_delete")
        return real_remove(path)

    monkeypatch.setattr(boot.mod.os, "remove", _remove)
    _spy_self_uninstall(boot, monkeypatch, events)
    _no_restart(boot, monkeypatch, events)
    boot.state["select_queue"] = [0]

    outcome = boot.mod.run_guided(dict(_IPTV_ENV))

    assert outcome == "finished"
    assert events == ["env_delete", "self_uninstall", "restart"], (
        f"Finish order must be env→uninstall→restart, got {events}"
    )
    assert not env_file.exists(), "Finish must consume the per-device env"


def test_finish_with_missing_env_is_guarded(boot, monkeypatch, tmp_path):
    """Finish on a box whose env is already gone (crash / manual delete): the
    guarded delete no-ops and the terminal op still completes."""
    events = []
    monkeypatch.setattr(boot.mod, "BOX_ENV_PATH", str(tmp_path / "absent.env"))
    _simulate_foundation_done(boot, monkeypatch)
    _simulate_addons_done(boot)
    _spy_self_uninstall(boot, monkeypatch, events)
    _no_restart(boot, monkeypatch, events)
    boot.state["select_queue"] = [0]

    outcome = boot.mod.run_guided({"SETUP_MODE": "guided"})

    assert outcome == "finished"
    assert events == ["self_uninstall", "restart"]


# --------------------------------------------------------------------------- #
# Remove Setup: explicit, confirmed, terminal.
# --------------------------------------------------------------------------- #
def test_remove_setup_confirmed_fires_terminal_op(boot, monkeypatch, tmp_path):
    events = []
    env_file = _stage_env_file(boot, monkeypatch, tmp_path)
    _spy_self_uninstall(boot, monkeypatch, events)
    _no_restart(boot, monkeypatch, events)
    boot.state["select_queue"] = [1]
    boot.state["yesno_queue"] = [True]

    outcome = boot.mod.run_guided({"SETUP_MODE": "guided"})

    assert outcome == "removed"
    assert events == ["self_uninstall", "restart"]
    assert not env_file.exists(), (
        "Remove Setup must consume the env (no lingering secrets)"
    )
    assert any("Remove Setup" in msg for _t, msg in boot.state["yesno"]), (
        "Remove Setup must be CONFIRMED before firing"
    )


def test_remove_setup_declined_returns_to_menu(boot, monkeypatch, tmp_path):
    events = []
    env_file = _stage_env_file(boot, monkeypatch, tmp_path)
    _spy_self_uninstall(boot, monkeypatch, events)
    _no_restart(boot, monkeypatch, events)
    boot.state["select_queue"] = [1, 2]  # Remove Setup → declined → Exit
    boot.state["yesno_queue"] = [False]

    outcome = boot.mod.run_guided({"SETUP_MODE": "guided"})

    assert outcome == "exit"
    assert events == [], "a declined Remove must change nothing"
    assert env_file.exists()
    assert len(boot.state["select"]) == 2, "the menu must return after the decline"


def test_exit_keeps_setup_and_env(boot, monkeypatch, tmp_path):
    """The decline-everything path: explicit Exit keeps the add-on + the env —
    the home tile remains the 'continue setup' affordance (Model A)."""
    events = []
    env_file = _stage_env_file(boot, monkeypatch, tmp_path)
    _spy_self_uninstall(boot, monkeypatch, events)
    _no_restart(boot, monkeypatch, events)
    boot.state["select_queue"] = [2]

    outcome = boot.mod.run_guided({"SETUP_MODE": "guided"})

    assert outcome == "exit"
    assert events == []
    assert env_file.exists()
    assert boot.state["installed"] == set()


def test_run_guided_none_env_normalizes(boot, monkeypatch):
    _no_restart(boot, monkeypatch)
    assert boot.mod.run_guided(None) == "exit"


# --------------------------------------------------------------------------- #
# The shipped run(): SETUP_MODE routing (Express stays the untouched default).
# --------------------------------------------------------------------------- #
def test_run_routes_to_guided_on_setup_mode(boot, monkeypatch, tmp_path):
    """SETUP_MODE=guided in the per-device env routes run() to the wizard —
    and run() does NOT delete the env (the wizard owns the terminal delete)."""
    env_file = _stage_env_file(
        boot, monkeypatch, tmp_path, "SETUP_MODE=guided\nDEVICE=test\n"
    )
    seen = {}
    monkeypatch.setattr(
        boot.mod, "run_guided", lambda env: seen.setdefault("guided", env)
    )
    monkeypatch.setattr(
        boot.mod,
        "run_express",
        lambda env: (_ for _ in ()).throw(AssertionError("Express must not run")),
    )
    boot.mod.run()
    assert seen["guided"]["SETUP_MODE"] == "guided"
    assert env_file.exists(), "run() must not delete the env on the Guided route"


def test_run_routing_is_case_insensitive(boot, monkeypatch, tmp_path):
    _stage_env_file(boot, monkeypatch, tmp_path, "SETUP_MODE=Guided\n")
    seen = []
    monkeypatch.setattr(boot.mod, "run_guided", lambda env: seen.append(env))
    boot.mod.run()
    assert len(seen) == 1


def test_run_defaults_to_express_without_setup_mode(boot, monkeypatch, tmp_path):
    """No SETUP_MODE key → the exact pre-5d Express path (the one-tap Fire TV
    default; byte-identical behaviour is pinned by the UNCHANGED snapshot in
    test_modular_setup.py — here we pin the routing decision itself)."""
    _stage_env_file(boot, monkeypatch, tmp_path, "DEVICE=test\n")
    routed = []
    from tony7bones.setup.result import LayerResult

    monkeypatch.setattr(
        boot.mod,
        "run_express",
        lambda env: (
            routed.append(env),
            (LayerResult(layer="addons", ok=True), None, None),
        )[1],
    )
    monkeypatch.setattr(
        boot.mod,
        "run_guided",
        lambda env: (_ for _ in ()).throw(AssertionError("Guided must not run")),
    )
    boot.mod.run()
    assert len(routed) == 1


def test_run_express_route_on_unknown_mode_value(boot, monkeypatch, tmp_path):
    """Any value other than 'guided' (typo'd or future) falls back to Express —
    the safe default that always completes the box."""
    _stage_env_file(boot, monkeypatch, tmp_path, "SETUP_MODE=wizard\n")
    routed = []
    from tony7bones.setup.result import LayerResult

    monkeypatch.setattr(
        boot.mod,
        "run_express",
        lambda env: (
            routed.append(env),
            (LayerResult(layer="addons", ok=True), None, None),
        )[1],
    )
    boot.mod.run()
    assert len(routed) == 1
