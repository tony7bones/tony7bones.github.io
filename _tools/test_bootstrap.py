"""Coverage for the Tony.7.Bones Bootstrap add-on.

Two layers:

* Static contract — manifest is well-formed and version-bumped, the script
  compiles, every repo zip it references exists in the published repositories/
  folder (so installs won't 404), and no IPTV secret is embedded.
* Runtime behavior — default.py is imported under mocked Kodi modules (run() is
  __main__-guarded, so import is side-effect-free) and the prompt-free resolver
  is exercised directly: dependency ordering, system-prefix skip, already-
  installed skip, cyclic-dep termination, unresolved/extract-failure recording,
  and a full run() that asserts zero InstallAddon prompts.
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


def test_addon_name_is_original():
    assert _addon_root().get("name") == "Tony 7 Bones Setup"


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


def test_addons_are_plain_id_strings_no_labels():
    """No display-name labels: ADDONS and FIRST_PARTY are lists of id strings."""
    for item in _assign("ADDONS"):
        assert isinstance(item, str), f"ADDONS entry is not a bare id: {item!r}"
    for item in _assign("FIRST_PARTY"):
        assert isinstance(item, str), f"FIRST_PARTY entry is not a bare id: {item!r}"


def test_known_video_addons_present():
    ids = set(_assign("ADDONS"))
    assert {
        "plugin.video.pov",
        "plugin.video.sporthdme",
        "plugin.video.the-loop",
    } <= ids


def test_patch_is_first_party_direct_extract():
    """The MOD V2 patch is installed by direct extract, NOT via InstallAddon."""
    assert "script.tony7bones.modv2.patch" in _assign("FIRST_PARTY")
    assert "script.tony7bones.modv2.patch" not in _assign("ADDONS")


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
    """EZ Maintenance+ repo + Real-Debrid stay unset until their ids are provided."""
    assert _assign("EZ_MAINT_REPO_ZIP_URL") == ""
    assert _assign("EZ_MAINT_REPO_ID") == ""
    assert all(_assign("ADDONS")), "ADDONS must contain no empty ids"


def test_addons_is_exactly_the_three_video_apps():
    assert _assign("ADDONS") == [
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
import gzip  # noqa: E402
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
    assert boot.mod._extract_zip("https://x/repository.foo-1.0.zip", dp, 50)
    assert (boot.addons / "addon" / "addon.xml").exists()


def test_extract_zip_failure(boot, monkeypatch):
    def boom(url, dst):
        raise OSError("download failed")

    monkeypatch.setattr(urllib.request, "urlretrieve", boom)
    dp = boot.mod.xbmcgui.DialogProgress()
    assert boot.mod._extract_zip("https://x/y.zip", dp, 50) is False


# --- resolver units --------------------------------------------------------- #
def test_zip_url_standard_layout(boot):
    assert boot.mod._zip_url("https://r/x/dir", "plugin.video.pov", "1.2.3") == (
        "https://r/x/dir/plugin.video.pov/plugin.video.pov-1.2.3.zip"
    )


def test_download_text_gunzips(boot, monkeypatch):
    payload = gzip.compress(b"<addons/>")

    class _R:
        def read(self):
            return payload

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(urllib.request, "urlopen", lambda url, timeout=None: _R())
    assert boot.mod._download_text("https://x/addons.xml.gz") == "<addons/>"


def test_build_index_merges_repo_addonsxml(boot, monkeypatch):
    monkeypatch.setattr(
        boot.mod, "_repo_dirs", lambda rid: [("https://i/addons.xml", "https://d")]
    )
    monkeypatch.setattr(
        boot.mod,
        "_download_text",
        lambda url: (
            '<addons><addon id="plugin.video.pov" version="1.0">'
            '<requires><import addon="script.module.x" version="1"/></requires>'
            "</addon></addons>"
        ),
    )
    index = boot.mod._build_index(["repository.foo"])
    assert index["plugin.video.pov"] == ("1.0", "https://d", ["script.module.x"])


def test_install_tree_extracts_deps_then_app_skips_system_and_installed(
    boot, monkeypatch
):
    pulled = []
    monkeypatch.setattr(
        boot.mod, "_extract_zip", lambda url, dialog, pct: pulled.append(url) or True
    )
    index = {
        "plugin.video.pov": ("1.0", "https://d", ["script.module.dep", "xbmc.python"]),
        "script.module.dep": ("2.0", "https://d", []),
    }
    done, failed = set(), set()
    dp = boot.mod.xbmcgui.DialogProgress()
    assert boot.mod._install_tree("plugin.video.pov", index, done, failed, dp, 0)
    # dependency extracted before the app; system dep (xbmc.python) skipped
    assert pulled == [
        "https://d/script.module.dep/script.module.dep-2.0.zip",
        "https://d/plugin.video.pov/plugin.video.pov-1.0.zip",
    ]
    assert done == {"plugin.video.pov", "script.module.dep"}
    assert failed == set()


def test_install_tree_handles_cyclic_deps_without_crashing(boot, monkeypatch):
    """A <-> B dependency cycle must terminate, not RecursionError."""
    pulled = []
    monkeypatch.setattr(
        boot.mod, "_extract_zip", lambda url, dialog, pct: pulled.append(url) or True
    )
    index = {
        "plugin.video.a": ("1.0", "https://d", ["plugin.video.b"]),
        "plugin.video.b": ("1.0", "https://d", ["plugin.video.a"]),
    }
    done, failed = set(), set()
    dp = boot.mod.xbmcgui.DialogProgress()
    assert boot.mod._install_tree("plugin.video.a", index, done, failed, dp, 0)
    assert done == {"plugin.video.a", "plugin.video.b"}
    assert failed == set()
    assert len(pulled) == 2  # each extracted exactly once despite the cycle


def test_install_tree_skips_already_installed_dep(boot, monkeypatch):
    """An indexed dep that is already installed is recorded done, not re-extracted."""
    pulled = []
    monkeypatch.setattr(
        boot.mod, "_extract_zip", lambda url, dialog, pct: pulled.append(url) or True
    )
    boot.state["installed"].add("script.module.dep")  # pre-installed
    index = {
        "plugin.video.pov": ("1.0", "https://d", ["script.module.dep"]),
        "script.module.dep": ("2.0", "https://d", []),
    }
    done, failed = set(), set()
    dp = boot.mod.xbmcgui.DialogProgress()
    assert boot.mod._install_tree("plugin.video.pov", index, done, failed, dp, 0)
    # only the app is extracted; the installed dep is skipped
    assert pulled == ["https://d/plugin.video.pov/plugin.video.pov-1.0.zip"]
    assert "script.module.dep" in done
    assert failed == set()


def test_install_tree_records_app_in_failed_when_extract_fails(boot, monkeypatch):
    """If a resolved app's zip 404s, it lands in failed — no silent success."""
    monkeypatch.setattr(boot.mod, "_extract_zip", lambda url, dialog, pct: False)
    index = {"plugin.video.pov": ("1.0", "https://d", [])}
    done, failed = set(), set()
    dp = boot.mod.xbmcgui.DialogProgress()
    assert (
        boot.mod._install_tree("plugin.video.pov", index, done, failed, dp, 0) is False
    )
    assert "plugin.video.pov" in failed
    assert "plugin.video.pov" not in done


