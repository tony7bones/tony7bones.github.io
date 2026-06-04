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
import re
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
    assert rl.is_greater(v, "1.0.21"), f"version {v} must exceed the old 1.0.21"


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
    assert "_resolve_closure" in src and "_install_with_deps" in src


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
    src = DEFAULT_PY.read_text()
    assert "_platform_tag" in src, "binary add-ons need runtime platform detection"


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
    restart via a yes/no prompt — never a silent or forced restart."""
    src = DEFAULT_PY.read_text()
    assert "_restart_kodi" in src, "restart helper must exist"
    assert "_restart_kodi()" in src, "restart helper must be invoked in run()"
    assert "yesno(" in src, "the restart must be user-confirmed (yesno)"


def test_restart_is_platform_correct():
    """Desktop uses RestartApp(); Android (which can't relaunch) uses Quit()
    after telling the user to reopen Kodi by hand."""
    src = DEFAULT_PY.read_text()
    assert "RestartApp()" in src, "desktop restart must use RestartApp()"
    assert "_is_android" in src, "must branch on Android (no RestartApp there)"
    assert "Quit()" in src, "Android path must Quit() so the user can reopen"


def test_restart_comes_after_success_summary():
    """The restart prompt must follow the counts dialog, not replace it."""
    src = DEFAULT_PY.read_text()
    ok_pos = src.rfind("Open Add-ons to finish")
    restart_pos = src.rfind("_restart_kodi()")
    assert ok_pos != -1 and restart_pos != -1
    assert restart_pos > ok_pos, "restart prompt must come after the summary dialog"


# --------------------------------------------------------------------------- #
# Self-uninstall (run once, then disappear — no leftover home tile)
# --------------------------------------------------------------------------- #
def test_self_uninstall_logic_exists():
    """The setup must remove itself after a successful run. Kodi 21 Omega has no
    UninstallAddon builtin and no JSON-RPC uninstall method, so the supported
    mechanism is: delete our own add-on directory and let the end-of-setup
    restart de-register it. The code must therefore reference its own add-on id
    and delete that directory."""
    src = DEFAULT_PY.read_text()
    assert "_self_uninstall" in src, "self-uninstall helper must exist"
    assert "_self_uninstall()" in src, "self-uninstall must be invoked in run()"
    assert "script.tony7bones.bootstrap" in src, (
        "self-uninstall must target the add-on's own id"
    )
    # It must actually delete its own directory (the supported uninstall path).
    assert "rmtree" in src, "self-uninstall must delete its own add-on directory"
    assert "special://home/addons/" in src, "must resolve its own addons/ path"


def test_self_uninstall_runs_after_summary_and_before_restart():
    """Sequence must be: summary dialog -> self-uninstall -> restart prompt.
    The restart is what finalises the removal (startup scan drops the DB row)."""
    src = DEFAULT_PY.read_text()
    ok_pos = src.rfind("Open Add-ons to finish")
    uninstall_pos = src.rfind("_self_uninstall()")
    restart_pos = src.rfind("_restart_kodi()")
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
            # Kodi only enables an add-on it has scanned (extracted on disk).
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

        def yesno(self, title, msg, **kwargs):
            # Record the restart prompt; decline so run() never restarts in tests.
            state.setdefault("yesno", []).append((title, msg))
            return False

    xbmcgui.DialogProgress = _DP
    xbmcgui.Dialog = _Dialog

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

    xbmcvfs.exists = _exists
    xbmcvfs.mkdirs = _mkdirs

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

    spec = importlib.util.spec_from_file_location("boot_default", DEFAULT_PY)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # run() is __main__-guarded, so this does not run it
    return types.SimpleNamespace(
        mod=mod, state=state, addons=addons, sources_xml=sources_xml
    )


def test_no_unknown_sources_jsonrpc_during_run(boot):
    """A full run must never send a Settings.SetSettingValue for
    addons.unknownsources — that is what pops the security prompt."""
    boot.mod.run()
    assert not any("addons.unknownsources" in s for s in boot.state["jsonrpc"])


def test_platform_tag_returns_kodi_arch_string(boot):
    """The platform tag must look like Kodi's binary datadir suffix
    (e.g. osx-arm64, windows-x86_64) or None on platforms not served here."""
    tag = boot.mod._platform_tag()
    assert tag is None or re.match(r"^(osx|windows|android)-", tag), tag


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
    # the fake zip lays down <id>/addon.xml using the id parsed from the name
    assert (boot.addons / "repository.foo" / "addon.xml").exists()


def test_extract_zip_failure(boot, monkeypatch):
    def boom(*a, **k):
        raise OSError("download failed")

    monkeypatch.setattr(urllib.request, "urlopen", boom)
    dp = boot.mod.xbmcgui.DialogProgress()
    assert boot.mod._extract_zip("https://x/y.zip", dp, 50) is False


# --- dependency resolver + direct-install units ---------------------------- #
def test_resolve_closure_walks_dependencies(boot):
    """The closure must include the app AND its transitive module deps, with
    dependencies ordered before the add-on that imports them, and system
    imports (xbmc.* / kodi.*) excluded."""
    idx = boot.state["index"]
    indexes = [("https://peno64", idx), ("https://official", idx)]
    closure = boot.mod._resolve_closure(["script.ezmaintenanceplus"], indexes)
    ids = [aid for aid, _url in closure]
    assert "script.ezmaintenanceplus" in ids
    assert "script.module.requests" in ids
    assert "script.module.urllib3" in ids  # transitive dep of requests
    assert not any(i.startswith(("xbmc.", "kodi.")) for i in ids)
    # dependency must come before the add-on that imports it
    assert ids.index("script.module.requests") < ids.index("script.ezmaintenanceplus")
    assert ids.index("script.module.urllib3") < ids.index("script.module.requests")


def test_load_index_skips_optional_imports(boot, monkeypatch):
    """_load_index must drop imports flagged optional="true": Kodi installs
    optional deps on-demand, so resolving them into the closure over-installs
    add-ons nothing requires (the plugin.googledrive-via-resolveurl bug)."""
    xml = (
        '<?xml version="1.0"?><addons>'
        '<addon id="script.module.resolveurl" version="5.1.0"><requires>'
        '<import addon="script.module.required.dep" version="1.0.0"/>'
        '<import addon="plugin.googledrive" version="1.0.0" optional="true"/>'
        "</requires></addon></addons>"
    ).encode("utf-8")
    monkeypatch.setattr(
        urllib.request,
        "urlopen",
        lambda req, timeout=None: _FakeResp(_gzip.compress(xml)),
    )
    idx = boot.mod._load_index("https://official", None)
    _ver, deps, _path = idx["script.module.resolveurl"]
    assert "script.module.required.dep" in deps, "required import must be kept"
    assert "plugin.googledrive" not in deps, "optional import must be skipped"


def test_resolve_closure_skips_optional_dep(boot, monkeypatch):
    """End-to-end: a target with one required + one optional dep resolves only
    the required one. plugin.googledrive (optional) must never be pulled in."""
    xml = (
        '<?xml version="1.0"?><addons>'
        '<addon id="plugin.video.the-loop" version="7.9"><requires>'
        '<import addon="script.module.resolveurl" version="1.0.0"/>'
        "</requires></addon>"
        '<addon id="script.module.resolveurl" version="5.1.0"><requires>'
        '<import addon="script.module.requests" version="1.0.0"/>'
        '<import addon="plugin.googledrive" version="1.0.0" optional="true"/>'
        "</requires></addon>"
        '<addon id="script.module.requests" version="2.31.0"><requires/></addon>'
        '<addon id="plugin.googledrive" version="3.0.0"><requires/></addon>'
        "</addons>"
    ).encode("utf-8")
    monkeypatch.setattr(
        urllib.request,
        "urlopen",
        lambda req, timeout=None: _FakeResp(_gzip.compress(xml)),
    )
    idx = boot.mod._load_index("https://official", None)
    closure = boot.mod._resolve_closure(["plugin.video.the-loop"], [("https://x", idx)])
    ids = [aid for aid, _url in closure]
    assert "plugin.video.the-loop" in ids
    assert "script.module.resolveurl" in ids
    assert "script.module.requests" in ids  # required transitive dep present
    assert "plugin.googledrive" not in ids, "optional dep must NOT be installed"


def test_resolve_closure_skips_unresolvable(boot):
    indexes = [("https://x", boot.state["index"])]
    closure = boot.mod._resolve_closure(["script.does.not.exist"], indexes)
    assert closure == []


def test_install_with_deps_extracts_and_enables(boot):
    dp = boot.mod.xbmcgui.DialogProgress()
    assert boot.mod._install_with_deps("script.ezmaintenanceplus", dp)
    s = boot.state
    # the app and its dependency closure were extracted AND enabled
    assert "script.ezmaintenanceplus" in s["installed"]
    assert "script.module.requests" in s["installed"]
    # no modal installer was ever invoked
    assert not any(b.startswith("InstallAddon(") for b in s["builtins"])
    # the local add-on store was rescanned so Kodi sees the extracted dirs
    assert "UpdateLocalAddons()" in s["builtins"]


def test_install_with_deps_skips_already_installed(boot):
    boot.state["installed"].add("script.realdebrid")
    dp = boot.mod.xbmcgui.DialogProgress()
    assert boot.mod._install_with_deps("script.realdebrid", dp)
    # already present → nothing extracted
    assert "script.realdebrid" not in boot.state["extracted"]


def test_install_with_deps_reports_failure_when_unresolvable(boot):
    dp = boot.mod.xbmcgui.DialogProgress()
    assert boot.mod._install_with_deps("script.does.not.exist", dp) is False


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


def test_load_index_keeps_noarch_and_filters_arch(boot, monkeypatch):
    """A 'platform=all' entry (e.g. weather.multi, script.module.requests) is
    universal and must be kept; arch-tagged duplicates must be filtered to this
    machine's tag. Regression: an 'all' tag must not be mistaken for an arch."""
    xml = (
        '<?xml version="1.0"?><addons>'
        '<addon id="weather.multi" version="1.1.0"><requires/>'
        '<extension point="xbmc.addon.metadata"><platform>all</platform>'
        "<path>weather.multi/weather.multi-1.1.0.zip</path></extension></addon>"
        '<addon id="pvr.iptvsimple" version="21.11.0"><requires/>'
        '<extension point="xbmc.addon.metadata"><platform>osx-arm64</platform>'
        "<path>pvr.iptvsimple+osx-arm64/pvr.iptvsimple-21.11.0.zip</path>"
        "</extension></addon>"
        '<addon id="pvr.iptvsimple" version="21.11.0"><requires/>'
        '<extension point="xbmc.addon.metadata"><platform>windows-x86_64</platform>'
        "<path>pvr.iptvsimple+windows-x86_64/pvr.iptvsimple-21.11.0.zip</path>"
        "</extension></addon>"
        "</addons>"
    ).encode("utf-8")
    monkeypatch.setattr(
        urllib.request,
        "urlopen",
        lambda req, timeout=None: _FakeResp(_gzip.compress(xml)),
    )
    idx = boot.mod._load_index("https://official", "osx-arm64")
    assert "weather.multi" in idx, "platform=all entry must be kept"
    assert idx["pvr.iptvsimple"][2].startswith("pvr.iptvsimple+osx-arm64/")


def test_binary_addon_resolves_to_platform_path(boot):
    """A binary add-on with an explicit <path> must download from that path
    (the platform-suffixed datadir), not the conventional '<id>/<id>-<ver>.zip'."""
    idx = boot.mod._load_index("https://official", "osx-arm64")
    indexes = [("https://official", idx)]
    closure = dict(boot.mod._resolve_closure(["pvr.iptvsimple"], indexes))
    assert closure["pvr.iptvsimple"].endswith(
        "pvr.iptvsimple+osx-arm64/pvr.iptvsimple-21.11.0.zip"
    )
    # its binary inputstream dependency is pulled the same way
    assert "inputstream.ffmpegdirect" in closure
    assert "+osx-arm64/" in closure["inputstream.ffmpegdirect"]
    # the kodi.binary.* system import is NOT downloaded
    assert not any(k.startswith("kodi.") for k in closure)


def test_self_uninstall_removes_own_dir(boot):
    """_self_uninstall() must delete its own add-on directory (the supported
    Omega uninstall path: delete dir, then the restart de-registers it)."""
    my_dir = boot.addons / "script.tony7bones.bootstrap"
    my_dir.mkdir()
    (my_dir / "addon.xml").write_text('<addon id="script.tony7bones.bootstrap"/>')
    assert my_dir.exists()
    boot.mod._self_uninstall()
    assert not my_dir.exists(), "self-uninstall must remove its own add-on dir"


def test_self_uninstall_only_touches_own_dir(boot):
    """It must delete ONLY its own dir, never a sibling add-on."""
    mine = boot.addons / "script.tony7bones.bootstrap"
    other = boot.addons / "script.realdebrid"
    mine.mkdir()
    other.mkdir()
    (other / "addon.xml").write_text('<addon id="script.realdebrid"/>')
    boot.mod._self_uninstall()
    assert not mine.exists()
    assert other.exists(), "must not delete other add-ons"


def test_self_uninstall_never_raises(boot, monkeypatch):
    """A failure during self-uninstall must be swallowed (it runs last and must
    not abort the run)."""
    import shutil as _shutil

    def boom(*a, **k):
        raise OSError("permission denied")

    monkeypatch.setattr(_shutil, "rmtree", boom)
    mine = boot.addons / "script.tony7bones.bootstrap"
    mine.mkdir()
    boot.mod._self_uninstall()  # must not raise


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
    restart_pos = src.rfind("_restart_kodi()")
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
