"""Unit tests for the new tony7bones.setup sublibrary (Phase 2a scaffolding).

Covers the three primitives created in Phase 2a:

* ``LayerResult`` — defaults, field semantics, and the log-friendly ``__repr__``.
* ``KodiHost`` / ``RealKodiHost`` — the port wrapping the ``xbmc*`` calls the new
  setup code uses. Delegation is verified by injecting a fake ``xbmc`` /
  ``xbmcvfs`` (NOT by patching the real Kodi), and a ``FakeKodiHost`` demonstrates
  the constructor-injection substitution the orchestrator relies on.
* ``env`` — ``parse_env`` / ``read_box_env`` / ``split_list`` moved here verbatim
  from the bootstrap; the same cases the bootstrap suite pinned, exercised against
  the sublibrary directly (no Kodi mocks needed — pure Python).

These modules are pure Python (no top-level Kodi imports), so the sublibrary is
imported straight off ``lib/`` with no ``sys.modules`` monkeypatching; the fake
Kodi modules are injected ONLY for the RealKodiHost delegation tests.
"""

from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

HERE = Path(__file__).parent
REPO_ROOT = HERE.parent
LIB = REPO_ROOT / "addons" / "script.module.tony7bones" / "lib"


@pytest.fixture
def setup_pkg(monkeypatch):
    """Import ``tony7bones.setup`` straight off lib/, purging any cached copy so
    each test binds fresh.

    The sublibrary imports cleanly WITHOUT a running Kodi: ``result``/``env``/
    ``host`` have no Kodi deps (RealKodiHost imports xbmc lazily, inside its
    methods), AND the parent ``tony7bones/__init__.py`` now binds its
    Kodi-dependent engine lazily (PEP 562 ``__getattr__``), so importing the
    package no longer drags in ``import xbmc``. We still register a lightweight
    namespace ``tony7bones`` package (``__path__`` -> the real lib dir) purely to
    purge-and-rebind a clean copy per test and to keep this file independent of
    whatever engine state another test left in ``sys.modules`` — it is no longer
    REQUIRED to dodge the engine import, which is the isolation Phase 2a now
    actually delivers (see ``test_setup_host_imports_without_xbmc``)."""
    monkeypatch.syspath_prepend(str(LIB))
    for name in list(sys.modules):
        if name == "tony7bones" or name.startswith("tony7bones."):
            monkeypatch.delitem(sys.modules, name, raising=False)
    pkg = types.ModuleType("tony7bones")
    pkg.__path__ = [str(LIB / "tony7bones")]
    monkeypatch.setitem(sys.modules, "tony7bones", pkg)
    import tony7bones.setup as setup

    return setup


# --------------------------------------------------------------------------- #
# Package surface
# --------------------------------------------------------------------------- #
def test_package_reexports_public_names(setup_pkg):
    for name in (
        "LayerResult",
        "KodiHost",
        "RealKodiHost",
        "parse_env",
        "read_box_env",
        "split_list",
    ):
        assert hasattr(setup_pkg, name), f"setup must re-export {name}"


# --------------------------------------------------------------------------- #
# LayerResult — defaults, field semantics, repr
# --------------------------------------------------------------------------- #
def test_layerresult_defaults(setup_pkg):
    from tony7bones.setup.result import LayerResult

    r = LayerResult(layer="foundation", ok=True)
    assert r.layer == "foundation"
    assert r.ok is True
    # Every optional field has a sensible default.
    assert r.already_done is False
    assert r.installed == {}
    assert r.failed == {}
    assert r.needs_skin_activation is False
    assert r.needs_restart is False
    assert r.detail == ""


def test_layerresult_default_dicts_are_independent(setup_pkg):
    """The dict defaults must not be a shared mutable (the dataclass field
    factory) — two results must not alias the same installed/failed dict."""
    from tony7bones.setup.result import LayerResult

    a = LayerResult(layer="iptv", ok=True)
    b = LayerResult(layer="addons", ok=True)
    a.installed["pvr.iptvsimple"] = "enabled"
    a.failed["x"] = "boom"
    assert b.installed == {}
    assert b.failed == {}


