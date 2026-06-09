#!/usr/bin/env python3
"""Build the Kodi repo from two pristine source trees into the Pages-served root.

Two source trees, two jobs:

  dropbox/   the human canvas (pristine, committed; NEVER holds generated files).
             Mirrored verbatim to the repo ROOT (repositories/, media/, iptv/,
             rss/, ...), with a Kodi-parseable index.html generated into every
             folder plus a root index.html that lists the canvas 1:1. This is
             exactly what the bare URL https://tony7bones.github.io/ serves — the
             Kodi File Manager source.

  addons/    first-party add-on source + the hosted/ third-party mirror trees
             (committed). Each dir with an addon.xml is built into a reproducible
             zip and listed in addons/addons.xml (+ .sha256/.md5). The virtual
             proxy fetches these from main via raw.githubusercontent; they are
             NOT listed at the bare URL.

The root install zip (repository.tony7bones-X.Y.Z.zip) is owned by deploy.py and
stays served at the repo root for the proxy self-update, but is NOT listed on the
bare-URL root page (the root index is the owner's canvas, 1:1). The generator
injects a copy into the served repositories/ so the installer is browsable there.

The mirror honors .gitignore: a secret-bearing source file (e.g. IPTV instance
settings) is kept locally but never copied into the served tree.

Run from anywhere:
    python3 _tools/generate_repo.py
"""

import hashlib
import os
import shutil
import subprocess
import zipfile
from xml.etree import ElementTree as ET

ROOT_DIR = os.path.normpath(
    os.path.join(os.path.abspath(os.path.dirname(__file__)), "..")
)
DROPBOX_DIR = os.path.join(ROOT_DIR, "dropbox")
ADDONS_DIR = os.path.join(ROOT_DIR, "addons")

MEDIA_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg"}

# Inside addons/: hosted/ holds the third-party mirror trees the proxy fetches
# verbatim — never built as an add-on, never indexed (it is not browsed at the
# bare URL and indexing would churn an index.html into every hosted subdir).
_ADDONS_SPECIAL = {"hosted"}

# Tooling/cache dirs that must NEVER be zipped, indexed, or mirrored. They are
# build-time cruft (lint/test/type caches, bytecode) and leak non-deterministic
# bytes into add-on zips if a tool happened to run in a source dir before a build.
_CRUFT_DIRS = {"__pycache__", ".ruff_cache", ".pytest_cache", ".mypy_cache"}

# Repo-root entries that are NOT canvas and must never be served-listed or pruned
# by the canvas mirror. Everything else at the root that is a directory is treated
# as canvas output (a mirror of a dropbox/ folder) and pruned if dropbox/ drops it.
_ROOT_PROTECTED = {
    "dropbox",
    "addons",
    "_tools",
    "docs",
    "images",
    "node_modules",
    ".git",
    ".github",
    ".githooks",
    ".claude",
    ".ruff_cache",
    ".pytest_cache",
}
# Root files that belong to the site/install, not the canvas listing.
_ROOT_NONCANVAS_FILES = {"index.html", "style.css"}


def _fmt_size(n: int) -> str:
    for unit in ("B", "K", "M", "G"):
        if n < 1024:
            return f"{n}{unit}"
        n //= 1024
    return f"{n}G"


def _git_ignored(path: str) -> bool:
    """True if `path` is git-ignored, so it is kept locally but never published.

    Lets a secret-bearing file (e.g. IPTV settings) live in the canvas for local
    use without being copied into the served tree or appearing in any listing.
    Outside a git repo (tests) this returns False, so behaviour is unchanged.
    """
    try:
        return (
            subprocess.run(
                ["git", "check-ignore", "-q", path],
                cwd=os.path.dirname(path) or ".",
                capture_output=True,
            ).returncode
            == 0
        )
    except OSError:
        return False


def _make_index(directory: str, title: str, rows: list[str]) -> None:
    """Write an Apache-style directory listing Kodi can parse (HTML 3.2)."""
    html = (
        '<!DOCTYPE HTML PUBLIC "-//W3C//DTD HTML 3.2 Final//EN">\n'
        f"<html>\n<head><title>{title}</title></head>\n"
        f"<body>\n<h1>{title}</h1>\n<pre>\n"
        + "\n".join(rows)
        + "\n</pre>\n</body>\n</html>\n"
    )
    with open(os.path.join(directory, "index.html"), "w", encoding="utf-8") as fh:
        fh.write(html)


