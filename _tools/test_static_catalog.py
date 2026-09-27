"""Tests for static_catalog.py - the /static/ Kodi repo builder.

Carries forward the engine's propagation contracts at build time (see
test_update_propagation.py for the engine originals, retired at Phase 6):
md5 <-> document invariant, per-entry fault isolation with last-good
fallback, never-empty catalog, plus the new build-time gates (shrink guard,
90MB ceiling, determinism). No network: all fetches go through a fake.
"""

import gzip
import hashlib
import io
import json
import os
import sys
import urllib.error
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest

sys.path.insert(0, str(Path(__file__).parent))
import static_catalog as sc

OWN = "https://raw.githubusercontent.com/{username}/{repository}/{ref}"
BASE_URL = "https://example.test"
LATEST_HTML = "https://github.com/moquette/src/releases/latest"
LATEST_API = "https://api.github.com/repos/moquette/src/releases/latest"
INDEX_URL = "https://up.example/repo/packages/addons.xml"
RELEASE_ZIP = (
    "https://github.com/moquette/src/releases/download/v{v}/release.addon-{v}.zip"
)
INDEXED_ZIP = "https://up.example/repo/indexed.addon/indexed.addon-{v}.zip"
# A source repo that ships SEVERAL add-ons: per-add-on tag namespace.
RELEASES_LIST = "https://api.github.com/repos/moquette/multi/releases?per_page=100"
NS_ZIP = "https://github.com/moquette/multi/releases/download/ns.addon-v{v}/ns.addon-{v}.zip"
NS_ASSET_API = "https://api.github.com/repos/moquette/multi/releases/assets/{v}"


# The five entries resolved from OUR sources of truth (four GitHub release
# namespaces and POV's upstream index) ...
OWNED_BUILD_RESOLVED = {
    "script.ezmaintenanceplusplus",
    "plugin.video.pov",
    "skin.estuary.plusplus",
    "service.tvos.pythonfix",
}
# ... and the eleven official-library modules resolved from the official Kodi
# repository's own index since 2026-09-26 (hybrid + upstream_index, no
# committed copy). Not ours: served only because Kodi resolves a hard
# dependency solely from the repository the add-on is installed FROM.
OFFICIAL_INDEX = "https://mirrors.kodi.tv/addons/piers/addons.xml.gz"
OFFICIAL_ZIP = "https://mirrors.kodi.tv/addons/piers/{id}/{id}-{version}.zip"
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


def _index_xml(*pairs: tuple[str, str]) -> bytes:
    body = "".join(f'<addon id="{i}" version="{v}"/>' for i, v in pairs)
    return f"<addons>{body}</addons>".encode()


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
class FakeFetcher:
    """Duck-typed sc.Fetcher backed by a dict; raises FetchError on misses.

    ``fetch`` is the cached path and records into ``calls``; ``_download``,
    ``get_json`` and ``redirect_location`` are the uncached lookups the
    version resolution uses and record into ``download_calls``, so a test can
    assert a lookup never went through the cache."""

    def __init__(self, urls: dict | None = None, redirects: dict | None = None):
        self.urls = dict(urls or {})
        self.redirects = dict(redirects or {})
        self.calls: list[str] = []
        self.download_calls: list[str] = []
        self.fetch_headers: dict[str, dict | None] = {}
        self.fetch_expectations: dict[str, tuple | None] = {}

    def fetch(
        self,
        url,
        mutable=False,
        tolerate_missing=False,
        expect_zip=False,
        headers=None,
        expect_addon=None,
    ):
        self.calls.append(url)
        self.fetch_headers[url] = headers
        self.fetch_expectations[url] = expect_addon
        if url in self.urls:
            return self.urls[url]
        if tolerate_missing:
            return None
        raise sc.FetchError(f"{url}: not in fake")

    def _download(self, url, headers=None):
        self.download_calls.append(url)
        if url in self.urls:
            v = self.urls[url]
            if isinstance(v, Exception):
                raise v
            return v
        raise sc.FetchError(f"{url}: not in fake")

    def get_json(self, url, headers=None):
        return json.loads(self._download(url, headers))

    def redirect_location(self, url):
        self.download_calls.append(url)
        if url in self.redirects:
            return self.redirects[url]
        raise sc.FetchError(f"{url}: no redirect in fake")


class SplitFetcher(FakeFetcher):
    """Models the F1 bug surface: fetch() serves the (possibly stale) CACHE,
    _download() serves the LIVE site. The fallback path must only ever touch
    the latter."""

    def __init__(
        self,
        cached: dict | None = None,
        live: dict | None = None,
        redirects: dict | None = None,
    ):
        super().__init__(cached, redirects)
        self.live = dict(live or {})

    def _download(self, url, headers=None):
        self.download_calls.append(url)
        if url in self.live:
            return self.live[url]
        raise sc.FetchError(f"{url}: not live")


def _zip_bytes(
    addon_id: str,
    version: str,
    top_dir: str | None = None,
    extra: dict | None = None,
) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(
            f"{top_dir or addon_id}/addon.xml",
            f'<addon id="{addon_id}" version="{version}"/>',
        )
        for rel, data in (extra or {}).items():
            zf.writestr(f"{top_dir or addon_id}/{rel}", data)
    return buf.getvalue()


def _addon_xml(addon_id: str, version: str) -> str:
    return (
        f'<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<addon id="{addon_id}" name="T" version="{version}" provider-name="t">\n'
        f'  <extension point="xbmc.addon.metadata"><summary>x</summary>'
        f"</extension>\n</addon>\n"
    )


def _entry(addon_id: str, kind: str) -> dict:
    e = {
        "id": addon_id,
        "username": "tony7bones",
        "repository": "tony7bones.github.io",
        "branch": "main",
    }
    if kind == "first-party":
        e["asset_prefix"] = OWN + "/addons/{id}/"
        e["assets"] = {"zip": OWN + "/addons/{id}/{id}-{version}.zip"}
    elif kind == "hosted":
        e["asset_prefix"] = OWN + "/addons/hosted/{id}/"
        e["assets"] = {"zip": OWN + "/addons/hosted/{id}/{id}-{version}.zip"}
    elif kind == "hosted-unversioned":
        e["asset_prefix"] = OWN + "/addons/hosted/{id}/"
        e["assets"] = {"zip": OWN + "/addons/hosted/{id}/{id}.zip"}
    elif kind == "hybrid":
        e["asset_prefix"] = OWN + "/addons/hosted/{id}/"
        e["assets"] = {
            "zip": "https://raw.githubusercontent.com/up/stream/master/{id}-{version}.zip"
        }
    elif kind == "release-asset":
        e["asset_prefix"] = OWN + "/addons/hosted/{id}/"
        e["assets"] = {
            "zip": "https://github.com/moquette/src/releases/download/v{version}/{id}-{version}.zip"
        }
    elif kind == "release-asset-namespaced":
        e["asset_prefix"] = OWN + "/addons/hosted/{id}/"
        e["assets"] = {
            "zip": "https://github.com/moquette/multi/releases/download/{id}-v{version}/{id}-{version}.zip"
        }
    elif kind == "indexed":
        # hybrid + upstream_index: version from the upstream addons.xml
        e["asset_prefix"] = OWN + "/addons/hosted/{id}/"
        e["assets"] = {"zip": "https://up.example/repo/{id}/{id}-{version}.zip"}
        e["upstream_index"] = "https://up.example/repo/packages/addons.xml"
    elif kind == "streamed":
        e["username"], e["repository"] = "up", "stream"
        e["asset_prefix"] = (
            "https://raw.githubusercontent.com/{username}/{repository}/{ref}/zips/{id}/"
        )
        e["assets"] = {
            "zip": "https://raw.githubusercontent.com/{username}/{repository}/{ref}/zips/{id}/{id}-{version}.zip"
        }
    return e


@pytest.fixture
def fake_repo(tmp_path):
    """A minimal repo tree with one entry of every class + its manifest."""
    root = tmp_path / "repo"
    entries = []

    fp = root / "addons" / "first.party"
    fp.mkdir(parents=True)
    (fp / "addon.xml").write_text(_addon_xml("first.party", "1.0.0"))
    (fp / "first.party-1.0.0.zip").write_bytes(_zip_bytes("first.party", "1.0.0"))
    (fp / "icon.png").write_bytes(b"PNG-FP")
    entries.append(_entry("first.party", "first-party"))

    for hid, kind, zname in [
        ("hosted.addon", "hosted", "hosted.addon-2.0.0.zip"),
        ("unversioned.addon", "hosted-unversioned", "unversioned.addon.zip"),
        ("hybrid.addon", "hybrid", None),
    ]:
        d = root / "addons" / "hosted" / hid
        d.mkdir(parents=True)
        (d / "addon.xml").write_text(_addon_xml(hid, "2.0.0"))
        (d / "icon.png").write_bytes(b"PNG-" + hid.encode())
        if zname:
            (d / zname).write_bytes(_zip_bytes(hid, "2.0.0"))
        entries.append(_entry(hid, kind))

    # The two build-resolved kinds have NO addons/hosted/<id>/ at all.
    entries.append(_entry("release.addon", "release-asset"))
    entries.append(_entry("indexed.addon", "indexed"))
    entries.append(_entry("streamed.addon", "streamed"))

    manifest_path = root / "repository.json"
    manifest_path.write_text(json.dumps(entries))

    fetcher = FakeFetcher(
        {
            "https://raw.githubusercontent.com/up/stream/master/hybrid.addon-2.0.0.zip": _zip_bytes(
                "hybrid.addon", "2.0.0"
            ),
            RELEASE_ZIP.format(v="2.0.0"): _zip_bytes("release.addon", "2.0.0"),
            INDEX_URL: _index_xml(("other.addon", "9.9"), ("indexed.addon", "2.0.0")),
            INDEXED_ZIP.format(v="2.0.0"): _zip_bytes("indexed.addon", "2.0.0"),
            "https://raw.githubusercontent.com/up/stream/main/zips/streamed.addon/addon.xml": _addon_xml(
                "streamed.addon", "3.0.0"
            ).encode(),
            "https://raw.githubusercontent.com/up/stream/main/zips/streamed.addon/streamed.addon-3.0.0.zip": _zip_bytes(
                "streamed.addon", "3.0.0"
            ),
            "https://raw.githubusercontent.com/up/stream/main/zips/streamed.addon/icon.png": b"PNG-ST",
        },
        redirects={LATEST_HTML: "https://github.com/moquette/src/releases/tag/v2.0.0"},
    )
    return root, manifest_path, fetcher