def test_layerresult_fields_settable(setup_pkg):
    from tony7bones.setup.result import LayerResult

    r = LayerResult(
        layer="foundation",
        ok=True,
        already_done=False,
        installed={"skin.estuary.modv2": "enabled"},
        failed={"script.module.pvr.artwork": "404"},
        needs_skin_activation=True,
        needs_restart=True,
        detail="foundation staged",
    )
    assert r.installed == {"skin.estuary.modv2": "enabled"}
    assert r.failed == {"script.module.pvr.artwork": "404"}
    assert r.needs_skin_activation is True
    assert r.needs_restart is True
    assert r.detail == "foundation staged"


def test_layerresult_repr_ok_with_flags(setup_pkg):
    from tony7bones.setup.result import LayerResult

    r = LayerResult(
        layer="foundation",
        ok=True,
        installed={"a": "enabled", "b": "enabled"},
        needs_skin_activation=True,
        needs_restart=True,
        detail="staged",
    )
    text = repr(r)
    assert "foundation" in text
    assert "ok" in text
    assert "needs_skin_activation" in text
    assert "needs_restart" in text
    assert "installed=2" in text
    assert "failed=0" in text
    assert "staged" in text


def test_layerresult_repr_failed_minimal(setup_pkg):
    from tony7bones.setup.result import LayerResult

    r = LayerResult(layer="addons", ok=False, failed={"plugin.video.pov": "no zip"})
    text = repr(r)
    assert "addons" in text
    assert "FAILED" in text
    # No flags / no detail when none are set.
    assert "needs_skin_activation" not in text
    assert "needs_restart" not in text
    assert "detail=" not in text
    assert "failed=1" in text


def test_layerresult_repr_already_done(setup_pkg):
    from tony7bones.setup.result import LayerResult

    r = LayerResult(layer="iptv", ok=True, already_done=True)
    assert "already_done" in repr(r)


def test_layers_constant(setup_pkg):
    from tony7bones.setup.result import LAYERS

    assert LAYERS == ("foundation", "backup", "iptv", "skin", "addons")


# --------------------------------------------------------------------------- #
# KodiHost / RealKodiHost — delegation verified via a fake xbmc / xbmcvfs
# --------------------------------------------------------------------------- #
def _fake_kodi(monkeypatch, state):
    """Install minimal fake xbmc / xbmcgui / xbmcvfs modules that record calls
    into ``state``, so RealKodiHost's lazy imports resolve to them."""
    xbmc = types.ModuleType("xbmc")
    xbmc.LOGINFO = 1
    xbmc.LOGWARNING = 2
    xbmc.LOGERROR = 4
    xbmc.log = lambda msg, level=1: state["log"].append((msg, level))
    xbmc.sleep = lambda ms: state["sleep"].append(ms)
    xbmc.getCondVisibility = lambda cond: state["condvis"].setdefault(cond, True)
    xbmc.executeJSONRPC = lambda req: state["jsonrpc"].append(req) or '{"ok":1}'
    xbmc.executebuiltin = lambda cmd: state["builtins"].append(cmd)
    xbmc.getSkinDir = lambda: state["skin"]

    xbmcvfs = types.ModuleType("xbmcvfs")
    xbmcvfs.translatePath = lambda p: state["translate"].append(p) or ("/abs" + p)
    xbmcvfs.exists = lambda p: state["exists"].append(p) or True
    xbmcvfs.mkdirs = lambda p: state["mkdirs"].append(p) or True
    xbmcvfs.copy = lambda s, d: state["copy"].append((s, d)) or True

    xbmcgui = types.ModuleType("xbmcgui")

    for nm, mod in (("xbmc", xbmc), ("xbmcvfs", xbmcvfs), ("xbmcgui", xbmcgui)):
        monkeypatch.setitem(sys.modules, nm, mod)


