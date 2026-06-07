"""Tests for generate_repo.py — the dropbox/->root + addons/->zips build."""

import hashlib
import sys
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest

sys.path.insert(0, str(Path(__file__).parent))
import generate_repo as gr


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def _make_addon(
    base: Path, addon_id: str, version: str, extra_files: dict = None
) -> Path:
    """Create a minimal add-on directory under base."""
    addon_dir = base / addon_id
    addon_dir.mkdir(parents=True)
    (addon_dir / "addon.xml").write_text(
        f'<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<addon id="{addon_id}" name="Test" version="{version}" provider-name="test">\n'
        f"  <requires/>\n"
        f'  <extension point="xbmc.python.script" library="default.py"/>\n'
        f"</addon>"
    )
    (addon_dir / "default.py").write_text("# script")
    for name, content in (extra_files or {}).items():
        (addon_dir / name).write_bytes(
            content if isinstance(content, bytes) else content.encode()
        )
    return addon_dir


def _patch_dirs(monkeypatch, root: Path):
    """Point the generator at a sandbox: root + root/addons + root/dropbox."""
    monkeypatch.setattr(gr, "ROOT_DIR", str(root))
    monkeypatch.setattr(gr, "ADDONS_DIR", str(root / "addons"))
    monkeypatch.setattr(gr, "DROPBOX_DIR", str(root / "dropbox"))


# ---------------------------------------------------------------------------
# _fmt_size
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "n, expected",
    [
        (0, "0B"),
        (1, "1B"),
        (1023, "1023B"),
        (1024, "1K"),
        (1025, "1K"),
        (1024 * 1024, "1M"),
        (1024 * 1024 * 1024, "1G"),
        (1024 * 1024 * 1024 * 1024, "1G"),  # exhausts units -> remainder in G
    ],
)
def test_fmt_size(n, expected):
    assert gr._fmt_size(n) == expected


# ---------------------------------------------------------------------------
# _make_index  (HTML 3.2 — Kodi-parseable)
# ---------------------------------------------------------------------------
def test_make_index_creates_file(tmp_path):
    rows = ['<a href="../">Parent Directory</a>', '<a href="addon.zip">addon.zip</a>']
    gr._make_index(str(tmp_path), "Test Title", rows)
    content = (tmp_path / "index.html").read_text()
    assert "HTML 3.2" in content
    assert "Test Title" in content
    assert "Parent Directory" in content
    assert "addon.zip" in content


def test_make_index_empty_rows(tmp_path):
    gr._make_index(str(tmp_path), "Empty", [])
    assert "<pre>" in (tmp_path / "index.html").read_text()


# ---------------------------------------------------------------------------
# process_addons  (addons/ -> reproducible zips + addons.xml roots)
# ---------------------------------------------------------------------------
def test_process_addons_happy_path(tmp_path, monkeypatch):
    _patch_dirs(monkeypatch, tmp_path)
    addons = tmp_path / "addons"
    _make_addon(addons, "plugin.test", "1.0.0")

    roots = gr.process_addons(str(addons))

    assert [r.get("id") for r in roots] == ["plugin.test"]
    assert (addons / "plugin.test" / "plugin.test-1.0.0.zip").exists()
    index = (addons / "plugin.test" / "index.html").read_text()
    assert "plugin.test-1.0.0.zip" in index


def test_process_addons_zip_excludes_zip_and_root_index(tmp_path, monkeypatch):
    """Only .zip and the add-on's own root index.html are excluded from the zip."""
    _patch_dirs(monkeypatch, tmp_path)
    addons = tmp_path / "addons"
    addon_dir = _make_addon(
        addons,
        "plugin.test",
        "1.0.0",
        {"old.zip": b"x", "changelog.html": b"<html/>", "data.json": b"{}"},
    )
    sub = addon_dir / "resources"
    sub.mkdir()
    (sub / "page.html").write_bytes(b"<html/>")

    gr.process_addons(str(addons))

    with zipfile.ZipFile(addon_dir / "plugin.test-1.0.0.zip") as zf:
        names = zf.namelist()
    assert not any(n.endswith(".zip") for n in names)
    assert "plugin.test/index.html" not in names  # add-on root index excluded
    assert any("changelog.html" in n for n in names)  # other html kept
    assert any("page.html" in n for n in names)
    assert any("data.json" in n for n in names)


