"""addons.xml index loading, parsing, merging, and closure resolution.

This is the dependency-resolution core shared by both Setups. Two index shapes
exist because the two Setups feed the resolver differently:

* The base Setup resolves a fixed app list against an ORDERED list of repo
  indexes (peno64 first, then the official Kodi repo); the first repo that
  declares an id wins, and binary add-ons carry an explicit <path>. It does not
  need per-add-on origins. -> load_index_simple + resolve_closure_ordered.

* The video Setup resolves a user-chosen app list against a SINGLE COMBINED
  index built from every repo installed on the box plus the official repo, where
  the highest version wins (official preferred for shared modules) and each entry
  carries its source-repo origin (for origin stamping). -> parse_index /
  load_repo_index / merge_index / build_index + resolve_closure_combined.

Both resolvers walk <requires>/<import> recursively, drop optional imports
(matching Kodi's on-demand behaviour — no Google Drive pulled via resolveurl),
skip xbmc.*/kodi.* system imports, and order dependencies BEFORE their dependents
so extraction is safe.
"""

from xml.etree import ElementTree as ET

import xbmc

from . import net

# Dependency ids provided by the Kodi runtime itself — never downloaded.
SYSTEM_PREFIXES = ("xbmc.", "kodi.")


def _required_dep_ids(addon_el):
    """The ids of an <addon>'s REQUIRED imports (optional='true' dropped).

    Kodi's own installer treats optional imports as on-demand (fetched only when
    actually needed at runtime); resolving them into the install closure would
    over-install add-ons nothing requires (e.g. plugin.googledrive pulled via
    resolveurl). Matching Kodi, we keep only required imports.
    """
    return [
        imp.get("addon")
        for imp in addon_el.findall("requires/import")
        if (imp.get("optional") or "").lower() != "true" and imp.get("addon")
    ]


def _path_and_platform(addon_el):
    """Return (declared <path> or None, declared <platform> or None)."""
    meta = addon_el.find("extension[@point='xbmc.addon.metadata']")
    if meta is None:
        return None, None
    p = meta.find("path")
    pl = meta.find("platform")
    return (
        p.text if p is not None else None,
        pl.text if pl is not None else None,
    )


def _platform_match(plat, platform_tag):
    """False only when this is an arch-specific entry for a DIFFERENT arch.

    A real per-arch entry tags an arch like "osx-arm64"; "all" (or any tag
    without a "-") is universal and always kept. Of the arch-specific duplicates,
    keep only this machine's.
    """
    is_arch = bool(plat) and "-" in plat
    return not (is_arch and platform_tag and plat != platform_tag)


# --------------------------------------------------------------------------- #
# Simple (base-Setup) index + ordered-indexes resolver
# --------------------------------------------------------------------------- #
def load_index_simple(base, platform_tag=None):
    """Return {id: (version, [dep_ids], path_or_None)} from a repo's addons.xml(.gz).

    `path` is the add-on's relative download path when the manifest declares one
    (binary add-ons do: e.g. 'pvr.iptvsimple+osx-arm64/pvr.iptvsimple-X.zip'),
    otherwise None and the caller builds the conventional '<id>/<id>-<ver>.zip'
    path. Binary add-ons appear once per platform; when `platform_tag` is given we
    keep only the entry whose <platform> matches this machine.
    """
    err = None
    for name in ("addons.xml.gz", "addons.xml"):
        try:
            root = ET.fromstring(net.http_get(f"{base}/{name}"))
            out = {}
            for a in root.findall("addon"):
                aid = a.get("id")
                deps = _required_dep_ids(a)
                path, plat = _path_and_platform(a)
                if not _platform_match(plat, platform_tag):
                    continue
                out[aid] = (a.get("version"), deps, path)
            return out
        except Exception as e:  # noqa: BLE001 - try the next index variant
            err = e
    xbmc.log(f"[tony7bones] index load failed {base}: {err}", xbmc.LOGERROR)
    return {}


def resolve_closure_ordered(targets, indexes):
    """Walk the dependency graph of `targets` across an ORDERED list of indexes.

    `indexes` is an ordered list of (base_url, index_dict) where index_dict is the
    shape returned by load_index_simple; the first repo that declares an id wins.
    Returns an ordered list of (addon_id, zip_url) with dependencies BEFORE the
    add-ons that need them. System imports (xbmc.*/kodi.*) are skipped. An entry
    whose manifest carries an explicit <path> (binary add-ons) is downloaded from
    that path; otherwise the conventional '<id>/<id>-<ver>.zip' is used.
    """
    resolved = {}  # id -> zip_url
    order = []

    def visit(aid):
        if aid in resolved or aid.startswith(SYSTEM_PREFIXES):
            return
        for base, idx in indexes:
            if aid in idx:
                ver, deps, path = idx[aid]
                rel = path if path else f"{aid}/{aid}-{ver}.zip"
                resolved[aid] = f"{base}/{rel}"
                for dep in deps:  # deps first
                    visit(dep)
                order.append(aid)
                return
        xbmc.log(f"[tony7bones] cannot resolve dependency: {aid}", xbmc.LOGERROR)

    for t in targets:
        visit(t)
    return [(aid, resolved[aid]) for aid in order]


