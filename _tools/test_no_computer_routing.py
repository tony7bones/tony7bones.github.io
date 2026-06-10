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
    """Pushed path FIRST (primary override honored), the legacy push path
    second (pre-_T7B boxes), profile-local last — translated through xbmcvfs
    into the real profile dir."""
    from tony7bones.setup import env as env_mod

    paths = env_mod.box_env_paths(primary="/tmp/pushed.env")
    assert paths[0] == "/tmp/pushed.env"
    assert paths[1] == env_mod.LEGACY_BOX_ENV_PATH
    assert len(paths) == 3
    assert paths[2] == boot.mod.xbmcvfs.translatePath(env_mod.PROFILE_ENV_SPECIAL)
    # Default primary is the canonical pushed-path constant (under _T7B).
    assert env_mod.box_env_paths()[0] == env_mod.BOX_ENV_PATH
    assert env_mod.BOX_ENV_PATH == "/storage/emulated/0/_T7B/kodi/tony7bones.env"
    assert (
        env_mod.LEGACY_BOX_ENV_PATH
        == "/storage/emulated/0/kodi/tony.7.bones/tony7bones.env"
    )


def test_box_env_paths_off_kodi_omits_profile(boot, monkeypatch):
    """Off-Kodi (no xbmcvfs importable) the profile candidate is omitted —
    the module stays import-clean and usable for pure-Python callers."""
    import sys as _sys

    from tony7bones.setup import env as env_mod

    monkeypatch.setitem(_sys.modules, "xbmcvfs", None)  # import yields None -> raises
    assert env_mod.box_env_paths(primary="/tmp/p.env") == [
        "/tmp/p.env",
        env_mod.LEGACY_BOX_ENV_PATH,
    ]


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


# --------------------------------------------------------------------------- #
# Phase N1.1 — the device-resident MASTER env (.env.<device>): persistent
# identity (NEVER deleted), provisioner-parity derivation, and the no-env
# SCAFFOLD duty. docs/plans/no-computer-setup.md (N1.1 build-log entry).
# --------------------------------------------------------------------------- #
def _staging(boot):
    """The staging dir the master scan uses (dirname of the primary)."""
    return os.path.dirname(str(boot.env_file))


def _write_master(boot, name, content):
    path = os.path.join(_staging(boot), ".env." + name)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(content)
    return path


def _masters(boot):
    return sorted(n for n in os.listdir(_staging(boot)) if n.startswith(".env."))


def _stub_guided(boot, monkeypatch, calls):
    monkeypatch.setattr(
        boot.mod, "run_guided", lambda env=None: calls.append(env) or "exit"
    )


def test_master_env_routes_express_when_derived_absent(boot, monkeypatch):
    """The owner's model: the device-resident .env.<device> alone (no derived
    push) drives the box exactly like a provisioned env — no SETUP_MODE ->
    Express with the parsed dict."""
    _no_env(boot)
    _write_master(boot, "office", 'WEATHER_LOCATIONS="Testville"\n')
    _forbid_guided(boot, monkeypatch)
    calls = []
    _stub_express_ok(boot, monkeypatch, calls)

    boot.mod.run()

    assert calls and calls[0]["WEATHER_LOCATIONS"] == "Testville"


def test_master_env_setup_mode_guided_routes_wizard(boot, monkeypatch):
    """SETUP_MODE=guided FROM THE MASTER routes the wizard with the master's
    own dict (SETUP_MODE works from the master — the N1.1 routing contract)."""
    _no_env(boot)
    _write_master(boot, "office", 'SETUP_MODE="guided"\nMARKER="m"\n')
    _forbid_express(boot, monkeypatch)
    calls = []
    _stub_guided(boot, monkeypatch, calls)

    boot.mod.run()

    assert calls and calls[0]["MARKER"] == "m"
    assert calls[0]["SETUP_MODE"] == "guided"


def test_derived_env_wins_over_master(boot, monkeypatch):
    """Source order: the derived tony7bones.env (the freshest provisioner
    derivation — incl. its prompt-overridden DEVICE_NAME and appended
    IPTV_STAGING_DIR) outranks the master. MUTATION KILLER for a reversed
    order."""
    boot.env_file.write_text('MARKER="derived"\n')
    _write_master(boot, "office", 'MARKER="master"\n')
    calls = []
    _stub_express_ok(boot, monkeypatch, calls)

    boot.mod.run()

    assert calls and calls[0]["MARKER"] == "derived"


