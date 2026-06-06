"""Tests for generate_repo.py"""

import hashlib
import sys
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest

sys.path.insert(0, str(Path(__file__).parent))
import generate_repo as gr

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
        (
            1024 * 1024 * 1024 * 1024,
            "1G",
        ),  # 1TB: exhausts all units, returns remainder in G
    ],
)
def test_fmt_size(n, expected):
    assert gr._fmt_size(n) == expected


# ---------------------------------------------------------------------------
# _fmt_date
# ---------------------------------------------------------------------------


def test_fmt_date_format(tmp_path):
    f = tmp_path / "file.txt"
    f.write_text("x")
    result = gr._fmt_date(str(f))
    # Must match "YYYY-MM-DD HH:MM"
    import re

    assert re.match(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}$", result), repr(result)


def test_fmt_date_missing_file():
    with pytest.raises(FileNotFoundError):
        gr._fmt_date("/nonexistent/path/file.txt")


# ---------------------------------------------------------------------------
# _make_index
# ---------------------------------------------------------------------------


def test_make_index_creates_file(tmp_path):
    rows = ['<a href="../">Parent Directory</a>', '<a href="addon.zip">addon.zip</a>']
    gr._make_index(str(tmp_path), "Test Title", rows)
    index = tmp_path / "index.html"
    assert index.exists()
    content = index.read_text()
    assert "HTML 3.2" in content
    assert "Test Title" in content
    assert "Parent Directory" in content
    assert "addon.zip" in content


def test_make_index_empty_rows(tmp_path):
    gr._make_index(str(tmp_path), "Empty", [])
    content = (tmp_path / "index.html").read_text()
    assert "<pre>" in content


# ---------------------------------------------------------------------------
# _styled_page
# ---------------------------------------------------------------------------


def test_styled_page_structure():
    html = gr._styled_page("My Title", "My Heading", ["file1.zip", "file2.zip"])
    assert "My Title" in html
    assert "My Heading" in html
    assert '<a href="file1.zip">file1.zip</a>' in html
    assert '<a href="file2.zip">file2.zip</a>' in html
    assert "/style.css" in html


def test_styled_page_empty_links():
    html = gr._styled_page("T", "H", [])
    assert "T" in html
    assert "<a" not in html


# ---------------------------------------------------------------------------
# process_addons
# ---------------------------------------------------------------------------


def _make_addon(
    base: Path, addon_id: str, version: str, extra_files: dict = None
) -> Path:
    """Create a minimal addon directory under base."""
    addon_dir = base / addon_id
    addon_dir.mkdir()
    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<addon id="{addon_id}" name="Test" version="{version}" provider-name="test">
  <requires/>
  <extension point="xbmc.python.script" library="default.py"/>
