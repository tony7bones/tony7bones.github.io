"""Coverage for the Video Add-ons Setup add-on (script.tony7bones.video).

Two layers, mirroring test_bootstrap.py:

* Static contract — the manifest is well-formed (id / name / version), the
  script compiles, the four target apps are present in the right order with the
  first three preselected, the picker uses a multiselect dialog, the resolver
  works off the INSTALLED repositories (not fixed source urls), it self-removes
  after a run, and no IPTV secret is embedded.
* Runtime behaviour — default.py is imported under mocked Kodi modules (run() is
  __main__-guarded, so import is side-effect-free) and the install flow is
  exercised directly: repo discovery reads the installed repository.* dirs, the
  closure walks dependencies, and the selected apps install + enable.
"""

from __future__ import annotations

import ast
import gzip as _gzip
import importlib.util
import io
import json as _json
import py_compile
import sys
import types
import urllib.request
import zipfile as _zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest

HERE = Path(__file__).parent
REPO_ROOT = HERE.parent
ADDON_DIR = REPO_ROOT / "repo" / "script.tony7bones.video"
ADDON_XML = ADDON_DIR / "addon.xml"
DEFAULT_PY = ADDON_DIR / "default.py"


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
def test_addon_id():
    assert _addon_root().get("id") == "script.tony7bones.video"


def test_addon_name():
    assert _addon_root().get("name") == "Video Add-ons Setup"


def test_addon_version_is_initial():
    assert _addon_root().get("version") == "1.0.0"


def test_addon_provider_and_license():
    root = _addon_root()
    assert root.get("provider-name") == "tony7bones"
    lic = root.find("extension[@point='xbmc.addon.metadata']/license")
    assert lic is not None and lic.text == "GPL-2.0-or-later"


def test_is_a_proper_program_addon():
    ext = _addon_root().find("extension[@point='xbmc.python.script']")
    assert ext is not None, "must keep the xbmc.python.script extension (runnable)"
    assert ext.get("library") == "default.py"
    provides = [p.text for p in ext.findall("provides")]
    assert provides == ["executable"], (
        f"must declare <provides>executable</provides>; got {provides!r}"
    )


def test_has_news():
    news = _addon_root().find("extension[@point='xbmc.addon.metadata']/news")
    assert news is not None and news.text and news.text.strip()


def test_icon_present():
    assert (ADDON_DIR / "icon.png").exists(), "must ship an icon.png"


# --------------------------------------------------------------------------- #
# Script — static contract
# --------------------------------------------------------------------------- #
def test_default_py_compiles():
    py_compile.compile(str(DEFAULT_PY), doraise=True)


def test_target_apps_present_in_order():
    """Exactly the four target ids, in this order."""
    apps = _assign("APPS")
    ids = [aid for _label, aid in apps]
    assert ids == [
        "plugin.video.pov",
        "plugin.video.the-loop",
        "plugin.video.sporthdme",
        "plugin.video.umbrella",
    ]


def test_app_labels_match():
    labels = [label for label, _aid in _assign("APPS")]
    assert labels == ["POV", "The Loop", "Sports HD", "Umbrella"]


def test_preselect_is_first_three():
    """POV, The Loop, Sports HD checked by default; Umbrella unchecked."""
    assert _assign("PRESELECT") == [0, 1, 2]
    apps = _assign("APPS")
    # the unchecked one is Umbrella
    assert apps[3][1] == "plugin.video.umbrella"


def test_uses_multiselect_dialog():
    src = DEFAULT_PY.read_text()
    assert ".multiselect(" in src, "the picker must use a multiselect dialog"
    assert "preselect=PRESELECT" in src or "preselect=" in src


def test_resolves_from_installed_repos():
    """The resolver must discover the installed repositories rather than use a
    fixed list of source urls — it reads repository.* add-on.xml dirs."""
    src = DEFAULT_PY.read_text()
    assert "_repo_dirs" in src and "_build_index" in src
    assert "_resolve_closure" in src
    assert 'startswith("repository.")' in src, (
        "must enumerate installed repository.* add-ons"
    )
    assert "xbmc.addon.repository" in src, "must read the repository extension"


def test_no_modal_installer():
    src = DEFAULT_PY.read_text()
    assert "InstallAddon(" not in src, "InstallAddon modal must not be used"
    assert "SetAddonEnabled" in src, "must enable via SetAddonEnabled"


def test_never_toggles_unknown_sources():
    src = DEFAULT_PY.read_text()
    assert "addons.unknownsources" not in src


def test_self_uninstall_targets_own_id():
    src = DEFAULT_PY.read_text()
    assert "_self_uninstall" in src and "_self_uninstall()" in src
    assert _assign("MY_ID") == "script.tony7bones.video"
    assert "rmtree" in src and "special://home/addons/" in src


