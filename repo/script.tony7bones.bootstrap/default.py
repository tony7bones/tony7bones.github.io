"""Tony.7.Bones Setup — one-tap install for a fresh Kodi box.

Installs by add-on id only. No display-name labels.

run():
  * extracts the repo installer zips (direct download)
  * extracts first-party add-ons from our Pages (version resolved live)
  * installs each requested app together with its full dependency closure by
    direct download + extract, then registers + enables every add-on through
    Kodi's add-on manager so the apps actually function.

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
FIRST_PARTY = ["script.tony7bones.modv2.patch"]

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
                deps = [imp.get("addon") for imp in a.findall("requires/import")]
                deps = [d for d in deps if d]
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


if __name__ == "__main__":
    run()
