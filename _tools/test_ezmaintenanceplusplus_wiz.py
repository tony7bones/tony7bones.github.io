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


def test_backup_opens_native_settings_when_path_unset(wiz, monkeypatch, tmp_path):
    """backup() with an empty download.path must open the (now-working) NATIVE
    settings dialog via control.openSettings, not the retired custom screen."""
    backupdata = tmp_path / "home"
    backupdata.mkdir()
    monkeypatch.setattr(wiz.control, "HOME", str(backupdata))
    monkeypatch.setattr(wiz.control, "setting", lambda key: "")

    calls = []
    monkeypatch.setattr(wiz.control, "openSettings", lambda *a, **k: calls.append(True))

    wiz.backup(mode="full")
    assert calls == [True]


def test_restore_opens_native_settings_when_path_unset(wiz, monkeypatch):
    """restoreFolder() with an empty restore.path must open the NATIVE settings
    dialog via control.openSettings, not the retired custom screen."""
    monkeypatch.setattr(wiz.control, "setting", lambda key: "")

    calls = []
    monkeypatch.setattr(wiz.control, "openSettings", lambda *a, **k: calls.append(True))

    wiz.restoreFolder()
    assert calls == [True]


def test_restore_does_not_rewrite_settings_verbatim_restore(wiz, monkeypatch, tmp_path):
    """A restore now restores the backup EXACTLY as taken - it does NOT re-stamp
    download.path/restore.path/destination afterward. The user sets the backup path
    themselves (the native settings dialog works), so restore stays a plain, predictable
    extract with no magic touching the restored settings."""
    import zipfile as _zip

    writes = []
    monkeypatch.setattr(wiz.control, "setting", lambda key: "")
    monkeypatch.setattr(wiz.control, "setSetting", lambda k, v: writes.append((k, v)))
    monkeypatch.setattr(wiz.ui, "ask_restart", lambda *a, **k: None)

    src = tmp_path / "some_backup.zip"
    with _zip.ZipFile(src, "w") as z:
        z.writestr(
            "userdata/addon_data/script.ezmaintenanceplusplus/settings.xml",
            "<settings><setting id='download.path'>"
            "nfs://192.168.7.2/Kodi/Backup/office/</setting></settings>",
        )
        z.writestr("userdata/guisettings.xml", "<settings />")

    wiz.restore(str(src), confirm=False)

    # restore() must NOT setSetting any box-local key - the extracted settings.xml stands.
    assert not any(
        k in ("download.path", "restore.path", "destination") for k, _ in writes
    ), f"restore should not re-stamp box-local settings, but wrote: {writes}"


# --------------------------------------------------------------------------- #
# "Wipe clean before restore" (clean-clone) path + the extract crash fix.
# --------------------------------------------------------------------------- #
class _RecordingProgress:
    """A fake ui.Progress that records every items() note and never cancels, so the
    extract's dialog-update throttle can be asserted off-device."""

    def __init__(self):
        self.notes = []

    def cancelled(self):
        return False

    def items(self, done, total, note=""):
        self.notes.append(note)


def _make_valid_zip(path, files):
    import zipfile as _zip

    with _zip.ZipFile(path, "w") as z:
        for name, body in files:
            z.writestr(name, body)
    return path


def _load_onetap():
    return importlib.import_module("resources.lib.modules.onetap")


def test_restore_wipe_does_not_wipe_on_bad_zip(wiz, monkeypatch, tmp_path):
    """(a) restore(wipe=True) with a corrupt/short zip must ABORT with the box UNTOUCHED
    - validation fails, so the wipe is never reached."""
    onetap = _load_onetap()

    wiped = []
    restarted = []
    monkeypatch.setattr(onetap, "_wipe", lambda *a, **k: wiped.append(a))
    monkeypatch.setattr(wiz.ui, "ask_restart", lambda *a, **k: restarted.append(True))
    monkeypatch.setattr(wiz.control, "HOME", str(tmp_path / "home"))

    bad = tmp_path / "corrupt.zip"
    bad.write_bytes(b"this is not a zip file at all")  # size > 0 but not a real zip

    wiz.restore(str(bad), confirm=False, wipe=True)

    assert wiped == [], "the box must NOT be wiped when the zip is invalid"
    assert restarted == [], "a bad zip must not reach the restart prompt"


