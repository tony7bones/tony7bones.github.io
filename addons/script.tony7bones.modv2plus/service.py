"""Auto-apply service for Estuary MOD V2+.

The MOD V2+ patch can only run when skin.estuary.modv2 is the ACTIVE skin (it
overwrites the live skin's XML, sets skin strings, and reloads). In the one-tap
Setup flow the skin is installed and selected, but it only becomes active after
the end-of-Setup restart — at which point the Setup add-on is gone. This service
closes that gap: on Kodi start, once MOD V2 is the active skin AND the patch is
not already applied, it applies the patch once, automatically. That makes the
one-shot truly hands-off, and it also auto-recovers the patch after a MOD V2 skin
update (an update overwrites our patched files with stock ones).

It is a no-op on every normal start (already patched) and whenever a different
skin is active. The manual Apply/Restore (chooser + the in-skin buttons) are
unchanged; this only adds automatic first-run application.
"""

import os

import xbmc

try:
    from xbmcvfs import translatePath
except ImportError:  # very old Kodi
    from xbmc import translatePath

SKIN_ID = "skin.estuary.modv2"
# How long to wait for the skin to finish loading after Kodi starts (seconds).
_SKIN_WAIT_SECS = 90


def _skin_root():
    return translatePath("special://home/addons/{}".format(SKIN_ID))


def _is_applied():
    """True if our patch is already on the live skin.

    Our patched Home.xml gates the System Info overlay on
    `Skin.HasSetting(show_system_info_overlay)` — a string stock MOD V2 never
    contains. So its presence in the live Home.xml is a reliable "patched" marker
    that also resets to False after a skin update overwrites Home.xml with stock.
    """
    home = os.path.join(_skin_root(), "xml", "Home.xml")
    try:
        with open(home, encoding="utf-8") as fh:
            return "show_system_info_overlay" in fh.read()
    except OSError:
        return False


def _menu_is_ours():
    """True if the BUILT home menu is OUR deployed menu (trim + Movies/TV shows ->
    POV + custom-list widgets), not the stock default.

    The Setup's live skin-switch can race script.skinshortcuts into building the
    STOCK menu BEFORE the patch deploys ours; skinshortcuts then caches that build
    (via its hash) and SKIPS rebuilding on the next boot — leaving the wrong menu
    even though our menu is on disk. Our menu points Movies and TV shows at
    plugin.video.pov (the stock menu never does), so the POV action's presence in
    the built includes is a reliable 'this is our menu' signal. When false, the
    service re-applies, which clears the cache, redeploys our skinshortcuts menu,
    and rebuilds from it on this (race-free) boot.
    """
    inc = os.path.join(_skin_root(), "xml", "script-skinshortcuts-includes.xml")
    try:
        with open(inc, encoding="utf-8") as fh:
            data = fh.read()
    except OSError:
        return False  # not built yet -> treat as not ours (apply will build it)
    return "plugin.video.pov" in data


def _settings_applied():
    """True if OUR skin SETTINGS (not just the file patch) are present + on in the
    skin's settings.xml. The file patch persists immediately (it's a file copy), but
    the SETTINGS are written by apply_skin_settings and — on a first boot with no
    clean shutdown — could be lost. The old gate checked only the file patch + menu,
    so it logged 'nothing to do' and NEVER re-applied lost settings. Checking these
    here makes the next boot self-heal. Markers: weather readout on + Outline HD."""
    path = os.path.join(
        translatePath("special://profile/addon_data/{}".format(SKIN_ID)),
        "settings.xml",
    )
    try:
        import xml.etree.ElementTree as ET

        root = ET.parse(path).getroot()
    except Exception:  # noqa: BLE001 - absent/malformed -> treat as not applied
        return False
    vals = {s.get("id"): (s.text or "") for s in root.findall("setting")}
    return vals.get("show_weatherinfo") == "true" and "outline-hd" in vals.get(
        "WeatherIcons.path", ""
    )


def _auto_apply():
    """Apply the patch via the add-on's own apply path (default.py:_apply)."""
    try:
        import default as patch  # same add-on dir; run() is __main__-guarded

        skin_root = _skin_root()
        skin_xml = os.path.join(skin_root, "xml")
        if not os.path.isdir(skin_xml):
            xbmc.log("[mod v2+ service] skin xml dir missing — skipping", xbmc.LOGERROR)
            return
        xbmc.log(
            "[mod v2+ service] MOD V2 active + unpatched -> auto-applying", xbmc.LOGINFO
        )
        patch._apply(skin_root, skin_xml)
    except Exception as e:  # noqa: BLE001 - a service must never crash Kodi
        xbmc.log("[mod v2+ service] auto-apply failed: {}".format(e), xbmc.LOGERROR)


def _gui_ready():
    """True once MOD V2 is the active skin AND the Home window (id 10000) has
    actually rendered. getSkinDir() flips to MOD V2 the moment the skin is *set* —
    too early: applying (overwrite + ReloadSkin) while script.skinshortcuts is
    still building the home menu leaves the home blank ('Control 9000 can't
    focus'). Window.IsVisible(10000) means the skin has painted the home screen, so
    it is safe to patch + reload."""
    return xbmc.getSkinDir() == SKIN_ID and xbmc.getCondVisibility(
        "Window.IsVisible(10000)"
    )


def run():
    monitor = xbmc.Monitor()
    # Wait for the skin to finish loading AND the GUI to actually be up before
    # touching the live skin — services start before the skin renders, and acting
    # too early is the 'sometimes it comes up blank / doesn't continue' race.
    waited = 0
    while waited < _SKIN_WAIT_SECS and not monitor.abortRequested():
        if _gui_ready():
            # let the freshly-painted skin settle before we overwrite + reload
            monitor.waitForAbort(2)
            break
        if monitor.waitForAbort(3):
            return  # Kodi is shutting down
        waited += 3
    if xbmc.getSkinDir() == SKIN_ID and (
        not _is_applied() or not _menu_is_ours() or not _settings_applied()
    ):
        _auto_apply()
    else:
        xbmc.log(
            "[mod v2+ service] nothing to do (skin={}, applied={}, menu={}, settings={})".format(
                xbmc.getSkinDir(), _is_applied(), _menu_is_ours(), _settings_applied()
            ),
            xbmc.LOGINFO,
        )


if __name__ == "__main__":
    run()
