"""Tony.7.Bones Setup — one-tap install for a fresh Kodi box.

Installs by add-on id only. No display-name labels.

run():
  * extracts the repo installer zips (direct download)
  * extracts first-party add-ons from our Pages (version resolved live)
  * installs each requested app together with its full dependency closure by
    direct download + extract, then registers + enables every add-on through
    Kodi's add-on manager so the apps actually function.
  * finally removes ITSELF (run once, then disappear) so no Setup tile lingers
    on the home screen — the end-of-setup restart de-registers it cleanly. It
    stays in the Tony.7.Bones repo for one-tap reinstall whenever needed.

Why not Kodi's InstallAddon builtin: on Omega it calls CAddonInstaller::
InstallModal(..., CHOICE_YES), which (1) pops a blocking "Do you want to
install X?" yes/no dialog and (2) runs the job as a *modal* job on the GUI
thread. Driven from a script with no user at the keyboard that modal never
returns — the GUI locks (the "Registering add-ons" freeze). There is no
JSON-RPC install method on Omega either (the Addons namespace only exposes
GetAddons / GetAddonDetails / SetAddonEnabled / ExecuteAddon). So we resolve
the dependency closure ourselves from the repos' addons.xml and extract every
zip directly, exactly the way build wizards do, then enable each add-on — which
inserts it into Kodi's installed table and makes it runnable.

No unknown-sources prompt: the script never toggles the unknown-sources
setting. That GUI setting only gates Kodi's *install-from-zip* UI flow; it has
no bearing on the direct-extract + Addons.SetAddonEnabled path used here, which
registers and enables an add-on regardless of the setting. Flipping it
false->true (the old behaviour) popped the blocking "Add-ons will be given
access to personal data... Proceed?" warning, so it is deliberately left
untouched — a real user running this setup never sees that dialog.

Binary (platform-specific) add-ons — e.g. pvr.iptvsimple and the
inputstream.* clients it needs — are not in the common omega/ datadir as
plain zips. The official repo's addons.xml lists each binary add-on once per
platform, every entry carrying a <platform> tag and a <path> pointing at the
correct platform-suffixed zip (e.g. pvr.iptvsimple+osx-arm64/...). We detect
this machine's Kodi platform string at runtime and pick the matching entry,
so the right native build is downloaded on any OS/arch without hardcoding.

No secrets are embedded in this script.
"""

import gzip
import json
import os
import re
import urllib.request
import zipfile
from xml.etree import ElementTree as ET

import xbmc
import xbmcaddon
import xbmcgui
import xbmcvfs

REPO_BASE = "https://tony7bones.github.io/repo/repositories/"
STATIC_BASE = "https://tony7bones.github.io/repo"

# Add-on index (addons.xml / addons.xml.gz) + per-id datadir for the closure.
# The two peno64 apps live in peno64; their module dependencies, the weather
# add-on, and the binary PVR/inputstream clients all live in the official Kodi
# repo. The resolver walks <requires>/<import> recursively across both.
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
# The Estuary MOD V2 patch (script.tony7bones.modv2.patch) is deliberately NOT
# auto-installed: it only makes sense once a user adopts the Estuary MOD V2 skin.
# It stays hosted in our repo (repo/script.tony7bones.modv2.patch/ and in
# repo/addons.xml) so anyone who wants it can install it by hand. Leave this list
# empty and run() will simply skip the first-party loop.
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

# Dependency ids provided by the Kodi runtime itself — never downloaded.
_SYSTEM_PREFIXES = ("xbmc.", "kodi.")


def _is_installed(addon_id):
    try:
        xbmcaddon.Addon(addon_id)
        return True
    except RuntimeError:
        return False


