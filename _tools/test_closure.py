"""Gate: the hosted dependency closure must be COMPLETE and self-contained.

A box that cannot reach the Kodi mirror (some fleet ATVs) can only install an
add-on if EVERY transitive dependency is hosted here. This test walks the
<import> graph offline (hosted addon.xml files only) from each first-party
add-on and fails if any non-built-in dependency is not itself hosted AND not
listed in repository.json. It is why "skin -> autocompletion -> requests ->
urllib3" can never again die on a missing piece on-device.

Two exclusion sets, and they do NOT mean the same thing. BUILTINS are Kodi
extension points that no repository could host. OFFICIAL_LIBRARY are real
add-ons this tree is PROHIBITED from hosting, so the closure is deliberately
incomplete there.

That second set is IMPORTED from mirror_closure.py rather than repeated here,
for the same reason release_detect.changed_addons is shared between the release
tool and the pre-push gate: a gate and the tool its own error message tells you
to run must never be able to disagree about what is in scope.

Regenerate the closure with:  python3 _tools/mirror_closure.py <id> --apply
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

import pytest

HERE = os.path.dirname(__file__)
HOSTED = os.path.join(HERE, "..", "addons", "hosted")
REPO_JSON = os.path.join(HERE, "..", "_tools", "catalog.json")

sys.path.insert(0, str(Path(__file__).parent))
from mirror_closure import OFFICIAL_LIBRARY  # noqa: E402

# Roots whose FULL closure must be hosted (the fleet installs these off-grid).
#
# script.ezmaintenanceplusplus was added 2026-07-25. It ships to the same boxes
# as the skin and carries its own <requires>, but only the skin's closure was
# ever gated, so a bump to a dependency version this repo does not host would
# 404 at install time on an off-grid Apple TV with nothing red anywhere.
#
# skin.estuary8 was added 2026-07-31, the day it was first hosted here. Its
# closure is the interesting one: it imports script.estuary8.shortcuts, which is
# OURS and exists nowhere else, so an unhosted dependency is not a slow 404 on
# an off-grid box but an install that cannot succeed anywhere at all. Gating it
# from day one is cheap; discovering it from a box is not.
#
# skin.estuary.pov was added 2026-08-27, the day it was first hosted here, for
# that same "cheap on day one" reason. It was trivial then, when its only
# <import> was xbmc.gui: it is not now. As of 1.3.0 it imports xbmc.gui,
# plugin.program.autocompletion and plugin.video.pov, and the last two drag real
# subtrees behind them. 1.3.0 also DROPPED xbmc.python, which it had declared
# only to support a boot service it no longer has: the skin ships no Python at
# all now, and every tvOS repair lives in service.tvos.pythonfix below.
#
# service.tvos.pythonfix is a ROOT OF ITS OWN, added 2026-08-29, and the reason
# is the trap that produced it. It was reachable here for exactly two days, as a
# child of skin.estuary.pov 1.2.7's <import>. Removing that import in 1.2.8 is
# correct (it is a tvOS-only add-on and had no business on Fire TV), but it also
# silently dropped this add-on out of every closure walk in this file: no test
# fails, no gate turns red, and the first symptom would be an off-grid Apple TV
# unable to install it because script.module.requests stopped being hosted.
#
# The general lesson, worth more than this entry: a root that is reachable only
# THROUGH another root is not gated, it is coincidentally covered, and the cover
# disappears with an ordinary edit to somebody else's addon.xml. Anything the
# fleet installs DIRECTLY belongs in this list directly. This add-on is now
# user-installed on Apple TVs rather than pulled in by a skin, which makes it
# exactly that case.
ROOTS = [
    "skin.estuary7",
    "script.ezmaintenanceplusplus",
    "skin.estuary8",
    "skin.estuary.pov",
    "service.tvos.pythonfix",
]

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

# OFFICIAL_LIBRARY comes from mirror_closure.py; see the import at the top and
# that file for the per-entry reasons. Recorded here because it is this gate,
# not that tool, that a reader hits first: the one entry today is
# script.skinshortcuts, whose hosted 2.0.3 mirror was deleted 2026-07-29 under
# the root CLAUDE.md hard rule ("we do not patch it, fork it, version it, host
# it, mirror it, or ship it"; re-adding it to addons/hosted/ is listed as
# forbidden without exception). The skin's <import> line stays, and is named
# there as the ONE permitted reference to it in the tree.
#
# The cost, stated rather than hidden: an off-grid box that cannot reach
# mirrors.kodi.tv can no longer install Estuary 7 from this repo alone. That is
# the owner's call taken with the prohibition in hand, not an oversight this
# gate should paper over. Anything added to that set needs the same kind of
# written reason, or the set turns a real gate into a rubber stamp.


def _imports(xml_text):
    return [
        m.group(1)
        for m in re.finditer(r'<import\s+addon="([^"]+)"', xml_text)
        if m.group(1) not in BUILTINS and m.group(1) not in OFFICIAL_LIBRARY
    ]


def _hosted_xml(addon_id):
    p = os.path.join(HOSTED, addon_id, "addon.xml")
    return open(p, encoding="utf-8").read() if os.path.isfile(p) else None


def _repo_json_ids():
    txt = open(REPO_JSON, encoding="utf-8").read()
    return set(re.findall(r'"id":\s*"([^"]+)"', txt))


def closure_missing(root, lookup=_hosted_xml):
    """Ids in root's transitive <import> graph that this repo does not host.

    Takes the addon.xml lookup as an argument so the gate's own behaviour can
    be tested against a fake tree: that an OFFICIAL_LIBRARY id is satisfied,
    and, more importantly, that a genuinely missing id of OURS still fails.
    """
    seen, missing = set(), []
    stack = [root]
    while stack:
        aid = stack.pop()
        if aid in seen:
            continue
        seen.add(aid)
        xml = lookup(aid)
        if xml is None:
            missing.append(aid)
            continue
        stack.extend(_imports(xml))
    return [m for m in missing if m != root]


@pytest.mark.parametrize("root", ROOTS)
def test_dependency_closure_is_hosted(root):
    missing = closure_missing(root)
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


# --------------------------------------------------------------------------- #
# the exemption is itself gated
#
# An exclusion set added to make a red build green is one edit away from being
# the place a real missing dependency goes to hide. These four tests are what
# stop OFFICIAL_LIBRARY becoming that place.
# --------------------------------------------------------------------------- #
def test_official_library_holds_nothing_of_ours():
    """It may only ever name add-ons Kodi ships, never one this repo delivers.

    Three independent proofs that an id is not ours: it is not a gated root, we
    carry no hosted mirror of it, and our catalog does not advertise it. Any of
    the three failing means this repo still ships the thing, and whether this
    repo ships a dependency is precisely what the closure gate measures.
    """
    hosted = {d for d in os.listdir(HOSTED) if os.path.isdir(os.path.join(HOSTED, d))}
    advertised = _repo_json_ids()
    for aid in OFFICIAL_LIBRARY:
        assert aid not in ROOTS, f"{aid} is a first-party root, not Kodi's"
        assert aid not in hosted, (
            f"addons/hosted/{aid}/ exists, so the exemption is both wrong and "
            f"dead weight - delete one of the two"
        )
        assert aid not in advertised, (
            f"catalog.json advertises {aid}, so this repo still ships it"
        )


def test_official_library_is_a_closed_list_of_named_ids():
    """Explicit ids only: no prefixes, no patterns, no wildcards.

    A rule like "anything under script.module." would silently swallow a real
    missing dependency the day one of ours happened to match it. Changing this
    list is meant to require changing this line.
    """
    assert OFFICIAL_LIBRARY == frozenset({"script.skinshortcuts"})


def test_an_official_library_dependency_is_satisfied_unhosted():
    """The actual fix: our add-on may import it without this repo hosting it."""
    fake = {"skin.ours": '<import addon="script.skinshortcuts" version="1.1.3"/>'}
    assert closure_missing("skin.ours", fake.get) == []


def test_a_missing_dependency_of_ours_still_fails():
    """The exemption must not have turned the gate into a rubber stamp."""
    fake = {
        "skin.ours": (
            '<import addon="script.skinshortcuts" version="1.1.3"/>'
            '<import addon="script.module.ours" version="1.0.0"/>'
        )
    }
    assert closure_missing("skin.ours", fake.get) == ["script.module.ours"]
