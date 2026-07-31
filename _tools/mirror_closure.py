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

# Dependencies this tree is FORBIDDEN to host. Unlike BUILTINS, which are Kodi
# extension points no repository could host, these are REAL add-ons that Kodi
# resolves from its own official library. Defined here rather than in the gate
# because this tool is the thing that would otherwise re-create the mirror; the
# gate (test_closure.py) imports this same set, so the two can never drift.
#
# `script.skinshortcuts` was mirrored at addons/hosted/script.skinshortcuts/
# (2.0.3) until 2026-07-29, when the owner ordered every copy purged and the
# root CLAUDE.md gained a hard rule: "We do not patch it, fork it, version it,
# host it, mirror it, or ship it", with "adding it back to
# repo/addons/hosted/" listed as forbidden without exception. The skin's own
# `<import addon="script.skinshortcuts" .../>` line is explicitly the ONE
# permitted reference to it in the tree, so the import stays and is walked past
# rather than deleted. Kodi publishes it for every release this repo targets:
# mirrors.kodi.tv/addons/{nexus,omega,piers}/script.skinshortcuts/ all return
# 200, omega (the release skin.estuary7's xbmc.gui 5.17.0 pins) serves 2.0.3,
# and the skin asks for >= 1.1.3, which Kodi reads as a MINIMUM.
#
# The cost, stated plainly rather than hidden: an off-grid box that cannot
# reach mirrors.kodi.tv can no longer install Estuary 7 from this repo alone.
# That is the owner's call, taken with the prohibition in hand, not an
# oversight the gate should paper over. Anything added here needs the same kind
# of written reason, because a silent entry turns a real gate into a rubber
# stamp.
OFFICIAL_LIBRARY = frozenset({"script.skinshortcuts"})


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
    if addon_id in OFFICIAL_LIBRARY:
        raise SystemExit(
            f"refusing to mirror {addon_id}: Kodi resolves it from its official "
            f"library and hosting it here is forbidden (see OFFICIAL_LIBRARY "
            f"above and the HARD RULE in CLAUDE.md)"
        )
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
        if aid in seen or aid in BUILTINS or aid in OFFICIAL_LIBRARY:
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
    if root in OFFICIAL_LIBRARY:
        # Without this the walk skips the root and prints "closure complete",
        # which reads as success for a run that mirrored nothing and never
        # could. A vacuous pass is worse than a refusal.
        raise SystemExit(
            f"{root} is in OFFICIAL_LIBRARY: Kodi resolves it from its official "
            f"library and this repo is forbidden to host it. Nothing to mirror."
        )
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