@pytest.mark.parametrize(
    "needle",
    ["m3uUrl", "epgUrl", "bit.ly", "cutt.ly", "xtream", "get.php", "player_api"],
)
def test_no_iptv_secret_embedded(needle):
    assert needle not in DEFAULT_PY.read_text(), f"secret-ish token: {needle}"


# --------------------------------------------------------------------------- #
# Runtime coverage — import default.py under mocked Kodi APIs
# --------------------------------------------------------------------------- #
class _FakeResp:
    def __init__(self, data):
        self._data = data

    def read(self):
        return self._data

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


# A small fake index covering the apps and a transitive module dep. Sports HD
# pulls dateutil/six/requests; resolveurl stands in for the heavier Loop deps.
_INDEX = {
    "plugin.video.pov": ("6.06.04", ["script.module.requests"], None),
    "plugin.video.the-loop": (
        "7.9",
        ["script.module.requests", "script.module.resolveurl"],
        None,
    ),
    "plugin.video.sporthdme": (
        "0.1.85.1",
        ["script.module.dateutil", "script.module.requests"],
        None,
    ),
    "plugin.video.umbrella": ("6.7.77", ["script.module.requests"], None),
    "script.module.requests": ("2.31.0", ["script.module.urllib3"], None),
    "script.module.urllib3": ("2.2.3", [], None),
    "script.module.resolveurl": ("5.1.0", [], None),
    "script.module.dateutil": ("2.8.2", ["script.module.six"], None),
    "script.module.six": ("1.16.0", [], None),
}


@pytest.fixture
def vid(tmp_path, monkeypatch):
    """Import default.py with fake Kodi modules; return module + recorded state."""
    state = {
        "installed": set(),
        "extracted": set(),
        "builtins": [],
        "jsonrpc": [],
        "ok": [],
        "multiselect": [],
        "index": dict(_INDEX),
    }

    xbmc = types.ModuleType("xbmc")
    xbmc.LOGERROR = 4
    xbmc.LOGINFO = 1
    xbmc.log = lambda *a, **k: None
    xbmc.sleep = lambda ms: None

    def _builtin(cmd, wait=False):
        state["builtins"].append(cmd)

    xbmc.executebuiltin = _builtin

    def _jsonrpc(s):
        state["jsonrpc"].append(s)
        d = _json.loads(s)
        if d.get("method") == "Addons.SetAddonEnabled":
            aid = d["params"]["addonid"]
            if aid in state["extracted"]:
                state["installed"].add(aid)
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
            state["builtins"].append("DialogProgress.close")

    class _Dialog:
        def ok(self, title, msg):
            state["ok"].append((title, msg))

        def multiselect(self, title, options, preselect=None):
            state["multiselect"].append((title, options, preselect))
            # 'pick' drives the test: None = cancel, [] = nothing, else indexes.
            pick = state.get("pick", preselect)
            return None if pick is None else list(pick)

        def yesno(self, title, msg, **kwargs):
            return False

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

    # Lay down a fake installed repository with a versioned <dir> so _repo_dirs
    # discovers a real source. Its info url is the sentinel our fake urlopen
    # answers with the combined index.
    repo_dir = addons / "repository.fake"
    repo_dir.mkdir()
    (repo_dir / "addon.xml").write_text(
        '<?xml version="1.0"?>'
        '<addon id="repository.fake" version="1.0.0">'
        '<extension point="xbmc.addon.repository">'
        '<dir minversion="21.0.0">'
        "<info>https://fake.repo/zips/addons.xml</info>"
        "<datadir>https://fake.repo/zips/</datadir>"
        "</dir></extension></addon>"
    )
    # A second repo gated to an OLD Kodi (Nexus) — must be filtered out.
    old_dir = addons / "repository.old"
    old_dir.mkdir()
    (old_dir / "addon.xml").write_text(
        '<?xml version="1.0"?>'
        '<addon id="repository.old" version="1.0.0">'
        '<extension point="xbmc.addon.repository">'
        '<dir minversion="19.0.0" maxversion="20.89.0">'
        "<info>https://old.repo/zips/addons.xml</info>"
        "<datadir>https://old.repo/zips/</datadir>"
        "</dir></extension></addon>"
    )
    # Our own host proxy repo — must be skipped (127.0.0.1 source).
    proxy_dir = addons / "repository.tony7bones"
    proxy_dir.mkdir()
    (proxy_dir / "addon.xml").write_text(
        '<?xml version="1.0"?>'
        '<addon id="repository.tony7bones" version="1.0.0">'
        '<extension point="xbmc.addon.repository">'
        "<dir><info>http://127.0.0.1:61234/addons.xml</info>"
        "<datadir>http://127.0.0.1:61234/</datadir></dir>"
        "</extension></addon>"
    )

    def _index_xml(index):
        parts = ['<?xml version="1.0"?>', "<addons>"]
        for aid, (ver, deps, _path) in index.items():
            parts.append(f'<addon id="{aid}" version="{ver}"><requires>')
            for d in deps:
                parts.append(f'<import addon="{d}" version="1.0.0"/>')
            parts.append("</requires></addon>")
        parts.append("</addons>")
        return "".join(parts).encode("utf-8")

    def _url_of(req):
        return req.full_url if hasattr(req, "full_url") else req

    def _fake_urlopen(req, timeout=None):
        url = _url_of(req)
        if "fake.repo" in url and ("addons.xml" in url):
            data = _index_xml(state["index"])
            return _FakeResp(_gzip.compress(data) if url.endswith(".gz") else data)
        if "old.repo" in url and "addons.xml" in url:
            # the old dir should never be queried; answer empty if it is
            data = b'<?xml version="1.0"?><addons></addons>'
            return _FakeResp(_gzip.compress(data) if url.endswith(".gz") else data)
        if "mirrors.kodi.tv" in url and "addons.xml" in url:
            data = b'<?xml version="1.0"?><addons></addons>'
            return _FakeResp(_gzip.compress(data) if url.endswith(".gz") else data)
        if url.endswith(".zip"):
            aid = url.rsplit("/", 1)[-1].rsplit("-", 1)[0]
            state["extracted"].add(aid)
            buf = io.BytesIO()
            with _zipfile.ZipFile(buf, "w") as z:
                z.writestr(f"{aid}/addon.xml", f'<addon id="{aid}"/>')
            return _FakeResp(buf.getvalue())
        return _FakeResp(b"")

    monkeypatch.setattr(urllib.request, "urlopen", _fake_urlopen)

    spec = importlib.util.spec_from_file_location("video_default", DEFAULT_PY)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return types.SimpleNamespace(mod=mod, state=state, addons=addons)