@pytest.fixture(autouse=True)
def _no_token(monkeypatch):
    """Default: no token, so release-asset resolves via the redirect. Tests
    of the API path set GH_TOKEN themselves."""
    monkeypatch.delenv("GH_TOKEN", raising=False)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)


def _build(fake_repo, out, **kw):
    root, manifest_path, fetcher = fake_repo
    kw.setdefault("fetcher", fetcher)
    kw.setdefault("base_url", BASE_URL)
    return sc.build(
        str(out),
        repo_json=str(manifest_path),
        repo_root=str(root),
        **kw,
    )


# ---------------------------------------------------------------------------
# classification
# ---------------------------------------------------------------------------
def test_classify_all_five_kinds():
    assert sc.classify(_entry("a", "first-party")) == sc.KIND_FIRST_PARTY
    assert sc.classify(_entry("a", "hosted")) == sc.KIND_HOSTED
    assert sc.classify(_entry("a", "hosted-unversioned")) == sc.KIND_HOSTED
    assert sc.classify(_entry("a", "hybrid")) == sc.KIND_HYBRID
    assert sc.classify(_entry("a", "release-asset")) == sc.KIND_RELEASE_ASSET
    assert (
        sc.classify(_entry("a", "release-asset-namespaced")) == sc.KIND_RELEASE_ASSET
    )
    assert sc.classify(_entry("a", "indexed")) == sc.KIND_HYBRID
    assert sc.classify(_entry("a", "streamed")) == sc.KIND_STREAMED


def test_release_asset_shape_parses_owner_repo_and_tag_namespace():
    """Both tag shapes are release-asset; the tag prefix is what tells the
    resolver whether releases/latest is the answer (one add-on per repo) or
    the namespace listing is (several add-ons per repo)."""
    plain = sc._RELEASE_ASSET_RE.match(_entry("a", "release-asset")["assets"]["zip"])
    assert (plain.group("owner"), plain.group("repo")) == ("moquette", "src")
    assert plain.group("tag_prefix") == ""
    ns = sc._RELEASE_ASSET_RE.match(
        _entry("a", "release-asset-namespaced")["assets"]["zip"]
    )
    assert (ns.group("owner"), ns.group("repo")) == ("moquette", "multi")
    assert ns.group("tag_prefix") == "{id}-"
    assert sc._subst(ns.group("tag_prefix"), _entry("skin.x", "release-asset")) == (
        "skin.x-"
    )
    # a tag segment that is neither shape is not a release asset
    other = dict(_entry("a", "release-asset"))
    other["assets"] = {
        "zip": "https://github.com/o/r/releases/download/release-{version}/{id}.zip"
    }
    assert sc._RELEASE_ASSET_RE.match(other["assets"]["zip"]) is None
    assert sc.classify(other) != sc.KIND_RELEASE_ASSET


def test_metadata_resolved_at_build_is_exactly_the_two_upstream_truths():
    assert sc.metadata_resolved_at_build(_entry("a", "release-asset"))
    assert sc.metadata_resolved_at_build(_entry("a", "release-asset-namespaced"))
    assert sc.metadata_resolved_at_build(_entry("a", "indexed"))
    for kind in ("first-party", "hosted", "hosted-unversioned", "hybrid", "streamed"):
        assert not sc.metadata_resolved_at_build(_entry("a", kind)), kind


def test_real_catalog_build_resolved_entries_have_no_committed_metadata():
    """The owner's rule of 2026-09-26: THERE MUST BE NO MIRROR VERSION TO BE
    WRONG. The two entries whose version rotted by hand are resolved upstream
    at build time, and the directories that held the hand copy are gone. The
    skin joined them the same day: it releases from the skin repo's CI into
    the ``<id>-v<version>`` tag namespace of moquette/kodi-estuarypp
    (``skin.estuary.plusplus-v`` since the rename, ``skin.estuary.pov-v`` for
    the old id while boxes migrate) and nothing of it is committed here."""
    resolved = {e["id"] for e in sc.load_catalog() if sc.metadata_resolved_at_build(e)}
    assert resolved == OWNED_BUILD_RESOLVED | OFFICIAL_MODULES
    for aid in resolved:
        assert not os.path.exists(os.path.join(sc.REPO_ROOT, "addons", "hosted", aid))


