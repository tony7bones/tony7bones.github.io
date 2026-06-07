import os
import shutil
import sys
import xbmc
import xbmcgui
import xbmcaddon

try:
    from xbmcvfs import translatePath
except ImportError:
    from xbmc import translatePath

ADDON = xbmcaddon.Addon()
ADDON_PATH = translatePath(ADDON.getAddonInfo("path"))
SKIN_ID = "skin.estuary.modv2"

# XML files copied into the skin's xml/ dir (one-time .bak, then overwrite).
FILES = [
    "Home.xml",
    "SkinSettings.xml",
    "Settings.xml",
    "Includes.xml",
    "Variables.xml",
]

# Loose media assets copied to a path OUTSIDE xml/. Each entry maps a source
# (relative to ADDON_PATH) to a destination (relative to the skin root), both as
# forward-slash POSIX paths normalized at use. These are NEW files in the skin
# (no .bak); Restore deletes them.
MEDIA = [
    (
        "resources/media/extras/logo-text-hires.png",
        "media/extras/logo-text-hires.png",
    ),
]


def apply_patches(skin_xml):
    """Copy each XML in FILES into the skin's xml/ dir.

    The original is snapshotted once as ``<file>.bak`` before the first
    overwrite. Each file is handled defensively: a failure is logged and never
    aborts the run. Returns (applied, failed).

    NB: use ``shutil.copyfile`` (content only), NOT ``copy2``. On Fire OS 8 /
    Android 11 the skin lives on an sdcardfs/FUSE volume where copy2's copystat
    (os.utime / os.chmod) raises OSError(EPERM) *after* the bytes are written —
    which made every copy count as "failed", tripping the "Partly Applied" early
    return before the menu-trim + skin-settings steps. copyfile skips copystat.
    """
    applied = 0
    failed = 0

    for fname in FILES:
        src = os.path.join(ADDON_PATH, "resources", "xml", fname)
        dst = os.path.join(skin_xml, fname)
        bak = dst + ".bak"

        try:
            if os.path.exists(dst) and not os.path.exists(bak):
                shutil.copyfile(dst, bak)
            shutil.copyfile(src, dst)
            applied += 1
            xbmc.log("[mod v2+] applied {}".format(fname), xbmc.LOGINFO)
        except Exception as e:
            xbmc.log("[mod v2+] failed {}: {}".format(fname, e), xbmc.LOGERROR)
            failed += 1

    return applied, failed


def apply_media(skin_root):
    """Copy each loose MEDIA asset into the skin (a NEW file — no .bak).

    Creates the destination directory as needed and overwrites. Each entry is
    handled defensively. Returns (applied, failed).
    """
    applied = 0
    failed = 0

    for rel_src, rel_dst in MEDIA:
        src = os.path.join(ADDON_PATH, *rel_src.split("/"))
        dst = os.path.join(skin_root, *rel_dst.split("/"))

        try:
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copyfile(src, dst)
            applied += 1
            xbmc.log("[mod v2+] applied media {}".format(rel_dst), xbmc.LOGINFO)
        except Exception as e:
            xbmc.log("[mod v2+] failed media {}: {}".format(rel_dst, e), xbmc.LOGERROR)
            failed += 1

    return applied, failed


def restore_patches(skin_xml):
    """Revert the patched XML files to their pre-patch originals.

    For each file in FILES, if a one-time ``<file>.bak`` snapshot exists, copy
    it back over the live file and remove the .bak. Files with no .bak are
    counted as skipped. Each file is handled defensively. Returns
    (restored, failed, skipped).
    """
    restored = 0
    failed = 0
    skipped = 0

    for fname in FILES:
        dst = os.path.join(skin_xml, fname)
        bak = dst + ".bak"

        try:
            if os.path.exists(bak):
                shutil.copyfile(bak, dst)
                os.remove(bak)
                restored += 1
                xbmc.log("[mod v2+] restored {}".format(fname), xbmc.LOGINFO)
            else:
                skipped += 1
                xbmc.log(
                    "[mod v2+] no backup for {}, skipped".format(fname),
                    xbmc.LOGINFO,
                )
        except Exception as e:
            xbmc.log(
                "[mod v2+] failed restoring {}: {}".format(fname, e),
                xbmc.LOGERROR,
            )
            failed += 1

    return restored, failed, skipped