def _platform_tag():
    """Kodi's platform/arch tag for binary add-ons, e.g. 'osx-arm64'.

    Mirrors the way the official repo names its platform-specific datadirs
    (<id>+<platform>-<arch>/). Detected at runtime from os.uname()/os.name so
    the correct native build is selected on any machine. Returns None on
    platforms whose binaries are not served from this mirror (e.g. desktop
    Linux, which ships binary add-ons via the OS package manager).
    """
    name = os.name
    try:
        sysname = os.uname().sysname.lower()
        machine = os.uname().machine.lower()
    except AttributeError:  # Windows has no os.uname()
        sysname = ""
        import platform as _platform

        machine = _platform.machine().lower()

    if sysname == "darwin":
        arch = "arm64" if machine in ("arm64", "aarch64") else "x86_64"
        return f"osx-{arch}"
    if name == "nt" or sysname.startswith("win"):
        # Kodi tags: windows-x86_64 (64-bit) / windows-i686 (32-bit).
        return "windows-x86_64" if machine in ("amd64", "x86_64") else "windows-i686"
    if "android" in sysname or os.environ.get("ANDROID_ROOT"):
        return "android-aarch64" if machine in ("aarch64", "arm64") else "android-armv7"
    # Linux/other: binaries come from the distro, not this mirror.
    return None