def test_classify_the_real_manifest_covers_all_entries():
    """The REAL catalog.json: every entry classifies, with the known per-class
    counts (update deliberately when the catalog changes).

    28 entries, and the arithmetic behind that number, newest first:

      +0  2026-09-26, the ELEVEN official-library modules (autocompletion
          plugin and module, image.resource.select, certifi, chardet, idna,
          requests, simplecache, simpleeval, unidecode, urllib3) switched
          from hosted to HYBRID with upstream_index: version from the
          official Kodi repository's Piers index (addons.xml.gz, 13MB
          unpacked, fetched once per build), zip from mirrors.kodi.tv, and
          their addons/hosted/<id>/ directories are DELETED. The committed
          copies were NOT stale (all eleven matched the official versions
          when measured that day); the switch is so they cannot rot. The
          official zips' bytes differ from the old committed copies at the
          same version (packaging), which changes nothing for a box already
          at that version, since Kodi installs by id and version.
      -4  2026-08-31, the Estuary 7/8 DECOMMISSION, owner order ("we're only
          supporting EPOV"). skin.estuary7 (release-asset; its zips stay on the
          archived moquette/kodi-estuary7 Releases), skin.estuary8,
          script.estuary8.shortcuts and plugin.video.estuary8.search (hosted;
          their only published copies, which survive in this repo's git
          history) are all REMOVED. Every running box is on POV; atv2's boxed
          Kodi 21 copy of estuary7 is offline and unaffected. This also ended
          the estuary7-release repository_dispatch in pages.yml and the
          Releases-API polling of kodi-estuary7 in
          check_hosted_release_sync.py.
      +1  2026-08-29, service.tvos.pythonfix ADDED, hosted. OURS, and it exists
          nowhere else, so an unhosted entry is not a slow 404 on an off-grid box
          but an install that cannot succeed anywhere at all. It carries the
          _scproxy shim that skin.estuary.pov's own boot service wrote in 1.2.2
          through 1.2.5, moved out into a separate add-on because a skin is
          installed AFTER its dependencies and therefore structurally cannot
          repair them: MEASURED on atv1, plugin.video.pov was installed at
          07:42:31.754 and had already died on the missing module at
          07:42:32.991, 117 ms before the skin reached disk.
          NOTE, and this changed twice within two days of being added:
          skin.estuary.pov 1.2.7 declared a hard <import> on it, 1.2.8 REMOVED
          that import, and 1.3.0 handed it the Siri remote keymap as well and
          deleted the skin's boot service outright. No skin depends on it and no
          skin carries any tvOS code. It is USER-INSTALLED, by an Apple TV owner,
          from this repository's own listing, which makes hosting it more load
          bearing rather than less: a dependency has a parent that can drag it
          in, and this has nothing but this catalog entry. It is also a root of
          its own in test_closure.py as of the same day, because reachability
          through the skin was the only thing gating its subtree and that is
          exactly what 1.2.8 removed.
      +1  2026-08-29, plugin.program.autocompletion ADDED, hosted. Not ours: a
          verbatim mirror of the official build, pulled by the since-deleted
          mirror_closure.py (gone 2026-09-26 with the committed copies),
          version 2.1.2 on both the omega and piers mirrors. skin.estuary.pov
          1.2.4 declares a hard <import> on it so the virtual keyboard's
          suggestion panel has a content provider, and by the SAME rule already
          measured for plugin.video.pov two entries down, a hard dependency
          resolves only from the repository the add-on is installed FROM.
          Leaving it to repository.xbmc.org would therefore have failed every
          1.2.4 skin update with "failed to find dependency", not just the
          off-grid ones. test_closure.py caught it before the push. Its own
          dependency script.module.autocompletion (>= 2.0.5) was already hosted
          here at 2.1.1, so the closure closes with nothing else added.
      +1  2026-08-27, plugin.video.pov ADDED, HYBRID. It is not ours and its
          bytes are not committed here: only its addon.xml is, and the build
          fetches the zip from the upstream Pages host at
          kodiyashimaru.github.io and republishes it under our own /static/.
          It is here because skin.estuary.pov declares a hard <import> on it,
          and MEASURED on a Kodi 22 bench: Kodi resolves a hard dependency only
          from the repository the add-on is being installed FROM. With POV
          reachable only through repository.kodifitzwell the skin install failed
          with "failed to find dependency plugin.video.pov" three times over,
          even with kodifitzwell installed, enabled, indexed, and offering POV
          6.08.15 through Addons.GetAddons. Serving POV ourselves is what makes
          the dependency resolvable at all.

          HYBRID rather than STREAMED, and that is forced, not chosen. A
          streamed entry fetches <asset_prefix>/addon.xml from upstream, and
          kodiyashimaru publishes no per-addon addon.xml: /repo/<id>/addon.xml,
          /repo/packages/<id>/addon.xml and /repo/zips/<id>/addon.xml all 404,
          and only /repo/packages/addons.xml (the index) and the zip exist.
          Until 2026-09-26 the metadata came from a committed copy whose
          version was typed by hand, and it rotted: 6.08.15 against an
          upstream 6.09.06, zip 404, POV DROPPED from the build for days, the
          skin uninstallable. Since then the entry carries "upstream_index"
          (that packages/addons.xml), the build reads the version from it on
          every run and takes addon.xml out of the zip, and there is no
          committed copy at all. repository.kodifitzwell is the same kind of
          Pages host but keeps its committed addon.xml (no upstream_index).
      +1  2026-09-26, skin.estuary.plusplus ADDED, release-asset (29 entries,
          release-asset 4). The skin renamed to Estuary++ under a NEW id
          (owner decision: whatever we touch keeps its name with ++ appended),
          first version 1.5.0, source repo renamed to
          moquette/kodi-estuarypp with the same {id}-v{version} tag
          namespace. skin.estuary.pov STAYS for the transition: a new id is a
          new add-on to Kodi, so EZM++ migrates each box (install the new id,
          carry settings, switch, drop the old) and needs both served until
          every box is over; the old entry is retired in stage E of the rename
          plan with allow_catalog_shrink. Both templates (and
          service.tvos.pythonfix's) name the new repo: GitHub redirects the
          old name, but nothing here relies on that.
      +1  2026-08-27, skin.estuary.pov ADDED, hosted. Ours: stock Kodi Estuary
          4.1.0 reworked so the Movies and TV shows home tabs are driven by
          plugin.video.pov instead of the local library. Hosted rather than
          release-asset for the same reason as Estuary 8 and one stronger: its
          source repo moquette/kodi-estuary-pov did not exist on GitHub at all
          when it was added (measured with git ls-remote, "Repository not
          found"), so a release-asset pointer would have had no latest release
          to resolve and the entry would have fallen back or dropped. At 2.4MB the
          committed zip is a ninth of Estuary 8's, so the cost of self-hosting
          is small and the install stays available off-grid.
          SWITCHED to release-asset 2026-09-26 (hosted 16, release-asset 2
          from then on): estuary-pov CI now publishes every version bump as
          the GitHub release skin.estuary.pov-v<version> with the zip attached
          and dispatches this hub, and addons/hosted/skin.estuary.pov/ is gone.
          The tag is NAMESPACED because that repo also ships
          service.tvos.pythonfix and a repo has one releases/latest; the build
          lists the releases and takes the newest skin.estuary.pov-v tag.
          service.tvos.pythonfix stays hosted here until its own switch.
      +1  2026-08-03, plugin.video.estuary8.search ADDED, hosted. It is the
          Estuary 8 streaming-search result filter and a declared dependency of
          skin.estuary8, so hosting it here is what lets Kodi install it from
          this repo alongside the skin. Ours, not a mirror of anything external,
          and hosted for the same reason the two Estuary 8 entries below are:
          there is no GitHub Release to point at.
      +2  2026-07-31, the Estuary 8 launch. script.estuary8.shortcuts and
          skin.estuary8 are both ADDED, both hosted, on the owner's explicit
          instruction. Neither is a mirror of anything external: the first is
          our fork of a menu add-on carried under our OWN add-on id, the second
          is our skin. Hosting them is the opposite of the prohibition below
          rather than an exception to it, and hosting BOTH is what makes an
          install one step instead of a side-loaded zip followed by a skin.
      -1  2026-07-29, script.skinshortcuts dropped with its hosted mirror. The
          root CLAUDE.md forbids hosting it and Kodi serves it from the official
          library, which every box already has.
      -n  earlier: estuary7 1.0.46 dropped PVR artwork + outline icons, and the
          engine-era setup machinery (script.tony7bones.bootstrap +
          script.module.tony7bones) and the dead modv2plus were nuked.

    skin.estuary8 was HOSTED, not release-asset like skin.estuary7, and that
    difference was deliberate rather than an oversight. A release-asset entry
    resolves its version and zip from the source repo's LATEST GitHub Release
    at build time (since 2026-09-26; before that a hand-maintained addon.xml
    plus a freshness gate that hard-failed on a broken pointer): declare one
    before any release exists and the entry has nothing to resolve. Hosting the
    zip in this repo also kept the whole Estuary 8 closure installable
    off-grid, which is exactly what the skinshortcuts purge above cost
    Estuary 7. The same reasoning holds for skin.estuary.pov today.

    script.ezmaintenanceplusplus, skin.estuary.plusplus, skin.estuary.pov and
    service.tvos.pythonfix are the four release-asset entries, and since
    2026-09-26 none has an addons/hosted/ directory: version from the latest
    release of moquette/kodi-ezmpp (releases/latest) and from the newest
    ``<id>-v`` tag of moquette/kodi-estuarypp, addon.xml and art from
    that release's zip.
    """
    entries = sc.load_catalog()
    kinds = {}
    for e in entries:
        kinds.setdefault(sc.classify(e), []).append(e["id"])
    assert len(entries) == 28
    assert kinds[sc.KIND_FIRST_PARTY] == ["repository.tony7bones"]
    # hosted 15 -> 4 on 2026-09-26: the eleven official modules left for the
    # official index. What remains hosted is third-party repository installers
    # only (unversioned zips with no index of their own).
    assert sorted(kinds[sc.KIND_HOSTED]) == [
        "repository.Magnetic",
        "repository.kodinerds",
        "repository.loop",
        "repository.redwizard",
    ]
    assert len(kinds[sc.KIND_HYBRID]) == 15
    assert len(kinds[sc.KIND_STREAMED]) == 5
    assert len(kinds[sc.KIND_RELEASE_ASSET]) == 3
    assert "skin.estuary.plusplus" in kinds[sc.KIND_RELEASE_ASSET]
    assert "service.tvos.pythonfix" in kinds[sc.KIND_RELEASE_ASSET]
    assert "script.ezmaintenanceplusplus" in kinds[sc.KIND_RELEASE_ASSET]
    assert "plugin.video.pov" in kinds[sc.KIND_HYBRID]
    by_id = {e["id"]: e for e in entries}
    for aid in OFFICIAL_MODULES:
        e = by_id[aid]
        assert sc.classify(e) == sc.KIND_HYBRID, aid
        assert e["upstream_index"] == OFFICIAL_INDEX, aid
        assert e["assets"]["zip"] == OFFICIAL_ZIP, aid
        assert "/addons/hosted/" in e["asset_prefix"], aid
    ids = {e["id"] for e in entries}
    for gone in (
        "script.module.pvr.artwork",
        "resource.images.weathericons.outline-hd",
        "script.tony7bones.modv2plus",
        "script.tony7bones.bootstrap",
        "script.module.tony7bones",
        "script.skinshortcuts",
        "skin.estuary7",
        "skin.estuary8",
        "script.estuary8.shortcuts",
        "plugin.video.estuary8.search",
    ):
        assert gone not in ids


def test_no_catalog_entry_points_at_a_deleted_hosted_mirror():
    """A dangling addons/hosted/<id>/ reference is not inert - it republishes.

    When the primary 404s, resolve_all falls back to the last-good copy already
    on the live site and marks the entry stale: a warning, not a failure. So a
    catalog entry left behind after its mirror is deleted keeps serving that
    mirror from /static/ forever, with a green build. That is how the
    script.skinshortcuts 2.0.3 zip would have survived the 2026-07-29 purge
    ordered under the root CLAUDE.md hard rule. Deleting a hosted mirror means
    deleting its catalog entry in the same change.
    """
    hosted_dir = os.path.join(sc.REPO_ROOT, "addons", "hosted")
    hosted = {
        d for d in os.listdir(hosted_dir) if os.path.isdir(os.path.join(hosted_dir, d))
    }
    dangling = sorted(
        e["id"]
        for e in sc.load_catalog()
        if "/addons/hosted/" in json.dumps(e)
        and e["id"] not in hosted
        and not sc.metadata_resolved_at_build(e)
    )
    assert not dangling, (
        f"catalog.json points at addons/hosted/ mirrors that do not exist: "
        f"{dangling} - remove the entry, or restore the mirror if it is ours"
    )


# ---------------------------------------------------------------------------
# happy path + md5 invariant + determinism
# ---------------------------------------------------------------------------
def test_build_materializes_every_class(fake_repo, tmp_path):
    out = tmp_path / "static"
    manifest = _build(fake_repo, out)
    assert manifest["count"] == 7
    ids = set(manifest["entries"])
    assert ids == {
        "first.party",
        "hosted.addon",
        "unversioned.addon",
        "hybrid.addon",
        "release.addon",
        "indexed.addon",
        "streamed.addon",
    }
    for entry_id, info in manifest["entries"].items():
        zip_path = out / info["zip"]
        assert zip_path.is_file(), entry_id
        assert hashlib.sha256(zip_path.read_bytes()).hexdigest() == info["zip_sha256"]
        assert (out / entry_id / "addon.xml").is_file()
        assert not info["stale"]
    # the unversioned hosted zip landed under its VERSIONED datadir name
    assert manifest["entries"]["unversioned.addon"]["zip"].endswith(
        "unversioned.addon-2.0.0.zip"
    )
    # streamed art arrived
    assert (out / "streamed.addon" / "icon.png").read_bytes() == b"PNG-ST"


def test_addons_xml_md5_is_digest_of_the_written_bytes(fake_repo, tmp_path):
    out = tmp_path / "static"
    _build(fake_repo, out)
    data = (out / "addons.xml").read_bytes()
    assert (out / "addons.xml.md5").read_text() == hashlib.md5(data).hexdigest()
    ids = [el.get("id") for el in ET.fromstring(data)]
    assert ids == sorted(ids), "addons.xml entries must be id-sorted (determinism)"


def test_double_build_is_byte_identical(fake_repo, tmp_path):
    out1, out2 = tmp_path / "s1", tmp_path / "s2"
    _build(fake_repo, out1)
    _build(fake_repo, out2)
    files1 = sorted(p.relative_to(out1) for p in out1.rglob("*") if p.is_file())
    files2 = sorted(p.relative_to(out2) for p in out2.rglob("*") if p.is_file())
    assert files1 == files2
    for rel in files1:
        assert (out1 / rel).read_bytes() == (out2 / rel).read_bytes(), rel


# ---------------------------------------------------------------------------
# fault policy
# ---------------------------------------------------------------------------
def _kill_streamed(fake_repo):
    root, manifest_path, fetcher = fake_repo
    for url in list(fetcher.urls):
        if "streamed.addon" in url:
            del fetcher.urls[url]


