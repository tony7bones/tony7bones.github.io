"""Tony.7.Bones Bootstrap — one-tap setup for a fresh Kodi box.

run() installs, in one pass:
  * the 12 third-party repos from the Tony.7.Bones repositories/ folder
    (repository.tony7bones, the virtual repo, is already installed — that's how
    this script got here — giving 13 repos total)
  * the EZ Maintenance+ repo, then the apps it provides (Easy Maintenance +,
    RealDebrid)
  * the video apps: POV, Sports HD, The Loop
  * the Estuary MOD V2 patch, so it appears under Add-ons -> Program add-ons
    (this script does NOT run/apply it — the user runs it themselves)

No secrets are embedded in this script.
"""

import json
import os
import urllib.request
import zipfile

import xbmc
import xbmcaddon
import xbmcgui
import xbmcvfs

REPO_BASE = "https://tony7bones.github.io/repo/repositories/"

# 1. Repos installed directly by zip (the 12 in the Tony.7.Bones repositories/ folder).
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

# 2. EZ Maintenance+ repo — provides "Easy Maintenance +" and the RealDebrid app.
#    TODO confirm: a full https URL to the repo zip (or "" to skip), and its addon id.
EZ_MAINT_REPO_ZIP_URL = ""  # e.g. "https://.../repository.ezmaintenance-x.y.z.zip"
EZ_MAINT_REPO_ID = ""  # e.g. "repository.ezmaintenance"

# 3. Apps installed from the repos above (id, display name). Empty id = skip (not yet confirmed).
ADDONS = [
    ("plugin.video.pov", "POV"),
    ("plugin.video.sporthdme", "Sports HD"),
    ("plugin.video.the-loop", "The Loop"),
    ("", "Easy Maintenance +"),  # TODO confirm id (from EZ Maintenance+ repo)
    ("", "RealDebrid"),  # TODO confirm id (from EZ Maintenance+ repo)
]

# 4. Made available under Programs (installed, not run) — from repository.tony7bones.
PATCH_ADDON = ("script.tony7bones.modv2.patch", "Estuary MOD V2 patches")


def _is_installed(addon_id):
    try:
        xbmcaddon.Addon(addon_id)
        return True
    except RuntimeError:
        return False


def _extract_repo(url, label, dialog, pct):
    """Download a repository zip and extract it. Returns True on success."""
    dialog.update(pct, f"Installing repository: {label}")
    name = url.rsplit("/", 1)[-1]
    temp_path = xbmcvfs.translatePath("special://temp/" + name)
    addons_path = xbmcvfs.translatePath("special://home/addons/")
    ok = False
    try:
        urllib.request.urlretrieve(url, temp_path)
        with zipfile.ZipFile(temp_path, "r") as z:
            z.extractall(addons_path)
        ok = True
    except Exception as e:
        xbmc.log(f"[tony7bones.bootstrap] Failed to install {name}: {e}", xbmc.LOGERROR)
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)
    return ok


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
    xbmc.sleep(300)


def _install(addon_id, name, dialog, pct):
    """Install an add-on from a registered repo. Returns True if present after."""
    dialog.update(pct, f"Installing: {name}")
    if _is_installed(addon_id):
        return True
    for attempt in range(3):
        xbmc.executebuiltin(f"InstallAddon({addon_id})", True)
        xbmc.sleep(3000)
        if _is_installed(addon_id):
            return True
        xbmc.log(f"[tony7bones.bootstrap] {addon_id} attempt {attempt + 1} failed")
        xbmc.sleep(5000)
    return False


def run():
    dialog = xbmcgui.DialogProgress()
    dialog.create("Tony.7.Bones Bootstrap", "Starting setup...")

    repo_jobs = list(REPO_ZIPS)
    if EZ_MAINT_REPO_ZIP_URL:
        repo_jobs.append((EZ_MAINT_REPO_ZIP_URL, EZ_MAINT_REPO_ID))
    addon_jobs = [a for a in ADDONS if a[0]] + [PATCH_ADDON]
    total = len(repo_jobs) + 2 + len(addon_jobs)  # repos + register/enable + addons
    step = 0

    repo_ok = 0
    app_ok = 0

    # 1. install repos by zip
    for entry, _rid in repo_jobs:
        step += 1
        url = entry if entry.startswith("http") else REPO_BASE + entry
        if _extract_repo(
            url, entry.rsplit("/", 1)[-1], dialog, int(step / total * 100)
        ):
            repo_ok += 1
        if dialog.iscanceled():
            return dialog.close()

    # 2. register + enable the freshly extracted repos
    step += 1
    dialog.update(int(step / total * 100), "Registering repositories...")
    xbmc.executebuiltin("UpdateLocalAddons()")
    xbmc.sleep(5000)
    for _entry, rid in repo_jobs:
        if rid:
            dialog.update(int(step / total * 100), f"Enabling: {rid}")
            _enable(rid)

    # 3. fetch each repo's add-on list
    step += 1
    dialog.update(int(step / total * 100), "Fetching repository add-on lists...")
    xbmc.executebuiltin("UpdateAddonRepos()", True)
    xbmc.sleep(20000)
    if dialog.iscanceled():
        return dialog.close()

    # 4. install the apps (+ make the MOD V2 patch available)
    for addon_id, name in addon_jobs:
        step += 1
        if _install(addon_id, name, dialog, int(step / total * 100)):
            app_ok += 1
        if dialog.iscanceled():
            return dialog.close()

    dialog.close()
    xbmcgui.Dialog().ok(
        "Tony.7.Bones Bootstrap",
        f"Repos: {repo_ok}/{len(repo_jobs)} installed.\n"
        f"Apps: {app_ok}/{len(addon_jobs)} installed.\n"
        "Open Add-ons to finish any remaining setup.",
    )


run()
