"""Gate: the dependency closure this repo serves must be COMPLETE.

A box that cannot reach the Kodi mirror (some fleet ATVs) can only install an
add-on if EVERY transitive dependency is served here, and Kodi resolves a hard
dependency only from the repository the add-on is installed FROM (measured on
a Kodi 22 bench). Until 2026-09-26 this file walked the <import> graph OFFLINE
through committed addons/hosted/<id>/addon.xml files. Since that day NOTHING
of ours and none of our dependencies has a committed addon.xml: the four
add-ons the fleet installs and the eleven official-library modules they drag
in are all resolved at build time (releases, POV's index, the official Kodi
repository's index). So the offline walk has nothing to walk, and the closure
gate is static_catalog._check_imports_hosted, which walks every build-resolved
entry's imports TRANSITIVELY through the other build-resolved entries, reading
each addon.xml out of its resolved zip, on every build. This file pins that
the two halves leave no entry uncovered, and exercises the walk against a
fake tree so the gate's own behaviour stays tested without the network.

Two exclusion sets, and they do NOT mean the same thing. BUILTINS are Kodi
extension points that no repository could host. OFFICIAL_LIBRARY are real
add-ons this tree is PROHIBITED from hosting, so the closure is deliberately
incomplete there. Both sets are IMPORTED from static_catalog.py, where the
build-time walk reads them, so this gate and the build can never disagree
about what is in scope. (They lived in mirror_closure.py until 2026-09-26,
when that retired tool was deleted.)
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
from static_catalog import BUILTINS, OFFICIAL_LIBRARY  # noqa: E402

# The ids the fleet installs DIRECTLY. Every one of them is build-resolved
# (no committed addon.xml, metadata out of the resolved zip) and its whole
# closure is walked by static_catalog._check_imports_hosted at build time.
#
# History of this list, because each entry taught something:
#
# script.ezmaintenanceplusplus was an offline root from 2026-07-25 to
# 2026-09-26. It ships to the same boxes as the skin and carries its own
# <requires>, but only the skin's closure was ever gated, so a bump to a
# dependency version this repo did not serve would have 404ed at install time
# on an off-grid Apple TV with nothing red anywhere.
#
# skin.estuary7 (rooted from this file's creation) and skin.estuary8 (rooted
# 2026-07-31) left on 2026-08-31, when both skins were decommissioned and
# unpublished on the owner's order; their closures left with their entries.
#
# skin.estuary.pov was rooted from 2026-08-27, the day it was first hosted, to
# 2026-09-26, when it became a release-asset entry: as of 1.3.0 it imports
# xbmc.gui, plugin.program.autocompletion and plugin.video.pov, and the first
# of those drags a real subtree (autocompletion -> script.module.autocompletion
# -> requests -> urllib3/certifi/chardet/idna).
#
# service.tvos.pythonfix is listed ON ITS OWN, since 2026-08-29, and the reason
# is the trap that produced it. It was reachable for exactly two days as a
# child of skin.estuary.pov 1.2.7's <import>. Removing that import in 1.2.8 was
# correct (a tvOS-only add-on had no business on Fire TV), but it also silently
# dropped this add-on out of every closure walk: no test failed, no gate went
# red, and the first symptom would have been an off-grid Apple TV unable to
# install it. A root reachable only THROUGH another root is not gated, it is
# coincidentally covered, and the cover disappears with an ordinary edit to
# somebody else's addon.xml. Anything the fleet installs DIRECTLY is listed
# here directly.
#
# The hosted subtrees those roots stood on (script.module.requests and
# plugin.program.autocompletion were rooted here from 2026-09-26 morning until
# the afternoon) left when the eleven official modules became build-resolved
# from the official Kodi repository's index: there is no committed addon.xml
# left to walk, and the build-time walk now carries every hop.
# skin.estuary.plusplus is the same skin under its new id since 2026-09-26
# (Estuary++, 1.5.0, repo moquette/kodi-estuarypp); its imports are the
# old id's. skin.estuary.pov left the catalog on 2026-09-26 (stage E of the
# rename plan, recorded in _tools/retired.json); boxes still on it migrate
# from what they have installed, they do not need the hub to serve it.
FLEET_INSTALLS = {
    "skin.estuary.plusplus",
    "service.tvos.pythonfix",
    "script.ezmaintenanceplusplus",
    "plugin.video.pov",  # the skin's hard import; not ours, served for it
}

# The official-library modules the closures above reach, all build-resolved
# from https://mirrors.kodi.tv/addons/piers/addons.xml.gz since 2026-09-26.
OFFICIAL_MODULES = {
    "plugin.program.autocompletion",
    "script.image.resource.select",
    "script.module.autocompletion",
    "script.module.certifi",
    "script.module.chardet",
    "script.module.idna",
    "script.module.requests",
    "script.module.simplecache",
    "script.module.simpleeval",
    "script.module.unidecode",
    "script.module.urllib3",
}

# BUILTINS and OFFICIAL_LIBRARY come from static_catalog.py; see the import at
# the top. OFFICIAL_LIBRARY is EMPTY since 2026-08-31: its one entry ever,
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


def test_every_fleet_installed_id_is_build_resolved_with_no_committed_copy():
    """A build-resolved id must have no committed addon.xml, or two truths
    exist and one of them rots (the owner's rule of 2026-09-26: THERE MUST BE
    NO MIRROR VERSION TO BE WRONG). The set is pinned exactly so a new entry
    of ours cannot arrive as a hand copy unnoticed."""
    resolved = _build_resolved_ids()
    assert resolved == FLEET_INSTALLS | OFFICIAL_MODULES
    for aid in resolved:
        assert not os.path.exists(os.path.join(HOSTED, aid)), (
            f"addons/hosted/{aid}/ exists but the build resolves its metadata "
            f"upstream: delete the directory, there must be no copy to rot"
        )
    # what is left under addons/hosted/ is third-party repository installers
    hosted = {d for d in os.listdir(HOSTED) if os.path.isdir(os.path.join(HOSTED, d))}
    assert hosted and all(d.startswith("repository.") for d in hosted), hosted


def test_official_modules_follow_the_official_index_not_a_committed_copy():
    by_id = {e["id"]: e for e in sc.load_catalog()}
    for aid in OFFICIAL_MODULES:
        e = by_id[aid]
        assert sc.classify(e) == sc.KIND_HYBRID, aid
        assert e["upstream_index"] == "https://mirrors.kodi.tv/addons/piers/addons.xml.gz"
        assert e["assets"]["zip"] == (
            "https://mirrors.kodi.tv/addons/piers/{id}/{id}-{version}.zip"
        )


def _fake_resolver(tree: dict[str, str]):
    """addon.xml lookup for build-resolved ids, shaped like
    BuildContext.addon_xml_for: bytes for a known id, None otherwise."""

    def resolver(aid):
        xml = tree.get(aid)
        if xml is None:
            return None
        return (
            f'<addon id="{aid}" version="1"><requires>{xml}</requires></addon>'
        ).encode()

    return resolver


def test_build_time_walk_carries_the_whole_closure():
    """The build-time half really walks TRANSITIVELY through build-resolved
    entries and refuses an import that is neither a catalog entry nor a Kodi
    builtin. The tree is the fleet's real shape: skin -> autocompletion plugin
    -> autocompletion module -> requests -> urllib3/certifi/chardet/idna, and
    service.tvos.pythonfix -> requests -> the same leaves."""
    tree = {
        "plugin.program.autocompletion": (
            '<import addon="xbmc.python" version="3.0.0"/>'
            '<import addon="script.module.autocompletion" version="2.0.5"/>'
        ),
        "script.module.autocompletion": (
            '<import addon="script.module.requests" version="2.9.1"/>'
        ),
        "script.module.requests": (
            '<import addon="script.module.certifi"/>'
            '<import addon="script.module.chardet"/>'
            '<import addon="script.module.idna"/>'
            '<import addon="script.module.urllib3"/>'
        ),
        "script.module.urllib3": "",
        "script.module.certifi": "",
        "script.module.chardet": "",
        "script.module.idna": "",
        "plugin.video.pov": '<import addon="script.module.requests"/>',
    }
    catalog_ids = set(tree) | FLEET_INSTALLS
    def skin_xml(aid):
        return (
            b'<addon id="' + aid.encode() + b'" version="1"><requires>'
            b'<import addon="xbmc.gui" version="5.18.0"/>'
            b'<import addon="plugin.program.autocompletion" version="2.1.2"/>'
            b'<import addon="plugin.video.pov" version="6.08.15"/>'
            b"</requires></addon>"
        )

    skin = skin_xml("skin.estuary.pov")
    fixes = (
        b'<addon id="service.tvos.pythonfix" version="1"><requires>'
        b'<import addon="xbmc.python" version="3.0.0"/>'
        b'<import addon="script.module.requests" version="2.31.0"/>'
        b"</requires></addon>"
    )
    sc._check_imports_hosted(
        "skin.estuary.pov", skin, catalog_ids, resolver=_fake_resolver(tree)
    )
    # the renamed skin declares the same imports and must resolve them the
    # same way from its own release zip
    sc._check_imports_hosted(
        "skin.estuary.plusplus",
        skin_xml("skin.estuary.plusplus"),
        catalog_ids,
        resolver=_fake_resolver(tree),
    )
    sc._check_imports_hosted(
        "service.tvos.pythonfix", fixes, catalog_ids, resolver=_fake_resolver(tree)
    )
    # a leaf four hops down that the catalog does not serve fails the ROOT
    for leaf in ("script.module.urllib3", "script.module.idna"):
        for aid in ("skin.estuary.pov", "skin.estuary.plusplus"):
            with pytest.raises(sc.FetchError, match=leaf):
                sc._check_imports_hosted(
                    aid,
                    skin_xml(aid),
                    catalog_ids - {leaf},
                    resolver=_fake_resolver(tree),
                )
        with pytest.raises(sc.FetchError, match=leaf):
            sc._check_imports_hosted(
                "service.tvos.pythonfix",
                fixes,
                catalog_ids - {leaf},
                resolver=_fake_resolver(tree),
            )
    # a hop whose own zip cannot be resolved fails the root, named
    def broken(aid):
        if aid == "script.module.requests":
            raise sc.FetchError("zip 404")
        return _fake_resolver(tree)(aid)

    with pytest.raises(sc.FetchError, match="script.module.requests could not"):
        sc._check_imports_hosted("skin.estuary.pov", skin, catalog_ids, resolver=broken)
    # and without a resolver nothing is walked past the first hop: the walk
    # is only a gate when the build supplies BuildContext.addon_xml_for
    sc._check_imports_hosted(
        "skin.estuary.pov", skin, catalog_ids - {"script.module.urllib3"}
    )


def test_real_catalog_resolver_covers_every_official_module():
    """BuildContext.addon_xml_for answers for exactly the build-resolved ids
    of the REAL catalog (resolving is not attempted here: no network), so the
    build-time walk cannot skip one of the eleven as a leaf."""
    entries = sc.load_catalog()
    ctx = sc.BuildContext(entries, fetcher=None, warnings=[])
    for aid in FLEET_INSTALLS | OFFICIAL_MODULES:
        assert sc.metadata_resolved_at_build(ctx.entries[aid]), aid
    for aid in ("repository.tony7bones", "repository.loop", "repository.709"):
        assert ctx.addon_xml_for(aid) is None, aid
    assert ctx.addon_xml_for("not.in.catalog") is None


# --------------------------------------------------------------------------- #
# the exemption is itself gated
#
# An exclusion set added to make a red build green is one edit away from being
# the place a real missing dependency goes to hide. These four tests are what
# stop OFFICIAL_LIBRARY becoming that place.
# --------------------------------------------------------------------------- #
def test_official_library_holds_nothing_of_ours():
    """It may only ever name add-ons Kodi ships, never one this repo delivers.

    Three independent proofs that an id is not ours: it is not a build-resolved
    id, we carry no hosted mirror of it, and our catalog does not advertise it. Any of
    the three failing means this repo still ships the thing, and whether this
    repo ships a dependency is precisely what the closure gate measures.
    """
    hosted = {d for d in os.listdir(HOSTED) if os.path.isdir(os.path.join(HOSTED, d))}
    advertised = _repo_json_ids()
    for aid in OFFICIAL_LIBRARY:
        assert aid not in FLEET_INSTALLS | OFFICIAL_MODULES, (
            f"{aid} is served by this repo, not Kodi's library"
        )
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
