"""apply_skin — the Skin layer of the modular setup (plan section 3.3, Phase 4).

Installs the Estuary MOD V2 skin CLOSURE + the MOD V2+ patch add-on (moved here
from the Foundation layer — see ``docs/plans/automate-share-and-backup-config.md``
section 2/3.1/3.3: the skin is curatorial branding, not a Foundation prerequisite),
and trims the STOCK Estuary home menu (tightly coupled to the skin: it only makes
sense to trim stock Estuary's menu here, since MOD V2's own menu is handled
separately by modv2plus's boot service once that skin is active).

This layer does NOT set ``lookandfeel.skin`` — activation stays the orchestrator's
terminal seam (set LAST, immediately before the single restart, so Kodi's "Keep
this skin?" safety timeout can't silently revert it). ``apply_skin`` returns
``needs_skin_activation=True`` as a REQUEST, exactly like the old (pre-split)
``apply_foundation`` did.

Two things make this layer NOT a drop-in copy of Foundation's install pattern
(mirrors the rationale already documented in ``backup.py``):

  * **Two deps are invisible to the normal closure resolver.** The resolver
    (``repos.repo_dirs()``) skips our ``127.0.0.1`` proxy, so
    ``script.module.pvr.artwork`` (b-jesch's GitHub-only module, a hard skin
    requirement) and our own ``script.tony7bones.modv2plus`` are DIRECT-EXTRACTED
    before the closure resolve, so the skin's dependency check is satisfied.
  * **Freshly-extracted add-ons must be registered AND enabled before the skin
    is set** — a rescan (``update_local_addons`` + a 3s settle) + explicit
    ``enable`` for each direct-extracted id runs before ``apply_skin`` returns,
    or Kodi silently rejects the skin choice and the box boots stock Estuary.

``_log``/``MY_ID``/``_latest_zip_url`` are a SEPARATE copy (not a shared import,
mirroring ``backup.py``'s own copy) so this module has no dependency on
Foundation's internals beyond the two constants it explicitly re-exports.
"""

import os
from xml.etree import ElementTree as ET

import xbmc
import xbmcvfs

from tony7bones import (
    extract_zip,
    install_selection,
    install_with_deps,
    is_installed,
    update_local_addons,
)
from tony7bones import enable as _enable

from .foundation import OFFICIAL_BASE, STATIC_BASE
from .result import LayerResult

MY_ID = "script.tony7bones.bootstrap"

# Estuary MOD V2 skin + the MOD V2+ patch — installed by the Skin layer.
SKIN_ID = "skin.estuary.modv2"
MODV2PLUS_ID = "script.tony7bones.modv2plus"
OUTLINE_HD_ID = "resource.images.weathericons.outline-hd"
# script.module.pvr.artwork is a hard requirement of the skin but is b-jesch's own
# GitHub module — not in Kodinerds/official, and the closure resolver SKIPS our
# 127.0.0.1 proxy (repos.py), so it would resolve as "missing". We direct-extract
# it (+ its requests/simplecache deps from official) BEFORE the closure resolve so
# the skin's dependency check is satisfied. The mirror is served at our Pages
# /addons/hosted/ (raw.githubusercontent equivalent for the proxy).
HOSTED_BASE = "https://tony7bones.github.io/addons/hosted"
PVR_ARTWORK_ID = "script.module.pvr.artwork"
PVR_ARTWORK_ZIP = "script.module.pvr.artwork-2.2.10.zip"
PVR_ARTWORK_DEPS = ["script.module.requests", "script.module.simplecache"]


def _log(msg, level=xbmc.LOGINFO):
    xbmc.log(f"[{MY_ID}] {msg}", level)


def _latest_zip_url(addon_id):
    """Resolve a first-party add-on's current zip URL from its static addon.xml.

    Same mechanism as ``foundation._latest_zip_url``/``backup._latest_zip_url`` —
    a separate copy (not a shared import), same rationale as ``backup.py``."""
    import re
    import urllib.request

    base = f"{STATIC_BASE}/{addon_id}"
    try:
        with urllib.request.urlopen(f"{base}/addon.xml", timeout=15) as r:
            xml = r.read().decode("utf-8", "replace")
        m = re.search(r'<addon\b[^>]*\bversion="([^"]+)"', xml)
        if m:
            return f"{base}/{addon_id}-{m.group(1)}.zip"
    except Exception as e:  # noqa: BLE001
        _log(f"cannot resolve {addon_id}: {e}", xbmc.LOGERROR)
    return None


