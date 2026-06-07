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
ADDON_DIR = REPO_ROOT / "addons" / "script.tony7bones.video"
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


def test_addon_version_bumped():
    import sys as _sys

    _sys.path.insert(0, str(HERE))
    import release_lib as rl  # noqa: PLC0415

    v = _addon_root().get("version")
    assert rl.is_greater(v, "1.0.0"), f"version {v} must exceed the initial 1.0.0"


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
    fixed list of source urls. That discovery (repo_dirs) + combined index
    (build_index) + dependency walk (resolve_closure_combined) now live in the
    shared library; the video Setup must drive all three."""
    src = DEFAULT_PY.read_text()
    assert "repo_dirs" in src and "build_index" in src
    assert "resolve_closure_combined" in src


def test_no_modal_installer():
    src = DEFAULT_PY.read_text()
    assert "InstallAddon(" not in src, "InstallAddon modal must not be used"
    # Enabling now goes through the shared library's install_closure (which calls
    # SetAddonEnabled); the Setup must drive it, never the modal installer.
    assert "install_closure" in src, "must install via the shared install_closure"


def test_requires_the_shared_module():
    """The manifest must declare the shared library as a required import so Kodi
    auto-installs it when this Setup is installed from the repo."""
    imp = _addon_root().find("requires/import[@addon='script.module.tony7bones']")
    assert imp is not None, "must <import> script.module.tony7bones"
    assert imp.get("version") == "1.0.0"


def test_imports_from_shared_module():
    """default.py must import its machinery from the shared library, not carry a
    private copy."""
    src = DEFAULT_PY.read_text()
    assert "from tony7bones import" in src


def test_never_toggles_unknown_sources():
    src = DEFAULT_PY.read_text()
    assert "addons.unknownsources" not in src


def test_self_uninstall_targets_own_id():
    """The deletion machinery now lives in the shared library's self_uninstall();
    the Setup must invoke it with its own id."""
    src = DEFAULT_PY.read_text()
    assert "self_uninstall(MY_ID" in src
    assert _assign("MY_ID") == "script.tony7bones.video"


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
# Each value is (version, [deps], zip_url, origin). origin is unused by the
# fake index serialiser (the real origin is derived from the discovered
# repository.fake during _parse_index) but keeps the tuple shape consistent with
# the module's index shape.
_INDEX = {
    "plugin.video.pov": (
        "6.06.04",
        ["script.module.requests"],
        None,
        "repository.fake",
    ),
    "plugin.video.the-loop": (
        "7.9",
        ["script.module.requests", "script.module.resolveurl"],
        None,
        "repository.fake",
    ),
    "plugin.video.sporthdme": (
        "0.1.85.1",
        ["script.module.dateutil", "script.module.requests"],
        None,
        "repository.fake",
    ),
    "plugin.video.umbrella": (
        "6.7.77",
        ["script.module.requests"],
        None,
        "repository.fake",
    ),
    "script.module.requests": (
        "2.31.0",
        ["script.module.urllib3"],
        None,
        "repository.fake",
    ),
    "script.module.urllib3": ("2.2.3", [], None, "repository.fake"),
    "script.module.resolveurl": ("5.1.0", [], None, "repository.fake"),
    "script.module.dateutil": ("2.8.2", ["script.module.six"], None, "repository.fake"),
    "script.module.six": ("1.16.0", [], None, "repository.fake"),
}


@pytest.fixture
def vid(tmp_path, monkeypatch):
    """Import default.py with fake Kodi modules; return module + recorded state."""
    state = {
        "installed": set(),
        "extracted": set(),
        "disabled": set(),
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
            enabled = d["params"].get("enabled", True)
            if enabled:
                if aid in state["extracted"]:
                    state["installed"].add(aid)
                state["disabled"].discard(aid)
            else:
                # Disabling leaves the add-on installed; just record the state.
                state["disabled"].add(aid)
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
        for aid, entry in index.items():
            ver, deps = entry[0], entry[1]
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

    # Put the shared library (script.module.tony7bones) on sys.path exactly as
    # Kodi does for an add-on that imports it, and purge any cached copy so the
    # library re-binds to THIS test's mock Kodi modules (it does `import xbmc`
    # at module load). Without the purge a prior test's mocks would leak in.
    _LIB = REPO_ROOT / "addons" / "script.module.tony7bones" / "lib"
    monkeypatch.syspath_prepend(str(_LIB))
    for _name in list(sys.modules):
        if _name == "tony7bones" or _name.startswith("tony7bones."):
            monkeypatch.delitem(sys.modules, _name, raising=False)

    spec = importlib.util.spec_from_file_location("video_default", DEFAULT_PY)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return types.SimpleNamespace(mod=mod, state=state, addons=addons)


# --------------------------------------------------------------------------- #
# Install-then-disable Dailymotion for The Loop
# --------------------------------------------------------------------------- #
def test_disable_after_install_is_dailymotion_only():
    """The install-then-disable set is exactly Dailymotion — nothing else."""
    disable = _assign("DISABLE_AFTER_INSTALL")
    assert disable == {"plugin.video.dailymotion_com"}


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
    # source repos were enabled (so stamped origins reference repos Kodi knows).
    enabled = [
        _json.loads(j)["params"]["addonid"]
        for j in s["jsonrpc"]
        if _json.loads(j).get("method") == "Addons.SetAddonEnabled"
    ]
    assert "repository.fake" in enabled, "source repos must be enabled"


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
    # have_source_repos is imported into the module's namespace from the shared
    # library; force it False to take the early-bail branch.
    monkeypatch.setattr(vid.mod, "have_source_repos", lambda _log: False)
    vid.state["pick"] = [0, 1, 2]
    vid.mod.run()
    assert vid.state["installed"] == set()
    assert vid.state["ok"], "must show the guidance dialog"
    _title, msg = vid.state["ok"][-1]
    assert "Tony.7.Bones Setup" in msg


# --- restart so the fix takes effect on first launch -----------------------


def test_run_restarts_after_install(vid, monkeypatch):
    """A successful install restarts Kodi (so POV's strings load and the stamped
    origins go live). yesno is forced True to take the restart branch."""
    monkeypatch.setattr(vid.mod.xbmcgui, "Dialog", _yes_dialog_factory(vid.state))
    vid.state["pick"] = [0]
    vid.mod.run()
    assert any(b.startswith("RestartApp") for b in vid.state["builtins"]), (
        "must restart after install"
    )


def test_run_no_restart_when_nothing_installed(vid, monkeypatch):
    """If no app ends up installed, do not restart."""
    monkeypatch.setattr(vid.mod.xbmcgui, "Dialog", _yes_dialog_factory(vid.state))
    # install_selected reports zero installed -> run() must not restart.
    monkeypatch.setattr(vid.mod, "install_selected", lambda selected, dialog: 0)
    vid.state["pick"] = [0]
    vid.mod.run()
    assert not any(b.startswith("RestartApp") for b in vid.state["builtins"])


def test_no_modal_installer_runtime(vid):
    """Belt-and-braces: the live module never emits an InstallAddon builtin."""
    vid.state["pick"] = [0, 1, 2]
    vid.mod.run()
    assert not any(b.startswith("InstallAddon(") for b in vid.state["builtins"])


def _yes_dialog_factory(state):
    """A Dialog whose yesno() returns True (to exercise the restart branch),
    recording ok()/multiselect like the default fake."""

    class _D:
        def ok(self, title, msg):
            state["ok"].append((title, msg))

        def multiselect(self, title, options, preselect=None):
            state["multiselect"].append((title, options, preselect))
            pick = state.get("pick", preselect)
            return None if pick is None else list(pick)

        def yesno(self, title, msg, **kwargs):
            return True

    return _D