def test_process_addons_zip_members_location_independent(tmp_path, monkeypatch):
    """Zip member arcnames are rooted at the add-on id — no addons/ or dropbox/
    prefix — so moving the scan root never perturbs the published zip."""
    _patch_dirs(monkeypatch, tmp_path)
    addons = tmp_path / "addons"
    _make_addon(addons, "plugin.test", "1.0.0")
    gr.process_addons(str(addons))
    with zipfile.ZipFile(addons / "plugin.test" / "plugin.test-1.0.0.zip") as zf:
        names = zf.namelist()
    assert all(n.startswith("plugin.test/") for n in names)
    assert not any("addons/" in n or "dropbox/" in n for n in names)


def test_process_addons_zip_is_reproducible(tmp_path, monkeypatch):
    """Building twice yields byte-identical zips (fixed 1980 timestamps)."""
    _patch_dirs(monkeypatch, tmp_path)
    addons = tmp_path / "addons"
    _make_addon(addons, "plugin.test", "1.0.0")
    zip_path = addons / "plugin.test" / "plugin.test-1.0.0.zip"
    gr.process_addons(str(addons))
    first = zip_path.read_bytes()
    gr.process_addons(str(addons))
    assert zip_path.read_bytes() == first


def test_process_addons_skips_hosted(tmp_path, monkeypatch):
    """hosted/ is a pass-through mirror — never built or listed as an add-on."""
    _patch_dirs(monkeypatch, tmp_path)
    addons = tmp_path / "addons"
    hosted = addons / "hosted" / "repository.x"
    hosted.mkdir(parents=True)
    (hosted / "addon.xml").write_text('<addon id="repository.x" version="1.0"/>')
    _make_addon(addons, "plugin.test", "1.0.0")

    roots = gr.process_addons(str(addons))
    assert [r.get("id") for r in roots] == ["plugin.test"]
    assert not (addons / "hosted" / "index.html").exists()


def test_process_addons_skips_malformed_xml(tmp_path, monkeypatch, capsys):
    _patch_dirs(monkeypatch, tmp_path)
    addons = tmp_path / "addons"
    (addons / "bad").mkdir(parents=True)
    (addons / "bad" / "addon.xml").write_text("<unclosed>")
    assert gr.process_addons(str(addons)) == []
    assert "skipping" in capsys.readouterr().out


def test_process_addons_skips_no_addon_xml(tmp_path, monkeypatch):
    _patch_dirs(monkeypatch, tmp_path)
    addons = tmp_path / "addons"
    (addons / "not_an_addon").mkdir(parents=True)
    (addons / "not_an_addon" / "default.py").write_text("pass")
    assert gr.process_addons(str(addons)) == []


def test_process_addons_skips_missing_id(tmp_path, monkeypatch, capsys):
    _patch_dirs(monkeypatch, tmp_path)
    addons = tmp_path / "addons"
    (addons / "bad").mkdir(parents=True)
    (addons / "bad" / "addon.xml").write_text(
        '<?xml version="1.0"?><addon version="1.0"/>'
    )
    assert gr.process_addons(str(addons)) == []
    assert "skipping" in capsys.readouterr().out


def test_process_addons_skips_missing_version(tmp_path, monkeypatch, capsys):
    _patch_dirs(monkeypatch, tmp_path)
    addons = tmp_path / "addons"
    (addons / "bad").mkdir(parents=True)
    (addons / "bad" / "addon.xml").write_text('<?xml version="1.0"?><addon id="bad"/>')
    assert gr.process_addons(str(addons)) == []
    assert "skipping" in capsys.readouterr().out


