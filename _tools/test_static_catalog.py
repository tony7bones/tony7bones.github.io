"""Tests for static_catalog.py - the /static/ Kodi repo builder.

Carries forward the engine's propagation contracts at build time (see
test_update_propagation.py for the engine originals, retired at Phase 6):
md5 <-> document invariant, per-entry fault isolation with last-good
fallback, never-empty catalog, plus the new build-time gates (shrink guard,
90MB ceiling, determinism). No network: all fetches go through a fake.
"""

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


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
class FakeFetcher:
    """Duck-typed sc.Fetcher backed by a dict; raises FetchError on misses."""

    def __init__(self, urls: dict | None = None):
        self.urls = dict(urls or {})
        self.calls: list[str] = []

    def fetch(self, url, mutable=False, tolerate_missing=False, expect_zip=False):
        self.calls.append(url)
        if url in self.urls:
            return self.urls[url]
        if tolerate_missing:
            return None
        raise sc.FetchError(f"{url}: not in fake")

    def _download(self, url):
        return self.fetch(url)


class SplitFetcher(FakeFetcher):
    """Models the F1 bug surface: fetch() serves the (possibly stale) CACHE,
    _download() serves the LIVE site. The fallback path must only ever touch
    the latter."""

    def __init__(self, cached: dict | None = None, live: dict | None = None):
        super().__init__(cached)
        self.live = dict(live or {})
        self.download_calls: list[str] = []

    def _download(self, url):
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
        ("release.addon", "release-asset", None),
    ]:
        d = root / "addons" / "hosted" / hid
        d.mkdir(parents=True)
        (d / "addon.xml").write_text(_addon_xml(hid, "2.0.0"))
        (d / "icon.png").write_bytes(b"PNG-" + hid.encode())
        if zname:
            (d / zname).write_bytes(_zip_bytes(hid, "2.0.0"))
        entries.append(_entry(hid, kind))

    entries.append(_entry("streamed.addon", "streamed"))

    manifest_path = root / "repository.json"
    manifest_path.write_text(json.dumps(entries))

    fetcher = FakeFetcher(
        {
            "https://raw.githubusercontent.com/up/stream/master/hybrid.addon-2.0.0.zip": _zip_bytes(
                "hybrid.addon", "2.0.0"
            ),
            "https://github.com/moquette/src/releases/download/v2.0.0/release.addon-2.0.0.zip": _zip_bytes(
                "release.addon", "2.0.0"
            ),
            "https://raw.githubusercontent.com/up/stream/main/zips/streamed.addon/addon.xml": _addon_xml(
                "streamed.addon", "3.0.0"
            ).encode(),
            "https://raw.githubusercontent.com/up/stream/main/zips/streamed.addon/streamed.addon-3.0.0.zip": _zip_bytes(
                "streamed.addon", "3.0.0"
            ),
            "https://raw.githubusercontent.com/up/stream/main/zips/streamed.addon/icon.png": b"PNG-ST",
        }
    )
    return root, manifest_path, fetcher


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
    assert sc.classify(_entry("a", "streamed")) == sc.KIND_STREAMED


def test_classify_the_real_manifest_covers_all_entries():
    """The REAL catalog.json: every entry classifies, with the known per-class
    counts (update deliberately when the catalog changes).

    28 entries, and the arithmetic behind that number, newest first:

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

    skin.estuary8 is HOSTED, not release-asset like skin.estuary7, and that
    difference is deliberate rather than an oversight. A release-asset entry
    resolves its zip from a GitHub Release on the source repo, and
    check_hosted_release_sync.py HARD-FAILS on a broken pointer: declare one
    before a matching release exists and every build goes red. Estuary 8 has no
    release yet. Hosting the zip in this repo also keeps the whole Estuary 8
    closure installable off-grid, which is exactly what the skinshortcuts purge
    above cost Estuary 7. Switching it to release-asset later is a one-line
    change here plus a real release; do not do it before the release exists.
    """
    entries = sc.load_catalog()
    kinds = {}
    for e in entries:
        kinds.setdefault(sc.classify(e), []).append(e["id"])
    assert len(entries) == 28
    assert kinds[sc.KIND_FIRST_PARTY] == ["repository.tony7bones"]
    assert len(kinds[sc.KIND_HOSTED]) == 17
    assert len(kinds[sc.KIND_HYBRID]) == 3
    assert len(kinds[sc.KIND_STREAMED]) == 5
    assert len(kinds[sc.KIND_RELEASE_ASSET]) == 2
    assert "skin.estuary7" in kinds[sc.KIND_RELEASE_ASSET]
    assert "skin.estuary8" in kinds[sc.KIND_HOSTED]
    assert "script.estuary8.shortcuts" in kinds[sc.KIND_HOSTED]
    assert "plugin.video.estuary8.search" in kinds[sc.KIND_HOSTED]
    ids = {e["id"] for e in entries}
    for gone in (
        "script.module.pvr.artwork",
        "resource.images.weathericons.outline-hd",
        "script.tony7bones.modv2plus",
        "script.tony7bones.bootstrap",
        "script.module.tony7bones",
        "script.skinshortcuts",
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
        if "/addons/hosted/" in json.dumps(e) and e["id"] not in hosted
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
    assert manifest["count"] == 6
    ids = set(manifest["entries"])
    assert ids == {
        "first.party",
        "hosted.addon",
        "unversioned.addon",
        "hybrid.addon",
        "release.addon",
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
    # the other five resolved fresh - fault isolation
    assert manifest["count"] == 6
    assert sum(e["stale"] for e in manifest["entries"].values()) == 1


def test_dead_upstream_without_baseline_is_dropped_with_survivors(fake_repo, tmp_path):
    _kill_streamed(fake_repo)
    manifest = _build(fake_repo, tmp_path / "static", baseline=None)
    assert manifest["count"] == 5
    assert "streamed.addon" not in manifest["entries"]


def test_shrink_vs_baseline_fails_without_the_flag(fake_repo, tmp_path):
    _kill_streamed(fake_repo)
    baseline = {"entries": {"streamed.addon": {"version": "2.9.0"}}}
    # baseline knows the entry but the live fallback copies are gone too
    with pytest.raises(sc.BuildError, match="LOSE entries"):
        _build(fake_repo, tmp_path / "static", baseline=baseline)


def test_shrink_is_allowed_only_explicitly(fake_repo, tmp_path):
    _kill_streamed(fake_repo)
    baseline = {"entries": {"streamed.addon": {"version": "2.9.0"}}}
    manifest = _build(
        fake_repo, tmp_path / "static", baseline=baseline, allow_shrink=True
    )
    assert manifest["count"] == 5


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
    assert manifest["count"] == 6


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

        def _dl(url):
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
