"""Installed-repository discovery, source-repo enabling, and origin stamping.

The video Setup resolves its closure from the repositories ALREADY installed on
the box, so it needs to (a) discover each installed repository.* add-on's index
url + datadir, honouring the per-Kodi-release <dir> gates, (b) enable those
repos so Kodi treats their add-ons as repo-installed, and (c) stamp each
installed add-on's `origin` column with its source repo — an empty origin is
what breaks The Loop ("installed from unknown source") and POV (empty menu).
"""

import os
from xml.etree import ElementTree as ET

import xbmc
import xbmcvfs

from . import net

# This box's running Kodi major version, used to honour <dir> min/maxversion
# gates so we read the right (Omega) index for repos that ship several.
KODI_MAJOR = 21


def _version_ok(attr, *, is_min):
    """True when KODI_MAJOR satisfies a <dir> min/maxversion attribute.

    Attributes look like '20.90.0' / '21.0.0'. We compare on the major number
    only — enough to pick the Omega dir over Nexus/Matrix dirs in repos that ship
    one <dir> per Kodi release. A missing/garbage attr never gates.
    """
    if not attr:
        return True
    try:
        major = int(str(attr).split(".", 1)[0])
    except (ValueError, TypeError):
        return True
    return KODI_MAJOR >= major if is_min else KODI_MAJOR <= major


def repo_dirs(log):
    """Discover (repo_id, info_url, datadir_url) triples from every installed repo.

    Reads each special://home/addons/repository.*/addon.xml, walks its
    xbmc.addon.repository extension's <dir> blocks (or the legacy flat form where
    <info>/<datadir> sit directly under the extension), and keeps only the dirs
    whose min/maxversion gate matches this Kodi major. Our own host proxy
    (127.0.0.1) is skipped: it is not a content source here.

    repo_id is the owning repository.* add-on id; it is carried through the index
    so every installed add-on can be stamped with a real `origin`.
    """
    addons_root = xbmcvfs.translatePath("special://home/addons/")
    triples = []
    try:
        names = sorted(os.listdir(addons_root))
    except OSError as e:
        log(f"cannot list addons dir: {e}", xbmc.LOGERROR)
        return triples
    for name in names:
        if not name.startswith("repository."):
            continue
        axml = os.path.join(addons_root, name, "addon.xml")
        if not os.path.isfile(axml):
            continue
        try:
            root = ET.parse(axml).getroot()
        except ET.ParseError as e:
            log(f"bad addon.xml in {name}: {e}", xbmc.LOGERROR)
            continue
        repo_id = root.get("id") or name
        ext = root.find("extension[@point='xbmc.addon.repository']")
        if ext is None:
            continue
        dirs = ext.findall("dir")
        # Legacy flat repos put <info>/<datadir> directly under the extension.
        blocks = dirs if dirs else [ext]
        for d in blocks:
            if not _version_ok(d.get("minversion"), is_min=True):
                continue
            if not _version_ok(d.get("maxversion"), is_min=False):
                continue
            info = d.find("info")
            datadir = d.find("datadir")
            if info is None or info.text is None:
                continue
            info_url = info.text.strip()
            if "127.0.0.1" in info_url or "localhost" in info_url:
                continue  # our own proxy is not a content source
            base = (
                datadir.text.strip().rstrip("/")
                if datadir is not None and datadir.text
                else info_url.rsplit("/", 1)[0]
            )
            triples.append((repo_id, info_url, base))
    return triples


def have_source_repos(log):
    """True when at least one content repository (other than our own proxy) is
    installed, i.e. the main Tony.7.Bones Setup has been run."""
    return len(repo_dirs(log)) > 0


def enable_source_repos(log):
    """Enable every installed repository.* add-on (except our 127.0.0.1 proxy).

    The direct-extract setup drops repo dirs into addons/ but can leave them
    DISABLED, so Kodi never indexes them and never treats their add-ons as
    repo-installed — which is why installed apps end up with an empty origin.
    Enabling the repos makes the origin we stamp reference a repo Kodi knows
    about, and lets Kodi keep them current going forward. Never raises.
    """
    addons_root = xbmcvfs.translatePath("special://home/addons/")
    try:
        names = sorted(os.listdir(addons_root))
    except OSError:
        return
    for name in names:
        if not name.startswith("repository."):
            continue
        axml = os.path.join(addons_root, name, "addon.xml")
        if not os.path.isfile(axml):
            continue
        try:
            root = ET.parse(axml).getroot()
            repo_id = root.get("id") or name
            ext = root.find("extension[@point='xbmc.addon.repository']")
            info = ext.find("dir/info") if ext is not None else None
            if info is None and ext is not None:
                info = ext.find("info")
            info_url = (info.text or "") if info is not None else ""
            if "127.0.0.1" in info_url or "localhost" in info_url:
                continue  # our own proxy is not a content source
            net.enable(repo_id)
        except Exception:  # noqa: BLE001 - one bad repo must not abort the run
            continue


def _addons_db_path():
    """Locate Kodi's current Addons<NN>.db (the schema version varies by Kodi
    release — Omega ships Addons33.db). Returns the newest match, or None."""
    db_dir = xbmcvfs.translatePath("special://database/")
    try:
        cands = [
            os.path.join(db_dir, n)
            for n in os.listdir(db_dir)
            if n.startswith("Addons") and n.endswith(".db")
        ]
    except OSError:
        return None
    if not cands:
        return None

    def _schema_num(path):
        digits = "".join(c for c in os.path.basename(path) if c.isdigit())
        return int(digits) if digits else -1

    # Highest schema number wins (e.g. Addons33.db over Addons27.db).
    return max(cands, key=_schema_num)


def set_origins(origins, log):
    """Stamp each installed add-on's `origin` to its source repository id.

    `origins` is {addon_id: repository_id}. An empty origin is what breaks the
    video apps: The Loop opens a blocking "installed from unknown source" dialog
    on every launch (so its directory never returns), and POV's language strings
    fail to load (getLocalizedString -> '' -> setLabel raises -> empty menu).
    Kodi's own repository installer sets this column; the direct-extract path does
    not, so we set it ourselves — exactly the value Kodi would have written. We
    touch only the `origin` column of rows we just installed, and the change takes
    effect on the next Kodi start.

    Never raises: a failure here must not abort the run.
    """
    db = _addons_db_path()
    if not db:
        log("could not locate Addons DB; origins not set", xbmc.LOGERROR)
        return
    try:
        import sqlite3  # noqa: PLC0415 - stdlib, only needed here

        con = sqlite3.connect(db, timeout=10)
        try:
            for aid, repo_id in origins.items():
                if not repo_id:
                    continue
                con.execute(
                    "UPDATE installed SET origin=? WHERE addonID=? AND origin=''",
                    (repo_id, aid),
                )
            con.commit()
        finally:
            con.close()
        log(f"stamped origin on {len(origins)} add-on(s)", xbmc.LOGINFO)
    except Exception as e:  # noqa: BLE001 - origin stamping must not abort the run
        log(f"set_origins failed (non-fatal): {e}", xbmc.LOGERROR)
