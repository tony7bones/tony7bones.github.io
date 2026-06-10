"""Phase N1 (no-computer track): run() routing + ordered env sources + the
no-env wizard's "Install everything with defaults" entry.

What this file pins (docs/plans/no-computer-setup.md, D1/D5/N1):

ROUTING MATRIX (the D1 table — each row a test, the no-env row the N1 change):

    env ABSENT everywhere (read -> {})        -> run_guided({})   (NEW)
    env present, no SETUP_MODE / other value  -> run_express(env) (unchanged)
    env present, SETUP_MODE=guided            -> run_guided(env)  (unchanged)

  MUTATION KILLER: the no-env test stubs run_express to RAISE, so reverting
  the routing (no-env -> Express, the pre-N1 behaviour) fails loudly here.

ORDERED ENV SOURCES: the provisioner's pushed ``BOX_ENV_PATH`` WINS when
present (provisioned-path byte-compatibility); the profile-local persisted env
(``special://profile/addon_data/script.tony7bones.bootstrap/tony7bones.env`` —
the future collector's output) is read only when the pushed file yields
nothing. An empty / comment-only / malformed file parses to {} and is the same
class as ABSENT (documented decision: a degenerate push carries no
configuration, and the wizard — whose defaults entry keeps the one-tap one
pick away — is the safe interactive landing for it).

TERMINAL DELETE COVERS BOTH LOCATIONS (Model A): Express completion and the
Guided terminal ops consume EVERY env candidate; a cancelled Express leaves
both intact (the re-run needs them).

THE DEFAULTS ENTRY (D1's one-tap escape): offered ONLY on the NO-ENV wizard
while gates remain; runs the EXACT old no-env Express — ``run_express({})``,
proven over the REAL engine to install exactly ``EXPECTED_NET_INSTALLED`` (the
frozen Express-proven constant) and to fire the Express terminal seam
(self-uninstall). An env-routed wizard's menu stays BYTE-IDENTICAL to 5d
(asserted exactly), so the shipped Guided surface cannot drift through N1.
"""

from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

# The frozen Express-proven net-set constant (the same loader pattern as
# test_no_fork.py, so this file never depends on rootdir-relative imports).
_TMS_PATH = Path(__file__).parent / "test_modular_setup.py"
_spec = importlib.util.spec_from_file_location("_tms_for_no_computer", _TMS_PATH)
_tms = importlib.util.module_from_spec(_spec)
sys.modules["_tms_for_no_computer"] = _tms
_spec.loader.exec_module(_tms)
EXPECTED_NET_INSTALLED = _tms.EXPECTED_NET_INSTALLED


def _no_env(boot):
    """Remove the fixture's seeded Express env -> a box with NO env anywhere
    (the remote-only / no-computer launch)."""
    os.remove(boot.env_file)


def _profile_env_path(boot):
    """The translated profile-local env path under THIS test's fake Kodi."""
    from tony7bones.setup import env as env_mod

    return env_mod.profile_env_path()


def _write_profile_env(boot, content):
    path = _profile_env_path(boot)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(content)
    return path


def _stub_express_ok(boot, monkeypatch, calls):
    """Stub run_express to record its env arg and report a completed run."""
    from tony7bones.setup.result import LayerResult

    def _express(env=None):
        calls.append(env)
        return LayerResult(layer="addons", ok=True), None, None

    monkeypatch.setattr(boot.mod, "run_express", _express)


def _forbid_express(boot, monkeypatch):
    monkeypatch.setattr(
        boot.mod,
        "run_express",
        lambda *a, **k: (_ for _ in ()).throw(
            AssertionError("run_express must NOT run on this route")
        ),
    )


def _forbid_guided(boot, monkeypatch):
    monkeypatch.setattr(
        boot.mod,
        "run_guided",
        lambda *a, **k: (_ for _ in ()).throw(
            AssertionError("run_guided must NOT run on this route")
        ),
    )


def _script_probes(boot, monkeypatch, foundation=False, iptv=True, addons=False):
    monkeypatch.setattr(boot.mod._probes, "foundation_done", lambda: foundation)
    monkeypatch.setattr(boot.mod._probes, "iptv_done", lambda env: iptv)
    monkeypatch.setattr(boot.mod._probes, "addons_done", lambda: addons)


