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
    (top / "aaa_subdir" / "x.xml").write_text("<groups/>")
    (top / "zzz_file.txt").write_text("z")

    gr._index_tree(str(top), str(tmp_path))

    content = (top / "index.html").read_text()
    assert content.index("aaa_subdir/") < content.index("zzz_file.txt")
    assert "Parent Directory" in content
    child = (top / "aaa_subdir" / "index.html").read_text()
    assert "x.xml" in child


def test_index_tree_delists_secret_bearing_artifacts(tmp_path, monkeypatch):
    """Structural-secret files (m3u playlists, pvr instance settings, env
    files) never appear in a served listing, even when tracked - their URLs
    must not be advertised and the CI artifact excludes the files anyway
    (build_site.copy_tracked_tree), so a listed name would be a dead link."""
    _patch_dirs(monkeypatch, tmp_path)
    top = tmp_path / "iptv"
    top.mkdir(parents=True)
    (top / "Provider.m3u").write_text("#EXTM3U")
    (top / "instance-settings-1.xml").write_text("<settings/>")
    (top / "groups.xml").write_text("<groups/>")

    gr._index_tree(str(top), str(tmp_path))

    content = (top / "index.html").read_text()
    assert "groups.xml" in content
    assert "Provider.m3u" not in content
    assert "instance-settings-1.xml" not in content


def test_index_tree_title_relative_no_abs_path(tmp_path, monkeypatch):
    _patch_dirs(monkeypatch, tmp_path)
    top = tmp_path / "iptv"
    top.mkdir()
    (top / "f.txt").write_text("x")
    gr._index_tree(str(top), str(tmp_path))
    content = (top / "index.html").read_text()
    assert str(tmp_path) not in content
    assert "Index of /iptv/" in content


def test_index_tree_ignores_output_side_gitignore(tmp_path):
    """THE 2026-07-16 QA blocker: CI builds into _site/, which is itself
    gitignored, so an output-side `git check-ignore` would delist EVERY file
    from every served index (Kodi's File Manager reads the index HTML, so the
    whole canvas would look empty). _index_tree must NOT consult .gitignore -
    ignore-filtering happens at copy time on the SOURCE paths. Regression
    test against a REAL git repo with a gitignored output dir."""
    import subprocess

    repo = tmp_path / "repo"
    site = repo / "_site"
    (site / "media").mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    (repo / ".gitignore").write_text("/_site/\n")
    (site / "media" / "splash.jpg").write_bytes(b"jpg")

    gr._index_tree(str(site / "media"), str(site))

    content = (site / "media" / "index.html").read_text()
    assert "splash.jpg" in content, (
        "output-side gitignore delisted a served file from its index"
    )


# ---------------------------------------------------------------------------
# mirror_canvas (into a TARGET site dir - the CI output; never the repo root)
# ---------------------------------------------------------------------------
def test_mirror_canvas_mirrors_indexes_and_keeps_source_clean(tmp_path, monkeypatch):
    _patch_dirs(monkeypatch, tmp_path)
    site = tmp_path / "_site"
    site.mkdir()

    canvas = tmp_path / "dropbox"
    (canvas / "repositories").mkdir(parents=True)
    (canvas / "repositories" / "repository.x-1.0.0.zip").write_bytes(b"zip")
    (canvas / "iptv").mkdir()
    (canvas / "iptv" / "groups.xml").write_bytes(b"<x/>")
    (canvas / "note.txt").write_bytes(b"hi")  # loose root file mirrors too

    listing = gr.mirror_canvas(str(site))

    assert (site / "repositories" / "repository.x-1.0.0.zip").read_bytes() == b"zip"
    assert (site / "iptv" / "groups.xml").read_bytes() == b"<x/>"
    assert (site / "note.txt").read_bytes() == b"hi"
    # index.html generated into the served copy, NEVER into the pristine canvas
    assert (site / "repositories" / "index.html").exists()
    assert not (canvas / "index.html").exists()
    assert not (canvas / "repositories" / "index.html").exists()
    # index titles are relative to the SITE root, not the machine's paths
    assert "Index of /iptv/" in (site / "iptv" / "index.html").read_text()
    # canvas stays exactly what we authored
    assert {p.name for p in canvas.rglob("*") if p.is_file()} == {
        "repository.x-1.0.0.zip",
        "groups.xml",
        "note.txt",
    }
    # listing reports dirs (trailing slash) + loose files
    assert "repositories/" in listing and "iptv/" in listing and "note.txt" in listing


def test_mirror_canvas_explicit_dropbox_dir(tmp_path):
    """build_site passes the source canvas explicitly - no module-global reliance."""
    site = tmp_path / "out"
    site.mkdir()
    canvas = tmp_path / "elsewhere" / "dropbox"
    (canvas / "media").mkdir(parents=True)
    (canvas / "media" / "a.jpg").write_bytes(b"a")
    listing = gr.mirror_canvas(str(site), str(canvas))
    assert (site / "media" / "a.jpg").read_bytes() == b"a"
    assert listing == ["media/"]


def test_mirror_canvas_replaces_prior_copy(tmp_path, monkeypatch):
    """A re-mirror into the same target replaces each canvas dir wholesale, so
    deletions in the source propagate."""
    _patch_dirs(monkeypatch, tmp_path)
    site = tmp_path / "_site"
    site.mkdir()
    canvas = tmp_path / "dropbox"
    (canvas / "media").mkdir(parents=True)
    (canvas / "media" / "a.jpg").write_bytes(b"a")
    (canvas / "media" / "b.jpg").write_bytes(b"b")
    gr.mirror_canvas(str(site))
    assert (site / "media" / "b.jpg").exists()
    (canvas / "media" / "b.jpg").unlink()
    gr.mirror_canvas(str(site))
    assert not (site / "media" / "b.jpg").exists()
    assert (site / "media" / "a.jpg").exists()


