"""Tests for external_addons.py — the manifest-driven hybrid prototype.

All network access is faked, so these run fully offline.
"""

import json
import sys
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest

sys.path.insert(0, str(Path(__file__).parent))
import external_addons as ea  # noqa: E402


def _addon_xml(addon_id: str, version: str) -> str:
    return (
        f'<?xml version="1.0" encoding="UTF-8"?>'
        f'<addon id="{addon_id}" name="Example" version="{version}" provider-name="x">'
        f'<extension point="xbmc.python.script" library="default.py"/>'
        f"</addon>"
    )


class FakeResolverBackend:
    """Records requests and serves canned text/bytes responses by URL substring."""

    def __init__(self, texts: dict, blobs: dict | None = None):
        self.texts = texts
        self.blobs = blobs or {}
        self.text_calls: list[tuple[str, dict]] = []
        self.bytes_calls: list[tuple[str, dict]] = []

    def fetch_text(self, url: str, headers: dict) -> str:
        self.text_calls.append((url, headers))
        for key, value in self.texts.items():
            if key in url:
                return value
        raise AssertionError(f"unexpected text fetch: {url}")

    def fetch_bytes(self, url: str, headers: dict) -> bytes:
        self.bytes_calls.append((url, headers))
        for key, value in self.blobs.items():
            if key in url:
                return value
        raise AssertionError(f"unexpected bytes fetch: {url}")


# ---------------------------------------------------------------------------
# _subst / _version_from_tag
# ---------------------------------------------------------------------------


def test_subst_replaces_known_and_keeps_unknown():
    out = ea._subst("a/{username}/{missing}", username="bob")
    assert out == "a/bob/{missing}"


@pytest.mark.parametrize(
    "tag, pattern, expected",
    [
        ("v1.2.3", "v{version}", "1.2.3"),
        ("1.2.3", "v{version}", "1.2.3"),  # pattern doesn't match → fallback
        ("v2.0", None, "2.0"),  # no pattern → strip leading v
        ("2.0", None, "2.0"),
        ("release-9", "release-{version}", "9"),
    ],
)
def test_version_from_tag(tag, pattern, expected):
    assert ea._version_from_tag(tag, pattern) == expected


# ---------------------------------------------------------------------------
# load_manifest
# ---------------------------------------------------------------------------


def test_load_manifest_missing_returns_empty(tmp_path):
    assert ea.load_manifest(str(tmp_path / "nope.json")) == []


def test_load_manifest_reads_list(tmp_path):
    p = tmp_path / "m.json"
    p.write_text(json.dumps([{"id": "a", "username": "b"}]))
    assert ea.load_manifest(str(p)) == [{"id": "a", "username": "b"}]


def test_load_manifest_rejects_non_list(tmp_path):
    p = tmp_path / "m.json"
    p.write_text(json.dumps({"id": "a"}))
    with pytest.raises(ValueError):
        ea.load_manifest(str(p))


# ---------------------------------------------------------------------------
# GitHubResolver.resolve
# ---------------------------------------------------------------------------


def test_resolve_happy_path():
    backend = FakeResolverBackend(
        texts={
            "releases/latest": json.dumps({"tag_name": "v1.4.0"}),
            "addon.xml": _addon_xml("plugin.video.example", "1.4.0"),
        }
    )
    resolver = ea.GitHubResolver(backend.fetch_text, backend.fetch_bytes)
    entry = {"id": "plugin.video.example", "username": "someuser"}

    resolved = resolver.resolve(entry)

    assert resolved.id == "plugin.video.example"
    assert resolved.version == "1.4.0"
    assert resolved.tag == "v1.4.0"
    assert resolved.root.get("version") == "1.4.0"
    # default zip template was applied
    assert resolved.zip_url == (
        "https://github.com/someuser/plugin.video.example/releases/download/"
        "v1.4.0/plugin.video.example-1.4.0.zip"
    )


def test_resolve_uses_custom_repository_and_assets():
    backend = FakeResolverBackend(
        texts={
            "releases/latest": json.dumps({"tag_name": "3.0"}),
            "addon.xml": _addon_xml("plugin.x", "3.0"),
        }
    )
    resolver = ea.GitHubResolver(backend.fetch_text, backend.fetch_bytes)
    entry = {
        "id": "plugin.x",
        "username": "owner",
        "repository": "custom-repo",
        "assets": {"zip": "https://host/{repository}/{version}.zip"},
    }

    resolved = resolver.resolve(entry)

    assert resolved.zip_url == "https://host/custom-repo/3.0.zip"
    # the latest-release API call must target the custom repository name
    assert any("owner/custom-repo/releases/latest" in u for u, _ in backend.text_calls)


