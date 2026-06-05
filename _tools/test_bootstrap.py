"""Coverage for the Tony.7.Bones Bootstrap add-on.

Two layers:

* Static contract — manifest is well-formed and version-bumped, the script
  compiles, every repo zip it references exists in the published repositories/
  folder (so installs won't 404), and no IPTV secret is embedded.
* Runtime behavior — default.py is imported under mocked Kodi modules (run() is
  __main__-guarded, so import is side-effect-free) and the install flow is
  exercised directly: repos extract, the first-party patch resolves live, and
  the requested apps install through Kodi's own repo installer (InstallAddon)
  one at a time so they register and actually run.
"""

from __future__ import annotations

import ast
import os
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


def test_addon_name_is_branded():
    assert _addon_root().get("name") == "Tony.7.Bones Setup"


def test_version_bumped_past_old():
    v = _addon_root().get("version")
    assert rl.is_greater(v, "1.0.22"), f"version {v} must exceed the old 1.0.22"


# --------------------------------------------------------------------------- #
# Script
# --------------------------------------------------------------------------- #
def test_script_is_a_proper_program_addon():
    """The setup is a normal runnable Program add-on while it briefly exists.

    The old 'image' content-type hack (to hide it from Estuary's home Programs
    widget) is gone: the add-on now keeps itself off the home screen by REMOVING
    ITSELF after a successful run (see test_self_uninstall_logic_exists), so it
    can declare the correct content type. It must provide 'executable' so that,
    for the one run it exists, it behaves like the Program add-on it is."""
    ext = _addon_root().find("extension[@point='xbmc.python.script']")
    assert ext is not None, "must keep the xbmc.python.script extension (runnable)"
    assert ext.get("library") == "default.py"
    provides = [p.text for p in ext.findall("provides")]
    assert provides == ["executable"], (
        "must declare <provides>executable</provides> (a proper Program add-on); "
        f"got {provides!r}"
    )


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


def test_addons_includes_peno64_apps_weather_and_pvr():
    """Install set: the two peno64 apps plus Multi Weather and IPTV Simple."""
    assert _assign("ADDONS") == [
        "script.ezmaintenanceplus",
        "script.realdebrid",
        "weather.multi",
        "pvr.iptvsimple",
    ]


def test_peno64_repo_is_installed_so_apps_resolve():
    """The apps live in peno64 — its repo zip must be in the install list."""
    repo_ids = {rid for _zip, rid in _assign("REPO_ZIPS")}
    assert "repository.peno64" in repo_ids


def test_patch_is_first_party_direct_extract():
    """The MOD V2 patch must NOT be auto-installed by the setup. It is neither in
    the first-party direct-extract list nor in the apps list — a user installs it
    by hand only if they adopt the Estuary MOD V2 skin. It stays HOST-provided
    (see test_modv2_patch_is_host_provided)."""
    assert "script.tony7bones.modv2.patch" not in _assign("FIRST_PARTY")
    assert "script.tony7bones.modv2.patch" not in _assign("ADDONS")


def test_first_party_is_empty():
    """Nothing is auto-installed from our Pages as a 'first-party' add-on now
    that the MOD V2 patch is opt-in. run() must skip the first-party loop."""
    assert _assign("FIRST_PARTY") == []


def test_apps_install_without_modal_installer():
    """Apps must NOT use Kodi's InstallAddon builtin — it pops a blocking modal
    install dialog that deadlocks the GUI when driven from a script. They are
    installed by resolving the dependency closure and extracting directly."""
    src = DEFAULT_PY.read_text()
    assert "InstallAddon(" not in src, "InstallAddon modal must not be used"
    # The closure-resolve + direct-extract install now lives in the shared
    # library; the base Setup drives it through install_with_deps().
    assert "install_with_deps" in src


def test_never_toggles_unknown_sources():
    """The bootstrap must NOT touch addons.unknownsources. Flipping it
    false->true pops a blocking "access to personal data... Proceed?" warning.
    Direct-extract + SetAddonEnabled installs/enables add-ons without that
    setting, so a real user running the setup never sees the prompt."""
    src = DEFAULT_PY.read_text()
    assert "addons.unknownsources" not in src, (
        "must not write addons.unknownsources (it pops the security prompt)"
    )
    assert "_set_unknown_sources" not in src, (
        "the unknown-sources toggle helper must be removed"
    )


def test_installs_weather_and_pvr_binary():
    """The install set must include the weather add-on and the binary PVR
    client, and the script must detect the platform to pick the right build."""
    addons = _assign("ADDONS")
    assert "weather.multi" in addons
    assert "pvr.iptvsimple" in addons
    # Binary add-ons need runtime platform detection; that now lives in the
    # shared library's install_with_deps (it loads the official index with the
    # platform tag). The base Setup hands it the official base + peno64 base.
    src = DEFAULT_PY.read_text()
    assert "install_with_deps" in src
    assert "OFFICIAL_BASE" in src and "PENO64_BASE" in src


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


def test_no_empty_addon_ids():
    assert all(_assign("ADDONS")), "ADDONS must contain no empty ids"
    assert all(_assign("FIRST_PARTY")), "FIRST_PARTY must contain no empty ids"


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
# End-of-setup restart flow (the Fire Stick end-freeze fix)
# --------------------------------------------------------------------------- #
def test_restart_flow_present_and_prompted():
    """After the success summary the script must offer a platform-correct
    restart. The restart machinery (RestartApp/Quit/yesno, Android branch) now
    lives in the shared library's restart_kodi(); the base Setup must call it."""
    src = DEFAULT_PY.read_text()
    assert "restart_kodi" in src, "must invoke the shared restart helper"
    assert 'restart_kodi("Tony.7.Bones Setup"' in src, (
        "the base Setup must drive restart_kodi with its own title"
    )


def test_restart_comes_after_success_summary():
    """The restart prompt must follow the counts dialog, not replace it."""
    src = DEFAULT_PY.read_text()
    ok_pos = src.rfind("Open Add-ons to finish")
    restart_pos = src.rfind("restart_kodi(")
    assert ok_pos != -1 and restart_pos != -1
    assert restart_pos > ok_pos, "restart prompt must come after the summary dialog"


# --------------------------------------------------------------------------- #
# Self-uninstall (run once, then disappear — no leftover home tile)
# --------------------------------------------------------------------------- #
def test_self_uninstall_logic_exists():
    """The setup must remove itself after a successful run. The deletion
    machinery (rmtree of its own addons/ dir, with the own-id guard) now lives in
    the shared library's self_uninstall(); the base Setup must invoke it with its
    own add-on id."""
    src = DEFAULT_PY.read_text()
    assert "self_uninstall" in src, "must invoke the shared self-uninstall helper"
    assert 'MY_ID = "script.tony7bones.bootstrap"' in src, (
        "the base Setup must define its own id"
    )
    assert "self_uninstall(MY_ID" in src, (
        "self-uninstall must target the add-on's own id"
    )


def test_self_uninstall_runs_after_summary_and_before_restart():
    """Sequence must be: summary dialog -> self-uninstall -> restart prompt.
    The restart is what finalises the removal (startup scan drops the DB row)."""
    src = DEFAULT_PY.read_text()
    ok_pos = src.rfind("Open Add-ons to finish")
    uninstall_pos = src.rfind("self_uninstall(MY_ID")
    restart_pos = src.rfind("restart_kodi(")
    assert ok_pos != -1 and uninstall_pos != -1 and restart_pos != -1
    assert ok_pos < uninstall_pos < restart_pos, (
        "order must be summary -> self-uninstall -> restart"
    )