# --------------------------------------------------------------------------- #
# Combined (video-Setup) index + installed-aware resolver with origins
# --------------------------------------------------------------------------- #
def parse_index(xml_bytes, base, platform_tag=None, origin=""):
    """Parse one addons.xml into {id: (version, [dep_ids], zip_url, origin)}.

    A binary add-on declares an explicit <path> per platform; we keep only the
    entry matching this machine and download from that path. Otherwise the
    conventional '<base>/<id>/<id>-<ver>.zip' url is built. `origin` is the owning
    repository.* id, carried so installed add-ons can be stamped with a real
    source repo (an empty origin breaks The Loop and POV).
    """
    out = {}
    root = ET.fromstring(xml_bytes)
    for a in root.findall("addon"):
        aid = a.get("id")
        if not aid:
            continue
        deps = _required_dep_ids(a)
        path, plat = _path_and_platform(a)
        if not _platform_match(plat, platform_tag):
            continue
        ver = a.get("version")
        rel = path.strip() if path else f"{aid}/{aid}-{ver}.zip"
        out[aid] = (ver, deps, f"{base}/{rel}", origin)
    return out


def load_repo_index(info_url, base, platform_tag=None, origin=""):
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
            return parse_index(net.http_get(url), base, platform_tag, origin)
        except Exception as e:  # noqa: BLE001 - try the next variant / repo
            last = e
    xbmc.log(f"[tony7bones] index load failed {info_url}: {last}", xbmc.LOGERROR)
    return {}


def ver_key(version):
    """A sortable key for a Kodi version string like '5.1.200' or '5.0.09'.

    Splits on dots and compares numeric parts numerically (so 5.1.200 > 5.0.38 and
    5.1.61 > 5.1.9), falling back to a string compare for any non-numeric part.
    Used to pick the NEWEST build of an add-on when several repos publish it.
    """
    key = []
    for part in str(version or "0").split("."):
        if part.isdigit():
            key.append((1, int(part), ""))
        else:
            key.append((0, 0, part))
    return key


def merge_index(combined, idx, *, prefer):
    """Merge one repo's index into `combined`, keeping the best entry per id.

    `prefer=True` (the official Kodi repo) always wins for an id it carries, so
    shared script.module.* resolve to the Kodi-matched build. Otherwise the
    HIGHEST version wins — across all third-party repos — so an old duplicate
    never shadows the current build. Each value is
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
        if ver_key(ver) > ver_key(_ever):
            combined[aid] = (ver, deps, url, origin, prefer)


def build_index(repo_triples, official_base, platform_tag=None):
    """Build a single combined index across installed repos + the official repo.

    `repo_triples` is the (repo_id, info_url, datadir) list from repos.repo_dirs().
    Returns {id: (version, [dep_ids], zip_url, origin)}. The official repo is
    merged with prefer=True so its modules win (Kodi-matched versions); among the
    third-party repos the highest version of any duplicated id wins. origin is the
    providing repository.* id (official repo -> 'repository.xbmc.org').
    """
    combined = {}
    for repo_id, info_url, base in repo_triples:
        idx = load_repo_index(info_url, base, platform_tag, repo_id)
        if idx:
            merge_index(combined, idx, prefer=False)
    official = load_repo_index(
        f"{official_base}/addons.xml.gz",
        official_base,
        platform_tag,
        "repository.xbmc.org",
    )
    if official:
        merge_index(combined, official, prefer=True)
    # Drop the prefer flag: {id: (version, deps, url, origin)}.
    return {aid: (v, d, u, o) for aid, (v, d, u, o, _p) in combined.items()}


def resolve_closure_combined(targets, index):
    """Walk the dependency graph of `targets` against the combined `index`.

    Returns (ordered closure, missing) where the closure is a list of
    (addon_id, zip_url, origin) with dependencies BEFORE their dependents, and
    `missing` is the set of ids that could not be resolved from any repo. System
    imports (xbmc.*/kodi.*) are skipped. An add-on already installed on the box is
    treated as satisfied (its subtree is not re-resolved). Optional imports never
    enter the closure (dropped at parse time).

    Note: required imports we do not want to RUN (e.g. plugin.video.dailymotion_com
    for The Loop) are still installed here so the requiring add-on's dependency
    check is satisfied — they are disabled after install instead of excluded.
    """
    resolved = {}  # id -> (zip_url, origin)
    order = []
    missing = set()

    def visit(aid):
        if aid in resolved or aid.startswith(SYSTEM_PREFIXES) or net.is_installed(aid):
            return
        entry = index.get(aid)
        if entry is None:
            missing.add(aid)
            xbmc.log(f"[tony7bones] cannot resolve dependency: {aid}", xbmc.LOGERROR)
            return
        _ver, deps, url, origin = entry
        resolved[aid] = (url, origin)
        for dep in deps:  # deps first
            visit(dep)
        order.append(aid)

    for t in targets:
        visit(t)
    return [(aid, resolved[aid][0], resolved[aid][1]) for aid in order], missing