@pytest.fixture
def real_host(setup_pkg, monkeypatch):
    state = {
        "log": [],
        "sleep": [],
        "condvis": {},
        "jsonrpc": [],
        "builtins": [],
        "skin": "skin.estuary.modv2",
        "translate": [],
        "exists": [],
        "mkdirs": [],
        "copy": [],
    }
    _fake_kodi(monkeypatch, state)
    from tony7bones.setup.host import RealKodiHost

    return RealKodiHost(), state


def test_realhost_log_delegates(real_host):
    host, state = real_host
    host.log("hello", host.LOGERROR)
    assert state["log"] == [("hello", host.LOGERROR)]


def test_realhost_log_default_level_is_loginfo(real_host):
    host, state = real_host
    host.log("info-line")
    # Default maps to xbmc.LOGINFO (1) resolved lazily from the fake xbmc.
    assert state["log"] == [("info-line", 1)]


def test_realhost_sleep_delegates(real_host):
    host, state = real_host
    host.sleep(250)
    assert state["sleep"] == [250]


def test_realhost_cond_visibility_delegates(real_host):
    host, state = real_host
    assert host.get_cond_visibility("Window.IsVisible(10100)") is True
    assert "Window.IsVisible(10100)" in state["condvis"]


def test_realhost_jsonrpc_delegates_and_returns(real_host):
    host, state = real_host
    resp = host.execute_jsonrpc('{"method":"Foo"}')
    assert resp == '{"ok":1}'
    assert state["jsonrpc"] == ['{"method":"Foo"}']


def test_realhost_builtin_delegates(real_host):
    host, state = real_host
    host.execute_builtin("SendClick(11)")
    assert state["builtins"] == ["SendClick(11)"]


def test_realhost_translate_path_delegates(real_host):
    host, state = real_host
    assert host.translate_path("special://home/") == "/absspecial://home/"
    assert state["translate"] == ["special://home/"]


def test_realhost_get_skin_dir_delegates(real_host):
    host, state = real_host
    state["skin"] = "skin.estuary"
    assert host.get_skin_dir() == "skin.estuary"


def test_realhost_exists_delegates(real_host):
    host, state = real_host
    assert host.exists("/x") is True
    assert state["exists"] == ["/x"]


def test_realhost_mkdirs_delegates(real_host):
    host, state = real_host
    assert host.mkdirs("/x/y") is True
    assert state["mkdirs"] == ["/x/y"]


def test_realhost_copy_delegates(real_host):
    host, state = real_host
    assert host.copy("/a", "/b") is True
    assert state["copy"] == [("/a", "/b")]


def test_kodihost_level_constants(setup_pkg):
    """The level constants are available on the port without a running Kodi, so
    callers can pass host.LOGERROR etc. before any xbmc import happens."""
    from tony7bones.setup.host import KodiHost, RealKodiHost

    assert KodiHost.LOGINFO == 1
    assert KodiHost.LOGWARNING == 2
    assert KodiHost.LOGERROR == 4
    # RealKodiHost inherits them.
    assert RealKodiHost.LOGERROR == 4


def test_kodihost_abstract_methods_raise(setup_pkg):
    """The base port is an interface: every method raises NotImplementedError so
    an incomplete fake fails loudly instead of silently returning None."""
    from tony7bones.setup.host import KodiHost

    h = KodiHost()
    methods = [
        ("log", ("m",)),
        ("sleep", (1,)),
        ("get_cond_visibility", ("c",)),
        ("execute_jsonrpc", ("r",)),
        ("execute_builtin", ("b",)),
        ("translate_path", ("p",)),
        ("get_skin_dir", ()),
        ("exists", ("p",)),
        ("mkdirs", ("p",)),
        ("copy", ("a", "b")),
    ]
    for name, args in methods:
        with pytest.raises(NotImplementedError):
            getattr(h, name)(*args)


