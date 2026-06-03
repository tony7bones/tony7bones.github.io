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


def test_patch_is_first_party_direct_extract():
    """The MOD V2 patch is installed by direct extract, NOT via InstallAddon."""
    fp_ids = [a[0] for a in _assign("FIRST_PARTY")]
    assert "script.tony7bones.modv2.patch" in fp_ids
    addon_ids = [a[0] for a in _assign("ADDONS")]
    assert "script.tony7bones.modv2.patch" not in addon_ids


def test_sets_unknown_sources():
    """Bootstrap must enable Unknown sources up front to avoid zip warnings."""
    assert "addons.unknownsources" in DEFAULT_PY.read_text()


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
    """The patch must exist in the host addons.xml and be served statically."""
    addons = (REPO_ROOT / "repo" / "addons.xml").read_text()
    assert 'id="script.tony7bones.modv2.patch"' in addons


# --------------------------------------------------------------------------- #
# Runtime coverage — import default.py under mocked Kodi APIs and run it
# --------------------------------------------------------------------------- #
import importlib.util  # noqa: E402
import json as _json  # noqa: E402
import re as _re  # noqa: E402
import types  # noqa: E402
import urllib.request  # noqa: E402
import zipfile as _zipfile  # noqa: E402


class _FakeResp:
    def __init__(self, data):
        self._data = data

    def read(self):
        return self._data

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


@pytest.fixture
def boot(tmp_path, monkeypatch):
    """Import default.py with fake Kodi modules; return module + recorded state."""
    state = {"installed": set(), "builtins": [], "jsonrpc": [], "ok": []}

    xbmc = types.ModuleType("xbmc")
    xbmc.LOGERROR = 4
    xbmc.log = lambda *a, **k: None
    xbmc.sleep = lambda ms: None

    def _builtin(cmd, wait=False):
        state["builtins"].append(cmd)
        m = _re.match(r"InstallAddon\((.+)\)", cmd)
        if m:
            state["installed"].add(m.group(1))

    xbmc.executebuiltin = _builtin

    def _jsonrpc(s):
        state["jsonrpc"].append(s)
        d = _json.loads(s)
        if d.get("method") == "Addons.SetAddonEnabled":
            state["installed"].add(d["params"]["addonid"])
        return "{}"

    xbmc.executeJSONRPC = _jsonrpc

    xbmcaddon = types.ModuleType("xbmcaddon")

    class _Addon:
        def __init__(self, addon_id=""):
            if addon_id not in state["installed"]:
                raise RuntimeError("not installed")

    xbmcaddon.Addon = _Addon

    xbmcgui = types.ModuleType("xbmcgui")

    class _DP:
        def create(self, *a):
            pass

        def update(self, *a):
            pass

        def iscanceled(self):
            return False

        def close(self):
            pass

    class _Dialog:
        def ok(self, title, msg):
            state["ok"].append((title, msg))

    xbmcgui.DialogProgress = _DP
    xbmcgui.Dialog = _Dialog

    xbmcvfs = types.ModuleType("xbmcvfs")
    temp = tmp_path / "temp"
    addons = tmp_path / "addons"
    temp.mkdir()
    addons.mkdir()

    def _translate(p):
        return p.replace("special://temp/", str(temp) + "/").replace(
            "special://home/addons/", str(addons) + "/"
        )

    xbmcvfs.translatePath = _translate

    for nm, mod in (
        ("xbmc", xbmc),
        ("xbmcaddon", xbmcaddon),
        ("xbmcgui", xbmcgui),
        ("xbmcvfs", xbmcvfs),
    ):
        monkeypatch.setitem(sys.modules, nm, mod)

    def _fake_urlretrieve(url, dst):
        with _zipfile.ZipFile(dst, "w") as z:
            z.writestr("addon/addon.xml", "<addon/>")

    def _fake_urlopen(url, timeout=None):
        return _FakeResp(b'<addon id="script.tony7bones.modv2.patch" version="1.0.3"/>')

    monkeypatch.setattr(urllib.request, "urlretrieve", _fake_urlretrieve)
    monkeypatch.setattr(urllib.request, "urlopen", _fake_urlopen)

    spec = importlib.util.spec_from_file_location("boot_default", DEFAULT_PY)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # run() is __main__-guarded, so this does not run it
    return types.SimpleNamespace(mod=mod, state=state, addons=addons)


def test_set_unknown_sources_sends_jsonrpc(boot):
    boot.mod._set_unknown_sources()
    assert any("addons.unknownsources" in s for s in boot.state["jsonrpc"])


def test_latest_zip_url_resolves_live_version(boot):
    url = boot.mod._latest_zip_url("script.tony7bones.modv2.patch")
    assert url == (
        "https://tony7bones.github.io/repo/script.tony7bones.modv2.patch/"
        "script.tony7bones.modv2.patch-1.0.3.zip"
    )


def test_latest_zip_url_handles_error(boot, monkeypatch):
    def boom(*a, **k):
        raise OSError("no net")

    monkeypatch.setattr(urllib.request, "urlopen", boom)
    assert boot.mod._latest_zip_url("script.tony7bones.modv2.patch") is None


def test_extract_zip_success(boot):
    dp = boot.mod.xbmcgui.DialogProgress()
    assert boot.mod._extract_zip("https://x/repository.foo-1.0.zip", "foo", dp, 50)
    assert (boot.addons / "addon" / "addon.xml").exists()


def test_extract_zip_failure(boot, monkeypatch):
    def boom(url, dst):
        raise OSError("download failed")

    monkeypatch.setattr(urllib.request, "urlretrieve", boom)
    dp = boot.mod.xbmcgui.DialogProgress()
    assert boot.mod._extract_zip("https://x/y.zip", "y", dp, 50) is False


def test_run_first_party_is_prompt_free_apps_use_installaddon(boot):
    boot.mod.run()
    s = boot.state
    # unknown sources enabled up front
    assert any("addons.unknownsources" in j for j in s["jsonrpc"])
    # the patch was direct-extracted + enabled, never InstallAddon'd (no prompt)
    assert not any(
        "InstallAddon(script.tony7bones.modv2.patch)" in b for b in s["builtins"]
    )
    assert "script.tony7bones.modv2.patch" in s["installed"]
    # the 12 repos were enabled too
    assert "repository.umbrella" in s["installed"]
    # third-party apps DO go through InstallAddon
    assert any("InstallAddon(plugin.video.pov)" in b for b in s["builtins"])
    # honest completion summary
    assert s["ok"], "no completion dialog shown"
    _title, msg = s["ok"][-1]
    assert "Repos:" in msg and "Patches:" in msg and "Apps:" in msg


def test_run_aborts_cleanly_on_cancel(boot, monkeypatch):
    monkeypatch.setattr(
        boot.mod.xbmcgui.DialogProgress, "iscanceled", lambda self: True
    )
    boot.mod.run()  # must not raise
    # cancelled before finishing → no completion dialog
    assert boot.state["ok"] == []
