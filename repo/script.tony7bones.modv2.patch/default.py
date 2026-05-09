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

FILES = [
    "Home.xml",
    "Includes.xml",
    "DialogButtonMenu.xml",
    "LoginScreen.xml",
    "Includes_MediaMenu.xml",
    "script-globalsearch.xml",
    "script-script.module.kodi65-t9search.xml",
]


def run():
    skin_xml = translatePath("special://home/addons/skin.estuary.modv2/xml")

    if not os.path.isdir(skin_xml):
        xbmcgui.Dialog().ok(
            "Patch Failed",
            "skin.estuary.modv2 not found.[CR]Install it first, then run this script.",
        )
        return

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

    if failed == 0:
        xbmcgui.Dialog().ok(
            "Patches Applied", "{} files patched.[CR]Reloading skin...".format(applied)
        )
        xbmc.executebuiltin("ReloadSkin()")
    else:
        xbmcgui.Dialog().ok(
            "Patches Partial",
            "{} applied, {} failed.[CR]Check the Kodi log for details.".format(
                applied, failed
            ),
        )


run()
