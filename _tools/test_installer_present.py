"""DEPLOYMENT GATE - the repository.tony7bones installer MUST be produced at the
served ROOT and be browsable in the served ``repositories/`` folder, or a fresh
box has no way to install the repo.

In the static model the installer is no longer committed: ``build_site.py``'s
``place_root_installer`` copies the built static-only add-on zip to the site
root (``repository.tony7bones-<version>.zip``) and into ``repositories/`` every
deploy. This gate exercises that function against a synthetic manifest so a
regression that drops the installer fails loudly in CI.
"""

import sys
import zipfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
import build_site  # noqa: E402
import static_catalog as sc  # noqa: E402


def _site_with_built_repo(tmp_path: Path, version: str = "3.0.0") -> tuple[Path, dict]:
    """A minimal _site/ carrying the built static repo add-on zip + repositories/."""
    site = tmp_path / "_site"
    entry_dir = site / "static" / "repository.tony7bones"
    entry_dir.mkdir(parents=True)
    zip_name = f"repository.tony7bones-{version}.zip"
    with zipfile.ZipFile(entry_dir / zip_name, "w") as zf:
        zf.writestr(
            "repository.tony7bones/addon.xml",
            f'<addon id="repository.tony7bones" version="{version}"/>',
        )
    (site / "repositories").mkdir()
    manifest = {
        "count": 1,
        "entries": {
            "repository.tony7bones": {
                "version": version,
                "zip": f"repository.tony7bones/{zip_name}",
            }
        },
    }
    return site, manifest


def test_installer_placed_at_root_and_in_repositories(tmp_path):
    site, manifest = _site_with_built_repo(tmp_path)
    # a pre-existing repositories/ index that lists only third-party zips
    (site / "repositories" / "repository.other-1.0.zip").write_bytes(b"OTHER")
    (site / "repositories" / "index.html").write_text(
        '<a href="repository.other-1.0.zip">repository.other-1.0.zip</a>'
    )
    build_site.place_root_installer(str(site), manifest)
    installer = "repository.tony7bones-3.0.0.zip"
    assert (site / installer).is_file(), "installer missing at served root"
    assert (site / "repositories" / installer).is_file(), (
        "installer not browsable in repositories/"
    )
    # THE bug this guards: Kodi lists from the index HTML, so the installer
    # must appear in repositories/index.html, not merely exist on disk.
    index = (site / "repositories" / "index.html").read_text()
    assert installer in index, "installer not listed in repositories/index.html"
    assert "repository.other-1.0.zip" in index, "reindex dropped a third-party zip"


def test_root_and_repositories_installers_are_byte_identical(tmp_path):
    site, manifest = _site_with_built_repo(tmp_path)
    build_site.place_root_installer(str(site), manifest)
    installer = "repository.tony7bones-3.0.0.zip"
    assert (site / installer).read_bytes() == (
        site / "repositories" / installer
    ).read_bytes()


def test_stale_root_installer_is_replaced(tmp_path):
    site, manifest = _site_with_built_repo(tmp_path)
    (site / "repository.tony7bones-2.5.0.zip").write_bytes(b"STALE")
    (site / "repositories" / "repository.tony7bones-2.5.0.zip").write_bytes(b"STALE")
    build_site.place_root_installer(str(site), manifest)
    assert not (site / "repository.tony7bones-2.5.0.zip").exists()
    assert not (site / "repositories" / "repository.tony7bones-2.5.0.zip").exists()
    assert (site / "repository.tony7bones-3.0.0.zip").is_file()


def test_missing_repo_entry_fails_loudly(tmp_path):
    site = tmp_path / "_site"
    (site / "static").mkdir(parents=True)
    with pytest.raises(sc.BuildError, match="no installer to serve"):
        build_site.place_root_installer(str(site), {"count": 0, "entries": {}})