class _SkinDeps:
    """The install primitives ``_install_skin`` needs, gathered so the orchestrator
    can inject a different binding set (it forwards the BOOTSTRAP's module-level
    primitives so ``run()``-driven tests that monkeypatch ``boot.mod.*`` still take
    effect — a behaviour-preservation requirement, since the monolith resolved
    these names in the bootstrap module).

    The defaults resolve LIVE from THIS module's globals on every access (late
    binding), so the standalone skin tests that monkeypatch
    ``skin.install_selection`` / ``extract_zip`` / ``_latest_zip_url`` take
    effect too — mirroring how the bootstrap's ``_BootSkinDeps`` reads its globals.
    """

    # primitive name -> (this module's global name, import default). __getattr__
    # reads globals() FIRST (late binding, so monkeypatching the module global
    # takes effect); the import default keeps the imports real references (ruff)
    # and is the fallback if the global is absent.
    _MAP = {
        "install_selection": ("install_selection", install_selection),
        "install_with_deps": ("install_with_deps", install_with_deps),
        "extract_zip": ("extract_zip", extract_zip),
        "is_installed": ("is_installed", is_installed),
        "update_local_addons": ("update_local_addons", update_local_addons),
        "enable": ("_enable", _enable),
        "latest_zip_url": ("_latest_zip_url", None),
    }

    def __getattr__(self, name):
        entry = self._MAP.get(name)
        if entry is None:
            raise AttributeError(name)
        gname, default = entry
        return globals().get(gname, default)


def _install_skin(dialog, *, deps=None):
    """Install Estuary MOD V2 and the MOD V2+ patch, unattended.

    Two pieces are INVISIBLE to the closure resolver because it skips our
    127.0.0.1 proxy (repos.py): script.module.pvr.artwork (b-jesch GitHub-only)
    and our OWN first-party patch add-on script.tony7bones.modv2plus. Both are
    direct-extracted here. install_selection then resolves the rest of the skin's
    closure (skin.estuary.modv2 + skinshortcuts + image.resource.select from
    Kodinerds; pvr.artwork already satisfied) from the installed repos.

    Then we rescan + settle + enable everything we direct-extracted BEFORE setting
    lookandfeel.skin: a freshly-extracted skin must be registered AND enabled or
    Kodi silently rejects the skin setting and the box boots stock Estuary (the
    bug the fresh-Kodi test caught). The orchestrator's single end-of-Setup
    restart then activates MOD V2 (no "Keep this skin?" modal); modv2plus's boot
    service auto-applies the patch once MOD V2 is live. Returns True if the skin
    installed. Never raises.

    NOTE: lookandfeel.skin is NOT set here — the orchestrator sets it LAST, right
    before the restart (the activate-skin invariant). ``apply_skin`` surfaces
    that as needs_skin_activation=True.

    ``deps`` lets the caller inject the install primitives (defaults to this
    module's). The bootstrap injects ITS bindings so a ``run()`` driven through
    monkeypatched ``boot.mod.install_selection`` / ``extract_zip`` / ``_latest_zip_url``
    still routes through the patched functions — behaviour-identical to the
    monolith, which resolved those names in the bootstrap module.
    """
    if deps is None:
        deps = _SkinDeps()
    try:
        if dialog is not None:
            dialog.update(0, "Installing Estuary MOD V2 skin...")
        # 1. pvr.artwork (GitHub-only, proxy-invisible) + its module deps, direct.
        if not deps.is_installed(PVR_ARTWORK_ID):
            deps.extract_zip(
                f"{HOSTED_BASE}/{PVR_ARTWORK_ID}/{PVR_ARTWORK_ZIP}", dialog, 100, _log
            )
        for dep in PVR_ARTWORK_DEPS:
            deps.install_with_deps(dep, dialog, [], OFFICIAL_BASE, _log)
        # 2. our MOD V2+ patch add-on is proxy-only too -> direct-extract it (live
        #    version) + pull its outline-hd weather-icon dep from the official repo.
        if not deps.is_installed(MODV2PLUS_ID):
            url = deps.latest_zip_url(MODV2PLUS_ID)
            if url:
                deps.extract_zip(url, dialog, 100, _log)
        deps.install_with_deps(OUTLINE_HD_ID, dialog, [], OFFICIAL_BASE, _log)
        # 3. the skin + its remaining closure from the installed repos + official.
        deps.install_selection([SKIN_ID], OFFICIAL_BASE, set(), dialog, _log)
        # 4. rescan + settle + enable everything so the skin is a registered,
        #    enabled choice BEFORE we set it (else Kodi keeps stock Estuary).
        deps.update_local_addons()
        xbmc.sleep(3000)
        for aid in (PVR_ARTWORK_ID, MODV2PLUS_ID, SKIN_ID):
            deps.enable(aid)
        xbmc.sleep(1000)
        # NOTE: lookandfeel.skin is set LAST by the orchestrator, immediately
        # before the restart — NOT here. A long gap between the skin-set and the
        # restart lets Kodi's "Keep this skin?" safety timeout silently revert
        # the choice (the bug the fresh-Kodi test caught); setting it right
        # before the restart persists it to guisettings on shutdown.
        return deps.is_installed(SKIN_ID)
    except Exception as e:  # noqa: BLE001 - a skin failure must not abort the box
        _log(f"skin install failed (non-fatal): {e}", xbmc.LOGERROR)
        return False