# --------------------------------------------------------------------------- #
# Runtime coverage — import default.py under mocked Kodi APIs and run it
# --------------------------------------------------------------------------- #
import gzip as _gzip  # noqa: E402
import importlib.util  # noqa: E402
import io  # noqa: E402
import json as _json  # noqa: E402
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
    # Fake repo index: id -> (version, [deps], path_or_None). The apps depend on
    # the requests module, which pulls a small closure — the resolver must walk
    # it. weather.multi is pure python; pvr.iptvsimple is BINARY and carries an
    # explicit platform-suffixed <path>, as does its inputstream dep, exercising
    # the binary-path branch.
    state = {
        "installed": set(),
        "extracted": set(),  # zips unpacked on disk but not yet enabled
        "disabled": set(),  # ids disabled via SetAddonEnabled enabled=false
        "builtins": [],
        "jsonrpc": [],
        "ok": [],
        "index": {
            "script.ezmaintenanceplus": (
                "2026.04.05.0",
                ["script.module.requests"],
                None,
            ),
            "script.realdebrid": ("0.7", ["script.module.requests"], None),
            "script.module.requests": (
                "2.31.0",
                ["script.module.urllib3", "script.module.certifi", "xbmc.python"],
                None,
            ),
            "script.module.urllib3": ("2.2.3", [], None),
            "script.module.certifi": ("2023.5.7", [], None),
            "weather.multi": ("1.1.0", ["script.module.requests"], None),
            "pvr.iptvsimple": (
                "21.11.0",
                ["inputstream.ffmpegdirect", "kodi.binary.instance.pvr"],
                "pvr.iptvsimple+osx-arm64/pvr.iptvsimple-21.11.0.zip",
            ),
            "inputstream.ffmpegdirect": (
                "21.3.8",
                ["kodi.binary.instance.inputstream"],
                "inputstream.ffmpegdirect+osx-arm64/inputstream.ffmpegdirect-21.3.8.zip",
            ),
        },
    }

    xbmc = types.ModuleType("xbmc")
    xbmc.LOGERROR = 4
    xbmc.LOGINFO = 1
    xbmc.log = lambda *a, **k: None
    xbmc.sleep = lambda ms: None
    # Active skin — default to Estuary so _trim_home_menu() is exercised. Tests
    # that need another skin monkeypatch this.
    xbmc.getSkinDir = lambda: "skin.estuary"

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
                # Kodi only enables an add-on it has scanned (extracted on disk).
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

        def yesno(self, title, msg, **kwargs):
            # Two yes/no prompts exist now: the front-loaded "Include video
            # add-ons?" (msg starts with "Include video") and the end-of-setup
            # restart prompt. The "also video" answer is driven by state
            # (default False = base-only, today's behaviour); the restart prompt is
            # always declined so run() never actually restarts in tests.
            state.setdefault("yesno", []).append((title, msg))
            if msg.startswith("Include video"):
                return bool(state.get("also_video", False))
            return False

        def multiselect(self, title, options, preselect=None):
            state.setdefault("multiselect", []).append((title, options, preselect))
            # state['video_pick']: None = cancel, [] = nothing, else indexes.
            pick = state.get("video_pick", preselect)
            return None if pick is None else list(pick)

    xbmcgui.DialogProgress = _DP
    xbmcgui.Dialog = _Dialog
    # Kodi 21 Omega exposes this; the base Setup uses it to default the
    # "Include video add-ons?" prompt to No.
    xbmcgui.DLG_YESNO_NO_BTN = 1

    xbmcvfs = types.ModuleType("xbmcvfs")
    temp = tmp_path / "temp"
    addons = tmp_path / "addons"
    profile = tmp_path / "userdata"
    temp.mkdir()
    addons.mkdir()
    profile.mkdir()
    sources_xml = profile / "sources.xml"
    # Record every mkdirs() call so the directory-create attempt is provable.
    state["mkdirs"] = []

    def _translate(p):
        return (
            p.replace("special://temp/", str(temp) + "/")
            .replace("special://home/addons/", str(addons) + "/")
            .replace("special://profile/", str(profile) + "/")
            .replace("special://home/userdata/", str(profile) + "/")
        )

    xbmcvfs.translatePath = _translate

    def _exists(p):
        return os.path.exists(p)

    def _mkdirs(p):
        # Record the attempt. The Android path can't be created on this host —
        # mimic that by refusing to create absolute /storage/... paths (returns
        # False, as Kodi's xbmcvfs.mkdirs does on failure), so the test proves
        # the call is guarded and the source is still added.
        state["mkdirs"].append(p)
        if p.startswith("/storage/"):
            return False
        os.makedirs(p, exist_ok=True)
        return True

    def _copy(src, dst):
        # Mimic xbmcvfs.copy: overwrite the destination, return bool success.
        import shutil

        try:
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copyfile(src, dst)
            return True
        except OSError:
            return False

    xbmcvfs.exists = _exists
    xbmcvfs.mkdirs = _mkdirs
    xbmcvfs.copy = _copy

    for nm, mod in (
        ("xbmc", xbmc),
        ("xbmcaddon", xbmcaddon),
        ("xbmcgui", xbmcgui),
        ("xbmcvfs", xbmcvfs),
    ):
        monkeypatch.setitem(sys.modules, nm, mod)

    def _index_xml():
        parts = ['<?xml version="1.0"?>', "<addons>"]
        for aid, (ver, deps, path) in state["index"].items():
            parts.append(f'<addon id="{aid}" version="{ver}">')
            parts.append("<requires>")
            for d in deps:
                parts.append(f'<import addon="{d}" version="1.0.0"/>')
            parts.append("</requires>")
            # binary add-ons carry an explicit <path> in the metadata extension
            parts.append('<extension point="xbmc.addon.metadata">')
            if path:
                parts.append(f"<path>{path}</path>")
            parts.append("</extension></addon>")
        parts.append("</addons>")
        return "".join(parts).encode("utf-8")

    def _url_of(req):
        return req.full_url if hasattr(req, "full_url") else req

    def _fake_urlopen(req, timeout=None):
        url = _url_of(req)
        if url.endswith("addon.xml"):
            return _FakeResp(
                b'<addon id="script.tony7bones.modv2.patch" version="1.0.3"/>'
            )
        if url.endswith("addons.xml") or url.endswith("addons.xml.gz"):
            data = _index_xml()
            return _FakeResp(_gzip.compress(data) if url.endswith(".gz") else data)
        if url.endswith(".zip"):
            # name pattern: .../<id>/<id>-<ver>.zip  → record the inner id
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
    _LIB = REPO_ROOT / "repo" / "script.module.tony7bones" / "lib"
    monkeypatch.syspath_prepend(str(_LIB))
    for _name in list(sys.modules):
        if _name == "tony7bones" or _name.startswith("tony7bones."):
            monkeypatch.delitem(sys.modules, _name, raising=False)

    spec = importlib.util.spec_from_file_location("boot_default", DEFAULT_PY)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # run() is __main__-guarded, so this does not run it
    estuary_settings = profile / "addon_data" / "skin.estuary" / "settings.xml"
    return types.SimpleNamespace(
        mod=mod,
        state=state,
        addons=addons,
        sources_xml=sources_xml,
        estuary_settings=estuary_settings,
    )


def test_no_unknown_sources_jsonrpc_during_run(boot):
    """A full run must never send a Settings.SetSettingValue for
    addons.unknownsources — that is what pops the security prompt."""
    boot.mod.run()
    assert not any("addons.unknownsources" in s for s in boot.state["jsonrpc"])


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


