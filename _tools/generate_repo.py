#!/usr/bin/env python3
"""Generate addons.xml, addons.xml.sha256, per-addon zips, and index.html files
so Kodi can browse the repo over HTTP.

Structure:
  repo/                → Kodi plugin add-ons (have addon.xml, go in addons.xml)
  repo/repositories/   → repo installer zips (manual install only)
  repo/scripts/        → script zips (manual install only)
  repo/media/          → images browsable from Kodi file manager
  repo/<anything>/     → any other directory is auto-indexed for Kodi file manager

Run from anywhere:
    python3 _tools/generate_repo.py
"""

import hashlib
import os
import subprocess
import zipfile
from datetime import datetime, timezone
from xml.etree import ElementTree as ET

REPO_DIR = os.path.normpath(
    os.path.join(os.path.abspath(os.path.dirname(__file__)), "..", "repo")
)
REPOS_DIR = os.path.join(REPO_DIR, "repositories")
SCRIPTS_DIR = os.path.join(REPO_DIR, "scripts")
MEDIA_DIR = os.path.join(REPO_DIR, "media")
MEDIA_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg"}

# Top-level dirs handled by dedicated generators — skip in asset discovery
_SPECIAL_DIRS = {"repositories", "scripts", "media"}


def _fmt_size(n: int) -> str:
    for unit in ("B", "K", "M", "G"):
        if n < 1024:
            return f"{n}{unit}"
        n //= 1024
    return f"{n}G"


def _git_date(path: str) -> str | None:
    """Return the last-commit date for path as 'YYYY-MM-DD HH:MM', or None if unknown."""
    try:
        out = (
            subprocess.check_output(
                ["git", "log", "-1", "--format=%cI", "--", path],
                stderr=subprocess.DEVNULL,
            )
            .decode()
            .strip()
        )
        if not out:
            return None
        dt = datetime.fromisoformat(out)
        return dt.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M")
    except (subprocess.CalledProcessError, ValueError, OSError):
        return None


def _fmt_date(path: str) -> str:
    """Return a stable date string for path.

    Prefers the git last-commit date so the output is identical on every
    checkout (including CI runners that reset all file mtimes).  Falls back
    to the filesystem mtime for untracked files.
    """
    git_date = _git_date(path)
    if git_date is not None:
        return git_date
    ts = os.path.getmtime(path)
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M")


def _make_index(directory: str, title: str, rows: list[str]) -> None:
    """Write an Apache-style directory listing Kodi can parse."""
    html = (
        '<!DOCTYPE HTML PUBLIC "-//W3C//DTD HTML 3.2 Final//EN">\n'
        f"<html>\n<head><title>{title}</title></head>\n"
        f"<body>\n<h1>{title}</h1>\n<pre>\n"
        + "\n".join(rows)
        + "\n</pre>\n</body>\n</html>\n"
    )
    with open(os.path.join(directory, "index.html"), "w", encoding="utf-8") as fh:
        fh.write(html)


def _styled_page(title: str, heading: str, links: list[str]) -> str:
    """Return a dark-themed HTML page using the shared stylesheet."""
    link_tags = "\n      ".join(f'<a href="{h}">{h}</a>' for h in links)
    return (
        "<!DOCTYPE html>\n"
        '<html lang="en">\n'
        "  <head>\n"
        '    <meta charset="utf-8">\n'
        f"    <title>{title}</title>\n"
        '    <link rel="stylesheet" href="/style.css">\n'
        "  </head>\n"
        "  <body>\n"
        '    <img src="/images/tony7bones.jpg" alt="Tony 7 Bones" class="avatar">\n'
        f"    <h1>{heading}</h1>\n"
        '    <nav class="links">\n'
        f"      {link_tags}\n"
        "    </nav>\n"
        "  </body>\n"
        "</html>\n"
    )


def _zip_is_stale(addon_dir: str, zip_path: str) -> bool:
    """Return True if any source file in addon_dir is newer than zip_path."""
    zip_mtime = os.path.getmtime(zip_path)
    root_index = os.path.join(addon_dir, "index.html")
    for dirpath, _dirs, files in os.walk(addon_dir):
        for fname in files:
            if fname.endswith(".zip") or os.path.join(dirpath, fname) == root_index:
                continue
            if os.path.getmtime(os.path.join(dirpath, fname)) > zip_mtime:
                return True
    return False


def process_addons(scan_dir: str) -> tuple[list[ET.Element], list[str]]:
    """Zip every addon subdir that has an addon.xml. Returns (roots, addon_ids)."""
    roots, ids = [], []
    for entry in sorted(os.listdir(scan_dir)):
        addon_dir = os.path.join(scan_dir, entry)
        xml_path = os.path.join(addon_dir, "addon.xml")
        if not os.path.isdir(addon_dir) or not os.path.exists(xml_path):
            continue
        try:
            root = ET.parse(xml_path).getroot()
        except ET.ParseError as exc:
            print(f"  ! skipping {entry}: malformed addon.xml ({exc})")
            continue
        addon_id, version = root.get("id"), root.get("version")
        if not (addon_id and version):
            print(f"  ! skipping {entry}: missing id or version")
            continue
        zip_name = f"{addon_id}-{version}.zip"
        zip_path = os.path.join(addon_dir, zip_name)
        if not os.path.exists(zip_path) or _zip_is_stale(addon_dir, zip_path):
            with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
                for dirpath, _dirs, files in os.walk(addon_dir):
                    for fname in files:
                        if fname.endswith(".zip") or (
                            fname == "index.html" and dirpath == addon_dir
                        ):
                            continue
                        fpath = os.path.join(dirpath, fname)
                        arcname = os.path.relpath(fpath, os.path.dirname(addon_dir))
                        zf.write(fpath, arcname)
        addon_rows = [
            '<a href="../">Parent Directory</a>',
            f'<a href="{zip_name}">{zip_name}</a>  {_fmt_date(zip_path)}  {_fmt_size(os.path.getsize(zip_path))}',
        ]
        _make_index(
            addon_dir,
            f"Index of /{os.path.relpath(addon_dir, os.path.dirname(REPO_DIR))}/",
            addon_rows,
        )
        roots.append(root)
        ids.append(addon_id)
        print(f"  + {addon_id} {version}  →  {zip_name}")
    return roots, ids


