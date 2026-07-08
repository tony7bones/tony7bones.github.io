"""Coverage for script.ezmaintenanceplusplus's nsud.py (Apple TV restore durability).

nsud re-writes restored userdata *.xml THROUGH xbmcvfs so tvOS vectors them into
NSUserDefaults. The load-bearing correctness rule is the SINGLE write per file: Kodi's
tvOS CTVOSFile::Write REPLACES the whole NSUserDefaults key on every call, so a chunked
write would leave only the last chunk (a truncated XML fragment). The fake xbmcvfs.File
below models that replace-per-write semantics, so a regression to chunking fails these
tests exactly the way a real Apple TV would corrupt the settings.

nsud imports only os/json (real) + xbmc/xbmcvfs (faked here), so it is exercised as the
real module in isolation, no heavy add-on import chain needed.
"""

from __future__ import annotations

import importlib
import sys
import types
from pathlib import Path

import pytest

ADDON_MODULES = (
    Path(__file__).parent.parent
    / "addons"
    / "script.ezmaintenanceplusplus"
    / "resources"
    / "lib"
    / "modules"
)


class _FakeFile:
    """Models tvOS CTVOSFile: each write() REPLACES the whole stored value for the path."""

    def __init__(self, store, writes, fail, path, mode):
        self._store = store
        self._writes = writes
        self._fail = fail
        self._path = path

    def write(self, data):
        self._writes.append((self._path, bytes(data)))  # record every write call
        if self._fail:
            return False
        self._store[self._path] = bytes(data)  # REPLACE (not append) — the tvOS semantics
        return True

    def close(self):
        pass


@pytest.fixture
def nsud(monkeypatch):
    """Import the real nsud.py with faked xbmc/xbmcvfs; expose recorders."""
    store: dict[str, bytes] = {}  # special path -> final bytes in "NSUserDefaults"
    writes: list[tuple[str, bytes]] = []  # every (path, bytes) write call
    events: list[str] = []  # ordered trace: enable:.. / sleep / write:<path>
    state = {"fail_writes": False}

    xbmc = types.ModuleType("xbmc")
    xbmc.LOGINFO = 3
    xbmc.LOGERROR = 1
    xbmc.sleep = lambda ms: events.append("sleep")
    xbmc.log = lambda *a, **k: None

    def _execute_jsonrpc(s):
        import json

        req = json.loads(s)
        if req.get("method") == "Addons.SetAddonEnabled":
            events.append("enable:%s" % req["params"]["enabled"])
        return json.dumps({"result": "OK"})

    xbmc.executeJSONRPC = _execute_jsonrpc

    xbmcvfs = types.ModuleType("xbmcvfs")

    def _make_file(path, mode):
        events.append("write-open:%s" % path)
        return _FakeFile(store, writes, state["fail_writes"], path, mode)

    # File() records the OPEN in events on construction so ordering vs enable/sleep is
    # captured even though the write itself happens on .write().
    xbmcvfs.File = _make_file

    monkeypatch.setitem(sys.modules, "xbmc", xbmc)
    monkeypatch.setitem(sys.modules, "xbmcvfs", xbmcvfs)
    monkeypatch.syspath_prepend(str(ADDON_MODULES))
    monkeypatch.delitem(sys.modules, "nsud", raising=False)
    mod = importlib.import_module("nsud")

    return types.SimpleNamespace(
        mod=mod, store=store, writes=writes, events=events, state=state
    )


def _write(base: Path, rel: str, content: bytes = b"<x/>") -> None:
    p = base / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(content)


# --------------------------------------------------------------------------- #
# The core invariant: ONE write per file, full content (the anti-chunking guard).
# --------------------------------------------------------------------------- #
def test_single_write_per_file_full_content(nsud, tmp_path):
    big = b"<settings>" + b"x" * 100_000 + b"</settings>"
    _write(tmp_path, "guisettings.xml", big)

    nsud.mod.rewrite_userdata_xml(str(tmp_path))

    special = "special://home/userdata/guisettings.xml"
    per_file = [w for w in nsud.writes if w[0] == special]
    assert len(per_file) == 1, "must be exactly ONE write() per file — never chunk"
    assert nsud.store[special] == big, "the whole file must land, not a tail fragment"


# --------------------------------------------------------------------------- #
# Exclusions: the add-on's own settings (secret + boot-crash) and the pvr subtree.
# --------------------------------------------------------------------------- #
def test_excludes_own_settings_secret(nsud, tmp_path):
    _write(
        tmp_path,
        "addon_data/script.ezmaintenanceplusplus/settings.xml",
        b'<settings><setting id="dropbox_refresh_token">SECRET</setting></settings>',
    )
    _write(tmp_path, "guisettings.xml")

    written, skipped, failed = nsud.mod.rewrite_userdata_xml(str(tmp_path))

    assert (
        "special://home/userdata/addon_data/script.ezmaintenanceplusplus/settings.xml"
        not in nsud.store
    )
    assert not any(b"SECRET" in v for v in nsud.store.values())
    assert skipped >= 1 and written >= 1


