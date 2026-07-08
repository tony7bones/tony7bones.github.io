"""Make a restore stick on Apple TV (tvOS) by re-writing the restored userdata *.xml
THROUGH xbmcvfs, so Kodi vectors each file into NSUserDefaults.

Why this exists (root cause, verified in Kodi's tvOS source `xbmc/platform/darwin/tvos/`):
tvOS gives an app ~500 KB of normal app-directory storage, so Kodi stores `userdata/*.xml`
in the app's NSUserDefaults and rewrites the on-disk files from that mirror on launch. A
`.xml` write THROUGH xbmcvfs is dispatched to `CTVOSFile::Write` ->
`CTVOSNSUserDefaults::SetKeyDataFromPath(..., synchronize=true)` -> `[NSUserDefaults
synchronize]`, i.e. persisted to the only durable tvOS store BEFORE the call returns, with
no dependency on a clean shutdown. But the restore extracts with plain Python `zipfile`
(`zin.extract`) = a plain POSIX write that BYPASSES CTVOSFile, so the restored files never
reach NSUserDefaults and are shadowed by the stale mirror at boot. Re-writing each restored
`.xml` through xbmcvfs here dissolves that shadow. On Fire TV / desktop the same call is a
harmless rewrite of identical bytes.

Hard rules (see docs/plans/atv-restore-*.md and the adversarial review that produced them):
- SINGLE write per file, NEVER chunk. `CTVOSFile::Write` REPLACES the whole NSUserDefaults
  key on every call, so a chunked loop would leave only the last chunk -> a truncated XML
  fragment -> settings reset to defaults, unrecoverable (worse than the shadow bug). Read
  the whole file with plain `open()` (per kodi-vfs-cannot-read-foreign-local-files.md the
  READ must be plain, never xbmcvfs), write it in ONE `xbmcvfs.File.write` call, check the
  return.
- EXCLUDE this add-on's own settings.xml (carries the SOURCE box's paths + Dropbox secret,
  and service.py int()-parses those at import -> would crash the boot service).
- IPTV instance settings are handled in a PVR-disabled window (a live pvr.iptvsimple client
  clobbers direct writes on shutdown), NOT in the general walk.
"""

import json
import os

import xbmc
import xbmcvfs

ADDON_ID = "script.ezmaintenanceplusplus"
PVR_BACKEND_ID = "pvr.iptvsimple"

# Files (relative to userdata/, forward-slash) the general walk must NOT re-vector.
DEFAULT_EXCLUDES = (
    # Our own settings carry the source box's download/restore paths AND its
    # dropbox_refresh_token (a secret); service.py reads several at import with int(),
    # so a foreign/blank value would crash the boot service.
    "addon_data/%s/settings.xml" % ADDON_ID,
)

# Whole subtrees (relative to userdata/, forward-slash) the general walk must skip.
DEFAULT_EXCLUDE_DIR_PREFIXES = (
    # pvr.iptvsimple instance/customTVGroups files are handled by the disable-window
    # (reassert_iptv_instances), never written under a live client.
    "addon_data/%s/" % PVR_BACKEND_ID,
)


def _special_for(rel):
    """special:// path Kodi routes through CTVOSFile on tvOS (the /userdata key match)."""
    return "special://home/userdata/" + rel.replace("\\", "/")


def _vfs_rewrite_once(posix_src, special_dst):
    """Read the whole file with PLAIN python, write it in EXACTLY ONE xbmcvfs write.

    Returns True only on a confirmed write. On any failure returns False and leaves the
    POSIX source untouched (so the worst case is the pre-existing shadow, never data loss).
    NEVER chunk here (see module docstring) and NEVER reuse ui.py's _stream_copy/_LocalReader.
    """
    try:
        with open(posix_src, "rb") as fh:
            data = fh.read()
    except OSError:
        return False
    f = None
    try:
        f = xbmcvfs.File(special_dst, "w")
        ok = f.write(bytearray(data))  # ONE call, full payload; check the boolean return
        return bool(ok)
    except Exception:
        return False
    finally:
        try:
            if f is not None:
                f.close()
        except Exception:
            pass


def rewrite_userdata_xml(
    userdata_dir,
    exclude_rel=DEFAULT_EXCLUDES,
    exclude_dir_prefixes=DEFAULT_EXCLUDE_DIR_PREFIXES,
    log=None,
):
    """Re-write every *.xml under userdata_dir through xbmcvfs. Returns
    (written, skipped, failed). Fully guarded; never raises."""
    written = skipped = failed = 0
    excl = {x.replace("\\", "/") for x in exclude_rel}
    prefixes = tuple(p.replace("\\", "/") for p in exclude_dir_prefixes)
    try:
        for dirpath, _dirnames, filenames in os.walk(userdata_dir):
            for name in filenames:
                if not name.lower().endswith(".xml"):
                    continue
                posix = os.path.join(dirpath, name)
                rel = os.path.relpath(posix, userdata_dir).replace("\\", "/")
                if rel in excl or any(rel.startswith(p) for p in prefixes):
                    skipped += 1
                    continue
                if _vfs_rewrite_once(posix, _special_for(rel)):
                    written += 1
                else:
                    failed += 1
    except Exception:
        pass
    if log:
        log(
            "nsud: userdata xml re-write: %d written, %d skipped, %d failed"
            % (written, skipped, failed)
        )
    return (written, skipped, failed)


def _rpc(method, params):
    req = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
    try:
        return json.loads(xbmc.executeJSONRPC(json.dumps(req)))
    except Exception:
        return {}


def _set_pvr_enabled(enabled):
    _rpc("Addons.SetAddonEnabled", {"addonid": PVR_BACKEND_ID, "enabled": bool(enabled)})


def reassert_iptv_instances(userdata_dir, log=None):
    """Force pvr.iptvsimple to adopt the RESTORED instance settings, inside a PVR-disabled
    window (a live client clobbers direct writes on shutdown; Kodi reads instance-settings
    once at client instantiation and never watches the file, so the disable->settle->write->
    enable bounce is the only in-Kodi way to make the placed files take effect).

    Enumerates the restore's ACTUAL instance-settings-*.xml (no fixed 1+2 assumption). If
    pvr.iptvsimple's addon_data is absent or has no instance-settings, it is a no-op (never
    disturbs a box that has no restored IPTV). Returns (written, failed). Never raises.
    """
    pvr_dir = os.path.join(userdata_dir, "addon_data", PVR_BACKEND_ID)
    try:
        xmls = [n for n in os.listdir(pvr_dir) if n.lower().endswith(".xml")]
    except OSError:
        return (0, 0)  # pvr.iptvsimple not installed / no addon_data restored
    instances = [n for n in xmls if n.lower().startswith("instance-settings-")]
    if not instances:
        return (0, 0)  # nothing restored for IPTV; leave the client alone

    written = failed = 0
    try:
        _set_pvr_enabled(False)  # tear the client down; its stale flush lands FIRST
        xbmc.sleep(1000)  # settle
        # Re-write instance-settings-*.xml AND customTVGroups-*.xml (all .xml, all vector).
        for name in xmls:
            rel = "addon_data/%s/%s" % (PVR_BACKEND_ID, name)
            if _vfs_rewrite_once(os.path.join(pvr_dir, name), _special_for(rel)):
                written += 1
            else:
                failed += 1
    except Exception:
        pass
    finally:
        try:
            _set_pvr_enabled(True)  # re-enable FORCES a re-read of our files
        except Exception:
            pass
    if log:
        log(
            "nsud: iptv re-assert across %d instance(s): %d written, %d failed"
            % (len(instances), written, failed)
        )
    return (written, failed)
