"""Coverage for script.ezmaintenanceplusplus's ui.py copy-size-settle fix.

A large NFS write can complete (every fdst.write() returns True, close()
raises nothing) before the server has actually committed the bytes - an
immediate xbmcvfs.Stat right after close() can still read a stale, pre-write
size. Live-observed: a real 142 MB backup copy reported "size mismatch
(0 != 142380074)" on all 3 attempts, each completing in ~130ms (far too fast
to be a genuine failed 142 MB transfer), with no write ever refused and no
exception raised - the write succeeded, the immediate size check just read
stale server-side metadata.

This file builds a minimal fake xbmc/xbmcaddon/xbmcgui/xbmcvfs (ui.py's own
docstring: "Imports ONLY xbmc / xbmcaddon / xbmcgui / xbmcvfs, so it is fully
unit-testable off-device") to exercise the real _copy_once/copy_with_progress
code, not a reimplementation of it.
"""

from __future__ import annotations

import importlib
import sys
import types
from pathlib import Path

import pytest

HERE = Path(__file__).parent
REPO_ROOT = HERE.parent
ADDON_ROOT = REPO_ROOT / "addons" / "script.ezmaintenanceplusplus"


@pytest.fixture
def ui(monkeypatch, tmp_path):
    monkeypatch.syspath_prepend(str(ADDON_ROOT))
    for name in list(sys.modules):
        if name == "resources" or name.startswith("resources."):
            monkeypatch.delitem(sys.modules, name, raising=False)

    sleeps = []
    logs = []
    fake_xbmc = types.SimpleNamespace(
        log=lambda msg, level=None: logs.append(msg),
        sleep=lambda ms: sleeps.append(ms),
        LOGERROR=1,
        LOGWARNING=2,
        LOGINFO=3,
        LOGDEBUG=4,
        LOGFATAL=0,
        LOGNONE=5,
    )
    fake_xbmcaddon = types.SimpleNamespace(
        Addon=lambda: types.SimpleNamespace(
            getAddonInfo=lambda key: "EZ Maintenance++" if key == "name" else ""
        )
    )
    fake_xbmcgui = types.SimpleNamespace(
        Dialog=lambda: types.SimpleNamespace(
            yesno=lambda *a, **k: False, ok=lambda *a, **k: None
        ),
        DialogProgress=lambda: types.SimpleNamespace(
            create=lambda *a, **k: None,
            update=lambda *a, **k: None,
            close=lambda: None,
            iscanceled=lambda: False,
        ),
    )

    monkeypatch.setitem(sys.modules, "xbmc", fake_xbmc)
    monkeypatch.setitem(sys.modules, "xbmcaddon", fake_xbmcaddon)
    monkeypatch.setitem(sys.modules, "xbmcgui", fake_xbmcgui)
    # A bare placeholder so `import xbmcvfs` succeeds; each test then replaces
    # it (both in sys.modules and on the imported ui module directly) with a
    # File/Stat/etc. fake tailored to what it's exercising.
    monkeypatch.setitem(sys.modules, "xbmcvfs", types.SimpleNamespace())

    mod = importlib.import_module("resources.lib.modules.ui")
    mod._TEST_SLEEPS = sleeps
    mod._TEST_LOGS = logs
    return mod


class _FakeFile:
    """A minimal xbmcvfs.File stand-in backed by an in-memory byte buffer.

    `broken_read_paths` simulates the live tvOS bug: File(path, "r").readBytes()
    returns empty on every call for a path, even though the store (and therefore
    Stat() and the native copy() fallback) hold the real, correctly-sized data.
    """

    def __init__(self, data_store, path, mode, broken_read_paths=frozenset()):
        self._store = data_store
        self._path = path
        self._mode = mode
        self._pos = 0
        self._broken = path in broken_read_paths

    def readBytes(self, n):
        if self._broken:
            return b""
        data = self._store.get(self._path, b"")
        chunk = data[self._pos : self._pos + n]
        self._pos += len(chunk)
        return chunk

    def write(self, chunk):
        self._store[self._path] = self._store.get(self._path, b"") + bytes(chunk)
        return True

    def close(self):
        pass