def test_resolve_sends_token_header():
    backend = FakeResolverBackend(
        texts={
            "releases/latest": json.dumps({"tag_name": "v1.0.0"}),
            "addon.xml": _addon_xml("plugin.priv", "1.0.0"),
        }
    )
    resolver = ea.GitHubResolver(backend.fetch_text, backend.fetch_bytes)
    resolver.resolve({"id": "plugin.priv", "username": "u", "token": "secret"})

    assert all(h.get("Authorization") == "token secret" for _, h in backend.text_calls)


def test_resolve_rejects_id_mismatch():
    backend = FakeResolverBackend(
        texts={
            "releases/latest": json.dumps({"tag_name": "v1.0.0"}),
            "addon.xml": _addon_xml("plugin.OTHER", "1.0.0"),
        }
    )
    resolver = ea.GitHubResolver(backend.fetch_text, backend.fetch_bytes)
    with pytest.raises(ValueError, match="declares id"):
        resolver.resolve({"id": "plugin.expected", "username": "u"})


def test_resolve_requires_id_and_username():
    resolver = ea.GitHubResolver(lambda u, h: "", lambda u, h: b"")
    with pytest.raises(ValueError, match="missing id/username"):
        resolver.resolve({"id": "x"})


def test_resolve_errors_when_no_tag():
    backend = FakeResolverBackend(texts={"releases/latest": json.dumps({})})
    resolver = ea.GitHubResolver(backend.fetch_text, backend.fetch_bytes)
    with pytest.raises(ValueError, match="no tag_name"):
        resolver.resolve({"id": "plugin.x", "username": "u"})


# ---------------------------------------------------------------------------
# process_external_addons
# ---------------------------------------------------------------------------


def test_process_empty_manifest_is_noop():
    roots, ids = ea.process_external_addons(manifest=[])
    assert (roots, ids) == ([], [])


def test_process_resolves_without_writing():
    backend = FakeResolverBackend(
        texts={
            "releases/latest": json.dumps({"tag_name": "v2.1.0"}),
            "addon.xml": _addon_xml("plugin.video.example", "2.1.0"),
        }
    )
    resolver = ea.GitHubResolver(backend.fetch_text, backend.fetch_bytes)

    roots, ids = ea.process_external_addons(
        manifest=[{"id": "plugin.video.example", "username": "someuser"}],
        resolver=resolver,
        write=False,
    )

    assert ids == ["plugin.video.example"]
    assert roots[0].get("id") == "plugin.video.example"
    assert backend.bytes_calls == []  # nothing downloaded in dry run


def test_process_write_downloads_zip_and_index(tmp_path):
    # Build a real zip payload to "download".
    zip_path = tmp_path / "payload.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("plugin.video.example/addon.xml", _addon_xml("plugin.video.example", "2.1.0"))
    payload = zip_path.read_bytes()

    backend = FakeResolverBackend(
        texts={
            "releases/latest": json.dumps({"tag_name": "v2.1.0"}),
            "addon.xml": _addon_xml("plugin.video.example", "2.1.0"),
        },
        blobs={".zip": payload},
    )
    resolver = ea.GitHubResolver(backend.fetch_text, backend.fetch_bytes)
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()

    roots, ids = ea.process_external_addons(
        manifest=[{"id": "plugin.video.example", "username": "someuser"}],
        resolver=resolver,
        write=True,
        repo_dir=str(repo_dir),
    )

    assert ids == ["plugin.video.example"]
    out_zip = repo_dir / "plugin.video.example" / "plugin.video.example-2.1.0.zip"
    out_index = repo_dir / "plugin.video.example" / "index.html"
    assert out_zip.read_bytes() == payload
    assert "plugin.video.example-2.1.0.zip" in out_index.read_text()
    assert "HTML 3.2" in out_index.read_text()


# ---------------------------------------------------------------------------
# generate_repo integration — must stay a no-op without a manifest
# ---------------------------------------------------------------------------


def test_generate_repo_integration_noop_without_manifest(tmp_path, monkeypatch):
    """generate() must not change behaviour when no external manifest exists."""
    import generate_repo as gr

    repo = tmp_path / "repo"
    addon = repo / "plugin.hello"
    addon.mkdir(parents=True)
    (addon / "addon.xml").write_text(_addon_xml("plugin.hello", "1.0.0"))
    (addon / "default.py").write_text("# x")

    monkeypatch.setattr(gr, "REPO_DIR", str(repo))
    monkeypatch.setattr(gr, "REPOS_DIR", str(repo / "repositories"))
    monkeypatch.setattr(gr, "SCRIPTS_DIR", str(repo / "scripts"))
    monkeypatch.setattr(gr, "MEDIA_DIR", str(repo / "media"))
    # Point the prototype's manifest lookup at a non-existent file.
    monkeypatch.setattr(ea, "DEFAULT_MANIFEST", str(tmp_path / "absent.json"))

    gr.generate()

    ids = [el.get("id") for el in ET.parse(str(repo / "addons.xml")).getroot()]
    assert ids == ["plugin.hello"]  # only the in-tree add-on, nothing external