def test_repo_dirs_discovers_installed_filters_old_and_proxy(vid):
    """Discovery keeps the Omega-gated repo, drops the Nexus-gated one and the
    127.0.0.1 host proxy."""
    pairs = vid.mod._repo_dirs()
    infos = [info for info, _base in pairs]
    assert "https://fake.repo/zips/addons.xml" in infos
    assert "https://old.repo/zips/addons.xml" not in infos, "old Kodi dir must be gated"
    assert not any("127.0.0.1" in i for i in infos), "host proxy must be skipped"


def test_build_index_combines_repos(vid):
    combined = vid.mod._build_index(None)
    assert "plugin.video.pov" in combined
    assert "plugin.video.umbrella" in combined


def test_build_index_picks_highest_version(vid):
    """When several repos publish the same id at different versions, the newest
    build must win — regression for resolveurl 5.0.09 shadowing 5.1.200, which
    made Kodi reject the old build as incompatible."""
    a = {"script.module.resolveurl": ("5.0.09", [], None)}
    b = {"script.module.resolveurl": ("5.1.200", [], None)}
    combined = {}
    vid.mod._merge_index(combined, a, prefer=False)
    vid.mod._merge_index(combined, b, prefer=False)
    assert combined["script.module.resolveurl"][0] == "5.1.200"
    # order of merge must not matter
    combined2 = {}
    vid.mod._merge_index(combined2, b, prefer=False)
    vid.mod._merge_index(combined2, a, prefer=False)
    assert combined2["script.module.resolveurl"][0] == "5.1.200"


def test_ver_key_numeric_compare(vid):
    k = vid.mod._ver_key
    assert k("5.1.200") > k("5.0.38")
    assert k("5.1.61") > k("5.1.9")  # numeric, not lexical
    assert k("2.0.1") > k("2.0.0")


def test_official_preferred_for_shared_modules(vid):
    """A module the official repo carries must come from official even if a
    third-party repo lists a higher version (Kodi-matched build wins)."""
    third = {"script.module.requests": ("9.9.9", [], None)}
    official = {"script.module.requests": ("2.31.0", [], None)}
    combined = {}
    vid.mod._merge_index(combined, third, prefer=False)
    vid.mod._merge_index(combined, official, prefer=True)
    assert combined["script.module.requests"][0] == "2.31.0"


def test_resolve_closure_walks_deps_order(vid):
    indexes = vid.mod._build_index(None)
    closure, missing = vid.mod._resolve_closure(["plugin.video.sporthdme"], indexes)
    ids = [aid for aid, _url in closure]
    assert "plugin.video.sporthdme" in ids
    assert "script.module.requests" in ids
    assert "script.module.six" in ids  # transitive dep of dateutil
    assert not any(i.startswith(("xbmc.", "kodi.")) for i in ids)
    assert ids.index("script.module.requests") < ids.index("plugin.video.sporthdme")
    assert not missing