def test_master_wins_over_profile_local(boot, monkeypatch):
    """Source order: the master outranks the profile-local collector env."""
    _no_env(boot)
    _write_master(boot, "office", 'MARKER="master"\n')
    _write_profile_env(boot, 'MARKER="profile"\n')
    calls = []
    _stub_express_ok(boot, monkeypatch, calls)

    boot.mod.run()

    assert calls and calls[0]["MARKER"] == "master"


def test_multiple_masters_sorted_first_nonempty_wins_and_warns(boot, monkeypatch):
    """More than one .env.* is a misconfiguration: deterministic pick (sorted
    order, first NON-EMPTY wins — a degenerate file falls through like every
    other candidate) + a logged warning naming the files (names ONLY, never
    values)."""
    _no_env(boot)
    _write_master(boot, "aaa", "# all comments — degenerate\n")
    _write_master(boot, "bbb", 'MARKER="bbb" # SECRETVALUE must not be logged\n')
    _write_master(boot, "ccc", 'MARKER="ccc"\n')
    logged = []
    monkeypatch.setattr(boot.mod, "_log", lambda msg, *a, **k: logged.append(msg))
    calls = []
    _stub_express_ok(boot, monkeypatch, calls)

    boot.mod.run()

    assert calls and calls[0]["MARKER"] == "bbb"
    warnings = [m for m in logged if "multiple master envs" in m]
    assert warnings, "multiple masters must surface a logged warning"
    assert ".env.aaa" in warnings[0] and ".env.ccc" in warnings[0]
    assert "SECRETVALUE" not in " ".join(logged), "values must never be logged"


def test_master_derivation_drops_device_ip_and_injects_staging(boot, monkeypatch):
    """Provisioner parity: DEVICE_IP dropped (the derivation greps it out);
    IPTV_STAGING_DIR injected iff the sibling iptv/ staging dir exists —
    equivalent to the provisioner appending the key iff the push landed."""
    _no_env(boot)
    iptv_dir = os.path.join(_staging(boot), "iptv")
    os.makedirs(iptv_dir, exist_ok=True)
    _write_master(boot, "office", 'DEVICE_IP="1.2.3.4"\nMARKER="x"\n')
    calls = []
    _stub_express_ok(boot, monkeypatch, calls)

    boot.mod.run()

    assert calls and "DEVICE_IP" not in calls[0]
    assert calls[0]["IPTV_STAGING_DIR"] == iptv_dir


def test_master_derivation_respects_explicit_staging_and_absent_dir(boot, monkeypatch):
    """An explicit IPTV_STAGING_DIR in the master is preserved; with no iptv/
    dir on disk nothing is injected."""
    from tony7bones.setup import env as env_mod

    env = env_mod.derive_master_env(
        {"IPTV_STAGING_DIR": "/explicit", "DEVICE_IP": "1.2.3.4"},
        os.path.join(_staging(boot), ".env.office"),
    )
    assert env["IPTV_STAGING_DIR"] == "/explicit" and "DEVICE_IP" not in env

    env2 = env_mod.derive_master_env(
        {"MARKER": "x"}, os.path.join(_staging(boot), ".env.office")
    )
    assert "IPTV_STAGING_DIR" not in env2


def test_master_with_only_device_ip_is_no_env(boot, monkeypatch):
    """A master whose derivation empties it (only DEVICE_IP) carries no
    configuration -> the no-env class -> the wizard. And the scaffold must NOT
    fire (a master exists — never overwrite, never proliferate)."""
    _no_env(boot)
    path = _write_master(boot, "office", 'DEVICE_IP="1.2.3.4"\n')
    _forbid_express(boot, monkeypatch)
    calls = []
    _stub_guided(boot, monkeypatch, calls)

    boot.mod.run()

    assert calls == [{}]
    assert _masters(boot) == [".env.office"], "scaffold must not add a second master"
    assert open(path, encoding="utf-8").read() == 'DEVICE_IP="1.2.3.4"\n'


def test_non_utf8_master_is_no_env(boot, monkeypatch):
    """A user-placed master can be ANY bytes a file app produced: binary/non-
    UTF8 content is 'unreadable' -> {} -> the wizard, never a crash."""
    _no_env(boot)
    with open(os.path.join(_staging(boot), ".env.office"), "wb") as fh:
        fh.write(b"\xff\xfe\x00\x01 not text \x80")
    _forbid_express(boot, monkeypatch)
    calls = []
    _stub_guided(boot, monkeypatch, calls)

    boot.mod.run()

    assert calls == [{}]