def test_general_walk_skips_pvr_instance_settings(nsud, tmp_path):
    _write(tmp_path, "addon_data/pvr.iptvsimple/instance-settings-1.xml")
    _write(tmp_path, "RssFeeds.xml")

    nsud.mod.rewrite_userdata_xml(str(tmp_path))

    assert not any("pvr.iptvsimple" in p for p in nsud.store), (
        "pvr instance files are handled by the disable-window, not the blind walk"
    )
    assert "special://home/userdata/RssFeeds.xml" in nsud.store


def test_non_xml_files_skipped(nsud, tmp_path):
    _write(tmp_path, "Database/MyVideos.db", b"sqlite")
    _write(tmp_path, "Thumbnails/a.jpg", b"jpeg")
    _write(tmp_path, "keyboard.xml")

    written, _skipped, _failed = nsud.mod.rewrite_userdata_xml(str(tmp_path))

    assert list(nsud.store) == ["special://home/userdata/keyboard.xml"]
    assert written == 1


def test_write_failure_leaves_source_and_counts_failed(nsud, tmp_path):
    _write(tmp_path, "guisettings.xml", b"<settings/>")
    nsud.state["fail_writes"] = True

    written, _skipped, failed = nsud.mod.rewrite_userdata_xml(str(tmp_path))

    assert written == 0 and failed == 1
    # POSIX source is untouched (no data loss — worst case is the pre-existing shadow).
    assert (tmp_path / "guisettings.xml").read_bytes() == b"<settings/>"


# --------------------------------------------------------------------------- #
# IPTV disable-window: ordering, re-enable in finally, dynamic instance count.
# --------------------------------------------------------------------------- #
def test_iptv_disable_window_ordering(nsud, tmp_path):
    _write(tmp_path, "addon_data/pvr.iptvsimple/instance-settings-1.xml")
    _write(tmp_path, "addon_data/pvr.iptvsimple/customTVGroups-Foo.xml")

    written, failed = nsud.mod.reassert_iptv_instances(str(tmp_path))

    assert written == 2 and failed == 0
    ev = nsud.events
    assert ev[0] == "enable:False", "must DISABLE the client first"
    assert ev[1] == "sleep", "must settle before writing"
    assert ev[-1] == "enable:True", "must RE-ENABLE last (forces re-read) — in finally"
    # every file write happens strictly inside the window
    write_idx = [i for i, e in enumerate(ev) if e.startswith("write-open:")]
    assert write_idx and min(write_idx) > 1 and max(write_idx) < len(ev) - 1


def test_iptv_reenable_even_when_write_raises(nsud, tmp_path):
    _write(tmp_path, "addon_data/pvr.iptvsimple/instance-settings-1.xml")

    def _boom(path, mode):
        raise RuntimeError("vfs blew up")

    sys.modules["xbmcvfs"].File = _boom

    nsud.mod.reassert_iptv_instances(str(tmp_path))

    assert nsud.events[0] == "enable:False"
    assert nsud.events[-1] == "enable:True", "re-enable must run in finally on failure"


def test_iptv_noop_without_instance_settings(nsud, tmp_path):
    # pvr dir exists but holds no instance-settings -> must not toggle the client.
    _write(tmp_path, "addon_data/pvr.iptvsimple/customTVGroups-Foo.xml")

    written, failed = nsud.mod.reassert_iptv_instances(str(tmp_path))

    assert (written, failed) == (0, 0)
    assert nsud.events == []


def test_iptv_noop_when_pvr_absent(nsud, tmp_path):
    written, failed = nsud.mod.reassert_iptv_instances(str(tmp_path))
    assert (written, failed) == (0, 0)
    assert nsud.events == []


def test_iptv_dynamic_instance_count(nsud, tmp_path):
    _write(tmp_path, "addon_data/pvr.iptvsimple/instance-settings-1.xml")
    _write(tmp_path, "addon_data/pvr.iptvsimple/instance-settings-2.xml")

    written, failed = nsud.mod.reassert_iptv_instances(str(tmp_path))

    assert written == 2 and failed == 0


# --------------------------------------------------------------------------- #
# Wiring: the re-write runs AFTER apply_guisettings/UpdateLocalAddons and BEFORE the
# restart prompt (source-order guard — the ordering is load-bearing, review finding).
# --------------------------------------------------------------------------- #
def test_wiz_calls_nsud_after_updatelocaladdons_before_restart():
    wiz_src = (
        ADDON_MODULES / "wiz.py"
    ).read_text(encoding="utf-8")
    i_apply = wiz_src.index("apply_guisettings(")
    i_update = wiz_src.index('executebuiltin("UpdateLocalAddons")')
    i_rewrite = wiz_src.index("nsud.rewrite_userdata_xml(")
    i_iptv = wiz_src.index("nsud.reassert_iptv_instances(")
    i_marker = wiz_src.index("mark_buffer_prompt_pending()")
    assert i_apply < i_update < i_rewrite < i_iptv < i_marker