def test_run_installs_apps_without_modal(boot):
    boot.mod.run()
    s = boot.state
    # NO unknown-sources toggle — that prompt must never fire for a real user
    assert not any("addons.unknownsources" in j for j in s["jsonrpc"])
    # local add-on store rescanned so Kodi sees the freshly extracted dirs
    assert "UpdateLocalAddons()" in s["builtins"]
    # NO modal installer was ever used — that is what caused the GUI freeze
    assert not any(b.startswith("InstallAddon(") for b in s["builtins"])
    # each app and its dependency closure ended up installed + enabled
    for aid in boot.mod.ADDONS:
        assert aid in s["installed"], f"{aid} not installed"
    assert "script.module.requests" in s["installed"]  # resolved dependency
    # weather add-on and the binary PVR client both installed + enabled
    assert "weather.multi" in s["installed"]
    assert "pvr.iptvsimple" in s["installed"]
    assert "inputstream.ffmpegdirect" in s["installed"]  # binary dep of the PVR
    # the MOD V2 patch is NO LONGER auto-installed (opt-in only)
    assert "script.tony7bones.modv2.patch" not in s["installed"]
    assert "script.tony7bones.modv2.patch" not in s["extracted"]
    assert s["ok"], "no completion dialog shown"
    _title, msg = s["ok"][-1]
    assert "Repos:" in msg and "Patches:" in msg and "Apps:" in msg


def test_run_self_uninstalls_at_end(boot):
    """A full run must end by removing the setup's own add-on directory."""
    mine = boot.addons / "script.tony7bones.bootstrap"
    mine.mkdir()
    (mine / "addon.xml").write_text('<addon id="script.tony7bones.bootstrap"/>')
    boot.mod.run()
    assert not mine.exists(), "run() must self-uninstall at the end"


def test_run_aborts_cleanly_on_cancel(boot, monkeypatch):
    monkeypatch.setattr(
        boot.mod.xbmcgui.DialogProgress, "iscanceled", lambda self: True
    )
    boot.mod.run()  # must not raise
    # cancelled before finishing → no completion dialog
    assert boot.state["ok"] == []


# --------------------------------------------------------------------------- #
# File-Manager sources (Kodi home + sources dirs added to sources.xml)
# --------------------------------------------------------------------------- #
def _files_sources(boot):
    """Parse sources.xml and return [(name, path), ...] from the <files> section."""
    root = ET.parse(boot.sources_xml).getroot()
    files = root.find("files")
    assert files is not None, "<files> section must exist"
    return [(s.findtext("name"), s.findtext("path")) for s in files.findall("source")]


_HOME = ("Kodi home directory", "special://home")
_SRC = ("Kodi sources directory", "/storage/emulated/0/kodi/")


def test_add_file_sources_helper_exists():
    """The helper must exist and be wired into run() before the restart."""
    src = DEFAULT_PY.read_text()
    assert "_add_file_sources" in src, "helper must exist"
    assert "_add_file_sources()" in src, "helper must be invoked in run()"
    # Must run before the restart (Kodi caches sources.xml at startup).
    add_pos = src.rfind("_add_file_sources()")
    restart_pos = src.rfind("restart_kodi(")
    assert add_pos != -1 and restart_pos != -1
    assert add_pos < restart_pos, "_add_file_sources() must come before the restart"


def test_add_file_sources_creates_file_when_missing(boot):
    """No sources.xml → it creates the structure and adds both sources."""
    assert not boot.sources_xml.exists()
    boot.mod._add_file_sources()
    entries = _files_sources(boot)
    assert _HOME in entries
    assert _SRC in entries
    # canonical shape: <files> opens with a <default> element
    root = ET.parse(boot.sources_xml).getroot()
    assert root.find("files")[0].tag == "default"
    # path entries carry pathversion="1"
    for s in root.find("files").findall("source"):
        assert s.find("path").get("pathversion") == "1"
        assert s.findtext("allowsharing") == "true"


def test_add_file_sources_both_present_with_names_and_paths(boot):
    boot.mod._add_file_sources()
    entries = dict(_files_sources(boot))
    assert entries["Kodi home directory"] == "special://home"
    assert entries["Kodi sources directory"] == "/storage/emulated/0/kodi/"


def test_add_file_sources_preserves_existing(boot):
    """Existing sources (incl. a .tony7.bones files source and other media
    sections) must survive untouched."""
    boot.sources_xml.write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<sources>\n"
        "  <video>\n"
        "    <default></default>\n"
        "    <source><name>Movies</name>"
        "<path>/Users/x/Movies</path><allowsharing>true</allowsharing></source>\n"
        "  </video>\n"
        "  <files>\n"
        "    <default></default>\n"
        "    <source><name>.tony7.bones</name>"
        "<path>https://tony7bones.github.io/</path>"
        "<allowsharing>true</allowsharing></source>\n"
        "  </files>\n"
        "</sources>\n"
    )
    boot.mod._add_file_sources()
    root = ET.parse(boot.sources_xml).getroot()
    # video section + its Movies source preserved
    movies = [s.findtext("name") for s in root.find("video").findall("source")]
    assert "Movies" in movies
    # the .tony7.bones files source preserved, plus the two new ones added
    files_entries = _files_sources(boot)
    names = [n for n, _p in files_entries]
    assert ".tony7.bones" in names
    assert "Kodi home directory" in names
    assert "Kodi sources directory" in names


def test_add_file_sources_dedupes_on_second_run(boot):
    """Running twice must not duplicate (dedupe on name OR path)."""
    boot.mod._add_file_sources()
    boot.mod._add_file_sources()
    entries = _files_sources(boot)
    assert entries.count(_HOME) == 1
    assert entries.count(_SRC) == 1


def test_add_file_sources_dedupes_on_path_with_different_name(boot):
    """A pre-existing source sharing only the PATH must block re-adding."""
    boot.sources_xml.write_text(
        "<sources><files><default></default>"
        "<source><name>my home</name>"
        '<path pathversion="1">special://home</path>'
        "<allowsharing>true</allowsharing></source>"
        "</files></sources>"
    )
    boot.mod._add_file_sources()
    paths = [p for _n, p in _files_sources(boot)]
    # special://home appears exactly once (the pre-existing one), not duplicated
    assert paths.count("special://home") == 1
    # the sources dir was still added
    assert "/storage/emulated/0/kodi/" in paths


def test_add_file_sources_handles_malformed_xml(boot):
    """A corrupt sources.xml must be recreated, not crash the run."""
    boot.sources_xml.write_text("<sources><files><not closed")
    boot.mod._add_file_sources()  # must not raise
    entries = _files_sources(boot)
    assert _HOME in entries
    assert _SRC in entries


def test_add_file_sources_attempts_guarded_mkdirs(boot):
    """mkdirs must be ATTEMPTED for the Android path and guarded so a failure
    off Android is harmless — the source entry lands regardless."""
    boot.mod._add_file_sources()
    # the directory-create was attempted on the Android internal-storage path
    assert "/storage/emulated/0/kodi/" in boot.state["mkdirs"], (
        "mkdirs must be attempted for the Android storage path"
    )
    # and even though that mkdirs returns False on this host, the source landed
    paths = [p for _n, p in _files_sources(boot)]
    assert "/storage/emulated/0/kodi/" in paths


def test_add_file_sources_never_raises_on_write_error(boot, monkeypatch):
    """Any failure must be swallowed (never aborts the rest of setup)."""
    real_open = open

    def boom(path, *a, **k):
        if str(path).endswith("sources.xml") and (
            "w" in (a[0] if a else k.get("mode", ""))
        ):
            raise OSError("disk full")
        return real_open(path, *a, **k)

    monkeypatch.setattr("builtins.open", boom)
    boot.mod._add_file_sources()  # must not raise


def test_run_adds_file_sources(boot):
    """A full run must add the two File-Manager sources to sources.xml."""
    boot.mod.run()
    entries = _files_sources(boot)
    assert _HOME in entries
    assert _SRC in entries


# --------------------------------------------------------------------------- #
# Estuary home-menu trim (hide 8 items; keep TV, Add-ons, Favourites, Weather)
# --------------------------------------------------------------------------- #
# The eight hide-ids and the four kept-ids, in the exact lowercase form Estuary
# persists in addon_data/skin.estuary/settings.xml (verified on Kodi 21 Omega).
_HIDE_IDS = [
    "homemenunomoviebutton",
    "homemenunotvshowbutton",
    "homemenunomusicbutton",
    "homemenunomusicvideobutton",
    "homemenunoradiobutton",
    "homemenunopicturesbutton",
    "homemenunovideosbutton",
    "homemenunogamesbutton",
]
_KEEP_IDS = [
    "homemenunotvbutton",
    "homemenunoprogramsbutton",
    "homemenunofavbutton",
    "homemenunoweatherbutton",
]