# ---- terminal-delete split: the master is NEVER deleted -------------------- #
def test_express_completion_spares_master(boot, monkeypatch):
    """MUTATION KILLER (delete split): Express completion consumes the derived
    + profile-local envs but the device-resident master SURVIVES — it is the
    box's persistent identity (wipe-and-redo works forever)."""
    boot.env_file.write_text('MARKER="derived"\n')
    profile_env = _write_profile_env(boot, 'MARKER="profile"\n')
    master = _write_master(boot, "office", 'MARKER="master"\n')
    _stub_express_ok(boot, monkeypatch, [])

    boot.mod.run()

    assert not boot.env_file.exists()
    assert not os.path.exists(profile_env)
    assert os.path.exists(master), "the master env must NEVER be deleted"


def test_guided_finish_spares_master(boot, monkeypatch):
    """The Guided terminal op deletes the deletable set only — master spared."""
    boot.env_file.write_text("SETUP_MODE=guided\n")
    profile_env = _write_profile_env(boot, "SETUP_MODE=guided\n")
    master = _write_master(boot, "office", 'SETUP_MODE="guided"\n')
    _script_probes(boot, monkeypatch, foundation=True, iptv=True, addons=True)
    monkeypatch.setattr(boot.mod, "restart_kodi", lambda *a, **k: None)
    boot.state["select_queue"] = [0]  # Finish

    outcome = boot.mod.run_guided({"SETUP_MODE": "guided"})

    assert outcome == "finished"
    assert not boot.env_file.exists() and not os.path.exists(profile_env)
    assert os.path.exists(master), "the master env must NEVER be deleted"


def test_wipe_and_redo_works_off_surviving_master(boot, monkeypatch):
    """The owner contract end-to-end: a completed Express spares the master,
    so a 'wiped' box (no derived, no profile env) re-runs Express off the SAME
    master, forever."""
    _no_env(boot)
    _write_master(boot, "office", 'MARKER="master"\n')
    calls = []
    _stub_express_ok(boot, monkeypatch, calls)

    boot.mod.run()  # first run consumes nothing it shouldn't
    boot.mod.run()  # the redo: still routed by the surviving master

    assert [c["MARKER"] for c in calls] == ["master", "master"]


# ---- the scaffold duty ------------------------------------------------------ #
def test_no_env_scaffolds_master_template(boot, monkeypatch):
    """With NO env anywhere Setup CREATES .env.<device-name> (sanitized from
    Kodi's device name), content = the bundled template comment-disabled (so
    it parses to {} — the unedited scaffold cannot hijack routing), and the
    wizard surfaces ONE unobtrusive line (a toast naming the path)."""
    from tony7bones.setup import env as env_mod

    _no_env(boot)
    boot.state["settings_values"] = {"services.devicename": "Office Fire TV"}
    calls = []
    _stub_guided(boot, monkeypatch, calls)

    boot.mod.run()

    path = os.path.join(_staging(boot), ".env.office-fire-tv")
    assert os.path.exists(path), "the scaffold must create .env.<device-name>"
    content = open(path, encoding="utf-8").read()
    with open(boot.mod._ENV_TEMPLATE_RESOURCE, encoding="utf-8") as fh:
        assert content == env_mod.scaffold_template_text(fh.read())
    assert env_mod.parse_env(content) == {}, "unedited scaffold must parse empty"
    assert calls == [{}], "the wizard still runs after scaffolding"
    notes = boot.state.get("notification", [])
    assert any(path in msg for _t, msg in notes), "the one unobtrusive line"


def test_scaffold_device_name_fallback_generic(boot, monkeypatch):
    """No readable device name -> the generic fallback '.env.device'."""
    _no_env(boot)
    _stub_guided(boot, monkeypatch, [])

    boot.mod.run()

    assert os.path.exists(os.path.join(_staging(boot), ".env.device"))