def test_setup_host_imports_without_xbmc(monkeypatch):
    """The port's real value: ``import tony7bones.setup.host`` resolves OFF-box
    with NO ``xbmc`` available, because the parent package binds its engine
    lazily (PEP 562). We block ``xbmc*`` at the meta-path AND purge the package,
    then import the host module from a clean interpreter state — it must succeed.

    This is the meaningful assertion that replaces the old vacuous
    ``"xbmc" not in sys.modules or ... is not None`` tautology."""
    monkeypatch.syspath_prepend(str(LIB))
    for name in list(sys.modules):
        if name == "tony7bones" or name.startswith("tony7bones."):
            monkeypatch.delitem(sys.modules, name, raising=False)
    for name in ("xbmc", "xbmcgui", "xbmcvfs", "xbmcaddon"):
        monkeypatch.delitem(sys.modules, name, raising=False)

    class _BlockKodi:
        def find_spec(self, name, path=None, target=None):
            if name in ("xbmc", "xbmcgui", "xbmcvfs", "xbmcaddon"):
                raise ModuleNotFoundError(f"blocked: {name}")
            return None

    monkeypatch.setattr(sys, "meta_path", [_BlockKodi(), *sys.meta_path])

    import importlib

    host = importlib.import_module("tony7bones.setup.host")
    # The module + its classes are usable with no xbmc on the system.
    assert host.RealKodiHost is not None
    assert host.KodiHost.LOGERROR == 4
    # Importing the parent package itself also stays xbmc-free...
    pkg = importlib.import_module("tony7bones")
    # ...until an ENGINE name is touched, which lazily pulls Kodi and now fails.
    with pytest.raises(ModuleNotFoundError):
        pkg.install_selection  # noqa: B018 — attribute access triggers the import


# --------------------------------------------------------------------------- #
# FakeKodiHost — demonstrates plain constructor injection (the whole point of the
# port: new code gets a fake without sys.modules monkeypatching).
# --------------------------------------------------------------------------- #
def test_fake_host_injection_no_sysmodules(setup_pkg):
    """A fake host is just an object passed to the consumer — no xbmc in
    sys.modules required. Subclass RealKodiHost and override only what's used."""
    from tony7bones.setup.host import KodiHost, RealKodiHost

    class FakeKodiHost(RealKodiHost):
        def __init__(self):
            self.calls = []

        def log(self, msg, level=KodiHost.LOGINFO):
            self.calls.append(("log", msg, level))

        def get_skin_dir(self):
            return "skin.estuary.modv2"

    def consumer(host):
        """Stand-in for the future orchestrator: depends only on the port."""
        host.log("starting", host.LOGINFO)
        return host.get_skin_dir()

    fake = FakeKodiHost()
    assert consumer(fake) == "skin.estuary.modv2"
    assert fake.calls == [("log", "starting", KodiHost.LOGINFO)]


def test_fake_host_ducktype(setup_pkg):
    """A fake need not subclass — duck-typing the port works just as well."""

    class DuckHost:
        LOGINFO = 1

        def __init__(self):
            self.slept = []

        def sleep(self, ms):
            self.slept.append(ms)

    d = DuckHost()
    d.sleep(500)
    assert d.slept == [500]


# --------------------------------------------------------------------------- #
# env — parse_env / split_list / read_box_env (verbatim move; pinned here too)
# --------------------------------------------------------------------------- #
def test_parse_env_basic_quotes_and_empty(setup_pkg):
    from tony7bones.setup.env import parse_env

    env = parse_env('DEVICE_NAME="Bedroom TV"\nIPTV_NAME=Network 24\nEMPTY=\n')
    assert env["DEVICE_NAME"] == "Bedroom TV"  # surrounding quotes stripped
    assert env["IPTV_NAME"] == "Network 24"  # unquoted value with a space
    assert env["EMPTY"] == ""  # empty value preserved