# --------------------------------------------------------------------------- #
# The routing matrix (D1).
# --------------------------------------------------------------------------- #
def test_run_no_env_routes_to_guided_wizard(boot, monkeypatch):
    """THE N1 CHANGE + ITS MUTATION KILLER: with NO env anywhere, run() routes
    to run_guided({}) — and run_express raises if reached, so reverting the
    routing to the pre-N1 no-env Express fails here loudly."""
    _no_env(boot)
    seen = []
    monkeypatch.setattr(boot.mod, "run_guided", lambda env: seen.append(env))
    _forbid_express(boot, monkeypatch)

    boot.mod.run()

    assert seen == [{}], "no env -> run_guided({}) exactly once"


def test_run_env_without_mode_routes_express_with_env(boot, monkeypatch):
    """The provisioned one-tap CANNOT regress: an env without SETUP_MODE (the
    fixture's seeded pushed env carries only SETUP_MODE=express — same class)
    routes to Express with the parsed dict; the wizard never runs."""
    boot.env_file.write_text('DEVICE_NAME="Office"\n')
    calls = []
    _stub_express_ok(boot, monkeypatch, calls)
    _forbid_guided(boot, monkeypatch)

    boot.mod.run()

    assert len(calls) == 1
    assert calls[0].get("DEVICE_NAME") == "Office"


def test_run_env_guided_mode_still_routes_wizard(boot, monkeypatch):
    """SETUP_MODE=guided routing is unchanged from 5d."""
    boot.env_file.write_text("SETUP_MODE=guided\nMARK=pushed\n")
    seen = []
    monkeypatch.setattr(boot.mod, "run_guided", lambda env: seen.append(env))
    _forbid_express(boot, monkeypatch)

    boot.mod.run()

    assert len(seen) == 1 and seen[0]["MARK"] == "pushed"


def test_user_placed_env_at_device_path_routes_identically(boot, monkeypatch):
    """DELIVERY MODE 2 (owner directive — the self-contained no-adb path): an
    env file that simply EXISTS at the device path (``BOX_ENV_PATH``) routes
    EXACTLY as a provisioner-pushed one, regardless of HOW it got there
    (downloader app, Send-Files-to-TV, USB, share — the reader is
    provenance-agnostic by construction, and this pin keeps it that way).
    Both routes: no ``SETUP_MODE`` -> Express with the parsed dict;
    ``SETUP_MODE=guided`` -> the wizard with the parsed dict."""
    # Route 1: user-placed env, no SETUP_MODE -> the provisioned one-tap.
    boot.env_file.write_text('DEVICE_NAME="HandPlaced"\n')
    calls = []
    _stub_express_ok(boot, monkeypatch, calls)
    _forbid_guided(boot, monkeypatch)
    boot.mod.run()
    assert calls == [{"DEVICE_NAME": "HandPlaced"}], (
        "a user-placed env at the device path must drive Express exactly like "
        "a provisioner-pushed env"
    )

    # Route 2: user-placed env with SETUP_MODE=guided -> the wizard.
    boot.env_file.write_text("SETUP_MODE=guided\nMARK=hand-placed\n")
    seen = []
    monkeypatch.setattr(boot.mod, "run_guided", lambda env: seen.append(env))
    _forbid_express(boot, monkeypatch)
    boot.mod.run()
    assert seen == [{"SETUP_MODE": "guided", "MARK": "hand-placed"}], (
        "a user-placed env must honor SETUP_MODE routing identically"
    )


# --------------------------------------------------------------------------- #
# Ordered env sources: BOX_ENV_PATH wins; profile-local is the fallback.
# --------------------------------------------------------------------------- #
def test_pushed_env_wins_over_profile_local(boot, monkeypatch):
    """PRECEDENCE: with envs in BOTH locations the provisioner's pushed file
    wins — the provisioned path is byte-compatible by construction."""
    boot.env_file.write_text("SETUP_MODE=guided\nMARK=pushed\n")
    _write_profile_env(boot, "SETUP_MODE=guided\nMARK=profile\n")
    seen = []
    monkeypatch.setattr(boot.mod, "run_guided", lambda env: seen.append(env))

    boot.mod.run()

    assert seen[0]["MARK"] == "pushed", "BOX_ENV_PATH must win over profile-local"


def test_profile_local_env_routes_express_when_pushed_absent(boot, monkeypatch):
    """The collector's persisted env (profile-local) is a full peer: with the
    pushed file absent it drives the routing exactly like a pushed env."""
    _no_env(boot)
    _write_profile_env(boot, 'DEVICE_NAME="Collected"\n')
    calls = []
    _stub_express_ok(boot, monkeypatch, calls)
    _forbid_guided(boot, monkeypatch)

    boot.mod.run()

    assert calls[0].get("DEVICE_NAME") == "Collected"


