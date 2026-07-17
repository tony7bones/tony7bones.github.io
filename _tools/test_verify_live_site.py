"""Tests for verify_live_site.py - the consumer-seat post-deploy gate.

All HTTP is faked at the _request seam; the contract under test: a deploy
whose served bytes do not exactly match the build manifest FAILS the run.
"""

import hashlib
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
import verify_live_site as vls

BASE = "https://example.test"


def _manifest_and_urls():
    zips = {
        "repository.tony7bones": b"ZIP-REPO",
        "other.addon": b"ZIP-OTHER",
    }
    versions = {"repository.tony7bones": "3.0.0", "other.addon": "1.2.3"}
    entries = {
        i: {
            "version": versions[i],
            "zip": f"{i}/{i}-{versions[i]}.zip",
            "zip_sha256": hashlib.sha256(zips[i]).hexdigest(),
            "zip_size": len(zips[i]),
            "kind": "first-party",
            "source_url": "x",
            "stale": False,
        }
        for i in zips
    }
    manifest = {"count": len(entries), "entries": entries}

    addons_xml = (
        "<addons>"
        + "".join(f'<addon id="{i}" version="{versions[i]}"/>' for i in sorted(zips))
        + "</addons>"
    ).encode()
    urls = {
        f"{BASE}/static/addons.xml": addons_xml,
        f"{BASE}/static/addons.xml.md5": hashlib.md5(addons_xml).hexdigest().encode(),
        f"{BASE}/": (
            # The served canvas root after the 2026-07-16 retirement of
            # media/ + zips/ + iptv/: repositories/ + rss/ only.
            '<a href="repositories/">r</a><a href="rss/">r</a>'
        ).encode(),
        f"{BASE}/repository.tony7bones-3.0.0.zip": b"INSTALLER",
        f"{BASE}/addons/addons.xml": b"<addons/>",
    }
    for i, z in zips.items():
        urls[f"{BASE}/static/{i}/{i}-{versions[i]}.zip"] = z
    return manifest, urls


@pytest.fixture
def fake_http(monkeypatch):
    manifest, urls = _manifest_and_urls()

    def _request(url, method="GET"):
        if url not in urls:
            raise vls.VerifyError(f"{method} {url}: http 404")
        return urls[url] if method == "GET" else b""

    monkeypatch.setattr(vls, "_request", _request)
    return manifest, urls


def _verify(manifest, transition=True):
    return vls.verify(manifest, BASE, attempts=1, delay=0, transition=transition)


def test_happy_path_verifies(fake_http):
    manifest, _ = fake_http
    assert _verify(manifest) is True


def test_md5_mismatch_fails(fake_http):
    manifest, urls = fake_http
    urls[f"{BASE}/static/addons.xml.md5"] = b"0" * 32
    assert _verify(manifest) is False


def test_missing_zip_fails(fake_http):
    manifest, urls = fake_http
    del urls[f"{BASE}/static/other.addon/other.addon-1.2.3.zip"]
    assert _verify(manifest) is False


def test_served_sha_drift_fails(fake_http):
    manifest, urls = fake_http
    urls[f"{BASE}/static/repository.tony7bones/repository.tony7bones-3.0.0.zip"] = (
        b"TAMPERED"
    )
    assert _verify(manifest) is False


def test_version_drift_fails(fake_http):
    manifest, _ = fake_http
    manifest["entries"]["other.addon"]["version"] = "9.9.9"
    manifest["entries"]["other.addon"]["zip"] = "other.addon/other.addon-9.9.9.zip"
    assert _verify(manifest) is False


def test_missing_canvas_folder_fails(fake_http):
    manifest, urls = fake_http
    # rss/ present but repositories/ missing -> a required canvas folder is gone.
    urls[f"{BASE}/"] = b'<a href="rss/">r</a>'
    assert _verify(manifest) is False


def test_legacy_endpoint_checked_only_in_transition(fake_http):
    manifest, urls = fake_http
    del urls[f"{BASE}/addons/addons.xml"]
    assert _verify(manifest, transition=True) is False
    assert _verify(manifest, transition=False) is True


def test_expect_count_floor_fails_a_shrunken_manifest(fake_http):
    """F3 follow-through: the manifest is the build's own output - the count
    floor is the only check anchored to the SOURCE catalog."""
    manifest, _ = fake_http
    assert vls.verify(manifest, BASE, attempts=1, delay=0, expect_count=31) is False
    assert (
        vls.verify(manifest, BASE, attempts=1, delay=0, transition=True, expect_count=2)
        is True
    )


def test_manifest_without_proxy_entry_fails_cleanly(fake_http):
    """A missing repository.tony7bones must be a VerifyError (retried, then
    red), never a KeyError traceback that kills the retry loop."""
    manifest, urls = fake_http
    del manifest["entries"]["repository.tony7bones"]
    # keep the served side consistent so only the canvas check trips
    manifest["count"] = 1
    addons_xml = b'<addons><addon id="other.addon" version="1.2.3"/></addons>'
    urls[f"{BASE}/static/addons.xml"] = addons_xml
    import hashlib as _h

    urls[f"{BASE}/static/addons.xml.md5"] = _h.md5(addons_xml).hexdigest().encode()
    assert _verify(manifest) is False
