"""Coverage for script.ezmaintenanceplusplus's wiz.py port-stripping fix.

wiz.py's backup()/restoreFolder() read download.path/restore.path - both
Kodi "type=folder" settings, browse-only, with no manual text entry at all.
Kodi's own network-browse dialog bakes an explicit port into the nfs:// URL
it hands back (e.g. nfs://host:2049/export/path), and that explicit-port
form breaks Kodi's own NFS client write path - live-proven, independently,
on two different boxes (a VfsCopyError / 0-byte copy every time). Since the
setting can only ever be set via that same dialog, this can recur on any
future box; _strip_nfs_port() defangs it at the two read sites.

This is a large, pre-existing third-party add-on this repo forks/patches
(CLAUDE.md: "standardize on the repo's ++ fork"), with no existing test
harness of its own. The fixture below fakes just enough of xbmc*/xbmcaddon/
xbmcgui/xbmcvfs/xbmcplugin for wiz.py's own import chain (control.py,
maintenance.py, tools.py, ui.py) to succeed, so _strip_nfs_port can be
exercised as the real function inside the real module, not a copy-pasted
reimplementation of its regex.
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
def wiz(monkeypatch, tmp_path):
    monkeypatch.syspath_prepend(str(ADDON_ROOT))
    for name in list(sys.modules):
        if name == "resources" or name.startswith("resources."):
            monkeypatch.delitem(sys.modules, name, raising=False)

    xbmc = types.ModuleType("xbmc")
    xbmc.translatePath = lambda p: p.replace("special://", str(tmp_path) + "/")
    xbmc.getLocalizedString = lambda i: str(i)
    xbmc.getInfoLabel = lambda s: ""
    xbmc.getCondVisibility = lambda s: False
    xbmc.getSkinDir = lambda: "skin.estuary"
    xbmc.log = lambda *a, **k: None
    xbmc.executebuiltin = lambda *a, **k: None
    xbmc.executeJSONRPC = lambda cmd: "{}"
    xbmc.LOGERROR = 1
    xbmc.LOGWARNING = 2
    xbmc.LOGINFO = 3
    xbmc.LOGDEBUG = 4
    xbmc.LOGFATAL = 0
    xbmc.LOGNONE = 5
    xbmc.LOGNOTICE = 3
    xbmc.PLAYLIST_VIDEO = 1
    xbmc.sleep = lambda ms: None
    xbmc.Keyboard = lambda *a, **k: types.SimpleNamespace(
        doModal=lambda: None, isConfirmed=lambda: False, getText=lambda: ""
    )
    xbmc.PlayList = lambda *a, **k: types.SimpleNamespace(
        clear=lambda: None, add=lambda *a: None
    )
    xbmc.Player = lambda *a, **k: types.SimpleNamespace(play=lambda *a, **k: None)
    xbmc.Monitor = type(
        "Monitor",
        (),
        {"abortRequested": lambda self: False, "waitForAbort": lambda self, t: False},
    )

    xbmcaddon = types.ModuleType("xbmcaddon")

    class _FakeAddon:
        def getLocalizedString(self, i):
            return str(i)

        def getSetting(self, key):
            return ""

        def setSetting(self, key, value):
            pass

        def getAddonInfo(self, key):
            return {
                "id": "script.ezmaintenanceplusplus",
                "name": "EZ Maintenance++",
                "path": str(ADDON_ROOT),
                "profile": "special://profile/",
                "version": "0.0.0",
            }.get(key, "")

    xbmcaddon.Addon = _FakeAddon

    xbmcgui = types.ModuleType("xbmcgui")

    class _FakeDialogProgress:
        def create(self, *a, **k):
            pass

        def update(self, *a, **k):
            pass

        def close(self):
            pass

        def iscanceled(self):
            return False

    class _FakeDialog:
        def ok(self, *a, **k):
            return False

        def yesno(self, *a, **k):
            return False

        def notification(self, *a, **k):
            pass

        def select(self, *a, **k):
            return -1

    xbmcgui.DialogProgress = _FakeDialogProgress
    xbmcgui.DialogProgressBG = _FakeDialogProgress
    xbmcgui.Dialog = _FakeDialog
    xbmcgui.ListItem = lambda *a, **k: types.SimpleNamespace(
        setArt=lambda *a, **k: None
    )
    xbmcgui.ControlButton = lambda *a, **k: None
    xbmcgui.ControlImage = lambda *a, **k: None

    class _FakeWindow:
        def __init__(self, *a, **k):
            pass

        def getProperty(self, k):
            return ""

        def setProperty(self, k, v):
            pass

        def clearProperty(self, k):
            pass

    xbmcgui.Window = _FakeWindow
    xbmcgui.WindowDialog = _FakeWindow

    xbmcvfs = types.ModuleType("xbmcvfs")
    xbmcvfs.translatePath = xbmc.translatePath
    xbmcvfs.exists = lambda p: Path(p).exists()
    xbmcvfs.mkdirs = lambda p: Path(p).mkdir(parents=True, exist_ok=True)
    xbmcvfs.mkdir = lambda p: Path(p).mkdir(parents=True, exist_ok=True)
    xbmcvfs.rmdir = lambda p: None
    xbmcvfs.delete = lambda p: None
    xbmcvfs.listdir = lambda p: ([], [])
    xbmcvfs.copy = lambda s, d: True
    xbmcvfs.File = lambda *a, **k: types.SimpleNamespace(
        read=lambda *a: b"", write=lambda *a: True, close=lambda: None, size=lambda: 0
    )

    xbmcplugin = types.ModuleType("xbmcplugin")
    xbmcplugin.addDirectoryItem = lambda *a, **k: None
    xbmcplugin.endOfDirectory = lambda *a, **k: None
    xbmcplugin.setContent = lambda *a, **k: None
    xbmcplugin.setProperty = lambda *a, **k: None
    xbmcplugin.setResolvedUrl = lambda *a, **k: None

    for name, mod in (
        ("xbmc", xbmc),
        ("xbmcaddon", xbmcaddon),
        ("xbmcgui", xbmcgui),
        ("xbmcvfs", xbmcvfs),
        ("xbmcplugin", xbmcplugin),
    ):
        monkeypatch.setitem(sys.modules, name, mod)

    return importlib.import_module("resources.lib.modules.wiz")


def test_strip_nfs_port_removes_explicit_port(wiz):
    assert (
        wiz._strip_nfs_port("nfs://192.168.7.2:2049/Users/moquette/Kodi/Backup/atv-2/")
        == "nfs://192.168.7.2/Users/moquette/Kodi/Backup/atv-2/"
    )


def test_strip_nfs_port_no_port_unchanged(wiz):
    path = "nfs://192.168.7.2/Users/moquette/Kodi/Backup/atv-2/"
    assert wiz._strip_nfs_port(path) == path


def test_strip_nfs_port_leaves_non_nfs_paths_alone(wiz):
    assert (
        wiz._strip_nfs_port("smb://192.168.7.2/KodiBackup/atv-2/")
        == "smb://192.168.7.2/KodiBackup/atv-2/"
    )
    assert wiz._strip_nfs_port("/local/path") == "/local/path"


def test_strip_nfs_port_handles_empty_and_none(wiz):
    assert wiz._strip_nfs_port("") == ""
    assert wiz._strip_nfs_port(None) is None


def test_strip_nfs_port_bare_host_no_trailing_slash(wiz):
    # A port on a bare host with no path at all must still be stripped.
    assert wiz._strip_nfs_port("nfs://192.168.7.2:2049") == "nfs://192.168.7.2"


def test_backup_uses_stripped_port_path(wiz, monkeypatch, tmp_path):
    """End-to-end: backup() must pass the STRIPPED path to CreateZip, not the
    raw (possibly port-carrying) download.path setting value."""
    backupdata = tmp_path / "home"
    backupdata.mkdir()
    monkeypatch.setattr(wiz.control, "HOME", str(backupdata))
    monkeypatch.setattr(
        wiz.control,
        "setting",
        lambda key: (
            "nfs://192.168.7.2:2049/Users/moquette/Kodi/Backup/atv-2/"
            if key == "download.path"
            else ""
        ),
    )
    monkeypatch.setattr(wiz.tools, "_get_keyboard", lambda **k: "mybackup")

    captured = {}

    def _fake_create_zip(src, dst, *a, **k):
        captured["dst"] = dst
        return False

    monkeypatch.setattr(wiz, "CreateZip", _fake_create_zip)
    monkeypatch.setattr(wiz, "_rotate_vfs", lambda *a, **k: None)
    monkeypatch.setattr(
        wiz,
        "xbmcaddon",
        types.SimpleNamespace(
            Addon=lambda: types.SimpleNamespace(getSetting=lambda k: "false")
        ),
    )

    wiz.backup(mode="full")
    assert "dst" in captured, "CreateZip must have been called"
    assert ":2049" not in captured["dst"]
    assert captured["dst"].startswith(
        "nfs://192.168.7.2/Users/moquette/Kodi/Backup/atv-2/"
    )
