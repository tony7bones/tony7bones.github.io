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
    """
    applied = 0
    failed = 0

    for fname in FILES:
        src = os.path.join(ADDON_PATH, "resources", "xml", fname)
        dst = os.path.join(skin_xml, fname)
        bak = dst + ".bak"

        try:
            if os.path.exists(dst) and not os.path.exists(bak):
                shutil.copy2(dst, bak)
            shutil.copy2(src, dst)
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
            shutil.copy2(src, dst)
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
                shutil.copy2(bak, dst)
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


def set_weather_icons():
    """Point MOD V2's weather widgets (home tab + top bar) at the Outline HD set.

    MOD V2 resolves its weather icons through the Skin.String(WeatherIcons.path)
    / WeatherIcons.name pair — the same strings its built-in icon picker sets;
    when they're empty it falls back to the .default pack (the bug). Setting them
    drives the home weather widget AND the top-bar condition icon. Defensive:
    logged, never aborts the run.
    """
    try:
        xbmc.executebuiltin(
            "Skin.SetString(WeatherIcons.path,"
            "resource://resource.images.weathericons.outline-hd/)"
        )
        xbmc.executebuiltin(
            "Skin.SetString(WeatherIcons.name,Weather Icons - Outline HD)"
        )
        xbmc.log("[mod v2+] weather icons -> Outline HD", xbmc.LOGINFO)
    except Exception as e:
        xbmc.log("[mod v2+] failed setting weather icons: {}".format(e), xbmc.LOGERROR)


def reset_weather_icons():
    """Clear the weather-icon skin strings so MOD V2 reverts to its default pack."""
    try:
        xbmc.executebuiltin("Skin.Reset(WeatherIcons.path)")
        xbmc.executebuiltin("Skin.Reset(WeatherIcons.name)")
        xbmc.log("[mod v2+] weather icons reset", xbmc.LOGINFO)
    except Exception as e:
        xbmc.log(
            "[mod v2+] failed resetting weather icons: {}".format(e), xbmc.LOGERROR
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
    set_weather_icons()
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
    reset_weather_icons()
    xbmc.executebuiltin("ReloadSkin()")


if __name__ == "__main__":
    run()