def test_profile_local_guided_mode_routes_wizard(boot, monkeypatch):
    """The collector writes SETUP_MODE=guided so every reopen resumes the
    wizard (the N2 self-resume mechanism) — pin the routing half now."""
    _no_env(boot)
    _write_profile_env(boot, "SETUP_MODE=guided\n")
    seen = []
    monkeypatch.setattr(boot.mod, "run_guided", lambda env: seen.append(env))
    _forbid_express(boot, monkeypatch)

    boot.mod.run()

    assert len(seen) == 1 and seen[0]["SETUP_MODE"] == "guided"


def test_empty_env_file_is_the_no_env_case(boot, monkeypatch):
    """An EMPTY env file parses to {} -> same class as absent -> the wizard.
    (Documented decision: a degenerate push carries no configuration; the
    wizard is the safe interactive landing and keeps the one-tap one pick
    away. A provisioned box can no longer hit this — the provisioner aborts
    on a failed env push since N1.)"""
    boot.env_file.write_text("")
    seen = []
    monkeypatch.setattr(boot.mod, "run_guided", lambda env: seen.append(env))
    _forbid_express(boot, monkeypatch)

    boot.mod.run()

    assert seen == [{}]


def test_malformed_env_file_is_the_no_env_case(boot, monkeypatch):
    """Comment-only / no KEY=value lines parse to {} -> the wizard (same
    rationale as the empty file)."""
    boot.env_file.write_text("# just a comment\ngarbage line without equals\n")
    seen = []
    monkeypatch.setattr(boot.mod, "run_guided", lambda env: seen.append(env))
    _forbid_express(boot, monkeypatch)

    boot.mod.run()

    assert seen == [{}]


def test_empty_pushed_env_does_not_shadow_profile_local(boot, monkeypatch):
    """An empty pushed file is SKIPPED, not treated as a present-but-blank
    winner: the profile-local env behind it still drives the run."""
    boot.env_file.write_text("# pushed but empty\n")
    _write_profile_env(boot, 'DEVICE_NAME="Collected"\n')
    calls = []
    _stub_express_ok(boot, monkeypatch, calls)

    boot.mod.run()

    assert calls[0].get("DEVICE_NAME") == "Collected"


# --------------------------------------------------------------------------- #
# Terminal env-delete covers BOTH locations (Model A).
# --------------------------------------------------------------------------- #
def test_express_completion_deletes_both_env_locations(boot, monkeypatch):
    boot.env_file.write_text('DEVICE_NAME="Office"\n')
    profile_env = _write_profile_env(boot, 'DEVICE_NAME="Stale"\n')
    _stub_express_ok(boot, monkeypatch, [])

    boot.mod.run()

    assert not boot.env_file.exists(), "Express completion must consume the pushed env"
    assert not os.path.exists(profile_env), (
        "Express completion must ALSO consume the profile-local env "
        "(no secret lingers in either location)"
    )


def test_cancelled_express_leaves_both_envs_intact(boot, monkeypatch):
    """The early-return contract: a mid-install cancel consumed nothing, so
    BOTH env files survive for the re-run."""
    from tony7bones.setup.result import LayerResult

    boot.env_file.write_text('DEVICE_NAME="Office"\n')
    profile_env = _write_profile_env(boot, 'DEVICE_NAME="Stale"\n')
    monkeypatch.setattr(
        boot.mod,
        "run_express",
        lambda env=None: (LayerResult(layer="addons", ok=False), None, None),
    )

    boot.mod.run()

    assert boot.env_file.exists() and os.path.exists(profile_env)


def test_guided_finish_deletes_both_env_locations(boot, monkeypatch):
    """The Guided terminal op consumes EVERY env candidate."""
    boot.env_file.write_text("SETUP_MODE=guided\n")
    profile_env = _write_profile_env(boot, "SETUP_MODE=guided\n")
    _script_probes(boot, monkeypatch, foundation=True, iptv=True, addons=True)
    monkeypatch.setattr(boot.mod, "restart_kodi", lambda *a, **k: None)
    boot.state["select_queue"] = [0]  # Finish

    outcome = boot.mod.run_guided({"SETUP_MODE": "guided"})

    assert outcome == "finished"
    assert not boot.env_file.exists()
    assert not os.path.exists(profile_env)


