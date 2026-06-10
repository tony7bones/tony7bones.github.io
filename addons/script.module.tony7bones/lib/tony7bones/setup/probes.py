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
from xml.etree import ElementTree as ET

import xbmc
import xbmcvfs

from tony7bones import is_installed

from .addons import ADDONS, VIDEO_APPS
from .env import env_has_iptv
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


def _addons_missing():
    """The base-app / curated-video ids NOT yet installed (per-id
    ``is_installed``). The honest detail behind ``addons_done`` — used by
    ``assert_box_complete`` to NAME what is missing instead of a bare False.
    A raising primitive reads as "missing" (worst case: an idempotent re-run)."""
    missing = []
    for aid in list(ADDONS) + list(VIDEO_APPS):
        try:
            if not is_installed(aid):
                missing.append(aid)
        except Exception:  # noqa: BLE001 - a broken probe must read as "not done"
            missing.append(aid)
    return missing


def addons_done():
    """True when the Add-ons gate's target state is on the box: every base app
    and every curated video add-on is installed (per-id ``is_installed``).
    Origin is NOT probed (the peno64 apps ship blank origins by design).
    Never raises."""
    try:
        return not _addons_missing()
    except Exception:  # noqa: BLE001 - a broken probe must read as "not done"
        return False


def box_state(box_env):
    """The box's layer done-ness, in one honest dict (probes only, never lies):

        {"foundation": bool, "iptv": bool | None, "addons": bool}

    ``iptv`` is ``None`` when the env carries NO provider playlist source
    (``env_has_iptv``) — IPTV is not expected on that box, which is different
    from "expected and missing" (False). Never raises (each probe is
    defensive)."""
    box_env = box_env or {}
    return {
        "foundation": foundation_done(),
        "iptv": iptv_done(box_env) if env_has_iptv(box_env) else None,
        "addons": addons_done(),
    }


def _addon_ids_on_disk(addons_dir):
    """The add-on ids present under `addons_dir` (any dir carrying an
    addon.xml). Empty set when the dir is missing/unreadable; never raises."""
    try:
        if not os.path.isdir(addons_dir):
            return set()
        return {
            name
            for name in os.listdir(addons_dir)
            if os.path.isfile(os.path.join(addons_dir, name, "addon.xml"))
        }
    except Exception:  # noqa: BLE001 - an unreadable tree reads as empty
        return set()


def missing_required_imports():
    """The dependency-closure walk: every REQUIRED ``<import>`` declared by a
    USER add-on (under ``special://home/addons/``) that is satisfied nowhere,
    as ``(addon_id, missing_dep)`` pairs.

    This is the "complete box is a check, not a slogan" probe: the install
    ritual direct-extracts + enables, so a partially-failed closure can leave a
    dangling required import that Kodi will flag as a broken add-on on some
    later scan. Rules mirror Kodi's own dependency check: ``optional="true"``
    imports are skipped (Kodi installs those on demand), ``xbmc.*`` / ``kodi.*``
    are runtime-provided, and an add-on PRESENT on disk satisfies the import
    even when disabled (the dailymotion install-then-disable contract).

    "Present" means EITHER add-on tree: the user tree (``special://home``) OR
    Kodi's BUNDLED system tree (``special://xbmc/addons/`` — a real, readable
    dir on every platform incl. Android's extracted apk assets). The first cut
    checked only the user tree and falsely "dangled" 7 imports on the owner's
    real complete box (``metadata.common.*`` / ``script.module.pil`` — all
    shipped INSIDE Kodi, never under ``special://home``). Belt-and-braces, a
    dep found in neither tree is last-checked via ``is_installed`` (Kodi's own
    registry) — this probe informs, so a false alarm is worse than a miss.
    Defensive: an unparseable manifest is skipped; never raises."""
    dangling = []
    try:
        addons_dir = xbmcvfs.translatePath("special://home/addons/")
        on_disk = _addon_ids_on_disk(addons_dir)
        if not on_disk:
            return dangling
        satisfied = on_disk | _addon_ids_on_disk(
            xbmcvfs.translatePath("special://xbmc/addons/")
        )
        for aid in sorted(on_disk):
            try:
                root = ET.parse(os.path.join(addons_dir, aid, "addon.xml")).getroot()
            except Exception:  # noqa: BLE001 - skip an unparseable manifest
                continue
            for imp in root.findall("./requires/import"):
                dep = (imp.get("addon") or "").strip()
                if not dep or dep.startswith(("xbmc.", "kodi.")):
                    continue
                if (imp.get("optional") or "").lower() == "true":
                    continue
                if dep in satisfied:
                    continue
                try:
                    registered = is_installed(dep)
                except Exception:  # noqa: BLE001 - a broken registry probe
                    registered = False
                if registered:
                    satisfied.add(dep)
                    continue
                dangling.append((aid, dep))
    except Exception:  # noqa: BLE001 - a broken walk must not break the caller
        pass
    return dangling


def assert_box_complete(box_env, *, layers=None):
    """ASSERT the box is complete for the expected layers — the plan's
    verification primitive, honest by construction: it raises AssertionError
    NAMING exactly what is missing, or returns the verified ``box_state``.

    ``layers`` defaults to every layer the env expects (foundation + addons
    always; iptv only when ``env_has_iptv``). On top of the per-layer
    done-probes it runs the dependency-closure walk
    (``missing_required_imports``) — a complete box has no dangling required
    import. Usable by tests, the wizard's Finish, and any post-setup
    verification. This is the ONE probe that is allowed to raise — that is its
    job; callers that must never fail wrap it."""
    box_env = box_env or {}
    state = box_state(box_env)
    if layers is None:
        layers = ["foundation", "addons"] + (["iptv"] if env_has_iptv(box_env) else [])
    problems = []
    if "foundation" in layers and not state["foundation"]:
        problems.append(
            "foundation: {} not installed or not the active skin".format(SKIN_ID)
        )
    if "iptv" in layers and not state["iptv"]:
        problems.append(
            "iptv: {} not installed or no provider instance-settings on disk".format(
                PVR_BACKEND_ID
            )
        )
    if "addons" in layers:
        missing = _addons_missing()
        if missing:
            problems.append("addons: not installed: {}".format(", ".join(missing)))
    dangling = missing_required_imports()
    if dangling:
        problems.append(
            "dangling required imports: "
            + ", ".join("{} -> {}".format(a, d) for a, d in dangling)
        )
    assert not problems, "box NOT complete: " + "; ".join(problems)
    return state
