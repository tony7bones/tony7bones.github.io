"""Coverage for script.ezmaintenanceplusplus's custom in-app settings screen.

Kodi's native Addon.OpenSettings dialog (CGUIDialogAddonSettings) is confirmed
broken in this add-on's real deployment: blank categories/controls, sometimes a
stale header naming whatever add-on's settings last loaded successfully - live-
confirmed on a real device across three different skins (this repo's patch,
stock MOD V2 Omega, stock Estuary) and on an unrelated, schema-valid, Kodi-team-
maintained add-on (inputstream.adaptive), including on a freshly wiped box. That
rules out this add-on's settings.xml/skin files; it is a Kodi engine bug, not
fixable from this repo. settings_menu.py bypasses CGUIDialogAddonSettings
entirely, reading/writing the exact same xbmcaddon.Addon().getSetting/setSetting
storage (aliased control.setting/setSetting) through plain xbmcgui dialogs.

This file fakes just enough of xbmc*/xbmcaddon/xbmcgui/xbmcvfs/xbmcplugin for
control.py + ui.py + settings_menu.py's import chain to succeed, backed by an
in-memory settings store and queued dialog responses, so the real module logic
runs end to end (not a reimplementation of it).
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

# The exact defaults resources/settings.xml declares - a faithful "fresh install"
# baseline so tests exercise the real inactive/active boundaries (e.g.
# autoCleanDays defaults to 0, so autoCleanHour starts out inactive).
_DEFAULTS = {
    "notify_mode": "false",
    "startup.cache": "true",
    "autoCleanDays": "0",
    "autoCleanHour": "4",
    "filesize_alert": "200",
    "packagenumbers_alert": "50",
    "filesizethumb_alert": "500",
    "BackupFixSpecialHome": "false",
    "destination": "0",
    "backup.keep": "5",
    "download.path": "",
    "restore.path": "",
    "dropbox_key": "",
    "dropbox_secret": "",
    "dropbox_refresh_token": "",
}


class _FakeDialog:
    """A queued xbmcgui.Dialog(): each response list is consumed in call order.
    Running out raises IndexError, so a test that under-queues fails loudly
    instead of silently reusing a stale response."""

    def __init__(self):
        self.select_queue = []
        self.input_queue = []
        self.browse_queue = []
        self.notifications = []

    def select(self, heading, options):
        return self.select_queue.pop(0)

    def input(self, prompt, default="", type=0):
        return self.input_queue.pop(0)

    def browse(
        self,
        type_,
        heading,
        shares,
        mask="",
        useThumbs=False,
        treatAsFolder=False,
        defaultt="",
    ):
        return self.browse_queue.pop(0)

    def notification(self, heading, message, icon=None, time_ms=4000, sound=False):
        self.notifications.append(message)

    def yesno(self, *a, **k):
        return False

    def ok(self, *a, **k):
        return True


@pytest.fixture
def env(monkeypatch):
    monkeypatch.syspath_prepend(str(ADDON_ROOT))
    for name in list(sys.modules):
        if name == "resources" or name.startswith("resources."):
            monkeypatch.delitem(sys.modules, name, raising=False)

    store = dict(_DEFAULTS)

    xbmc = types.ModuleType("xbmc")
    xbmc.translatePath = lambda p: p.replace("special://", "/fake/")
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
    xbmc.PLAYLIST_VIDEO = 1
    xbmc.sleep = lambda ms: None
    xbmc.Keyboard = lambda *a, **k: types.SimpleNamespace(
        doModal=lambda: None, isConfirmed=lambda: False, getText=lambda: ""
    )
    xbmc.PlayList = lambda *a, **k: types.SimpleNamespace(
        clear=lambda: None, add=lambda *a: None
    )
    xbmc.Player = lambda *a, **k: types.SimpleNamespace(play=lambda *a, **k: None)

    xbmcaddon = types.ModuleType("xbmcaddon")

    class _FakeAddon:
        def getLocalizedString(self, i):
            return str(i)

        def getSetting(self, key):
            return store.get(key, "")

        def setSetting(self, key, value):
            store[key] = value

        def getAddonInfo(self, key):
            return {
                "id": "script.ezmaintenanceplusplus",
                "name": "EZ Maintenance++",
                "path": str(ADDON_ROOT),
            }.get(key, "")

    xbmcaddon.Addon = _FakeAddon

    dialog = _FakeDialog()
    xbmcgui = types.ModuleType("xbmcgui")
    xbmcgui.Dialog = lambda: dialog
    xbmcgui.DialogProgress = lambda: types.SimpleNamespace(
        create=lambda *a, **k: None,
        update=lambda *a, **k: None,
        close=lambda: None,
        iscanceled=lambda: False,
    )
    xbmcgui.DialogProgressBG = xbmcgui.DialogProgress
    xbmcgui.WindowDialog = lambda *a, **k: types.SimpleNamespace()
    xbmcgui.Window = lambda *a, **k: types.SimpleNamespace(
        getProperty=lambda k: "", setProperty=lambda k, v: None
    )
    xbmcgui.ListItem = lambda *a, **k: types.SimpleNamespace(
        setArt=lambda *a, **k: None
    )
    xbmcgui.ControlButton = lambda *a, **k: None
    xbmcgui.ControlImage = lambda *a, **k: None
    xbmcgui.NOTIFICATION_INFO = "info"
    xbmcgui.NOTIFICATION_WARNING = "warning"
    xbmcgui.NOTIFICATION_ERROR = "error"
    xbmcgui.INPUT_ALPHANUM = 0
    xbmcgui.INPUT_NUMERIC = 1

    xbmcvfs = types.ModuleType("xbmcvfs")
    xbmcvfs.translatePath = xbmc.translatePath
    xbmcvfs.mkdir = lambda p: None
    xbmcvfs.delete = lambda p: None
    xbmcvfs.rmdir = lambda p: None
    xbmcvfs.listdir = lambda p: ([], [])
    xbmcvfs.exists = lambda p: False
    xbmcvfs.File = lambda *a, **k: types.SimpleNamespace(
        read=lambda *a: b"", write=lambda *a: True, close=lambda: None
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

    settings_menu = importlib.import_module("resources.lib.modules.settings_menu")
    return types.SimpleNamespace(
        settings_menu=settings_menu, store=store, dialog=dialog
    )


# --------------------------------------------------------------------------- #
# Row labels reflect current settings-store values
# --------------------------------------------------------------------------- #
def test_maintenance_row_labels_reflect_defaults(env):
    labels = [
        env.settings_menu._row_label(r) for r in env.settings_menu._MAINTENANCE_ROWS
    ]
    assert "Show Stats at Startup: Off" in labels
    assert "AutoClean Cache at Startup: On" in labels
    assert "Max Package Folder Size (MB): 200" in labels
    # autoCleanDays defaults to 0 ("0 is Not"), so autoCleanHour starts inactive.
    assert any(
        lbl.startswith("AutoClean Cache at Hour") and "[inactive" in lbl
        for lbl in labels
    )


def test_autoclean_hour_suffix_clears_once_days_nonzero(env):
    env.store["autoCleanDays"] = "3"
    labels = [
        env.settings_menu._row_label(r) for r in env.settings_menu._MAINTENANCE_ROWS
    ]
    hour_label = next(
        lbl for lbl in labels if lbl.startswith("AutoClean Cache at Hour")
    )
    assert "[inactive" not in hour_label


# --------------------------------------------------------------------------- #
# Boolean toggle
# --------------------------------------------------------------------------- #
def test_boolean_setting_toggles_and_persists(env):
    env.dialog.select_queue = [0, -1]  # pick notify_mode row, then exit
    env.settings_menu.open_maintenance_menu()
    assert env.store["notify_mode"] == "true"
    assert "Show Stats at Startup: On" in env.dialog.notifications


# --------------------------------------------------------------------------- #
# Bounded integer setting
# --------------------------------------------------------------------------- #
def test_integer_setting_valid_value_saves(env):
    env.dialog.select_queue = [4, -1]  # filesize_alert is row index 4
    env.dialog.input_queue = ["300"]
    env.settings_menu.open_maintenance_menu()
    assert env.store["filesize_alert"] == "300"
    assert "Max Package Folder Size (MB): 300" in env.dialog.notifications


def test_integer_setting_out_of_range_rejected(env):
    env.dialog.select_queue = [4, -1]
    env.dialog.input_queue = ["999"]  # max is 500
    env.settings_menu.open_maintenance_menu()
    assert env.store["filesize_alert"] == "200"  # unchanged
    assert env.dialog.notifications == ["Enter a whole number from 25 to 500"]


def test_integer_setting_non_numeric_rejected(env):
    env.dialog.select_queue = [4, -1]
    env.dialog.input_queue = ["abc"]
    env.settings_menu.open_maintenance_menu()
    assert env.store["filesize_alert"] == "200"
    assert env.dialog.notifications == ["Enter a whole number from 25 to 500"]


def test_integer_setting_cancelled_input_is_silent(env):
    env.dialog.select_queue = [4, -1]
    env.dialog.input_queue = [""]  # Kodi's input dialog returns "" on cancel
    env.settings_menu.open_maintenance_menu()
    assert env.store["filesize_alert"] == "200"
    assert env.dialog.notifications == []


# --------------------------------------------------------------------------- #
# Destination-conditional rows (Backup/Restore)
# --------------------------------------------------------------------------- #
def test_backup_rows_show_paths_when_destination_local(env):
    rows = env.settings_menu._backup_restore_rows()
    ids = [r["id"] for r in rows]
    assert "download.path" in ids
    assert "restore.path" in ids
    assert "dropbox_signin" not in ids
    assert "dropbox_key" not in ids
    assert "dropbox_secret" not in ids


def test_backup_rows_show_dropbox_fields_when_destination_dropbox(env):
    env.store["destination"] = "2"
    rows = env.settings_menu._backup_restore_rows()
    ids = [r["id"] for r in rows]
    assert "dropbox_signin" in ids
    assert "dropbox_key" in ids
    assert "dropbox_secret" in ids
    assert "download.path" not in ids
    assert "restore.path" not in ids


def test_destination_change_persists_and_updates_menu(env):
    # Pick the "Destination" row (index 1), choose "Dropbox" (index 2), exit.
    env.dialog.select_queue = [1, 2, -1]
    env.settings_menu.open_backup_restore_menu()
    assert env.store["destination"] == "2"
    assert "Destination: Dropbox" in env.dialog.notifications


# --------------------------------------------------------------------------- #
# Path setting (folder browse)
# --------------------------------------------------------------------------- #
def test_path_setting_browse_selection_saves(env):
    env.dialog.select_queue = [3, -1]  # download.path is row index 3 (Local mode)
    env.dialog.browse_queue = ["nfs://192.168.7.2/Users/moquette/Kodi/Backup/office/"]
    env.settings_menu.open_backup_restore_menu()
    assert (
        env.store["download.path"]
        == "nfs://192.168.7.2/Users/moquette/Kodi/Backup/office/"
    )
    assert "Backup Location set" in env.dialog.notifications


def test_path_setting_browse_cancelled_leaves_unset(env):
    env.dialog.select_queue = [3, -1]
    env.dialog.browse_queue = [""]
    env.settings_menu.open_backup_restore_menu()
    assert env.store["download.path"] == ""
    assert env.dialog.notifications == []


# --------------------------------------------------------------------------- #
# Dropbox sign-in re-uses the real authorize flow, not the broken native dialog
# --------------------------------------------------------------------------- #
def test_dropbox_signin_invokes_authorize(env, monkeypatch):
    calls = []
    fake_dropbox_remote = types.SimpleNamespace(authorize=lambda: calls.append(True))
    monkeypatch.setitem(
        sys.modules, "resources.lib.modules.dropbox_remote", fake_dropbox_remote
    )
    env.store["destination"] = "2"
    env.dialog.select_queue = [3, -1]  # dropbox_signin is row index 3 in Dropbox mode
    env.settings_menu.open_backup_restore_menu()
    assert calls == [True]


def test_dropbox_text_field_edit_saves(env):
    env.store["destination"] = "2"
    env.dialog.select_queue = [4, -1]  # dropbox_key is row index 4 in Dropbox mode
    env.dialog.input_queue = ["myappkey"]
    env.settings_menu.open_backup_restore_menu()
    assert env.store["dropbox_key"] == "myappkey"


def test_dropbox_text_field_cancel_does_not_wipe_existing_value(env):
    # Kodi's input dialog returns "" for BOTH a cancel and a confirmed-empty
    # entry - opening an already-configured field and backing out must not
    # silently blank it.
    env.store["destination"] = "2"
    env.store["dropbox_key"] = "already-configured-key"
    env.dialog.select_queue = [4, -1]
    env.dialog.input_queue = [""]
    env.settings_menu.open_backup_restore_menu()
    assert env.store["dropbox_key"] == "already-configured-key"
    assert env.dialog.notifications == []


# --------------------------------------------------------------------------- #
# Never expose the One-Tap Restore pin slots or the Dropbox refresh token
# --------------------------------------------------------------------------- #
def test_pin_slots_and_refresh_token_never_exposed(env):
    all_ids = {r["id"] for r in env.settings_menu._MAINTENANCE_ROWS}
    for destination in ("0", "1", "2"):
        env.store["destination"] = destination
        all_ids |= {r["id"] for r in env.settings_menu._backup_restore_rows()}
    assert "dropbox_refresh_token" not in all_ids
    assert not any(i.startswith("pin") for i in all_ids)


# --------------------------------------------------------------------------- #
# Top-level entry point
# --------------------------------------------------------------------------- #
def test_open_settings_menu_dispatches_to_backup_restore(env):
    env.dialog.select_queue = [
        0,
        -1,
        -1,
    ]  # top: Backup/Restore -> submenu exit -> top exit
    env.settings_menu.open_settings_menu()
    assert env.dialog.select_queue == []


def test_open_settings_menu_dispatches_to_maintenance(env):
    env.dialog.select_queue = [
        1,
        -1,
        -1,
    ]  # top: Maintenance -> submenu exit -> top exit
    env.settings_menu.open_settings_menu()
    assert env.dialog.select_queue == []


def test_open_settings_menu_exits_immediately_on_cancel(env):
    env.dialog.select_queue = [-1]
    env.settings_menu.open_settings_menu()
    assert env.dialog.select_queue == []