def test_restore_wipe_validates_then_wipes_then_extracts(wiz, monkeypatch, tmp_path):
    """(b) restore(wipe=True) with a valid zip must wipe ONLY after validation, then run
    the (uninterruptible) extract, then reach the restart prompt - in that order."""
    onetap = _load_onetap()

    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(wiz.control, "HOME", str(home))

    events = []
    monkeypatch.setattr(onetap, "_wipe", lambda *a, **k: events.append("wipe"))

    captured = {}

    def _fake_extract(_in, _out, progress, **kw):
        events.append("extract")
        captured["cancelable"] = kw.get("cancelable", True)
        return False

    monkeypatch.setattr(wiz, "ExtractWithProgress", _fake_extract)
    monkeypatch.setattr(wiz.ui, "ask_restart", lambda *a, **k: events.append("restart"))

    src = tmp_path / "backup.zip"
    _make_valid_zip(
        src,
        [
            ("userdata/guisettings.xml", "<settings />"),
            ("addons/foo/addon.xml", "<a/>"),
        ],
    )

    wiz.restore(str(src), confirm=False, wipe=True)

    assert events == ["wipe", "extract", "restart"], events
    # A wiped box must be driven by an UNINTERRUPTIBLE extract (post_wipe semantics).
    assert captured["cancelable"] is False


def test_wipe_excludes_preserves_addon_deps_and_temp(wiz):
    """(c) the reused One-Tap wipe excludes must preserve this add-on, its runtime deps,
    and special://temp (where the validated zip is staged)."""
    onetap = _load_onetap()
    ex = onetap._wipe_excludes()
    assert "temp" in ex
    assert "script.module.requests" in ex
    assert "script.ezmaintenanceplusplus" in ex


def test_extract_progress_note_is_throttled(wiz, tmp_path):
    """(d) the extract must NOT redraw the progress dialog with a new filename every file
    (the Fire OS 8 SIGSEGV). The note is refreshed at most every N files and never carries
    a per-file basename."""
    src = tmp_path / "many.zip"
    files = [("data/file%03d.txt" % i, "x") for i in range(200)]
    _make_valid_zip(src, files)

    out = tmp_path / "out"
    out.mkdir()
    p = _RecordingProgress()
    wiz.ExtractWithProgress(str(src), str(out), p)

    # Far fewer dialog updates than files (throttled), but still moving.
    assert 0 < len(p.notes) <= 200 // 10
    # No note carries a source basename - only the short static "Extracting file X of Y".
    assert all(n.startswith("Extracting file ") for n in p.notes)
    assert not any(".txt" in n for n in p.notes)
    # Every file was still actually extracted.
    assert len(list(out.rglob("*.txt"))) == 200


def test_order_userdata_first_puts_settings_before_addons(wiz):
    """(e) userdata/ entries must be ordered before addons/ so an interrupted extract
    keeps the irreplaceable settings."""
    infos = [
        types.SimpleNamespace(filename="addons/a/x.py"),
        types.SimpleNamespace(filename="userdata/guisettings.xml"),
        types.SimpleNamespace(filename="media/logo.png"),
        types.SimpleNamespace(filename="addons/b/y.py"),
        types.SimpleNamespace(filename="userdata/sources.xml"),
    ]
    names = [i.filename for i in wiz._order_userdata_first(infos)]
    last_userdata = max(i for i, n in enumerate(names) if n.startswith("userdata/"))
    first_addon = min(i for i, n in enumerate(names) if n.startswith("addons/"))
    assert last_userdata < first_addon, names