def _zip_addon(addon_dir: str) -> tuple[ET.Element, str, str] | None:
    """Build a reproducible zip for one add-on dir. Returns (root, id, zip_name).

    Members are collected in a stable path-sorted order and written with fixed
    1980 timestamps / 0644 perms so the zip is byte-for-byte reproducible on every
    machine and CI run (Kodi's version-based auto-upgrade breaks on same-version
    byte churn). __pycache__ and any prior zip / root index.html are excluded.
    The zip is always rebuilt (a copy pipeline rewrites mtimes, so an mtime
    staleness heuristic is meaningless — determinism makes the rebuild a no-op
    diff anyway).
    """
    xml_path = os.path.join(addon_dir, "addon.xml")
    try:
        root = ET.parse(xml_path).getroot()
    except ET.ParseError as exc:
        print(
            f"  ! skipping {os.path.basename(addon_dir)}: malformed addon.xml ({exc})"
        )
        return None
    addon_id, version = root.get("id"), root.get("version")
    if not (addon_id and version):
        print(f"  ! skipping {os.path.basename(addon_dir)}: missing id or version")
        return None

    zip_name = f"{addon_id}-{version}.zip"
    zip_path = os.path.join(addon_dir, zip_name)
    members = []
    for dirpath, dirs, files in os.walk(addon_dir):
        dirs[:] = [d for d in dirs if d not in _CRUFT_DIRS]
        dirs.sort()
        for fname in sorted(files):
            if fname.endswith(".zip") or (
                fname == "index.html" and dirpath == addon_dir
            ):
                continue
            fpath = os.path.join(dirpath, fname)
            arcname = os.path.relpath(fpath, os.path.dirname(addon_dir))
            members.append((fpath, arcname))
    members.sort(key=lambda m: m[1])
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for fpath, arcname in members:
            info = zipfile.ZipInfo(arcname, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            with open(fpath, "rb") as fh:
                zf.writestr(info, fh.read())
    return root, addon_id, zip_name


def process_addons(scan_dir: str) -> list[ET.Element]:
    """Zip every add-on subdir (has addon.xml) under scan_dir + write its index.

    Returns the list of <addon> roots for addons.xml. hosted/ is skipped.
    """
    roots = []
    if not os.path.isdir(scan_dir):
        return roots
    for entry in sorted(os.listdir(scan_dir)):
        addon_dir = os.path.join(scan_dir, entry)
        if entry in _ADDONS_SPECIAL or not os.path.isdir(addon_dir):
            continue
        if not os.path.exists(os.path.join(addon_dir, "addon.xml")):
            continue
        built = _zip_addon(addon_dir)
        if built is None:
            continue
        root, addon_id, zip_name = built
        _make_index(
            addon_dir,
            f"Index of /{os.path.relpath(addon_dir, ROOT_DIR)}/",
            [
                '<a href="../">Parent Directory</a>',
                f'<a href="{zip_name}">{zip_name}</a>  '
                f"{_fmt_size(os.path.getsize(os.path.join(addon_dir, zip_name)))}",
            ],
        )
        roots.append(root)
        print(f"  + {addon_id} {root.get('version')}  ->  {zip_name}")
    return roots


def write_addons_xml(roots: list[ET.Element]) -> tuple[str, str]:
    """Write addons/addons.xml + .sha256 + .md5. Returns (sha256, md5)."""
    addons_el = ET.Element("addons")
    addons_el.extend(roots)
    ET.indent(addons_el, space="    ")
    path = os.path.join(ADDONS_DIR, "addons.xml")
    ET.ElementTree(addons_el).write(path, encoding="UTF-8", xml_declaration=True)
    data = open(path, "rb").read()
    sha256 = hashlib.sha256(data).hexdigest()
    md5 = hashlib.md5(data).hexdigest()
    with open(path + ".sha256", "w") as fh:
        fh.write(sha256)
    with open(path + ".md5", "w") as fh:
        fh.write(md5)
    return sha256, md5


def _index_tree(top: str) -> int:
    """Generate a Kodi index.html into `top` and every subdir, listing real
    entries (dirs + files) by name with sizes, no dates. Git-ignored files are
    omitted (kept locally, never served). Returns the number of indexes written.
    """
    count = 0
    for dirpath, dirnames, filenames in os.walk(top):
        dirnames[:] = sorted(d for d in dirnames if d not in _CRUFT_DIRS)
        rel = os.path.relpath(dirpath, ROOT_DIR)
        rows = ['<a href="../">Parent Directory</a>']
        for d in dirnames:
            rows.append(f'<a href="{d}/">{d}/</a>')
        for f in sorted(filenames):
            if f == "index.html":
                continue
            fpath = os.path.join(dirpath, f)
            if _git_ignored(fpath):
                continue
            rows.append(f'<a href="{f}">{f}</a>  {_fmt_size(os.path.getsize(fpath))}')
        _make_index(dirpath, f"Index of /{rel}/", rows)
        count += 1
    return count


def _copy_canvas_dir(src: str, dst: str) -> None:
    """Mirror one canvas folder src -> dst, replacing dst wholesale (so deletions
    in the source propagate) and skipping git-ignored files (secrets)."""
    if os.path.isdir(dst):
        shutil.rmtree(dst)

    def _ignore(dirname, names):
        skip = set()
        for n in names:
            p = os.path.join(dirname, n)
            if n in _CRUFT_DIRS or (os.path.isfile(p) and _git_ignored(p)):
                skip.add(n)
        return skip

    shutil.copytree(src, dst, ignore=_ignore)


def mirror_canvas() -> list[str]:
    """Mirror dropbox/ -> repo ROOT (1:1) and index every served folder.

    Each top-level dropbox/ folder is copied to ROOT/<folder> (replacing any
    prior copy), loose dropbox/ files are copied to the root, and a Kodi index is
    generated into every served canvas folder. Root dirs that were canvas but are
    no longer in dropbox/ are pruned. Returns the sorted canvas entry names (dirs
    + loose files) for the root listing. No-op if dropbox/ is absent.
    """
    if not os.path.isdir(DROPBOX_DIR):
        return []
    entries = sorted(os.listdir(DROPBOX_DIR))
    canvas_dirs = [e for e in entries if os.path.isdir(os.path.join(DROPBOX_DIR, e))]

    # Prune root dirs that used to be canvas but dropbox/ no longer owns.
    for d in os.listdir(ROOT_DIR):
        p = os.path.join(ROOT_DIR, d)
        if (
            os.path.isdir(p)
            and d not in _ROOT_PROTECTED
            and d not in canvas_dirs
            and not os.path.exists(os.path.join(p, "addon.xml"))
        ):
            shutil.rmtree(p)
            print(f"pruned root/{d} (no longer in dropbox/)")

    listing = []
    for e in entries:
        src = os.path.join(DROPBOX_DIR, e)
        dst = os.path.join(ROOT_DIR, e)
        if os.path.isdir(src):
            _copy_canvas_dir(src, dst)
            _index_tree(dst)
            listing.append(e + "/")
            print(f"dropbox/{e}/ -> /{e}/")
        elif os.path.isfile(src) and not _git_ignored(src):
            shutil.copyfile(src, dst)
            listing.append(e)
    return listing


def _root_install_zip() -> str | None:
    """The repository.tony7bones-*.zip at the repo root (owned by deploy.py)."""
    zips = sorted(
        e
        for e in os.listdir(ROOT_DIR)
        if e.startswith("repository.tony7bones-") and e.endswith(".zip")
    )
    return zips[-1] if zips else None


def write_root_index(canvas_listing: list[str]) -> None:
    """Generate the bare-URL root index.html: the canvas 1:1, nothing else.

    HTML 3.2 so Kodi's File Manager parses it. Lists EXACTLY the canvas entries
    (mirrored from dropbox/) — no addons/, dropbox/, _tools/, docs/, and NOT the
    root install zip. The install zip stays served at the repo root (so the proxy
    self-update keeps working) but is deliberately NOT listed here, so the
    bare-URL view shows only the owner's canvas; the installer is browsed from the
    served repositories/ folder (where _inject_install_zip_into_repositories puts
    a copy).
    """
    rows = [f'<a href="{e}">{e}</a>' for e in canvas_listing]
    _make_index(ROOT_DIR, "Index of /", rows)


def _inject_install_zip_into_repositories() -> None:
    """Copy the root install zip into the served repositories/ so it is browsable
    in the canvas too, pruning any older proxy zip there. dropbox/ stays pristine
    (the built zip is injected only into the served copy)."""
    install_zip = _root_install_zip()
    served_repos = os.path.join(ROOT_DIR, "repositories")
    if not install_zip or not os.path.isdir(served_repos):
        return
    for e in os.listdir(served_repos):
        if e.startswith("repository.tony7bones-") and e.endswith(".zip"):
            os.remove(os.path.join(served_repos, e))
    shutil.copyfile(
        os.path.join(ROOT_DIR, install_zip), os.path.join(served_repos, install_zip)
    )
    # Re-index repositories/ so the injected zip shows in its listing.
    if os.path.isdir(served_repos):
        _index_tree(served_repos)


def generate() -> None:
    # 1. Build the add-on zips + addons.xml (machine tree, proxy-fetched).
    roots = process_addons(ADDONS_DIR)
    sha256, md5 = write_addons_xml(roots)

    # 2. Mirror the canvas to the served root + index every folder.
    canvas_listing = mirror_canvas()

    # 3. Make the proxy installer browsable in the canvas, then the root listing.
    _inject_install_zip_into_repositories()
    write_root_index(canvas_listing)

    print(f"\naddons.xml: {len(roots)} add-on(s)")
    print(f"addons.xml.sha256: {sha256}")
    print(f"addons.xml.md5:    {md5}")


if __name__ == "__main__":
    generate()