</addon>"""
    (addon_dir / "addon.xml").write_text(xml)
    (addon_dir / "default.py").write_text("# script")
    if extra_files:
        for name, content in extra_files.items():
            (addon_dir / name).write_bytes(
                content if isinstance(content, bytes) else content.encode()
            )
    return addon_dir


def test_process_addons_happy_path(tmp_path, monkeypatch):
    monkeypatch.setattr(gr, "REPO_DIR", str(tmp_path))
    _make_addon(tmp_path, "plugin.test", "1.0.0")

    roots, ids = gr.process_addons(str(tmp_path))

    assert ids == ["plugin.test"]
    assert roots[0].get("id") == "plugin.test"

    zip_path = tmp_path / "plugin.test" / "plugin.test-1.0.0.zip"
    assert zip_path.exists()

    index_path = tmp_path / "plugin.test" / "index.html"
    assert index_path.exists()
    assert "plugin.test-1.0.0.zip" in index_path.read_text()


def test_process_addons_zip_excludes_zip_and_root_index(tmp_path, monkeypatch):
    """Only .zip files and the root index.html are excluded; other .html files are kept."""
    monkeypatch.setattr(gr, "REPO_DIR", str(tmp_path))
    addon_dir = _make_addon(
        tmp_path,
        "plugin.test",
        "1.0.0",
        {
            "old.zip": b"old zip data",
            "changelog.html": b"<html>changelog</html>",
            "data.json": b'{"key": "value"}',
        },
    )
    # also put an html file in a subdir
    sub = addon_dir / "resources"
    sub.mkdir()
    (sub / "page.html").write_bytes(b"<html/>")

    gr.process_addons(str(tmp_path))

    zip_path = tmp_path / "plugin.test" / "plugin.test-1.0.0.zip"
    with zipfile.ZipFile(zip_path) as zf:
        names = zf.namelist()
    assert not any(n.endswith(".zip") for n in names)
    assert "plugin.test/index.html" not in names  # only root index.html excluded
    # non-root .html files ARE included
    assert any("changelog.html" in n for n in names)
    assert any("page.html" in n for n in names)
    assert any("data.json" in n for n in names)


def test_process_addons_skips_malformed_xml(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(gr, "REPO_DIR", str(tmp_path))
    addon_dir = tmp_path / "bad_addon"
    addon_dir.mkdir()
    (addon_dir / "addon.xml").write_text("<unclosed>")

    roots, ids = gr.process_addons(str(tmp_path))
    assert ids == []
    assert "skipping" in capsys.readouterr().out


def test_process_addons_zip_not_rebuilt_when_fresh(tmp_path, monkeypatch):
    """Zip is not recreated when source files are older than the existing zip."""
    monkeypatch.setattr(gr, "REPO_DIR", str(tmp_path))
    _make_addon(tmp_path, "plugin.test", "1.0.0")

    gr.process_addons(str(tmp_path))
    zip_path = tmp_path / "plugin.test" / "plugin.test-1.0.0.zip"
    mtime_after_first = zip_path.stat().st_mtime

    gr.process_addons(str(tmp_path))
    assert zip_path.stat().st_mtime == mtime_after_first


def test_process_addons_zip_rebuilt_when_stale(tmp_path, monkeypatch):
    """Zip is recreated when a source file is newer than the existing zip."""
    import time

    monkeypatch.setattr(gr, "REPO_DIR", str(tmp_path))
    _make_addon(tmp_path, "plugin.test", "1.0.0")

    gr.process_addons(str(tmp_path))
    zip_path = tmp_path / "plugin.test" / "plugin.test-1.0.0.zip"
    mtime_after_first = zip_path.stat().st_mtime

    time.sleep(0.05)
    (tmp_path / "plugin.test" / "default.py").write_text("# updated")

    gr.process_addons(str(tmp_path))
    assert zip_path.stat().st_mtime > mtime_after_first


def test_process_addons_skips_no_addon_xml(tmp_path, monkeypatch):
    monkeypatch.setattr(gr, "REPO_DIR", str(tmp_path))
    (tmp_path / "not_an_addon").mkdir()
    (tmp_path / "not_an_addon" / "default.py").write_text("pass")

    roots, ids = gr.process_addons(str(tmp_path))
    assert ids == []


def test_process_addons_skips_missing_id(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(gr, "REPO_DIR", str(tmp_path))
    addon_dir = tmp_path / "bad_addon"
    addon_dir.mkdir()
    (addon_dir / "addon.xml").write_text(
        '<?xml version="1.0"?><addon version="1.0.0"/>'
    )

    roots, ids = gr.process_addons(str(tmp_path))
    assert ids == []
    assert "skipping" in capsys.readouterr().out


def test_process_addons_skips_missing_version(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(gr, "REPO_DIR", str(tmp_path))
    addon_dir = tmp_path / "bad_addon"
    addon_dir.mkdir()
    (addon_dir / "addon.xml").write_text('<?xml version="1.0"?><addon id="bad_addon"/>')

    roots, ids = gr.process_addons(str(tmp_path))
    assert ids == []
    assert "skipping" in capsys.readouterr().out


def test_process_addons_sorted_order(tmp_path, monkeypatch):
    monkeypatch.setattr(gr, "REPO_DIR", str(tmp_path))
    _make_addon(tmp_path, "plugin.zzz", "1.0.0")
    _make_addon(tmp_path, "plugin.aaa", "1.0.0")

    _, ids = gr.process_addons(str(tmp_path))
    assert ids == ["plugin.aaa", "plugin.zzz"]


# ---------------------------------------------------------------------------
# generate_scripts_index
# ---------------------------------------------------------------------------


def test_generate_scripts_index_creates_html(tmp_path, monkeypatch):
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    (scripts_dir / "myscript-1.0.0.zip").write_bytes(b"zip")
    (scripts_dir / "notazip.txt").write_text("ignored")
    monkeypatch.setattr(gr, "SCRIPTS_DIR", str(scripts_dir))

    gr.generate_scripts_index()

    index = scripts_dir / "index.html"
    assert index.exists()
    content = index.read_text()
    assert "myscript-1.0.0.zip" in content
    assert "notazip.txt" not in content


def test_generate_scripts_index_missing_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(gr, "SCRIPTS_DIR", str(tmp_path / "nonexistent"))
    gr.generate_scripts_index()  # should not raise


def test_generate_scripts_index_empty_dir(tmp_path, monkeypatch):
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    monkeypatch.setattr(gr, "SCRIPTS_DIR", str(scripts_dir))

    gr.generate_scripts_index()
    assert (scripts_dir / "index.html").exists()


def test_generate_scripts_index_uppercase_zip(tmp_path, monkeypatch):
    """Uppercase .ZIP extension must be included, consistent with media index."""
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    (scripts_dir / "script-1.0.ZIP").write_bytes(b"zip")
    monkeypatch.setattr(gr, "SCRIPTS_DIR", str(scripts_dir))

    gr.generate_scripts_index()
    assert "script-1.0.ZIP" in (scripts_dir / "index.html").read_text()


# ---------------------------------------------------------------------------
# generate_media_index
# ---------------------------------------------------------------------------


def test_generate_media_index_creates_html(tmp_path, monkeypatch):
    media_dir = tmp_path / "media"
    media_dir.mkdir()
    (media_dir / "splash.jpg").write_bytes(b"jpg")
    (media_dir / "banner.PNG").write_bytes(b"png")
    (media_dir / "readme.txt").write_text("ignored")
    monkeypatch.setattr(gr, "MEDIA_DIR", str(media_dir))

    gr.generate_media_index()

    content = (media_dir / "index.html").read_text()
    assert "splash.jpg" in content
    assert "banner.PNG" in content
    assert "readme.txt" not in content


def test_generate_media_index_missing_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(gr, "MEDIA_DIR", str(tmp_path / "nonexistent"))
    gr.generate_media_index()  # should not raise


@pytest.mark.parametrize("ext", [".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg"])
def test_generate_media_index_all_extensions(tmp_path, monkeypatch, ext):
    media_dir = tmp_path / "media"
    media_dir.mkdir()
    (media_dir / f"image{ext}").write_bytes(b"data")
    monkeypatch.setattr(gr, "MEDIA_DIR", str(media_dir))

    gr.generate_media_index()
    assert f"image{ext}" in (media_dir / "index.html").read_text()


# ---------------------------------------------------------------------------
# generate — integration
# ---------------------------------------------------------------------------


def _build_repo_tree(base: Path):
    """Scaffold a minimal repo tree for the full generate() integration test."""
    repo = base / "repo"
    repo.mkdir()

    # one addon
    _make_addon(repo, "plugin.hello", "2.0.0")

    # repositories dir with a zip
    repos = repo / "repositories"
    repos.mkdir()
    (repos / "repository.other-1.0.0.zip").write_bytes(b"zip")

    # scripts dir
    scripts = repo / "scripts"
    scripts.mkdir()
    (scripts / "script.setup-1.0.0.zip").write_bytes(b"zip")

    # media dir
    media = repo / "media"
    media.mkdir()
    (media / "splash.jpg").write_bytes(b"jpg")

    return repo


def test_generate_integration(tmp_path, monkeypatch):
    repo = _build_repo_tree(tmp_path)
    monkeypatch.setattr(gr, "REPO_DIR", str(repo))
    monkeypatch.setattr(gr, "REPOS_DIR", str(repo / "repositories"))
    monkeypatch.setattr(gr, "SCRIPTS_DIR", str(repo / "scripts"))
    monkeypatch.setattr(gr, "MEDIA_DIR", str(repo / "media"))

    gr.generate()

    # addons.xml exists and contains the addon
    addons_xml = repo / "addons.xml"
    assert addons_xml.exists()
    tree = ET.parse(str(addons_xml))
    ids = [el.get("id") for el in tree.getroot()]
    assert "plugin.hello" in ids

    # hashes match addons.xml content
    data = addons_xml.read_bytes()
    assert (repo / "addons.xml.sha256").read_text() == hashlib.sha256(data).hexdigest()
    assert (repo / "addons.xml.md5").read_text() == hashlib.md5(data).hexdigest()

    # repositories index lists the zip
    repos_index = (repo / "repositories" / "index.html").read_text()
    assert "repository.other-1.0.0.zip" in repos_index

    # scripts index lists the zip
    scripts_index = (repo / "scripts" / "index.html").read_text()
    assert "script.setup-1.0.0.zip" in scripts_index

    # media index lists the image
    media_index = (repo / "media" / "index.html").read_text()
    assert "splash.jpg" in media_index

    # per-addon zip and index created
    assert (repo / "plugin.hello" / "plugin.hello-2.0.0.zip").exists()
    assert (repo / "plugin.hello" / "index.html").exists()


# ---------------------------------------------------------------------------
# generate_asset_indexes
# ---------------------------------------------------------------------------


def test_generate_asset_indexes_empty_repo(tmp_path, monkeypatch):
    """No asset dirs — runs silently without error."""
    repo = tmp_path / "repo"
    repo.mkdir()
    monkeypatch.setattr(gr, "REPO_DIR", str(repo))
    gr.generate_asset_indexes()  # should not raise


def test_generate_asset_indexes_flat(tmp_path, monkeypatch):
    """Single level: files appear, index.html itself is excluded."""
    repo = tmp_path / "repo"
    asset = repo / "files"
    asset.mkdir(parents=True)
    (asset / "settings.xml").write_text("<settings/>")
    (asset / "readme.txt").write_text("hello")
    monkeypatch.setattr(gr, "REPO_DIR", str(repo))

    gr.generate_asset_indexes()

    content = (asset / "index.html").read_text()
    assert "HTML 3.2" in content
    assert "settings.xml" in content
    assert "readme.txt" in content
    assert content.count("index.html") == 0  # excluded from listing


def test_generate_asset_indexes_nested(tmp_path, monkeypatch):
    """Nested subfolders each get their own index.html."""
    repo = tmp_path / "repo"
    sub = repo / "iptv" / "channels"
    sub.mkdir(parents=True)
    (sub / "channels.m3u").write_text("#EXTM3U")
    monkeypatch.setattr(gr, "REPO_DIR", str(repo))

    gr.generate_asset_indexes()

    # parent lists the subfolder
    parent = (repo / "iptv" / "index.html").read_text()
    assert "channels/" in parent

    # subfolder lists the file
    child = (sub / "index.html").read_text()
    assert "channels.m3u" in child
    assert "Parent Directory" in child


def test_generate_asset_indexes_title_uses_relative_path(tmp_path, monkeypatch):
    """Title must never contain an absolute filesystem path."""
    repo = tmp_path / "repo"
    asset = repo / "iptv"
    asset.mkdir(parents=True)
    (asset / "file.txt").write_text("x")
    monkeypatch.setattr(gr, "REPO_DIR", str(repo))

    gr.generate_asset_indexes()

    content = (asset / "index.html").read_text()
    assert str(tmp_path) not in content  # no absolute path leaked
    assert "Index of" in content


def test_generate_asset_indexes_dirs_before_files(tmp_path, monkeypatch):
    """Subdirectories are listed before files."""
    repo = tmp_path / "repo"
    sub = repo / "assets" / "aaa_subdir"
    sub.mkdir(parents=True)
    (repo / "assets" / "zzz_file.txt").write_text("z")
    monkeypatch.setattr(gr, "REPO_DIR", str(repo))

    gr.generate_asset_indexes()

    content = (repo / "assets" / "index.html").read_text()
    assert content.index("aaa_subdir") < content.index("zzz_file.txt")


def test_generate_asset_indexes_skips_special_and_addon_dirs(tmp_path, monkeypatch):
    """repositories/, scripts/, media/ and addon dirs are not asset-indexed."""
    repo = tmp_path / "repo"
    (repo / "repositories").mkdir(parents=True)
    (repo / "scripts").mkdir()
    (repo / "media").mkdir()
    addon = repo / "plugin.test"
    addon.mkdir()
    (addon / "addon.xml").write_text("<addon/>")
    asset = repo / "iptv"
    asset.mkdir()
    (asset / "file.txt").write_text("x")
    monkeypatch.setattr(gr, "REPO_DIR", str(repo))

    gr.generate_asset_indexes()

    assert not (repo / "repositories" / "index.html").exists()
    assert not (repo / "scripts" / "index.html").exists()
    assert not (repo / "media" / "index.html").exists()
    assert not (repo / "plugin.test" / "index.html").exists()
    assert (repo / "iptv" / "index.html").exists()


# ---------------------------------------------------------------------------
# sync_kodibox — kodibox/ is the human canvas; the build mirrors it into repo/
# ---------------------------------------------------------------------------
def test_kodibox_sync_mirrors_canvas_drops_unowned_and_keeps_canvas_clean(
    tmp_path, monkeypatch
):
    repo = tmp_path / "repo"
    repo.mkdir()
    # an add-on dir (must be left untouched by the sync)
    _make_addon(repo, "plugin.hello", "2.0.0")
    # a served content folder the canvas no longer owns (must be removed)
    (repo / "scripts").mkdir()
    (repo / "scripts" / "old.zip").write_bytes(b"old")

    # the canvas: a sibling of repo/ (sync derives kodibox from REPO_DIR/..)
    canvas = tmp_path / "kodibox"
    (canvas / "repositories").mkdir(parents=True)
    (canvas / "repositories" / "repository.x-1.0.0.zip").write_bytes(b"zip")
    (canvas / "iptv").mkdir()
    (canvas / "iptv" / "groups.xml").write_bytes(b"<x/>")

    monkeypatch.setattr(gr, "REPO_DIR", str(repo))
    monkeypatch.setattr(gr, "REPOS_DIR", str(repo / "repositories"))
    monkeypatch.setattr(gr, "SCRIPTS_DIR", str(repo / "scripts"))
    monkeypatch.setattr(gr, "MEDIA_DIR", str(repo / "media"))

    gr.generate()

    # canvas content mirrored into repo/
    assert (repo / "repositories" / "repository.x-1.0.0.zip").read_bytes() == b"zip"
    assert (repo / "iptv" / "groups.xml").read_bytes() == b"<x/>"
    # index.html generated into repo/, never into the canvas
    assert (repo / "repositories" / "index.html").exists()
    assert (repo / "iptv" / "index.html").exists()
    assert not (canvas / "repositories" / "index.html").exists()
    assert not (canvas / "iptv" / "index.html").exists()
    # canvas stays exactly what we authored — nothing added
    assert {p.name for p in canvas.rglob("*") if p.is_file()} == {
        "repository.x-1.0.0.zip",
        "groups.xml",
    }
    # served folder the canvas no longer owns is dropped; add-on dir untouched
    assert not (repo / "scripts").exists()
    assert (repo / "plugin.hello" / "addon.xml").exists()


def test_kodibox_sync_noop_without_canvas(tmp_path, monkeypatch):
    """No sibling kodibox/ -> sync is a clean no-op (real-repo tests stay sandboxed)."""
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "repositories").mkdir()
    (repo / "repositories" / "keep.zip").write_bytes(b"zip")
    monkeypatch.setattr(gr, "REPO_DIR", str(repo))

    gr.sync_kodibox()

    assert (repo / "repositories" / "keep.zip").exists()
