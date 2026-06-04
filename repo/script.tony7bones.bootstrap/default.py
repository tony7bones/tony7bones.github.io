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
# The two apps live in peno64; their module dependencies live in the official
# Kodi repo. The resolver walks <requires>/<import> recursively across both.
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
# Both live in the peno64 repository (installed above).
ADDONS = ["script.ezmaintenanceplus", "script.realdebrid"]

# Dependency ids provided by the Kodi runtime itself — never downloaded.
_SYSTEM_PREFIXES = ("xbmc.", "kodi.")


def _is_installed(addon_id):
    try:
        xbmcaddon.Addon(addon_id)
        return True
    except RuntimeError:
        return False


def _set_unknown_sources():
    """Allow zip installs without the per-install security warning (no dialog)."""
    xbmc.executeJSONRPC(
        json.dumps(
            {
                "jsonrpc": "2.0",
                "method": "Settings.SetSettingValue",
                "params": {"setting": "addons.unknownsources", "value": True},
                "id": 1,
            }
        )
    )


def _http_get(url, timeout=30):
    """Fetch bytes, transparently gunzipping a .gz index."""
    req = urllib.request.Request(url, headers={"User-Agent": "Kodi"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = r.read()
    if url.endswith(".gz"):
        data = gzip.decompress(data)
    return data


def _load_index(base):
    """Return {id: (version, [dep_ids])} from a repo's addons.xml(.gz)."""
    err = None
    for name in ("addons.xml.gz", "addons.xml"):
        try:
            root = ET.fromstring(_http_get(f"{base}/{name}"))
            out = {}
            for a in root.findall("addon"):
                deps = [imp.get("addon") for imp in a.findall("requires/import")]
                out[a.get("id")] = (a.get("version"), [d for d in deps if d])
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
    System imports (xbmc.* / kodi.*) are skipped — Kodi provides them.
    """
    resolved = {}  # id -> zip_url
    order = []

    def visit(aid):
        if aid in resolved or aid.startswith(_SYSTEM_PREFIXES):
            return
        for base, idx in indexes:
            if aid in idx:
                ver, deps = idx[aid]
                resolved[aid] = f"{base}/{aid}/{aid}-{ver}.zip"
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
    table, which is what makes a directly-extracted add-on actually runnable."""
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
    never freezes. After extracting the closure the caller rescans local
    add-ons and enables each id, which registers them and makes them function.
    Returns True once the app reports as installed.
    """
    if _is_installed(addon_id):
        return True
    indexes = [
        (PENO64_BASE, _load_index(PENO64_BASE)),
        (OFFICIAL_BASE, _load_index(OFFICIAL_BASE)),
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

    _set_unknown_sources()

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