def test_process_addons_sorted_order(tmp_path, monkeypatch):
    _patch_dirs(monkeypatch, tmp_path)
    addons = tmp_path / "addons"
    _make_addon(addons, "plugin.zzz", "1.0.0")
    _make_addon(addons, "plugin.aaa", "1.0.0")
    roots = gr.process_addons(str(addons))
    assert [r.get("id") for r in roots] == ["plugin.aaa", "plugin.zzz"]


def test_process_addons_missing_dir(tmp_path, monkeypatch):
    _patch_dirs(monkeypatch, tmp_path)
    assert gr.process_addons(str(tmp_path / "nope")) == []


# ---------------------------------------------------------------------------
# write_addons_xml
# ---------------------------------------------------------------------------
def test_write_addons_xml_and_hashes(tmp_path, monkeypatch):
    _patch_dirs(monkeypatch, tmp_path)
    addons = tmp_path / "addons"
    _make_addon(addons, "plugin.test", "1.0.0")
    roots = gr.process_addons(str(addons))

    sha256, md5 = gr.write_addons_xml(roots)

    xml = addons / "addons.xml"
    data = xml.read_bytes()
    assert hashlib.sha256(data).hexdigest() == sha256
    assert hashlib.md5(data).hexdigest() == md5
    assert (addons / "addons.xml.sha256").read_text() == sha256
    assert (addons / "addons.xml.md5").read_text() == md5
    assert "plugin.test" in [el.get("id") for el in ET.parse(str(xml)).getroot()]


# ---------------------------------------------------------------------------
# _index_tree
# ---------------------------------------------------------------------------
def test_index_tree_nested_dirs_before_files(tmp_path, monkeypatch):
    _patch_dirs(monkeypatch, tmp_path)
    top = tmp_path / "iptv"
    (top / "aaa_subdir").mkdir(parents=True)
    (top / "aaa_subdir" / "x.m3u").write_text("#EXTM3U")
    (top / "zzz_file.txt").write_text("z")

    gr._index_tree(str(top))

    content = (top / "index.html").read_text()
    assert content.index("aaa_subdir/") < content.index("zzz_file.txt")
    assert "Parent Directory" in content
    child = (top / "aaa_subdir" / "index.html").read_text()
    assert "x.m3u" in child


def test_index_tree_title_relative_no_abs_path(tmp_path, monkeypatch):
    _patch_dirs(monkeypatch, tmp_path)
    top = tmp_path / "iptv"
    top.mkdir()
    (top / "f.txt").write_text("x")
    gr._index_tree(str(top))
    content = (top / "index.html").read_text()
    assert str(tmp_path) not in content
    assert "Index of /iptv/" in content


def test_index_tree_skips_gitignored(tmp_path, monkeypatch):
    """A git-ignored (secret) file is never listed in the served index."""
    _patch_dirs(monkeypatch, tmp_path)
    top = tmp_path / "iptv"
    top.mkdir()
    (top / "public.xml").write_text("<x/>")
    secret = top / "instance-settings-1.xml"
    secret.write_text("SECRET")
    monkeypatch.setattr(
        gr, "_git_ignored", lambda p: p.endswith("instance-settings-1.xml")
    )

    gr._index_tree(str(top))
    content = (top / "index.html").read_text()
    assert "public.xml" in content
    assert "instance-settings-1.xml" not in content