def restore_media(skin_root):
    """Remove the loose MEDIA assets we added (they didn't exist originally).

    A missing file is treated as already-removed (skipped). Each entry is
    handled defensively. Returns (removed, failed, skipped).
    """
    removed = 0
    failed = 0
    skipped = 0

    for _rel_src, rel_dst in MEDIA:
        dst = os.path.join(skin_root, *rel_dst.split("/"))

        try:
            if os.path.exists(dst):
                os.remove(dst)
                removed += 1
                xbmc.log("[mod v2+] removed media {}".format(rel_dst), xbmc.LOGINFO)
            else:
                skipped += 1
                xbmc.log(
                    "[mod v2+] media {} absent, skipped".format(rel_dst),
                    xbmc.LOGINFO,
                )
        except Exception as e:
            xbmc.log(
                "[mod v2+] failed removing media {}: {}".format(rel_dst, e),
                xbmc.LOGERROR,
            )
            failed += 1

    return removed, failed, skipped


def _clear_skinshortcuts_cache():
    """Delete script.skinshortcuts' built data for this skin so it re-seeds the
    home menu from our shipped shortcuts/mainmenu.DATA.xml default.

    Removes every file under special://profile/addon_data/script.skinshortcuts/
    whose name starts with the skin id (the built menu DATA + properties + hash).
    This wipes any user menu customizations — intended for our opinionated default;
    Restore reverts it by rebuilding from the restored full default. Defensive:
    a missing dir is fine, each removal is logged, failures never abort the run.
    Returns the number of files removed.
    """
    removed = 0
    try:
        cache_dir = translatePath("special://profile/addon_data/script.skinshortcuts/")
        if not os.path.isdir(cache_dir):
            xbmc.log(
                "[mod v2+] skinshortcuts cache dir absent, nothing to clear",
                xbmc.LOGINFO,
            )
            return 0
        for name in os.listdir(cache_dir):
            if not name.startswith(SKIN_ID):
                continue
            path = os.path.join(cache_dir, name)
            try:
                if os.path.isfile(path):
                    os.remove(path)
                    removed += 1
                    xbmc.log(
                        "[mod v2+] cleared skinshortcuts {}".format(name),
                        xbmc.LOGINFO,
                    )
            except Exception as e:
                xbmc.log(
                    "[mod v2+] failed clearing skinshortcuts {}: {}".format(name, e),
                    xbmc.LOGERROR,
                )
    except Exception as e:
        xbmc.log(
            "[mod v2+] failed clearing skinshortcuts cache: {}".format(e),
            xbmc.LOGERROR,
        )
    return removed


def apply_home_menu(skin_root):
    """Install our trimmed home menu over the skin's skinshortcuts default.

    Copies resources/shortcuts/mainmenu.DATA.xml -> <skin_root>/shortcuts/
    mainmenu.DATA.xml, taking a one-time mainmenu.DATA.xml.bak of the original
    first (creating the shortcuts dir if needed), then clears skinshortcuts' built
    data so the menu re-seeds from our trimmed default. Defensive: logged, never
    aborts the run. Returns True if the default was copied.
    """
    src = os.path.join(ADDON_PATH, "resources", "shortcuts", "mainmenu.DATA.xml")
    dst_dir = os.path.join(skin_root, "shortcuts")
    dst = os.path.join(dst_dir, "mainmenu.DATA.xml")
    bak = dst + ".bak"

    try:
        os.makedirs(dst_dir, exist_ok=True)
        if os.path.exists(dst) and not os.path.exists(bak):
            shutil.copyfile(dst, bak)
        shutil.copyfile(src, dst)
        xbmc.log(
            "[mod v2+] applied home menu (trimmed mainmenu.DATA.xml)", xbmc.LOGINFO
        )
        _clear_skinshortcuts_cache()
        return True
    except Exception as e:
        xbmc.log("[mod v2+] failed applying home menu: {}".format(e), xbmc.LOGERROR)
        return False


