"""Platform detection, restart, and self-uninstall primitives.

These wrap the parts of the install flow that touch Kodi's process / platform:
detecting the binary-add-on platform tag, whether we are on Android (where the
app cannot relaunch itself), removing the calling Setup add-on's own directory,
and the end-of-setup restart. They are identical between the two Setups, so they
live here once.
"""

import json
import os

import xbmc
import xbmcgui
import xbmcvfs


def platform_tag():
    """Kodi's platform/arch tag for binary add-ons, e.g. 'osx-arm64'.

    Mirrors the way the official repo names its platform-specific datadirs
    (<id>+<platform>-<arch>/). Detected at runtime from os.uname()/os.name so the
    correct native build is selected on any machine. Returns None on platforms
    whose binaries are not served from this mirror (e.g. desktop Linux, which
    ships binary add-ons via the OS package manager).
    """
    name = os.name
    try:
        sysname = os.uname().sysname.lower()
        machine = os.uname().machine.lower()
    except AttributeError:  # Windows has no os.uname()
        sysname = ""
        import platform as _platform

        machine = _platform.machine().lower()

    if sysname == "darwin":
        arch = "arm64" if machine in ("arm64", "aarch64") else "x86_64"
        return f"osx-{arch}"
    if name == "nt" or sysname.startswith("win"):
        # Kodi tags: windows-x86_64 (64-bit) / windows-i686 (32-bit).
        return "windows-x86_64" if machine in ("amd64", "x86_64") else "windows-i686"
    if "android" in sysname or os.environ.get("ANDROID_ROOT"):
        return "android-aarch64" if machine in ("aarch64", "arm64") else "android-armv7"
    # Linux/other: binaries come from the distro, not this mirror.
    return None


def is_android():
    """True when running on Android (incl. Fire Stick), where the app cannot
    relaunch itself. Detected the same way as platform_tag()."""
    if os.environ.get("ANDROID_ROOT") or os.environ.get("ANDROID_DATA"):
        return True
    try:
        return "android" in os.uname().sysname.lower()
    except AttributeError:  # Windows
        return False


def self_uninstall(addon_id, log):
    """Remove a Setup add-on's own directory so it leaves no permanent home tile.

    Kodi 21 Omega has NO uninstall path a script can call: there is no
    UninstallAddon executebuiltin (only install/enable/disable/run exist) and no
    JSON-RPC uninstall method (the Addons namespace exposes only GetAddons /
    GetAddonDetails / SetAddonEnabled / ExecuteAddon). The supported mechanism is
    therefore: delete the add-on's own directory, then let the end-of-setup
    restart finalise removal. On the next start Kodi's add-on scan
    (CAddonMgr::FindAddons) skips the now-missing dir and
    AddonDatabase::SyncInstalled deletes the stale rows — so there is no dangling
    DB row and no "broken add-on".

    Defensive by design: callers run this only after everything else succeeded,
    it never raises (a failure here must not abort the run), and it deletes ONLY
    the add-on directory whose basename matches `addon_id` — nothing else.
    """
    try:
        my_dir = xbmcvfs.translatePath("special://home/addons/" + addon_id)
        # Hard guard: only ever delete the caller's OWN add-on directory.
        if os.path.basename(os.path.normpath(my_dir)) != addon_id:
            log(f"self-uninstall: refusing unexpected path {my_dir}", xbmc.LOGERROR)
            return
        if os.path.isdir(my_dir):
            import shutil

            shutil.rmtree(my_dir, ignore_errors=True)
            log(f"self-uninstall: removed {my_dir}", xbmc.LOGINFO)
    except Exception as e:  # noqa: BLE001 - self-uninstall must never abort the run
        log(f"self-uninstall failed (non-fatal): {e}", xbmc.LOGERROR)


def activate_skin(skin_id, log):
    """Switch the active skin to skin_id AND accept Kodi's "Keep this skin?"
    confirmation so the change PERSISTS across the end-of-setup restart.

    Setting lookandfeel.skin live triggers a skin reload and pops a yes/no confirm
    (window 10100) that DEFAULTS TO REVERT on its timeout. If it is not accepted
    before Kodi restarts/quits, Kodi rolls the skin back to the previous one — so
    the box boots stock Estuary instead of MOD V2 (a real Fire TV install hit
    exactly this). We set the skin, wait for the confirm to appear, then click its
    Yes button (control 11 of the yes/no dialog) so the change commits, and let it
    settle before the caller restarts. Verified on a real Fire TV: control 11 keeps
    the skin with no revert.
    """
    xbmc.executeJSONRPC(
        json.dumps(
            {
                "jsonrpc": "2.0",
                "method": "Settings.SetSettingValue",
                "params": {"setting": "lookandfeel.skin", "value": skin_id},
                "id": 1,
            }
        )
    )
    for _ in range(24):  # up to ~12s for the confirm to render
        if xbmc.getCondVisibility("Window.IsVisible(10100)"):
            xbmc.executebuiltin("SendClick(11)")  # control 11 == Yes (keep)
            log(
                "activate_skin: accepted keep-skin for {}".format(skin_id),
                xbmc.LOGINFO,
            )
            break
        xbmc.sleep(500)
    else:
        log(
            "activate_skin: no keep-skin dialog appeared for {}".format(skin_id),
            xbmc.LOGINFO,
        )
    xbmc.sleep(2000)  # let the keep commit + the skin settle before the restart


def restart_kodi(title, log):
    """Restart Kodi the platform-correct way after setup completes.

    A restart is required so Kodi fully loads every freshly extracted add-on
    (avoids the Fire Stick end-of-setup freeze where half-registered add-ons
    leave the UI wedged) and so stamped origins / language resources are live on
    first launch. The user always chooses Restart now / Later.

    * Desktop (Windows / Linux / macOS): RestartApp() truly cycles the app.
    * Android / Fire Stick: RestartApp() is a no-op (it is "only implemented under
      Windows and Linux"), so Kodi cannot relaunch itself — the user reopens it by
      hand and the boot service finishes setup. We do NOT show a blocking prompt
      here: the skin was just set live, so any time spent waiting lets Kodi's
      "Keep this skin?" timeout revert it to stock, and the half-rendered new skin
      can wedge the GUI so a yes/no never clears (the "it hangs, force-kill it"
      symptom). Instead we show a non-blocking notice and Quit() promptly. Quit is
      a CLEAN shutdown — it flushes the skin choice + all skin settings to disk —
      and a hard kill (os._exit / killall) is deliberately avoided because it would
      lose those unsaved settings.
    """
    if is_android():
        log("restart: Android clean Quit() (prompt-free)", xbmc.LOGINFO)
        xbmcgui.Dialog().notification(
            title,
            "Setup complete — closing Kodi. Reopen it to finish.",
            xbmcgui.NOTIFICATION_INFO,
            6000,
        )
        xbmc.sleep(3000)  # let the notice render; well under the skin-revert window
        xbmc.executebuiltin("Quit")
        return

    if xbmcgui.Dialog().yesno(
        title,
        "Setup is complete. Kodi needs to restart to finish.\n\nRestart now?",
        yeslabel="Restart now",
        nolabel="Later",
    ):
        log("restart: RestartApp()", xbmc.LOGINFO)
        xbmc.executebuiltin("RestartApp()")