def test_scaffold_never_overwrites_existing_master(boot, monkeypatch):
    """NEVER overwrite: any pre-existing master (even a degenerate one) means
    no scaffold write, no toast, byte-identical content after the run.
    MUTATION KILLER for an unconditional create."""
    _no_env(boot)
    sentinel = "# user file — hands off\n"
    path = _write_master(boot, "mine", sentinel)
    _stub_guided(boot, monkeypatch, [])

    boot.mod.run()

    assert _masters(boot) == [".env.mine"]
    assert open(path, encoding="utf-8").read() == sentinel
    assert not boot.state.get("notification"), "no creation -> no toast"


def test_scaffold_creates_missing_staging_dirs(boot, monkeypatch):
    """The staging dir is created when absent (mkdir -p semantics)."""
    deep = os.path.join(_staging(boot), "sub", "deep")
    monkeypatch.setattr(boot.mod, "BOX_ENV_PATH", os.path.join(deep, "t.env"))
    _no_env(boot)
    _stub_guided(boot, monkeypatch, [])

    boot.mod.run()

    assert os.path.exists(os.path.join(deep, ".env.device"))


def test_scaffold_nonfatal_when_staging_unavailable(boot, monkeypatch):
    """Where the staging root cannot exist (macOS: /storage/... is not
    creatable) the scaffold is a guarded LOG-SKIP — the wizard still runs."""
    blocker = os.path.join(_staging(boot), "blocker")
    open(blocker, "w").close()  # a FILE where the dir must go -> OSError
    monkeypatch.setattr(boot.mod, "BOX_ENV_PATH", os.path.join(blocker, "x", "t.env"))
    _no_env(boot)
    calls = []
    _stub_guided(boot, monkeypatch, calls)

    boot.mod.run()  # must not raise

    assert calls == [{}]
    assert not boot.state.get("notification")


def test_bundled_template_matches_repo_example(boot):
    """DRIFT PIN: the bundled scaffold resource is a byte-identical copy of
    the repo's committed .env.device.example."""
    repo_example = Path(__file__).resolve().parent.parent / ".env.device.example"
    assert (
        Path(boot.mod._ENV_TEMPLATE_RESOURCE).read_bytes() == repo_example.read_bytes()
    )


def test_scaffolded_content_is_placeholder_comments_only(boot):
    """Secret-leak shape: every non-blank scaffolded line is a comment."""
    from tony7bones.setup import env as env_mod

    with open(boot.mod._ENV_TEMPLATE_RESOURCE, encoding="utf-8") as fh:
        text = env_mod.scaffold_template_text(fh.read())
    for line in text.splitlines():
        assert not line.strip() or line.lstrip().startswith("#"), line


# ---- pure env-helper units (N1.1) ------------------------------------------ #
def test_box_env_paths_order_includes_masters_in_middle(boot):
    """Order contract: [derived (canonical, legacy), masters (sorted),
    profile-local]."""
    from tony7bones.setup import env as env_mod

    _write_master(boot, "bbb", "X=1\n")
    _write_master(boot, "aaa", "X=1\n")
    primary = str(boot.env_file)
    paths = env_mod.box_env_paths(primary=primary)
    assert paths[0] == primary
    assert paths[1] == env_mod.LEGACY_BOX_ENV_PATH
    assert paths[2].endswith(".env.aaa") and paths[3].endswith(".env.bbb")
    assert paths[4] == env_mod.profile_env_path()


def test_deletable_env_paths_excludes_masters(boot):
    from tony7bones.setup import env as env_mod

    _write_master(boot, "office", "X=1\n")
    primary = str(boot.env_file)
    deletable = env_mod.deletable_env_paths(primary=primary)
    assert deletable == [
        primary,
        env_mod.LEGACY_BOX_ENV_PATH,
        env_mod.profile_env_path(),
    ]
    assert not any(env_mod.is_master_env_path(p) for p in deletable)


def test_master_env_paths_off_device_is_empty(boot):
    """No staging dir (the real /storage/... on macOS / off-device) -> []."""
    from tony7bones.setup import env as env_mod

    missing = os.path.join(_staging(boot), "nope", "tony7bones.env")
    assert env_mod.master_env_paths(primary=missing) == []


def test_sanitize_device_name_cases(boot):
    from tony7bones.setup import env as env_mod

    s = env_mod.sanitize_device_name
    assert s("Office Fire TV") == "office-fire-tv"
    assert s("  Tony's #1 Box!! ") == "tony-s-1-box"
    assert s("") == "device"
    assert s(None) == "device"
    assert s("___") == "device"