def test_resolve_closure_reports_missing(vid):
    indexes = vid.mod._build_index(None)
    closure, missing = vid.mod._resolve_closure(["plugin.video.nope"], indexes)
    assert closure == []
    assert "plugin.video.nope" in missing


def test_resolve_closure_skips_installed(vid):
    vid.state["installed"].add("script.module.requests")
    indexes = vid.mod._build_index(None)
    closure, _missing = vid.mod._resolve_closure(["plugin.video.pov"], indexes)
    ids = [aid for aid, _url in closure]
    # requests already installed → not re-resolved
    assert "script.module.requests" not in ids
    assert "plugin.video.pov" in ids


def test_run_default_selection_installs_three(vid):
    """The default selection (preselect [0,1,2]) installs POV, The Loop, Sports
    HD and their closure, enables them, and does NOT install Umbrella."""
    vid.state["pick"] = [0, 1, 2]
    vid.mod.run()
    s = vid.state
    # multiselect shown with the right options + preselect
    assert s["multiselect"], "multiselect dialog must be shown"
    _title, options, preselect = s["multiselect"][-1]
    assert options == ["POV", "The Loop", "Sports HD", "Umbrella"]
    assert preselect == [0, 1, 2]
    # the three defaults installed + enabled
    for aid in ("plugin.video.pov", "plugin.video.the-loop", "plugin.video.sporthdme"):
        assert aid in s["installed"], f"{aid} not installed"
    # closure deps installed
    assert "script.module.requests" in s["installed"]
    assert "script.module.resolveurl" in s["installed"]
    # Umbrella was NOT selected
    assert "plugin.video.umbrella" not in s["installed"]
    # no modal installer
    assert not any(b.startswith("InstallAddon(") for b in s["builtins"])
    assert "UpdateLocalAddons()" in s["builtins"]
    assert s["ok"], "completion dialog must be shown"


def test_run_umbrella_when_selected(vid):
    vid.state["pick"] = [3]
    vid.mod.run()
    assert "plugin.video.umbrella" in vid.state["installed"]


def test_run_cancel_makes_no_changes_and_keeps_addon(vid):
    """Cancelling the picker (None) installs nothing and does NOT self-uninstall
    so the user can re-run it."""
    mine = vid.addons / "script.tony7bones.video"
    mine.mkdir()
    (mine / "addon.xml").write_text('<addon id="script.tony7bones.video"/>')
    vid.state["pick"] = None
    vid.mod.run()
    assert vid.state["installed"] == set()
    assert mine.exists(), "must NOT self-uninstall on cancel"


def test_run_empty_selection_makes_no_changes(vid):
    vid.state["pick"] = []
    vid.mod.run()
    assert vid.state["installed"] == set()


def test_run_self_uninstalls_after_install(vid):
    mine = vid.addons / "script.tony7bones.video"
    mine.mkdir()
    (mine / "addon.xml").write_text('<addon id="script.tony7bones.video"/>')
    vid.state["pick"] = [0]
    vid.mod.run()
    assert not mine.exists(), "must self-uninstall after a successful run"


def test_run_bails_without_source_repos(vid, monkeypatch):
    """With no source repos installed, run() shows a 'run main Setup first'
    dialog and installs nothing."""
    monkeypatch.setattr(vid.mod, "_repo_dirs", lambda: [])
    vid.state["pick"] = [0, 1, 2]
    vid.mod.run()
    assert vid.state["installed"] == set()
    assert vid.state["ok"], "must show the guidance dialog"
    _title, msg = vid.state["ok"][-1]
    assert "Tony.7.Bones Setup" in msg


def test_self_uninstall_only_touches_own_dir(vid):
    mine = vid.addons / "script.tony7bones.video"
    other = vid.addons / "plugin.video.pov"
    mine.mkdir()
    other.mkdir()
    (other / "addon.xml").write_text('<addon id="plugin.video.pov"/>')
    vid.mod._self_uninstall()
    assert not mine.exists()
    assert other.exists(), "must not delete other add-ons"


def test_self_uninstall_never_raises(vid, monkeypatch):
    import shutil as _shutil

    def boom(*a, **k):
        raise OSError("permission denied")

    monkeypatch.setattr(_shutil, "rmtree", boom)
    mine = vid.addons / "script.tony7bones.video"
    mine.mkdir()
    vid.mod._self_uninstall()  # must not raise


def test_platform_tag_shape(vid):
    tag = vid.mod._platform_tag()
    import re

    assert tag is None or re.match(r"^(osx|windows|android)-", tag), tag
