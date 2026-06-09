"""apply_foundation — Layer 0 (Foundation) of the modular setup.

The Foundation layer installs the Estuary MOD V2 skin closure + the MOD V2+ patch
add-on and applies the two base-only box-configuration steps that have no content
(File-Manager sources + the Estuary home-menu trim). It is the branded, content-
free box: skin + patch + sources + a trimmed home menu, NO video, NO PVR.

This module holds the bodies LIFTED VERBATIM out of
``script.tony7bones.bootstrap/default.py`` (Phase 2b) — the ``_install_skin`` /
``_add_file_sources`` / ``_trim_home_menu`` (+ its ``settings.xml`` fallback)
logic, behaviour-identical. ``default.py`` now keeps thin shims that delegate here
so every existing reference and test (``boot.mod._install_skin`` /
``_add_file_sources`` / ``_trim_home_menu``) keeps working unchanged, and ``run()``
calls ``apply_foundation`` in the EXACT slot those three functions occupied.

Behaviour-preservation rules encoded here (do NOT change — this is a MOVE):

  * Install order: DIRECT-EXTRACT the two proxy-invisible deps
    (``script.module.pvr.artwork`` + its module deps, then our own
    ``script.tony7bones.modv2plus`` + its Outline-HD weather-icon dep) BEFORE the
    closure resolve, so the skin's dependency check is already satisfied. THEN
    ``install_selection([SKIN_ID])`` resolves the rest of the closure
    (skin + skinshortcuts + image.resource.select) from the installed repos.
  * After the closure: one ``update_local_addons`` + a 3s settle, then ENABLE
    everything direct-extracted (pvr.artwork, modv2plus, the skin) so the skin is a
    REGISTERED + ENABLED choice before activation.
  * This layer does NOT set ``lookandfeel.skin`` — that stays the orchestrator's
    terminal seam (set LAST, right before the restart, so Kodi's "Keep this skin?"
    timeout can't silently revert it). ``apply_foundation`` returns
    ``needs_skin_activation=True`` as a REQUEST instead.
  * The home-trim writes BOTH mechanisms (Skin.SetBool live value + a settings.xml
    merge) — the belt-and-suspenders behaviour the monolith encoded.

This module assumes the base repos are ALREADY installed (``run()`` still installs
them via ``_install_base`` before calling ``apply_foundation``). Layer independence
(the layer installing its own repos) is a LATER phase and is deliberately NOT added
here.
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

from .result import LayerResult

# --------------------------------------------------------------------------- #
# Index bases + add-on ids (lifted verbatim from default.py).
# --------------------------------------------------------------------------- #
STATIC_BASE = "https://tony7bones.github.io/addons"
OFFICIAL_BASE = "https://mirrors.kodi.tv/addons/omega"

# Estuary MOD V2 skin + the MOD V2+ patch — installed by the Foundation layer.
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

MY_ID = "script.tony7bones.bootstrap"


def _log(msg, level=xbmc.LOGINFO):
    xbmc.log(f"[{MY_ID}] {msg}", level)


def _latest_zip_url(addon_id):
    """Resolve a first-party add-on's current zip URL from its static addon.xml."""
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
    these names from the bootstrap module).

    The defaults resolve LIVE from THIS module's globals on every access (late
    binding), so the standalone foundation tests that monkeypatch
    ``foundation.install_selection`` / ``extract_zip`` / ``_latest_zip_url`` take
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
    bug the fresh-Kodi test caught). The single end-of-Setup restart then activates
    MOD V2 (no "Keep this skin?" modal); modv2plus's boot service auto-applies the
    patch once MOD V2 is live. Returns True if the skin installed. Never raises.

    NOTE: lookandfeel.skin is NOT set here — the orchestrator sets it LAST, right
    before the restart (the activate-skin invariant). apply_foundation surfaces
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
        # NOTE: lookandfeel.skin is set LAST in run(), immediately before the
        # restart — NOT here. A long gap between the skin-set and the restart lets
        # Kodi's "Keep this skin?" safety timeout silently revert the choice (the
        # bug the fresh-Kodi test caught); setting it right before the restart
        # persists it to guisettings on shutdown.
        return deps.is_installed(SKIN_ID)
    except Exception as e:  # noqa: BLE001 - a skin failure must not abort the box
        _log(f"skin install failed (non-fatal): {e}", xbmc.LOGERROR)
        return False


