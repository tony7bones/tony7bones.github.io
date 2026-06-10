"""Tests for the bootstrap <-> shared-library compatibility guard (Phase 6).

A too-old ``script.module.tony7bones`` paired with a too-new
``script.tony7bones.bootstrap`` (a cross-gate update skew, or a sideload that
bypassed Kodi's ``<requires>`` check — our own direct-extract path does exactly
that) must fail LOUD AND HONEST: one "update the library from the repository"
dialog + an ERROR log + a raise — never a cryptic ImportError/AttributeError
deep inside a gate.

The guard (``_require_setup_library`` in the bootstrap ``default.py``) runs at
import, BEFORE the real library imports. The library declares the capability
level it ships (``tony7bones.setup.SETUP_API``); the bootstrap declares the
level it needs (``REQUIRED_SETUP_API``). These tests re-exec ``default.py``
under the ``boot`` fixture's fake Kodi with a sabotaged library to prove both
failure shapes (level too low / setup modules missing outright) and pin that
the SHIPPED pairing is compatible.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).parent
REPO_ROOT = HERE.parent
DEFAULT_PY = REPO_ROOT / "addons" / "script.tony7bones.bootstrap" / "default.py"


def _exec_default():
    spec = importlib.util.spec_from_file_location("boot_default_guard", DEFAULT_PY)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _guard_dialogs(boot):
    """The honest 'update the library' dialogs the fake Dialog.ok recorded."""
    return [(t, m) for t, m in boot.state["ok"] if "script.module.tony7bones" in m]


def test_shipped_pairing_is_compatible(boot):
    """The repo's own library must satisfy the repo's own bootstrap — the guard
    passes silently on the shipped pairing (the whole suite rides on this, but
    pin it explicitly so a REQUIRED_SETUP_API bump without the matching library
    SETUP_API bump fails HERE, not on a box)."""
    import tony7bones.setup as setup_pkg

    assert setup_pkg.SETUP_API >= boot.mod.REQUIRED_SETUP_API
    # And the guard itself returns silently (no dialog, no raise).
    boot.mod._require_setup_library()
    assert _guard_dialogs(boot) == []


def test_too_old_library_api_fails_loud(boot, monkeypatch):
    """Library present but its SETUP_API is below the bootstrap's requirement:
    one honest dialog + RuntimeError. MUTATION: removing the api comparison (or
    the raise) fails here."""
    import tony7bones.setup as setup_pkg

    monkeypatch.setattr(setup_pkg, "SETUP_API", 0, raising=False)
    with pytest.raises(RuntimeError) as e:
        _exec_default()
    assert "script.module.tony7bones" in str(e.value)
    assert "SETUP_API 0 < required" in str(e.value)
    dialogs = _guard_dialogs(boot)
    assert dialogs, "the user must be told to update the library"
    assert any("repository" in m for _t, m in dialogs)


def test_genuinely_old_library_missing_setup_modules_fails_loud(boot, monkeypatch):
    """A genuinely old library has no setup modules at all — the guard's probe
    import fails and the SAME honest dialog + RuntimeError fires (never a raw
    ImportError traceback as the only signal)."""

    class _Block:
        def find_spec(self, name, path=None, target=None):
            if name == "tony7bones.setup.probes":
                raise ImportError("blocked: simulated pre-setup library")
            return None

    monkeypatch.delitem(sys.modules, "tony7bones.setup.probes", raising=False)
    sys.meta_path.insert(0, blocker := _Block())
    try:
        with pytest.raises(RuntimeError) as e:
            _exec_default()
    finally:
        sys.meta_path.remove(blocker)
    assert "library import failed" in str(e.value)
    assert _guard_dialogs(boot), "the user must be told to update the library"


def test_guard_runs_before_the_real_imports(boot):
    """The guard must fire BEFORE the bootstrap's real library imports, so the
    user sees the honest dialog instead of whatever import crashes first. Pin
    the order structurally: the guard call appears before the first
    ``from tony7bones import`` in the source."""
    src = DEFAULT_PY.read_text()
    assert src.index("_require_setup_library()") < src.index(
        "from tony7bones import ("
    ), "the compat guard must run before the real library imports"


def test_guard_dialog_failure_does_not_mask_the_error(boot, monkeypatch):
    """A broken Dialog must not swallow the incompatibility — the raise still
    happens (the dialog is best-effort, the RuntimeError is the contract)."""
    import tony7bones.setup as setup_pkg

    monkeypatch.setattr(setup_pkg, "SETUP_API", 0, raising=False)

    def _boom(self, *a, **k):
        raise RuntimeError("dialog broken")

    monkeypatch.setattr(boot.mod.xbmcgui.Dialog, "ok", _boom)
    with pytest.raises(RuntimeError) as e:
        _exec_default()
    assert "script.module.tony7bones" in str(e.value)