def _estuary_bools(boot):
    """Return {id: text} for every <setting> in the Estuary settings.xml."""
    root = ET.parse(boot.estuary_settings).getroot()
    return {
        (s.get("id") or "").lower(): (s.text or "").strip()
        for s in root.findall("setting")
    }


def test_trim_home_menu_helper_exists_and_wired_before_restart():
    """The helper must exist and be invoked in run() BEFORE the restart (the
    restart is what makes Estuary re-read settings.xml)."""
    src = DEFAULT_PY.read_text()
    assert "_trim_home_menu" in src, "helper must exist"
    assert "_trim_home_menu()" in src, "helper must be invoked in run()"
    trim_pos = src.rfind("_trim_home_menu()")
    restart_pos = src.rfind("restart_kodi(")
    assert trim_pos != -1 and restart_pos != -1
    assert trim_pos < restart_pos, "_trim_home_menu() must come before the restart"


# The eight camel-case ids the skin XML / Skin.SetBool use (the part that
# survives the restart), and the four kept camel-case ids that must never be set.
_HIDE_CAMEL = [
    "HomeMenuNoMovieButton",
    "HomeMenuNoTVShowButton",
    "HomeMenuNoMusicButton",
    "HomeMenuNoMusicVideoButton",
    "HomeMenuNoRadioButton",
    "HomeMenuNoPicturesButton",
    "HomeMenuNoVideosButton",
    "HomeMenuNoGamesButton",
]
_KEEP_CAMEL = [
    "HomeMenuNoTVButton",
    "HomeMenuNoProgramsButton",
    "HomeMenuNoFavButton",
    "HomeMenuNoWeatherButton",
]


def test_trim_home_menu_uses_setbool_for_active_skin(boot):
    """It MUST set the live in-memory skin booleans via Skin.SetBool — that is
    the only mechanism that survives the end-of-setup restart (Kodi rewrites
    settings.xml from memory on shutdown, clobbering a file-only write). It must
    SetBool exactly the eight hide-ids (camel-case) and never the four kept."""
    boot.mod._trim_home_menu()
    setbools = [b for b in boot.state["builtins"] if b.startswith("Skin.SetBool(")]
    for cid in _HIDE_CAMEL:
        assert f"Skin.SetBool({cid})" in setbools, f"must Skin.SetBool({cid})"
    for cid in _KEEP_CAMEL:
        assert f"Skin.SetBool({cid})" not in setbools, f"must NOT set kept {cid}"
    assert len(setbools) == 8, f"exactly 8 SetBool calls expected, got {setbools}"


def test_trim_home_menu_setbool_skipped_on_other_skin(boot, monkeypatch):
    """Off Estuary, no Skin.SetBool is issued (the whole helper no-ops)."""
    monkeypatch.setattr(boot.mod.xbmc, "getSkinDir", lambda: "skin.confluence")
    boot.mod._trim_home_menu()
    assert not any(b.startswith("Skin.SetBool(") for b in boot.state["builtins"])


def test_trim_home_menu_writes_eight_hide_settings(boot):
    """Creates the file and sets all eight hide-booleans to true."""
    assert not boot.estuary_settings.exists()
    boot.mod._trim_home_menu()
    bools = _estuary_bools(boot)
    for sid in _HIDE_IDS:
        assert bools.get(sid) == "true", f"{sid} must be set true (hidden)"
    # exactly the eight singular ids the real skin uses (Movie/MusicVideo/TVShow)
    assert "homemenunomoviebutton" in bools and "homemenunomoviesbutton" not in bools
    assert (
        "homemenunomusicvideobutton" in bools
        and "homemenunomusicvideosbutton" not in bools
    )


def test_trim_home_menu_does_not_set_the_four_kept(boot):
    """The four kept items (TV, Add-ons, Favourites, Weather) must NOT be written
    when starting from no file — they stay visible by their absence."""
    boot.mod._trim_home_menu()
    bools = _estuary_bools(boot)
    for sid in _KEEP_IDS:
        assert sid not in bools, f"{sid} must NOT be set (kept visible)"


def test_trim_home_menu_preserves_existing_settings(boot):
    """Existing unrelated skin settings — and a pre-existing kept-id set to
    false — must survive untouched."""
    boot.estuary_settings.parent.mkdir(parents=True)
    boot.estuary_settings.write_text(
        "<settings>"
        '<setting id="homemenunofavbutton" type="bool">false</setting>'
        '<setting id="no_fanart" type="bool">false</setting>'
        '<setting id="HomeFanart.ext" type="string">.jpg</setting>'
        "</settings>"
    )
    boot.mod._trim_home_menu()
    bools = _estuary_bools(boot)
    # unrelated settings preserved
    assert bools.get("no_fanart") == "false"
    root = ET.parse(boot.estuary_settings).getroot()
    fanart = root.find("setting[@id='HomeFanart.ext']")
    assert fanart is not None and (fanart.text or "") == ".jpg"
    # the pre-existing kept-id stays false (not flipped to hide)
    assert bools.get("homemenunofavbutton") == "false"
    # and the eight hide-ids are now true
    for sid in _HIDE_IDS:
        assert bools.get(sid) == "true"


def test_trim_home_menu_is_idempotent(boot):
    """Running twice must not duplicate <setting> elements or change values."""
    boot.mod._trim_home_menu()
    boot.mod._trim_home_menu()
    root = ET.parse(boot.estuary_settings).getroot()
    ids = [s.get("id") for s in root.findall("setting")]
    for sid in _HIDE_IDS:
        assert ids.count(sid) == 1, f"{sid} duplicated on re-run"
    bools = _estuary_bools(boot)
    for sid in _HIDE_IDS:
        assert bools.get(sid) == "true"


def test_trim_home_menu_noop_on_other_skin(boot, monkeypatch):
    """When the active skin is not Estuary, it must be a safe no-op (write
    nothing)."""
    monkeypatch.setattr(boot.mod.xbmc, "getSkinDir", lambda: "skin.confluence")
    boot.mod._trim_home_menu()
    assert not boot.estuary_settings.exists(), "must not write when skin != estuary"


def test_trim_home_menu_recreates_malformed_file(boot):
    """A corrupt settings.xml must be rebuilt, not crash the run."""
    boot.estuary_settings.parent.mkdir(parents=True)
    boot.estuary_settings.write_text("<settings><setting not closed")
    boot.mod._trim_home_menu()  # must not raise
    bools = _estuary_bools(boot)
    for sid in _HIDE_IDS:
        assert bools.get(sid) == "true"


def test_trim_home_menu_never_raises(boot, monkeypatch):
    """Any failure must be swallowed so it can't abort the rest of setup."""
    real_open = open

    def boom(path, *a, **k):
        if str(path).endswith("settings.xml") and (
            "w" in (a[0] if a else k.get("mode", ""))
        ):
            raise OSError("disk full")
        return real_open(path, *a, **k)

    monkeypatch.setattr("builtins.open", boom)
    boot.mod._trim_home_menu()  # must not raise


def test_run_trims_home_menu(boot):
    """A full run must hide the eight Estuary home items."""
    boot.mod.run()
    bools = _estuary_bools(boot)
    for sid in _HIDE_IDS:
        assert bools.get(sid) == "true"
    for sid in _KEEP_IDS:
        assert sid not in bools


# --------------------------------------------------------------------------- #
# Shared-library wiring + one-shot video chaining (Option B / Phase 2)
# --------------------------------------------------------------------------- #
VIDEO_DEFAULT_PY = REPO_ROOT / "repo" / "script.tony7bones.video" / "default.py"


