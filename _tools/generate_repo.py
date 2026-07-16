#!/usr/bin/env python3
"""Build the committed add-on artifacts + the canvas-mirror library for CI.

Two source trees, two jobs:

  addons/    first-party add-on source + the hosted/ third-party mirror trees
             (committed). Each dir with an addon.xml is built into a reproducible
             zip and listed in addons/addons.xml (+ .sha256/.md5). Running this
             tool regenerates those COMMITTED artifacts in place; superseded
             per-add-on zips are pruned so old versions never accumulate.

  dropbox/   the human canvas (pristine, committed; NEVER holds generated files).
             It is NOT mirrored into the repo anymore: build_site.py calls the
             mirror functions below (mirror_canvas, write_root_index,
             write_robots) against the CI output dir, so the served root
             (repositories/, media/, iptv/, rss/, index.html, robots.txt) is
             generated fresh every deploy and never committed.

The mirror honors .gitignore: a secret-bearing source file (e.g. IPTV instance
settings) is kept locally but never copied into the served tree.

Run from anywhere:
    python3 _tools/generate_repo.py
"""

import hashlib
import os
import shutil
import subprocess
import sys
import zipfile
from xml.etree import ElementTree as ET

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))
import check_site_secrets  # noqa: E402

ROOT_DIR = os.path.normpath(
    os.path.join(os.path.abspath(os.path.dirname(__file__)), "..")
)
DROPBOX_DIR = os.path.join(ROOT_DIR, "dropbox")
ADDONS_DIR = os.path.join(ROOT_DIR, "addons")


# Inside addons/: hosted/ holds the third-party mirror trees the proxy fetches
# verbatim — never built as an add-on, never indexed (it is not browsed at the
# bare URL and indexing would churn an index.html into every hosted subdir).
_ADDONS_SPECIAL = {"hosted"}

# First-party add-on source dirs to build but keep OUT of the legacy
# addons/addons.xml catalog. Empty now that the engine-era setup add-ons
# (bootstrap, library, modv2plus) are gone; retained as the hook for any future
# built-but-unlisted add-on. process_addons skips these exactly like hosted/.
_ADDONS_DELISTED = set()

# Tooling/cache dirs that must NEVER be zipped, indexed, or mirrored. They are
# build-time cruft (lint/test/type caches, bytecode) and leak non-deterministic
# bytes into add-on zips if a tool happened to run in a source dir before a build.
_CRUFT_DIRS = {"__pycache__", ".ruff_cache", ".pytest_cache", ".mypy_cache"}


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
    # Prune superseded versions so old zips never accumulate in the tree
    # (only the current version is committed; /static/ serves the fleet).
    for entry in sorted(os.listdir(addon_dir)):
        if (
            entry.startswith(addon_id + "-")
            and entry.endswith(".zip")
            and entry != zip_name
        ):
            os.remove(os.path.join(addon_dir, entry))
            print(f"  - pruned superseded {entry}")
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
        if (
            entry in _ADDONS_SPECIAL
            or entry in _ADDONS_DELISTED
            or not os.path.isdir(addon_dir)
        ):
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


def _index_tree(top: str, site_root: str) -> int:
    """Generate a Kodi index.html into `top` and every subdir, listing real
    entries (dirs + files) by name with sizes, no dates. Index titles and the
    structural secret delisting are computed relative to `site_root` (the
    served root the tree will be deployed under). Returns the number of
    indexes written.

    NO .gitignore check here: this walks the OUTPUT copy, which in CI lives
    under a gitignored dir (_site/), so `git check-ignore` would delist every
    file. Ignore-filtering already happened at copy time (_copy_canvas_dir
    checks the SOURCE paths); the structural secret delisting below is the
    output-side backstop.
    """
    count = 0
    for dirpath, dirnames, filenames in os.walk(top):
        dirnames[:] = sorted(d for d in dirnames if d not in _CRUFT_DIRS)
        rel = os.path.relpath(dirpath, site_root)
        rows = ['<a href="../">Parent Directory</a>']
        for d in dirnames:
            rows.append(f'<a href="{d}/">{d}/</a>')
        for f in sorted(filenames):
            if f == "index.html":
                continue
            fpath = os.path.join(dirpath, f)
            # Secret-bearing artifacts (the tracked instance-settings pair)
            # are excluded from the CI-built site by build_site.py; delisting
            # them here keeps the served indexes free of dead links AND stops
            # advertising the file's URL on the branch-served site today.
            if check_site_secrets._structural_violation(
                os.path.relpath(fpath, site_root)
            ):
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


