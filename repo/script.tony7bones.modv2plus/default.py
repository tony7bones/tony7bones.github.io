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

# Loose media DIRECTORIES copied wholesale into the skin. Each entry maps a
# source dir (relative to ADDON_PATH) to a destination dir (relative to the skin
# root). These are NEW directories in the skin (no .bak); Restore deletes them
# entirely. Used for the stock-white weather condition icon set that replaces
# MOD V2's own coloured extras/weather/ art (we point Includes.xml at
# extras/weather-stock/ so MOD V2's set is left untouched and Restore is clean).
#
# NOTE the destination is the skin ROOT's extras/ (NOT media/extras/): the
# Includes.xml texture uses special://skin/extras/weather-stock/, which Kodi
# resolves against the skin root — that's where MOD V2's own extras/weather/
# lives. (The logo MEDIA entry above lands under media/extras/ because Home.xml
# texture refs are resolved relative to the skin's media/ dir; special://skin/ is
# the skin root. Two different bases — don't conflate them.)
MEDIA_DIRS = [
    (
        "resources/media/extras/weather-stock",
        "extras/weather-stock",
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


def apply_media_dirs(skin_root):
    """Copy each loose MEDIA_DIRS source directory into the skin (NEW dirs — no
    .bak). The destination dir is created/refreshed and the source contents are
    copied in, overwriting. Each entry is handled defensively. Returns
    (applied, failed) counted in directories.
    """
    applied = 0
    failed = 0

    for rel_src, rel_dst in MEDIA_DIRS:
        src = os.path.join(ADDON_PATH, *rel_src.split("/"))
        dst = os.path.join(skin_root, *rel_dst.split("/"))

        try:
            os.makedirs(dst, exist_ok=True)
            count = 0
            for name in os.listdir(src):
                s = os.path.join(src, name)
                if os.path.isfile(s):
                    shutil.copy2(s, os.path.join(dst, name))
                    count += 1
            applied += 1
            xbmc.log(
                "[mod v2+] applied media dir {} ({} files)".format(rel_dst, count),
                xbmc.LOGINFO,
            )
        except Exception as e:
            xbmc.log(
                "[mod v2+] failed media dir {}: {}".format(rel_dst, e), xbmc.LOGERROR
            )
            failed += 1

    return applied, failed


def restore_media_dirs(skin_root):
    """Remove the loose MEDIA_DIRS directories we added (they didn't exist
    originally). A missing dir is treated as already-removed (skipped). Each
    entry is handled defensively. Returns (removed, failed, skipped) in dirs.
    """
    removed = 0
    failed = 0
    skipped = 0

    for _rel_src, rel_dst in MEDIA_DIRS:
        dst = os.path.join(skin_root, *rel_dst.split("/"))

        try:
            if os.path.isdir(dst):
                shutil.rmtree(dst)
                removed += 1
                xbmc.log("[mod v2+] removed media dir {}".format(rel_dst), xbmc.LOGINFO)
            else:
                skipped += 1
                xbmc.log(
                    "[mod v2+] media dir {} absent, skipped".format(rel_dst),
                    xbmc.LOGINFO,
                )
        except Exception as e:
            xbmc.log(
                "[mod v2+] failed removing media dir {}: {}".format(rel_dst, e),
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


def _apply(skin_root, skin_xml):
    applied, failed = apply_patches(skin_xml)
    media_applied, media_failed = apply_media(skin_root)
    dirs_applied, dirs_failed = apply_media_dirs(skin_root)

    media_applied += dirs_applied
    total_failed = failed + media_failed + dirs_failed
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
    xbmc.executebuiltin("ReloadSkin()")


def _restore(skin_root, skin_xml):
    restored, failed, _skipped = restore_patches(skin_xml)
    media_removed, media_failed, _media_skipped = restore_media(skin_root)
    dirs_removed, dirs_failed, _dirs_skipped = restore_media_dirs(skin_root)

    media_removed += dirs_removed
    media_failed += dirs_failed

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
    xbmc.executebuiltin("ReloadSkin()")


if __name__ == "__main__":
    run()