def restore_home_menu(skin_root):
    """Revert the home menu to the skin's original full default.

    If a mainmenu.DATA.xml.bak snapshot exists, copy it back over
    mainmenu.DATA.xml and remove the .bak, then clear skinshortcuts' built data
    so the menu rebuilds from the restored full default. Defensive: logged, never
    aborts the run. Returns True if a backup was restored.
    """
    dst = os.path.join(skin_root, "shortcuts", "mainmenu.DATA.xml")
    bak = dst + ".bak"

    restored = False
    try:
        if os.path.exists(bak):
            shutil.copyfile(bak, dst)
            os.remove(bak)
            restored = True
            xbmc.log(
                "[mod v2+] restored home menu (original mainmenu.DATA.xml)",
                xbmc.LOGINFO,
            )
        else:
            xbmc.log("[mod v2+] no home-menu backup, skipped restore", xbmc.LOGINFO)
    except Exception as e:
        xbmc.log("[mod v2+] failed restoring home menu: {}".format(e), xbmc.LOGERROR)
    # Clear the built data regardless so the menu rebuilds from whatever default
    # is now in place (restored original, or the skin's own if no backup existed).
    _clear_skinshortcuts_cache()
    return restored


def run():
    if xbmc.getSkinDir() != SKIN_ID:
        xbmcgui.Dialog().ok(
            "Wrong Skin",
            "This only runs on Estuary MOD V2.[CR]Switch skins and run again.",
        )
        return

    skin_root = translatePath("special://home/addons/{}".format(SKIN_ID))
    skin_xml = os.path.join(skin_root, "xml")

    if not os.path.isdir(skin_xml):
        xbmcgui.Dialog().ok(
            "Failed",
            "{} not found.[CR]Install it first, then run this script.".format(SKIN_ID),
        )
        return

    # Direct-action routing: RunScript(...,apply) / RunScript(...,restore) run the
    # matching path straight away (used by the in-tab Apply / Restore buttons in
    # the "Tony.7.Bones MOD V2+" Skin Settings category). With no/unknown arg we
    # fall back to the interactive chooser.
    arg = sys.argv[1].strip().lower() if len(sys.argv) > 1 and sys.argv[1] else ""
    if arg == "apply":
        _apply(skin_root, skin_xml)
        return
    if arg == "restore":
        _restore(skin_root, skin_xml)
        return

    choice = xbmcgui.Dialog().select(
        "Estuary MOD V2+", ["Apply patches", "Restore original"]
    )

    if choice == 0:
        _apply(skin_root, skin_xml)
    elif choice == 1:
        _restore(skin_root, skin_xml)
    # choice == -1 (cancelled / back) -> do nothing


def apply_skin_settings():
    """Apply our MOD V2 skin-setting defaults (the parts that aren't shipped files).

    - Weather icons -> the Outline HD pack via Skin.String(WeatherIcons.path) /
      WeatherIcons.name (the strings MOD V2's own picker sets; empty -> .default).
    - Top-bar weather/temp readout ON (`show_weatherinfo`) — MOD V2 leaves it OFF
      on a fresh skin, so a freshly-patched box shows the weather below the clock.
    - Splash screen OFF and seasonal Themes OFF. Both are MOD V2 **opt-out** flags
      (the toggles read `!Skin.HasSetting(...)`), so *setting* `EnableSplashScreen`
      / `DisableThemes` is what turns them off.
    - Power menu style -> "Classic list" (`powermenu_list`; the style is an
      exclusive group, so clear the other two flags `powermenu_panel` /
      `powermenu_iconlist`).
    Defensive: logged, never aborts the run.
    """
    try:
        xbmc.executebuiltin(
            "Skin.SetString(WeatherIcons.path,"
            "resource://resource.images.weathericons.outline-hd/)"
        )
        xbmc.executebuiltin(
            "Skin.SetString(WeatherIcons.name,Weather Icons - Outline HD)"
        )
        xbmc.executebuiltin("Skin.SetBool(show_weatherinfo)")
        xbmc.executebuiltin("Skin.SetBool(EnableSplashScreen)")
        xbmc.executebuiltin("Skin.SetBool(DisableThemes)")
        # Power menu style -> "Classic list" (exclusive group: clear the other two)
        xbmc.executebuiltin("Skin.SetBool(powermenu_list)")
        xbmc.executebuiltin("Skin.Reset(powermenu_panel)")
        xbmc.executebuiltin("Skin.Reset(powermenu_iconlist)")
        xbmc.log("[mod v2+] skin settings applied", xbmc.LOGINFO)
    except Exception as e:
        xbmc.log("[mod v2+] failed applying skin settings: {}".format(e), xbmc.LOGERROR)


