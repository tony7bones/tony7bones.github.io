"""Tony.7.Bones Setup — one-tap install for a fresh Kodi box.

Installs by add-on id only. No display-name labels.

run():
  * extracts the repo installer zips (direct download)
  * installs each requested app together with its full dependency closure by
    direct download + extract, then registers + enables every add-on through
    Kodi's add-on manager so the apps actually function.
  * adds the File-Manager sources, trims the Estuary home menu, then removes
    ITSELF (run once, then disappear) so no Setup tile lingers on the home
    screen — the end-of-setup restart de-registers it cleanly. It stays in the
    Tony.7.Bones repo for one-tap reinstall whenever needed.

The shared install machinery (HTTP fetch, addons.xml index load/resolve, zip
extract, enable, self-uninstall, restart, platform detection) lives in the
script.module.tony7bones library; this file holds only the base box's own
configuration and the two base-only steps (file sources + Estuary home trim).

Why not Kodi's InstallAddon builtin: on Omega it calls a *modal* installer on
the GUI thread that pops a blocking yes/no and never returns when driven from a
script — the GUI locks. So the library resolves the dependency closure itself
from the repos' addons.xml and extracts every zip directly, then enables each
add-on — which inserts it into Kodi's installed table and makes it runnable.

No unknown-sources prompt: the script never toggles the unknown-sources setting
(it has no bearing on the direct-extract + enable path used here).

Binary (platform-specific) add-ons — e.g. pvr.iptvsimple and the inputstream.*
clients it needs — are resolved per-platform: the library detects this machine's
Kodi platform string at runtime and picks the matching official-repo entry.

This Setup can optionally chain the Video Add-ons Setup: two prompts are
FRONT-LOADED before any install (a yes/no, default No, then the video
multiselect), and the whole run — base install plus the chosen video apps — runs
unattended in this one script with a single combined summary and a single
restart.

No secrets are embedded in this script.
"""

import os
from xml.etree import ElementTree as ET

import xbmc
import xbmcgui
import xbmcvfs

# Shared install library (script.module.tony7bones). All the generic machinery
# lives here; this file keeps only the base box's configuration + base-only steps.
from tony7bones import (
    extract_zip,
    install_with_deps,
    restart_kodi,
    self_uninstall,
    update_local_addons,
)
from tony7bones import enable as _enable

MY_ID = "script.tony7bones.bootstrap"

REPO_BASE = "https://tony7bones.github.io/repo/repositories/"
STATIC_BASE = "https://tony7bones.github.io/repo"

# Add-on index base urls for the closure. The two peno64 apps live in peno64;
# their module dependencies, the weather add-on, and the binary PVR/inputstream
# clients all live in the official Kodi repo. The library's resolver walks
# <requires>/<import> recursively across both (peno64 first, official last).
OFFICIAL_BASE = "https://mirrors.kodi.tv/addons/omega"
PENO64_BASE = (
    "https://raw.githubusercontent.com/peno64/repository.peno64/master/repo/zips"
)

# Repo installer zips: (zip filename, addon id).
REPO_ZIPS = [
    ("repository.709-1.0.2.zip", "repository.709"),
    ("repository.bugatsinho-2.8.zip", "repository.bugatsinho"),
    ("repository.cocoscrapers-1.0.1.zip", "repository.cocoscrapers"),
    ("repository.diggz.zip", "repository.diggz"),
    ("repository.ivarbrandt-1.0.3.zip", "repository.ivarbrandt"),
    ("repository.kodifitzwell-0.0.1.zip", "repository.kodifitzwell"),
    ("repository.kodinerds-7.0.1.7.zip", "repository.kodinerds"),
    ("repository.loop-3.0.4.zip", "repository.loop"),
    ("repository.Magnetic-1.1.0b.zip", "repository.Magnetic"),
    ("repository.peno64-1.5.zip", "repository.peno64"),
    ("repository.redwizard-1.2.2.zip", "repository.redwizard"),
    ("repository.umbrella-2.2.6.zip", "repository.umbrella"),
]

# First-party add-on ids on our Pages — direct extract, version resolved live.
# Deliberately empty (the Estuary MOD V2 patch is manual-only); run() simply
# skips the first-party loop.
FIRST_PARTY = []

# Apps installed (with dependency closure) by direct extract, in order.
#   * script.ezmaintenanceplus / script.realdebrid — peno64 (python).
#   * weather.multi — official repo (pure python; pulls python module deps).
#   * pvr.iptvsimple — official repo (BINARY; pulls binary inputstream deps).
ADDONS = [
    "script.ezmaintenanceplus",
    "script.realdebrid",
    "weather.multi",
    "pvr.iptvsimple",
]


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