def test_full_shape_master_fixture_parity(boot, monkeypatch):
    """A FULL-SHAPE master (every .env.device.example key, FAKE values) read
    through run(): the consumed keys arrive parsed, DEVICE_IP is dropped
    (parity with the provisioner's grep), DEVICE_NAME passes through AS THE
    MASTER'S OWN VALUE (documented divergence: no prompt to override it on
    the no-computer path), and IPTV_STAGING_DIR is injected iff staged."""
    _no_env(boot)
    os.makedirs(os.path.join(_staging(boot), "iptv"), exist_ok=True)
    _write_master(
        boot,
        "office",
        "\n".join(
            [
                'DEVICE_NAME="Fake Box"',
                'DEVICE_IP="203.0.113.7"',
                'KODI_DATA_PATH="/sdcard/kodi_data/.kodi"',
                'KODI_WEB_USER="fakeuser"',
                'KODI_WEB_PASS="fakepass"',
                'KODI_WEB_PORT="8080"',
                'KODI_REMOTE_CONTROL="true"',
                'SETTINGS_LEVEL="expert"',
                'WEATHER_LOCATIONS="Faketown; Mocksville"',
                'WEATHERBIT_API_KEY="fake_wb_key"',
                'OWM_API_KEY="fake_owm_key"',
                'IPTV_NAME="Fake Provider"',
                'IPTV_M3U="http://fake.example:8080/get.php?username=U&password=P"',
                'IPTV_EPG="http://fake.example:8080/xmltv.php?username=U&password=P"',
                'IPTV_GROUPS="FAKE GROUP A; FAKE GROUP B"',
                'IPTV_GROUPS_ONLY="true"',
                'RSS_INTERVAL="30"',
                'RSS_FEEDS="https://feeds.example.com/a.xml"',
            ]
        )
        + "\n",
    )
    calls = []
    _stub_express_ok(boot, monkeypatch, calls)

    boot.mod.run()

    env = calls[0]
    assert "DEVICE_IP" not in env
    assert env["DEVICE_NAME"] == "Fake Box"
    assert env["WEATHER_LOCATIONS"] == "Faketown; Mocksville"
    assert env["IPTV_M3U"].startswith("http://fake.example")
    assert env["IPTV_GROUPS"] == "FAKE GROUP A; FAKE GROUP B"
    assert env["RSS_FEEDS"].startswith("https://feeds.example.com")
    assert env["IPTV_STAGING_DIR"] == os.path.join(_staging(boot), "iptv")


def test_device_name_unreadable_falls_back_generic(boot, monkeypatch):
    """A failing JSON-RPC device-name read -> '' -> the generic scaffold name."""
    monkeypatch.setattr(
        boot.mod.xbmc,
        "executeJSONRPC",
        lambda s: (_ for _ in ()).throw(RuntimeError("rpc down")),
    )
    assert boot.mod._device_name() == ""


def test_scaffold_skips_when_bundled_template_unreadable(boot, monkeypatch):
    """A missing/unreadable bundled resource is a guarded log-skip, never a
    crash (the wizard still runs)."""
    monkeypatch.setattr(
        boot.mod, "_ENV_TEMPLATE_RESOURCE", os.path.join(_staging(boot), "missing")
    )
    assert boot.mod._scaffold_master_env() is None


def test_scaffold_toast_failure_never_blocks_wizard(boot, monkeypatch):
    """A raising notification (odd skins/platforms) must not break run()."""

    class _BoomDialog(boot.mod.xbmcgui.Dialog):
        def notification(self, *a, **k):
            raise RuntimeError("toast broken")

    monkeypatch.setattr(boot.mod.xbmcgui, "Dialog", _BoomDialog)
    _no_env(boot)
    calls = []
    _stub_guided(boot, monkeypatch, calls)

    boot.mod.run()  # must not raise

    assert calls == [{}]
    assert os.path.exists(os.path.join(_staging(boot), ".env.device"))


# --------------------------------------------------------------------------- #
# N1.1 — the LEGACY device root (/storage/emulated/0/kodi/tony.7.bones/) is a
# read-only FALLBACK: still read (pre-_T7B boxes have files there), outranked
# by everything at the canonical _T7B root, and NEVER written to (no scaffold).
# --------------------------------------------------------------------------- #
def _legacy_root(boot, monkeypatch):
    """Point the module's legacy push path at a real tmp legacy root (the
    functions resolve the module global late, so this carries the legacy
    master scan along too)."""
    from tony7bones.setup import env as env_mod

    root = os.path.join(_staging(boot), "legacy-root")
    os.makedirs(root, exist_ok=True)
    monkeypatch.setattr(
        env_mod, "LEGACY_BOX_ENV_PATH", os.path.join(root, "tony7bones.env")
    )
    return root