def test_one_dead_upstream_falls_back_to_last_good(fake_repo, tmp_path):
    _kill_streamed(fake_repo)
    root, manifest_path, fetcher = fake_repo
    baseline = {"entries": {"streamed.addon": {"version": "2.9.0"}}}
    live = f"{BASE_URL}/static/streamed.addon/"
    fetcher.urls[live + "addon.xml"] = _addon_xml("streamed.addon", "2.9.0").encode()
    fetcher.urls[live + "streamed.addon-2.9.0.zip"] = _zip_bytes(
        "streamed.addon", "2.9.0"
    )
    manifest = _build(fake_repo, tmp_path / "static", baseline=baseline)
    info = manifest["entries"]["streamed.addon"]
    assert info["stale"] is True
    assert info["version"] == "2.9.0"
    # the other six resolved fresh - fault isolation
    assert manifest["count"] == 7
    assert sum(e["stale"] for e in manifest["entries"].values()) == 1


def test_dead_upstream_without_baseline_is_dropped_with_survivors(fake_repo, tmp_path):
    _kill_streamed(fake_repo)
    manifest = _build(fake_repo, tmp_path / "static", baseline=None)
    assert manifest["count"] == 6
    assert "streamed.addon" not in manifest["entries"]


def test_shrink_vs_baseline_fails_without_the_flag(fake_repo, tmp_path):
    _kill_streamed(fake_repo)
    baseline = {"entries": {"streamed.addon": {"version": "2.9.0"}}}
    # baseline knows the entry but the live fallback copies are gone too
    with pytest.raises(sc.BuildError, match="LOSE entries"):
        _build(fake_repo, tmp_path / "static", baseline=baseline)


def test_shrink_is_allowed_by_a_recorded_retirement(fake_repo, tmp_path):
    """A retirement recorded in _tools/retired.json lets an id leave on an
    ordinary push; an id missing without a record still fails."""
    _kill_streamed(fake_repo)
    baseline = {"entries": {"streamed.addon": {"version": "2.9.0"}}}
    root = Path(fake_repo[0])
    (root / "_tools").mkdir(exist_ok=True)
    (root / "_tools" / "retired.json").write_text(
        json.dumps({"streamed.addon": "2026-09-26 test retirement"})
    )
    manifest = _build(fake_repo, tmp_path / "static", baseline=baseline)
    assert manifest["count"] == 6


def test_shrink_is_allowed_only_explicitly(fake_repo, tmp_path):
    _kill_streamed(fake_repo)
    baseline = {"entries": {"streamed.addon": {"version": "2.9.0"}}}
    manifest = _build(
        fake_repo, tmp_path / "static", baseline=baseline, allow_shrink=True
    )
    assert manifest["count"] == 6


def test_total_loss_refuses_to_publish_an_empty_catalog(tmp_path):
    manifest_path = tmp_path / "repository.json"
    manifest_path.write_text(json.dumps([_entry("streamed.addon", "streamed")]))
    with pytest.raises(sc.BuildError, match="empty catalog"):
        sc.build(
            str(tmp_path / "static"),
            fetcher=FakeFetcher(),
            repo_json=str(manifest_path),
            repo_root=str(tmp_path),
            base_url=BASE_URL,
        )


def test_missing_first_party_zip_is_a_hard_build_failure(fake_repo, tmp_path):
    root, _, _ = fake_repo
    (root / "addons" / "first.party" / "first.party-1.0.0.zip").unlink()
    with pytest.raises(sc.BuildError, match="first-party zip missing"):
        _build(fake_repo, tmp_path / "static")


def test_oversized_zip_fails_the_whole_build(fake_repo, tmp_path, monkeypatch):
    monkeypatch.setattr(sc, "MAX_FILE_BYTES", 10)
    with pytest.raises(sc.BuildError, match="90MB gate"):
        _build(fake_repo, tmp_path / "static")


def test_foreign_top_dir_zip_is_served_verbatim_with_a_warning(
    fake_repo, tmp_path, capsys
):
    root, manifest_path, fetcher = fake_repo
    url = "https://raw.githubusercontent.com/up/stream/master/hybrid.addon-2.0.0.zip"
    fetcher.urls[url] = _zip_bytes("hybrid.addon", "2.0.0", top_dir="other.dir")
    manifest = _build(fake_repo, tmp_path / "static")
    assert "hybrid.addon" in manifest["entries"]
    assert "top-level dir" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# review findings: F1 (fallback freshness + version skew), F3 (baseline),
# F4 (corrupt zips fall back per entry), F5 (internal id/version cross-check)
# ---------------------------------------------------------------------------
def test_fallback_never_reads_the_cache(fake_repo, tmp_path):
    """F1: a stale cached copy of the live addon.xml must be ignored - the
    fallback fetches fresh via _download only."""
    root, manifest_path, old = fake_repo
    _kill_streamed(fake_repo)
    live = f"{BASE_URL}/static/streamed.addon/"
    fetcher = SplitFetcher(
        cached={
            **old.urls,
            # poisoned cache: an ancient addon.xml under the live URL key
            live + "addon.xml": _addon_xml("streamed.addon", "1.0.0").encode(),
        },
        live={
            live + "addon.xml": _addon_xml("streamed.addon", "2.9.0").encode(),
            live + "streamed.addon-2.9.0.zip": _zip_bytes("streamed.addon", "2.9.0"),
        },
    )
    baseline = {"entries": {"streamed.addon": {"version": "2.9.0"}}}
    manifest = _build(fake_repo, tmp_path / "s", fetcher=fetcher, baseline=baseline)
    info = manifest["entries"]["streamed.addon"]
    assert info["version"] == "2.9.0" and info["stale"] is True
    assert live + "addon.xml" in fetcher.download_calls


def test_fallback_refused_on_live_vs_baseline_version_skew(fake_repo, tmp_path):
    """F1: live addon.xml version != baseline manifest version -> the entry
    is dropped, never published skewed (Kodi would 404 the computed zip)."""
    _kill_streamed(fake_repo)
    live = f"{BASE_URL}/static/streamed.addon/"
    fetcher = SplitFetcher(
        cached=fake_repo[2].urls,
        live={
            live + "addon.xml": _addon_xml("streamed.addon", "2.8.0").encode(),
            live + "streamed.addon-2.9.0.zip": _zip_bytes("streamed.addon", "2.9.0"),
        },
    )
    baseline = {"entries": {"streamed.addon": {"version": "2.9.0"}}}
    manifest = _build(
        fake_repo,
        tmp_path / "s",
        fetcher=fetcher,
        baseline=baseline,
        allow_shrink=True,
    )
    assert "streamed.addon" not in manifest["entries"]


def test_baseline_non_404_failure_fails_the_build(fake_repo, tmp_path):
    """F3: a 503/timeout on the baseline must NOT silently disarm the shrink
    guard - it is a hard failure; --no-baseline is the explicit escape."""
    with pytest.raises(sc.BuildError, match="shrink-guard reference"):
        _build(
            fake_repo,
            tmp_path / "s",
            baseline_url=f"{BASE_URL}/static/catalog.json",
        )


def test_corrupt_primary_zip_falls_back_not_crash(fake_repo, tmp_path):
    """F4: a truncated/HTML-error zip is a per-entry flake -> last-good."""
    root, manifest_path, fetcher = fake_repo
    url = "https://raw.githubusercontent.com/up/stream/master/hybrid.addon-2.0.0.zip"
    fetcher.urls[url] = b"<html>rate limited</html>"
    live = f"{BASE_URL}/static/hybrid.addon/"
    fetcher.urls[live + "addon.xml"] = _addon_xml("hybrid.addon", "1.5.0").encode()
    fetcher.urls[live + "hybrid.addon-1.5.0.zip"] = _zip_bytes("hybrid.addon", "1.5.0")
    baseline = {"entries": {"hybrid.addon": {"version": "1.5.0"}}}
    manifest = _build(fake_repo, tmp_path / "s", baseline=baseline)
    info = manifest["entries"]["hybrid.addon"]
    assert info["stale"] is True and info["version"] == "1.5.0"
    assert manifest["count"] == 7


def test_internal_version_mismatch_is_rejected(fake_repo, tmp_path):
    """F5: a hosted zip whose internal addon.xml disagrees with the advertised
    version would loop Kodi's updater - the entry must not publish."""
    root, manifest_path, fetcher = fake_repo
    d = root / "addons" / "hosted" / "hosted.addon"
    (d / "hosted.addon-2.0.0.zip").write_bytes(
        _zip_bytes("hosted.addon", "1.9.9")  # internal version lies
    )
    manifest = _build(fake_repo, tmp_path / "s", allow_shrink=True)
    assert "hosted.addon" not in manifest["entries"]


def test_first_party_corruption_is_a_hard_failure(fake_repo, tmp_path):
    """First-party bytes are local: corruption = build bug, never fallback."""
    root, _, _ = fake_repo
    (root / "addons" / "first.party" / "first.party-1.0.0.zip").write_bytes(b"junk")
    with pytest.raises(sc.BuildError):
        _build(fake_repo, tmp_path / "s")


def test_missing_art_is_extracted_from_the_zip(fake_repo, tmp_path):
    """Dev-Kodi finding: Kodi fetches <datadir>/<id>/icon.png for the browser
    listing; most hosted metadata dirs never carried it even though the zip
    does. Declared-but-missing art must be materialized out of the zip."""
    root, manifest_path, fetcher = fake_repo
    d = root / "addons" / "hosted" / "hosted.addon"
    (d / "icon.png").unlink()  # metadata dir has NO icon
    (d / "addon.xml").write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<addon id="hosted.addon" name="T" version="2.0.0" provider-name="t">\n'
        '  <extension point="xbmc.addon.metadata">\n'
        "    <assets><icon>resources/icon.png</icon></assets>\n"
        "  </extension>\n</addon>\n"
    )
    (d / "hosted.addon-2.0.0.zip").write_bytes(
        _zip_bytes(
            "hosted.addon", "2.0.0", extra={"resources/icon.png": b"PNG-FROM-ZIP"}
        )
    )
    _build(fake_repo, tmp_path / "s")
    art = tmp_path / "s" / "hosted.addon" / "resources" / "icon.png"
    assert art.read_bytes() == b"PNG-FROM-ZIP"