# ---------------------------------------------------------------------------
# mirror_canvas
# ---------------------------------------------------------------------------
def test_mirror_canvas_mirrors_indexes_prunes_and_keeps_source_clean(
    tmp_path, monkeypatch
):
    _patch_dirs(monkeypatch, tmp_path)
    root = tmp_path
    # an add-on dir at root must be left untouched (it is not canvas)
    (root / "addons").mkdir()
    # a previously-served canvas dir the canvas no longer owns -> pruned
    (root / "scripts").mkdir()
    (root / "scripts" / "old.zip").write_bytes(b"old")

    canvas = root / "dropbox"
    (canvas / "repositories").mkdir(parents=True)
    (canvas / "repositories" / "repository.x-1.0.0.zip").write_bytes(b"zip")
    (canvas / "iptv").mkdir()
    (canvas / "iptv" / "groups.xml").write_bytes(b"<x/>")
    (canvas / "note.txt").write_bytes(b"hi")  # loose root file mirrors too

    listing = gr.mirror_canvas()

    assert (root / "repositories" / "repository.x-1.0.0.zip").read_bytes() == b"zip"
    assert (root / "iptv" / "groups.xml").read_bytes() == b"<x/>"
    assert (root / "note.txt").read_bytes() == b"hi"
    # index.html generated into served copy, NEVER into the pristine canvas
    assert (root / "repositories" / "index.html").exists()
    assert not (canvas / "index.html").exists()
    assert not (canvas / "repositories" / "index.html").exists()
    # canvas stays exactly what we authored
    assert {p.name for p in canvas.rglob("*") if p.is_file()} == {
        "repository.x-1.0.0.zip",
        "groups.xml",
        "note.txt",
    }
    # unowned served dir dropped; protected addons/ untouched
    assert not (root / "scripts").exists()
    assert (root / "addons").exists()
    # listing reports dirs (trailing slash) + loose files
    assert "repositories/" in listing and "iptv/" in listing and "note.txt" in listing


def test_mirror_canvas_propagates_deletions(tmp_path, monkeypatch):
    """A file removed from the canvas disappears from the served mirror."""
    _patch_dirs(monkeypatch, tmp_path)
    canvas = tmp_path / "dropbox"
    (canvas / "media").mkdir(parents=True)
    (canvas / "media" / "a.jpg").write_bytes(b"a")
    (canvas / "media" / "b.jpg").write_bytes(b"b")
    gr.mirror_canvas()
    assert (tmp_path / "media" / "b.jpg").exists()
    (canvas / "media" / "b.jpg").unlink()
    gr.mirror_canvas()
    assert not (tmp_path / "media" / "b.jpg").exists()
    assert (tmp_path / "media" / "a.jpg").exists()


def test_mirror_canvas_skips_gitignored_secret(tmp_path, monkeypatch):
    """A git-ignored secret in the canvas is never copied into the served tree."""
    _patch_dirs(monkeypatch, tmp_path)
    canvas = tmp_path / "dropbox"
    (canvas / "iptv").mkdir(parents=True)
    (canvas / "iptv" / "ok.xml").write_text("<x/>")
    (canvas / "iptv" / "instance-settings-1.xml").write_text("SECRET")
    monkeypatch.setattr(
        gr, "_git_ignored", lambda p: p.endswith("instance-settings-1.xml")
    )

    gr.mirror_canvas()
    assert (tmp_path / "iptv" / "ok.xml").exists()
    assert not (tmp_path / "iptv" / "instance-settings-1.xml").exists()


def test_mirror_canvas_noop_without_dropbox(tmp_path, monkeypatch):
    _patch_dirs(monkeypatch, tmp_path)
    assert gr.mirror_canvas() == []


# ---------------------------------------------------------------------------
# root install zip + root index + injection
# ---------------------------------------------------------------------------
def test_root_install_zip_picks_proxy_zip(tmp_path, monkeypatch):
    _patch_dirs(monkeypatch, tmp_path)
    (tmp_path / "repository.tony7bones-2.2.0.zip").write_bytes(b"z")
    (tmp_path / "other.zip").write_bytes(b"z")
    assert gr._root_install_zip() == "repository.tony7bones-2.2.0.zip"


def test_write_root_index_lists_only_canvas_not_install_zip(tmp_path, monkeypatch):
    _patch_dirs(monkeypatch, tmp_path)
    (tmp_path / "repository.tony7bones-2.2.0.zip").write_bytes(b"z")
    gr.write_root_index(["repositories/", "media/", "note.txt"])
    content = (tmp_path / "index.html").read_text()
    assert "HTML 3.2" in content
    # the install zip is served at the root but NOT listed in the bare-URL canvas
    assert "repository.tony7bones-2.2.0.zip" not in content
    assert '<a href="repositories/">repositories/</a>' in content
    assert '<a href="media/">media/</a>' in content
    assert '<a href="note.txt">note.txt</a>' in content
    # nothing machine leaks into the bare-URL listing
    assert "addons/" not in content
    assert "dropbox/" not in content


