import json
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
    "SkinSettings.xml",
    "Includes.xml",
    "DialogButtonMenu.xml",
    "LoginScreen.xml",
    "Includes_MediaMenu.xml",
    "script-globalsearch.xml",
    "script-script.module.kodi65-t9search.xml",
    "Font.xml",
    "Settings.xml",
]


def force_default_fontset():
    """Force the core look-and-feel fontset to Default (Noto Sans).

    This is a CORE Kodi setting (settable via JSON-RPC, unlike pvr instance
    settings). It is set defensively: any failure is logged and never aborts
    the run. Returns True on success, False otherwise.
    """
    request = json.dumps(
        {
            "jsonrpc": "2.0",
            "method": "Settings.SetSettingValue",
            "params": {"setting": "lookandfeel.font", "value": "Default"},
            "id": 1,
        }
    )
    try:
        raw = xbmc.executeJSONRPC(request)
        resp = json.loads(raw)
        if resp.get("result") is True:
            xbmc.log("[tony7bones patch] forced lookandfeel.font=Default", xbmc.LOGINFO)
            return True
        xbmc.log(
            "[tony7bones patch] lookandfeel.font not set: {}".format(raw),
            xbmc.LOGWARNING,
        )
        return False
    except Exception as e:
        xbmc.log(
            "[tony7bones patch] failed forcing lookandfeel.font: {}".format(e),
            xbmc.LOGERROR,
        )
        return False


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
    if xbmc.getSkinDir() != SKIN_ID:
        xbmcgui.Dialog().ok(
            "Wrong Skin",
            "This patch only runs on Estuary MOD V2.[CR]Switch skins and run again.",
        )
        return

    skin_xml = translatePath("special://home/addons/{}/xml".format(SKIN_ID))

    if not os.path.isdir(skin_xml):
        xbmcgui.Dialog().ok(
            "Patch Failed",
            "{} not found.[CR]Install it first, then run this script.".format(SKIN_ID),
        )
        return

    font_forced = force_default_fontset()

    applied, failed = apply_patches(skin_xml)

    if failed > 0:
        xbmcgui.Dialog().ok(
            "Patches Partial",
            "{} applied, {} failed.[CR]Check the Kodi log for details.".format(
                applied, failed
            ),
        )
        return

    font_note = "[CR]Fonts set to stock Estuary (Noto Sans)." if font_forced else ""
    xbmcgui.Dialog().ok(
        "Patches Applied",
        "{} files patched.{}[CR]Reloading skin...".format(applied, font_note),
    )
    xbmc.executebuiltin("ReloadSkin()")


run()