# --------------------------------------------------------------------------- #
# File-Manager sources (base-only configuration + merge)
# --------------------------------------------------------------------------- #
# (display name, path). The second path is the Android/Fire Stick internal
# storage dir — we try to create it (harmless no-op off Android) but always add
# the source entry regardless.
FILE_SOURCES = [
    ("Kodi home directory", "special://home"),
    ("Kodi sources directory", "/storage/emulated/0/kodi/"),
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
    PRESERVES every existing source, and DEDUPES on both name and path so a second
    run adds nothing. For the Android internal-storage path we attempt mkdirs
    first (guarded) but add the source entry either way. Fully defensive: any
    error is logged and the rest of setup continues. The end-of-setup restart is
    what makes Kodi pick up the new sources (it caches sources.xml at startup).
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

        # Existing names/paths in <files> — dedupe against both.
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

        if added:
            data = ET.tostring(root, encoding="unicode")
            with open(xml_path, "w", encoding="utf-8") as f:
                f.write(data)
            _log(f"added {added} file source(s) to {xml_path}", xbmc.LOGINFO)
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
# Optional video chaining — front-loaded prompts (see video module for config)
# --------------------------------------------------------------------------- #
# Imported lazily inside run() so this base Setup still imports cleanly if the
# video Setup is not installed; the prompts are shown BEFORE any install so the
# whole run is unattended afterwards.


def _ask_also_video():
    """Front-loaded yes/no: 'Also install Video Add-ons after setup?'.

    DEFAULTS TO NO (opt-in): the No button is pre-focused via Kodi's
    defaultbutton=DLG_YESNO_NO_BTN. Both the constant and the kwarg exist on
    Kodi 21 Omega (verified on the box). We fall back gracefully on any older
    Kodi that lacks either — a plain yesno whose No is the right-hand (default)
    button. Returns True only if the user explicitly chose Yes.
    """
    title = "Tony.7.Bones Setup"
    msg = "Also install Video Add-ons after setup?"
    no_btn = getattr(xbmcgui, "DLG_YESNO_NO_BTN", None)
    if no_btn is not None:
        try:
            return bool(
                xbmcgui.Dialog().yesno(
                    title, msg, yeslabel="Yes", nolabel="No", defaultbutton=no_btn
                )
            )
        except TypeError:
            pass  # older Kodi without the defaultbutton kwarg — fall through
    return bool(xbmcgui.Dialog().yesno(title, msg, yeslabel="Yes", nolabel="No"))


def _install_base(dialog):
    """Run the base install: repos + first-party + apps. Returns (repo_ok, fp_ok,
    app_ok, canceled). Shares the progress dialog with the (optional) video stage
    so the user sees one continuous progress bar. `canceled` is True if the user
    cancelled the progress dialog mid-install (run() then aborts with no summary,
    exactly today's behaviour)."""
    total = len(REPO_ZIPS) + len(FIRST_PARTY) + len(ADDONS) + 1
    step = 0
    repo_ok = fp_ok = app_ok = 0

    # 1. repos by direct extract
    for zip_name, _rid in REPO_ZIPS:
        step += 1
        if extract_zip(REPO_BASE + zip_name, dialog, int(step / total * 100), _log):
            repo_ok += 1
        if dialog.iscanceled():
            return repo_ok, fp_ok, app_ok, True

    # 2. first-party add-ons by direct extract
    for addon_id in FIRST_PARTY:
        step += 1
        url = _latest_zip_url(addon_id)
        if url and extract_zip(url, dialog, int(step / total * 100), _log):
            fp_ok += 1
        if dialog.iscanceled():
            return repo_ok, fp_ok, app_ok, True

    # 3. register + enable the repos and first-party add-ons.
    step += 1
    dialog.update(int(step / total * 100), "Registering add-ons...")
    update_local_addons()
    xbmc.sleep(3000)
    for _zip_name, rid in REPO_ZIPS:
        if rid:
            _enable(rid)
    for addon_id in FIRST_PARTY:
        _enable(addon_id)

    # 4. install each app with its dependency closure by direct extract.
    for addon_id in ADDONS:
        step += 1
        dialog.update(int(step / total * 100), f"Installing {addon_id}")
        if install_with_deps(addon_id, dialog, [PENO64_BASE], OFFICIAL_BASE, _log):
            app_ok += 1
        if dialog.iscanceled():
            return repo_ok, fp_ok, app_ok, True

    return repo_ok, fp_ok, app_ok, False


def run():
    # Front-load the optional video chaining prompts BEFORE any install, so the
    # rest of the run is unattended. Default is No (opt-in). If Yes, the video
    # multiselect is shown up front and the selection captured; the actual video
    # install happens after the base install, in this one script.
    video = None  # the video Setup's default.py module, imported only if chosen
    video_selected = []  # list of chosen video app ids
    if _ask_also_video():
        video = _load_video_module()
        if video is not None:
            labels = [label for label, _aid in video.APPS]
            choices = xbmcgui.Dialog().multiselect(
                "Video Add-ons Setup", labels, preselect=video.PRESELECT
            )
            # Cancelled/empty multiselect → run base only (today's behaviour).
            if choices:
                video_selected = [video.APPS[i][1] for i in choices]

    dialog = xbmcgui.DialogProgress()
    dialog.create("Tony.7.Bones Setup", "Starting setup...")

    # --- base install ---
    repo_ok, fp_ok, app_ok, canceled = _install_base(dialog)
    if canceled:
        # User cancelled the progress dialog mid-install: abort cleanly with NO
        # summary, NO self-uninstall, NO restart (exactly today's behaviour). The
        # partial install is harmless and re-running Setup completes it.
        return dialog.close()

    # --- optional video install (unattended, in this one script) ---
    video_installed = video_total = 0
    if video is not None and video_selected:
        video_installed, video_total = _install_video(video, video_selected, dialog)

    dialog.close()

    # --- one combined summary ---
    lines = [
        f"Repos: {repo_ok}/{len(REPO_ZIPS)}",
        f"Patches: {fp_ok}/{len(FIRST_PARTY)}",
        f"Apps: {app_ok}/{len(ADDONS)}",
    ]
    if video_total:
        lines.append(f"Video add-ons: {video_installed}/{video_total}")
    lines.append("Open Add-ons to finish any remaining setup.")
    xbmcgui.Dialog().ok("Tony.7.Bones Setup", "\n".join(lines))

    # Run once, then disappear. Done AFTER the summary; never raises.
    self_uninstall(MY_ID, _log)
    # If we chained the Video Add-ons Setup, remove ITS tile too (the standalone
    # video run removes itself; the chained run never reaches that code, so the
    # base run cleans it up here). The shared library is a hidden module add-on
    # and is deliberately LEFT installed. Guarded + never-raises by self_uninstall.
    if video is not None and video_selected:
        self_uninstall("script.tony7bones.video", _log)
    # Add our File-Manager sources (Kodi home + sources dirs) — before the restart.
    _add_file_sources()
    # Trim the stock Estuary home menu — before the restart so Estuary re-reads it.
    _trim_home_menu()
    # ONE restart finalises every freshly extracted add-on AND the self-removal.
    restart_kodi("Tony.7.Bones Setup", _log)


def _load_video_module():
    """Import the installed Video Add-ons Setup's default.py as a module so its
    config (APPS / PRESELECT / DISABLE_AFTER_INSTALL) and helpers can be reused.

    Returns the module, or None if the video Setup is not installed on the box.
    The video default.py is __main__-guarded, so importing it runs no install.
    """
    try:
        import importlib.util

        path = xbmcvfs.translatePath(
            "special://home/addons/script.tony7bones.video/default.py"
        )
        if not os.path.isfile(path):
            _log("video Setup not installed; running base only", xbmc.LOGINFO)
            return None
        spec = importlib.util.spec_from_file_location("video_setup", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    except Exception as e:  # noqa: BLE001 - video chaining is best-effort
        _log(f"could not load video Setup (running base only): {e}", xbmc.LOGERROR)
        return None


def _install_video(video, selected, dialog):
    """Install the chosen video apps + closure via the video Setup's own logic,
    sharing this run's progress dialog. Returns (installed_ok, total_selected).

    Delegates to video.install_selected(), the standalone-and-chained entry point
    the video module exposes, so the chained path and the standalone path run the
    exact same code. No separate restart/self-uninstall happens here — the base
    run owns the single restart and the video Setup's tile is removed by the base
    run too (see run())."""
    try:
        installed_ok = video.install_selected(selected, dialog)
        return installed_ok, len(selected)
    except Exception as e:  # noqa: BLE001 - a video failure must not abort base
        _log(f"video install failed (non-fatal): {e}", xbmc.LOGERROR)
        return 0, len(selected)


if __name__ == "__main__":
    run()
