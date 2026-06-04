"""Video Add-ons Setup — pick-and-install video add-ons for a Tony.7.Bones box.

run():
  * shows a multiselect picker of four video add-ons (POV, The Loop, Sports HD,
    Umbrella); the first three are preselected.
  * for each chosen add-on it resolves the FULL dependency closure live from the
    repositories ALREADY INSTALLED on this box (their addons.xml indexes) plus
    the official Kodi repo (for the shared script.module.* deps, so they match
    the running Kodi), then installs every add-on in the closure by direct
    download + extract and registers + enables each through Kodi's add-on
    manager, then STAMPS each installed add-on's `origin` with its source repo
    so the apps actually function (see below).
  * finally removes ITSELF after a successful run (run once, then disappear) so
    no Setup tile lingers on the home screen, and restarts Kodi to finish. It
    stays in the Tony.7.Bones repo for re-install whenever needed.

Why stamp `origin` (the fix for broken POV / The Loop): Kodi's repository
installer records which repo an add-on came from in the `installed.origin`
column. The direct-extract path leaves it blank, and a blank origin breaks the
video apps: The Loop shows a blocking "installed from unknown source" dialog on
every launch (its directory never returns -> "script aborted"), and POV's
language strings fail to load (getLocalizedString -> '' -> setLabel raises ->
empty menu). After installing we set origin to the providing repo — the exact
value Kodi would have written — and enable the source repos + restart so the
change is live on first launch. This keeps the prompt-free direct-extract path
(no modal installer) while making the apps actually browse content.

Why resolve from the INSTALLED repos rather than fixed URLs: these video apps
live across several third-party repos (The Loop -> repository.loop, Umbrella ->
repository.umbrella, POV -> a dir of repository.kodifitzwell, Sports HD ->
repository.bugatsinho) and pull shared modules (resolveurl, requests, etc.) from
those repos' secondary dirs and from the official repo. Reading each installed
repository.* add-on.xml for its <dir> info/datadir, building a combined index,
and walking <requires>/<import> means we always fetch the versions the box's own
repos publish — no hardcoded source that can drift.

Why not Kodi's InstallAddon builtin: on Omega it calls a *modal* installer on
the GUI thread that pops a blocking yes/no and never returns when driven from a
script — the GUI locks. There is no JSON-RPC install method on Omega either
(the Addons namespace only exposes GetAddons / GetAddonDetails /
SetAddonEnabled / ExecuteAddon). So we resolve the closure ourselves and extract
every zip directly, then SetAddonEnabled each one — which registers it in Kodi's
installed table and makes it runnable, regardless of the unknown-sources setting.

No secrets are embedded in this script.
"""

import gzip
import json
import os
import urllib.request
import zipfile
from xml.etree import ElementTree as ET

import xbmc
import xbmcaddon
import xbmcgui
import xbmcvfs

# This add-on's own id (used for self-uninstall and to skip itself).
MY_ID = "script.tony7bones.video"

# The picker. (label, addon_id). Order is load-bearing — the test pins it and
# the preselect indexes below refer to these positions.
APPS = [
    ("POV", "plugin.video.pov"),
    ("The Loop", "plugin.video.the-loop"),
    ("Sports HD", "plugin.video.sporthdme"),
    ("Umbrella", "plugin.video.umbrella"),
]

# Indexes of APPS that start checked. POV, The Loop, Sports HD on; Umbrella off.
PRESELECT = [0, 1, 2]