def test_single_writer_refuses_version_skew(tmp_path):
    """The last line of defense: addons.xml version must equal the zip name's."""
    item = sc.ResolvedEntry(
        id="x.addon",
        kind=sc.KIND_HOSTED,
        version="2.0.0",
        addon_xml=_addon_xml("x.addon", "1.0.0").encode(),
        zip_bytes=_zip_bytes("x.addon", "2.0.0"),
        source_url="test",
    )
    with pytest.raises(sc.BuildError, match="version skew"):
        sc.write_static_tree([item], str(tmp_path / "s"))


# ---------------------------------------------------------------------------
# build-time version resolution (2026-09-26): release-asset from the latest
# GitHub release, hybrid+upstream_index from the upstream addons.xml, the
# addon.xml taken FROM THE ZIP, nothing committed, nothing cached.
# ---------------------------------------------------------------------------
def _release_zip_with_art(version="2.0.0"):
    xml = (
        f'<addon id="release.addon" name="R" version="{version}" provider-name="t">'
        f'<extension point="xbmc.addon.metadata"><assets><icon>icon.png</icon>'
        f"</assets></extension></addon>"
    )
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("release.addon/addon.xml", xml)
        zf.writestr("release.addon/icon.png", b"PNG-FROM-RELEASE")
    return buf.getvalue(), xml.encode()


def test_release_asset_resolves_via_redirect_without_a_token(fake_repo, tmp_path):
    root, manifest_path, fetcher = fake_repo
    zip_bytes, xml = _release_zip_with_art()
    fetcher.urls[RELEASE_ZIP.format(v="2.0.0")] = zip_bytes
    manifest = _build(fake_repo, tmp_path / "s")
    info = manifest["entries"]["release.addon"]
    assert info["version"] == "2.0.0" and info["kind"] == sc.KIND_RELEASE_ASSET
    assert info["source_url"] == RELEASE_ZIP.format(v="2.0.0")
    assert not info["stale"]
    # the lookup went through the uncached path, and only the redirect
    assert LATEST_HTML in fetcher.download_calls
    assert LATEST_API not in fetcher.download_calls
    assert LATEST_HTML not in fetcher.calls
    # metadata and art come FROM THE ZIP
    assert (tmp_path / "s" / "release.addon" / "addon.xml").read_bytes() == xml
    assert (
        tmp_path / "s" / "release.addon" / "icon.png"
    ).read_bytes() == b"PNG-FROM-RELEASE"


def test_release_asset_resolves_via_api_with_a_token(fake_repo, tmp_path, monkeypatch):
    monkeypatch.setenv("GH_TOKEN", "t0k")
    root, manifest_path, fetcher = fake_repo
    fetcher.urls[LATEST_API] = json.dumps({"tag_name": "v2.1.0"}).encode()
    fetcher.urls[RELEASE_ZIP.format(v="2.1.0")] = _zip_bytes("release.addon", "2.1.0")
    manifest = _build(fake_repo, tmp_path / "s")
    assert manifest["entries"]["release.addon"]["version"] == "2.1.0"
    assert LATEST_API in fetcher.download_calls
    assert LATEST_HTML not in fetcher.download_calls, "API answered; no redirect needed"


def test_release_asset_api_failure_falls_back_to_the_redirect(
    fake_repo, tmp_path, monkeypatch
):
    monkeypatch.setenv("GITHUB_TOKEN", "t0k")
    root, manifest_path, fetcher = fake_repo
    fetcher.urls[LATEST_API] = sc.FetchError(f"{LATEST_API}: HTTP 503")
    manifest = _build(fake_repo, tmp_path / "s")
    assert manifest["entries"]["release.addon"]["version"] == "2.0.0"
    assert fetcher.download_calls.index(LATEST_API) < fetcher.download_calls.index(
        LATEST_HTML
    )


def test_release_asset_with_no_release_falls_back_to_last_good(
    fake_repo, tmp_path, monkeypatch
):
    """API 404 = no release at all: a FetchError, so the live copy is served
    stale exactly as for any other dead upstream."""
    monkeypatch.setenv("GH_TOKEN", "t0k")
    root, manifest_path, fetcher = fake_repo
    fetcher.urls[LATEST_API] = _http_404(LATEST_API)
    del fetcher.redirects[LATEST_HTML]
    live = f"{BASE_URL}/static/release.addon/"
    fetcher.urls[live + "addon.xml"] = _addon_xml("release.addon", "1.9.0").encode()
    fetcher.urls[live + "release.addon-1.9.0.zip"] = _zip_bytes(
        "release.addon", "1.9.0"
    )
    baseline = {"entries": {"release.addon": {"version": "1.9.0"}}}
    manifest = _build(fake_repo, tmp_path / "s", baseline=baseline)
    info = manifest["entries"]["release.addon"]
    assert info["stale"] is True and info["version"] == "1.9.0"
    assert manifest["count"] == 7


def test_release_asset_redirect_to_a_non_tag_is_a_fetch_error(fake_repo, tmp_path):
    root, manifest_path, fetcher = fake_repo
    fetcher.redirects[LATEST_HTML] = "https://github.com/moquette/src/releases"
    manifest = _build(fake_repo, tmp_path / "s", allow_shrink=True)
    assert "release.addon" not in manifest["entries"]


def test_tag_vs_packaged_version_mismatch_falls_back(fake_repo, tmp_path):
    """The tag says 2.1.0 but the zip packages addon.xml 2.0.0: publishing it
    would loop Kodi's updater, so it is a FetchError and the last-good copy
    is served instead."""
    root, manifest_path, fetcher = fake_repo
    fetcher.redirects[LATEST_HTML] = (
        "https://github.com/moquette/src/releases/tag/v2.1.0"
    )
    fetcher.urls[RELEASE_ZIP.format(v="2.1.0")] = _zip_bytes("release.addon", "2.0.0")
    live = f"{BASE_URL}/static/release.addon/"
    fetcher.urls[live + "addon.xml"] = _addon_xml("release.addon", "2.0.0").encode()
    fetcher.urls[live + "release.addon-2.0.0.zip"] = _zip_bytes(
        "release.addon", "2.0.0"
    )
    baseline = {"entries": {"release.addon": {"version": "2.0.0"}}}
    manifest = _build(fake_repo, tmp_path / "s", baseline=baseline)
    info = manifest["entries"]["release.addon"]
    assert info["stale"] is True and info["version"] == "2.0.0"


def test_release_zip_without_its_addon_xml_is_a_fetch_error(fake_repo, tmp_path):
    root, manifest_path, fetcher = fake_repo
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("release.addon/README", b"no manifest")
    fetcher.urls[RELEASE_ZIP.format(v="2.0.0")] = buf.getvalue()
    manifest = _build(fake_repo, tmp_path / "s", allow_shrink=True)
    assert "release.addon" not in manifest["entries"]


# ---------------------------------------------------------------------------
# per-add-on tag namespace (2026-09-26): a source repo shipping several add-ons
# (estuarypp: the skin and service.tvos.pythonfix) has ONE releases/latest, so
# the zip template names the tag as {id}-v{version} and the build lists the
# repo's releases and takes the newest in that namespace.
# ---------------------------------------------------------------------------
def _release(tag, assets=True, **flags):
    """A release as the listing shows it. ``assets`` True attaches the
    ns.addon zip for the tag's version at its API asset URL."""
    rel = {"tag_name": tag, "draft": False, "prerelease": False, "assets": [], **flags}
    if assets and tag.startswith("ns.addon-v"):
        v = tag[len("ns.addon-v") :]
        rel["assets"] = [
            {"name": "other.bin", "url": NS_ASSET_API.format(v="x" + v)},
            {
                "name": f"ns.addon-{v}.zip",
                "url": NS_ASSET_API.format(v=v),
                "browser_download_url": NS_ZIP.format(v=v),
            },
        ]
    return rel


def _add_namespaced(fake_repo, releases, zips=("2.0.0",)):
    """Append the namespaced entry to the fixture manifest and stock the
    fetcher with the releases listing and the named zips (at their API
    asset URLs, which is where a namespaced release is downloaded from)."""
    root, manifest_path, fetcher = fake_repo
    entries = json.loads(manifest_path.read_text())
    entries.append(_entry("ns.addon", "release-asset-namespaced"))
    manifest_path.write_text(json.dumps(entries))
    if releases is not None:
        fetcher.urls[RELEASES_LIST] = json.dumps(releases).encode()
    for v in zips:
        fetcher.urls[NS_ASSET_API.format(v=v)] = _zip_bytes("ns.addon", v)


def test_namespaced_release_asset_lists_releases_and_takes_its_own_newest(
    fake_repo, tmp_path
):
    """Other namespaces, drafts and prereleases are skipped; the highest
    version wins regardless of list order; releases/latest is never asked."""
    root, manifest_path, fetcher = fake_repo
    _add_namespaced(
        fake_repo,
        [
            _release("other.addon-v9.9.9"),
            _release("ns.addon-v2.0.0"),
            _release("ns.addon-v2.10.0"),
            _release("ns.addon-v3.0.0", draft=True),
            _release("ns.addon-v4.0.0", prerelease=True),
            _release("v5.0.0"),
        ],
        zips=("2.0.0", "2.10.0"),
    )
    manifest = _build(fake_repo, tmp_path / "s")
    info = manifest["entries"]["ns.addon"]
    assert info["version"] == "2.10.0" and info["kind"] == sc.KIND_RELEASE_ASSET
    assert info["source_url"] == NS_ZIP.format(v="2.10.0")
    assert not info["stale"]
    assert RELEASES_LIST in fetcher.download_calls
    assert RELEASES_LIST not in fetcher.calls, "never through the cache"
    assert not any("moquette/multi/releases/latest" in c for c in fetcher.download_calls)
    # downloaded through the API asset URL, as an octet stream, via the cache
    asset = NS_ASSET_API.format(v="2.10.0")
    assert asset in fetcher.calls
    assert fetcher.fetch_headers[asset]["Accept"] == "application/octet-stream"
    assert NS_ZIP.format(v="2.10.0") not in fetcher.calls
    served = (tmp_path / "s" / "ns.addon" / "addon.xml").read_bytes()
    assert ET.fromstring(served).get("version") == "2.10.0"