# --------------------------------------------------------------------------- #
# Post-restore, per-device video-cache-buffer retune.
# --------------------------------------------------------------------------- #
def test_restore_writes_buffer_prompt_marker(wiz, monkeypatch, tmp_path):
    """(a) a successful restore drops the persistent buffer-prompt marker (AFTER the
    extract, before the restart) so the boot service knows to retune the buffer."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(wiz.control, "HOME", str(home))
    monkeypatch.setattr(wiz, "ExtractWithProgress", lambda *a, **k: False)
    monkeypatch.setattr(wiz.ui, "ask_restart", lambda *a, **k: None)

    tools = wiz.tools
    # Ensure a clean slate.
    tools.clear_buffer_prompt_marker()
    assert not tools.buffer_prompt_pending()

    src = tmp_path / "backup.zip"
    _make_valid_zip(src, [("userdata/guisettings.xml", "<settings />")])

    wiz.restore(str(src), confirm=False, wipe=False)

    assert tools.buffer_prompt_pending(), "restore must drop the buffer-prompt marker"


def test_prompt_buffer_sets_recommended_and_clears(wiz, monkeypatch):
    """(b) with the marker present, choosing 'Set' calls _set_cache_mb(_recommended_mb())
    and deletes the marker (so it fires exactly once)."""
    tools = wiz.tools
    tools.mark_buffer_prompt_pending()
    assert tools.buffer_prompt_pending()

    monkeypatch.setattr(tools, "_recommended_mb", lambda: 128)
    sets = []
    monkeypatch.setattr(tools, "_set_cache_mb", lambda mb: sets.append(mb) or True)
    monkeypatch.setattr(tools.dialog, "select", lambda *a, **k: 0)

    shown = tools.prompt_buffer_after_restore()

    assert shown is True
    assert sets == [128], "must set the device-recommended size"
    assert not tools.buffer_prompt_pending(), "marker must be cleared after prompting"


def test_prompt_buffer_no_marker_no_prompt(wiz, monkeypatch):
    """(c) no marker => no prompt: the dialog is never shown and nothing is set."""
    tools = wiz.tools
    tools.clear_buffer_prompt_marker()
    assert not tools.buffer_prompt_pending()

    calls = []
    monkeypatch.setattr(
        tools.dialog, "select", lambda *a, **k: calls.append("select") or -1
    )
    monkeypatch.setattr(tools, "_set_cache_mb", lambda mb: calls.append("set") or True)

    shown = tools.prompt_buffer_after_restore()

    assert shown is False
    assert calls == [], "no marker must mean no dialog and no cache change"


def test_prompt_buffer_let_me_choose_opens_screen_and_clears(wiz, monkeypatch):
    """'Let me choose' routes to the existing Buffer Size screen and still clears the
    marker (so a manual choice also disarms the one-time prompt)."""
    tools = wiz.tools
    tools.mark_buffer_prompt_pending()

    opened = []
    monkeypatch.setattr(tools, "advancedSettings", lambda: opened.append(True))
    monkeypatch.setattr(
        tools,
        "_set_cache_mb",
        lambda mb: (_ for _ in ()).throw(
            AssertionError("must not auto-set on 'Let me choose'")
        ),
    )
    monkeypatch.setattr(tools.dialog, "select", lambda *a, **k: 1)

    shown = tools.prompt_buffer_after_restore()

    assert shown is True
    assert opened == [True]
    assert not tools.buffer_prompt_pending()


def test_prompt_buffer_keep_current_changes_nothing_but_clears(wiz, monkeypatch):
    """'Keep current' (or cancel) changes nothing yet still clears the marker."""
    tools = wiz.tools
    tools.mark_buffer_prompt_pending()

    monkeypatch.setattr(
        tools,
        "_set_cache_mb",
        lambda mb: (_ for _ in ()).throw(
            AssertionError("must not set the cache on 'Keep current'")
        ),
    )
    monkeypatch.setattr(
        tools,
        "advancedSettings",
        lambda: (_ for _ in ()).throw(
            AssertionError("must not open the screen on 'Keep current'")
        ),
    )
    monkeypatch.setattr(tools.dialog, "select", lambda *a, **k: 2)

    shown = tools.prompt_buffer_after_restore()

    assert shown is True
    assert not tools.buffer_prompt_pending()


def test_restore_no_wipe_still_overlays(wiz, monkeypatch, tmp_path):
    """(f) the normal (wipe=False) path is unchanged: it never wipes, it extracts, and it
    reaches the restart prompt."""
    onetap = _load_onetap()

    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(wiz.control, "HOME", str(home))

    wiped = []
    monkeypatch.setattr(onetap, "_wipe", lambda *a, **k: wiped.append(a))

    extracted = []
    monkeypatch.setattr(
        wiz, "ExtractWithProgress", lambda *a, **k: extracted.append(True) or False
    )
    restarted = []
    monkeypatch.setattr(wiz.ui, "ask_restart", lambda *a, **k: restarted.append(True))

    src = tmp_path / "backup.zip"
    _make_valid_zip(src, [("userdata/guisettings.xml", "<settings />")])

    wiz.restore(str(src), confirm=False, wipe=False)

    assert wiped == [], "the no-wipe path must never wipe"
    assert extracted == [True], "the no-wipe path must still extract"
    assert restarted == [True], "the no-wipe path must still offer a restart"