def mirror_canvas(target_root: str, dropbox_dir: str | None = None) -> list[str]:
    """Mirror dropbox/ -> `target_root` (1:1) and index every served folder.

    Each top-level dropbox/ folder is copied to target_root/<folder> (replacing
    any prior copy), loose dropbox/ files are copied to the target root, and a
    Kodi index is generated into every served canvas folder. Returns the sorted
    canvas entry names (dirs + loose files) for the root listing. No-op if
    dropbox/ is absent. Called by build_site.py against the CI output dir; the
    mirror is never written into the repo itself.
    """
    src_root = dropbox_dir if dropbox_dir is not None else DROPBOX_DIR
    if not os.path.isdir(src_root):
        return []
    entries = sorted(os.listdir(src_root))

    listing = []
    for e in entries:
        src = os.path.join(src_root, e)
        dst = os.path.join(target_root, e)
        if os.path.isdir(src):
            _copy_canvas_dir(src, dst)
            _index_tree(dst, target_root)
            listing.append(e + "/")
            print(f"dropbox/{e}/ -> /{e}/")
        elif os.path.isfile(src) and not _git_ignored(src):
            shutil.copyfile(src, dst)
            listing.append(e)
    return listing


def write_root_index(target_root: str, canvas_listing: list[str]) -> None:
    """Generate the bare-URL root index.html: links present, visually hidden.

    The canvas entries (mirrored from dropbox/) ARE written as <a href> anchors
    so Kodi's File Manager, which discovers folders by scanning the HTML for
    href= and ignores CSS, can still browse the bare URL exactly as before. A
    <style> block hides the listing in a web browser (display:none on the body's
    children), so a human visiting https://tony7bones.github.io/ sees a blank
    page while Kodi sees the full folder list. HTML 3.2 doctype is kept for the
    Kodi parser; the style block is inert to it.

    The root install zip stays served at the root (fresh-install path) but is
    still NOT listed — only the canvas folders are.
    """
    rows = [f'<a href="{e}">{e}</a>' for e in canvas_listing]
    style = "<style>body>*{display:none}</style>"
    html = (
        '<!DOCTYPE HTML PUBLIC "-//W3C//DTD HTML 3.2 Final//EN">\n'
        "<html>\n<head><title></title>\n"
        f"{style}\n</head>\n"
        "<body>\n<pre>\n" + "\n".join(rows) + "\n</pre>\n</body>\n</html>\n"
    )
    with open(os.path.join(target_root, "index.html"), "w", encoding="utf-8") as fh:
        fh.write(html)


def write_robots(target_root: str) -> None:
    """Write a served-root robots.txt that asks crawlers to index nothing.

    Disallow-all keeps the listing out of search engines (the realistic scraper
    exposure on public Pages). It is advisory only — well-behaved crawlers obey,
    malicious scrapers and direct path access do not, and it has no effect on
    Kodi (not a crawler).
    """
    with open(os.path.join(target_root, "robots.txt"), "w", encoding="utf-8") as fh:
        fh.write("User-agent: *\nDisallow: /\n")


def generate() -> None:
    """Regenerate the COMMITTED add-on artifacts: per-add-on zips (current
    version only, superseded pruned), per-add-on indexes, and addons.xml +
    hashes. The served canvas mirror is NOT built here — build_site.py
    generates it into the CI output dir every deploy."""
    roots = process_addons(ADDONS_DIR)
    sha256, md5 = write_addons_xml(roots)

    print(f"\naddons.xml: {len(roots)} add-on(s)")
    print(f"addons.xml.sha256: {sha256}")
    print(f"addons.xml.md5:    {md5}")


if __name__ == "__main__":
    generate()