def _fake_copy(store, src, dst, copy_fails_paths, copy_truncate_to):
    if dst in copy_fails_paths:
        return False
    data = store.get(src, b"")
    if dst in copy_truncate_to:
        data = data[: copy_truncate_to[dst]]
    store[dst] = data
    return True


def _install_fake_vfs(
    monkeypatch,
    ui_mod,
    *,
    store,
    settled_sizes_by_path=None,
    broken_read_paths=None,
    copy_fails_paths=None,
    copy_truncate_to=None,
):
    """A fake xbmcvfs where Stat().st_size() can return a caller-controlled,
    per-call sequence of values (to simulate the settle race), independent of
    what was ACTUALLY written to the in-memory store. `copy_fails_paths` makes
    xbmcvfs.copy() return False for that destination; `copy_truncate_to` makes
    it "succeed" but write fewer bytes than the source has (a truncated native
    copy) - both simulate the fallback path itself failing."""
    settled_sizes_by_path = settled_sizes_by_path or {}
    broken_read_paths = broken_read_paths or frozenset()
    copy_fails_paths = copy_fails_paths or frozenset()
    copy_truncate_to = copy_truncate_to or {}
    call_counts = {}

    class _FakeStat:
        def __init__(self, path):
            self._path = path

        def st_size(self):
            if self._path in settled_sizes_by_path:
                seq = settled_sizes_by_path[self._path]
                i = call_counts.get(self._path, 0)
                call_counts[self._path] = i + 1
                return seq[min(i, len(seq) - 1)]
            return len(store.get(self._path, b""))

    fake_xbmcvfs = types.SimpleNamespace(
        File=lambda path, mode="r": _FakeFile(
            store, path, mode, broken_read_paths=broken_read_paths
        ),
        Stat=_FakeStat,
        exists=lambda p: p in store,
        delete=lambda p: store.pop(p, None) or True,
        rename=lambda a, b: (
            (store.__setitem__(b, store.pop(a)), True)[1] if a in store else False
        ),
        copy=lambda a, b: _fake_copy(store, a, b, copy_fails_paths, copy_truncate_to),
    )
    monkeypatch.setitem(sys.modules, "xbmcvfs", fake_xbmcvfs)
    monkeypatch.setattr(ui_mod, "xbmcvfs", fake_xbmcvfs)
    return call_counts


def test_copy_once_settles_after_transient_zero_size(ui, monkeypatch):
    """The live-observed shape: the write completes fully (no refused write,
    no exception), but the FIRST size check reads stale 0 - it must settle to
    the correct size on a later poll instead of declaring a hard failure."""
    store = {"src": b"x" * 1000}
    # First Stat call after the write reads stale 0; the second reads correct.
    _install_fake_vfs(
        monkeypatch, ui, store=store, settled_sizes_by_path={"dst.ezmpart": [0, 1000]}
    )
    result = ui.copy_with_progress("src", "dst")
    assert result == ui.COPY_OK
    assert store["dst"] == b"x" * 1000
    # Settled via the cheap poll, NOT the expensive whole-copy retry.
    assert len(ui._TEST_SLEEPS) == 1
    assert ui._TEST_SLEEPS[0] == ui.SIZE_SETTLE_DELAY_MS


def test_copy_once_falls_back_to_native_copy_after_settle_attempts_exhausted(
    ui, monkeypatch
):
    """A size that never settles must not spin forever, and must not just raise
    either - it must fall back to the opaque xbmcvfs.copy() (the pre-2026.07.01.0
    mechanism) and succeed, since the destination store DOES hold the right bytes
    (only the Stat() reads in this scenario are wrong, not the underlying data)."""
    store = {"src": b"x" * 1000}
    _install_fake_vfs(
        monkeypatch, ui, store=store, settled_sizes_by_path={"dst.ezmpart": [0]}
    )
    result = ui._copy_once("src", "dst")
    assert result == ui.COPY_OK
    assert len(ui._TEST_SLEEPS) == ui.SIZE_SETTLE_ATTEMPTS - 1
    assert store["dst"] == b"x" * 1000  # shipped via the native copy() fallback
    assert "dst.ezmpart" not in store  # partial cleaned up