def test_namespaced_release_asset_works_without_a_token_and_with_one(
    fake_repo, tmp_path, monkeypatch
):
    _add_namespaced(fake_repo, [_release("ns.addon-v2.0.0")])
    assert _build(fake_repo, tmp_path / "a")["entries"]["ns.addon"]["version"] == (
        "2.0.0"
    )
    root, manifest_path, fetcher = fake_repo
    assert "Authorization" not in fetcher.fetch_headers[NS_ASSET_API.format(v="2.0.0")]
    monkeypatch.setenv("GH_TOKEN", "t0k")
    assert _build(fake_repo, tmp_path / "b")["entries"]["ns.addon"]["version"] == (
        "2.0.0"
    )
    # a private source repo: the token rides on the asset download too
    assert fetcher.fetch_headers[NS_ASSET_API.format(v="2.0.0")]["Authorization"] == (
        "Bearer t0k"
    )
    assert "Authorization" in sc._github_headers()
    monkeypatch.delenv("GH_TOKEN")
    assert "Authorization" not in sc._github_headers()


def test_namespaced_release_asset_without_a_release_falls_back_to_last_good(
    fake_repo, tmp_path
):
    """Nothing tagged in the namespace yet (or the listing failed): the live
    copy is served stale, exactly as for any dead upstream."""
    root, manifest_path, fetcher = fake_repo
    _add_namespaced(fake_repo, [_release("other.addon-v1.0.0"), _release("v1.0.0")])
    live = f"{BASE_URL}/static/ns.addon/"
    fetcher.urls[live + "addon.xml"] = _addon_xml("ns.addon", "1.9.0").encode()
    fetcher.urls[live + "ns.addon-1.9.0.zip"] = _zip_bytes("ns.addon", "1.9.0")
    baseline = {"entries": {"ns.addon": {"version": "1.9.0"}}}
    manifest = _build(fake_repo, tmp_path / "s", baseline=baseline)
    info = manifest["entries"]["ns.addon"]
    assert info["stale"] is True and info["version"] == "1.9.0"
    fetcher.urls[RELEASES_LIST] = sc.FetchError(f"{RELEASES_LIST}: HTTP 403")
    manifest = _build(fake_repo, tmp_path / "s2", baseline=baseline)
    assert manifest["entries"]["ns.addon"]["stale"] is True


def test_namespaced_release_asset_with_no_release_and_no_baseline_is_dropped(
    fake_repo, tmp_path
):
    _add_namespaced(fake_repo, [])
    manifest = _build(fake_repo, tmp_path / "s", allow_shrink=True)
    assert "ns.addon" not in manifest["entries"]


def test_namespaced_release_without_its_zip_attached_falls_back(fake_repo, tmp_path):
    """A tag without the asset is not a release: the last-good copy serves."""
    root, manifest_path, fetcher = fake_repo
    _add_namespaced(fake_repo, [_release("ns.addon-v2.1.0", assets=False)], zips=())
    live = f"{BASE_URL}/static/ns.addon/"
    fetcher.urls[live + "addon.xml"] = _addon_xml("ns.addon", "2.0.0").encode()
    fetcher.urls[live + "ns.addon-2.0.0.zip"] = _zip_bytes("ns.addon", "2.0.0")
    baseline = {"entries": {"ns.addon": {"version": "2.0.0"}}}
    manifest = _build(fake_repo, tmp_path / "s", baseline=baseline)
    info = manifest["entries"]["ns.addon"]
    assert info["stale"] is True and info["version"] == "2.0.0"


def test_namespaced_tag_vs_packaged_version_mismatch_falls_back(fake_repo, tmp_path):
    root, manifest_path, fetcher = fake_repo
    _add_namespaced(fake_repo, [_release("ns.addon-v2.1.0")], zips=())
    fetcher.urls[NS_ASSET_API.format(v="2.1.0")] = _zip_bytes("ns.addon", "2.0.0")
    live = f"{BASE_URL}/static/ns.addon/"
    fetcher.urls[live + "addon.xml"] = _addon_xml("ns.addon", "2.0.0").encode()
    fetcher.urls[live + "ns.addon-2.0.0.zip"] = _zip_bytes("ns.addon", "2.0.0")
    baseline = {"entries": {"ns.addon": {"version": "2.0.0"}}}
    manifest = _build(fake_repo, tmp_path / "s", baseline=baseline)
    info = manifest["entries"]["ns.addon"]
    assert info["stale"] is True and info["version"] == "2.0.0"


def test_plain_release_asset_still_uses_releases_latest_not_the_listing(
    fake_repo, tmp_path, monkeypatch
):
    """The ezmpp shape is untouched by the namespace work: with a token it
    asks releases/latest, without one the redirect, and never the list."""
    root, manifest_path, fetcher = fake_repo
    _build(fake_repo, tmp_path / "a")
    monkeypatch.setenv("GH_TOKEN", "t0k")
    fetcher.urls[LATEST_API] = json.dumps({"tag_name": "v2.0.0"}).encode()
    _build(fake_repo, tmp_path / "b")
    assert not any("/releases?per_page" in c for c in fetcher.download_calls)


def test_version_key_orders_dotted_versions_numerically():
    key = sc._version_key
    assert key("1.10.0") > key("1.9.0")
    assert key("2026.09.17.1") > key("2026.09.2.0")
    assert key("1.4.3") > key("1.4.2")
    assert max(["1.4.2", "1.4.10", "1.4.3"], key=key) == "1.4.10"


def test_build_time_import_check_walks_the_hosted_closure(tmp_path):
    """A build-resolved addon.xml's imports are walked THROUGH committed
    hosted addon.xml files, so a hosted subtree missing a leaf fails the
    entry the way test_closure.py would for a committed root."""
    hosted = tmp_path / "addons" / "hosted"
    (hosted / "plugin.mid").mkdir(parents=True)
    (hosted / "plugin.mid" / "addon.xml").write_text(
        '<addon id="plugin.mid" version="1"><requires>'
        '<import addon="script.module.leaf"/></requires></addon>'
    )
    xml = (
        b'<addon id="x" version="1"><requires>'
        b'<import addon="xbmc.python" version="3.0.0"/>'
        b'<import addon="plugin.mid"/></requires></addon>'
    )
    with pytest.raises(sc.FetchError, match="script.module.leaf"):
        sc._check_imports_hosted("x", xml, {"x", "plugin.mid"}, str(tmp_path))
    sc._check_imports_hosted(
        "x", xml, {"x", "plugin.mid", "script.module.leaf"}, str(tmp_path)
    )
    # an import that is itself build-resolved (no hosted addon.xml) is a leaf
    sc._check_imports_hosted(
        "x",
        b'<addon id="x" version="1"><requires><import addon="resolved.later"/>'
        b"</requires></addon>",
        {"x", "resolved.later"},
        str(tmp_path),
    )


def test_indexed_hybrid_resolves_version_from_the_upstream_index(fake_repo, tmp_path):
    root, manifest_path, fetcher = fake_repo
    fetcher.urls[INDEX_URL] = _index_xml(("indexed.addon", "3.1.0"))
    fetcher.urls[INDEXED_ZIP.format(v="3.1.0")] = _zip_bytes("indexed.addon", "3.1.0")
    manifest = _build(fake_repo, tmp_path / "s")
    info = manifest["entries"]["indexed.addon"]
    assert info["version"] == "3.1.0" and info["kind"] == sc.KIND_HYBRID
    assert info["source_url"] == INDEXED_ZIP.format(v="3.1.0")
    # the index is read fresh, never through the cache
    assert INDEX_URL in fetcher.download_calls and INDEX_URL not in fetcher.calls
    served = (tmp_path / "s" / "indexed.addon" / "addon.xml").read_bytes()
    assert ET.fromstring(served).get("version") == "3.1.0"


def test_index_missing_the_addon_falls_back_to_last_good(fake_repo, tmp_path):
    root, manifest_path, fetcher = fake_repo
    fetcher.urls[INDEX_URL] = _index_xml(("other.addon", "9.9"))
    live = f"{BASE_URL}/static/indexed.addon/"
    fetcher.urls[live + "addon.xml"] = _addon_xml("indexed.addon", "1.0.0").encode()
    fetcher.urls[live + "indexed.addon-1.0.0.zip"] = _zip_bytes(
        "indexed.addon", "1.0.0"
    )
    baseline = {"entries": {"indexed.addon": {"version": "1.0.0"}}}
    manifest = _build(fake_repo, tmp_path / "s", baseline=baseline)
    info = manifest["entries"]["indexed.addon"]
    assert info["stale"] is True and info["version"] == "1.0.0"


def test_index_that_is_not_xml_is_a_fetch_error(fake_repo, tmp_path):
    root, manifest_path, fetcher = fake_repo
    fetcher.urls[INDEX_URL] = b"<html>rate limited"
    manifest = _build(fake_repo, tmp_path / "s", allow_shrink=True)
    assert "indexed.addon" not in manifest["entries"]


def test_hybrid_without_upstream_index_keeps_the_committed_addon_xml(
    fake_repo, tmp_path
):
    """Nothing else in the catalog changes: a plain hybrid still reads
    addons/hosted/<id>/addon.xml for its version and metadata."""
    root, manifest_path, fetcher = fake_repo
    manifest = _build(fake_repo, tmp_path / "s")
    assert manifest["entries"]["hybrid.addon"]["version"] == "2.0.0"
    committed = (root / "addons" / "hosted" / "hybrid.addon" / "addon.xml").read_bytes()
    assert (tmp_path / "s" / "hybrid.addon" / "addon.xml").read_bytes() == committed
    assert INDEX_URL not in [c for c in fetcher.download_calls if "hybrid" in c]


