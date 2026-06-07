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


def run():
    monitor = xbmc.Monitor()
    # Wait for the skin to finish loading (Kodi reports the previous/booting skin
    # briefly), then act exactly once.
    waited = 0
    while waited < _SKIN_WAIT_SECS and not monitor.abortRequested():
        if xbmc.getSkinDir() == SKIN_ID:
            break
        if monitor.waitForAbort(3):
            return  # Kodi is shutting down
        waited += 3
    if xbmc.getSkinDir() == SKIN_ID and not _is_applied():
        _auto_apply()
    else:
        xbmc.log(
            "[mod v2+ service] nothing to do (skin={}, applied={})".format(
                xbmc.getSkinDir(), _is_applied()
            ),
            xbmc.LOGINFO,
        )


if __name__ == "__main__":
    run()