# --------------------------------------------------------------------------- #
# Stock Estuary home-menu trim — tightly coupled to the skin (see module
# docstring): it trims STOCK Estuary's menu; MOD V2's own menu is handled by
# modv2plus's boot service once that skin is active.
# --------------------------------------------------------------------------- #
# Both mechanisms are applied: Skin.SetBool() sets the in-memory value (which the
# shutdown persists, surviving the restart), and a direct settings.xml merge is
# the belt-and-suspenders fallback (covers a not-yet-loaded skin, preserves all
# other settings).
ESTUARY_SKIN_ID = "skin.estuary"

ESTUARY_HIDE_SETTINGS = [
    ("HomeMenuNoMovieButton", "homemenunomoviebutton"),  # Movies
    ("HomeMenuNoTVShowButton", "homemenunotvshowbutton"),  # TV shows
    ("HomeMenuNoMusicButton", "homemenunomusicbutton"),  # Music
    ("HomeMenuNoMusicVideoButton", "homemenunomusicvideobutton"),  # Music videos
    ("HomeMenuNoRadioButton", "homemenunoradiobutton"),  # Radio
    ("HomeMenuNoPicturesButton", "homemenunopicturesbutton"),  # Pictures
    ("HomeMenuNoVideosButton", "homemenunovideosbutton"),  # Videos
    ("HomeMenuNoGamesButton", "homemenunogamesbutton"),  # Games
]


def _estuary_settings_path():
    """Absolute path to skin.estuary's per-profile settings.xml."""
    return xbmcvfs.translatePath(
        "special://profile/addon_data/skin.estuary/settings.xml"
    )


def _trim_home_menu_setbool():
    """Set the eight hide-booleans in the ACTIVE skin's live memory via
    Skin.SetBool. This is what survives the end-of-setup restart: Kodi rewrites
    settings.xml from memory on shutdown, so the in-memory true persists."""
    for camel, _low in ESTUARY_HIDE_SETTINGS:
        xbmc.executebuiltin(f"Skin.SetBool({camel})")


def _trim_home_menu_writefile():
    """Merge the eight hide-booleans (= true) into skin.estuary's settings.xml,
    creating the file/dir if missing and PRESERVING every other existing setting.
    Belt-and-suspenders behind _trim_home_menu_setbool(). Idempotent."""
    xml_path = _estuary_settings_path()
    os.makedirs(os.path.dirname(xml_path), exist_ok=True)

    root = None
    if os.path.exists(xml_path):
        try:
            root = ET.parse(xml_path).getroot()
        except ET.ParseError as e:
            _log(f"skin.estuary settings.xml malformed, recreating: {e}", xbmc.LOGERROR)
            root = None
    if root is None or root.tag != "settings":
        root = ET.Element("settings")

    by_id = {
        (s.get("id") or "").lower(): s for s in root.findall("setting") if s.get("id")
    }

    changed = 0
    for _camel, low in ESTUARY_HIDE_SETTINGS:
        el = by_id.get(low)
        if el is None:
            el = ET.SubElement(root, "setting")
            el.set("id", low)
            el.set("type", "bool")
            by_id[low] = el
        elif not el.get("type"):
            el.set("type", "bool")
        if (el.text or "").strip().lower() != "true":
            changed += 1
        el.text = "true"

    with open(xml_path, "w", encoding="utf-8") as f:
        f.write(ET.tostring(root, encoding="unicode"))
    _log(
        f"_trim_home_menu: wrote 8 hide-bools ({changed} changed) to {xml_path}",
        xbmc.LOGINFO,
    )


