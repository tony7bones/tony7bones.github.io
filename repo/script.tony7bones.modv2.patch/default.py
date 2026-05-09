import os
import shutil
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

FILES = [
    "Home.xml",
    "Includes.xml",
    "DialogButtonMenu.xml",
    "LoginScreen.xml",
    "Includes_MediaMenu.xml",
    "script-globalsearch.xml",
    "script-script.module.kodi65-t9search.xml",
]


def apply_patches(skin_xml):
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
            xbmc.log("[tony7bones patch] applied {}".format(fname), xbmc.LOGINFO)
        except Exception as e:
            xbmc.log("[tony7bones patch] failed {}: {}".format(fname, e), xbmc.LOGERROR)
            failed += 1

    return applied, failed


def run():
    skin_xml = translatePath("special://home/addons/{}/xml".format(SKIN_ID))

    if not os.path.isdir(skin_xml):
        xbmcgui.Dialog().ok(
            "Patch Failed",
            "{} not found.[CR]Install it first, then run this script.".format(SKIN_ID),
        )
        return

    is_active = xbmc.getSkinDir() == SKIN_ID

    if not is_active:
        choice = xbmcgui.Dialog().select(
            "Estuary MOD V2 is not your active skin",
            [
                "Switch to MOD V2 and patch",
                "Patch anyway (switch later to see changes)",
            ],
        )
        if choice == -1:
            return
        if choice == 0:
            xbmc.executebuiltin("ActivateSkin({})".format(SKIN_ID))
            xbmc.sleep(2000)

    applied, failed = apply_patches(skin_xml)

    if failed == 0:
        if is_active or choice == 0:
            xbmcgui.Dialog().ok(
                "Patches Applied",
                "{} files patched.[CR]Reloading skin...".format(applied),
            )
            xbmc.executebuiltin("ReloadSkin()")
        else:
            xbmcgui.Dialog().ok(
                "Patches Applied",
                "{} files patched.[CR]Switch to Estuary MOD V2 to see the changes.".format(
                    applied
                ),
            )
    else:
        xbmcgui.Dialog().ok(
            "Patches Partial",
            "{} applied, {} failed.[CR]Check the Kodi log for details.".format(
                applied, failed
            ),
        )


run()
