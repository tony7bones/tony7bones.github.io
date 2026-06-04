"""Tony 7 Bones Setup — one-tap install for a fresh Kodi box.

Installs by add-on id only. No display-name labels.

run():
  * extracts the repo installer zips (direct download)
  * extracts first-party add-ons from our Pages (version resolved live)
  * enables them and refreshes the repos so their contents are known
  * installs each requested app through Kodi's own repo installer
    (InstallAddon), one at a time — Kodi resolves the dependency closure
    and registers each add-on properly, so the apps actually function.

No secrets are embedded in this script.
"""

import json
import os
import re
import urllib.request
import zipfile

import xbmc
import xbmcaddon
import xbmcgui
import xbmcvfs

REPO_BASE = "https://tony7bones.github.io/repo/repositories/"
STATIC_BASE = "https://tony7bones.github.io/repo"

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

# Apps installed interactively through Kodi's repo installer, in order.
# Both live in the peno64 repository (installed above).
ADDONS = ["script.ezmaintenanceplus", "script.realdebrid"]


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


def _extract_zip(url, dialog, pct):
    """Download a zip and extract it into addons/. Returns True on success."""
    name = url.rsplit("/", 1)[-1]
    dialog.update(pct, f"Installing {name}")
    temp_path = xbmcvfs.translatePath("special://temp/" + name)
    addons_path = xbmcvfs.translatePath("special://home/addons/")
    ok = False
    try:
        urllib.request.urlretrieve(url, temp_path)
        with zipfile.ZipFile(temp_path, "r") as z:
            z.extractall(addons_path)
        ok = True
    except Exception as e:
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
    except Exception as e:
        xbmc.log(
            f"[tony7bones.bootstrap] cannot resolve {addon_id}: {e}", xbmc.LOGERROR
        )
    return None


def _enable(addon_id):
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


def _install_interactive(addon_id, dialog, pct):
    """Install an add-on via Kodi's own repo installer.

    InstallAddon resolves the dependency closure from the enabled repos and
    registers everything the way Kodi expects, so the app actually runs. The
    builtin is called with wait=True; afterwards we poll briefly for the add-on
    to appear. Returns True once it is installed.
    """
    if _is_installed(addon_id):
        return True
    dialog.update(pct, f"Installing {addon_id}")
    xbmc.executebuiltin(f"InstallAddon({addon_id})", True)
    for _ in range(30):
        if _is_installed(addon_id):
            return True
        xbmc.sleep(1000)
    return _is_installed(addon_id)


def run():
    dialog = xbmcgui.DialogProgress()
    dialog.create("Tony 7 Bones Setup", "Starting setup...")

    _set_unknown_sources()

    total = len(REPO_ZIPS) + len(FIRST_PARTY) + 2 + len(ADDONS)
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

    # 3. register + enable the repos and first-party add-ons, then refresh the
    #    repos so their remote add-on lists are known to the installer.
    step += 1
    dialog.update(int(step / total * 100), "Registering add-ons...")
    xbmc.executebuiltin("UpdateLocalAddons()")
    xbmc.sleep(5000)
    repo_ids = [rid for _zip_name, rid in REPO_ZIPS if rid]
    for rid in repo_ids:
        _enable(rid)
    for addon_id in FIRST_PARTY:
        _enable(addon_id)

    step += 1
    dialog.update(int(step / total * 100), "Refreshing repositories...")
    xbmc.executebuiltin("UpdateAddonRepos()")
    xbmc.sleep(8000)

    # 4. install each app through Kodi's repo installer, one at a time
    for addon_id in ADDONS:
        step += 1
        if _install_interactive(addon_id, dialog, int(step / total * 100)):
            _enable(addon_id)
            app_ok += 1
        if dialog.iscanceled():
            return dialog.close()

    dialog.close()
    xbmcgui.Dialog().ok(
        "Tony 7 Bones Setup",
        f"Repos: {repo_ok}/{len(REPO_ZIPS)}\n"
        f"Patches: {fp_ok}/{len(FIRST_PARTY)}\n"
        f"Apps: {app_ok}/{len(ADDONS)}\n"
        "Open Add-ons to finish any remaining setup.",
    )


if __name__ == "__main__":
    run()
