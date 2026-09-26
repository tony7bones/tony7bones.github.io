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
import static_catalog as sc  # noqa: E402
from mirror_closure import OFFICIAL_LIBRARY  # noqa: E402

# Roots whose FULL closure must be hosted (the fleet installs these off-grid).
#
# script.ezmaintenanceplusplus was a root here from 2026-07-25 to 2026-09-26.
# It ships to the same boxes as the skin and carries its own <requires>, but
# only the skin's closure was ever gated, so a bump to a dependency version
# this repo does not host would 404 at install time on an off-grid Apple TV
# with nothing red anywhere. Since 2026-09-26 it has NO committed addon.xml:
# its version and metadata are resolved from its latest GitHub release at
# build time, so this offline walk cannot see its imports. Its closure is
# gated where the metadata arrives instead, by
# static_catalog._check_imports_hosted at every build, and
# test_build_resolved_entries_are_gated_at_build below pins that the two
# mechanisms together leave no entry uncovered. plugin.video.pov (resolved
# from upstream's own addons.xml the same way) is a leaf in the skin's walk
# for the same reason.
#
# skin.estuary7 (rooted from this file's creation) and skin.estuary8 (rooted
# 2026-07-31) left on 2026-08-31, when both skins were decommissioned and
# unpublished on the owner's order; their closures left with their catalog
# entries.
#
# skin.estuary.pov was a root here from 2026-08-27, the day it was first hosted,
# to 2026-09-26, when it became a release-asset entry like EZM++: its version
# and addon.xml now come from the newest skin.estuary.pov-v<version> release of
# moquette/kodi-estuary-pov at build time, nothing of it is committed here, and
# this offline walk cannot see its imports. Its closure is gated where the
# metadata arrives, by static_catalog._check_imports_hosted, which since the
# same day walks TRANSITIVELY through committed hosted addon.xml files, so the
# skin's autocompletion subtree is checked on every build. The subtree is ALSO
# rooted below on its own, so the offline suite goes red before a push rather
# than the build going stale after one: as of 1.3.0 the skin imports xbmc.gui,
# plugin.program.autocompletion and plugin.video.pov, and the first of those two
# drags a real subtree behind it (autocompletion -> script.module.autocompletion
# -> requests -> urllib3 ...). plugin.video.pov is a build-resolved leaf.
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
    "service.tvos.pythonfix",
    # skin.estuary.pov's hosted subtree, rooted directly (see above): the skin
    # itself is build-resolved and walked by _check_imports_hosted instead.
    "plugin.program.autocompletion",
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
# that file for the history. EMPTY since 2026-08-31: its one entry ever,
# script.skinshortcuts, existed for the decommissioned skin.estuary7 and left
# with it. The mechanism and its four gates below stay, so a future entry
# needs a written reason rather than a silent line.


def _imports(xml_text):
    return [
        m.group(1)
        for m in re.finditer(r'<import\s+addon="([^"]+)"', xml_text)
        if m.group(1) not in BUILTINS and m.group(1) not in OFFICIAL_LIBRARY
    ]


def _build_resolved_ids():
    """Ids whose addon.xml exists only at build time (no committed copy)."""
    return {e["id"] for e in sc.load_catalog() if sc.metadata_resolved_at_build(e)}


def _hosted_xml(addon_id):
    p = os.path.join(HOSTED, addon_id, "addon.xml")
    if os.path.isfile(p):
        return open(p, encoding="utf-8").read()
    if addon_id in _build_resolved_ids():
        # Present in the catalog, metadata resolved at build time, and its own
        # imports are checked by static_catalog._check_imports_hosted against
        # the catalog on every build. A leaf here, not a hole.
        return ""
    return None


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


def test_build_resolved_entries_are_gated_at_build():
    """The offline walk above and the build-time import check together cover
    every entry this repo carries metadata for: a build-resolved id must have
    no committed addon.xml, or two truths exist and one of them rots, and the
    build-time half must really refuse an unhosted import."""
    resolved = _build_resolved_ids()
    assert resolved == {
        "script.ezmaintenanceplusplus",
        "plugin.video.pov",
        "skin.estuary.pov",
    }
    for aid in resolved:
        assert aid not in ROOTS, f"{aid} is build-resolved: it cannot be walked here"
        assert not os.path.exists(os.path.join(HOSTED, aid)), (
            f"addons/hosted/{aid}/ exists but the build resolves its metadata "
            f"upstream: delete the directory, there must be no copy to rot"
        )
    # The build-time half really refuses an unhosted import, and walks the
    # REAL hosted tree transitively: script.module.requests is hosted here and
    # its own imports are in the catalog, so the closure through it is clean.
    catalog_ids = _repo_json_ids()
    with pytest.raises(sc.FetchError, match="script.module.nothosted"):
        sc._check_imports_hosted(
            "x",
            b'<addon id="x" version="1"><requires>'
            b'<import addon="xbmc.python" version="3.0.0"/>'
            b'<import addon="script.module.nothosted"/>'
            b"</requires></addon>",
            catalog_ids | {"x"},
        )
    sc._check_imports_hosted(
        "x",
        b'<addon id="x" version="1"><requires>'
        b'<import addon="xbmc.python" version="3.0.0"/>'
        b'<import addon="script.module.requests"/>'
        b"</requires></addon>",
        catalog_ids | {"x"},
    )
    # The skin's REAL closure, as its hosted subtree stands today: its
    # direct imports must resolve through the catalog with nothing missing.
    sc._check_imports_hosted(
        "skin.estuary.pov",
        b'<addon id="skin.estuary.pov" version="1"><requires>'
        b'<import addon="xbmc.gui" version="5.18.0"/>'
        b'<import addon="plugin.program.autocompletion" version="2.1.2"/>'
        b'<import addon="plugin.video.pov" version="6.08.15"/>'
        b"</requires></addon>",
        catalog_ids,
    )


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
    assert OFFICIAL_LIBRARY == frozenset()


def test_an_official_library_dependency_is_satisfied_unhosted(monkeypatch):
    """The mechanism: our add-on may import an exempted id without this repo
    hosting it. Exercised with a synthetic id injected into this module's
    OFFICIAL_LIBRARY binding (the set itself is empty today; the historical
    entry was script.skinshortcuts, which left with skin.estuary7)."""
    monkeypatch.setattr(
        sys.modules[__name__], "OFFICIAL_LIBRARY", frozenset({"script.official.example"})
    )
    fake = {"skin.ours": '<import addon="script.official.example" version="1.0.0"/>'}
    assert closure_missing("skin.ours", fake.get) == []


def test_a_missing_dependency_of_ours_still_fails(monkeypatch):
    """The exemption must not have turned the gate into a rubber stamp."""
    monkeypatch.setattr(
        sys.modules[__name__], "OFFICIAL_LIBRARY", frozenset({"script.official.example"})
    )
    fake = {
        "skin.ours": (
            '<import addon="script.official.example" version="1.0.0"/>'
            '<import addon="script.module.ours" version="1.0.0"/>'
        )
    }
    assert closure_missing("skin.ours", fake.get) == ["script.module.ours"]
