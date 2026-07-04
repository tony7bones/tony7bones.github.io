"""Coverage for script.ezmaintenanceplusplus's ui.py copy fallback/local-read fix.

Two real device logs on the same tvOS Apple TV both showed a 142 MB backup
copy failing with "size mismatch (0 != total)": copied=0, total=<the correct
size>, actual=0, on every retry. The first log proved this was a read-side
failure, not a destination-write-timing race. A second log - taken AFTER
shipping a fix that fell back to the opaque xbmcvfs.copy() on a broken chunked
read - showed the SAME failure: xbmcvfs.copy() ALSO could not read the source.
That is decisive: reading this local, just-built temp zip fails through EVERY
Kodi VFS mechanism (File.readBytes() and the native xbmcvfs.copy()), even
though xbmcvfs.Stat() on it always correctly reports the real size. This
add-on's own CreateZip() writes that file with plain zipfile/open(), and
wiz.py's own staged-zip validation already reads it back with plain
os.path.getsize()/zipfile.is_zipfile() - so plain Python I/O is proven to work
for this exact class of path on this exact device; only Kodi's VFS read of it
is broken. The fix: a local source path (no "://") is now read with plain
Python open(), never xbmcvfs, for both the primary chunked copy and its
fallback retry.

This file builds a minimal fake xbmc/xbmcaddon/xbmcgui/xbmcvfs (ui.py's own
docstring: "Imports ONLY xbmc / xbmcaddon / xbmcgui / xbmcvfs, so it is fully
unit-testable off-device") to exercise the real _copy_once/copy_with_progress
code, not a reimplementation of it. Fake VFS paths use an "nfs://" prefix so
`_open_reader` routes them through the fake xbmcvfs.File instead of a real
local `open()` - only the dedicated local-read test uses a real file (via
tmp_path), since that is the one behavior that must NOT go through the fake.
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
    returns empty on every call for a path, even though the store (and
    therefore Stat()) holds the real, correctly-sized data.
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


def _install_fake_vfs(
    monkeypatch, ui_mod, *, store, settled_sizes_by_path=None, broken_read_paths=None
):
    """A fake xbmcvfs where Stat().st_size() can return a caller-controlled,
    per-call sequence of values (to simulate a settle race or a permanently
    unreliable stat), independent of what was ACTUALLY written to the
    in-memory store."""
    settled_sizes_by_path = settled_sizes_by_path or {}
    broken_read_paths = broken_read_paths or frozenset()
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
        copy=lambda a, b: (store.__setitem__(b, store.get(a, b"")), True)[1],
    )
    monkeypatch.setitem(sys.modules, "xbmcvfs", fake_xbmcvfs)
    monkeypatch.setattr(ui_mod, "xbmcvfs", fake_xbmcvfs)
    return call_counts


def test_copy_once_settles_after_transient_zero_size(ui, monkeypatch):
    """The live-observed shape (the FIRST real device log, before the read-side
    root cause was found): the write completes fully (no refused write, no
    exception), but the FIRST size check reads stale 0 - it must settle to the
    correct size on a later poll instead of declaring a hard failure."""
    store = {"nfs://src": b"x" * 1000}
    # First Stat call after the write reads stale 0; the second reads correct.
    _install_fake_vfs(
        monkeypatch,
        ui,
        store=store,
        settled_sizes_by_path={"nfs://dst.ezmpart": [0, 1000]},
    )
    result = ui.copy_with_progress("nfs://src", "nfs://dst")
    assert result == ui.COPY_OK
    assert store["nfs://dst"] == b"x" * 1000
    # Settled via the cheap poll, NOT the expensive whole-copy retry.
    assert len(ui._TEST_SLEEPS) == 1
    assert ui._TEST_SLEEPS[0] == ui.SIZE_SETTLE_DELAY_MS


def test_copy_once_falls_back_after_settle_attempts_exhausted(ui, monkeypatch):
    """A destination size that never settles must not spin forever, and must
    not just raise either - it must fall back to a second, clean copy attempt
    and succeed, since the destination store DOES hold the right bytes (only
    the Stat() reads in this scenario are wrong, not the underlying data)."""
    store = {"nfs://src": b"x" * 1000}
    _install_fake_vfs(
        monkeypatch, ui, store=store, settled_sizes_by_path={"nfs://dst.ezmpart": [0]}
    )
    result = ui._copy_once("nfs://src", "nfs://dst")
    assert result == ui.COPY_OK
    assert len(ui._TEST_SLEEPS) == ui.SIZE_SETTLE_ATTEMPTS - 1
    assert store["nfs://dst"] == b"x" * 1000  # shipped via the fallback retry
    assert "nfs://dst.ezmpart" not in store  # partial cleaned up


def test_copy_once_reads_a_local_source_without_going_through_vfs(
    ui, monkeypatch, tmp_path
):
    """The actual, live-confirmed root cause and its fix: reading a just-built
    LOCAL temp zip via Kodi's VFS (File.readBytes() OR the opaque
    xbmcvfs.copy()) came back completely empty on a real Apple TV on every
    attempt, despite xbmcvfs.Stat() correctly reporting its size - confirmed
    twice, once for each recovery mechanism tried. A local source (no "://")
    must now be read with plain Python open(), never xbmcvfs, so this uses a
    REAL file (not the fake store) for src. To prove the VFS read is never
    even attempted, xbmcvfs.File is deliberately broken for this exact path
    too - if the code regressed to using it, this test would fail with a size
    mismatch instead of succeeding on the first try."""
    data = b"x" * 1000
    src = tmp_path / "kodi_backup_202607041122.zip"
    src.write_bytes(data)
    src_path = str(src)
    # Stat() still goes through xbmcvfs (the real Stat() has always correctly
    # reported the size in every live log) - only the store copy for the size
    # check; the real read bypasses this store entirely via plain open().
    store = {src_path: data}
    _install_fake_vfs(
        monkeypatch, ui, store=store, broken_read_paths=frozenset({src_path})
    )
    result = ui.copy_with_progress(src_path, "nfs://dst")
    assert result == ui.COPY_OK
    assert store["nfs://dst"] == data
    # Succeeded on the very first attempt - no settle poll, no fallback needed.
    assert ui._TEST_SLEEPS == []


def test_copy_with_progress_raises_when_both_attempts_fail(ui, monkeypatch):
    """A source whose VFS read is broken on BOTH the primary chunked attempt
    and the fallback's retry (a remote share that genuinely can't be read)
    must still raise VfsCopyError, not silently report success. Exercises
    copy_with_progress (not just _copy_once) so the outer COPY_RETRY_ATTEMPTS
    exhaustion path is proven too, not just one attempt."""
    store = {"nfs://src": b"x" * 1000}
    _install_fake_vfs(
        monkeypatch, ui, store=store, broken_read_paths=frozenset({"nfs://src"})
    )
    with pytest.raises(ui.VfsCopyError):
        ui.copy_with_progress("nfs://src", "nfs://dst")
    assert "nfs://dst" not in store


def test_fallback_copy_rejects_a_destination_that_never_settles(ui, monkeypatch):
    """A successful fallback copy is not proof the bytes actually landed - the
    same destination-stat unreliability the primary chunked path settles for
    could affect the fallback's own destination check too. A destination whose
    Stat() never matches must still raise VfsCopyError and clean up, not let
    backup() rotate out a good backup for a file whose true size is unknown."""
    store = {"nfs://src": b"x" * 1000}
    _install_fake_vfs(
        monkeypatch,
        ui,
        store=store,
        settled_sizes_by_path={"nfs://dst.ezmpart": [0], "nfs://dst": [0]},
    )
    with pytest.raises(ui.VfsCopyError, match="fallback copy size mismatch"):
        ui._copy_once("nfs://src", "nfs://dst")
    assert "nfs://dst" not in store  # the unverified file was cleaned up


def test_copy_once_no_settle_needed_is_fast(ui, monkeypatch):
    """The common case (size correct immediately) must not sleep at all."""
    store = {"nfs://src": b"x" * 1000}
    _install_fake_vfs(monkeypatch, ui, store=store)
    result = ui.copy_with_progress("nfs://src", "nfs://dst")
    assert result == ui.COPY_OK
    assert ui._TEST_SLEEPS == []


def test_copy_once_size_mismatch_logs_diagnostic_with_copied_count(ui, monkeypatch):
    """A never-settling mismatch must log `copied` (bytes actually read from
    src and written to tmp) alongside total/actual before falling back - the
    one fact that distinguished a read-side failure (copied==0) from a
    destination-stat failure (copied==total but actual!=total) during the live
    investigation, before a second real device log settled it decisively."""
    store = {"nfs://src": b"x" * 1000}
    _install_fake_vfs(
        monkeypatch, ui, store=store, settled_sizes_by_path={"nfs://dst.ezmpart": [0]}
    )
    result = ui._copy_once("nfs://src", "nfs://dst")
    assert result == ui.COPY_OK
    assert len(ui._TEST_LOGS) == 1
    msg = ui._TEST_LOGS[0]
    assert "copied=1000" in msg  # the full 1000 bytes WERE read+written here
    assert "total=1000" in msg
    assert "actual=0" in msg