# Per-app dependency exclusions: required imports we deliberately do NOT install,
# keyed by the app that pulls them. The Loop declares plugin.video.dailymotion_com
# as a REQUIRED import, but nobody here uses Dailymotion and it cannot be cleanly
# uninstalled while The Loop marks it required (Kodi shows it as a needed dep and
# refuses removal). We (a) drop it from the install closure so it is never put on
# the box, and (b) patch The Loop's extracted addon.xml to mark that one import
# optional="true" (see _patch_optional_imports) so Kodi treats it as on-demand —
# The Loop then enables and browses with Dailymotion absent and no "required"
# lock. Verified on Kodi 21 Omega: with the import optional and the add-on
# missing, The Loop is enabled, not broken, and browses normally.
#
# Scope guard: this map ONLY ever affects the listed app's own addon.xml. POV,
# Sports HD and Umbrella are untouched, and only the dailymotion import line in
# plugin.video.the-loop is rewritten — every other import is left exactly as is.
#
# Durability (honest): the patch lives in The Loop's INSTALLED addon.xml. When
# The Loop auto-updates from repository.loop, Kodi extracts the new zip over the
# add-on dir, overwriting our patch with the upstream manifest (Dailymotion
# required again) and — because Dailymotion is available from the official Kodi
# repo — re-pulls and re-locks it. This setup is re-runnable, so re-running it
# restores the clean state. It is NOT a permanent removal; it is a clean install
# that the next Loop *version* update will undo until this is run again.
EXCLUDE_FOR_APP = {
    "plugin.video.the-loop": {"plugin.video.dailymotion_com"},
}

# Flat set of every excluded id (any value above), for the closure walk.
_EXCLUDED_IDS = {dep for deps in EXCLUDE_FOR_APP.values() for dep in deps}

# The official Kodi repo index. Included LAST as a source for shared modules so a
# script.module.* dep resolves to the Kodi-matched build when a third-party repo
# does not carry it. Loaded with this machine's platform tag so any binary deps
# pick the correct native build.
OFFICIAL_BASE = "https://mirrors.kodi.tv/addons/omega"

# Dependency ids provided by the Kodi runtime itself — never downloaded.
_SYSTEM_PREFIXES = ("xbmc.", "kodi.")

# This box's running Kodi major version, used to honour <dir> min/maxversion
# gates so we read the right (Omega) index for repos that ship several.
_KODI_MAJOR = 21


def _log(msg, level=xbmc.LOGINFO):
    xbmc.log(f"[{MY_ID}] {msg}", level)


def _is_installed(addon_id):
    try:
        xbmcaddon.Addon(addon_id)
        return True
    except RuntimeError:
        return False


def _platform_tag():
    """Kodi's platform/arch tag for binary add-ons, e.g. 'osx-arm64'.

    Detected at runtime so the correct native build is picked on any machine.
    Returns None on platforms whose binaries are not served from the mirror
    (e.g. desktop Linux, where binaries come from the OS package manager).
    """
    name = os.name
    try:
        sysname = os.uname().sysname.lower()
        machine = os.uname().machine.lower()
    except AttributeError:  # Windows has no os.uname()
        sysname = ""
        import platform as _platform

        machine = _platform.machine().lower()

    if sysname == "darwin":
        arch = "arm64" if machine in ("arm64", "aarch64") else "x86_64"
        return f"osx-{arch}"
    if name == "nt" or sysname.startswith("win"):
        return "windows-x86_64" if machine in ("amd64", "x86_64") else "windows-i686"
    if "android" in sysname or os.environ.get("ANDROID_ROOT"):
        return "android-aarch64" if machine in ("aarch64", "arm64") else "android-armv7"
    return None


