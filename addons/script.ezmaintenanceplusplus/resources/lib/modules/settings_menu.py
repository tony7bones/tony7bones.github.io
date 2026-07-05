"""
EZ Maintenance++ : custom in-app settings screen.

Kodi's native add-on settings dialog (CGUIDialogAddonSettings) is broken in this
add-on's real-world environment: it renders a blank canvas (categories/controls
never populate) and can show a stale header naming whatever add-on's settings last
loaded successfully. Live-confirmed on a real device across three different skins
(this repo's patch, stock MOD V2 Omega, stock Estuary) and on an unrelated,
schema-valid, Kodi-team-maintained add-on (inputstream.adaptive) - including on a
freshly wiped box. That rules out this add-on's settings.xml and any skin file as
the cause; it is a Kodi engine-level bug, not fixable from here.

This module bypasses CGUIDialogAddonSettings entirely. It reads/writes the exact
same underlying settings storage the broken dialog would have
(xbmcaddon.Addon().getSetting/setSetting, aliased as control.setting/setSetting -
already proven live: wiz.py has always read destination/download.path/restore.path
this same way) through the add-on's own plain xbmcgui menu system, which has
worked throughout this whole add-on regardless of the dialog bug.

resources/settings.xml is unchanged in meaning - it still defines the schema/
defaults Kodi loads from disk; only its on-screen rendering is broken. The 50
One-Tap Restore pin slots are managed by their own working ONE-TAP RESTORE menu,
and dropbox_refresh_token is an internal secret set only by the Dropbox sign-in
flow - neither is exposed here.
"""

from resources.lib.modules import control, ui

_DESTINATION_LABELS = ["Local", "Network (SMB/NFS)", "Dropbox"]


def _bool(setting_id):
    return control.setting(setting_id) == "true"


def _set_bool(setting_id, value):
    control.setSetting(setting_id, "true" if value else "false")


def _int(setting_id):
    try:
        return int(control.setting(setting_id))
    except (TypeError, ValueError):
        return 0


def _destination():
    idx = _int("destination")
    return idx if 0 <= idx < len(_DESTINATION_LABELS) else 0


def _dropbox_authorize():
    from resources.lib.modules import dropbox_remote

    dropbox_remote.authorize()


def _spec(setting_id, kind, label, **extra):
    row = {"id": setting_id, "kind": kind, "label": label}
    row.update(extra)
    return row


_MAINTENANCE_ROWS = [
    _spec("notify_mode", "boolean", "Show Stats at Startup"),
    _spec("startup.cache", "boolean", "AutoClean Cache at Startup"),
    _spec(
        "autoCleanDays",
        "integer",
        "AutoClean Cache Every Number of Days (0 is Not)",
        minimum=0,
        maximum=365,
    ),
    _spec(
        "autoCleanHour",
        "integer",
        "AutoClean Cache at Hour (0-12 = AM / 12-23 = PM)",
        minimum=0,
        maximum=23,
    ),
    _spec(
        "filesize_alert",
        "integer",
        "Max Package Folder Size (MB)",
        minimum=25,
        maximum=500,
    ),
    _spec(
        "packagenumbers_alert",
        "integer",
        "Max Number of Zip Files",
        minimum=5,
        maximum=200,
    ),
    _spec(
        "filesizethumb_alert",
        "integer",
        "Max Thumbnails Folder Size (MB)",
        minimum=50,
        maximum=2000,
    ),
]


def _backup_restore_rows():
    rows = [
        _spec(
            "BackupFixSpecialHome",
            "boolean",
            "Replace home folder in xml files with special://home",
        ),
        _spec("destination", "enum", "Destination", options=_DESTINATION_LABELS),
        _spec(
            "backup.keep",
            "integer",
            "Keep how many backups (0 = keep all)",
            minimum=0,
            maximum=50,
        ),
    ]
    if _destination() == 2:
        rows.append(
            _spec(
                "dropbox_signin",
                "action",
                "Sign in to Dropbox",
                action=_dropbox_authorize,
            )
        )
        rows.append(_spec("dropbox_key", "text", "Dropbox App key (advanced)"))
        rows.append(_spec("dropbox_secret", "text", "Dropbox App secret (advanced)"))
    else:
        rows.append(_spec("download.path", "path", "Backup Location"))
        rows.append(_spec("restore.path", "path", "Restore from Zip Location (folder)"))
    return rows


def _row_label(row):
    setting_id, kind, label = row["id"], row["kind"], row["label"]
    if kind == "boolean":
        return "%s: %s" % (label, "On" if _bool(setting_id) else "Off")
    if kind == "integer":
        suffix = ""
        if setting_id == "autoCleanHour" and _int("autoCleanDays") == 0:
            suffix = " [inactive - AutoClean Days is 0]"
        return "%s: %s%s" % (label, _int(setting_id), suffix)
    if kind == "enum":
        return "%s: %s" % (label, row["options"][_destination()])
    if kind == "path":
        return "%s: %s" % (label, control.setting(setting_id) or "(not set)")
    if kind == "text":
        return "%s: %s" % (label, control.setting(setting_id) or "(blank)")
    return label  # "action"


def _edit_row(row):
    setting_id, kind, label = row["id"], row["kind"], row["label"]
    if kind == "boolean":
        _set_bool(setting_id, not _bool(setting_id))
        ui.notify("%s: %s" % (label, "On" if _bool(setting_id) else "Off"))
    elif kind == "integer":
        value = ui.ask_int(label, _int(setting_id), row["minimum"], row["maximum"])
        if value is not None:
            control.setSetting(setting_id, str(value))
            ui.notify("%s: %s" % (label, value))
    elif kind == "enum":
        options = row["options"]
        idx = ui.choose(options, heading=label)
        if idx != -1:
            control.setSetting(setting_id, str(idx))
            ui.notify("%s: %s" % (label, options[idx]))
    elif kind == "path":
        chosen = ui.browse_folder(label, control.setting(setting_id))
        if chosen:
            control.setSetting(setting_id, chosen)
            ui.notify("%s set" % label)
    elif kind == "text":
        # Kodi's input dialog returns "" for BOTH a cancel and a confirmed-empty
        # entry - there is no way to tell them apart from the return value alone.
        # Treat "" as "no change" (like every other row kind's cancel path),
        # rather than silently blanking an already-configured value.
        entered = ui.ask(label, control.setting(setting_id))
        if entered:
            control.setSetting(setting_id, entered)
            ui.notify("%s set" % label)
    elif kind == "action":
        row["action"]()


def _run_menu(heading, rows_fn):
    while True:
        rows = rows_fn()
        idx = ui.choose([_row_label(r) for r in rows], heading=heading)
        if idx == -1:
            return
        _edit_row(rows[idx])


def open_maintenance_menu():
    _run_menu("Maintenance Settings", lambda: _MAINTENANCE_ROWS)


def open_backup_restore_menu():
    _run_menu("Backup/Restore Settings", _backup_restore_rows)


def open_settings_menu():
    """Entry point: the custom settings screen shown instead of Kodi's broken
    native Addon.OpenSettings dialog. Loops until the user backs all the way out."""
    while True:
        idx = ui.choose(
            ["Backup/Restore Settings", "Maintenance Settings"],
            heading="EZ Maintenance++ Settings",
        )
        if idx == -1:
            return
        if idx == 0:
            open_backup_restore_menu()
        else:
            open_maintenance_menu()
