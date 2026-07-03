"""apply_backup — the Backup layer of the modular setup (plan section 3.1a).

Installs EZ Maintenance++ (``script.ezmaintenanceplusplus``, this repo's own fork
with the NFS/SMB retry hardening — see the repo's `docs/plans/automate-share-and-
backup-config.md`, Decision C) and configures it with a port-free, PER-DEVICE NFS
backup destination on the mini's Backup share. Runs immediately after Foundation —
a fresh box has a working backup/restore path as early as possible, second only to
the shares themselves.

Two things make this layer NOT a drop-in copy of the Foundation skin/weather/
autocomplete install pattern:

  * **EZM++ is invisible to the normal closure resolver.** Its `repository.json`
    entry is served ONLY by our own ``127.0.0.1`` proxy, and the closure resolver
    (``repos.repo_dirs()``) explicitly skips ``127.0.0.1``/``localhost`` — so
    ``install_selection()``/``install_with_deps()`` (the obvious-looking APIs)
    would silently install NOTHING. This is the exact closure-invisibility class
    already solved for ``pvr.artwork``/``modv2plus`` — DIRECT EXTRACT via
    ``_latest_zip_url`` is the only mechanism that works here.
  * **The settings write is gated on a VERIFIED install**, not merely "the extract
    call didn't raise". ``_install_ezm`` returns the outcome of a genuine
    ``is_installed()`` registry check after the extract+register+enable sequence,
    and ``apply_backup`` only calls ``_configure_backup`` when that check passed —
    otherwise the probe could read "done" (settings.xml present and correct) for
    an add-on that was never actually registered and can't run.
  * **The per-device slug uses the FULL device-identity fallback chain**
    (``env.resolve_device_name``: env ``DEVICE_NAME`` -> Kodi's own
    ``services.devicename`` setting -> the generic slug), not just the env
    value alone. ``DEVICE_NAME`` ships commented-out by default in the env
    template — without the Kodi-setting fallback, every box that never enabled
    it would collapse to the SAME generic ``device`` slug and silently
    overwrite each other's backups on the shared remote destination (harmless
    for a local file, a real collision here).

``destination=1`` (Network) is written regardless of the path form — confirmed
against ``wiz.py``: Local(0) and Network(1) are identical in the ``++`` fork except
the Dropbox branch at ``==2``, so Network is the clearer, correct value for an NFS
destination either way.
"""

import os
import re
import urllib.request
from xml.etree import ElementTree as ET

import xbmc
import xbmcvfs

from tony7bones import extract_zip, is_installed, update_local_addons
from tony7bones import enable as _enable

from .env import resolve_device_name, sanitize_device_name
from .foundation import STATIC_BASE, kodi_backup_url
from .result import LayerResult

MY_ID = "script.tony7bones.bootstrap"

# Our own `++` fork — the ONLY backup tool this Setup ever installs (Decision C).
EZM_ID = "script.ezmaintenanceplusplus"


def _log(msg, level=xbmc.LOGINFO):
    xbmc.log(f"[{MY_ID}] {msg}", level)


def _latest_zip_url(addon_id):
    """Resolve a first-party add-on's current zip URL from its static addon.xml.

    Same mechanism as ``foundation._latest_zip_url``/modv2plus's own resolver — a
    separate copy (not a shared import) so this module has no dependency on
    Foundation's internals beyond the two constants it explicitly re-exports."""
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


def _install_ezm(dialog):
    """Install EZ Maintenance++ by DIRECT EXTRACT (REQUIRED — see the module
    docstring; the normal closure resolver cannot see this add-on).

    Rescans + settles + enables after the extract, exactly like the skin's own
    direct-extract ritual, then returns a VERIFIED ``is_installed()`` result —
    not the extract call's own return value — so a caller never mistakes a
    failed-but-non-raising extract for a real install. A re-entry where it's
    already installed short-circuits. Never raises (a backup-tool failure must
    not abort the box)."""
    if is_installed(EZM_ID):
        return True
    try:
        if dialog is not None:
            dialog.update(0, "Installing EZ Maintenance++...")
        url = _latest_zip_url(EZM_ID)
        if not url:
            return False
        extract_zip(url, dialog, 100, _log)
        update_local_addons()
        xbmc.sleep(3000)
        _enable(EZM_ID)
        xbmc.sleep(1000)
        return is_installed(EZM_ID)
    except Exception as e:  # noqa: BLE001 - a backup-tool failure must not abort the box
        _log(f"EZM++ install failed (non-fatal): {e}", xbmc.LOGERROR)
        return False