def test_legacy_derived_env_routes_when_canonical_absent(boot, monkeypatch):
    """An already-provisioned box (derived env still at the LEGACY push path,
    nothing at the new root) keeps working: the legacy push drives Express —
    and, being machine-derived, is consumed by the terminal delete."""
    _no_env(boot)
    root = _legacy_root(boot, monkeypatch)
    legacy_env = os.path.join(root, "tony7bones.env")
    with open(legacy_env, "w", encoding="utf-8") as fh:
        fh.write('MARKER="legacy-derived"\n')
    calls = []
    _stub_express_ok(boot, monkeypatch, calls)
    _forbid_guided(boot, monkeypatch)

    boot.mod.run()

    assert calls and calls[0]["MARKER"] == "legacy-derived"
    assert not os.path.exists(legacy_env), (
        "the legacy derived push is machine-derived — the terminal delete owns it"
    )


def test_canonical_derived_wins_over_legacy_derived(boot, monkeypatch):
    """Source order: the canonical (_T7B) push outranks the legacy push.
    MUTATION KILLER for a reversed root order."""
    boot.env_file.write_text('MARKER="canonical"\n')
    root = _legacy_root(boot, monkeypatch)
    with open(os.path.join(root, "tony7bones.env"), "w", encoding="utf-8") as fh:
        fh.write('MARKER="legacy"\n')
    calls = []
    _stub_express_ok(boot, monkeypatch, calls)

    boot.mod.run()

    assert calls and calls[0]["MARKER"] == "canonical"


def test_legacy_master_read_as_fallback_and_never_deleted(boot, monkeypatch):
    """A master left at the LEGACY root still drives the box (fallback read)
    AND survives the terminal delete (the never-delete contract covers both
    roots)."""
    _no_env(boot)
    root = _legacy_root(boot, monkeypatch)
    legacy_master = os.path.join(root, ".env.office")
    with open(legacy_master, "w", encoding="utf-8") as fh:
        fh.write('MARKER="legacy-master"\n')
    calls = []
    _stub_express_ok(boot, monkeypatch, calls)

    boot.mod.run()

    assert calls and calls[0]["MARKER"] == "legacy-master"
    assert os.path.exists(legacy_master), "a legacy master must NEVER be deleted"


def test_canonical_master_wins_over_legacy_master(boot, monkeypatch):
    """Master scan order: the canonical root's masters outrank the legacy
    root's — the new root wins."""
    _no_env(boot)
    _write_master(boot, "office", 'MARKER="canonical-master"\n')
    root = _legacy_root(boot, monkeypatch)
    with open(os.path.join(root, ".env.office"), "w", encoding="utf-8") as fh:
        fh.write('MARKER="legacy-master"\n')
    calls = []
    _stub_express_ok(boot, monkeypatch, calls)

    boot.mod.run()

    assert calls and calls[0]["MARKER"] == "canonical-master"


def test_scaffold_skipped_by_legacy_master_and_never_writes_legacy(boot, monkeypatch):
    """The scaffold NEVER writes to the legacy root: (a) a master existing
    ONLY at the legacy root suppresses the scaffold entirely (never overwrite
    or proliferate — the legacy master IS the box's identity); (b) with no
    master anywhere the scaffold lands at the CANONICAL root and the legacy
    root stays untouched."""
    _no_env(boot)
    root = _legacy_root(boot, monkeypatch)
    legacy_master = os.path.join(root, ".env.mine")
    sentinel = "# legacy identity — hands off\n"
    with open(legacy_master, "w", encoding="utf-8") as fh:
        fh.write(sentinel)
    _stub_guided(boot, monkeypatch, [])

    boot.mod.run()

    assert _masters(boot) == [], "no scaffold at the canonical root"
    assert sorted(os.listdir(root)) == [".env.mine"]
    assert open(legacy_master, encoding="utf-8").read() == sentinel

    # (b) no master anywhere -> scaffold at the canonical root ONLY.
    os.remove(legacy_master)
    boot.mod.run()
    assert _masters(boot) == [".env.device"]
    assert sorted(os.listdir(root)) == [], "the legacy root is never written to"