def test_parse_env_inline_comment_only_when_unquoted(setup_pkg):
    from tony7bones.setup.env import parse_env

    env = parse_env(
        'KEY="8090329db7d84dae"   # forecast key\nBARE=value   # note\nHASH="a#b"\n'
    )
    assert env["KEY"] == "8090329db7d84dae"  # inline comment dropped
    assert env["BARE"] == "value"  # unquoted inline comment dropped
    assert env["HASH"] == "a#b"  # '#' inside quotes is kept


def test_parse_env_single_quoted_value(setup_pkg):
    from tony7bones.setup.env import parse_env

    env = parse_env("NAME='Office TV'  # label\n")
    assert env["NAME"] == "Office TV"  # single-quoted body, inline comment dropped


def test_parse_env_skips_comments_blanks_and_no_equals(setup_pkg):
    from tony7bones.setup.env import parse_env

    env = parse_env("# comment\n\n   \nnot_a_setting\nOK=1\n")
    assert env == {"OK": "1"}


def test_parse_env_skips_commented_out_setting(setup_pkg):
    """A FULL-LINE comment that itself looks like a KEY=value must be dropped by
    the ``line.startswith("#")`` guard — NOT parsed into the dict. The earlier
    "no '=' -> skip" cases can't prove this guard (those lines have no '='); a
    ``# KEY=value`` line DOES contain '=', so only the '#' guard catches it.
    Mutation check: delete that guard in env.py and this test must fail."""
    from tony7bones.setup.env import parse_env

    assert parse_env("# OWM_KEY=secret\nWEATHER_PROVIDER=weatherbit\n") == {
        "WEATHER_PROVIDER": "weatherbit"
    }


def test_parse_env_keeps_semicolons_in_value(setup_pkg):
    from tony7bones.setup.env import parse_env, split_list

    env = parse_env('M3U="http://h/get?a=1&b=2"\nLIST="x; y; z"\n')
    assert env["M3U"] == "http://h/get?a=1&b=2"
    assert env["LIST"] == "x; y; z"  # parse_env never splits
    assert split_list(env["LIST"]) == ["x", "y", "z"]  # split_list does


def test_parse_env_handles_crlf(setup_pkg):
    from tony7bones.setup.env import parse_env

    assert parse_env('A="x"\r\nB="y"\r\n') == {"A": "x", "B": "y"}


def test_parse_env_empty_key_skipped(setup_pkg):
    from tony7bones.setup.env import parse_env

    # A line that is just "=value" has an empty key after strip — skipped.
    assert parse_env("=orphan\nOK=1\n") == {"OK": "1"}


def test_split_list_trims_and_drops_empties(setup_pkg):
    from tony7bones.setup.env import split_list

    assert split_list("Sacramento, CA; Yuba City, CA ;; Reno, NV ") == [
        "Sacramento, CA",
        "Yuba City, CA",
        "Reno, NV",
    ]
    assert split_list("") == []
    assert split_list(None) == []


def test_split_list_custom_separator(setup_pkg):
    from tony7bones.setup.env import split_list

    assert split_list("a,b , c", sep=",") == ["a", "b", "c"]


def test_read_box_env_absent_returns_empty(setup_pkg, tmp_path):
    from tony7bones.setup.env import read_box_env

    assert read_box_env(str(tmp_path / "nope.env")) == {}


def test_read_box_env_reads_file(setup_pkg, tmp_path):
    from tony7bones.setup.env import read_box_env, split_list

    p = tmp_path / "tony7bones.env"
    p.write_text('DEVICE_NAME="Office"\nWEATHER_LOCATIONS="A; B"\n')
    env = read_box_env(str(p))
    assert env["DEVICE_NAME"] == "Office"
    assert split_list(env["WEATHER_LOCATIONS"]) == ["A", "B"]