# --------------------------------------------------------------------------- #
# File-Manager sources (base-only configuration + merge)
# --------------------------------------------------------------------------- #
# (display name, path). The "special://kodi" source's path is the Android/Fire
# Stick internal storage dir — we try to create it (harmless no-op off Android)
# but always add the source entry regardless.
# Our repo's bare URL is special: ANY existing source pointing at it (with OR
# without a trailing slash, under ANY label) is NORMALIZED to REPO_SOURCE_NAME +
# the canonical REPO_SOURCE_URL by _add_file_sources (not just deduped).
REPO_SOURCE_NAME = ".tony.7.bones"
REPO_SOURCE_URL = "https://tony7bones.github.io/"
FILE_SOURCES = [
    ("special://home", "special://home"),
    ("special://kodi", "/storage/emulated/0/kodi/"),
    (REPO_SOURCE_NAME, REPO_SOURCE_URL),
]


def _sources_xml_path():
    """Resolve the absolute path to userdata/sources.xml via xbmcvfs."""
    p = xbmcvfs.translatePath("special://profile/sources.xml")
    if not p:
        p = xbmcvfs.translatePath("special://home/userdata/sources.xml")
    return p


def _make_files_source(parent, name, path):
    """Append a standard <source> entry to the given <files> element."""
    src = ET.SubElement(parent, "source")
    ET.SubElement(src, "name").text = name
    p = ET.SubElement(src, "path")
    p.set("pathversion", "1")
    p.text = path
    ET.SubElement(src, "allowsharing").text = "true"


def _add_file_sources():
    """Add our File-Manager sources to userdata/sources.xml.

    Edits the <files> section in place: creates the file/structure if missing,
    PRESERVES every existing source, and DEDUPES new ones on both name and path so
    a second run adds nothing. Special case — the repo source is NORMALIZED: any
    existing source whose path is our bare URL (with or without a trailing slash,
    under ANY label) is renamed to REPO_SOURCE_NAME with the canonical
    REPO_SOURCE_URL, and slash-variant duplicates collapse to one. For the Android
    internal-storage path we attempt mkdirs first (guarded) but add the source
    entry either way. Fully defensive: any error is logged and the rest of setup
    continues. The end-of-setup restart is what makes Kodi pick up the new sources
    (it caches sources.xml at startup).
    """
    try:
        xml_path = _sources_xml_path()

        # Parse the existing file, or start a fresh <sources> tree.
        root = None
        if xml_path and os.path.exists(xml_path):
            try:
                root = ET.parse(xml_path).getroot()
            except ET.ParseError as e:
                _log(f"sources.xml malformed, recreating: {e}", xbmc.LOGERROR)
                root = None
        if root is None or root.tag != "sources":
            root = ET.Element("sources")

        # Ensure a <files> section with a leading <default> element exists.
        files = root.find("files")
        if files is None:
            files = ET.SubElement(root, "files")
        if files.find("default") is None:
            # Prepend <default> so the section matches Kodi's canonical shape.
            default = ET.Element("default")
            files.insert(0, default)

        changed = False
        # Normalize the repo source: ANY existing <files> source whose path is our
        # bare URL — with OR without a trailing slash, under ANY label — is renamed
        # to the canonical REPO_SOURCE_NAME + REPO_SOURCE_URL. Deliberate (not a
        # dedupe): claim the repo source under one known name however it was added.
        repo_key = REPO_SOURCE_URL.rstrip("/")
        for s in files.findall("source"):
            if (s.findtext("path") or "").strip().rstrip("/") == repo_key:
                name_el = s.find("name")
                if name_el is None:
                    name_el = ET.SubElement(s, "name")
                if name_el.text != REPO_SOURCE_NAME:
                    name_el.text = REPO_SOURCE_NAME
                    changed = True
                path_el = s.find("path")
                if (
                    path_el is not None
                    and (path_el.text or "").strip() != REPO_SOURCE_URL
                ):
                    path_el.text = REPO_SOURCE_URL
                    changed = True
        # Collapse any duplicates the normalization produced (e.g. both slash
        # variants existed) down to a single canonical repo source.
        seen_repo = False
        for s in list(files.findall("source")):
            is_repo = (s.findtext("name") or "") == REPO_SOURCE_NAME and (
                s.findtext("path") or ""
            ).strip() == REPO_SOURCE_URL
            if is_repo:
                if seen_repo:
                    files.remove(s)
                    changed = True
                else:
                    seen_repo = True

        # Existing names/paths in <files> — dedupe new sources against both.
        have_names = {
            (s.findtext("name") or "").strip() for s in files.findall("source")
        }
        have_paths = {
            (s.findtext("path") or "").strip() for s in files.findall("source")
        }

        added = 0
        for name, path in FILE_SOURCES:
            # The Android internal-storage dir: try to create it, guarded.
            if path == "/storage/emulated/0/kodi/":
                try:
                    if not xbmcvfs.exists(path):
                        xbmcvfs.mkdirs(path)
                except Exception as e:  # noqa: BLE001 - non-Android: harmless
                    _log(
                        f"mkdirs {path} skipped (expected off Android): {e}",
                        xbmc.LOGINFO,
                    )
            if name in have_names or path in have_paths:
                continue  # dedupe: already present by name or path
            _make_files_source(files, name, path)
            have_names.add(name)
            have_paths.add(path)
            added += 1

        if added or changed:
            data = ET.tostring(root, encoding="unicode")
            with open(xml_path, "w", encoding="utf-8") as f:
                f.write(data)
            _log(f"file sources updated ({added} added) in {xml_path}", xbmc.LOGINFO)
        else:
            _log("file sources already present (no change)", xbmc.LOGINFO)
    except Exception as e:  # noqa: BLE001 - never abort the rest of setup
        _log(f"_add_file_sources failed (non-fatal): {e}", xbmc.LOGERROR)