def test_inject_install_zip_into_repositories(tmp_path, monkeypatch):
    _patch_dirs(monkeypatch, tmp_path)
    (tmp_path / "repository.tony7bones-2.2.0.zip").write_bytes(b"new")
    repos = tmp_path / "repositories"
    repos.mkdir()
    (repos / "repository.tony7bones-1.0.0.zip").write_bytes(b"old")  # stale proxy zip
    (repos / "repository.other-1.0.0.zip").write_bytes(b"keep")

    gr._inject_install_zip_into_repositories()

    assert (repos / "repository.tony7bones-2.2.0.zip").read_bytes() == b"new"
    assert not (repos / "repository.tony7bones-1.0.0.zip").exists()  # old pruned
    assert (repos / "repository.other-1.0.0.zip").exists()  # third-party kept


# ---------------------------------------------------------------------------
# generate — full integration + determinism
# ---------------------------------------------------------------------------
def _scaffold_full(root: Path):
    addons = root / "addons"
    _make_addon(addons, "plugin.hello", "2.0.0")
    hosted = addons / "hosted" / "repository.x"
    hosted.mkdir(parents=True)
    (hosted / "addon.xml").write_text('<addon id="repository.x" version="1.0"/>')
    (hosted / "repository.x.zip").write_bytes(b"hostedzip")
    canvas = root / "dropbox"
    (canvas / "repositories").mkdir(parents=True)
    (canvas / "repositories" / "repository.other-1.0.0.zip").write_bytes(b"zip")
    (canvas / "media").mkdir()
    (canvas / "media" / "splash.jpg").write_bytes(b"jpg")
    (root / "repository.tony7bones-2.2.0.zip").write_bytes(b"installer")


def test_generate_integration(tmp_path, monkeypatch):
    _patch_dirs(monkeypatch, tmp_path)
    _scaffold_full(tmp_path)

    gr.generate()

    # addons.xml lists the first-party add-on (not hosted, not canvas)
    ids = [
        el.get("id")
        for el in ET.parse(str(tmp_path / "addons" / "addons.xml")).getroot()
    ]
    assert ids == ["plugin.hello"]
    # per-add-on zip + index
    assert (tmp_path / "addons" / "plugin.hello" / "plugin.hello-2.0.0.zip").exists()
    # hosted mirror left verbatim, not indexed
    assert (
        tmp_path / "addons" / "hosted" / "repository.x" / "repository.x.zip"
    ).exists()
    # canvas mirrored to root + indexed
    assert (tmp_path / "repositories" / "repository.other-1.0.0.zip").exists()
    assert (tmp_path / "media" / "splash.jpg").exists()
    assert (tmp_path / "media" / "index.html").exists()
    # proxy installer injected into served repositories/ (the install path)
    assert (tmp_path / "repositories" / "repository.tony7bones-2.2.0.zip").exists()
    # bare-URL root index = canvas 1:1, NOTHING else: no installer zip, no machine dirs
    root_index = (tmp_path / "index.html").read_text()
    assert "repository.tony7bones-2.2.0.zip" not in root_index
    assert '<a href="repositories/">repositories/</a>' in root_index
    assert '<a href="media/">media/</a>' in root_index
    assert "addons/" not in root_index and "dropbox/" not in root_index


def test_generate_is_deterministic(tmp_path, monkeypatch):
    """Build twice -> byte-identical served tree + zips (the CI determinism gate)."""
    _patch_dirs(monkeypatch, tmp_path)
    _scaffold_full(tmp_path)

    def snapshot():
        out = {}
        for p in sorted(tmp_path.rglob("*")):
            if p.is_file() and "dropbox" not in p.relative_to(tmp_path).parts:
                out[str(p.relative_to(tmp_path))] = hashlib.sha256(
                    p.read_bytes()
                ).hexdigest()
        return out

    gr.generate()
    first = snapshot()
    gr.generate()
    assert snapshot() == first
