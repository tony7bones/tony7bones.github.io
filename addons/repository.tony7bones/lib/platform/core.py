import logging

from . import kodi_platform
from . import os_platform
from .definitions import (
    PlatformError,
    SHARED_LIB_EXTENSIONS,
    EXECUTABLE_EXTENSIONS,
    Platform,
)

UNKNOWN_PLATFORM = Platform("unknown", "unknown", "unknown")


def dump_platform():
    return (
        "Kodi platform: "
        + kodi_platform.dump_platform()
        + "\n"
        + os_platform.dump_platform()
    )


def get_platform():
    try:
        return kodi_platform.get_platform()
    except PlatformError:
        return os_platform.get_platform()


# This runs at import time, pulled in by lib/entries.py (hence lib/service.py,
# the xbmc.service entry point Kodi imports the instant it enables the
# add-on). Both get_platform() paths above can still theoretically raise on
# an environment neither has ever been exercised on (a locked-down tvOS
# Python), and a platform we simply can't identify must not take the whole
# proxy down with it - degrade to an unknown platform (hides only
# platform-gated binary add-ons; everything else still serves) instead of
# crashing the entire service.
try:
    PLATFORM = get_platform()
except Exception as _e:
    logging.error(
        "Failed resolving platform, falling back to unknown: %s", _e, exc_info=True
    )
    try:
        # Purely diagnostic — dump_platform() calls the same OS/Kodi APIs
        # that just failed above, so it can raise too; never let a logging
        # convenience escalate a graceful degradation back into a crash.
        logging.error(dump_platform())
    except Exception:
        pass
    PLATFORM = UNKNOWN_PLATFORM

SHARED_LIB_EXTENSION = SHARED_LIB_EXTENSIONS.get(PLATFORM.system, "")
EXECUTABLE_EXTENSION = EXECUTABLE_EXTENSIONS.get(PLATFORM.system, "")
