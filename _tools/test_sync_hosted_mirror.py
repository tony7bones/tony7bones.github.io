"""sync_hosted_mirror.py: the hosted mirror follows the source repo's latest release.

Every GitHub call and every download is faked; nothing here touches the
network. The mirror id is synthetic, same convention as the gate's tests.
"""

import io
import json
import sys
import zipfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))

import sync_hosted_mirror as sync  # noqa: E402

ADDON = "script.testaddon"
OWNER, REPO = "moquette", "kodi-testaddon"
TEMPLATE = f"https://github.com/{OWNER}/{REPO}/releases/download/v{{version}}/{{id}}-{{version}}.zip"


def _addon_xml(version: str, news: str = "") -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        f'<addon id="{ADDON}" name="Test" version="{version}" provider-name="test">\n'
        f"  <extension point=\"xbmc.addon.metadata\"><news>{news}</news></extension>\n"
        "</addon>\n"
    )


def _zip_with_addon_xml(xml: str, member_dir: str = ADDON) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(f"{member_dir}/addon.xml", xml)
        zf.writestr(f"{member_dir}/default.py", "pass\n")
    return buf.getvalue()


@pytest.fixture
def sandbox(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    (root / "_tools").mkdir(parents=True)
    (root / "_tools" / "catalog.json").write_text(
        json.dumps([{"id": ADDON, "assets": {"zip": TEMPLATE}}])
    )
    mirror = root / "addons" / "hosted" / ADDON / "addon.xml"
    mirror.parent.mkdir(parents=True)
    mirror.write_text(_addon_xml("1.0.0", "v1.0.0: first"))
    return root


def _release(version: str) -> dict:
    return {
        "tag_name": f"v{version}",
        "assets": [
            {
                "name": f"{ADDON}-{version}.zip",
                "browser_download_url": TEMPLATE.format(id=ADDON, version=version),
            }
        ],
    }


def _stub_latest(monkeypatch, release):
    monkeypatch.setattr(sync.gate, "get_latest_release", lambda o, r, t: release)


def test_bumps_mirror_to_latest_release_with_the_packaged_addon_xml(sandbox, monkeypatch):
    _stub_latest(monkeypatch, _release("1.1.0"))
    new_xml = _addon_xml("1.1.0", "v1.1.0: second\nv1.0.0: first")
    fetched = []

    def fetch(url, token):
        fetched.append(url)
        return _zip_with_addon_xml(new_xml)

    bumped, messages = sync.sync(str(sandbox), None, fetch=fetch)

    assert bumped == [(ADDON, "1.1.0")]
    assert fetched == [TEMPLATE.format(id=ADDON, version="1.1.0")]
    mirror = (sandbox / "addons" / "hosted" / ADDON / "addon.xml").read_text()
    assert mirror == new_xml, "the whole packaged manifest is copied, news included"
    assert "bumped mirror 1.0.0 -> 1.1.0" in messages[0]


def test_dry_run_reports_but_writes_nothing(sandbox, monkeypatch):
    _stub_latest(monkeypatch, _release("1.1.0"))
    before = (sandbox / "addons" / "hosted" / ADDON / "addon.xml").read_text()

    bumped, messages = sync.sync(
        str(sandbox),
        None,
        dry_run=True,
        fetch=lambda u, t: _zip_with_addon_xml(_addon_xml("1.1.0")),
    )

    assert bumped == [(ADDON, "1.1.0")]
    assert "would bump" in messages[0]
    assert (sandbox / "addons" / "hosted" / ADDON / "addon.xml").read_text() == before


def test_current_mirror_is_left_alone_and_nothing_is_downloaded(sandbox, monkeypatch):
    _stub_latest(monkeypatch, _release("1.0.0"))

    def fetch(url, token):
        raise AssertionError("no download expected")

    bumped, messages = sync.sync(str(sandbox), None, fetch=fetch)
    assert bumped == []
    assert "already matches" in messages[0]


def test_never_downgrades_a_mirror_ahead_of_the_latest_release(sandbox, monkeypatch):
    _stub_latest(monkeypatch, _release("0.9.0"))
    before = (sandbox / "addons" / "hosted" / ADDON / "addon.xml").read_text()

    bumped, messages = sync.sync(
        str(sandbox), None, fetch=lambda u, t: _zip_with_addon_xml(_addon_xml("0.9.0"))
    )
    assert bumped == []
    assert "not downgrading" in messages[0]
    assert (sandbox / "addons" / "hosted" / ADDON / "addon.xml").read_text() == before


def test_release_missing_the_expected_asset_fails_loudly(sandbox, monkeypatch):
    rel = _release("1.1.0")
    rel["assets"] = [{"name": "wrong.zip", "browser_download_url": "https://x/wrong.zip"}]
    _stub_latest(monkeypatch, rel)
    with pytest.raises(sync.SyncError, match="has no asset"):
        sync.sync(str(sandbox), None, fetch=lambda u, t: b"")


def test_zip_without_addon_xml_fails_loudly(sandbox, monkeypatch):
    _stub_latest(monkeypatch, _release("1.1.0"))
    with pytest.raises(sync.SyncError, match="has no"):
        sync.sync(
            str(sandbox),
            None,
            fetch=lambda u, t: _zip_with_addon_xml(_addon_xml("1.1.0"), member_dir="other"),
        )


def test_packaged_version_must_match_the_release_tag(sandbox, monkeypatch):
    _stub_latest(monkeypatch, _release("1.1.0"))
    with pytest.raises(sync.SyncError, match="declaring 1.2.0"):
        sync.sync(
            str(sandbox), None, fetch=lambda u, t: _zip_with_addon_xml(_addon_xml("1.2.0"))
        )


def test_no_releases_at_all_fails_loudly(sandbox, monkeypatch):
    _stub_latest(monkeypatch, None)
    with pytest.raises(sync.SyncError, match="no published releases"):
        sync.sync(str(sandbox), None, fetch=lambda u, t: b"")


def test_github_output_carries_the_bump_list(tmp_path, monkeypatch):
    out = tmp_path / "out"
    monkeypatch.setenv("GITHUB_OUTPUT", str(out))
    sync.write_github_output([(ADDON, "1.1.0")])
    assert out.read_text() == f"bumped={ADDON}=1.1.0\n"
    sync.write_github_output([])
    assert out.read_text().endswith("bumped=\n")


def test_main_exit_codes(sandbox, monkeypatch, capsys):
    monkeypatch.setattr(sync.gate, "hosted_release_entries", lambda root=None: _entries(sandbox))
    monkeypatch.setattr(sync, "upstream_indexed_entries", lambda root=None: [])
    monkeypatch.setattr(sync, "_fetch_bytes", lambda u, t: _zip_with_addon_xml(_addon_xml("1.1.0")))
    _stub_latest(monkeypatch, _release("1.1.0"))
    assert sync.main(["--dry-run"]) == 0
    assert "would bump" in capsys.readouterr().out

    _stub_latest(monkeypatch, None)
    assert sync.main([]) == 1
    assert "ERROR" in capsys.readouterr().err


def _entries(root: Path) -> list:
    return [
        {
            "id": ADDON,
            "owner": OWNER,
            "repo": REPO,
            "asset_template": "{id}-{version}.zip",
            "addon_xml": str(root / "addons" / "hosted" / ADDON / "addon.xml"),
            "waiver_path": str(root / "addons" / "hosted" / ADDON / "release-sync-waiver.json"),
        }
    ]


# --------------------------------------------------------------------------- #
# upstream-indexed mirrors (plugin.video.pov shape): the version comes from the
# upstream repository's own addons.xml, never from a hand-typed number here.
# --------------------------------------------------------------------------- #
POV = "plugin.video.test"
INDEX = "https://upstream.example/repo/packages/addons.xml"
POV_ZIP = "https://upstream.example/repo/{id}/{id}-{version}.zip"


def _index_xml(version: str) -> bytes:
    return (
        '<?xml version="1.0" encoding="UTF-8"?><addons>'
        f'<addon id="other.addon" version="9.9.9"/><addon id="{POV}" version="{version}"/>'
        "</addons>"
    ).encode()


def _pov_xml(version: str) -> str:
    return _addon_xml(version).replace(ADDON, POV)


@pytest.fixture
def indexed_sandbox(sandbox: Path) -> Path:
    entries = json.loads((sandbox / "_tools" / "catalog.json").read_text())
    entries.append({"id": POV, "assets": {"zip": POV_ZIP}, "upstream_index": INDEX})
    (sandbox / "_tools" / "catalog.json").write_text(json.dumps(entries))
    mirror = sandbox / "addons" / "hosted" / POV / "addon.xml"
    mirror.parent.mkdir(parents=True)
    mirror.write_text(_pov_xml("6.08.15"))
    return sandbox


def test_indexed_entries_are_discovered_only_when_the_catalog_names_an_index(indexed_sandbox):
    found = sync.upstream_indexed_entries(str(indexed_sandbox))
    assert [e["id"] for e in found] == [POV]
    assert found[0]["index"] == INDEX


def test_indexed_mirror_follows_the_upstream_index_version(indexed_sandbox, monkeypatch):
    _stub_latest(monkeypatch, _release("1.0.0"))
    fetched = []

    def fetch(url, token):
        fetched.append(url)
        if url == INDEX:
            return _index_xml("6.09.06")
        return _zip_with_addon_xml(_pov_xml("6.09.06"), member_dir=POV)

    bumped, messages = sync.sync(str(indexed_sandbox), None, fetch=fetch)

    assert bumped == [(POV, "6.09.06")]
    assert fetched == [INDEX, POV_ZIP.format(id=POV, version="6.09.06")]
    mirror = (indexed_sandbox / "addons" / "hosted" / POV / "addon.xml").read_text()
    assert 'version="6.09.06"' in mirror


def test_indexed_mirror_current_is_left_alone(indexed_sandbox, monkeypatch):
    _stub_latest(monkeypatch, _release("1.0.0"))

    def fetch(url, token):
        assert url == INDEX, "only the index is read when nothing changed"
        return _index_xml("6.08.15")

    bumped, messages = sync.sync(str(indexed_sandbox), None, fetch=fetch)
    assert bumped == []
    assert any("already matches upstream index" in m for m in messages)


def test_indexed_mirror_never_downgrades(indexed_sandbox, monkeypatch):
    _stub_latest(monkeypatch, _release("1.0.0"))
    bumped, messages = sync.sync(
        str(indexed_sandbox), None, fetch=lambda u, t: _index_xml("6.00.00")
    )
    assert bumped == []
    assert any("not downgrading" in m for m in messages)


def test_index_without_the_addon_fails_loudly(indexed_sandbox, monkeypatch):
    _stub_latest(monkeypatch, _release("1.0.0"))
    with pytest.raises(sync.SyncError, match="does not list"):
        sync.sync(str(indexed_sandbox), None, fetch=lambda u, t: b"<addons/>")


def test_index_that_is_not_xml_fails_loudly(indexed_sandbox, monkeypatch):
    _stub_latest(monkeypatch, _release("1.0.0"))
    with pytest.raises(sync.SyncError, match="not XML"):
        sync.sync(str(indexed_sandbox), None, fetch=lambda u, t: b"<html>404")