def test_requires_the_shared_module():
    """The manifest must declare the shared library as a required import so Kodi
    auto-installs script.module.tony7bones when this Setup is installed."""
    imp = _addon_root().find("requires/import[@addon='script.module.tony7bones']")
    assert imp is not None, "must <import> script.module.tony7bones"
    assert imp.get("version") == "1.0.0"


def test_imports_from_shared_module():
    """The duplicated machinery is gone — default.py imports it from the library."""
    src = DEFAULT_PY.read_text()
    assert "from tony7bones import" in src
    # the moved helpers must NOT be redefined locally any more
    assert "def _resolve_closure" not in src
    assert "def _install_with_deps" not in src
    assert "def _platform_tag" not in src
    assert "def _self_uninstall" not in src
    assert "def _restart_kodi" not in src


def test_one_shot_prompt_is_front_loaded_and_defaults_no():
    """The 'Include video add-ons?' yes/no must come BEFORE any install and
    default to No (opt-in) via DLG_YESNO_NO_BTN."""
    src = DEFAULT_PY.read_text()
    assert "Include video add-ons?" in src
    assert "DLG_YESNO_NO_BTN" in src, "must default the prompt to No"
    # the ask happens before the progress dialog / base install in run()
    ask_pos = src.find("_ask_also_video()")
    base_pos = src.find("_install_base(dialog)")
    assert ask_pos != -1 and base_pos != -1 and ask_pos < base_pos


def _install_video_setup_into(boot):
    """Drop the REAL video default.py into the fixture's addons dir so the base
    Setup's _load_video_module() can import it (it imports the shared library,
    already on sys.path via the fixture)."""
    vdir = boot.addons / "script.tony7bones.video"
    vdir.mkdir(exist_ok=True)
    (vdir / "default.py").write_text(VIDEO_DEFAULT_PY.read_text())
    (vdir / "addon.xml").write_text('<addon id="script.tony7bones.video"/>')
    # lay down a discoverable source repo so the video resolver finds an index
    repo = boot.addons / "repository.fake"
    repo.mkdir(exist_ok=True)
    (repo / "addon.xml").write_text(
        '<?xml version="1.0"?><addon id="repository.fake" version="1.0.0">'
        '<extension point="xbmc.addon.repository"><dir minversion="21.0.0">'
        "<info>https://fake.repo/zips/addons.xml</info>"
        "<datadir>https://fake.repo/zips/</datadir>"
        "</dir></extension></addon>"
    )
    return vdir


def test_one_shot_no_runs_base_only(boot):
    """Declining the video prompt = exactly today's base behaviour: no video apps,
    no video line in the summary, one restart prompt."""
    boot.state["also_video"] = False
    boot.mod.run()
    # base apps installed
    for aid in boot.mod.ADDONS:
        assert aid in boot.state["installed"]
    # NO video apps touched
    assert "plugin.video.pov" not in boot.state["installed"]
    # summary has NO video line
    _title, msg = boot.state["ok"][-1]
    assert "Video add-ons:" not in msg
    # exactly one restart prompt (the base end-of-setup one)
    restart_prompts = [
        m for _t, m in boot.state.get("yesno", []) if "needs to restart" in m
    ]
    assert len(restart_prompts) == 1


def test_one_shot_yes_chains_video_install(boot):
    """Choosing Yes + the default multiselect installs the base AND the selected
    video apps in ONE run, with ONE combined summary and ONE restart."""
    _install_video_setup_into(boot)
    # the video resolver fetches an index from the discovered fake repo; serve a
    # tiny one plus zips through the fixture's urlopen.
    extra_index = {
        "plugin.video.pov": ("6.0", [], "https://fake.repo/zips/x.zip", "r"),
        "plugin.video.the-loop": (
            "7.9",
            ["plugin.video.dailymotion_com"],
            "https://fake.repo/zips/x.zip",
            "r",
        ),
        "plugin.video.sporthdme": ("0.1", [], "https://fake.repo/zips/x.zip", "r"),
        "plugin.video.dailymotion_com": (
            "1.0",
            [],
            "https://fake.repo/zips/x.zip",
            "r",
        ),
    }

    import urllib.request as _ur

    _orig_urlopen = _ur.urlopen

    def _vid_urlopen(req, timeout=None):
        url = req.full_url if hasattr(req, "full_url") else req
        if "fake.repo" in url and "addons.xml" in url:
            parts = ['<?xml version="1.0"?>', "<addons>"]
            for aid, (ver, deps, _u, _o) in extra_index.items():
                parts.append(f'<addon id="{aid}" version="{ver}"><requires>')
                for d in deps:
                    parts.append(f'<import addon="{d}" version="1.0.0"/>')
                parts.append("</requires></addon>")
            parts.append("</addons>")
            data = "".join(parts).encode()
            return _FakeResp(_gzip.compress(data) if url.endswith(".gz") else data)
        if "mirrors.kodi.tv" in url and "addons.xml" in url:
            data = b'<?xml version="1.0"?><addons></addons>'
            return _FakeResp(_gzip.compress(data) if url.endswith(".gz") else data)
        if url.endswith(".zip") and "fake.repo" in url:
            # video zips all share the 'x.zip' name, so extract every selected
            # video id deterministically here.
            for aid in extra_index:
                boot.state["extracted"].add(aid)
            buf = io.BytesIO()
            with _zipfile.ZipFile(buf, "w") as z:
                z.writestr("x/addon.xml", '<addon id="x"/>')
            return _FakeResp(buf.getvalue())
        # base apps + their index/zips go through the fixture's own urlopen
        return _orig_urlopen(req, timeout=timeout)

    _ur.urlopen = _vid_urlopen
    try:
        boot.state["also_video"] = True
        boot.state["video_pick"] = [0, 1, 2]  # POV, The Loop, Sports HD
        boot.mod.run()
    finally:
        _ur.urlopen = _orig_urlopen

    s = boot.state
    # base still installed
    for aid in boot.mod.ADDONS:
        assert aid in s["installed"], f"base {aid} missing"
    # multiselect was shown up front
    assert s.get("multiselect"), "the video multiselect must be shown"
    _t, options, preselect = s["multiselect"][-1]
    assert options == ["POV", "The Loop", "Sports HD", "Umbrella"]
    assert preselect == [0, 1, 2]
    # the chosen video apps installed
    for aid in ("plugin.video.pov", "plugin.video.the-loop", "plugin.video.sporthdme"):
        assert aid in s["installed"], f"video {aid} not installed"
    # Dailymotion installed-but-disabled
    assert "plugin.video.dailymotion_com" in s["installed"]
    assert "plugin.video.dailymotion_com" in s["disabled"]
    # ONE combined summary with both base and video counts
    _title, msg = s["ok"][-1]
    assert "Apps:" in msg and "Video add-ons:" in msg
    # exactly ONE restart prompt for the whole run
    restart_prompts = [m for _t, m in s.get("yesno", []) if "needs to restart" in m]
    assert len(restart_prompts) == 1, "exactly one restart for the whole one-shot run"


def test_one_shot_yes_removes_both_setup_tiles(boot):
    """A chained run self-removes BOTH the base and the video Setup dirs, but
    LEAVES the shared library module installed (it is a hidden dependency)."""
    base_dir = boot.addons / "script.tony7bones.bootstrap"
    base_dir.mkdir()
    (base_dir / "addon.xml").write_text('<addon id="script.tony7bones.bootstrap"/>')
    _install_video_setup_into(boot)

    import urllib.request as _ur

    _orig = _ur.urlopen

    def _u(req, timeout=None):
        url = req.full_url if hasattr(req, "full_url") else req
        if "fake.repo" in url and "addons.xml" in url:
            return _FakeResp(b'<?xml version="1.0"?><addons></addons>')
        if "mirrors.kodi.tv" in url and "addons.xml" in url:
            return _FakeResp(b'<?xml version="1.0"?><addons></addons>')
        return _orig(req, timeout=timeout)

    _ur.urlopen = _u
    try:
        boot.state["also_video"] = True
        boot.state["video_pick"] = [0]
        boot.mod.run()
    finally:
        _ur.urlopen = _orig

    assert not base_dir.exists(), "base Setup tile must be removed"
    assert not (boot.addons / "script.tony7bones.video").exists(), (
        "chained video Setup tile must be removed too"
    )


