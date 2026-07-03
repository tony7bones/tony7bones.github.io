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
        return LayerResult(layer="addons", ok=True), None, None, None, None

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
    """`foundation` drives ALL THREE probes the bundled Foundation gate backs
    (Foundation config + Backup + Skin — no separate gates/menu entries exist
    for those yet)."""
    monkeypatch.setattr(
        boot.mod._probes, "foundation_done", lambda env=None: foundation
    )
    monkeypatch.setattr(boot.mod._probes, "backup_done", lambda env=None: foundation)
    monkeypatch.setattr(boot.mod._probes, "skin_done", lambda: foundation)
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
        lambda env=None: (
            LayerResult(layer="addons", ok=False),
            None,
            None,
            None,
            None,
        ),
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
        lambda env=None: (
            LayerResult(layer="addons", ok=False),
            None,
            None,
            None,
            None,
        ),
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
def test_box_env_paths_order_and_profile_translation(boot, tmp_path):
    """Pushed path FIRST (primary override honored), the legacy push path
    second (pre-_T7B boxes), profile-local last — translated through xbmcvfs
    into the real profile dir. (A primary in an EMPTY dir so no stray master
    files perturb the order — the master-in-the-middle case is pinned
    separately.)"""
    from tony7bones.setup import env as env_mod

    primary = str(tmp_path / "pushed.env")
    paths = env_mod.box_env_paths(primary=primary)
    assert paths[0] == primary
    assert paths[1] == env_mod.LEGACY_BOX_ENV_PATH
    assert len(paths) == 3
    assert paths[2] == boot.mod.xbmcvfs.translatePath(env_mod.PROFILE_ENV_SPECIAL)
    # Default primary is the canonical pushed-path constant (under _T7B/kodi).
    assert env_mod.box_env_paths()[0] == env_mod.BOX_ENV_PATH
    assert env_mod.BOX_ENV_PATH == "/storage/emulated/0/_T7B/kodi/tony7bones.env"
    assert env_mod.BRAND_ROOT == "/storage/emulated/0/_T7B"
    assert (
        env_mod.LEGACY_BOX_ENV_PATH
        == "/storage/emulated/0/kodi/tony.7.bones/tony7bones.env"
    )