def test_build_resolved_entry_importing_an_unhosted_addon_falls_back(
    fake_repo, tmp_path
):
    """Metadata that arrives at build time is outside test_closure.py's
    offline walk, so its <import>s are checked against the catalog here."""
    root, manifest_path, fetcher = fake_repo
    xml = (
        '<addon id="release.addon" version="2.0.0"><requires>'
        '<import addon="xbmc.python" version="3.0.0"/>'
        '<import addon="hosted.addon"/>'
        '<import addon="script.module.nothosted"/>'
        "</requires></addon>"
    )
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("release.addon/addon.xml", xml)
    fetcher.urls[RELEASE_ZIP.format(v="2.0.0")] = buf.getvalue()
    manifest = _build(fake_repo, tmp_path / "s", allow_shrink=True)
    assert "release.addon" not in manifest["entries"]
    # the same imports minus the unhosted one pass
    xml_ok = xml.replace('<import addon="script.module.nothosted"/>', "")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("release.addon/addon.xml", xml_ok)
    fetcher.urls[RELEASE_ZIP.format(v="2.0.0")] = buf.getvalue()
    manifest = _build(fake_repo, tmp_path / "s2")
    assert manifest["entries"]["release.addon"]["version"] == "2.0.0"


def test_version_is_re_resolved_on_every_build_regardless_of_refresh_flag(
    fake_repo, tmp_path
):
    """Owned content has a minutes staleness bound: a new release between two
    builds is picked up by the second one with no flag and no commit."""
    root, manifest_path, fetcher = fake_repo
    m1 = _build(fake_repo, tmp_path / "s1")
    assert m1["entries"]["release.addon"]["version"] == "2.0.0"
    fetcher.redirects[LATEST_HTML] = (
        "https://github.com/moquette/src/releases/tag/v2.2.0"
    )
    fetcher.urls[RELEASE_ZIP.format(v="2.2.0")] = _zip_bytes("release.addon", "2.2.0")
    fetcher.urls[INDEX_URL] = _index_xml(("indexed.addon", "2.2.0"))
    fetcher.urls[INDEXED_ZIP.format(v="2.2.0")] = _zip_bytes("indexed.addon", "2.2.0")
    m2 = _build(fake_repo, tmp_path / "s2")
    assert m2["entries"]["release.addon"]["version"] == "2.2.0"
    assert m2["entries"]["indexed.addon"]["version"] == "2.2.0"


def test_release_asset_regex_parses_owner_and_repo():
    m = sc._RELEASE_ASSET_RE.match(
        "https://github.com/moquette/kodi-ezmpp/releases/download/v{version}/{id}-{version}.zip"
    )
    assert m and m.group("owner") == "moquette" and m.group("repo") == "kodi-ezmpp"
    assert m.group("asset_template") == "{id}-{version}.zip"
    assert not sc._RELEASE_ASSET_RE.match(
        "https://github.com/moquette/kodi-ezmpp/releases/download/1.0/{id}.zip"
    )


class TestRedirectLocation:
    """Fetcher.redirect_location against a local server: no network."""

    @pytest.fixture
    def server(self):
        import http.server
        import threading

        class H(http.server.BaseHTTPRequestHandler):
            def do_HEAD(self):
                if self.path == "/moquette/src/releases/latest":
                    self.send_response(302)
                    self.send_header(
                        "Location",
                        "https://github.com/moquette/src/releases/tag/v1.2.3",
                    )
                    self.end_headers()
                elif self.path == "/plain":
                    self.send_response(200)
                    self.end_headers()
                else:
                    self.send_response(404)
                    self.end_headers()

            def log_message(self, *a):
                pass

        srv = http.server.HTTPServer(("127.0.0.1", 0), H)
        t = threading.Thread(target=srv.serve_forever, daemon=True)
        t.start()
        yield f"http://127.0.0.1:{srv.server_port}"
        srv.shutdown()

    def test_returns_location_without_following(self, server, tmp_path):
        f = sc.Fetcher(cache_dir=str(tmp_path / "c"))
        loc = f.redirect_location(server + "/moquette/src/releases/latest")
        assert loc.endswith("/releases/tag/v1.2.3")

    def test_200_and_404_are_fetch_errors(self, server, tmp_path):
        f = sc.Fetcher(cache_dir=str(tmp_path / "c"))
        with pytest.raises(sc.FetchError, match="expected a redirect"):
            f.redirect_location(server + "/plain")
        with pytest.raises(sc.FetchError, match="404"):
            f.redirect_location(server + "/nope")


# ---------------------------------------------------------------------------
# Fetcher unit tests - the exact cache semantics F1/F4 exploited
# ---------------------------------------------------------------------------
def _http_404(url):
    err = None
    try:
        raise urllib.error.HTTPError(url, 404, "not found", None, None)
    except urllib.error.HTTPError as e:
        err = e
    exc = sc.FetchError(f"{url}: 404")
    exc.__cause__ = err
    return exc


class TestFetcher:
    def _fetcher(self, tmp_path, downloads: dict, **kw):
        f = sc.Fetcher(cache_dir=str(tmp_path / "cache"), **kw)
        f.download_calls = []

        def _dl(url, headers=None):
            f.download_calls.append(url)
            if url in downloads:
                v = downloads[url]
                if isinstance(v, Exception):
                    raise v
                return v
            raise sc.FetchError(f"{url}: down")

        f._download = _dl
        return f

    def test_miss_downloads_then_hit_serves_cache(self, tmp_path):
        f = self._fetcher(tmp_path, {"u://a": b"DATA"})
        assert f.fetch("u://a") == b"DATA"
        assert f.fetch("u://a") == b"DATA"
        assert f.download_calls == ["u://a"]

    def test_mutable_refreshes_only_when_asked(self, tmp_path):
        f = self._fetcher(tmp_path, {"u://a": b"V1"})
        assert f.fetch("u://a", mutable=True) == b"V1"
        f2 = self._fetcher(tmp_path, {"u://a": b"V2"}, refresh_mutable=True)
        assert f2.fetch("u://a", mutable=True) == b"V2"
        f3 = self._fetcher(tmp_path, {"u://a": b"V3"})
        assert f3.fetch("u://a", mutable=True) == b"V2"  # cache, no refresh

    def test_refresh_failure_falls_back_to_cache(self, tmp_path):
        f = self._fetcher(tmp_path, {"u://a": b"V1"})
        f.fetch("u://a", mutable=True)
        f2 = self._fetcher(
            tmp_path, {"u://a": sc.FetchError("boom")}, refresh_mutable=True
        )
        assert f2.fetch("u://a", mutable=True) == b"V1"

    def test_tolerated_404_returns_none_and_caches_nothing(self, tmp_path):
        f = self._fetcher(tmp_path, {"u://a": _http_404("u://a")})
        assert f.fetch("u://a", tolerate_missing=True) is None
        assert (
            not list((tmp_path / "cache").glob("*"))
            or not (tmp_path / "cache").exists()
        )

    def test_expect_zip_rejects_and_never_caches_garbage(self, tmp_path):
        f = self._fetcher(tmp_path, {"u://z": b"<html>err</html>"})
        with pytest.raises(sc.FetchError, match="not a readable zip"):
            f.fetch("u://z", expect_zip=True)
        f2 = self._fetcher(tmp_path, {"u://z": _zip_bytes("a", "1")})
        assert f2.fetch("u://z", expect_zip=True) == _zip_bytes("a", "1")
        assert f2.download_calls == ["u://z"]  # nothing poisoned earlier

    def test_poisoned_cache_self_heals(self, tmp_path):
        good = _zip_bytes("a", "1")
        f = self._fetcher(tmp_path, {"u://z": good})
        cache_path = f._cache_path("u://z")
        os.makedirs(os.path.dirname(cache_path), exist_ok=True)
        with open(cache_path, "wb") as fh:
            fh.write(b"POISON")
        assert f.fetch("u://z", expect_zip=True) == good
        assert f.download_calls == ["u://z"]


# ---------------------------------------------------------------------------
# the official Kodi repository as an upstream_index (2026-09-26): gzipped
# index, fetched once per build, the closure walked through build-resolved
# imports, and a mirror's wrong-file answer refused before the cache
# ---------------------------------------------------------------------------
GZ_INDEX = "https://mirror.example/addons/piers/addons.xml.gz"
GZ_ZIP = "https://mirror.example/addons/piers/{id}/{id}-{v}.zip"


def _official(addon_id: str, imports: tuple[str, ...] = ()) -> dict:
    """An entry shaped like the eleven official modules in catalog.json."""
    e = _entry(addon_id, "indexed")
    e["assets"] = {"zip": "https://mirror.example/addons/piers/{id}/{id}-{version}.zip"}
    e["upstream_index"] = GZ_INDEX
    return e


def _zip_with_imports(addon_id: str, version: str, imports: tuple[str, ...]) -> bytes:
    reqs = "".join(f'<import addon="{i}"/>' for i in ("xbmc.python", *imports))
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(
            f"{addon_id}/addon.xml",
            f'<addon id="{addon_id}" version="{version}"><requires>{reqs}'
            f"</requires></addon>",
        )
        zf.writestr(f"{addon_id}/icon.png", b"PNG")
    return buf.getvalue()


def _official_repo(tmp_path, graph: dict[str, tuple[str, ...]], version="1.0"):
    """A catalog of official-shaped entries whose imports follow ``graph``,
    all at ``version`` in ONE gzipped index."""
    root = tmp_path / "repo"
    (root / "addons" / "hosted").mkdir(parents=True)
    entries = [_official(aid) for aid in graph]
    manifest_path = root / "repository.json"
    manifest_path.write_text(json.dumps(entries))
    urls = {GZ_INDEX: gzip.compress(_index_xml(*((a, version) for a in graph)))}
    for aid, imports in graph.items():
        urls[GZ_ZIP.format(id=aid, v=version)] = _zip_with_imports(
            aid, version, imports
        )
    return root, manifest_path, FakeFetcher(urls)


