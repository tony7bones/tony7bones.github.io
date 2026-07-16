#!/usr/bin/env python3
"""Mirror the COMPLETE transitive dependency closure of a hosted add-on into
addons/hosted/, pulling any missing pieces from the Kodi Omega mirror.

Why: the proxy hosts a skin's dependencies so a box can install it WITHOUT
reaching the Kodi mirror (some fleet boxes can't, or the mirror is flaky). If
the closure is incomplete, an install dies on a missing transitive dep
(e.g. skin -> autocompletion -> requests -> urllib3). This tool resolves the
closure from the mirror and mirrors every not-yet-hosted piece, so the closure
is self-contained. Run it, review the diff, then generate_repo + deploy.

Usage: python3 _tools/mirror_closure.py <root_addon_id> [--apply]
       (without --apply it only reports what is missing)
"""

from __future__ import annotations

import os
import re
import sys
import urllib.request
import zipfile

MIRROR = "https://mirrors.kodi.tv/addons/omega/{id}/"
HOSTED = os.path.join(os.path.dirname(__file__), "..", "addons", "hosted")

# Kodi-provided extension points / built-ins that are never separate add-ons.
BUILTINS = {
    "xbmc.python",
    "xbmc.gui",
    "xbmc.addon",
    "xbmc.json",
    "xbmc.metadata",
    "kodi.resource",
    "xbmc.webinterface",
    "xbmc.audioencoder",
    "xbmc.python.pluginsource",
    "xbmc.python.module",
    "xbmc.python.script",
    "xbmc.python.library",
    "xbmc.gui.skin",
    "xbmc.service",
    "kodi.context.item",
}


def _imports(xml_text: str) -> list[str]:
    ids = []
    for m in re.finditer(r'<import\s+addon="([^"]+)"', xml_text):
        aid = m.group(1)
        if aid not in BUILTINS:
            ids.append(aid)
    return ids


def _hosted_ids() -> set[str]:
    if not os.path.isdir(HOSTED):
        return set()
    return {d for d in os.listdir(HOSTED) if os.path.isdir(os.path.join(HOSTED, d))}


def _hosted_addon_xml(addon_id: str) -> str | None:
    p = os.path.join(HOSTED, addon_id, "addon.xml")
    return open(p, encoding="utf-8").read() if os.path.isfile(p) else None


def _mirror_index(addon_id: str) -> str:
    with urllib.request.urlopen(MIRROR.format(id=addon_id), timeout=45) as r:
        return r.read().decode("utf-8", "ignore")


def _latest_zip(addon_id: str) -> str:
    idx = _mirror_index(addon_id)
    names = sorted(
        set(re.findall(re.escape(addon_id) + r"-[0-9][0-9A-Za-z.+~-]*\.zip", idx))
    )
    if not names:
        raise SystemExit(f"no zip for {addon_id} on the Kodi mirror")

    def key(n):
        v = n[len(addon_id) + 1 : -4]
        return [int(x) if x.isdigit() else 0 for x in re.split(r"[.+~-]", v)]

    return sorted(names, key=key)[-1]


def _fetch(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=90) as r:
        return r.read()


def mirror_one(addon_id: str, apply: bool) -> str:
    zip_name = _latest_zip(addon_id)
    url = MIRROR.format(id=addon_id) + zip_name
    blob = _fetch(url)
    with zipfile.ZipFile(__import__("io").BytesIO(blob)) as zf:
        axml = next(n for n in zf.namelist() if n.endswith("/addon.xml"))
        addon_xml = zf.read(axml).decode("utf-8", "ignore")
    if apply:
        dst = os.path.join(HOSTED, addon_id)
        os.makedirs(dst, exist_ok=True)
        with open(os.path.join(dst, zip_name), "wb") as f:
            f.write(blob)
        with open(os.path.join(dst, "addon.xml"), "w", encoding="utf-8") as f:
            f.write(addon_xml)
    return addon_xml


def closure(root_id: str, apply: bool) -> tuple[list[str], list[str]]:
    seen: set[str] = set()
    missing: list[str] = []
    mirrored: list[str] = []
    hosted = _hosted_ids()

    stack = [root_id]
    while stack:
        aid = stack.pop()
        if aid in seen or aid in BUILTINS:
            continue
        seen.add(aid)

        xml = _hosted_addon_xml(aid)
        if xml is None and aid != root_id:
            # Not hosted -> pull it (and its addon.xml) from the mirror.
            missing.append(aid)
            xml = mirror_one(aid, apply)
            if apply:
                mirrored.append(aid)
                hosted.add(aid)
        if xml is None:
            continue
        for dep in _imports(xml):
            if dep not in seen:
                stack.append(dep)
    return missing, mirrored


def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    root = sys.argv[1]
    apply = "--apply" in sys.argv[2:]
    missing, mirrored = closure(root, apply)
    print(f"root: {root}")
    print(f"missing from hosted/ (transitive): {missing or 'NONE - closure complete'}")
    if apply:
        print(f"mirrored into hosted/: {mirrored}")
    elif missing:
        print("re-run with --apply to mirror them, then generate_repo + deploy")
        sys.exit(1)


if __name__ == "__main__":
    main()