def test_repo_dirs_parses_multiple_dir_blocks(boot):
    """Repos like umbrella ship matrix/nexus/omega <dir> blocks — index them all."""
    rd = boot.addons / "repository.multi"
    rd.mkdir()
    (rd / "addon.xml").write_text(
        '<addon id="repository.multi">'
        '<extension point="xbmc.addon.repository">'
        "<dir><info>https://i/matrix/addons.xml</info>"
        "<datadir>https://d/matrix/</datadir></dir>"
        "<dir><info>https://i/omega/addons.xml</info>"
        "<datadir>https://d/omega/</datadir></dir>"
        "</extension></addon>"
    )
    assert list(boot.mod._repo_dirs("repository.multi")) == [
        ("https://i/matrix/addons.xml", "https://d/matrix"),
        ("https://i/omega/addons.xml", "https://d/omega"),
    ]


def test_repo_dirs_malformed_xml_yields_nothing(boot):
    """A corrupt repo addon.xml must not crash the index build."""
    rd = boot.addons / "repository.broken"
    rd.mkdir()
    (rd / "addon.xml").write_text("<addon><not-closed>")
    assert list(boot.mod._repo_dirs("repository.broken")) == []


def test_repo_dirs_parses_installed_repo(boot):
    rd = boot.addons / "repository.test"
    rd.mkdir()
    (rd / "addon.xml").write_text(
        '<addon id="repository.test">'
        '<extension point="xbmc.addon.repository">'
        '<dir><info compressed="false">https://i/addons.xml</info>'
        '<datadir zip="true">https://d/</datadir></dir>'
        "</extension></addon>"
    )
    assert list(boot.mod._repo_dirs("repository.test")) == [
        ("https://i/addons.xml", "https://d")
    ]


def test_repo_dirs_missing_repo_yields_nothing(boot):
    assert list(boot.mod._repo_dirs("repository.absent")) == []


def test_download_text_error_returns_empty(boot, monkeypatch):
    def boom(url, timeout=None):
        raise OSError("net")

    monkeypatch.setattr(urllib.request, "urlopen", boom)
    assert boot.mod._download_text("https://x/addons.xml") == ""


def test_install_tree_reports_unresolved(boot, monkeypatch):
    monkeypatch.setattr(boot.mod, "_extract_zip", lambda *a: True)
    done, failed = set(), set()
    dp = boot.mod.xbmcgui.DialogProgress()
    assert (
        boot.mod._install_tree("plugin.video.missing", {}, done, failed, dp, 0) is False
    )
    assert "plugin.video.missing" in failed


def test_run_is_fully_prompt_free(boot, monkeypatch):
    # apps resolve from a known index; nothing should hit InstallAddon
    monkeypatch.setattr(
        boot.mod,
        "_build_index",
        lambda repo_ids: {aid: ("1.0", "https://d", []) for aid in boot.mod.ADDONS},
    )
    boot.mod.run()
    s = boot.state
    assert any("addons.unknownsources" in j for j in s["jsonrpc"])
    # NOTHING goes through InstallAddon — zero prompts
    assert not any(b.startswith("InstallAddon(") for b in s["builtins"])
    # patch + apps all extracted and enabled
    assert "script.tony7bones.modv2.patch" in s["installed"]
    assert "plugin.video.pov" in s["installed"]
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