def _trim_home_menu():
    """Trim the stock Estuary home menu to TV, Add-ons, Favourites, Weather.

    Hides the other eight items by forcing each Estuary HomeMenuNo<X>Button
    boolean true. Applies BOTH mechanisms (Skin.SetBool live value + a settings.xml
    merge). Guard: only meaningful on the stock Estuary skin — when another skin
    is active this is a safe no-op. Idempotent and defensive (any failure is
    logged and swallowed; touches ONLY skin.estuary's settings).
    """
    try:
        skin = ""
        try:
            skin = xbmc.getSkinDir() or ""
        except Exception:  # noqa: BLE001 - older/edge Kodi: treat as unknown
            skin = ""
        if skin and skin != ESTUARY_SKIN_ID:
            _log(
                f"_trim_home_menu: active skin is {skin}, "
                "not skin.estuary — skipping (no-op)",
                xbmc.LOGINFO,
            )
            return
        _trim_home_menu_setbool()
        _trim_home_menu_writefile()
    except Exception as e:  # noqa: BLE001 - never abort the rest of setup
        _log(f"_trim_home_menu failed (non-fatal): {e}", xbmc.LOGERROR)


# --------------------------------------------------------------------------- #
# The Skin layer entry point.
# --------------------------------------------------------------------------- #
def apply_skin(env, *, dialog=None, log=None, install_skin=None, trim_home_menu=None):
    """Apply Layer 4 (Skin): the Estuary MOD V2 skin + MOD V2+ patch closure,
    then trim the STOCK Estuary home menu (File-Manager sources + weather/RSS
    moved to the Foundation layer — this layer is curatorial branding only).

    This layer does NOT set ``lookandfeel.skin`` — that stays the orchestrator's
    terminal seam (set LAST, right before the restart, so Kodi's "Keep this
    skin?" timeout can't silently revert it). Returns
    ``needs_skin_activation=True`` as a REQUEST.

    Parameters
    ----------
    env
        The already-parsed per-device env dict (passed in by the orchestrator for
        a uniform per-layer contract; this layer does not read it today).
    dialog
        The shared progress dialog (or ``None``); forwarded to the skin install.
    log
        The logging callable; reserved for future per-layer logging — the lifted
        bodies keep using this module's ``_log`` so their log lines stay
        byte-identical to the monolith.
    install_skin / trim_home_menu
        The two step functions, injectable. Default to THIS module's lifted
        bodies (what the standalone skin tests drive). The bootstrap injects ITS
        module-level shims so a ``run()`` driven through monkeypatched
        ``boot.mod.*`` install primitives still routes through the patched
        functions — behaviour-identical to the monolith.

    Returns
    -------
    LayerResult
        ``layer="skin"``; ``ok`` reflects skin-install success exactly like the
        old ``_install_skin`` boolean (the orchestrator only activates the skin
        when ``ok``); ``installed`` records the skin id when it installed;
        ``needs_skin_activation=True`` and ``needs_restart=True`` are REQUESTS
        the orchestrator owns.
    """
    install_skin = install_skin or _install_skin
    trim_home_menu = trim_home_menu or _trim_home_menu

    skin_ok = install_skin(dialog)
    # Home-menu trim only makes sense once we know whether stock Estuary is even
    # still active — the function itself no-ops off stock Estuary, so it is safe
    # to call unconditionally (mirrors the pre-split apply_foundation behaviour).
    trim_home_menu()

    installed = {SKIN_ID: "installed"} if skin_ok else {}
    failed = {} if skin_ok else {SKIN_ID: "skin install failed"}
    return LayerResult(
        layer="skin",
        ok=skin_ok,
        installed=installed,
        failed=failed,
        needs_skin_activation=True,
        needs_restart=True,
        detail=("Estuary MOD V2 installed" if skin_ok else "Estuary MOD V2 FAILED"),
    )
