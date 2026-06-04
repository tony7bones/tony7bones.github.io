"""HTTP fetch, zip extract, and add-on enable/disable primitives.

The low-level building blocks shared by both Setups: fetching an addons.xml
index (transparently gunzipping a .gz), downloading + extracting an add-on zip
into addons/, and toggling an add-on enabled/disabled through Kodi's JSON-RPC
(which registers a directly-extracted add-on into Kodi's installed table — the
step that makes it runnable, independent of the unknown-sources setting).
"""

import gzip
import json
import os
import urllib.request
import zipfile

import xbmc
import xbmcaddon
import xbmcvfs


def is_installed(addon_id):
    """True when Kodi has the add-on registered (xbmcaddon.Addon succeeds)."""
    try:
        xbmcaddon.Addon(addon_id)
        return True
    except RuntimeError:
        return False


def http_get(url, timeout=30):
    """Fetch bytes, transparently gunzipping a .gz index."""
    req = urllib.request.Request(url, headers={"User-Agent": "Kodi"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = r.read()
    if url.endswith(".gz"):
        data = gzip.decompress(data)
    return data


def extract_zip(url, dialog, pct, log):
    """Download a zip and extract it into addons/. Returns True on success.

    `dialog` is an optional DialogProgress (None is allowed). One bad zip is
    logged and swallowed (returns False) so a single failure never aborts a run.
    """
    name = url.rsplit("/", 1)[-1]
    if dialog is not None:
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
        log(f"failed {name}: {e}", xbmc.LOGERROR)
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)
    return ok


def update_local_addons():
    """Rescan addons/ so Kodi sees freshly extracted directories."""
    xbmc.executebuiltin("UpdateLocalAddons()")


def _set_enabled(addon_id, enabled):
    xbmc.executeJSONRPC(
        json.dumps(
            {
                "jsonrpc": "2.0",
                "method": "Addons.SetAddonEnabled",
                "params": {"addonid": addon_id, "enabled": enabled},
                "id": 1,
            }
        )
    )
    xbmc.sleep(200)


def enable(addon_id):
    """Register + enable an add-on. SetAddonEnabled adds it to Kodi's installed
    table, which is what makes a directly-extracted add-on actually runnable.
    Works without the unknown-sources setting — that setting only gates the
    install-from-zip GUI, not this direct-extract + enable path."""
    _set_enabled(addon_id, True)


def disable(addon_id):
    """Disable an installed add-on (enabled=false).

    The add-on stays installed/registered — Kodi keeps it as a satisfied
    dependency for anything that requires it — but it is never invoked.
    """
    _set_enabled(addon_id, False)