# --------------------------------------------------------------------------- #
# Regression: the one-shot video step must NOT silently vanish when the Video
# Add-ons Setup add-on is not yet installed (the original production bug).
#
# On a fresh box the user installs our repo + runs THIS base Setup; the Video
# Add-ons Setup add-on is usually NOT installed. The old code asked "Also install
# Video Add-ons?", got Yes, then _load_video_module() returned None and the whole
# video step disappeared with no prompt, no error, no summary line — exactly what
# was reported from the Fire Stick run. run() must instead fetch the Video Setup
# (via _ensure_video_setup_installed) before loading it, then run the picker and
# the video install. These tests fail against the pre-fix code.
# --------------------------------------------------------------------------- #
def test_one_shot_yes_fetches_video_setup_when_absent(boot, monkeypatch):
    """Yes + Video Setup NOT installed: run() must fetch it (so the picker and the
    video install actually happen), not silently fall back to base-only."""
    # Deliberately do NOT _install_video_setup_into(boot): the video add-on is
    # absent, mirroring a fresh box. Lay down a discoverable source repo so the
    # video resolver can build an index once the module is loaded.
    repo = boot.addons / "repository.fake"
    repo.mkdir(exist_ok=True)
    (repo / "addon.xml").write_text(
        '<?xml version="1.0"?><addon id="repository.fake" version="1.0.0">'
        '<extension point="xbmc.addon.repository"><dir minversion="21.0.0">'
        "<info>https://fake.repo/zips/addons.xml</info>"
        "<datadir>https://fake.repo/zips/</datadir>"
        "</dir></extension></addon>"
    )

    # The real _ensure_video_setup_installed() would download the video zip from
    # Pages and extract it; here we stand in for that fetch by dropping the REAL
    # video default.py into the addons dir, then call through. This proves run()
    # invokes the fetch step AND that after it the module becomes loadable.
    calls = {"ensure": 0}
    real_ensure = boot.mod._ensure_video_setup_installed

    def _fake_ensure():
        calls["ensure"] += 1
        vdir = boot.addons / "script.tony7bones.video"
        vdir.mkdir(exist_ok=True)
        (vdir / "default.py").write_text(VIDEO_DEFAULT_PY.read_text())
        (vdir / "addon.xml").write_text('<addon id="script.tony7bones.video"/>')

    monkeypatch.setattr(boot.mod, "_ensure_video_setup_installed", _fake_ensure)
    assert real_ensure is not None  # the fix's helper must exist

    extra_index = {
        "plugin.video.pov": ("6.0", []),
        "plugin.video.the-loop": ("7.9", ["plugin.video.dailymotion_com"]),
        "plugin.video.sporthdme": ("0.1", []),
        "plugin.video.dailymotion_com": ("1.0", []),
    }

    import urllib.request as _ur

    _orig = _ur.urlopen

    def _u(req, timeout=None):
        url = req.full_url if hasattr(req, "full_url") else req
        if "fake.repo" in url and "addons.xml" in url:
            parts = ['<?xml version="1.0"?>', "<addons>"]
            for aid, (ver, deps) in extra_index.items():
                parts.append(f'<addon id="{aid}" version="{ver}"><requires>')
                for d in deps:
                    parts.append(f'<import addon="{d}" version="1.0.0"/>')
                parts.append("</requires></addon>")
            parts.append("</addons>")
            return _FakeResp("".join(parts).encode())
        if "mirrors.kodi.tv" in url and "addons.xml" in url:
            return _FakeResp(b'<?xml version="1.0"?><addons></addons>')
        if url.endswith(".zip") and "fake.repo" in url:
            for aid in extra_index:
                boot.state["extracted"].add(aid)
            buf = io.BytesIO()
            with _zipfile.ZipFile(buf, "w") as z:
                z.writestr("x/addon.xml", '<addon id="x"/>')
            return _FakeResp(buf.getvalue())
        return _orig(req, timeout=timeout)

    _ur.urlopen = _u
    try:
        boot.state["also_video"] = True
        boot.state["video_pick"] = [0, 1, 2]
        boot.mod.run()
    finally:
        _ur.urlopen = _orig

    s = boot.state
    # The fetch step must have been invoked (this is the heart of the fix).
    assert calls["ensure"] == 1, "run() must fetch the Video Setup when it is absent"
    # The picker must have been shown (it was silently skipped before the fix).
    assert s.get("multiselect"), "the video picker must be shown after the fetch"
    # The chosen video apps must actually install — not silently vanish.
    for aid in ("plugin.video.pov", "plugin.video.the-loop", "plugin.video.sporthdme"):
        assert aid in s["installed"], f"video {aid} must install on a fresh box"
    # Combined summary names both base and video — never a base-only summary.
    _title, msg = s["ok"][-1]
    assert "Apps:" in msg and "Video add-ons:" in msg


def test_one_shot_yes_surfaces_video_load_failure(boot, monkeypatch):
    """If Yes is chosen but the Video Setup cannot be fetched/loaded, run() must
    say so in the summary instead of silently dropping the whole video step (and
    base install must still complete)."""
    # No video add-on present, and the fetch is a no-op (simulating a failed
    # download), so _load_video_module() returns None.
    monkeypatch.setattr(boot.mod, "_ensure_video_setup_installed", lambda: None)
    boot.state["also_video"] = True
    boot.mod.run()

    # base install still happened
    for aid in boot.mod.ADDONS:
        assert aid in boot.state["installed"]
    # no picker (module never loaded) and the failure is surfaced, not silent
    assert not boot.state.get("multiselect"), "no picker when the module won't load"
    _title, msg = boot.state["ok"][-1]
    assert "could not load" in msg.lower(), (
        "a video load failure must be surfaced in the summary, not silently dropped"
    )


def test_ensure_video_setup_runs_before_self_uninstall_and_restart():
    """Source-level ordering guard: the fetch step must be wired BEFORE the
    self-uninstall + restart so the chained video install can run first."""
    src = DEFAULT_PY.read_text()
    ensure_pos = src.find("_ensure_video_setup_installed()")
    install_video_pos = src.find("_install_video(")
    uninstall_pos = src.find("self_uninstall(MY_ID")
    restart_pos = src.find('restart_kodi("Tony.7.Bones Setup"')
    assert ensure_pos != -1, "run() must call _ensure_video_setup_installed()"
    assert ensure_pos < install_video_pos < uninstall_pos < restart_pos, (
        "fetch -> video install -> self-uninstall -> restart ordering must hold"
    )


# --------------------------------------------------------------------------- #
# Base box configuration (_configure_box): weather provider + Sacramento
# location, RSS news ticker off, Estuary top-bar weather.
# --------------------------------------------------------------------------- #
def _settings_set(boot):
    """{setting_id: value} from captured Settings.SetSettingValue JSON-RPC calls."""
    out = {}
    for s in boot.state["jsonrpc"]:
        try:
            d = _json.loads(s)
        except ValueError:
            continue
        if d.get("method") == "Settings.SetSettingValue":
            out[d["params"]["setting"]] = d["params"]["value"]
    return out


def test_configure_box_helper_exists_and_wired_before_restart():
    src = DEFAULT_PY.read_text()
    assert "_configure_box" in src and "_configure_box()" in src
    cfg = src.rfind("_configure_box()")
    restart = src.rfind("restart_kodi(")
    assert cfg != -1 and restart != -1 and cfg < restart, (
        "_configure_box() must run before the restart"
    )


