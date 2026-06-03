"""Tony.7.Bones Bootstrap — one-tap setup for a fresh Kodi box.

run() installs, in one pass:
  * the 12 third-party repos from the Tony.7.Bones repositories/ folder
    (repository.tony7bones, the virtual repo, is already installed — that's how
    this script got here — giving 13 repos total)
  * first-party add-ons hosted on our own Pages (the Estuary MOD V2 patch),
    installed PROMPT-FREE by direct download + extract — never via InstallAddon
    (which pops a blocking confirm dialog and routes through the in-Kodi proxy)
  * the video apps POV / Sports HD / The Loop, from their repos (these still use
    InstallAddon and may prompt — making them silent needs per-app dependency
    resolution, tracked separately)

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

# 2. First-party add-ons on our own Pages — installed by direct extract, prompt-free.
#    The version is resolved live from the static addon.xml, so this never goes stale.
FIRST_PARTY = [
    ("script.tony7bones.modv2.patch", "Estuary MOD V2 Patch"),
]

# 3. EZ Maintenance+ repo — provides "Easy Maintenance +" and the RealDebrid app.
#    TODO confirm: a full https URL to the repo zip (or "" to skip), and its addon id.
EZ_MAINT_REPO_ZIP_URL = ""  # e.g. "https://.../repository.ezmaintenance-x.y.z.zip"
EZ_MAINT_REPO_ID = ""  # e.g. "repository.ezmaintenance"

# 4. Third-party apps installed from their repos via InstallAddon (id, display name).
#    Empty id = skip (not yet confirmed).
ADDONS = [
    ("plugin.video.pov", "POV"),
    ("plugin.video.sporthdme", "Sports HD"),
    ("plugin.video.the-loop", "The Loop"),
    ("", "Easy Maintenance +"),  # TODO confirm id (from EZ Maintenance+ repo)
    ("", "RealDebrid"),  # TODO confirm id (from EZ Maintenance+ repo)
]


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


def _extract_zip(url, label, dialog, pct):
    """Download a zip and extract it into addons/. Returns True on success."""
    dialog.update(pct, f"Installing: {label}")
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
    xbmc.sleep(300)


def _install(addon_id, name, dialog, pct):
    """Install a third-party add-on from a registered repo. Returns True if present."""
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

    _set_unknown_sources()

    repo_jobs = list(REPO_ZIPS)
    if EZ_MAINT_REPO_ZIP_URL:
        repo_jobs.append((EZ_MAINT_REPO_ZIP_URL, EZ_MAINT_REPO_ID))
    app_jobs = [a for a in ADDONS if a[0]]
    total = len(repo_jobs) + len(FIRST_PARTY) + 2 + len(app_jobs)
    step = 0
    repo_ok = fp_ok = app_ok = 0

    # 1. repos by direct extract
    for entry, _rid in repo_jobs:
        step += 1
        url = entry if entry.startswith("http") else REPO_BASE + entry
        if _extract_zip(url, entry.rsplit("/", 1)[-1], dialog, int(step / total * 100)):
            repo_ok += 1
        if dialog.iscanceled():
            return dialog.close()

    # 2. first-party add-ons by direct extract (prompt-free, version resolved live)
    for addon_id, name in FIRST_PARTY:
        step += 1
        url = _latest_zip_url(addon_id)
        if url and _extract_zip(url, name, dialog, int(step / total * 100)):
            fp_ok += 1
        if dialog.iscanceled():
            return dialog.close()

    # 3. register + enable everything extracted (no prompts)
    step += 1
    dialog.update(int(step / total * 100), "Registering add-ons...")
    xbmc.executebuiltin("UpdateLocalAddons()")
    xbmc.sleep(5000)
    for _entry, rid in repo_jobs:
        if rid:
            _enable(rid)
    for addon_id, _name in FIRST_PARTY:
        _enable(addon_id)

    # 4. fetch each repo's add-on list
    step += 1
    dialog.update(int(step / total * 100), "Fetching repository add-on lists...")
    xbmc.executebuiltin("UpdateAddonRepos()", True)
    xbmc.sleep(20000)
    if dialog.iscanceled():
        return dialog.close()

    # 5. third-party apps via InstallAddon (may prompt)
    for addon_id, name in app_jobs:
        step += 1
        if _install(addon_id, name, dialog, int(step / total * 100)):
            app_ok += 1
        if dialog.iscanceled():
            return dialog.close()

    dialog.close()
    xbmcgui.Dialog().ok(
        "Tony.7.Bones Bootstrap",
        f"Repos: {repo_ok}/{len(repo_jobs)}\n"
        f"Patches: {fp_ok}/{len(FIRST_PARTY)}\n"
        f"Apps: {app_ok}/{len(app_jobs)}\n"
        "Open Add-ons to finish any remaining setup.",
    )


if __name__ == "__main__":
    run()
