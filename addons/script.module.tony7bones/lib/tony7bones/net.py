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


def _read_url(url, timeout, log=None, tries=4):
    """Fetch the full body of `url` as bytes, retrying transient network failures
    (connection aborts / timeouts) with exponential backoff before giving up.

    A single dropped download otherwise stalls a whole one-shot install — a flaky
    Wi-Fi moment shouldn't brick a provision. Retries up to `tries-1` times with
    1s/2s/4s backoff; re-raises the last error only if every attempt fails.
    """
    req = urllib.request.Request(url, headers={"User-Agent": "Kodi"})
    last = None
    for attempt in range(tries):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except Exception as e:  # noqa: BLE001 - retry transient network failures
            last = e
            if attempt < tries - 1:
                if log is not None:
                    log(
                        "net retry {}/{} for {}: {}".format(
                            attempt + 1, tries - 1, url.rsplit("/", 1)[-1], e
                        ),
                        xbmc.LOGWARNING,
                    )
                xbmc.sleep(1000 * (2**attempt))  # 1s, 2s, 4s
    raise last


def http_get(url, timeout=30, log=None):
    """Fetch bytes (with network retry), transparently gunzipping a .gz index."""
    data = _read_url(url, timeout, log)
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
        data = _read_url(url, 60, log)  # retries transient network failures
        with open(temp_path, "wb") as f:
            f.write(data)
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