def test_mirror_canvas_skips_gitignored_secret(tmp_path, monkeypatch):
    """A git-ignored secret in the canvas is never copied into the served tree."""
    _patch_dirs(monkeypatch, tmp_path)
    site = tmp_path / "_site"
    site.mkdir()
    canvas = tmp_path / "dropbox"
    (canvas / "iptv").mkdir(parents=True)
    (canvas / "iptv" / "ok.xml").write_text("<x/>")
    (canvas / "iptv" / "instance-settings-1.xml").write_text("SECRET")
    monkeypatch.setattr(
        gr, "_git_ignored", lambda p: p.endswith("instance-settings-1.xml")
    )

    gr.mirror_canvas(str(site))
    assert (site / "iptv" / "ok.xml").exists()
    assert not (site / "iptv" / "instance-settings-1.xml").exists()


def test_mirror_canvas_noop_without_dropbox(tmp_path, monkeypatch):
    _patch_dirs(monkeypatch, tmp_path)
    assert gr.mirror_canvas(str(tmp_path / "out")) == []


# ---------------------------------------------------------------------------
# root index + robots (written into the target site dir)
# ---------------------------------------------------------------------------
def test_write_root_index_links_present_but_css_hidden(tmp_path, monkeypatch):
    _patch_dirs(monkeypatch, tmp_path)
    (tmp_path / "repository.tony7bones-2.2.0.zip").write_bytes(b"z")
    gr.write_root_index(str(tmp_path), ["repositories/", "media/", "note.txt"])
    content = (tmp_path / "index.html").read_text()
    # HTML 3.2 so Kodi parses it; the canvas links ARE present (Kodi scans href=
    # and ignores CSS) so the bare URL stays browsable from the root...
    assert "HTML 3.2" in content
    assert '<a href="repositories/">repositories/</a>' in content
    assert '<a href="media/">media/</a>' in content
    assert '<a href="note.txt">note.txt</a>' in content
    # ...but a <style> block hides them from a web browser.
    assert "display:none" in content
    # the page carries no visible title (empty <title>, no <h1>)
    assert "<title></title>" in content
    assert "<h1>" not in content
    # the install zip is served at the root but still NOT advertised here
    assert "repository.tony7bones-2.2.0.zip" not in content


def test_write_robots_disallows_all(tmp_path, monkeypatch):
    _patch_dirs(monkeypatch, tmp_path)
    gr.write_robots(str(tmp_path))
    content = (tmp_path / "robots.txt").read_text()
    assert content == "User-agent: *\nDisallow: /\n"


# ---------------------------------------------------------------------------
# superseded-zip pruning (old versions never accumulate in the tree)
# ---------------------------------------------------------------------------
def test_zip_addon_prunes_superseded_versions(tmp_path, monkeypatch):
    _patch_dirs(monkeypatch, tmp_path)
    addons = tmp_path / "addons"
    addon_dir = _make_addon(addons, "plugin.test", "2.0.0")
    (addon_dir / "plugin.test-1.0.0.zip").write_bytes(b"old")
    (addon_dir / "plugin.test-1.5.0.zip").write_bytes(b"old")
    # a different add-on's zip (or arbitrary data zip) is NOT ours to prune
    (addon_dir / "plugin.other-1.0.0.zip").write_bytes(b"foreign")

    gr.process_addons(str(addons))

    assert (addon_dir / "plugin.test-2.0.0.zip").exists()
    assert not (addon_dir / "plugin.test-1.0.0.zip").exists()
    assert not (addon_dir / "plugin.test-1.5.0.zip").exists()
    assert (addon_dir / "plugin.other-1.0.0.zip").exists()


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
    # the served canvas mirror is a CI build product now - generate() must NOT
    # write any of it into the repo (no mirror dirs, no root index, no robots)
    assert not (tmp_path / "repositories").exists()
    assert not (tmp_path / "media").exists()
    assert not (tmp_path / "index.html").exists()
    assert not (tmp_path / "robots.txt").exists()


def test_mirror_into_site_dir_integration(tmp_path, monkeypatch):
    """The build_site.py sequence: mirror + root index + robots into an output
    dir, canvas links present but CSS-hidden, machine dirs not advertised."""
    _patch_dirs(monkeypatch, tmp_path)
    _scaffold_full(tmp_path)
    site = tmp_path / "_site"
    site.mkdir()

    listing = gr.mirror_canvas(str(site))
    gr.write_root_index(str(site), listing)
    gr.write_robots(str(site))

    assert (site / "repositories" / "repository.other-1.0.0.zip").exists()
    assert (site / "media" / "splash.jpg").exists()
    assert (site / "media" / "index.html").exists()
    root_index = (site / "index.html").read_text()
    assert "display:none" in root_index
    assert '<a href="repositories/">repositories/</a>' in root_index
    assert '<a href="media/">media/</a>' in root_index
    assert "addons/" not in root_index and "dropbox/" not in root_index
    assert (site / "robots.txt").read_text() == "User-agent: *\nDisallow: /\n"
    # the canvas folders are browsable (their own indexes are intact)
    assert (
        '<a href="repository.other-1.0.0.zip">'
        in (site / "repositories" / "index.html").read_text()
    )


def test_generate_is_deterministic(tmp_path, monkeypatch):
    """Build twice -> byte-identical committed artifacts (the CI staleness gate)."""
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
