#!/usr/bin/env python3
"""Generate addons.xml, addons.xml.sha256, per-addon zips, and Apache-style
index.html files so Kodi can browse the repo over HTTP.

Structure:
  repo/                          → plugins (included in addons.xml)
  repo/repositories/             → repo installer zips (manual install only)

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
    html = (
        '<!DOCTYPE HTML PUBLIC "-//W3C//DTD HTML 3.2 Final//EN">\n'
        f"<html>\n<head><title>{title}</title></head>\n"
        f"<body>\n<h1>{title}</h1>\n<pre>\n"
        + "\n".join(rows)
        + "\n</pre>\n</body>\n</html>\n"
    )
    with open(os.path.join(directory, "index.html"), "w", encoding="utf-8") as fh:
        fh.write(html)


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
        # per-addon index: only the zip, flat
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


def generate() -> None:
    ET.register_namespace("", "")

    # Plugins at repo root → go into addons.xml
    plugin_roots, plugin_ids = process_addons(REPO_DIR)

    # addons.xml (plugins only)
    addons_el = ET.Element("addons")
    for r in plugin_roots:
        addons_el.append(r)
    ET.indent(addons_el, space="    ")
    addons_xml_path = os.path.join(REPO_DIR, "addons.xml")
    ET.ElementTree(addons_el).write(
        addons_xml_path, encoding="UTF-8", xml_declaration=True
    )

    with open(addons_xml_path, "rb") as fh:
        sha256 = hashlib.sha256(fh.read()).hexdigest()
    with open(os.path.join(REPO_DIR, "addons.xml.sha256"), "w") as fh:
        fh.write(sha256)

    # repositories/ index — flat zip list (direct children only, no subdirs)
    os.makedirs(REPOS_DIR, exist_ok=True)
    repo_rows = ['<a href="../">Parent Directory</a>']
    for entry in sorted(os.listdir(REPOS_DIR)):
        full = os.path.join(REPOS_DIR, entry)
        if os.path.isfile(full) and entry.endswith(".zip"):
            repo_rows.append(
                f'<a href="{entry}">{entry}</a>  {_fmt_date(full)}  {_fmt_size(os.path.getsize(full))}'
            )
    _make_index(REPOS_DIR, "Index of /repo/repositories/", repo_rows)

    # repo/ root index — repositories/ folder + plugin dirs
    root_rows = [
        '<a href="../">Parent Directory</a>',
        '<a href="repositories/">repositories/</a>',
    ]
    for entry in sorted(os.listdir(REPO_DIR)):
        full = os.path.join(REPO_DIR, entry)
        if (
            os.path.isdir(full)
            and entry not in ("repositories",)
            and not entry.startswith("repository.")
        ):
            root_rows.append(f'<a href="{entry}/">{entry}/</a>')
    _make_index(REPO_DIR, "Index of /repo/", root_rows)

    print(f"\naddons.xml: {len(plugin_roots)} plugin(s)")
    print(f"addons.xml.sha256: {sha256}")


if __name__ == "__main__":
    generate()