def reset_skin_settings():
    """Revert our skin-setting defaults to MOD V2 stock: clear the weather icon
    strings, turn the top-bar readout back off, and clear the splash / themes /
    power-menu flags so they return to MOD V2's defaults."""
    try:
        for s in (
            "WeatherIcons.path",
            "WeatherIcons.name",
            "show_weatherinfo",
            "EnableSplashScreen",
            "DisableThemes",
            "powermenu_list",
            "powermenu_panel",
            "powermenu_iconlist",
        ):
            xbmc.executebuiltin("Skin.Reset({})".format(s))
        xbmc.log("[mod v2+] skin settings reset", xbmc.LOGINFO)
    except Exception as e:
        xbmc.log(
            "[mod v2+] failed resetting skin settings: {}".format(e), xbmc.LOGERROR
        )


def _apply(skin_root, skin_xml):
    applied, failed = apply_patches(skin_xml)
    media_applied, media_failed = apply_media(skin_root)

    total_failed = failed + media_failed
    if total_failed > 0:
        xbmcgui.Dialog().ok(
            "Partly Applied",
            "{} files + {} media applied, {} failed.[CR]Check the Kodi log.".format(
                applied, media_applied, total_failed
            ),
        )
        return

    # Non-blocking: notify and reload immediately. A modal ok() here would block
    # the reload until the user clicked it (while claiming to be reloading).
    xbmcgui.Dialog().notification(
        "Estuary MOD V2+",
        "Applied {} files + {} media — reloading skin".format(applied, media_applied),
        xbmcgui.NOTIFICATION_INFO,
        4000,
    )
    apply_skin_settings()
    apply_home_menu(skin_root)
    xbmc.executebuiltin("ReloadSkin()")


def _restore(skin_root, skin_xml):
    if not xbmcgui.Dialog().yesno(
        "Restore stock MOD V2",
        "This reverts all Tony.7.Bones tweaks and restores the original "
        "MOD V2 skin files.[CR]Continue?",
    ):
        return
    restored, failed, _skipped = restore_patches(skin_xml)
    media_removed, media_failed, _media_skipped = restore_media(skin_root)

    if restored == 0 and media_removed == 0:
        xbmcgui.Dialog().ok(
            "Nothing to Restore",
            "No backups found.[CR]Estuary MOD V2 is already unpatched.",
        )
        return

    total_failed = failed + media_failed
    if total_failed:
        # Blocking only when there's a failure the user should read.
        xbmcgui.Dialog().ok(
            "Original Restored",
            "Restored {} files, removed {} media.[CR]{} could not be reverted "
            "— check the Kodi log.".format(restored, media_removed, total_failed),
        )
    else:
        xbmcgui.Dialog().notification(
            "Estuary MOD V2+",
            "Restored {} files, removed {} media — reloading skin".format(
                restored, media_removed
            ),
            xbmcgui.NOTIFICATION_INFO,
            4000,
        )
    reset_skin_settings()
    restore_home_menu(skin_root)
    xbmc.executebuiltin("ReloadSkin()")


if __name__ == "__main__":
    run()