def test_copy_once_falls_back_to_native_copy_when_chunked_read_is_broken(
    ui, monkeypatch
):
    """The live-observed shape from a real Apple TV backup: File(src, "r").readBytes()
    returns empty on the very first call despite Stat(src) correctly reporting the
    full size (copied=0 total=142444751 actual=0 in the real log) - the chunked
    reader can never succeed no matter how many times it is retried, because Kodi's
    Python-level File/readBytes binding is what's broken, not the underlying file.
    The native xbmcvfs.copy() fallback bypasses that binding entirely and must
    still ship the correct bytes."""
    store = {"src": b"x" * 1000}
    _install_fake_vfs(
        monkeypatch, ui, store=store, broken_read_paths=frozenset({"src"})
    )
    result = ui.copy_with_progress("src", "dst")
    assert result == ui.COPY_OK
    assert store["dst"] == b"x" * 1000


def test_copy_with_progress_raises_when_fallback_copy_also_fails(ui, monkeypatch):
    """A double failure - the chunked read is broken (as on tvOS) AND the native
    xbmcvfs.copy() fallback also fails (share genuinely gone) - must still raise
    VfsCopyError, not silently report success. Exercises copy_with_progress (not
    just _copy_once) so the outer COPY_RETRY_ATTEMPTS exhaustion path is proven
    too, not just the first attempt."""
    store = {"src": b"x" * 1000}
    _install_fake_vfs(
        monkeypatch,
        ui,
        store=store,
        broken_read_paths=frozenset({"src"}),
        copy_fails_paths=frozenset({"dst"}),
    )
    with pytest.raises(ui.VfsCopyError):
        ui.copy_with_progress("src", "dst")
    assert "dst" not in store


def test_fallback_copy_rejects_a_truncated_native_copy(ui, monkeypatch):
    """xbmcvfs.copy() returning True is not proof the bytes actually landed - the
    same server-side commit-delay race the chunked path settles for could affect
    the native copy too. A fallback that "succeeds" but ships fewer bytes than
    the source must still raise VfsCopyError and clean up the short file, not
    let backup() rotate out a good backup for a truncated one."""
    store = {"src": b"x" * 1000}
    _install_fake_vfs(
        monkeypatch,
        ui,
        store=store,
        broken_read_paths=frozenset({"src"}),
        copy_truncate_to={"dst": 500},
    )
    with pytest.raises(ui.VfsCopyError, match="fallback copy size mismatch"):
        ui._copy_once("src", "dst")
    assert "dst" not in store  # the short file was cleaned up, not left behind


def test_copy_once_no_settle_needed_is_fast(ui, monkeypatch):
    """The common case (size correct immediately) must not sleep at all."""
    store = {"src": b"x" * 1000}
    _install_fake_vfs(monkeypatch, ui, store=store)
    result = ui.copy_with_progress("src", "dst")
    assert result == ui.COPY_OK
    assert ui._TEST_SLEEPS == []


def test_copy_once_size_mismatch_logs_diagnostic_with_copied_count(ui, monkeypatch):
    """A never-settling mismatch must log `copied` (bytes actually read from src
    and written to tmp) alongside total/actual before falling back - the one fact
    that distinguishes a read-side failure (copied==0) from a destination-stat
    failure (copied==total but actual!=total), per the live investigation that
    found the prior settle-only fix insufficient."""
    store = {"src": b"x" * 1000}
    _install_fake_vfs(
        monkeypatch, ui, store=store, settled_sizes_by_path={"dst.ezmpart": [0]}
    )
    result = ui._copy_once("src", "dst")
    assert result == ui.COPY_OK
    assert len(ui._TEST_LOGS) == 1
    msg = ui._TEST_LOGS[0]
    assert "copied=1000" in msg  # the full 1000 bytes WERE read+written here
    assert "total=1000" in msg
    assert "actual=0" in msg
