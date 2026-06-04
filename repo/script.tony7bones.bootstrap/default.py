"""Tony 7 Bones Setup — one-tap install for a fresh Kodi box.

Installs by add-on id only. No display-name labels. No install prompts.

run():
  * extracts the repo installer zips (direct download)
  * extracts first-party add-ons from our Pages (version resolved live)
  * enables them
  * builds an index of every add-on available across the installed repos
    (plus the Kodi add-on repo) and direct-extracts each requested app together
    with its full dependency closure — so InstallAddon (which prompts) is never
    called for the apps either.

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
KODI_REPO = "repository.xbmc.org"  # ships with Kodi; provides script.module.* deps
SYSTEM_PREFIXES = ("xbmc.", "kodi.")

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

# EZ Maintenance+ repo (provides Easy Maintenance + and Real-Debrid) — set when known.
EZ_MAINT_REPO_ZIP_URL = ""
EZ_MAINT_REPO_ID = ""

# Third-party app ids installed (with their dependencies) from the repos.
ADDONS = ["plugin.video.pov", "plugin.video.sporthdme", "plugin.video.the-loop"]


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


def _download_text(url):
    """Download text, transparently gunzipping addons.xml.gz."""
    try:
        with urllib.request.urlopen(url, timeout=20) as r:
            data = r.read()
        if url.endswith(".gz") or data[:2] == b"\x1f\x8b":
            data = gzip.decompress(data)
        return data.decode("utf-8", "replace")
    except Exception as e:
        xbmc.log(f"[tony7bones.bootstrap] cannot fetch {url}: {e}", xbmc.LOGERROR)
        return ""


def _repo_dirs(repo_id):
    """Yield (addons_xml_url, datadir) for each <dir> of an installed repo."""
    path = xbmcvfs.translatePath(f"special://home/addons/{repo_id}/addon.xml")
    if not os.path.exists(path):
        return
    try:
        root = ET.parse(path).getroot()
    except ET.ParseError:
        return
    for ext in root.findall("extension"):
        if ext.get("point") != "xbmc.addon.repository":
            continue
        containers = ext.findall("dir") or [ext]
        for d in containers:
            info = d.findtext("info")
            datadir = d.findtext("datadir")
            if info and datadir:
                yield info.strip(), datadir.strip().rstrip("/")


def _build_index(repo_ids):
    """Map addon id -> (version, datadir, [required ids]) across installed repos."""
    index = {}
    for repo_id in repo_ids:
        for info_url, datadir in _repo_dirs(repo_id):
            xml = _download_text(info_url)
            if not xml:
                continue
            try:
                root = ET.fromstring(xml)
            except ET.ParseError:
                continue
            for addon in root.findall("addon"):
                aid, ver = addon.get("id"), addon.get("version")
                if not aid or not ver:
                    continue
                reqs = [
                    imp.get("addon")
                    for imp in addon.findall("requires/import")
                    if imp.get("addon")
                ]
                index.setdefault(aid, (ver, datadir, reqs))
    return index


def _zip_url(datadir, addon_id, version):
    return f"{datadir}/{addon_id}/{addon_id}-{version}.zip"


def _install_tree(addon_id, index, done, failed, dialog, pct, seen=None):
    """Direct-extract an add-on and its dependency closure. Returns True if present."""
    if seen is None:
        seen = set()
    if addon_id in done or addon_id.startswith(SYSTEM_PREFIXES):
        return True
    if addon_id in seen:  # cyclic dependency — break the recursion
        return True
    seen.add(addon_id)
    if _is_installed(addon_id):
        done.add(addon_id)
        return True
    if addon_id not in index:
        failed.add(addon_id)
        xbmc.log(f"[tony7bones.bootstrap] unresolved: {addon_id}", xbmc.LOGERROR)
        return False
    version, datadir, reqs = index[addon_id]
    for dep in reqs:
        _install_tree(dep, index, done, failed, dialog, pct, seen)
    if _extract_zip(_zip_url(datadir, addon_id, version), dialog, pct):
        done.add(addon_id)
        return True
    failed.add(addon_id)
    return False


def run():
    dialog = xbmcgui.DialogProgress()
    dialog.create("Tony 7 Bones Setup", "Starting setup...")

    _set_unknown_sources()

    repo_jobs = list(REPO_ZIPS)
    if EZ_MAINT_REPO_ZIP_URL:
        repo_jobs.append((EZ_MAINT_REPO_ZIP_URL, EZ_MAINT_REPO_ID))
    total = len(repo_jobs) + len(FIRST_PARTY) + 2 + len(ADDONS)
    step = 0
    repo_ok = fp_ok = app_ok = 0

    # 1. repos by direct extract
    for entry, _rid in repo_jobs:
        step += 1
        url = entry if entry.startswith("http") else REPO_BASE + entry
        if _extract_zip(url, dialog, int(step / total * 100)):
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

    # 3. register + enable the repos and first-party add-ons
    step += 1
    dialog.update(int(step / total * 100), "Registering add-ons...")
    xbmc.executebuiltin("UpdateLocalAddons()")
    xbmc.sleep(5000)
    repo_ids = [rid for _entry, rid in repo_jobs if rid]
    for rid in repo_ids:
        _enable(rid)
    for addon_id in FIRST_PARTY:
        _enable(addon_id)

    # 4. build the add-on index and direct-extract each app + its dependencies
    step += 1
    dialog.update(int(step / total * 100), "Resolving add-ons...")
    # Kodi official repo FIRST so its Kodi-matched versions of shared modules
    # (script.module.requests, etc.) win over any older copy in a third-party repo.
    index = _build_index([KODI_REPO] + repo_ids)
    done, failed = set(), set()
    for addon_id in ADDONS:
        step += 1
        if _install_tree(
            addon_id, index, done, failed, dialog, int(step / total * 100)
        ):
            app_ok += 1
        if dialog.iscanceled():
            return dialog.close()

    # 5. register + enable everything newly extracted
    xbmc.executebuiltin("UpdateLocalAddons()")
    xbmc.sleep(3000)
    for addon_id in done:
        _enable(addon_id)

    dialog.close()
    xbmcgui.Dialog().ok(
        "Tony 7 Bones Setup",
        f"Repos: {repo_ok}/{len(repo_jobs)}\n"
        f"Patches: {fp_ok}/{len(FIRST_PARTY)}\n"
        f"Apps: {app_ok}/{len(ADDONS)}\n"
        "Open Add-ons to finish any remaining setup.",
    )


if __name__ == "__main__":
    run()