def test_configure_box_sets_weather_provider(boot):
    boot.mod._configure_box()
    assert _settings_set(boot).get("weather.addon") == "weather.multi"


def test_configure_box_enables_rss_feeds(boot):
    boot.mod._configure_box()
    assert _settings_set(boot).get("lookandfeel.enablerssfeeds") is True


def test_configure_box_writes_sacramento_location(boot):
    boot.mod._configure_box()
    path = boot.mod._weather_multi_settings_path()
    vals = {
        s.get("id"): (s.text or "") for s in ET.parse(path).getroot().findall("setting")
    }
    assert vals.get("loc1_name") == "Sacramento, CA, US"
    # loc1_url is the load-bearing field: weather.multi fetches the forecast from
    # https://weather.yahoo.com/<loc1_url>; an empty url means no fetch at all.
    assert vals.get("loc1_url") == "us/ca/sacramento", "fetch url must be written"
    assert vals.get("loc1_lat") and vals.get("loc1_lon"), "coords must be written"


def test_configure_box_sets_topbar_weather_skin_bool(boot):
    boot.mod._configure_box()
    assert "Skin.SetBool(show_weatherinfo)" in boot.state["builtins"]


def test_configure_box_topbar_skipped_off_estuary_but_core_settings_apply(
    boot, monkeypatch
):
    monkeypatch.setattr(boot.mod.xbmc, "getSkinDir", lambda: "skin.confluence")
    boot.mod._configure_box()
    assert "Skin.SetBool(show_weatherinfo)" not in boot.state["builtins"]
    # Core (non-skin) settings still apply regardless of skin.
    assert _settings_set(boot).get("weather.addon") == "weather.multi"


