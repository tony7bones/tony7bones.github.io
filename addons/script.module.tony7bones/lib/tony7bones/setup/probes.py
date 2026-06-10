"""Installed-state done-probes for the Guided wizard (Phase 5d).

The Guided wizard resumes via the box's ACTUAL state, never marker files (the
core re-entrancy principle): each probe answers "is this layer's target state
already on the box?" from the same primitives the layers themselves use. The
orchestrator (``run_guided`` in the bootstrap) calls these on every launch to
offer the NEXT undone gate — so a crash, a declined restart, or a silently
reverted skin all self-heal: the wizard simply re-offers the incomplete gate,
and every layer is idempotent on re-entry.

Probe semantics (the panel's plan, with two documented deviations):

* ``foundation_done`` — the skin is installed AND is the ACTIVE skin
  (``getSkinDir() == SKIN_ID``). Activation is part of the done-state because
  Kodi's "Keep this skin?" timeout can silently revert a set skin (a real race
  recorded in the 5b·3 leg-1 finding); probing activation makes the wizard
  re-offer Foundation after a revert, which re-activates — a self-heal, not a
  redo (the closure install short-circuits).
* ``iptv_done`` — the PVR backend is installed AND at least ONE env provider's
  ``instance-settings-<N>.xml`` exists on disk. A FILE check, deliberately NOT
  a populated channel list (channel sync is async; an empty list right after
  apply is normal, not failure). "At least one" — not "all" — because a
  portal-API provider with no staged host build can never land in-Kodi (the
  honest 5b·1 skip); requiring ALL files would re-offer the gate forever on
  such an env. Only consulted when the env actually carries a provider
  (``_env_has_iptv`` gates the offer upstream).
* ``addons_done`` — every base app + curated video add-on is installed
  (per-id ``is_installed``). Origin is deliberately NOT probed: the two peno64
  base apps ship blank origins by design (``install_with_deps`` "No origins" —
  live-proven identical under Express in the 5c verify), so a non-blank-origin
  requirement could never be satisfied.

Every probe is defensive (never raises; an unreadable state reads as "not
done", so the worst failure mode is re-offering an idempotent gate).
"""

import os

import xbmc
import xbmcvfs

from tony7bones import is_installed

from .addons import ADDONS, VIDEO_APPS
from .foundation import SKIN_ID
from .iptv import PVR_BACKEND_ID, _instance_settings_special, _iptv_providers


def foundation_done():
    """True when the Foundation gate's target state is on the box: the Estuary
    MOD V2 skin is installed AND currently the active skin. Never raises."""
    try:
        if not is_installed(SKIN_ID):
            return False
        return (xbmc.getSkinDir() or "") == SKIN_ID
    except Exception:  # noqa: BLE001 - a broken probe must read as "not done"
        return False


def iptv_done(box_env):
    """True when the IPTV gate's target state is on the box: pvr.iptvsimple is
    installed AND at least one env provider's instance-settings file exists.

    A FILE check by design — never the (async) channel list. The wizard only
    consults this when the env carries a provider source, so the legacy
    always-returned provider-1 entry is fine here: with a real provider in the
    env its instance file is what the apply wrote. Never raises."""
    try:
        if not is_installed(PVR_BACKEND_ID):
            return False
        for provider in _iptv_providers(box_env or {}):
            path = xbmcvfs.translatePath(_instance_settings_special(provider["n"]))
            if os.path.exists(path):
                return True
        return False
    except Exception:  # noqa: BLE001 - a broken probe must read as "not done"
        return False


def addons_done():
    """True when the Add-ons gate's target state is on the box: every base app
    and every curated video add-on is installed (per-id ``is_installed``).
    Origin is NOT probed (the peno64 apps ship blank origins by design).
    Never raises."""
    try:
        return all(is_installed(aid) for aid in list(ADDONS) + list(VIDEO_APPS))
    except Exception:  # noqa: BLE001 - a broken probe must read as "not done"
        return False
