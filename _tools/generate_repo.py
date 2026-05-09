#!/usr/bin/env python3
"""Generate addons.xml, addons.xml.sha256, per-addon zips, and index.html files
so Kodi can browse the repo over HTTP.

Structure:
  repo/                          → plugins (included in addons.xml)
  repo/repositories/             → repo installer zips (manual install only)
  repo/media/                    → images browsable from Kodi file manager

Run from anywhere:
    python3 _tools/generate_repo.py
"""

import hashlib
import os
import zipfile
from datetime import datetime, timezone
from xml.etree import ElementTree as ET

REPO_DIR = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "repo"))
REPOS_DIR = os.path.join(REPO_DIR, "repositories")
MEDIA_DIR = os.path.join(REPO_DIR, "media")
MEDIA_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg"}


def _fmt_size(n: int) -> str:
    for unit in ("B", "K", "M", "G"):
        if n < 1024:
            return f"{n}{unit}"
        n //= 1024
    return f"{n}G"


def _fmt_date(path: str) -> str:
    ts = os.path.getmtime(path)
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M")


def _make_index(directory: str, title: str, rows: list[str]) -> None:
    """Write an Apache-style directory listing Kodi can parse for per-addon dirs."""
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


def process_addons(scan_dir: str) -> tuple[list[ET.Element], list[str]]:
    """Zip every addon subdir that has an addon.xml. Returns (roots, addon_ids)."""
    roots, ids = [], []
    for entry in sorted(os.listdir(scan_dir)):
        addon_dir = os.path.join(scan_dir, entry)
        xml_path = os.path.join(addon_dir, "addon.xml")
        if not os.path.isdir(addon_dir) or not os.path.exists(xml_path):
            continue
        root = ET.parse(xml_path).getroot()
        addon_id, version = root.get("id"), root.get("version")
        if not (addon_id and version):
            print(f"  ! skipping {entry}: missing id or version")
            continue
        zip_name = f"{addon_id}-{version}.zip"
        zip_path = os.path.join(addon_dir, zip_name)
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for dirpath, _dirs, files in os.walk(addon_dir):
                for fname in files:
                    if fname.endswith((".zip", ".html")):
                        continue
                    fpath = os.path.join(dirpath, fname)
                    arcname = os.path.relpath(fpath, os.path.dirname(addon_dir))
                    zf.write(fpath, arcname)
        zip_full = os.path.join(addon_dir, zip_name)
        addon_rows = [
            '<a href="../">Parent Directory</a>',
            f'<a href="{zip_name}">{zip_name}</a>  {_fmt_date(zip_full)}  {_fmt_size(os.path.getsize(zip_full))}',
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


def generate() -> None:
    ET.register_namespace("", "")

    plugin_roots, _plugin_ids = process_addons(REPO_DIR)

    addons_el = ET.Element("addons")
    for r in plugin_roots:
        addons_el.append(r)
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
        if os.path.isfile(os.path.join(REPOS_DIR, e)) and e.endswith(".zip")
    )
    html = _styled_page("Tony 7 Bones — Repositories", "Repositories", zip_entries)
    with open(os.path.join(REPOS_DIR, "index.html"), "w", encoding="utf-8") as fh:
        fh.write(html)

    generate_media_index()

    # repo/index.html is hand-crafted — never overwrite it

    print(f"\naddons.xml: {len(plugin_roots)} plugin(s)")
    print(f"addons.xml.sha256: {sha256}")
    print(f"addons.xml.md5:    {md5}")


if __name__ == "__main__":
    generate()