# --------------------------------------------------------------------------- #
# ensure_device_dirs — onboarding self-creates the canonical _T7B/kodi/ tree
# (backups/ iptv/ media/ repositories/ rss/). Pure-library, guarded, idempotent.
# --------------------------------------------------------------------------- #
def _staging_primary(tmp_path):
    """A production-shaped primary (…/_T7B/kodi/tony7bones.env) so brand_root
    resolves to the _T7B parent and staging_dir to the kodi/ child — the real
    two-level layout, NOT a flat tmp dir."""
    import os

    staging = tmp_path / "_T7B" / "kodi"
    return os.path.join(str(staging), "tony7bones.env")


def test_ensure_device_dirs_canonical_subdirs_constant(setup_pkg):
    """The single source of truth is exactly the five canonical subdirs
    (docs/directory_structure.txt) — in order, no scripts/, no EM+."""
    from tony7bones.setup import env as env_mod

    assert env_mod.DEVICE_STAGING_SUBDIRS == (
        "backups",
        "iptv",
        "media",
        "repositories",
        "rss",
    )


def test_ensure_device_dirs_creates_roots_and_five_subdirs(setup_pkg, tmp_path):
    """From a clean slate: creates the BRAND ROOT, the DEVICE_ROOT staging tree,
    and each of the five subdirs — and returns exactly those paths created."""
    import os

    from tony7bones.setup import env as env_mod

    primary = _staging_primary(tmp_path)
    brand = env_mod.brand_root(primary)
    staging = env_mod.staging_dir(primary)
    assert not os.path.isdir(brand)  # nothing exists yet

    created = env_mod.ensure_device_dirs(primary=primary)

    assert os.path.isdir(brand)
    assert os.path.isdir(staging)
    for sub in ("backups", "iptv", "media", "repositories", "rss"):
        assert os.path.isdir(os.path.join(staging, sub)), f"{sub} not created"
    # EXACTLY the five subdirs + the two roots — no extras (no scripts/).
    assert set(created) == {brand, staging} | {
        os.path.join(staging, s) for s in env_mod.DEVICE_STAGING_SUBDIRS
    }
    # No stray dirs in staging.
    assert sorted(os.listdir(staging)) == [
        "backups",
        "iptv",
        "media",
        "repositories",
        "rss",
    ]


def test_ensure_device_dirs_idempotent_noop_when_present(setup_pkg, tmp_path):
    """A second call on an already-complete tree creates NOTHING (clean no-op)."""
    from tony7bones.setup import env as env_mod

    primary = _staging_primary(tmp_path)
    first = env_mod.ensure_device_dirs(primary=primary)
    assert first  # first call created the tree

    again = env_mod.ensure_device_dirs(primary=primary)

    assert again == [], "an already-provisioned box is a clean no-op"


def test_ensure_device_dirs_creates_only_the_missing(setup_pkg, tmp_path):
    """Partial tree: only the missing subdirs are created (not the ones that
    already exist) — proves the per-dir isdir() short-circuit."""
    import os

    from tony7bones.setup import env as env_mod

    primary = _staging_primary(tmp_path)
    staging = env_mod.staging_dir(primary)
    # Pre-create the staging root + iptv/ only.
    os.makedirs(os.path.join(staging, "iptv"), exist_ok=True)

    created = env_mod.ensure_device_dirs(primary=primary)

    assert os.path.join(staging, "iptv") not in created
    assert os.path.join(staging, "rss") in created
    assert staging not in created  # already existed


def test_ensure_device_dirs_guarded_when_makedirs_raises(
    setup_pkg, tmp_path, monkeypatch
):
    """A failing filesystem (read-only / off-Kodi where /storage can't exist):
    makedirs raises -> logged + swallowed, returns [], NEVER raises."""

    from tony7bones.setup import env as env_mod

    def _boom(path, exist_ok=False):
        raise OSError("read-only filesystem")

    monkeypatch.setattr(env_mod._os, "makedirs", _boom)
    logged = []

    created = env_mod.ensure_device_dirs(
        primary=_staging_primary(tmp_path), log=logged.append
    )

    assert created == []
    assert logged, "the guarded failure must be logged"
    assert any("skipped" in m for m in logged)


