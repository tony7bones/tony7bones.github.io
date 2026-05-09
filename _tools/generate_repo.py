#!/usr/bin/env python3
"""Generate addons.xml, addons.xml.md5, and per-addon zip files for a Kodi repo.

Run from anywhere:
    python3 _tools/generate_repo.py

The script scans every subdirectory of repo/ that contains an addon.xml,
zips it (excluding pre-existing zips), and rewrites addons.xml / addons.xml.md5.
"""

import hashlib
import os
import zipfile
from xml.etree import ElementTree as ET

REPO_DIR = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "repo"))


def create_zip(addon_dir: str, addon_id: str, version: str) -> str:
    zip_name = f"{addon_id}-{version}.zip"
    zip_path = os.path.join(addon_dir, zip_name)
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for dirpath, _dirs, files in os.walk(addon_dir):
            for fname in files:
                if fname.endswith(".zip"):
                    continue
                fpath = os.path.join(dirpath, fname)
                arcname = os.path.relpath(fpath, os.path.dirname(addon_dir))
                zf.write(fpath, arcname)
    return zip_path


def generate() -> None:
    ET.register_namespace("", "")  # keep unqualified tags
    addon_roots: list[ET.Element] = []

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

    print(f"\nWrote addons.xml  ({len(addon_roots)} addon(s))")
    print(f"Wrote addons.xml.md5  ({md5})")


if __name__ == "__main__":
    generate()
