"""Gate: the hosted dependency closure must be COMPLETE and self-contained.

A box that cannot reach the Kodi mirror (some fleet ATVs) can only install an
add-on if EVERY transitive dependency is hosted here. This test walks the
<import> graph offline (hosted addon.xml files only) from each first-party
add-on and fails if any non-built-in dependency is not itself hosted AND not
listed in repository.json. It is why "skin -> autocompletion -> requests ->
urllib3" can never again die on a missing piece on-device.

Regenerate the closure with:  python3 _tools/mirror_closure.py <id> --apply
"""

from __future__ import annotations

import os
import re

import pytest

HERE = os.path.dirname(__file__)
HOSTED = os.path.join(HERE, "..", "addons", "hosted")
REPO_JSON = os.path.join(
    HERE, "..", "_tools", "catalog.json"
)

# Roots whose FULL closure must be hosted (the fleet installs these off-grid).
ROOTS = ["skin.estuary7"]

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


def _imports(xml_text):
    return [
        m.group(1)
        for m in re.finditer(r'<import\s+addon="([^"]+)"', xml_text)
        if m.group(1) not in BUILTINS
    ]


def _hosted_xml(addon_id):
    p = os.path.join(HOSTED, addon_id, "addon.xml")
    return open(p, encoding="utf-8").read() if os.path.isfile(p) else None


def _repo_json_ids():
    txt = open(REPO_JSON, encoding="utf-8").read()
    return set(re.findall(r'"id":\s*"([^"]+)"', txt))


@pytest.mark.parametrize("root", ROOTS)
def test_dependency_closure_is_hosted(root):
    seen, missing = set(), []
    stack = [root]
    while stack:
        aid = stack.pop()
        if aid in seen:
            continue
        seen.add(aid)
        xml = _hosted_xml(aid)
        if xml is None:
            missing.append(aid)
            continue
        stack.extend(_imports(xml))
    missing = [m for m in missing if m != root]
    assert not missing, (
        f"{root} closure is INCOMPLETE - not hosted: {missing}. "
        f"Run: python3 _tools/mirror_closure.py {root} --apply"
    )


@pytest.mark.parametrize("root", ROOTS)
def test_hosted_closure_is_in_repository_json(root):
    """Every hosted piece of the closure must also be advertised by the proxy."""
    ids = _repo_json_ids()
    seen = set()
    stack = [root]
    not_listed = []
    while stack:
        aid = stack.pop()
        if aid in seen:
            continue
        seen.add(aid)
        xml = _hosted_xml(aid)
        if xml is None:
            continue
        if aid not in ids:
            not_listed.append(aid)
        stack.extend(_imports(xml))
    assert not not_listed, f"hosted but not in repository.json: {not_listed}"