def generate_scripts_index() -> None:
    """Regenerate repo/scripts/index.html from the zip files currently in that directory."""
    if not os.path.isdir(SCRIPTS_DIR):
        return
    zips = sorted(e for e in os.listdir(SCRIPTS_DIR) if e.lower().endswith(".zip"))
    html = _styled_page("Tony 7 Bones — Scripts", "Scripts", zips)
    with open(os.path.join(SCRIPTS_DIR, "index.html"), "w", encoding="utf-8") as fh:
        fh.write(html)
    print(f"scripts/index.html: {len(zips)} zip(s)")


def generate_media_index() -> None:
    """Regenerate repo/media/index.html from the images currently in that directory."""
    if not os.path.isdir(MEDIA_DIR):
        return
    images = sorted(
        e for e in os.listdir(MEDIA_DIR) if os.path.splitext(e)[1].lower() in MEDIA_EXTS
    )
    html = _styled_page("Tony 7 Bones — Media", "Media", images)
    with open(os.path.join(MEDIA_DIR, "index.html"), "w", encoding="utf-8") as fh:
        fh.write(html)
    print(f"media/index.html: {len(images)} image(s)")


def generate_asset_indexes() -> None:
    """Recursively index every top-level asset directory in repo/.

    An asset directory is any subdirectory that:
      - is not a known special dir (repositories, scripts, media)
      - does not contain an addon.xml (those are Kodi add-ons, handled separately)

    Just drop a folder under repo/, run this script, commit — Kodi's file
    manager can browse the full tree.
    """
    total = 0
    for entry in sorted(os.listdir(REPO_DIR)):
        asset_dir = os.path.join(REPO_DIR, entry)
        if not os.path.isdir(asset_dir):
            continue
        if entry in _SPECIAL_DIRS:
            continue
        if os.path.exists(os.path.join(asset_dir, "addon.xml")):
            continue
        count = 0
        for dirpath, dirnames, filenames in os.walk(asset_dir):
            dirnames.sort()
            rel = os.path.relpath(dirpath, os.path.dirname(REPO_DIR))
            rows = ['<a href="../">Parent Directory</a>']
            for d in dirnames:
                rows.append(f'<a href="{d}/">{d}/</a>')
            for f in sorted(filenames):
                if f == "index.html":
                    continue
                fpath = os.path.join(dirpath, f)
                rows.append(
                    f'<a href="{f}">{f}</a>  {_fmt_date(fpath)}  {_fmt_size(os.path.getsize(fpath))}'
                )
            _make_index(dirpath, f"Index of /{rel}/", rows)
            count += 1
        print(f"{entry}/: {count} index(es) generated")
        total += count
    return total


def generate() -> None:
    plugin_roots, _plugin_ids = process_addons(REPO_DIR)

    # Opt-in hybrid path: declarative, GitHub-sourced add-ons resolved at
    # generate time (see external_addons.py). With no manifest file present this
    # is a no-op and never touches the network, so output stays byte-identical.
    try:
        from external_addons import process_external_addons

        ext_roots, _ext_ids = process_external_addons(write=True)
        plugin_roots.extend(ext_roots)
    except ImportError:
        pass
    except Exception as exc:  # manifest/network problems must not break the build
        print(f"  ! external add-ons skipped: {exc}")

    addons_el = ET.Element("addons")
    addons_el.extend(plugin_roots)
    ET.indent(addons_el, space="    ")
    addons_xml_path = os.path.join(REPO_DIR, "addons.xml")
    ET.ElementTree(addons_el).write(
        addons_xml_path, encoding="UTF-8", xml_declaration=True
    )

    with open(addons_xml_path, "rb") as fh:
        data = fh.read()
    sha256 = hashlib.sha256(data).hexdigest()
    md5 = hashlib.md5(data).hexdigest()
    with open(os.path.join(REPO_DIR, "addons.xml.sha256"), "w") as fh:
        fh.write(sha256)
    with open(os.path.join(REPO_DIR, "addons.xml.md5"), "w") as fh:
        fh.write(md5)

    os.makedirs(REPOS_DIR, exist_ok=True)
    zip_entries = sorted(
        e
        for e in os.listdir(REPOS_DIR)
        if os.path.isfile(os.path.join(REPOS_DIR, e)) and e.lower().endswith(".zip")
    )
    html = _styled_page("Tony 7 Bones — Repositories", "Repositories", zip_entries)
    with open(os.path.join(REPOS_DIR, "index.html"), "w", encoding="utf-8") as fh:
        fh.write(html)

    generate_scripts_index()
    generate_media_index()
    generate_asset_indexes()

    # repo/index.html is hand-crafted — never overwrite it

    print(f"\naddons.xml: {len(plugin_roots)} plugin(s)")
    print(f"addons.xml.sha256: {sha256}")
    print(f"addons.xml.md5:    {md5}")


if __name__ == "__main__":
    generate()