def test_box_env_paths_off_kodi_omits_profile(boot, monkeypatch, tmp_path):
    """Off-Kodi (no xbmcvfs importable) the profile candidate is omitted —
    the module stays import-clean and usable for pure-Python callers."""
    import sys as _sys

    from tony7bones.setup import env as env_mod

    monkeypatch.setitem(_sys.modules, "xbmcvfs", None)  # import yields None -> raises
    primary = str(tmp_path / "p.env")
    assert env_mod.box_env_paths(primary=primary) == [
        primary,
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
    from tony7bones.setup import env as env_mod

    return sorted(
        n for n in os.listdir(_staging(boot)) if env_mod.is_master_env_filename(n)
    )


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
    IPTV_STAGING_DIR injected iff the sibling iptv/ staging dir holds STAGED
    ARTIFACTS (is non-empty) — equivalent to the provisioner appending the key
    iff the push landed. An EMPTY iptv/ (onboarding self-creates one) is not
    staging and does NOT inject (see test_empty_iptv_staging_dir_not_injected)."""
    _no_env(boot)
    iptv_dir = os.path.join(_staging(boot), "iptv")
    os.makedirs(iptv_dir, exist_ok=True)
    # A staged artifact landed (non-empty) — the real provisioner-push signal.
    with open(os.path.join(iptv_dir, "instance-settings-1.xml"), "w") as fh:
        fh.write("<settings/>")
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
    """With NO env anywhere Setup CREATES env.<device-name> (NO leading dot —
    the owner's convention; sanitized from Kodi's device name), content = the
    bundled template comment-disabled (so it parses to {} — the unedited
    scaffold cannot hijack routing), and the wizard surfaces ONE unobtrusive
    line (a toast naming the path)."""
    from tony7bones.setup import env as env_mod

    _no_env(boot)
    boot.state["settings_values"] = {"services.devicename": "Office Fire TV"}
    calls = []
    _stub_guided(boot, monkeypatch, calls)

    boot.mod.run()

    path = os.path.join(_staging(boot), "env.office-fire-tv")
    assert os.path.exists(path), "the scaffold must create env.<device-name>"
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

    assert os.path.exists(os.path.join(_staging(boot), "env.device"))


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

    assert os.path.exists(os.path.join(deep, "env.device"))


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
    iptv_dir = os.path.join(_staging(boot), "iptv")
    os.makedirs(iptv_dir, exist_ok=True)
    # Non-empty = staged artifacts landed (the provisioner-push signal).
    with open(os.path.join(iptv_dir, "instance-settings-1.xml"), "w") as fh:
        fh.write("<settings/>")
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


def test_device_name_treats_kodi_stock_default_as_generic(boot):
    """_device_name() is a thin shim over env.resolve_device_name - the SAME
    fix that protects the Backup layer's collision risk also protects the
    scaffold: Kodi's stock, never-customized device name ("Kodi") resolves the
    same as unreadable, not as a real, distinguishing name."""
    boot.state["settings_values"] = {"services.devicename": "Kodi"}
    assert boot.mod._device_name() == ""


# --------------------------------------------------------------------------- #
# ensure_device_name - the early, interactive collision-prevention prompt.
# Fires as soon as possible in Guided (never Express, which stays unattended).
# --------------------------------------------------------------------------- #
def test_ensure_device_name_noop_when_env_has_real_name(boot):
    """A real DEVICE_NAME in the env -> no-op, no prompt shown."""
    from tony7bones.setup import env as env_mod

    env_mod.ensure_device_name({"DEVICE_NAME": "Office"})
    assert boot.state.get("input", []) == []


def test_ensure_device_name_noop_when_kodi_name_already_real(boot):
    """A genuinely customized Kodi device name -> no-op, no prompt shown."""
    from tony7bones.setup import env as env_mod

    boot.state["settings_values"] = {"services.devicename": "Bedroom Fire TV"}
    env_mod.ensure_device_name({})
    assert boot.state.get("input", []) == []


def test_ensure_device_name_prompts_when_no_real_identity(boot):
    """No env value AND Kodi's device name is blank/stock -> the prompt fires."""
    from tony7bones.setup import env as env_mod

    env_mod.ensure_device_name({})
    assert len(boot.state.get("input", [])) == 1


def test_ensure_device_name_prompts_when_kodi_name_is_stock_default(boot):
    """Kodi's stock "Kodi" is treated as no identity -> the prompt fires too,
    not just the truly-blank case."""
    from tony7bones.setup import env as env_mod

    boot.state["settings_values"] = {"services.devicename": "Kodi"}
    env_mod.ensure_device_name({})
    assert len(boot.state.get("input", [])) == 1


def test_ensure_device_name_writes_entered_name_to_kodi_setting(boot):
    """A non-empty answer is written straight to services.devicename - so
    every later phase (and any future run) resolves a real identity. Proves
    the ACTUAL write-then-read round trip through the fake JSON-RPC (the fake
    mirrors Settings.SetSettingValue into settings_values, exactly like real
    Kodi's core settings store) - not a manually fabricated read."""
    from tony7bones.setup import env as env_mod

    boot.state["input_answer"] = "Living Room"
    env_mod.ensure_device_name({})
    written = [
        j
        for j in boot.state["jsonrpc"]
        if '"setting": "services.devicename"' in j and "SetSettingValue" in j
    ]
    assert written, "the entered name must be written via Settings.SetSettingValue"
    assert '"value": "Living Room"' in written[0]
    # A subsequent resolve genuinely finds it, through the fake's own mirrored
    # state — no manual seeding of settings_values.
    assert env_mod.resolve_device_name({}) == "Living Room"


def test_ensure_device_name_cancelled_prompt_is_safe_noop(boot):
    """An empty/cancelled answer (the fake's default) never raises and never
    writes anything - Setup proceeds regardless, keeping the generic identity."""
    from tony7bones.setup import env as env_mod

    env_mod.ensure_device_name({})  # boot.state["input_answer"] defaults to ""
    written = [j for j in boot.state["jsonrpc"] if "SetSettingValue" in j]
    assert not any('"setting": "services.devicename"' in j for j in written)


def test_ensure_device_name_rejects_user_typed_stock_default(boot):
    """A user who types Kodi's own stock name ("Kodi", any case) into the
    prompt must NOT have it written - that would recreate the exact collision
    this function exists to prevent, now via explicit user input instead of
    an unset default. Treated identically to cancelling."""
    from tony7bones.setup import env as env_mod

    for typed in ("Kodi", "kodi", "  KODI  "):
        boot.state["input_answer"] = typed
        boot.state["jsonrpc"] = []
        env_mod.ensure_device_name({})
        written = [j for j in boot.state["jsonrpc"] if "SetSettingValue" in j]
        assert not any('"setting": "services.devicename"' in j for j in written), (
            "typed value {!r} must not be written".format(typed)
        )


def test_ensure_device_name_verifies_write_before_claiming_success(boot, monkeypatch):
    """The write is VERIFIED with a read-back, not trusted fire-and-forget -
    the same discipline the Backup layer's install uses. If the setting
    somehow does not verify after the write, this must be non-fatal (log and
    move on), not silently claim success."""
    from tony7bones.setup import env as env_mod

    boot.state["input_answer"] = "Living Room"
    # Simulate a write that reports success but never actually lands: the
    # fake's own SetSettingValue mirroring is bypassed here so the read-back
    # genuinely fails, proving ensure_device_name checks it rather than
    # trusting the call.
    monkeypatch.setattr(
        boot.mod.xbmc,
        "executeJSONRPC",
        lambda s: "{}" if "SetSettingValue" in s else "{}",
    )
    logged = []
    env_mod.ensure_device_name({}, log=logged.append)
    assert env_mod.resolve_device_name({}) == "", (
        "an unverified write must not be trusted as a real identity"
    )
    assert any("did not verify" in m for m in logged)


def test_run_guided_calls_ensure_device_name_early(boot, monkeypatch):
    """Wired into the ACTUAL Guided entry point, before any gate runs — calls
    the REAL run_guided directly (not the routing stub, which replaces
    run_guided wholesale and would never reach the line under test)."""
    calls = []
    monkeypatch.setattr(
        boot.mod._env_mod, "ensure_device_name", lambda env, log=None: calls.append(env)
    )
    monkeypatch.setattr(boot.mod, "restart_kodi", lambda *a, **k: None)
    outcome = boot.mod.run_guided({})
    assert outcome == "exit"  # declines the fresh-box offer, same as other tests
    assert len(calls) == 1


def test_run_guided_calls_ensure_device_name_once_across_multiple_gate_iterations(
    boot, monkeypatch
):
    """Fires ONCE at the top of run_guided, not once per gate-loop iteration -
    a future refactor moving the call inside the while loop must be caught.
    Drives TWO loop iterations via the same select_queue pattern
    test_run_guided.py's own multi-iteration tests use (Remove Setup ->
    declined -> Exit)."""
    calls = []
    monkeypatch.setattr(
        boot.mod._env_mod, "ensure_device_name", lambda env, log=None: calls.append(env)
    )
    monkeypatch.setattr(boot.mod, "restart_kodi", lambda *a, **k: None)
    boot.state["select_queue"] = [1, 2]  # Remove Setup -> declined -> Exit
    boot.state["yesno_queue"] = [False]

    outcome = boot.mod.run_guided({"SETUP_MODE": "guided"})

    assert outcome == "exit"
    assert len(boot.state["select"]) == 2, "the menu must have looped twice"
    assert len(calls) == 1, "ensure_device_name must fire once, not per iteration"


def test_run_express_never_calls_ensure_device_name(boot, monkeypatch):
    """Express stays fully unattended - a provisioned box already has a real
    device name from the provisioner, so this must never fire there."""
    calls = []
    monkeypatch.setattr(
        boot.mod._env_mod, "ensure_device_name", lambda env, log=None: calls.append(env)
    )
    boot.mod.run()  # the fixture's seeded env is SETUP_MODE=express by default
    assert calls == []


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
    assert os.path.exists(os.path.join(_staging(boot), "env.device"))


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

    # (b) no master anywhere -> scaffold at the brand root ONLY.
    os.remove(legacy_master)
    boot.mod.run()
    assert _masters(boot) == ["env.device"]
    assert sorted(os.listdir(root)) == [], "the legacy root is never written to"


# --------------------------------------------------------------------------- #
# N1.1 FIX — the BRAND ROOT (_T7B/) is the PRIMARY master location, and the
# master filename is DOT-OPTIONAL. The owner physically places
# /storage/emulated/0/_T7B/env.<device> (NO leading dot, one level ABOVE the
# _T7B/kodi/ staging tree). The prior N1.1 code searched _T7B/kodi/.env.* —
# one dir too deep AND dot-required — so every box missed its master. These
# pins encode the owner's confirmed layout.
# --------------------------------------------------------------------------- #
def _prod_layout(boot, monkeypatch):
    """Point BOX_ENV_PATH at a production-shaped …/kodi/tony7bones.env so the
    brand root resolves to its PARENT (the _T7B/ analogue) and the staging tree
    is the kodi/ child. Returns (brand_root, staging_dir), both created."""
    from tony7bones.setup import env as env_mod

    brand = os.path.join(_staging(boot), "_T7B")
    staging = os.path.join(brand, "kodi")
    os.makedirs(staging, exist_ok=True)
    pushed = os.path.join(staging, "tony7bones.env")
    monkeypatch.setattr(boot.mod, "BOX_ENV_PATH", pushed)
    # The env module reads the bootstrap's BOX_ENV_PATH late, but its own
    # constants (BRAND_ROOT/DEVICE_ROOT) are unused once a primary is threaded.
    assert env_mod.brand_root(pushed) == brand
    assert env_mod.staging_dir(pushed) == staging
    return brand, staging


def test_owner_nodot_master_at_brand_root_routes_express(boot, monkeypatch):
    """THE BUG FIX, end-to-end: a no-dot master at the BRAND ROOT
    (_T7B/env.office) — exactly where the owner placed it — is FOUND and routes
    Express with its parsed dict. (Pre-fix the scan looked one dir too deep in
    _T7B/kodi/ and required a leading dot, so this file was missed and the box
    wrongly fell through to the wizard.)"""
    brand, _staging_tree = _prod_layout(boot, monkeypatch)
    os.remove(boot.env_file)  # no derived push anywhere
    master = os.path.join(brand, "env.office")  # NO leading dot, BRAND ROOT
    with open(master, "w", encoding="utf-8") as fh:
        fh.write('WEATHER_LOCATIONS="Sacramento"\n')
    _forbid_guided(boot, monkeypatch)
    calls = []
    _stub_express_ok(boot, monkeypatch, calls)

    boot.mod.run()

    assert calls and calls[0]["WEATHER_LOCATIONS"] == "Sacramento", (
        "the no-dot master at the brand root must route Express"
    )
    assert os.path.exists(master), "the brand-root master must never be deleted"


def test_dot_master_in_staging_tree_still_found(boot, monkeypatch):
    """The prior N1.1 location stays a fallback: a leading-dot master in the
    _T7B/kodi/ STAGING tree is still found and routed."""
    _brand, staging = _prod_layout(boot, monkeypatch)
    os.remove(boot.env_file)
    master = os.path.join(staging, ".env.office")  # dot form, staging tree
    with open(master, "w", encoding="utf-8") as fh:
        fh.write('MARKER="staging-dot"\n')
    calls = []
    _stub_express_ok(boot, monkeypatch, calls)

    boot.mod.run()

    assert calls and calls[0]["MARKER"] == "staging-dot"
    assert os.path.exists(master)


def test_brand_root_master_wins_over_staging_tree_master(boot, monkeypatch):
    """Master scan order: BRAND ROOT outranks the staging tree (the owner's
    placement is primary). MUTATION KILLER for a reversed root order."""
    brand, staging = _prod_layout(boot, monkeypatch)
    os.remove(boot.env_file)
    with open(os.path.join(brand, "env.office"), "w", encoding="utf-8") as fh:
        fh.write('MARKER="brand"\n')
    with open(os.path.join(staging, ".env.office"), "w", encoding="utf-8") as fh:
        fh.write('MARKER="staging"\n')
    calls = []
    _stub_express_ok(boot, monkeypatch, calls)

    boot.mod.run()

    assert calls and calls[0]["MARKER"] == "brand"


def test_nodot_master_setup_mode_guided_routes_wizard(boot, monkeypatch):
    """SETUP_MODE=guided from a no-dot brand-root master routes the wizard with
    the master's own dict (the routing contract holds dot-optionally)."""
    brand, _staging = _prod_layout(boot, monkeypatch)
    os.remove(boot.env_file)
    with open(os.path.join(brand, "env.office"), "w", encoding="utf-8") as fh:
        fh.write('SETUP_MODE="guided"\nMARKER="m"\n')
    _forbid_express(boot, monkeypatch)
    calls = []
    _stub_guided(boot, monkeypatch, calls)

    boot.mod.run()

    assert calls and calls[0]["SETUP_MODE"] == "guided" and calls[0]["MARKER"] == "m"


def test_scaffold_writes_nodot_at_brand_root_not_staging(boot, monkeypatch):
    """The scaffold target moved: with NO env anywhere it creates
    env.<device> (NO leading dot) at the BRAND ROOT — never the staging tree,
    never the legacy root."""
    brand, staging = _prod_layout(boot, monkeypatch)
    os.remove(boot.env_file)
    boot.state["settings_values"] = {"services.devicename": "Office Fire TV"}
    _stub_guided(boot, monkeypatch, [])

    boot.mod.run()

    from tony7bones.setup import env as env_mod

    scaffolded = os.path.join(brand, "env.office-fire-tv")
    assert os.path.exists(scaffolded), "scaffold lands at the brand root, no dot"
    # No MASTER env is dropped into the staging tree (the scaffold target is the
    # brand root). The staging tree DOES hold the five non-master onboarding
    # subdirs (backups/ iptv/ media/ repositories/ rss/ — ensure_device_dirs),
    # so assert specifically that no master-named file lands there.
    assert [
        n for n in os.listdir(staging) if env_mod.is_master_env_filename(n)
    ] == [], "the staging tree is not the scaffold target"
    toast = boot.state.get("notification", [])
    assert any(scaffolded in msg for _t, msg in toast)


def test_brand_root_master_never_deleted_on_express_completion(boot, monkeypatch):
    """The never-delete contract holds for a brand-root master: a completed
    Express consumes the derived push but spares the brand-root master, so a
    wipe-and-redo works forever off it."""
    brand, staging = _prod_layout(boot, monkeypatch)
    pushed = boot.mod.BOX_ENV_PATH
    with open(pushed, "w", encoding="utf-8") as fh:
        fh.write('MARKER="derived"\n')
    master = os.path.join(brand, "env.office")
    with open(master, "w", encoding="utf-8") as fh:
        fh.write('MARKER="master"\n')
    _stub_express_ok(boot, monkeypatch, [])

    boot.mod.run()

    assert not os.path.exists(pushed), "the derived push is consumed"
    assert os.path.exists(master), "the brand-root master must NEVER be deleted"


def test_iptv_staging_injected_for_brand_root_master(boot, monkeypatch):
    """A brand-root master finds the IPTV staging one level down under kodi/iptv/
    (the staging tree is _T7B/kodi/, not the brand root) and injects
    IPTV_STAGING_DIR — provisioner parity for the no-dot/brand-root placement."""
    brand, staging = _prod_layout(boot, monkeypatch)
    os.remove(boot.env_file)
    iptv_dir = os.path.join(staging, "iptv")
    os.makedirs(iptv_dir, exist_ok=True)
    # Staged artifacts landed (non-empty) — the provisioner-push signal.
    with open(os.path.join(iptv_dir, "instance-settings-1.xml"), "w") as fh:
        fh.write("<settings/>")
    with open(os.path.join(brand, "env.office"), "w", encoding="utf-8") as fh:
        fh.write('DEVICE_IP="1.2.3.4"\nMARKER="x"\n')
    calls = []
    _stub_express_ok(boot, monkeypatch, calls)

    boot.mod.run()

    assert calls and "DEVICE_IP" not in calls[0]
    assert calls[0]["IPTV_STAGING_DIR"] == iptv_dir


def test_empty_iptv_staging_dir_not_injected(boot, monkeypatch):
    """REGRESSION GUARD for the ensure_device_dirs interaction: onboarding
    self-creates an EMPTY iptv/ on every box, so derive_master_env must require
    NON-EMPTY content before injecting IPTV_STAGING_DIR. A DEVICE_IP-only master
    beside an empty iptv/ derives to {} -> the no-env class -> the wizard (NOT a
    false Express run)."""
    brand, _staging_dir = _prod_layout(boot, monkeypatch)
    os.remove(boot.env_file)
    with open(os.path.join(brand, "env.office"), "w", encoding="utf-8") as fh:
        fh.write('DEVICE_IP="1.2.3.4"\n')
    # ensure_device_dirs (run() runs it first) creates the empty kodi/iptv/.
    _forbid_express(boot, monkeypatch)
    calls = []
    _stub_guided(boot, monkeypatch, calls)

    boot.mod.run()  # must route the wizard, not Express

    assert calls == [{}]


def test_non_master_artifacts_at_brand_root_are_ignored(boot, monkeypatch):
    """Robustness: editor/build artifacts that happen to start 'env.'
    (env.bak, env.py, env.swp, the committed env.device.example) are NOT
    masters — they never route and never suppress the scaffold."""
    from tony7bones.setup import env as env_mod

    brand, _staging = _prod_layout(boot, monkeypatch)
    os.remove(boot.env_file)
    for junk in ("env.bak", "env.py", "env.swp", "env.device.example", "env", ".env"):
        with open(os.path.join(brand, junk), "w", encoding="utf-8") as fh:
            fh.write('MARKER="junk"\n')
    _stub_guided(boot, monkeypatch, [])

    boot.mod.run()

    # No artifact counted as a master, so the scaffold fired (env.device created).
    assert os.path.exists(os.path.join(brand, "env.device"))
    assert env_mod.master_env_paths(primary=boot.mod.BOX_ENV_PATH) == [
        os.path.join(brand, "env.device")
    ], "only the scaffolded master is recognised among the artifacts"


# --------------------------------------------------------------------------- #
# Onboarding self-creates the canonical _T7B/kodi/ staging tree
# (backups/ iptv/ media/ repositories/ rss/) — on EVERY entry path (Express AND
# Guided), EARLY (before config), idempotent, guarded, master never touched.
# --------------------------------------------------------------------------- #
def _five_subdirs():
    return ["backups", "iptv", "media", "repositories", "rss"]


def _spy_ensure(boot, monkeypatch):
    """Record every _ensure_device_dirs() call (the EARLY onboarding hook).
    Returns the call-list; delegates to the real function so dirs still land."""
    calls = []
    real = boot.mod._ensure_device_dirs

    def _spy():
        calls.append(True)
        return real()

    monkeypatch.setattr(boot.mod, "_ensure_device_dirs", _spy)
    return calls


def test_run_creates_device_tree_on_express(boot, monkeypatch):
    """The provisioned/Express route (env present, no SETUP_MODE) creates the
    canonical _T7B/kodi/{backups,iptv,media,repositories,rss} tree."""
    brand, staging = _prod_layout(boot, monkeypatch)
    # Production env at the pushed path so run() routes Express.
    with open(boot.mod.BOX_ENV_PATH, "w", encoding="utf-8") as fh:
        fh.write('MARKER="derived"\n')
    _stub_express_ok(boot, monkeypatch, [])

    boot.mod.run()

    for sub in _five_subdirs():
        assert os.path.isdir(os.path.join(staging, sub)), f"{sub} not created"
    assert os.path.isdir(brand)
    # No stray subdir (no scripts/).
    assert sorted(os.listdir(staging)) == _five_subdirs()


def test_run_creates_device_tree_on_guided(boot, monkeypatch):
    """The Guided route (SETUP_MODE=guided) ALSO creates the tree — onboarding
    self-creates it regardless of which orchestrator run() dispatches to."""
    brand, staging = _prod_layout(boot, monkeypatch)
    with open(boot.mod.BOX_ENV_PATH, "w", encoding="utf-8") as fh:
        fh.write('SETUP_MODE="guided"\nMARKER="m"\n')
    monkeypatch.setattr(boot.mod, "run_guided", lambda env=None: "exit")

    boot.mod.run()

    for sub in _five_subdirs():
        assert os.path.isdir(os.path.join(staging, sub)), f"{sub} not created"
    assert os.path.isdir(brand)


def test_run_creates_device_tree_on_no_env_wizard(boot, monkeypatch):
    """A no-env wizard box (the remote-only / no-computer launch) STILL gets its
    folders — it must run regardless of whether an env exists."""
    brand, staging = _prod_layout(boot, monkeypatch)
    os.remove(boot.env_file)  # no derived env
    monkeypatch.setattr(boot.mod, "run_guided", lambda env=None: "exit")

    boot.mod.run()

    for sub in _five_subdirs():
        assert os.path.isdir(os.path.join(staging, sub)), f"{sub} not created"


def test_ensure_device_dirs_fires_before_routing_on_both_paths(boot, monkeypatch):
    """MUTATION KILLER: _ensure_device_dirs() is called on the Express route AND
    the Guided route. Removing the run() call (or moving it behind the route
    branch) fails one of these. The spy delegates to the real function, so the
    dirs still land."""
    # Express route.
    _prod_layout(boot, monkeypatch)
    with open(boot.mod.BOX_ENV_PATH, "w", encoding="utf-8") as fh:
        fh.write('MARKER="derived"\n')
    _stub_express_ok(boot, monkeypatch, [])
    express_calls = _spy_ensure(boot, monkeypatch)
    boot.mod.run()
    assert express_calls == [True], "onboarding must create dirs on the Express route"

    # Guided route (fresh spy + env).
    with open(boot.mod.BOX_ENV_PATH, "w", encoding="utf-8") as fh:
        fh.write('SETUP_MODE="guided"\nMARKER="m"\n')
    monkeypatch.setattr(boot.mod, "run_guided", lambda env=None: "exit")
    guided_calls = _spy_ensure(boot, monkeypatch)
    boot.mod.run()
    assert guided_calls == [True], "onboarding must create dirs on the Guided route"


def test_run_device_tree_guarded_on_desktop(boot, monkeypatch):
    """Off-device / read-only fs: makedirs raises -> run() must NOT abort. The
    box still routes Express normally; the guarded failure is swallowed."""
    _prod_layout(boot, monkeypatch)
    with open(boot.mod.BOX_ENV_PATH, "w", encoding="utf-8") as fh:
        fh.write('MARKER="derived"\n')
    _stub_express_ok(boot, monkeypatch, [])

    from tony7bones.setup import env as env_mod

    real_makedirs = env_mod._os.makedirs

    def _boom(path, exist_ok=False):
        # Only the device-tree creates explode; everything else (the rest of the
        # fake-Kodi flow) keeps working so run() reaches its route.
        if "_T7B" in path:
            raise OSError("read-only filesystem")
        return real_makedirs(path, exist_ok=exist_ok)

    monkeypatch.setattr(env_mod._os, "makedirs", _boom)

    boot.mod.run()  # must not raise


def test_run_device_tree_never_touches_master(boot, monkeypatch):
    """Onboarding's dir-create never creates/deletes/overwrites the master
    .env.<device> at the brand root."""
    brand, staging = _prod_layout(boot, monkeypatch)
    os.remove(boot.env_file)
    master = os.path.join(brand, "env.office")
    sentinel = 'MARKER="master"\n'
    with open(master, "w", encoding="utf-8") as fh:
        fh.write(sentinel)
    _stub_express_ok(boot, monkeypatch, [])

    boot.mod.run()

    assert os.path.exists(master), "the master must survive onboarding"
    assert open(master, encoding="utf-8").read() == sentinel


def test_bootstrap_reexports_device_subdirs_constant(boot):
    """default.py re-exports the SAME constant object (single source of truth)."""
    from tony7bones.setup import env as env_mod

    assert boot.mod.DEVICE_STAGING_SUBDIRS is env_mod.DEVICE_STAGING_SUBDIRS


def test_is_master_env_filename_dot_optional_and_denylist():
    """The dot-optional matcher unit: env.<x> and .env.<x> match; bare env/.env
    and the artifact suffixes do not."""
    from tony7bones.setup import env as env_mod

    f = env_mod.is_master_env_filename
    assert f("env.office") and f(".env.office")
    assert f("env.travelstick-2") and f(".env.travel-stick")
    assert not f("env") and not f(".env")
    assert not f("env.device.example") and not f(".env.device.example")
    for suffix in (".bak", ".py", ".pyc", ".swp", ".orig", ".tmp", ".old", "~"):
        assert not f("env" + suffix), suffix
    assert not f("tony7bones.env") and not f("notes.txt")