def test_ensure_device_dirs_never_touches_master_env(setup_pkg, tmp_path):
    """The master .env.<device> at the brand root is NEVER created, deleted, or
    overwritten by ensure_device_dirs — the scaffold owns the master."""
    import os

    from tony7bones.setup import env as env_mod

    primary = _staging_primary(tmp_path)
    brand = env_mod.brand_root(primary)
    os.makedirs(brand, exist_ok=True)
    master = os.path.join(brand, "env.office")
    sentinel = "WEATHER_LOCATIONS=Sacramento\n"
    with open(master, "w", encoding="utf-8") as fh:
        fh.write(sentinel)

    env_mod.ensure_device_dirs(primary=primary)

    assert os.path.isfile(master), "the master must survive"
    assert open(master, encoding="utf-8").read() == sentinel, "master untouched"
    # And the function added zero master-like files anywhere.
    assert env_mod.master_env_paths(primary) == [master]


def test_derive_master_env_empty_iptv_dir_not_injected(setup_pkg, tmp_path):
    """The ensure_device_dirs interaction: an EMPTY iptv/ (onboarding creates
    one on every box) must NOT inject IPTV_STAGING_DIR — only a NON-EMPTY iptv/
    (real staged artifacts) does. Guards against a DEVICE_IP-only master falsely
    looking configured."""
    import os

    from tony7bones.setup import env as env_mod

    master = str(tmp_path / "env.office")
    empty_iptv = tmp_path / "iptv"
    empty_iptv.mkdir()

    # Empty iptv/ -> no injection.
    env = env_mod.derive_master_env({"MARKER": "x"}, master)
    assert "IPTV_STAGING_DIR" not in env

    # Now drop a staged artifact in -> injection.
    (empty_iptv / "instance-settings-1.xml").write_text("<settings/>")
    env2 = env_mod.derive_master_env({"MARKER": "x"}, master)
    assert env2["IPTV_STAGING_DIR"] == os.path.join(str(tmp_path), "iptv")


def test_dir_has_content_guarded_on_oserror(setup_pkg, monkeypatch, tmp_path):
    """_dir_has_content swallows an OSError from listdir (a vanished/unreadable
    dir) and returns False — so a transient fs error never injects staging."""
    import os

    from tony7bones.setup import env as env_mod

    d = tmp_path / "iptv"
    d.mkdir()

    def _boom(p):
        raise OSError("gone")

    monkeypatch.setattr(env_mod._os, "listdir", _boom)
    assert env_mod._dir_has_content(str(d)) is False
    # Absent dir is also False (no isdir).
    assert env_mod._dir_has_content(str(tmp_path / "nope")) is False
    assert os  # keep import referenced


def test_ensure_device_dirs_logs_created_summary(setup_pkg, tmp_path):
    """When dirs are created, ONE honest summary line is logged listing them."""
    from tony7bones.setup import env as env_mod

    logged = []
    env_mod.ensure_device_dirs(primary=_staging_primary(tmp_path), log=logged.append)

    assert any("device tree ensured" in m for m in logged)


# --------------------------------------------------------------------------- #
# Relocation contract — the bootstrap still exposes the SAME callables, and they
# are the very objects from the sublibrary (re-export, not a copy).
# --------------------------------------------------------------------------- #
def test_bootstrap_reexports_are_the_sublibrary_objects(boot):
    """default.py must re-export the sublibrary functions (same identity), so
    every existing reference / test that reaches them via the bootstrap module
    (``boot.mod.parse_env`` / ``read_box_env`` / ``split_list``) keeps working
    unchanged. Uses the shared ``boot`` fixture (conftest) — the same way the
    bootstrap suite imports default.py with the full engine on path."""
    from tony7bones.setup import env as env_mod

    assert boot.mod.parse_env is env_mod.parse_env
    assert boot.mod.read_box_env is env_mod.read_box_env
    assert boot.mod.split_list is env_mod.split_list
