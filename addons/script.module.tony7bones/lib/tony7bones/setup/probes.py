"""Installed-state done-probes for the Guided wizard (Phase 5d, redefined per
``docs/plans/automate-share-and-backup-config.md`` section 2/3.6 for the
Foundation/Skin/Backup split).

The Guided wizard resumes via the box's ACTUAL state, never marker files (the
core re-entrancy principle): each probe answers "is this layer's target state
already on the box?" from the same primitives the layers themselves use. The
orchestrator (``run_guided`` in the bootstrap) calls these on every launch to
offer the NEXT undone gate — so a crash, a declined restart, or a silently
reverted skin all self-heal: the wizard simply re-offers the incomplete gate,
and every layer is idempotent on re-entry.

Probe semantics (plan section 3.6, with documented deviations):

* ``foundation_done`` — install_repos succeeded (every REPO_ZIPS + our own
  proxy repo installed) AND autocomplete installed AND the KodiShare/
  KodiBackup File-Manager sources are present at their EXPECTED (env-resolved)
  URLs (content-checked, not just present under any label) AND weather.multi
  is installed with a non-empty ``loc1_url`` (content-checked — the
  load-bearing fetch field). Does NOT check skin state anymore (that moved to
  ``skin_done``) and does NOT check RSS (env-optional; its absence-of-write on
  a box with no ``RSS_FEEDS`` is not a failure, so there is nothing honest to
  probe there).
* ``backup_done`` — ``script.ezmaintenanceplusplus`` is ACTUALLY INSTALLED
  (not just settings.xml present — the install-invisibility trap: the closure
  resolver can't see this add-on, so a probe that only checked settings.xml
  could read "done" for an add-on that never actually landed) AND its
  settings.xml has non-empty ``download.path``/``restore.path`` rooted at the
  expected backup share (content-checked; the full per-device slug isn't
  independently recomputable here since it may include an interactively-typed
  device name, so "rooted at the expected share" is the honest bound).
* ``iptv_done`` — the PVR backend is installed AND at least ONE env provider's
  ``instance-settings-<N>.xml`` exists on disk. A FILE check, deliberately NOT
  a populated channel list (channel sync is async; an empty list right after
  apply is normal, not failure). "At least one" — not "all" — because a
  portal-API provider with no staged host build can never land in-Kodi (the
  honest 5b·1 skip); requiring ALL files would re-offer the gate forever on
  such an env. Only consulted when the env actually carries a provider
  (``_env_has_iptv`` gates the offer upstream).
* ``skin_done`` — MOD V2 is installed AND is the ACTIVE skin (activation is
  part of the done-state because Kodi's "Keep this skin?" timeout can silently
  revert a set skin — a real race recorded in the 5b·3 leg-1 finding; probing
  activation makes the wizard re-offer Skin after a revert, which
  re-activates — a self-heal, not a redo, since the closure install
  short-circuits) AND the MOD V2+ patch is applied — reusing modv2plus's own
  ``service.py::_is_applied()`` directly (dynamically loaded from the add-on's
  own resolved install path, since modv2plus does not ``<requires>`` this
  shared library and so cannot be imported normally) rather than re-deriving
  the check.
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

from .addons import ADDONS, PROXY_REPO_ID, REPO_ZIPS, VIDEO_APPS
from .backup import EZM_ID, _ezm_settings_path
from .env import env_has_iptv
from .foundation import (
    AUTOCOMPLETE_ID,
    KODI_BACKUP_SOURCE_NAME,
    KODI_SHARE_SOURCE_NAME,
    WEATHER_ADDON,
    _sources_xml_path,
    _weather_multi_settings_path,
    kodi_backup_url,
    kodi_share_url,
)
from .iptv import PVR_BACKEND_ID, _instance_settings_special, _iptv_providers
from .skin import MODV2PLUS_ID, SKIN_ID


def _source_url(name):
    """The ``<path>`` text for a File-Manager source named ``name`` in
    sources.xml, or ``None`` if sources.xml is missing/unreadable or has no
    such entry. Never raises."""
    try:
        path = _sources_xml_path()
        if not path or not os.path.exists(path):
            return None
        root = ET.parse(path).getroot()
        files = root.find("files")
        if files is None:
            return None
        for s in files.findall("source"):
            if s.findtext("name") == name:
                return s.findtext("path")
        return None
    except Exception:  # noqa: BLE001 - a broken probe must read as "not done"
        return None


def _foundation_sources_present(box_env):
    """KodiShare + KodiBackup are registered at their EXPECTED (env-resolved)
    URLs — content-checked, not just present under any label."""
    return _source_url(KODI_SHARE_SOURCE_NAME) == kodi_share_url(
        box_env
    ) and _source_url(KODI_BACKUP_SOURCE_NAME) == kodi_backup_url(box_env)


def _foundation_weather_configured():
    """weather.multi is installed AND its settings.xml has a non-empty
    loc1_url (the load-bearing fetch field) — content-checked."""
    try:
        if not is_installed(WEATHER_ADDON):
            return False
        path = _weather_multi_settings_path()
        if not os.path.exists(path):
            return False
        root = ET.parse(path).getroot()
        for s in root.findall("setting"):
            if s.get("id") == "loc1_url":
                return bool((s.text or "").strip())
        return False
    except Exception:  # noqa: BLE001 - a broken probe must read as "not done"
        return False


def foundation_done(box_env=None):
    """True when the Foundation gate's target state is on the box: all source
    repos + our proxy repo installed, autocomplete installed, KodiShare/
    KodiBackup sources present at their expected URLs, and weather.multi
    configured with a real loc1_url. Does NOT check skin state (that's
    ``skin_done``'s job) or RSS (env-optional). Never raises."""
    box_env = box_env or {}
    try:
        for _zip_name, rid in REPO_ZIPS:
            if rid and not is_installed(rid):
                return False
        if not is_installed(PROXY_REPO_ID):
            return False
        if not is_installed(AUTOCOMPLETE_ID):
            return False
        if not _foundation_sources_present(box_env):
            return False
        return _foundation_weather_configured()
    except Exception:  # noqa: BLE001 - a broken probe must read as "not done"
        return False


def _backup_configured(box_env):
    """script.ezmaintenanceplusplus is installed AND its settings.xml has
    non-empty download.path/restore.path rooted at the expected backup share
    (content-checked; the per-device slug isn't independently recomputable
    here — see the module docstring)."""
    try:
        if not is_installed(EZM_ID):
            return False
        path = _ezm_settings_path()
        if not os.path.exists(path):
            return False
        root = ET.parse(path).getroot()
        vals = {s.get("id"): (s.text or "") for s in root.findall("setting")}
        expected = kodi_backup_url(box_env).rstrip("/") + "/"
        dl = vals.get("download.path", "")
        rs = vals.get("restore.path", "")
        return (
            bool(dl)
            and bool(rs)
            and dl.startswith(expected)
            and rs.startswith(expected)
        )
    except Exception:  # noqa: BLE001 - a broken probe must read as "not done"
        return False


def backup_done(box_env=None):
    """True when the Backup gate's target state is on the box: EZ
    Maintenance++ ACTUALLY installed (not just settings present — the
    install-invisibility trap) AND its settings.xml has the expected
    destination path. Never raises."""
    return _backup_configured(box_env or {})


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


def _modv2plus_fully_applied():
    """Reuses modv2plus's own ``service.py`` checks (the plan's proven reuse
    target for the patch-applied check) rather than re-deriving the logic.
    modv2plus does NOT ``<requires>`` this shared library, so a normal Python
    import isn't available — this loads its ``service.py`` by the add-on's OWN
    resolved install path instead (the same file Kodi itself runs as
    modv2plus's boot service). Defensive: any failure (not installed, no
    xbmcaddon, import error) reads as "not applied" — never raises.

    Checks ALL THREE of ``_is_applied()`` (the Home.xml file patch) AND
    ``_menu_is_ours()`` (the built skinshortcuts menu — a live race can leave
    the file patch present while skinshortcuts still serves a cached STOCK
    menu) AND ``_settings_applied()`` (the look settings — an unclean first
    boot can lose these even though the file patch persisted immediately) —
    exactly the three conditions modv2plus's own ``service.py::run()`` checks
    before deciding "nothing to do". Checking only ``_is_applied()`` would let
    this probe read done while the service itself still considers the box
    unpatched and would still auto-correct on the next boot — a real fidelity
    gap between "Setup says done" and "the service says done"."""
    try:
        import importlib.util

        import xbmcaddon

        # translatePath: mirrors modv2plus's OWN default.py, which wraps this
        # exact getAddonInfo("path") call the same way — belt-and-suspenders
        # in case a platform ever returns a non-final path (e.g. a special://
        # form) rather than a plain filesystem path.
        addon_path = xbmcvfs.translatePath(
            xbmcaddon.Addon(MODV2PLUS_ID).getAddonInfo("path")
        )
        if not addon_path:
            return False
        service_path = os.path.join(addon_path, "service.py")
        spec = importlib.util.spec_from_file_location(
            "_modv2plus_service_probe", service_path
        )
        if spec is None or spec.loader is None:
            return False
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return bool(
            module._is_applied()
            and module._menu_is_ours()
            and module._settings_applied()
        )
    except Exception:  # noqa: BLE001 - a broken probe must read as "not done"
        return False


def skin_done():
    """True when the Skin gate's target state is on the box: MOD V2 is
    installed AND is the ACTIVE skin AND the MOD V2+ patch is FULLY applied
    (reusing modv2plus's own three patch-applied checks directly, matching
    exactly what its own boot service considers "nothing to do"). Never
    raises."""
    try:
        if not is_installed(SKIN_ID):
            return False
        if (xbmc.getSkinDir() or "") != SKIN_ID:
            return False
        return _modv2plus_fully_applied()
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

        {"foundation": bool, "backup": bool, "iptv": bool | None,
         "skin": bool, "addons": bool}

    ``iptv`` is ``None`` when the env carries NO provider playlist source
    (``env_has_iptv``) — IPTV is not expected on that box, which is different
    from "expected and missing" (False). Never raises (each probe is
    defensive)."""
    box_env = box_env or {}
    return {
        "foundation": foundation_done(box_env),
        "backup": backup_done(box_env),
        "iptv": iptv_done(box_env) if env_has_iptv(box_env) else None,
        "skin": skin_done(),
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

    ``layers`` defaults to every layer the env expects (foundation + backup +
    skin + addons always; iptv only when ``env_has_iptv``). On top of the
    per-layer done-probes it runs the dependency-closure walk
    (``missing_required_imports``) — a complete box has no dangling required
    import. Usable by tests, the wizard's Finish, and any post-setup
    verification. This is the ONE probe that is allowed to raise — that is its
    job; callers that must never fail wrap it."""
    box_env = box_env or {}
    state = box_state(box_env)
    if layers is None:
        layers = ["foundation", "backup", "skin", "addons"] + (
            ["iptv"] if env_has_iptv(box_env) else []
        )
    problems = []
    if "foundation" in layers and not state["foundation"]:
        problems.append(
            "foundation: repos/autocomplete/sources/weather not fully configured"
        )
    if "backup" in layers and not state["backup"]:
        problems.append("backup: {} not installed or not configured".format(EZM_ID))
    if "iptv" in layers and not state["iptv"]:
        problems.append(
            "iptv: {} not installed or no provider instance-settings on disk".format(
                PVR_BACKEND_ID
            )
        )
    if "skin" in layers and not state["skin"]:
        problems.append(
            "skin: {} not installed, not active, or patch not applied".format(SKIN_ID)
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