# --------------------------------------------------------------------------- #
# The "Install everything with defaults" entry (D1's one-tap escape).
# --------------------------------------------------------------------------- #
def test_no_env_wizard_offers_defaults_entry(boot, monkeypatch):
    """The NO-ENV wizard menu carries the defaults entry (between the gate
    offer and Remove Setup) while gates remain."""
    monkeypatch.setattr(boot.mod, "restart_kodi", lambda *a, **k: None)
    outcome = boot.mod.run_guided({})

    assert outcome == "exit"
    _title, options = boot.state["select"][0]
    assert options[0].startswith("Install Foundation")
    assert options[1] == boot.mod._DEFAULTS_LABEL
    assert options[2] == "Remove Setup"
    assert options[3] == "Exit (keep Setup)"


def test_env_wizard_menu_is_byte_identical_to_5d(boot, monkeypatch):
    """An env-routed wizard (SETUP_MODE=guided) NEVER shows the defaults entry
    — its menu surface is EXACTLY the shipped 5d three-entry list. (The
    OWNER-VETOABLE conditionality: a provisioned Guided box was deliberately
    set up for the interview; offering a {}-env Express there would discard
    the provisioned config.)"""
    monkeypatch.setattr(boot.mod, "restart_kodi", lambda *a, **k: None)
    boot.mod.run_guided({"SETUP_MODE": "guided"})

    _title, options = boot.state["select"][0]
    assert options == [
        boot.mod._GATE_LABELS["foundation"],
        "Remove Setup",
        "Exit (keep Setup)",
    ], "the env-routed wizard menu must stay byte-identical to 5d"


def test_defaults_entry_hidden_at_finish(boot, monkeypatch):
    """On a complete box the only offers are Finish/Remove/Exit — the defaults
    entry adds nothing and is not shown."""
    _script_probes(boot, monkeypatch, foundation=True, iptv=True, addons=True)
    monkeypatch.setattr(boot.mod, "restart_kodi", lambda *a, **k: None)
    boot.mod.run_guided({})

    _title, options = boot.state["select"][0]
    assert options[0].startswith("Finish")
    assert boot.mod._DEFAULTS_LABEL not in options


def test_defaults_entry_runs_express_with_empty_env(boot, monkeypatch):
    """The entry runs the EXACT old no-env Express: run_express({}) — exactly
    once, with an EMPTY dict (never a collected/partial env)."""
    calls = []
    _stub_express_ok(boot, monkeypatch, calls)
    boot.state["select_queue"] = [1]

    outcome = boot.mod.run_guided({})

    assert outcome == "defaults"
    assert calls == [{}], "the defaults entry must run run_express({}) exactly once"


def test_defaults_entry_real_engine_net_set_and_terminal_seam(boot, monkeypatch):
    """THE EQUIVALENCE PROOF for the escape hatch, over the REAL engine: the
    defaults entry installs exactly EXPECTED_NET_INSTALLED — the same frozen
    constant the Express run() is pinned against — and fires the Express
    terminal seam (self-uninstall: the one-tap box is DONE, no Setup tile
    lingers)."""
    _no_env(boot)
    mine = boot.addons / boot.mod.MY_ID
    mine.mkdir(parents=True, exist_ok=True)
    (mine / "addon.xml").write_text(f'<addon id="{boot.mod.MY_ID}"/>')
    boot.state["select_queue"] = [1]

    outcome = boot.mod.run_guided({})

    assert outcome == "defaults"
    assert set(boot.state["installed"]) == set(EXPECTED_NET_INSTALLED), (
        "the defaults entry's net installed set must equal the Express-proven "
        "constant. MISSING="
        f"{sorted(EXPECTED_NET_INSTALLED - boot.state['installed'])} EXTRA="
        f"{sorted(boot.state['installed'] - EXPECTED_NET_INSTALLED)}"
    )
    assert not mine.exists(), "the defaults run must self-uninstall (Express seam)"
    assert boot.state["ok"], "the Express summary must be shown"