def _http_get(url, timeout=30):
    """Fetch bytes, transparently gunzipping a .gz index."""
    req = urllib.request.Request(url, headers={"User-Agent": "Kodi"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = r.read()
    if url.endswith(".gz"):
        data = gzip.decompress(data)
    return data


def _version_ok(attr, *, is_min):
    """True when this Kodi major satisfies a <dir> min/maxversion attribute.

    Attributes look like '20.90.0' / '21.0.0'. We compare on the major number
    only — enough to pick the Omega dir over Nexus/Matrix dirs in repos that
    ship one <dir> per Kodi release. A missing/garbage attr never gates.
    """
    if not attr:
        return True
    try:
        major = int(str(attr).split(".", 1)[0])
    except (ValueError, TypeError):
        return True
    return _KODI_MAJOR >= major if is_min else _KODI_MAJOR <= major


def _repo_dirs():
    """Discover (repo_id, info_url, datadir_url) triples from every installed repo.

    Reads each special://home/addons/repository.*/addon.xml, walks its
    xbmc.addon.repository extension's <dir> blocks (or the legacy flat form
    where <info>/<datadir> sit directly under the extension), and keeps only the
    dirs whose min/maxversion gate matches this Kodi major — so Omega repos with
    several per-release dirs contribute their Omega index, not an older one.
    Our own host proxy (127.0.0.1) is skipped: it is not a content source here.

    repo_id is the owning repository.* add-on id; it is carried through the index
    so every installed add-on can be stamped with a real `origin` (the source
    repo). An empty origin is what breaks the video apps: The Loop refuses to
    open ("installed from unknown source") and POV's language strings fail to
    load (setLabel errors -> empty menu). See run() for the origin stamping.
    """
    addons_root = xbmcvfs.translatePath("special://home/addons/")
    triples = []
    try:
        names = sorted(os.listdir(addons_root))
    except OSError as e:
        _log(f"cannot list addons dir: {e}", xbmc.LOGERROR)
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
            _log(f"bad addon.xml in {name}: {e}", xbmc.LOGERROR)
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


def _parse_index(xml_bytes, base, platform_tag=None, origin=""):
    """Parse one addons.xml into {id: (version, [dep_ids], zip_url, origin)}.

    A binary add-on declares an explicit <path> per platform; we keep only the
    entry matching this machine and download from that path. Otherwise the
    conventional '<base>/<id>/<id>-<ver>.zip' url is built. `origin` is the
    owning repository.* id, carried so installed add-ons can be stamped with a
    real source repo (an empty origin breaks The Loop and POV — see run()).
    """
    out = {}
    root = ET.fromstring(xml_bytes)
    for a in root.findall("addon"):
        aid = a.get("id")
        if not aid:
            continue
        # Skip imports flagged optional="true": Kodi's own installer treats
        # those as on-demand (fetched only when actually needed at runtime),
        # so resolving them into the install closure over-installs add-ons
        # nothing actually requires (e.g. plugin.googledrive pulled via
        # resolveurl). Match Kodi's behaviour and keep only required imports.
        deps = [
            imp.get("addon")
            for imp in a.findall("requires/import")
            if (imp.get("optional") or "").lower() != "true" and imp.get("addon")
        ]
        meta = a.find("extension[@point='xbmc.addon.metadata']")
        path = plat = None
        if meta is not None:
            p = meta.find("path")
            path = p.text if p is not None else None
            pl = meta.find("platform")
            plat = pl.text if pl is not None else None
        # An arch-specific entry tags an arch like "osx-arm64"; "all" (or any
        # tag without a "-") is universal. Keep only this machine's arch entry.
        is_arch = bool(plat) and "-" in plat
        if is_arch and platform_tag and plat != platform_tag:
            continue
        ver = a.get("version")
        rel = path.strip() if path else f"{aid}/{aid}-{ver}.zip"
        out[aid] = (ver, deps, f"{base}/{rel}", origin)
    return out


def _load_repo_index(info_url, base, platform_tag=None, origin=""):
    """Fetch+parse a single repo dir's index. Tries the declared info url, then
    its .gz / plain sibling, so a repo that lists addons.xml works even if only
    addons.xml.gz exists (and vice versa)."""
    candidates = [info_url]
    if info_url.endswith(".gz"):
        candidates.append(info_url[:-3])
    else:
        candidates.append(info_url + ".gz")
    last = None
    for url in candidates:
        try:
            return _parse_index(_http_get(url), base, platform_tag, origin)
        except Exception as e:  # noqa: BLE001 - try the next variant / repo
            last = e
    _log(f"index load failed {info_url}: {last}", xbmc.LOGERROR)
    return {}


def _ver_key(version):
    """A sortable key for a Kodi version string like '5.1.200' or '5.0.09'.

    Splits on dots and compares numeric parts numerically (so 5.1.200 > 5.0.38
    and 5.1.61 > 5.1.9), falling back to a string compare for any non-numeric
    part. Used to pick the NEWEST build of an add-on when several repos publish
    it — the old build (e.g. resolveurl 5.0.09) is then never chosen over the
    Kodi-compatible one (5.1.200).
    """
    key = []
    for part in str(version or "0").split("."):
        if part.isdigit():
            key.append((1, int(part), ""))
        else:
            key.append((0, 0, part))
    return key


def _merge_index(combined, idx, *, prefer):
    """Merge one repo's index into `combined`, keeping the best entry per id.

    `prefer=True` (the official Kodi repo) always wins for an id it carries, so
    shared script.module.* resolve to the Kodi-matched build. Otherwise the
    HIGHEST version wins — across all third-party repos — so an old duplicate
    (e.g. resolveurl 5.0.09 in one repo) never shadows the current build
    (5.1.200 in another). Each value is
    (version, [deps], zip_url, origin, prefer_flag).
    """
    for aid, (ver, deps, url, origin) in idx.items():
        existing = combined.get(aid)
        if existing is None:
            combined[aid] = (ver, deps, url, origin, prefer)
            continue
        _ever, _ed, _eu, _eo, eprefer = existing
        if eprefer and not prefer:
            continue  # official already won this id
        if prefer and not eprefer:
            combined[aid] = (ver, deps, url, origin, prefer)
            continue
        # same tier (both official, or both third-party): newest version wins
        if _ver_key(ver) > _ver_key(_ever):
            combined[aid] = (ver, deps, url, origin, prefer)


def _build_index(platform_tag=None):
    """Build a single combined index across every installed repo + the official
    Kodi repo, choosing the best entry per id (see _merge_index).

    Returns {id: (version, [dep_ids], zip_url, origin)}. The official repo is
    merged with prefer=True so its modules win (Kodi-matched versions); among
    the third-party repos the highest version of any duplicated id wins. origin
    is the providing repository.* id (official repo -> 'repository.xbmc.org').
    """
    combined = {}
    for repo_id, info_url, base in _repo_dirs():
        idx = _load_repo_index(info_url, base, platform_tag, repo_id)
        if idx:
            _merge_index(combined, idx, prefer=False)
    official = _load_repo_index(
        f"{OFFICIAL_BASE}/addons.xml.gz",
        OFFICIAL_BASE,
        platform_tag,
        "repository.xbmc.org",
    )
    if official:
        _merge_index(combined, official, prefer=True)
    # Drop the prefer flag: {id: (version, deps, url, origin)}.
    return {aid: (v, d, u, o) for aid, (v, d, u, o, _p) in combined.items()}


def _resolve_closure(targets, index):
    """Walk the dependency graph of `targets` against the combined `index`.

    Returns an ordered list of (addon_id, zip_url, origin) with dependencies
    BEFORE the add-ons that need them, so extraction order is safe. System
    imports (xbmc.* / kodi.*) are skipped. An add-on already installed on the
    box is treated as satisfied (its subtree is not re-resolved). Ids in
    _EXCLUDED_IDS (e.g. plugin.video.dailymotion_com, the unwanted required dep
    of The Loop) are never resolved or installed — The Loop's manifest is patched
    to mark that import optional so it enables without them (see EXCLUDE_FOR_APP
    and _patch_optional_imports). Also returns the set of ids that could not be
    resolved from any installed repo.
    """
    resolved = {}  # id -> (zip_url, origin)
    order = []
    missing = set()

    def visit(aid):
        if (
            aid in resolved
            or aid in _EXCLUDED_IDS
            or aid.startswith(_SYSTEM_PREFIXES)
            or _is_installed(aid)
        ):
            return
        entry = index.get(aid)
        if entry is None:
            missing.add(aid)
            _log(f"cannot resolve dependency: {aid}", xbmc.LOGERROR)
            return
        _ver, deps, url, origin = entry
        resolved[aid] = (url, origin)
        for dep in deps:  # deps first
            visit(dep)
        order.append(aid)

    for t in targets:
        visit(t)
    return [(aid, resolved[aid][0], resolved[aid][1]) for aid in order], missing


def _extract_zip(url, dialog, pct):
    """Download a zip and extract it into addons/. Returns True on success."""
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
        _log(f"failed {name}: {e}", xbmc.LOGERROR)
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)
    return ok


def _enable(addon_id):
    """Register + enable an add-on. SetAddonEnabled adds it to Kodi's installed
    table, which makes a directly-extracted add-on actually runnable. Works
    without the unknown-sources setting (that only gates the install-from-zip
    GUI, not this direct-extract + enable path)."""
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


def _set_origins(origins):
    """Stamp each installed add-on's `origin` to its source repository id.

    `origins` is {addon_id: repository_id}. An empty origin is what breaks the
    video apps: The Loop opens a blocking "installed from unknown source" dialog
    on every launch (so its directory never returns), and POV's language strings
    fail to load (getLocalizedString -> '' -> setLabel raises -> empty menu).
    Kodi's own repository installer sets this column; the direct-extract path
    does not, so we set it ourselves — exactly the value Kodi would have written
    (the providing repo). Writing the live Addons DB is how build wizards do it;
    we touch only the `origin` column of rows we just installed, and the change
    takes effect on the next Kodi start (run() restarts at the end).

    Never raises: a failure here must not abort the run (the apps are at least
    installed; the user can re-run if origins did not take).
    """
    db = _addons_db_path()
    if not db:
        _log("could not locate Addons DB; origins not set", xbmc.LOGERROR)
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
        _log(f"stamped origin on {len(origins)} add-on(s)", xbmc.LOGINFO)
    except Exception as e:  # noqa: BLE001 - origin stamping must not abort the run
        _log(f"set_origins failed (non-fatal): {e}", xbmc.LOGERROR)


def _patch_optional_imports(app_id, exclude_ids):
    """Rewrite an installed app's addon.xml to mark each import in `exclude_ids`
    optional="true", so Kodi no longer treats it as a required dependency.

    The Loop declares plugin.video.dailymotion_com as a REQUIRED import. We do
    not install it (see EXCLUDE_FOR_APP / _resolve_closure), and Kodi 21 Omega
    will still enable The Loop with it absent — but it stays listed as a required
    dependency, which blocks a clean uninstall and re-pulls it on update. Marking
    that single import optional="true" makes Kodi treat it as on-demand: The Loop
    enables and browses with Dailymotion absent and no "required" lock.

    Surgical by design: we edit ONLY `app_id`'s own addon.xml, and within it only
    the <import addon="..."> lines whose addon is in `exclude_ids` and that are
    not already optional — every other import (resolveurl, looptv, jetextractors,
    the real optional ones, etc.) is left byte-for-byte untouched. Done with a
    line-anchored regex rather than an XML round-trip so we cannot accidentally
    reformat or drop anything else in the file. Never raises: a failed patch must
    not abort the run (The Loop still enables; the user can re-run).

    NOTE (durability): this patches the INSTALLED manifest. The Loop's next
    *version* update overwrites the whole add-on dir (manifest included) with the
    upstream one, restoring the required Dailymotion import; re-run this setup to
    reapply. See EXCLUDE_FOR_APP for the full tradeoff.
    """
    if not exclude_ids:
        return
    try:
        import re  # noqa: PLC0415 - only needed here

        axml = xbmcvfs.translatePath("special://home/addons/" + app_id + "/addon.xml")
        if not os.path.isfile(axml):
            return
        with open(axml, encoding="utf-8") as f:
            text = f.read()
        changed = False
        for dep in exclude_ids:
            # Match this dep's <import ...> tag only; skip it if already optional.
            pattern = re.compile(
                r'<import\s+addon="' + re.escape(dep) + r'"((?:(?!/?>).)*?)\s*/?>'
            )

            def _sub(m, _dep=dep):
                nonlocal changed
                attrs = m.group(1)
                if "optional" in attrs:
                    return m.group(0)  # already optional — leave untouched
                changed = True
                return f'<import addon="{_dep}"{attrs} optional="true" />'

            text = pattern.sub(_sub, text)
        if changed:
            with open(axml, "w", encoding="utf-8") as f:
                f.write(text)
            _log(
                f"patched {app_id}: marked {sorted(exclude_ids)} optional",
                xbmc.LOGINFO,
            )
    except Exception as e:  # noqa: BLE001 - patch must not abort the run
        _log(f"patch_optional_imports failed (non-fatal): {e}", xbmc.LOGERROR)


def _install_closure(closure, dialog):
    """Extract every zip in `closure` (deps first), patch any app whose unwanted
    required deps we excluded, rescan, enable each, then stamp every add-on's
    origin with its source repo.

    `closure` is a list of (addon_id, zip_url, origin). Returns the count of
    closure ids that report installed afterwards.
    """
    for aid, url, _origin in closure:
        if _is_installed(aid):
            continue
        _extract_zip(url, dialog, 100)
    # For every app that pulls an excluded required dep (e.g. The Loop ->
    # Dailymotion), mark that import optional in the freshly extracted addon.xml
    # BEFORE the rescan, so Kodi reads the patched manifest and enables the app
    # without treating the absent dep as required.
    closure_ids = {aid for aid, _u, _o in closure}
    for app_id, exclude_ids in EXCLUDE_FOR_APP.items():
        if app_id in closure_ids:
            _patch_optional_imports(app_id, exclude_ids)
    # Rescan so Kodi sees the freshly extracted dirs, then enable the closure
    # dependencies-first so each app's imports are satisfied when enabled.
    xbmc.executebuiltin("UpdateLocalAddons()")
    xbmc.sleep(2000)
    for aid, _url, _origin in closure:
        _enable(aid)
    # Stamp origins so the apps are not treated as "unknown source" orphans.
    _set_origins({aid: origin for aid, _url, origin in closure})
    return sum(1 for aid, _url, _origin in closure if _is_installed(aid))


def _self_uninstall():
    """Remove this add-on itself so it leaves no permanent home tile.

    Kodi 21 Omega has no uninstall path a script can call (no UninstallAddon
    builtin, no JSON-RPC uninstall method), so the supported mechanism is:
    delete our own add-on directory; Kodi's next add-on scan drops the stale DB
    rows. Defensive by design: runs only after a successful run, never raises,
    and deletes ONLY this add-on's own directory.
    """
    try:
        my_dir = xbmcvfs.translatePath("special://home/addons/" + MY_ID)
        # Hard guard: only ever delete OUR OWN add-on directory.
        if os.path.basename(os.path.normpath(my_dir)) != MY_ID:
            _log(f"self-uninstall: refusing unexpected path {my_dir}", xbmc.LOGERROR)
            return
        if os.path.isdir(my_dir):
            import shutil

            shutil.rmtree(my_dir, ignore_errors=True)
            _log(f"self-uninstall: removed {my_dir}", xbmc.LOGINFO)
    except Exception as e:  # noqa: BLE001 - self-uninstall must never abort the run
        _log(f"self-uninstall failed (non-fatal): {e}", xbmc.LOGERROR)


def _have_source_repos():
    """True when at least one content repository (other than our own proxy) is
    installed, i.e. the main Tony.7.Bones Setup has been run."""
    return len(_repo_dirs()) > 0


def _enable_source_repos():
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
            _enable(repo_id)
        except Exception:  # noqa: BLE001 - one bad repo must not abort the run
            continue


def _restart_kodi():
    """Restart Kodi so freshly installed add-ons (and the origins just stamped)
    are fully loaded before first use.

    POV builds its menu from localized strings on first run; if it is invoked
    before Kodi has registered its language resource, getLocalizedString returns
    '' and setLabel raises (empty menu). The Loop reads its origin at startup; a
    blank origin shows a blocking "unknown source" dialog. A restart guarantees
    both the language resources and the stamped origins are live. Platform-aware
    and prompt-driven so it never freezes (matches the main Setup's behaviour).
    """
    if _is_android():
        if xbmcgui.Dialog().yesno(
            "Video Add-ons Setup",
            "Setup is complete. Kodi must fully close and reopen to finish.\n\n"
            "Close Kodi now? After it closes, open it again to finish setup.",
            yeslabel="Close now",
            nolabel="Later",
        ):
            xbmc.executebuiltin("Quit()")
        return
    if xbmcgui.Dialog().yesno(
        "Video Add-ons Setup",
        "Setup is complete. Kodi needs to restart to finish.\n\nRestart now?",
    ):
        xbmc.executebuiltin("RestartApp()")


def _is_android():
    """True on Android (incl. Fire Stick), where the app cannot relaunch itself."""
    if os.environ.get("ANDROID_ROOT") or os.environ.get("ANDROID_DATA"):
        return True
    try:
        return "android" in os.uname().sysname.lower()
    except AttributeError:  # Windows
        return False


def run():
    # Bail early with a clear message if the box has no source repos yet.
    if not _have_source_repos():
        xbmcgui.Dialog().ok(
            "Video Add-ons Setup",
            "No source repositories are installed yet.\n\n"
            "Run the main Tony.7.Bones Setup first, then run this again.",
        )
        return

    labels = [label for label, _aid in APPS]
    choices = xbmcgui.Dialog().multiselect(
        "Video Add-ons Setup", labels, preselect=PRESELECT
    )
    # Cancelled (None) or nothing selected: make no changes and DO NOT
    # self-uninstall, so the user can re-run the picker later.
    if not choices:
        _log("picker cancelled or empty — no changes")
        return

    selected = [APPS[i][1] for i in choices]

    dialog = xbmcgui.DialogProgress()
    dialog.create("Video Add-ons Setup", "Resolving add-ons...")

    # Enable the source repos so the origins we stamp reference repos Kodi knows
    # about (a blank origin is what breaks The Loop and POV — see _set_origins).
    _enable_source_repos()

    plat = _platform_tag()
    indexes = _build_index(plat)
    if not indexes:
        dialog.close()
        xbmcgui.Dialog().ok(
            "Video Add-ons Setup",
            "Could not read any repository index.\n\n"
            "Check the network connection and try again.",
        )
        return

    closure, missing = _resolve_closure(selected, indexes)
    # Unresolvable APP targets (not just deps) are the real problem.
    unresolved_apps = [aid for aid in selected if aid in missing]

    installed_ok = 0
    if closure:
        dialog.update(10, "Installing add-ons and dependencies...")
        _install_closure(closure, dialog)
    for aid in selected:
        if _is_installed(aid):
            installed_ok += 1

    dialog.close()

    msg = f"Installed {installed_ok}/{len(selected)} selected add-on(s)."
    if unresolved_apps:
        msg += "\n\nNot found in your repos: " + ", ".join(unresolved_apps)
    msg += "\n\nKodi will restart to finish setup."
    xbmcgui.Dialog().ok("Video Add-ons Setup", msg)

    # Self-remove only after an actual install run completed (at least one app
    # selected and the flow reached here). It never raises and deletes only our
    # own dir.
    _self_uninstall()

    # Restart so the freshly installed apps load their language resources and
    # the stamped origins take effect on first launch (POV's menu and The Loop's
    # origin check both need a clean start — see _restart_kodi). Only reached
    # after an actual install; prompt-driven so it never freezes.
    if installed_ok:
        _restart_kodi()


if __name__ == "__main__":
    run()