def test_gzipped_index_is_decompressed_by_magic_bytes_or_suffix():
    plain = _index_xml(("a", "1.2"))
    assert sc._parse_index("u://x.xml", plain).find("addon").get("version") == "1.2"
    packed = gzip.compress(plain)
    assert sc._parse_index("u://x.xml", packed).find("addon").get("version") == "1.2"
    assert sc._parse_index("u://x.gz", packed).find("addon").get("version") == "1.2"
    with pytest.raises(sc.FetchError, match="not gzip"):
        sc._parse_index("u://x.gz", b"<addons/>")
    with pytest.raises(sc.FetchError, match="not XML"):
        sc._parse_index("u://x.xml", gzip.compress(b"<html>rate limited"))


def test_shared_index_is_fetched_once_per_build_and_again_next_build(tmp_path):
    graph = {"script.module.a": (), "script.module.b": (), "script.module.c": ()}
    root, manifest_path, fetcher = _official_repo(tmp_path, graph)
    m1 = sc.build(
        str(tmp_path / "s1"),
        fetcher=fetcher,
        repo_json=str(manifest_path),
        repo_root=str(root),
        base_url=BASE_URL,
    )
    assert set(m1["entries"]) == set(graph)
    assert all(e["kind"] == sc.KIND_HYBRID for e in m1["entries"].values())
    assert fetcher.download_calls.count(GZ_INDEX) == 1
    assert GZ_INDEX not in fetcher.calls  # never through the cache
    # a second build (the determinism gate, the next CI run) re-reads it
    sc.build(
        str(tmp_path / "s2"),
        fetcher=fetcher,
        repo_json=str(manifest_path),
        repo_root=str(root),
        base_url=BASE_URL,
    )
    assert fetcher.download_calls.count(GZ_INDEX) == 2


def test_import_closure_is_walked_transitively_through_build_resolved_entries(
    tmp_path, capsys
):
    """skin -> plugin -> module -> requests -> urllib3: every hop's addon.xml
    is read out of its resolved zip, on the importing entry's turn, and each
    zip is fetched ONCE for the build however many walks cross it."""
    graph = {
        "skin.x": ("plugin.program.autocompletion",),
        "plugin.program.autocompletion": ("script.module.autocompletion",),
        "script.module.autocompletion": ("script.module.requests",),
        "script.module.requests": ("script.module.urllib3", "script.module.certifi"),
        "script.module.urllib3": (),
        "script.module.certifi": (),
        "service.tvos.pythonfix": ("script.module.requests",),
    }
    root, manifest_path, fetcher = _official_repo(tmp_path, graph)
    m = sc.build(
        str(tmp_path / "s"),
        fetcher=fetcher,
        repo_json=str(manifest_path),
        repo_root=str(root),
        base_url=BASE_URL,
    )
    assert set(m["entries"]) == set(graph)
    assert not any(e["stale"] for e in m["entries"].values())
    for aid in graph:
        assert fetcher.calls.count(GZ_ZIP.format(id=aid, v="1.0")) == 1, aid
        assert fetcher.fetch_expectations[GZ_ZIP.format(id=aid, v="1.0")] == (aid, "1.0")
    assert "1 upstream index fetch(es)" in capsys.readouterr().out
    # art declared by the packaged addon.xml is materialized out of the zip
    assert (tmp_path / "s" / "script.module.urllib3" / "icon.png").read_bytes() == b"PNG"


def test_a_leaf_missing_from_the_catalog_fails_every_entry_that_reaches_it(tmp_path):
    graph = {
        "skin.x": ("plugin.mid",),
        "plugin.mid": ("script.module.leaf",),  # leaf is NOT a catalog entry
        "script.module.alone": (),
    }
    root, manifest_path, fetcher = _official_repo(tmp_path, graph)
    m = sc.build(
        str(tmp_path / "s"),
        fetcher=fetcher,
        repo_json=str(manifest_path),
        repo_root=str(root),
        base_url=BASE_URL,
        allow_shrink=True,
    )
    assert set(m["entries"]) == {"script.module.alone"}


def test_an_unresolvable_build_resolved_import_fails_the_importer_once(tmp_path):
    """The dependency's zip is gone from the mirror: the importer falls back
    (here: is dropped, no baseline), the dependency itself too, and the
    failed lookup is memoized rather than retried on the dependency's turn."""
    graph = {
        "skin.x": ("script.module.dep",),
        "script.module.dep": (),
        "script.module.alone": (),
    }
    root, manifest_path, fetcher = _official_repo(tmp_path, graph)
    dep_zip = GZ_ZIP.format(id="script.module.dep", v="1.0")
    del fetcher.urls[dep_zip]
    m = sc.build(
        str(tmp_path / "s"),
        fetcher=fetcher,
        repo_json=str(manifest_path),
        repo_root=str(root),
        base_url=BASE_URL,
        allow_shrink=True,
    )
    assert set(m["entries"]) == {"script.module.alone"}
    assert fetcher.calls.count(dep_zip) == 1


def test_check_imports_walks_through_a_resolver_and_names_the_failure():
    xml = (
        b'<addon id="x" version="1"><requires>'
        b'<import addon="script.module.dep"/></requires></addon>'
    )
    dep_xml = (
        b'<addon id="script.module.dep" version="1"><requires>'
        b'<import addon="script.module.leaf"/></requires></addon>'
    )

    def resolver(aid):
        if aid == "script.module.dep":
            return dep_xml
        if aid == "script.module.broken":
            raise sc.FetchError("zip 404")
        return None

    ids = {"x", "script.module.dep", "script.module.leaf", "script.module.broken"}
    sc._check_imports_hosted("x", xml, ids, resolver=resolver)
    with pytest.raises(sc.FetchError, match="script.module.leaf"):
        sc._check_imports_hosted("x", xml, ids - {"script.module.leaf"}, resolver=resolver)
    with pytest.raises(sc.FetchError, match="script.module.broken could not be resolved"):
        sc._check_imports_hosted(
            "x",
            b'<addon id="x" version="1"><requires>'
            b'<import addon="script.module.broken"/></requires></addon>',
            ids,
            resolver=resolver,
        )


def test_wrong_addon_bytes_from_a_mirror_are_refused_and_never_cached(tmp_path):
    """MEASURED 2026-09-26: a certifi download from mirrors.kodi.tv came back
    as the requests zip's bytes. A readable zip of the wrong add-on must be
    a FetchError (fallback applies) and must not land in the cache under
    certifi's URL, where an immutable key would serve it on every build."""
    requests_zip = _zip_bytes("script.module.requests", "2.31.0")
    certifi_zip = _zip_bytes("script.module.certifi", "2023.5.7")
    f = TestFetcher()._fetcher(tmp_path, {"u://certifi": requests_zip})
    with pytest.raises(sc.FetchError, match="no script.module.certifi/addon.xml"):
        f.fetch(
            "u://certifi",
            expect_zip=True,
            expect_addon=("script.module.certifi", "2023.5.7"),
        )
    assert not os.path.exists(f._cache_path("u://certifi"))
    # a wrong version at the right id is refused the same way
    f2 = TestFetcher()._fetcher(
        tmp_path, {"u://certifi": _zip_bytes("script.module.certifi", "2023.5.6")}
    )
    with pytest.raises(sc.FetchError, match="'2023.5.6', expected"):
        f2.fetch("u://certifi", expect_addon=("script.module.certifi", "2023.5.7"))
    # the right bytes are accepted and cached; a poisoned cache self-heals
    f3 = TestFetcher()._fetcher(tmp_path, {"u://certifi": certifi_zip})
    assert (
        f3.fetch("u://certifi", expect_addon=("script.module.certifi", "2023.5.7"))
        == certifi_zip
    )
    with open(f3._cache_path("u://certifi"), "wb") as fh:
        fh.write(requests_zip)
    f4 = TestFetcher()._fetcher(tmp_path, {"u://certifi": certifi_zip})
    assert (
        f4.fetch("u://certifi", expect_addon=("script.module.certifi", "2023.5.7"))
        == certifi_zip
    )
    assert f4.download_calls == ["u://certifi"]


class TestDownloadRetry:
    """_download retries a transient failure a bounded number of times and
    never retries a 4xx. urlopen is faked; sleep is silenced."""

    def _run(self, monkeypatch, answers: list, url="u://z"):
        calls = []

        class _Resp:
            def __init__(self, data):
                self.data = data

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def read(self):
                return self.data

        def fake_urlopen(req, timeout=None):
            calls.append(req.full_url)
            answer = answers.pop(0)
            if isinstance(answer, Exception):
                raise answer
            return _Resp(answer)

        monkeypatch.setattr(sc.urllib.request, "urlopen", fake_urlopen)
        monkeypatch.setattr(sc.time, "sleep", lambda s: None)
        return calls, sc.Fetcher(cache_dir=str("/nonexistent"))

    def test_transient_failures_are_retried_then_succeed(self, monkeypatch):
        calls, f = self._run(
            monkeypatch,
            [urllib.error.URLError("reset"), TimeoutError("slow"), b"OK"],
        )
        assert f._download("u://z") == b"OK"
        assert calls == ["u://z"] * 3

    def test_gives_up_after_the_bounded_attempts(self, monkeypatch):
        calls, f = self._run(
            monkeypatch, [urllib.error.URLError("down")] * sc._DOWNLOAD_ATTEMPTS
        )
        with pytest.raises(sc.FetchError, match="down"):
            f._download("u://z")
        assert len(calls) == sc._DOWNLOAD_ATTEMPTS

    def test_a_404_is_final_on_the_first_answer(self, monkeypatch):
        calls, f = self._run(
            monkeypatch, [urllib.error.HTTPError("u://z", 404, "nope", None, None)]
        )
        with pytest.raises(sc.FetchError) as exc:
            f._download("u://z")
        assert sc._is_404(exc.value)
        assert len(calls) == 1

    def test_a_5xx_is_retried(self, monkeypatch):
        calls, f = self._run(
            monkeypatch,
            [urllib.error.HTTPError("u://z", 503, "busy", None, None), b"OK"],
        )
        assert f._download("u://z") == b"OK"
        assert len(calls) == 2