# --------------------------------------------------------------------------- #
# Estuary home-menu trim (base-only configuration + merge)
# --------------------------------------------------------------------------- #
# Each home item in Estuary's xml/Home.xml is gated by
#   <visible>!Skin.HasSetting(HomeMenuNo<X>Button)</visible>,
# so setting the matching skin BOOLEAN true HIDES that item. We hide eight and
# leave the four we keep (TV/Live TV, Add-ons/Programs, Favourites, Weather)
# visible. Two ids per item: the camel-case ID the skin XML / Skin.SetBool use,
# and the LOWERCASE id the skin persists into settings.xml. Skin.HasSetting() is
# case-insensitive, so the skin reads either back.
#
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
# The Foundation layer entry point.
# --------------------------------------------------------------------------- #
def apply_foundation(
    env,
    *,
    dialog=None,
    log,
    install_skin=None,
    add_file_sources=None,
    trim_home_menu=None,
):
    """Apply Layer 0 (Foundation): the Estuary MOD V2 skin + MOD V2+ patch closure,
    then the two content-free base-config steps (File-Manager sources + the Estuary
    home-menu trim).

    Behaviour-preserving extraction of the monolith's ``_install_skin`` /
    ``_add_file_sources`` / ``_trim_home_menu`` sequence. The skin install drives
    the exact same direct-extract-before-resolve ritual (proxy-invisible pvr.artwork
    + modv2plus first, then the closure, then update_local_addons + 3s settle +
    enable). This layer does NOT set ``lookandfeel.skin`` — that stays the
    orchestrator's terminal seam — so it returns ``needs_skin_activation=True`` as a
    request.

    Parameters
    ----------
    env
        The already-parsed per-device env dict (passed in by the orchestrator; the
        Foundation layer needs no env values today, but the contract is uniform
        across layers so the orchestrator can read+own the env once).
    dialog
        The shared progress dialog (or ``None``); forwarded to the skin install.
    log
        The logging callable (e.g. the bootstrap's ``_log``); reserved for future
        per-layer logging — the lifted bodies keep using this module's ``_log`` so
        their log lines stay byte-identical to the monolith.
    install_skin / add_file_sources / trim_home_menu
        The three step functions, injectable. Default to THIS module's lifted
        bodies (what the standalone foundation tests drive). The bootstrap injects
        ITS module-level shims so a ``run()`` driven through monkeypatched
        ``boot.mod.*`` install primitives still routes through the patched
        functions — behaviour-identical to the monolith.

    Returns
    -------
    LayerResult
        ``layer="foundation"``; ``ok`` reflects skin-install success exactly like
        the old ``_install_skin`` boolean (the orchestrator only activates the skin
        when ``ok``); ``installed`` records the skin id when it installed;
        ``needs_skin_activation=True`` and ``needs_restart=True`` are REQUESTS the
        orchestrator owns.
    """
    install_skin = install_skin or _install_skin
    add_file_sources = add_file_sources or _add_file_sources
    trim_home_menu = trim_home_menu or _trim_home_menu

    skin_ok = install_skin(dialog)
    # The two content-free base-config steps that used to run inline in run() right
    # after the skin install. Order preserved: file sources, then the home trim.
    add_file_sources()
    trim_home_menu()

    installed = {SKIN_ID: "installed"} if skin_ok else {}
    failed = {} if skin_ok else {SKIN_ID: "skin install failed"}
    return LayerResult(
        layer="foundation",
        ok=bool(skin_ok),
        installed=installed,
        failed=failed,
        needs_skin_activation=True,
        needs_restart=True,
        detail=("Estuary MOD V2 installed" if skin_ok else "Estuary MOD V2 FAILED"),
    )
