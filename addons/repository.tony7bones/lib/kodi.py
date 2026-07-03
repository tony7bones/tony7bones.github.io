import logging

import xbmc
import xbmcaddon
import xbmcgui

from lib.utils import PY3, str_to_unicode

ADDON = xbmcaddon.Addon()

if PY3:
    from xbmcvfs import translatePath

    translate = ADDON.getLocalizedString
else:
    from xbmc import translatePath

    def translate(*args, **kwargs):
        return ADDON.getLocalizedString(*args, **kwargs).encode("utf-8")


ADDON_ID = ADDON.getAddonInfo("id")
ADDON_NAME = ADDON.getAddonInfo("name")
ADDON_PATH = str_to_unicode(ADDON.getAddonInfo("path"))
ADDON_ICON = str_to_unicode(ADDON.getAddonInfo("icon"))
ADDON_DATA = str_to_unicode(translatePath(ADDON.getAddonInfo("profile")))

# Mirrors resources/settings.xml's declared default for the "repository_port"
# setting — the fallback used when the setting can't be parsed as an int.
DEFAULT_REPOSITORY_PORT = 61234


def notification(message, heading=ADDON_NAME, icon=ADDON_ICON, time=5000, sound=True):
    xbmcgui.Dialog().notification(heading, message, icon, time, sound)


def get_repository_port():
    # lib/service.py calls this as the first statement in run(), right after
    # import. An empty/non-numeric setting value (corrupted profile, manual
    # edit, a Kodi skin/settings quirk) must not crash the whole service —
    # degrade to the documented default port instead.
    try:
        return int(ADDON.getSetting("repository_port"))
    except (TypeError, ValueError) as e:
        logging.warning(
            "Invalid repository_port setting, falling back to default %s: %s",
            DEFAULT_REPOSITORY_PORT,
            e,
        )
        return DEFAULT_REPOSITORY_PORT


class KodiLogHandler(logging.Handler):
    levels = {
        logging.CRITICAL: xbmc.LOGFATAL,
        logging.ERROR: xbmc.LOGERROR,
        logging.WARNING: xbmc.LOGWARNING,
        logging.INFO: xbmc.LOGINFO,
        logging.DEBUG: xbmc.LOGDEBUG,
        logging.NOTSET: xbmc.LOGNONE,
    }

    def __init__(self):
        super(KodiLogHandler, self).__init__()
        self.setFormatter(logging.Formatter("[{}] %(message)s".format(ADDON_ID)))

    def emit(self, record):
        xbmc.log(self.format(record), self.levels[record.levelno])


def set_logger(name=None, level=logging.NOTSET):
    logger = logging.getLogger(name)
    logger.handlers = [KodiLogHandler()]
    logger.setLevel(level)