def _http_get(url, timeout=30):
    """Fetch bytes, transparently gunzipping a .gz index."""
    req = urllib.request.Request(url, headers={"User-Agent": "Kodi"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = r.read()
    if url.endswith(".gz"):
        data = gzip.decompress(data)
    return data


def _load_index(base, platform_tag=None):
    """Return {id: (version, [dep_ids], path_or_None)} from a repo's addons.xml(.gz).

    `path` is the add-on's relative download path when the manifest declares one
    (binary add-ons do: e.g. 'pvr.iptvsimple+osx-arm64/pvr.iptvsimple-X.zip'),
    otherwise None and the caller builds the conventional '<id>/<id>-<ver>.zip'
    path. Binary add-ons appear once per platform; when `platform_tag` is given
    we keep only the entry whose <platform> matches this machine, so the right
    native build wins.
    """
    err = None
    for name in ("addons.xml.gz", "addons.xml"):
        try:
            root = ET.fromstring(_http_get(f"{base}/{name}"))
            out = {}
            for a in root.findall("addon"):
                aid = a.get("id")
                # Skip imports flagged optional="true": Kodi's own installer
                # treats those as on-demand (fetched only when actually needed
                # at runtime), so resolving them into the install closure
                # over-installs add-ons nothing actually requires (e.g.
                # plugin.googledrive pulled via resolveurl). Match Kodi's
                # behaviour and keep only required imports.
                deps = [
                    imp.get("addon")
                    for imp in a.findall("requires/import")
                    if (imp.get("optional") or "").lower() != "true"
                    and imp.get("addon")
                ]
                meta = a.find("extension[@point='xbmc.addon.metadata']")
                path = plat = None
                if meta is not None:
                    p = meta.find("path")
                    path = p.text if p is not None else None
                    pl = meta.find("platform")
                    plat = pl.text if pl is not None else None
                # A real per-arch entry tags an arch like "osx-arm64"; "all"
                # (or any tag without a "-") is universal and always kept.
                # Of the arch-specific duplicates, keep only this machine's.
                is_arch = bool(plat) and "-" in plat
                if is_arch and platform_tag and plat != platform_tag:
                    continue
                out[aid] = (a.get("version"), deps, path)
            return out
        except Exception as e:  # noqa: BLE001 - try the next index variant
            err = e
    xbmc.log(f"[tony7bones.bootstrap] index load failed {base}: {err}", xbmc.LOGERROR)
    return {}


def _resolve_closure(targets, indexes):
    """Walk the dependency graph of `targets` across the given repo indexes.

    `indexes` is an ordered list of (base_url, index_dict); the first repo that
    declares an id wins. Returns an ordered list of (addon_id, zip_url) with
    dependencies BEFORE the add-ons that need them, so extraction order is safe.
    System imports (xbmc.* / kodi.*) are skipped — Kodi provides them. An entry
    whose manifest carries an explicit <path> (binary add-ons) is downloaded
    from that path; otherwise the conventional '<id>/<id>-<ver>.zip' is used.
    """
    resolved = {}  # id -> zip_url
    order = []

    def visit(aid):
        if aid in resolved or aid.startswith(_SYSTEM_PREFIXES):
            return
        for base, idx in indexes:
            if aid in idx:
                ver, deps, path = idx[aid]
                rel = path if path else f"{aid}/{aid}-{ver}.zip"
                resolved[aid] = f"{base}/{rel}"
                for dep in deps:  # deps first
                    visit(dep)
                order.append(aid)
                return
        xbmc.log(
            f"[tony7bones.bootstrap] cannot resolve dependency: {aid}", xbmc.LOGERROR
        )

    for t in targets:
        visit(t)
    return [(aid, resolved[aid]) for aid in order]


def _extract_zip(url, dialog, pct):
    """Download a zip and extract it into addons/. Returns True on success."""
    name = url.rsplit("/", 1)[-1]
    dialog.update(pct, f"Installing {name}")
    temp_path = xbmcvfs.translatePath("special://temp/" + name)
    addons_path = xbmcvfs.translatePath("special://home/addons/")
    ok = False
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Kodi"})
        with urllib.request.urlopen(req, timeout=60) as r, open(temp_path, "wb") as f:
            f.write(r.read())
        with zipfile.ZipFile(temp_path, "r") as z:
            z.extractall(addons_path)
        ok = True
    except Exception as e:  # noqa: BLE001 - one bad zip must not abort the run
        xbmc.log(f"[tony7bones.bootstrap] Failed {name}: {e}", xbmc.LOGERROR)
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)
    return ok


def _latest_zip_url(addon_id):
    """Resolve a first-party add-on's current zip URL from its static addon.xml."""
    base = f"{STATIC_BASE}/{addon_id}"
    try:
        with urllib.request.urlopen(f"{base}/addon.xml", timeout=15) as r:
            xml = r.read().decode("utf-8", "replace")
        m = re.search(r'<addon\b[^>]*\bversion="([^"]+)"', xml)
        if m:
            return f"{base}/{addon_id}-{m.group(1)}.zip"
    except Exception as e:  # noqa: BLE001
        xbmc.log(
            f"[tony7bones.bootstrap] cannot resolve {addon_id}: {e}", xbmc.LOGERROR
        )
    return None


def _enable(addon_id):
    """Register + enable an add-on. SetAddonEnabled adds it to Kodi's installed
    table, which is what makes a directly-extracted add-on actually runnable.
    Works without the unknown-sources setting — that setting only gates the
    install-from-zip GUI, not this direct-extract + enable path."""
    xbmc.executeJSONRPC(
        json.dumps(
            {
                "jsonrpc": "2.0",
                "method": "Addons.SetAddonEnabled",
                "params": {"addonid": addon_id, "enabled": True},
                "id": 1,
            }
        )
    )
    xbmc.sleep(200)


def _install_with_deps(addon_id, dialog):
    """Install an app and its full dependency closure by direct extract.

    No modal installer is used (InstallAddon would deadlock the GUI), so this
    never freezes. The official index is loaded with this machine's platform
    tag so binary add-ons (pvr.iptvsimple + inputstream.* clients) resolve to
    the correct native build. After extracting the closure the caller rescans
    local add-ons and enables each id, which registers them and makes them
    function. Returns True once the app reports as installed.
    """
    if _is_installed(addon_id):
        return True
    plat = _platform_tag()
    indexes = [
        (PENO64_BASE, _load_index(PENO64_BASE)),
        (OFFICIAL_BASE, _load_index(OFFICIAL_BASE, plat)),
    ]
    closure = _resolve_closure([addon_id], indexes)
    if not any(aid == addon_id for aid, _ in closure):
        return False  # could not even resolve the app itself
    for aid, url in closure:
        if _is_installed(aid):
            continue
        _extract_zip(url, dialog, 100)
    # Rescan so Kodi sees the freshly extracted dirs, then enable the closure
    # dependencies-first so each app's imports are satisfied when it is enabled.
    xbmc.executebuiltin("UpdateLocalAddons()")
    xbmc.sleep(2000)
    for aid, _url in closure:
        _enable(aid)
    return _is_installed(addon_id)


# File-Manager sources added to userdata/sources.xml (the <files> section).
# (display name, path). The second path is the Android/Fire Stick internal
# storage dir — we try to create it (harmless no-op off Android) but always
# add the source entry regardless.
FILE_SOURCES = [
    ("Kodi home directory", "special://home"),
    ("Kodi sources directory", "/storage/emulated/0/kodi/"),
]


def _sources_xml_path():
    """Resolve the absolute path to userdata/sources.xml via xbmcvfs.

    special://profile is the active profile's userdata dir (== userdata/ for the
    master profile); sources.xml lives directly inside it. Fall back to the
    home-relative path if needed."""
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
    PRESERVES every existing source (Movies/Music/Pictures, a .tony7.bones
    source, anything else), and DEDUPES on both name and path so a second run
    adds nothing. For the Android internal-storage path we attempt mkdirs first
    (guarded — it can't and won't succeed off Android, which is fine) but add
    the source entry either way. Fully defensive: any error is logged and the
    rest of setup continues. The end-of-setup restart is what makes Kodi pick up
    the new sources (it caches sources.xml at startup)."""
    try:
        xml_path = _sources_xml_path()

        # Parse the existing file, or start a fresh <sources> tree.
        root = None
        if xml_path and os.path.exists(xml_path):
            try:
                root = ET.parse(xml_path).getroot()
            except ET.ParseError as e:
                xbmc.log(
                    f"[tony7bones.bootstrap] sources.xml malformed, recreating: {e}",
                    xbmc.LOGERROR,
                )
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
                    xbmc.log(
                        f"[tony7bones.bootstrap] mkdirs {path} skipped "
                        f"(expected off Android): {e}",
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
            xbmc.log(
                f"[tony7bones.bootstrap] added {added} file source(s) to {xml_path}",
                xbmc.LOGINFO,
            )
        else:
            xbmc.log(
                "[tony7bones.bootstrap] file sources already present (no change)",
                xbmc.LOGINFO,
            )
    except Exception as e:  # noqa: BLE001 - never abort the rest of setup
        xbmc.log(
            f"[tony7bones.bootstrap] _add_file_sources failed (non-fatal): {e}",
            xbmc.LOGERROR,
        )


# Estuary home/main-menu trim. Each home item in Estuary's xml/Home.xml is
# gated by   <visible>!Skin.HasSetting(HomeMenuNo<X>Button)</visible>,  so
# setting the matching skin BOOLEAN to true HIDES that item (verified by reading
# the real skin's Home.xml on Kodi 21 Omega). We hide eight and leave the four
# we keep (TV/Live TV, Add-ons/Programs, Favourites, Weather) untouched/visible.
#
# Two ids per item: the camel-case ID the skin's XML and Skin.SetBool use
# (HomeMenuNoMovieButton) and the LOWERCASE id the active skin persists into
# addon_data/skin.estuary/settings.xml (homemenunomoviebutton, type="bool",
# value "true"/"false"). Skin.HasSetting() is case-insensitive, so the skin
# reads either back. Note the SINGULAR forms the real skin uses: Movie (not
# Movies), MusicVideo (not MusicVideos), TVShow; and that Add-ons is gated by
# HomeMenuNoProgramsButton.
#
# Both mechanisms are applied, and this ordering matters (proven on the live
# box): when the skin is loaded, Kodi holds skin booleans in MEMORY and REWRITES
# settings.xml from memory on shutdown — so a file-only write is clobbered by the
# end-of-setup restart. Skin.SetBool() sets the in-memory value, which the
# shutdown then persists as "true", surviving the restart. The direct file merge
# is kept as a belt-and-suspenders fallback (covers a not-yet-loaded skin and
# guarantees the keys exist) and preserves every other existing skin setting.
ESTUARY_SKIN_ID = "skin.estuary"

# (camel-case id for Skin.SetBool / skin XML, lowercase id for settings.xml),
# for the eight items we HIDE. The four kept ids (HomeMenuNoTVButton,
# HomeMenuNoProgramsButton, HomeMenuNoFavButton, HomeMenuNoWeatherButton) are
# deliberately absent so they stay visible.
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
    settings.xml from memory on shutdown, so the in-memory true persists. No-op
    in effect off Estuary (the booleans simply aren't read by another skin)."""
    for camel, _low in ESTUARY_HIDE_SETTINGS:
        # Skin.SetBool(<id>) with no value sets it true — exactly how Estuary's
        # own "Main menu items" settings screen toggles each item off.
        xbmc.executebuiltin(f"Skin.SetBool({camel})")


def _trim_home_menu_writefile():
    """Merge the eight hide-booleans (= true) into skin.estuary's settings.xml,
    creating the file/dir if missing and PRESERVING every other existing setting.
    Belt-and-suspenders behind _trim_home_menu_setbool(): guarantees the keys
    exist even if the skin was never loaded. Idempotent; updates in place."""
    xml_path = _estuary_settings_path()
    os.makedirs(os.path.dirname(xml_path), exist_ok=True)

    # Parse the existing file, or start fresh. A malformed file is rebuilt.
    root = None
    if os.path.exists(xml_path):
        try:
            root = ET.parse(xml_path).getroot()
        except ET.ParseError as e:
            xbmc.log(
                f"[tony7bones.bootstrap] skin.estuary settings.xml malformed, "
                f"recreating: {e}",
                xbmc.LOGERROR,
            )
            root = None
    if root is None or root.tag != "settings":
        root = ET.Element("settings")

    # Index existing <setting id=...> (case-insensitive) so we update in place
    # and preserve everything else (other skin settings, the four kept ids).
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
    xbmc.log(
        f"[tony7bones.bootstrap] _trim_home_menu: wrote 8 hide-bools "
        f"({changed} changed) to {xml_path}",
        xbmc.LOGINFO,
    )


def _trim_home_menu():
    """Trim the stock Estuary home menu to TV, Add-ons, Favourites, Weather.

    Hides the other eight items by forcing each Estuary HomeMenuNo<X>Button
    boolean true. Applies BOTH mechanisms: Skin.SetBool (live in-memory value,
    which Kodi persists on the end-of-setup restart — the part that actually
    survives) and a direct settings.xml merge (fallback that guarantees the keys
    exist and preserves all other skin settings).

    Guard: only meaningful on the stock Estuary skin — when another skin is
    active this is a safe no-op (it returns before touching anything). Idempotent
    (re-running just re-asserts the eight values, never duplicating). Defensive:
    any failure is logged and swallowed so it can never abort the rest of setup,
    and it touches ONLY skin.estuary's settings — nothing else.
    """
    try:
        skin = ""
        try:
            skin = xbmc.getSkinDir() or ""
        except Exception:  # noqa: BLE001 - older/edge Kodi: treat as unknown
            skin = ""
        if skin and skin != ESTUARY_SKIN_ID:
            xbmc.log(
                f"[tony7bones.bootstrap] _trim_home_menu: active skin is {skin}, "
                "not skin.estuary — skipping (no-op)",
                xbmc.LOGINFO,
            )
            return
        _trim_home_menu_setbool()
        _trim_home_menu_writefile()
    except Exception as e:  # noqa: BLE001 - never abort the rest of setup
        xbmc.log(
            f"[tony7bones.bootstrap] _trim_home_menu failed (non-fatal): {e}",
            xbmc.LOGERROR,
        )


def _is_android():
    """True when running on Android (incl. Fire Stick), where the app cannot
    relaunch itself. Detected the same way as _platform_tag()."""
    if os.environ.get("ANDROID_ROOT") or os.environ.get("ANDROID_DATA"):
        return True
    try:
        return "android" in os.uname().sysname.lower()
    except AttributeError:  # Windows
        return False


def _self_uninstall():
    """Remove the Setup add-on itself so it leaves no permanent home tile.

    Kodi 21 Omega has NO uninstall path a script can call: there is no
    UninstallAddon executebuiltin (only install/enable/disable/run exist) and no
    JSON-RPC uninstall method (the Addons namespace exposes only GetAddons /
    GetAddonDetails / SetAddonEnabled / ExecuteAddon). The supported mechanism is
    therefore: delete our own add-on directory, then let the end-of-setup restart
    finalise removal. On the next start Kodi's add-on scan (CAddonMgr::FindAddons)
    skips the now-missing dir and AddonDatabase::SyncInstalled deletes the stale
    rows ("DELETE FROM installed WHERE addonID=..." plus its update rules and any
    repository entry) — so there is no dangling DB row and no "broken add-on".

    Defensive by design: this runs only after everything else succeeded, never
    raises (a failure here must not abort the run), and deletes ONLY this
    add-on's own directory — nothing else.

    Caveat: deleting a directory whose code is currently executing is fine on
    macOS / Linux / Android (the inode stays alive until the interpreter
    finishes; the path is just unlinked). On Windows the file is locked while
    open and the rmtree can partially fail; the restart still de-registers the
    add-on because SyncInstalled keys off addon.xml being absent — and even a
    fully-intact dir left behind is merely re-registered, never "broken". The
    target boxes (Fire Stick / Android, macOS, Linux) are unaffected.
    """
    try:
        my_id = "script.tony7bones.bootstrap"
        my_dir = xbmcvfs.translatePath("special://home/addons/" + my_id)
        # Hard guard: only ever delete OUR OWN add-on directory.
        if os.path.basename(os.path.normpath(my_dir)) != my_id:
            xbmc.log(
                "[tony7bones.bootstrap] self-uninstall: refusing unexpected path "
                f"{my_dir}",
                xbmc.LOGERROR,
            )
            return
        if os.path.isdir(my_dir):
            import shutil

            shutil.rmtree(my_dir, ignore_errors=True)
            xbmc.log(
                f"[tony7bones.bootstrap] self-uninstall: removed {my_dir}",
                xbmc.LOGINFO,
            )
    except Exception as e:  # noqa: BLE001 - self-uninstall must never abort the run
        xbmc.log(
            f"[tony7bones.bootstrap] self-uninstall failed (non-fatal): {e}",
            xbmc.LOGERROR,
        )


def _restart_kodi():
    """Restart Kodi the platform-correct way after setup completes.

    A restart is required so Kodi fully loads every freshly extracted add-on
    (avoids the Fire Stick end-of-setup freeze where half-registered add-ons
    leave the UI wedged). The user always chooses Restart now / Later.

    * Desktop (Windows / Linux / macOS): RestartApp() truly cycles the app.
    * Android / Fire Stick: RestartApp() is unsupported and cannot relaunch the
      app, so we ask the user to fully close and reopen Kodi, then Quit() on
      confirmation for a clean exit they relaunch by hand.
    """
    if _is_android():
        if xbmcgui.Dialog().yesno(
            "Tony.7.Bones Setup",
            "Setup is complete. Kodi must fully close and reopen to finish.\n\n"
            "Close Kodi now? After it closes, open it again from your home "
            "screen to finish setup.",
            yeslabel="Close now",
            nolabel="Later",
        ):
            xbmc.log("[tony7bones.bootstrap] restart: Android Quit()", xbmc.LOGINFO)
            xbmc.executebuiltin("Quit()")
        return

    if xbmcgui.Dialog().yesno(
        "Tony.7.Bones Setup",
        "Setup is complete. Kodi needs to restart to finish.\n\nRestart now?",
        yeslabel="Restart now",
        nolabel="Later",
    ):
        xbmc.log("[tony7bones.bootstrap] restart: RestartApp()", xbmc.LOGINFO)
        xbmc.executebuiltin("RestartApp()")


def run():
    dialog = xbmcgui.DialogProgress()
    dialog.create("Tony.7.Bones Setup", "Starting setup...")

    total = len(REPO_ZIPS) + len(FIRST_PARTY) + len(ADDONS) + 1
    step = 0
    repo_ok = fp_ok = app_ok = 0

    # 1. repos by direct extract
    for zip_name, _rid in REPO_ZIPS:
        step += 1
        if _extract_zip(REPO_BASE + zip_name, dialog, int(step / total * 100)):
            repo_ok += 1
        if dialog.iscanceled():
            return dialog.close()

    # 2. first-party add-ons by direct extract
    for addon_id in FIRST_PARTY:
        step += 1
        url = _latest_zip_url(addon_id)
        if url and _extract_zip(url, dialog, int(step / total * 100)):
            fp_ok += 1
        if dialog.iscanceled():
            return dialog.close()

    # 3. register + enable the repos and first-party add-ons.
    step += 1
    dialog.update(int(step / total * 100), "Registering add-ons...")
    xbmc.executebuiltin("UpdateLocalAddons()")
    xbmc.sleep(3000)
    for _zip_name, rid in REPO_ZIPS:
        if rid:
            _enable(rid)
    for addon_id in FIRST_PARTY:
        _enable(addon_id)

    # 4. install each app with its dependency closure by direct extract.
    #    No modal installer, so the GUI never freezes.
    for addon_id in ADDONS:
        step += 1
        dialog.update(int(step / total * 100), f"Installing {addon_id}")
        if _install_with_deps(addon_id, dialog):
            app_ok += 1
        if dialog.iscanceled():
            return dialog.close()

    dialog.close()
    xbmcgui.Dialog().ok(
        "Tony.7.Bones Setup",
        f"Repos: {repo_ok}/{len(REPO_ZIPS)}\n"
        f"Patches: {fp_ok}/{len(FIRST_PARTY)}\n"
        f"Apps: {app_ok}/{len(ADDONS)}\n"
        "Open Add-ons to finish any remaining setup.",
    )
    # Run once, then disappear: remove ourselves so no Setup tile lingers on the
    # home screen. Done AFTER the summary and only after everything else ran; it
    # never raises (so a failure here can't break the run) and deletes only our
    # own add-on dir. The restart below de-registers us from the add-on DB.
    _self_uninstall()
    # Add our File-Manager sources (Kodi home + sources dirs) to sources.xml.
    # Must run BEFORE the restart: Kodi caches sources.xml at startup, so the
    # new entries only appear in File Manager after the end-of-setup restart.
    _add_file_sources()
    # Trim the stock Estuary home menu down to TV, Add-ons, Favourites, Weather.
    # Must run BEFORE the restart: the restart is what makes Estuary re-read its
    # settings.xml and drop the eight hidden items from the main menu.
    _trim_home_menu()
    # A restart finalises the freshly extracted add-ons AND finalises the
    # self-removal (the startup scan drops the now-missing add-on from the DB).
    # Platform-correct and prompt-driven so it never freezes (Fire Stick fix).
    # If the user declines the restart the state is still sane: our files are
    # gone, we stay enabled in the DB until the next start, and that next start
    # cleans the row — there is no broken/half-state in between.
    _restart_kodi()


if __name__ == "__main__":
    run()