def test_configure_box_never_raises(boot, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("boom")

    monkeypatch.setattr(boot.mod.xbmc, "executeJSONRPC", boom)
    boot.mod._configure_box()  # must not raise


def test_run_configures_box(boot):
    boot.mod.run()
    s = _settings_set(boot)
    assert s.get("weather.addon") == "weather.multi"
    assert s.get("lookandfeel.enablerssfeeds") is True


# --------------------------------------------------------------------------- #
# Device → userdata file copies (DEVICE_FILE_COPIES / _copy_device_files, called
# from _configure_box). The sources are device "Kodi sources directory" paths;
# on the test host they do not exist, so we point DEVICE_FILE_COPIES at real temp
# files to exercise the copy path, and leave them unmapped for the guarded-skip
# path. Covers the custom RssFeeds.xml plus pvr.iptvsimple's instance settings
# and custom TV channel groups (whose channelGroups/ dir must be auto-created).
# --------------------------------------------------------------------------- #
# special:// destinations of the three configured copies.
_RSS_DST = "special://home/userdata/RssFeeds.xml"
_IPTV_INSTANCE_DST = (
    "special://home/userdata/addon_data/pvr.iptvsimple/instance-settings-1.xml"
)
_IPTV_GROUPS_DST = (
    "special://home/userdata/addon_data/pvr.iptvsimple/channelGroups/"
    "customTVGroups-Network24.xml"
)


def _dst_path(boot, special):
    """Absolute (translated) path of a special:// destination."""
    return boot.mod.xbmcvfs.translatePath(special)


def test_default_device_file_copies_are_the_three_expected(boot):
    """The data-driven list must hold the RSS feed + the two pvr.iptvsimple files,
    each to userdata/addon_data (private config never goes near the repo)."""
    dsts = [d for _s, d in boot.mod.DEVICE_FILE_COPIES]
    assert _RSS_DST in dsts
    assert _IPTV_INSTANCE_DST in dsts
    assert _IPTV_GROUPS_DST in dsts
    assert len(boot.mod.DEVICE_FILE_COPIES) == 3
    # Every source is a device path; every dest lives under userdata.
    for src, dst in boot.mod.DEVICE_FILE_COPIES:
        assert src.startswith("/storage/")
        assert dst.startswith("special://home/userdata/")


def _point_copies(boot, monkeypatch, tmp_path, mapping):
    """Repoint DEVICE_FILE_COPIES so the given special:// dests read from temp
    files (others get a guaranteed-missing source)."""
    new = []
    for src, dst in boot.mod.DEVICE_FILE_COPIES:
        if dst in mapping:
            new.append((str(mapping[dst]), dst))
        else:
            new.append((str(tmp_path / "missing" / os.path.basename(src)), dst))
    monkeypatch.setattr(boot.mod, "DEVICE_FILE_COPIES", new)


def test_copy_device_files_copies_rss_when_source_present(boot, monkeypatch, tmp_path):
    src = tmp_path / "RssFeeds.xml"
    src.write_text("<rssfeeds>CUSTOM</rssfeeds>")
    _point_copies(boot, monkeypatch, tmp_path, {_RSS_DST: src})
    boot.mod._copy_device_files()
    dst = _dst_path(boot, _RSS_DST)
    assert os.path.exists(dst), "custom RssFeeds.xml must be copied to userdata"
    assert "CUSTOM" in open(dst).read()


def test_copy_device_files_copies_iptv_instance_settings(boot, monkeypatch, tmp_path):
    src = tmp_path / "instance-settings-1.xml"
    src.write_text("<settings>INSTANCE</settings>")
    _point_copies(boot, monkeypatch, tmp_path, {_IPTV_INSTANCE_DST: src})
    boot.mod._copy_device_files()
    dst = _dst_path(boot, _IPTV_INSTANCE_DST)
    assert os.path.exists(dst), "instance-settings-1.xml must be copied to addon_data"
    assert "INSTANCE" in open(dst).read()
    # The addon_data/pvr.iptvsimple/ dir must have been created on the fresh box.
    assert os.path.isdir(os.path.dirname(dst))


def test_copy_device_files_copies_tv_groups_creating_channelgroups_dir(
    boot, monkeypatch, tmp_path
):
    """The customTVGroups copy must auto-create the channelGroups/ subdir, which
    does NOT exist on a fresh box, then land the file inside it."""
    src = tmp_path / "customTVGroups-Network24.xml"
    src.write_text("<groups>NET24</groups>")
    _point_copies(boot, monkeypatch, tmp_path, {_IPTV_GROUPS_DST: src})
    dst = _dst_path(boot, _IPTV_GROUPS_DST)
    # Prove the channelGroups/ dir is absent before the copy runs.
    assert not os.path.isdir(os.path.dirname(dst))
    boot.mod._copy_device_files()
    assert os.path.isdir(os.path.dirname(dst)), "channelGroups/ must be auto-created"
    assert os.path.exists(dst) and "NET24" in open(dst).read()


def test_copy_device_files_skips_when_source_missing(boot, monkeypatch, tmp_path):
    # All sources point at non-existent files (the default /storage path stand-in).
    _point_copies(boot, monkeypatch, tmp_path, {})
    boot.mod._copy_device_files()  # guarded no-op
    for special in (_RSS_DST, _IPTV_INSTANCE_DST, _IPTV_GROUPS_DST):
        assert not os.path.exists(_dst_path(boot, special)), "no copy when src absent"


def test_copy_device_files_overwrites_existing_destinations(
    boot, monkeypatch, tmp_path
):
    # Seed each destination with old content, then copy custom content over it.
    seeds = {
        _RSS_DST: ("RssFeeds.xml", "<rssfeeds>CUSTOM</rssfeeds>"),
        _IPTV_INSTANCE_DST: ("instance-settings-1.xml", "<settings>NEW</settings>"),
        _IPTV_GROUPS_DST: ("customTVGroups-Network24.xml", "<groups>NEW</groups>"),
    }
    mapping = {}
    for special, (fname, content) in seeds.items():
        dst = _dst_path(boot, special)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        with open(dst, "w") as f:
            f.write("<x>DEFAULT</x>")
        src = tmp_path / fname
        src.write_text(content)
        mapping[special] = src
    _point_copies(boot, monkeypatch, tmp_path, mapping)
    boot.mod._copy_device_files()
    for special, (_fname, content) in seeds.items():
        got = open(_dst_path(boot, special)).read()
        assert content in got and "DEFAULT" not in got, f"must overwrite {special}"


def test_copy_device_files_never_raises(boot, monkeypatch):
    # Even if xbmcvfs.copy blows up for every entry, the step must swallow each
    # error and continue through the rest of the list.
    def boom(*a, **k):
        raise RuntimeError("boom")

    monkeypatch.setattr(boot.mod.xbmcvfs, "exists", lambda p: True)
    monkeypatch.setattr(boot.mod.xbmcvfs, "copy", boom)
    boot.mod._copy_device_files()  # must not raise


def test_configure_box_default_sources_missing_is_guarded(boot):
    # With the real default /storage/... sources the files cannot exist on the
    # test host: _configure_box must still complete and apply the other settings
    # without raising or copying anything. The two USER-PROVIDED-ONLY copies (RSS
    # feeds + custom TV groups) must NOT appear. The instance-settings file is the
    # exception: the IPTV custom-groups enforce step creates it from scratch on a
    # fresh box (no device file needed), so it is expected to exist with the keys.
    boot.mod._configure_box()
    for special in (_RSS_DST, _IPTV_GROUPS_DST):
        assert not os.path.exists(_dst_path(boot, special)), "no copy on desktop"
    inst = _dst_path(boot, _IPTV_INSTANCE_DST)
    assert os.path.exists(inst), "enforce step creates instance-settings on a fresh box"
    got = _read_instance_settings(boot)
    assert got["tvGroupMode"] == "2"
    assert got["customTvGroupsFile"].endswith("customTVGroups-Network24.xml")
    assert _settings_set(boot).get("weather.addon") == "weather.multi"


# --------------------------------------------------------------------------- #
# IPTV custom-TV-groups instance-settings keys (1a/1b). These are pvr.iptvsimple
# INSTANCE settings — they live ONLY in instance-settings-1.xml (JSON-RPC's
# Settings.SetSettingValue cannot reach add-on instance settings), so the Setup
# enforces them by writing that file directly, after the device-file copy.
# --------------------------------------------------------------------------- #


def _read_instance_settings(boot):
    """Parse instance-settings-1.xml and return {id: text} for its <setting>s."""
    path = _dst_path(boot, boot.mod.IPTV_INSTANCE_SETTINGS_SPECIAL)
    root = ET.parse(path).getroot()
    return {s.get("id"): (s.text or "") for s in root.findall("setting")}


def test_ensure_iptv_groups_constants_match_schema():
    """The enforced values must be the schema's CUSTOM_GROUPS enum (2) and a
    channelGroups path pointing at the Network24 file we copy."""
    boot_src = DEFAULT_PY.read_text()
    assert 'IPTV_TV_GROUP_MODE_CUSTOM = "2"' in boot_src
    assert "tvGroupMode" in boot_src
    assert "customTvGroupsFile" in boot_src
    assert "customTVGroups-Network24.xml" in boot_src


def test_ensure_iptv_groups_creates_file_when_absent(boot):
    """On a fresh box with no copied instance-settings file, the step creates one
    with both keys correct (and the addon_data dir)."""
    path = _dst_path(boot, boot.mod.IPTV_INSTANCE_SETTINGS_SPECIAL)
    assert not os.path.exists(path)
    boot.mod._ensure_iptv_custom_tv_groups()
    got = _read_instance_settings(boot)
    assert got["tvGroupMode"] == "2"
    assert got["customTvGroupsFile"].endswith("customTVGroups-Network24.xml")
    assert "channelGroups" in got["customTvGroupsFile"]


def test_ensure_iptv_groups_patches_copied_file(boot):
    """When the user's instance-settings-1.xml was copied with the DEFAULT
    tvGroupMode=0 + example file, the step rewrites both keys and preserves the
    other settings (e.g. m3uUrl)."""
    path = _dst_path(boot, boot.mod.IPTV_INSTANCE_SETTINGS_SPECIAL)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(
            '<settings version="2">'
            '<setting id="m3uUrl">http://example/list.m3u</setting>'
            '<setting id="tvGroupMode" default="true">0</setting>'
            '<setting id="customTvGroupsFile" default="true">'
            "special://userdata/addon_data/pvr.iptvsimple/channelGroups/"
            "customTVGroups-example.xml</setting>"
            "</settings>"
        )
    boot.mod._ensure_iptv_custom_tv_groups()
    got = _read_instance_settings(boot)
    assert got["tvGroupMode"] == "2"
    assert got["customTvGroupsFile"].endswith("customTVGroups-Network24.xml")
    # Unrelated user settings survive untouched.
    assert got["m3uUrl"] == "http://example/list.m3u"
    # The default="true" flag is dropped on the keys we now override.
    root = ET.parse(path).getroot()
    for s in root.findall("setting"):
        if s.get("id") in ("tvGroupMode", "customTvGroupsFile"):
            assert s.get("default") is None


def test_ensure_iptv_groups_respects_user_value_when_already_custom(boot):
    """If the copied file already sets tvGroupMode=2 + the Network24 file, the
    step is a no-op (no rewrite needed) and the values stay correct."""
    path = _dst_path(boot, boot.mod.IPTV_INSTANCE_SETTINGS_SPECIAL)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    good_file = boot.mod.IPTV_CUSTOM_TV_GROUPS_FILE_VALUE
    with open(path, "w") as f:
        f.write(
            '<settings version="2">'
            '<setting id="tvGroupMode">2</setting>'
            f'<setting id="customTvGroupsFile">{good_file}</setting>'
            "</settings>"
        )
    before = open(path).read()
    boot.mod._ensure_iptv_custom_tv_groups()
    got = _read_instance_settings(boot)
    assert got["tvGroupMode"] == "2"
    assert got["customTvGroupsFile"] == good_file
    # No-op: content unchanged byte-for-byte.
    assert open(path).read() == before


def test_ensure_iptv_groups_recreates_malformed_file(boot):
    """A malformed instance-settings file is replaced with a valid one carrying
    both keys, never raising."""
    path = _dst_path(boot, boot.mod.IPTV_INSTANCE_SETTINGS_SPECIAL)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write("<settings><not-closed>")
    boot.mod._ensure_iptv_custom_tv_groups()
    got = _read_instance_settings(boot)
    assert got["tvGroupMode"] == "2"
    assert got["customTvGroupsFile"].endswith("customTVGroups-Network24.xml")


def test_ensure_iptv_groups_is_idempotent(boot):
    """Two runs converge — second run changes nothing."""
    boot.mod._ensure_iptv_custom_tv_groups()
    path = _dst_path(boot, boot.mod.IPTV_INSTANCE_SETTINGS_SPECIAL)
    first = open(path).read()
    boot.mod._ensure_iptv_custom_tv_groups()
    assert open(path).read() == first


def test_ensure_iptv_groups_never_raises(boot, monkeypatch):
    """Any write failure is swallowed (never aborts the rest of setup)."""

    def boom(*a, **k):
        raise RuntimeError("boom")

    # makedirs is the first filesystem op in the step — make it explode.
    monkeypatch.setattr(boot.mod.os, "makedirs", boom)
    boot.mod._ensure_iptv_custom_tv_groups()  # must not raise


def test_ensure_iptv_groups_wired_into_configure_box_after_copy():
    """_configure_box must call the enforce step, and AFTER the device-file copy
    (so it patches the copied file rather than being overwritten by it)."""
    src = DEFAULT_PY.read_text()
    assert "_ensure_iptv_custom_tv_groups()" in src
    copy_at = src.find("_copy_device_files()", src.find("def _configure_box"))
    ensure_at = src.find(
        "_ensure_iptv_custom_tv_groups()", src.find("def _configure_box")
    )
    assert 0 < copy_at < ensure_at, "enforce step must run after the copy"
