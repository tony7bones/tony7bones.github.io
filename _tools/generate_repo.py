#!/usr/bin/env python3
"""Generate addons.xml, addons.xml.md5, per-addon zips, and Apache-style
index.html files for every directory so Kodi can browse the repo over HTTP.

Run from anywhere:
    python3 _tools/generate_repo.py
"""

import hashlib
import os
import zipfile
from datetime import datetime, timezone
from xml.etree import ElementTree as ET

REPO_DIR = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "repo"))


def _fmt_size(n: int) -> str:
    for unit in ("B", "K", "M", "G"):
        if n < 1024:
            return f"{n}{unit}"
        n //= 1024
    return f"{n}G"


def _fmt_date(path: str) -> str:
    ts = os.path.getmtime(path)
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M")


def _apache_index(directory: str, title: str, parent: str) -> str:
    rows = [f'<a href="{parent}">Parent Directory</a>']

    entries = sorted(os.listdir(directory))

    # Directories first
    for name in entries:
        full = os.path.join(directory, name)
        if os.path.isdir(full) and name not in (".", ".."):
            rows.append(f'<a href="{name}/">{name}/</a>')

    # Then files (skip index.html itself)
    for name in entries:
        full = os.path.join(directory, name)
        if os.path.isfile(full) and name != "index.html":
            date = _fmt_date(full)
            size = _fmt_size(os.path.getsize(full))
            rows.append(f'<a href="{name}">{name}</a>  {date}  {size}')

    body = "\n".join(rows)
    return (
        f'<!DOCTYPE HTML PUBLIC "-//W3C//DTD HTML 3.2 Final//EN">\n'
        f"<html>\n<head><title>{title}</title></head>\n"
        f"<body>\n<h1>{title}</h1>\n<pre>\n{body}\n</pre>\n</body>\n</html>\n"
    )


def write_index(directory: str, url_path: str) -> None:
    title = f"Index of {url_path}"
    parent = "../" if url_path.rstrip("/").count("/") > 0 else "/"
    html = _apache_index(directory, title, parent)
    with open(os.path.join(directory, "index.html"), "w", encoding="utf-8") as fh:
        fh.write(html)


def create_zip(addon_dir: str, addon_id: str, version: str) -> str:
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
    return zip_path


def generate() -> None:
    ET.register_namespace("", "")
    addon_roots: list[ET.Element] = []
    addon_dirs: list[tuple[str, str]] = []  # (dir_path, addon_id)

    for entry in sorted(os.listdir(REPO_DIR)):
        addon_dir = os.path.join(REPO_DIR, entry)
        if not os.path.isdir(addon_dir):
            continue
        xml_path = os.path.join(addon_dir, "addon.xml")
        if not os.path.exists(xml_path):
            continue

        root = ET.parse(xml_path).getroot()
        addon_id = root.get("id")
        version = root.get("version")
        if not (addon_id and version):
            print(f"  ! skipping {entry}: missing id or version")
            continue

        zip_path = create_zip(addon_dir, addon_id, version)
        addon_roots.append(root)
        addon_dirs.append((addon_dir, addon_id))
        print(f"  + {addon_id} {version}  →  {os.path.basename(zip_path)}")

    # Build addons.xml
    addons_el = ET.Element("addons")
    for addon in addon_roots:
        addons_el.append(addon)
    ET.indent(addons_el, space="    ")

    addons_xml_path = os.path.join(REPO_DIR, "addons.xml")
    ET.ElementTree(addons_el).write(
        addons_xml_path, encoding="UTF-8", xml_declaration=True
    )

    # Write MD5
    with open(addons_xml_path, "rb") as fh:
        md5 = hashlib.md5(fh.read()).hexdigest()
    with open(os.path.join(REPO_DIR, "addons.xml.md5"), "w") as fh:
        fh.write(md5)

    # Generate index.html for each addon directory, then for the repo root
    for addon_dir, addon_id in addon_dirs:
        write_index(addon_dir, f"/repo/{addon_id}/")
        print(f"  index  {addon_id}/index.html")

    write_index(REPO_DIR, "/repo/")
    print("  index  repo/index.html")

    print(f"\nWrote addons.xml  ({len(addon_roots)} addon(s))")
    print(f"Wrote addons.xml.md5  ({md5})")


if __name__ == "__main__":
    generate()