def test_defaults_entry_cancel_returns_to_menu(boot, monkeypatch):
    """A mid-install cancel during the defaults run follows the early-return
    contract: nothing terminal, the wizard menu returns for retry/exit."""
    from tony7bones.setup.result import LayerResult

    events = []
    monkeypatch.setattr(
        boot.mod,
        "run_express",
        lambda env=None: (LayerResult(layer="addons", ok=False), None, None),
    )
    monkeypatch.setattr(
        boot.mod, "self_uninstall", lambda *a, **k: events.append("uninstall")
    )
    monkeypatch.setattr(
        boot.mod, "restart_kodi", lambda *a, **k: events.append("restart")
    )
    boot.state["select_queue"] = [1]  # defaults; menu returns; queue empty -> exit

    outcome = boot.mod.run_guided({})

    assert outcome == "exit"
    assert events == [], "a cancelled defaults run must do nothing terminal"
    assert len(boot.state["select"]) == 2, "the wizard menu must return after cancel"


def test_defaults_entry_consumes_late_appearing_env(boot, monkeypatch):
    """Adversarial: an env pushed AFTER the no-env wizard launched. The
    defaults run is a TERMINAL op, so it consumes the late file — Setup
    self-uninstalls and no secret-bearing env may linger behind it."""
    _no_env(boot)
    calls = []
    _stub_express_ok(boot, monkeypatch, calls)
    boot.env_file.write_text('OWM_API_KEY="pushed-too-late"\n')  # appears mid-wizard
    boot.state["select_queue"] = [1]

    outcome = boot.mod.run_guided({})

    assert outcome == "defaults"
    assert calls == [{}], "the late env is NOT retro-read into this launch"
    assert not boot.env_file.exists(), (
        "the terminal defaults run must consume a late-appearing env"
    )


def test_no_env_wizard_remove_setup_at_shifted_index(boot, monkeypatch):
    """The defaults entry shifts Remove/Exit down one slot on the no-env menu;
    Remove Setup still confirms and fires the terminal op."""
    events = []
    monkeypatch.setattr(
        boot.mod, "self_uninstall", lambda *a, **k: events.append("uninstall")
    )
    monkeypatch.setattr(
        boot.mod, "restart_kodi", lambda *a, **k: events.append("restart")
    )
    boot.state["select_queue"] = [2]  # Remove Setup (index 2 on the no-env menu)
    boot.state["yesno_queue"] = [True]

    outcome = boot.mod.run_guided({})

    assert outcome == "removed"
    assert events == ["uninstall", "restart"]


# --------------------------------------------------------------------------- #
# The env helpers themselves (pure-Python unit pins).
# --------------------------------------------------------------------------- #
def test_box_env_paths_order_and_profile_translation(boot):
    """Pushed path FIRST (primary override honored), profile-local second —
    translated through xbmcvfs into the real profile dir."""
    from tony7bones.setup import env as env_mod

    paths = env_mod.box_env_paths(primary="/tmp/pushed.env")
    assert paths[0] == "/tmp/pushed.env"
    assert len(paths) == 2
    assert paths[1] == boot.mod.xbmcvfs.translatePath(env_mod.PROFILE_ENV_SPECIAL)
    # Default primary is the canonical pushed-path constant.
    assert env_mod.box_env_paths()[0] == env_mod.BOX_ENV_PATH


def test_box_env_paths_off_kodi_omits_profile(boot, monkeypatch):
    """Off-Kodi (no xbmcvfs importable) the profile candidate is omitted —
    the module stays import-clean and usable for pure-Python callers."""
    import sys as _sys

    from tony7bones.setup import env as env_mod

    monkeypatch.setitem(_sys.modules, "xbmcvfs", None)  # import yields None -> raises
    assert env_mod.box_env_paths(primary="/tmp/p.env") == ["/tmp/p.env"]


def test_read_first_env_skips_empty_and_missing(tmp_path):
    """read_first_env: absent and empty candidates are skipped; the first
    NON-EMPTY parse wins; nothing anywhere -> {}."""
    from tony7bones.setup import env as env_mod

    empty = tmp_path / "empty.env"
    empty.write_text("# nothing\n")
    real = tmp_path / "real.env"
    real.write_text("KEY=value\n")
    missing = str(tmp_path / "missing.env")

    assert env_mod.read_first_env([missing, str(empty), str(real)]) == {"KEY": "value"}
    assert env_mod.read_first_env([missing, str(empty)]) == {}
    assert env_mod.read_first_env([]) == {}


def test_delete_box_envs_is_guarded(tmp_path):
    """delete_box_envs removes what exists and silently skips what does not."""
    from tony7bones.setup import env as env_mod

    a = tmp_path / "a.env"
    a.write_text("K=v\n")
    env_mod.delete_box_envs([str(a), str(tmp_path / "missing.env")])  # must not raise
    assert not a.exists()