def _ezm_settings_path():
    """Absolute path to EZ Maintenance++'s per-profile settings.xml."""
    return xbmcvfs.translatePath(
        "special://profile/addon_data/script.ezmaintenanceplusplus/settings.xml"
    )


def _configure_backup(box_env, device_name):
    """Write EZM++'s settings.xml so a fresh box has a working backup/restore
    path with ZERO manual steps: a port-free, PER-DEVICE NFS destination on the
    mini's Backup share (``Kodi/Backup/<device-slug>/`` — Decision B, no cross-box
    collisions, matches the existing ATV1/ATV2 shape; slug via
    ``env.sanitize_device_name``). Merges into any existing settings.xml
    (preserves other settings; idempotent; defensive — any failure is logged and
    swallowed, never aborts the rest of setup). Only ever called by
    ``apply_backup`` AFTER a verified EZM++ install (see the module docstring)."""
    try:
        box_env = box_env or {}
        slug = sanitize_device_name(device_name)
        path = kodi_backup_url(box_env).rstrip("/") + "/" + slug + "/"
        try:
            xbmcvfs.mkdirs(path)
        except Exception as e:  # noqa: BLE001 - a share hiccup must not abort setup
            _log(
                f"_configure_backup: mkdirs {path} failed (non-fatal): {e}",
                xbmc.LOGERROR,
            )

        xml_path = _ezm_settings_path()
        os.makedirs(os.path.dirname(xml_path), exist_ok=True)
        root = None
        if os.path.exists(xml_path):
            try:
                root = ET.parse(xml_path).getroot()
            except ET.ParseError as e:
                _log(f"EZM++ settings.xml malformed, recreating: {e}", xbmc.LOGERROR)
                root = None
        if root is None or root.tag != "settings":
            root = ET.Element("settings")
        by_id = {s.get("id"): s for s in root.findall("setting") if s.get("id")}

        def _set(setting_id, value):
            el = by_id.get(setting_id)
            if el is None:
                el = ET.SubElement(root, "setting")
                el.set("id", setting_id)
                by_id[setting_id] = el
            el.text = value

        # destination=1 (Network) — confirmed identical to Local(0) in wiz.py
        # except the Dropbox branch at ==2 (Decision D).
        _set("destination", "1")
        _set("download.path", path)
        _set("restore.path", path)

        with open(xml_path, "w", encoding="utf-8") as f:
            f.write(ET.tostring(root, encoding="unicode"))
        _log(f"_configure_backup: wrote EZM++ settings (destination={path})")
    except Exception as e:  # noqa: BLE001 - never abort the rest of setup
        _log(f"_configure_backup failed (non-fatal): {e}", xbmc.LOGERROR)


def apply_backup(
    env, *, dialog=None, log=None, install_ezm=None, configure_backup=None
):
    """Apply the Backup layer: install EZ Maintenance++ (direct extract — the
    normal closure resolver can't see it) and, only on a VERIFIED install,
    configure it with a port-free per-device NFS backup destination.

    Parameters
    ----------
    env
        The already-parsed per-device env dict (``MINI_HOST``/``KODI_BACKUP_NFS``/
        ``DEVICE_NAME`` are read from it).
    dialog
        The shared progress dialog (or ``None``); forwarded to the install.
    log
        The logging callable; reserved for future per-layer logging.
    install_ezm / configure_backup
        The two step functions, injectable (defaults to this module's bodies) —
        mirrors the Foundation layer's injection seam for testability.

    Returns
    -------
    LayerResult
        ``layer="backup"``. ``ok`` reflects the VERIFIED install (not merely
        "the extract didn't raise"). ``needs_restart=True`` is a REQUEST the
        orchestrator owns.
    """
    env = env or {}
    install_ezm = install_ezm or _install_ezm
    configure_backup = configure_backup or _configure_backup

    ezm_ok = install_ezm(dialog)
    if ezm_ok:
        configure_backup(env, resolve_device_name(env))

    installed = {EZM_ID: "installed"} if ezm_ok else {}
    failed = {} if ezm_ok else {EZM_ID: "install failed"}
    return LayerResult(
        layer="backup",
        ok=ezm_ok,
        installed=installed,
        failed=failed,
        needs_restart=True,
        detail=("EZ Maintenance++ installed" if ezm_ok else "EZ Maintenance++ FAILED"),
    )
