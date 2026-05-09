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

    # repositories/ index — styled page (Kodi still parses <a href=name>name</a>)
    os.makedirs(REPOS_DIR, exist_ok=True)
    zip_entries = sorted(
        e
        for e in os.listdir(REPOS_DIR)
        if os.path.isfile(os.path.join(REPOS_DIR, e)) and e.endswith(".zip")
    )
    link_tags = "\n      ".join(f'<a href="{e}">{e}</a>' for e in zip_entries)
    styled_html = (
        "<!doctype html>\n<html>\n  <head>\n"
        "    <title>Tony 7 Bones — Repositories</title>\n"
        "    <style>\n"
        "      *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }\n"
        "      body {\n"
        "        background: #0a0a0a; color: #e0e0e0;\n"
        "        font-family: Verdana, sans-serif; min-height: 100vh;\n"
        "        display: flex; flex-direction: column;\n"
        "        align-items: center; justify-content: center;\n"
        "        gap: 2rem; padding: 2rem;\n"
        "      }\n"
        "      .avatar {\n"
        "        width: 140px; height: 140px; border-radius: 50%;\n"
        "        object-fit: cover; border: 3px solid #444;\n"
        "        box-shadow: 0 0 30px rgba(255,255,255,0.08);\n"
        "      }\n"
        "      h1 {\n"
        "        font-size: 1.5rem; font-weight: normal;\n"
        "        letter-spacing: 0.1em; color: #ccc; text-transform: uppercase;\n"
        "      }\n"
        "      .links { display: flex; flex-direction: column; gap: 0.75rem; width: 340px; }\n"
        "      .links a {\n"
        "        display: block; padding: 0.65rem 1.25rem;\n"
        "        background: #1a1a1a; border: 1px solid #333; border-radius: 6px;\n"
        "        color: #bbb; text-decoration: none; font-size: 0.8rem;\n"
        "        letter-spacing: 0.03em; text-align: center;\n"
        "        transition: background 0.2s, border-color 0.2s, color 0.2s;\n"
        "      }\n"
        "      .links a:hover { background: #252525; border-color: #555; color: #fff; }\n"
        "    </style>\n"
        "  </head>\n  <body>\n"
        '    <img src="../../images/tony7bones.jpg" alt="Tony 7 Bones" class="avatar" />\n'
        "    <h1>Repositories</h1>\n"
        '    <nav class="links">\n'
        f"      {link_tags}\n"
        "    </nav>\n"
        "  </body>\n</html>\n"
    )
    with open(os.path.join(REPOS_DIR, "index.html"), "w", encoding="utf-8") as fh:
        fh.write(styled_html)

    # repo/index.html is a custom hand-crafted page — never overwrite it

    print(f"\naddons.xml: {len(plugin_roots)} plugin(s)")
    print(f"addons.xml.sha256: {sha256}")


if __name__ == "__main__":
    generate()
