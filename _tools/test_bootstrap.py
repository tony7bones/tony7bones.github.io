"""Coverage for the Tony.7.Bones Bootstrap add-on.

The add-on's default.py is a Kodi script (imports xbmc.*, calls run() at import),
so it can't be imported under pytest. These tests instead validate the
deployable, statically-checkable contract: the manifest is well-formed and
version-bumped, the script compiles, every repo zip it references actually
exists in the published repositories/ folder (so installs won't 404), and no
IPTV secret is embedded.
"""

from __future__ import annotations

import ast
import py_compile
import sys
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
import release_lib as rl  # noqa: E402

REPO_ROOT = HERE.parent
ADDON_DIR = REPO_ROOT / "repo" / "script.tony7bones.bootstrap"
ADDON_XML = ADDON_DIR / "addon.xml"
DEFAULT_PY = ADDON_DIR / "default.py"
REPOSITORIES = REPO_ROOT / "repo" / "repositories"


def _addon_root():
    return ET.parse(ADDON_XML).getroot()


def _assign(name):
    """Return the literal value assigned to `name` in default.py (no import/exec)."""
    tree = ast.parse(DEFAULT_PY.read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for tgt in node.targets:
                if isinstance(tgt, ast.Name) and tgt.id == name:
                    return ast.literal_eval(node.value)
    raise AssertionError(f"{name} not found in default.py")


# --------------------------------------------------------------------------- #
# Manifest
# --------------------------------------------------------------------------- #
def test_addon_id_unchanged():
    assert _addon_root().get("id") == "script.tony7bones.bootstrap"


def test_addon_renamed_to_bootstrap():
    assert _addon_root().get("name") == "Tony.7.Bones Bootstrap"


def test_version_bumped_past_old():
    v = _addon_root().get("version")
    assert rl.is_greater(v, "1.0.5"), f"version {v} must exceed the old 1.0.5"


# --------------------------------------------------------------------------- #
# Script
# --------------------------------------------------------------------------- #
def test_default_py_compiles():
    py_compile.compile(str(DEFAULT_PY), doraise=True)


def test_referenced_repo_zips_exist():
    """Every repo zip the bootstrap downloads must exist in repositories/."""
    for zip_name, _repo_id in _assign("REPO_ZIPS"):
        assert (REPOSITORIES / zip_name).exists(), f"missing repo zip: {zip_name}"


def test_repo_zip_count_is_twelve():
    # repository.tony7bones (the 13th) is the host repo, already installed.
    assert len(_assign("REPO_ZIPS")) == 12


def test_known_video_addons_present():
    ids = {addon_id for addon_id, _name in _assign("ADDONS") if addon_id}
    assert {
        "plugin.video.pov",
        "plugin.video.sporthdme",
        "plugin.video.the-loop",
    } <= ids


def test_patch_addon_is_modv2():
    assert _assign("PATCH_ADDON")[0] == "script.tony7bones.modv2.patch"


@pytest.mark.parametrize(
    "needle",
    ["m3uUrl", "epgUrl", "bit.ly", "cutt.ly", "xtream", "get.php", "player_api"],
)
def test_no_iptv_secret_embedded(needle):
    assert needle not in DEFAULT_PY.read_text(), (
        f"secret-ish token in default.py: {needle}"
    )


# --------------------------------------------------------------------------- #
# QA-added coverage
# --------------------------------------------------------------------------- #
def test_repo_zip_inner_id_matches_declared():
    """Each zip's inner addon.xml id must equal the id declared in REPO_ZIPS."""
    import zipfile

    for zip_name, repo_id in _assign("REPO_ZIPS"):
        with zipfile.ZipFile(REPOSITORIES / zip_name) as z:
            axml = next(n for n in z.namelist() if n.endswith("addon.xml"))
            root = ET.fromstring(z.read(axml))
        assert root.get("id") == repo_id, (
            f"{zip_name}: inner id {root.get('id')} != {repo_id}"
        )


def test_documented_gaps_are_empty():
    """The 3 unconfirmed external items stay empty until their ids are provided."""
    assert _assign("EZ_MAINT_REPO_ZIP_URL") == ""
    assert _assign("EZ_MAINT_REPO_ID") == ""
    empty = [a for a in _assign("ADDONS") if not a[0]]
    assert len(empty) == 2, "expected exactly 2 TODO (empty-id) app entries"


def test_skip_filter_yields_only_known_video_apps():
    installable = [a[0] for a in _assign("ADDONS") if a[0]]
    assert installable == [
        "plugin.video.pov",
        "plugin.video.sporthdme",
        "plugin.video.the-loop",
    ]


def test_success_dialog_does_not_overclaim():
    """The final dialog must report counts, not an unconditional 'apps installed'."""
    src = DEFAULT_PY.read_text()
    assert "Repos and apps installed" not in src
    assert "{repo_ok}" in src and "{app_ok}" in src


def test_modv2_patch_is_host_provided():
    """InstallAddon(modv2.patch) can only resolve if it's in the host addons.xml."""
    addons = (REPO_ROOT / "repo" / "addons.xml").read_text()
    assert 'id="script.tony7bones.modv2.patch"' in addons
