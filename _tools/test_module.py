"""Coverage for the shared install library (script.module.tony7bones).

This is the machinery extracted out of the two Setup add-ons in the Option-B
refactor: HTTP fetch, addons.xml index load/parse/merge, the two closure
resolvers (ordered, for the base Setup; combined-with-origins, for the video
Setup), zip extract, enable/disable, repo discovery, origin stamping,
source-repo enabling, platform detection, self-uninstall and restart.

The package is imported under mocked Kodi modules (xbmc/xbmcaddon/xbmcgui/
xbmcvfs) exactly as Kodi would expose it via the xbmc.python.module extension,
and each behaviour the Setups depend on is exercised directly so a regression in
the shared layer is caught here regardless of which Setup uses it.
"""

from __future__ import annotations

import gzip as _gzip
import importlib
import io
import json as _json
import sys
import types
import urllib.request
import zipfile as _zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest

HERE = Path(__file__).parent
REPO_ROOT = HERE.parent
MODULE_DIR = REPO_ROOT / "repo" / "script.module.tony7bones"
LIB = MODULE_DIR / "lib"
ADDON_XML = MODULE_DIR / "addon.xml"


def _addon_root():
    return ET.parse(ADDON_XML).getroot()


class _FakeResp:
    def __init__(self, data):
        self._data = data

    def read(self):
        return self._data

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


# --------------------------------------------------------------------------- #
# Manifest — the module is a library add-on, invisible on the home screen
# --------------------------------------------------------------------------- #
def test_module_id_and_version():
    root = _addon_root()
    assert root.get("id") == "script.module.tony7bones"
    assert root.get("version") == "1.0.0"
    assert root.get("provider-name") == "tony7bones"


def test_module_is_a_python_library_not_executable():
    """A xbmc.python.module add-on with NO script entry and NO <provides>
    executable — so it never shows on the home screen."""
    root = _addon_root()
    mod_ext = root.find("extension[@point='xbmc.python.module']")
    assert mod_ext is not None, "must be a python module add-on"
    assert mod_ext.get("library") == "lib"
    # Must NOT be runnable: no script extension, no executable provides.
    assert root.find("extension[@point='xbmc.python.script']") is None
    assert not root.findall(".//provides")


def test_module_license_is_gpl():
    lic = _addon_root().find("extension[@point='xbmc.addon.metadata']/license")
    assert lic is not None and lic.text == "GPL-2.0-or-later"


def test_module_in_repo_addons_xml():
    """The generator must list the module in repo/addons.xml so Kodi can resolve
    it as a dependency when a Setup is installed from the Tony.7.Bones repo."""
    addons = (REPO_ROOT / "repo" / "addons.xml").read_text()
    assert 'id="script.module.tony7bones"' in addons


def test_module_zip_built():
    zips = list(MODULE_DIR.glob("script.module.tony7bones-*.zip"))
    assert zips, "generator must have built the module zip"


def test_manifest_lists_the_module():
    """The proxy manifest (resources/repository.json) must carry an entry for the
    module, mirroring the script.tony7bones.bootstrap entry, so Kodi auto-installs
    it as a dependency from the repo."""
    manifest = _json.loads(
        (
            REPO_ROOT
            / "repo"
            / "repository.tony7bones"
            / "resources"
            / "repository.json"
        ).read_text()
    )
    by_id = {e["id"]: e for e in manifest}
    assert "script.module.tony7bones" in by_id
    entry = by_id["script.module.tony7bones"]
    ref = by_id["script.tony7bones.bootstrap"]
    # Mirror the bootstrap entry's shape (same host/branch/url template). The
    # branch is a deployment detail — assert the two entries agree rather than
    # hard-coding a value.
    assert entry["username"] == ref["username"]
    assert entry["repository"] == ref["repository"]
    assert entry["branch"] == ref["branch"]
    assert "{id}-{version}.zip" in entry["assets"]["zip"]


# --------------------------------------------------------------------------- #
# Runtime fixture — import the library under mocked Kodi modules
# --------------------------------------------------------------------------- #
@pytest.fixture
def lib(tmp_path, monkeypatch):
    state = {
        "installed": set(),
        "extracted": set(),
        "disabled": set(),
        "builtins": [],
        "jsonrpc": [],
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

    class _Dialog:
        def yesno(self, *a, **k):
            return False

    xbmcgui.Dialog = _Dialog
    xbmcgui.DLG_YESNO_NO_BTN = 1

    xbmcvfs = types.ModuleType("xbmcvfs")
    temp = tmp_path / "temp"
    addons = tmp_path / "addons"
    database = tmp_path / "database"
    temp.mkdir()
    addons.mkdir()
    database.mkdir()

    def _translate(p):
        return (
            p.replace("special://temp/", str(temp) + "/")
            .replace("special://home/addons/", str(addons) + "/")
            .replace("special://database/", str(database) + "/")
        )

    xbmcvfs.translatePath = _translate

    for nm, mod in (
        ("xbmc", xbmc),
        ("xbmcaddon", xbmcaddon),
        ("xbmcgui", xbmcgui),
        ("xbmcvfs", xbmcvfs),
    ):
        monkeypatch.setitem(sys.modules, nm, mod)

    # Put lib/ on path and purge any cached copy so it binds to THESE mocks.
    monkeypatch.syspath_prepend(str(LIB))
    for name in list(sys.modules):
        if name == "tony7bones" or name.startswith("tony7bones."):
            monkeypatch.delitem(sys.modules, name, raising=False)
    t7 = importlib.import_module("tony7bones")

    return types.SimpleNamespace(
        t7=t7, state=state, addons=addons, database=database, tmp_path=tmp_path
    )


# --------------------------------------------------------------------------- #
# Public API surface
# --------------------------------------------------------------------------- #
def test_public_api_surface(lib):
    t7 = lib.t7
    for name in (
        "is_installed",
        "http_get",
        "extract_zip",
        "update_local_addons",
        "enable",
        "disable",
        "platform_tag",
        "is_android",
        "self_uninstall",
        "restart_kodi",
        "load_index_simple",
        "resolve_closure_ordered",
        "parse_index",
        "load_repo_index",
        "ver_key",
        "merge_index",
        "build_index",
        "resolve_closure_combined",
        "repo_dirs",
        "have_source_repos",
        "enable_source_repos",
        "set_origins",
        "install_with_deps",
        "install_closure",
        "disable_after_install",
    ):
        assert hasattr(t7, name), f"missing public API: {name}"


def test_platform_tag_shape(lib):
    tag = lib.t7.platform_tag()
    assert tag is None or "-" in tag


# --------------------------------------------------------------------------- #
# HTTP + zip extract + enable/disable
# --------------------------------------------------------------------------- #
def test_http_get_gunzips(lib, monkeypatch):
    payload = b"<addons></addons>"

    def _open(req, timeout=None):
        url = req.full_url if hasattr(req, "full_url") else req
        return _FakeResp(_gzip.compress(payload) if url.endswith(".gz") else payload)

    monkeypatch.setattr(urllib.request, "urlopen", _open)
    assert lib.t7.http_get("https://x/addons.xml.gz") == payload
    assert lib.t7.http_get("https://x/addons.xml") == payload


def _zip_url_opener(state):
    def _open(req, timeout=None):
        url = req.full_url if hasattr(req, "full_url") else req
        if url.endswith(".zip"):
            aid = url.rsplit("/", 1)[-1].rsplit("-", 1)[0]
            state["extracted"].add(aid)
            buf = io.BytesIO()
            with _zipfile.ZipFile(buf, "w") as z:
                z.writestr(f"{aid}/addon.xml", f'<addon id="{aid}"/>')
            return _FakeResp(buf.getvalue())
        return _FakeResp(b"")

    return _open


def test_extract_zip_success(lib, monkeypatch):
    monkeypatch.setattr(urllib.request, "urlopen", _zip_url_opener(lib.state))
    ok = lib.t7.extract_zip(
        "https://x/repository.foo-1.0.zip", None, 50, lambda *a, **k: None
    )
    assert ok
    assert (lib.addons / "repository.foo" / "addon.xml").exists()


def test_extract_zip_failure_is_swallowed(lib, monkeypatch):
    def _boom(req, timeout=None):
        raise OSError("network down")

    monkeypatch.setattr(urllib.request, "urlopen", _boom)
    assert (
        lib.t7.extract_zip("https://x/y.zip", None, 50, lambda *a, **k: None) is False
    )


def test_enable_disable_jsonrpc(lib):
    lib.state["extracted"].add("plugin.video.x")
    lib.t7.enable("plugin.video.x")
    assert "plugin.video.x" in lib.state["installed"]
    lib.t7.disable("plugin.video.x")
    assert "plugin.video.x" in lib.state["disabled"]


# --------------------------------------------------------------------------- #
# Simple (base-Setup) index + ordered resolver
# --------------------------------------------------------------------------- #
def _simple_index_opener(index, state=None):
    def _open(req, timeout=None):
        url = req.full_url if hasattr(req, "full_url") else req
        if url.endswith("addons.xml") or url.endswith("addons.xml.gz"):
            parts = ['<?xml version="1.0"?>', "<addons>"]
            for aid, (ver, deps, path) in index.items():
                parts.append(f'<addon id="{aid}" version="{ver}"><requires>')
                for d in deps:
                    parts.append(f'<import addon="{d}" version="1.0.0"/>')
                parts.append("</requires>")
                parts.append('<extension point="xbmc.addon.metadata">')
                if path:
                    parts.append(f"<path>{path}</path>")
                parts.append("</extension></addon>")
            parts.append("</addons>")
            data = "".join(parts).encode()
            return _FakeResp(_gzip.compress(data) if url.endswith(".gz") else data)
        if url.endswith(".zip"):
            aid = url.rsplit("/", 1)[-1].rsplit("-", 1)[0]
            if state is not None:
                state["extracted"].add(aid)
            buf = io.BytesIO()
            with _zipfile.ZipFile(buf, "w") as z:
                z.writestr(f"{aid}/addon.xml", f'<addon id="{aid}"/>')
            return _FakeResp(buf.getvalue())
        return _FakeResp(b"")

    return _open


_SIMPLE_INDEX = {
    "script.ezmaintenanceplus": ("2026.04.05.0", ["script.module.requests"], None),
    "script.module.requests": (
        "2.31.0",
        ["script.module.urllib3", "xbmc.python"],
        None,
    ),
    "script.module.urllib3": ("2.2.3", [], None),
    "pvr.iptvsimple": (
        "21.11.0",
        ["inputstream.ffmpegdirect", "kodi.binary.instance.pvr"],
        "pvr.iptvsimple+osx-arm64/pvr.iptvsimple-21.11.0.zip",
    ),
    "inputstream.ffmpegdirect": (
        "21.3.8",
        [],
        "inputstream.ffmpegdirect+osx-arm64/inputstream.ffmpegdirect-21.3.8.zip",
    ),
}


def test_load_index_simple_skips_optional_imports(lib, monkeypatch):
    xml = (
        b'<?xml version="1.0"?><addons>'
        b'<addon id="plugin.video.the-loop" version="7.9"><requires>'
        b'<import addon="script.module.requests" version="1.0.0"/>'
        b'<import addon="plugin.googledrive" version="1.0.0" optional="true"/>'
        b"</requires></addon></addons>"
    )

    def _open(req, timeout=None):
        url = req.full_url if hasattr(req, "full_url") else req
        return _FakeResp(_gzip.compress(xml) if url.endswith(".gz") else xml)

    monkeypatch.setattr(urllib.request, "urlopen", _open)
    idx = lib.t7.load_index_simple("https://official", None)
    deps = idx["plugin.video.the-loop"][1]
    assert "script.module.requests" in deps
    assert "plugin.googledrive" not in deps, "optional import must be dropped"


def test_resolve_closure_ordered_walks_deps(lib, monkeypatch):
    monkeypatch.setattr(urllib.request, "urlopen", _simple_index_opener(_SIMPLE_INDEX))
    idx = lib.t7.load_index_simple("https://repo", None)
    closure = lib.t7.resolve_closure_ordered(
        ["script.ezmaintenanceplus"], [("https://repo", idx)]
    )
    ids = [aid for aid, _u in closure]
    # deps before dependents; system import (xbmc.python) excluded
    assert ids.index("script.module.urllib3") < ids.index("script.module.requests")
    assert ids.index("script.module.requests") < ids.index("script.ezmaintenanceplus")
    assert "xbmc.python" not in ids


def test_resolve_closure_ordered_binary_path(lib, monkeypatch):
    monkeypatch.setattr(urllib.request, "urlopen", _simple_index_opener(_SIMPLE_INDEX))
    idx = lib.t7.load_index_simple("https://official", "osx-arm64")
    closure = dict(
        lib.t7.resolve_closure_ordered(["pvr.iptvsimple"], [("https://official", idx)])
    )
    # binary add-on resolves to its explicit per-arch <path>, not the conventional url
    assert closure["pvr.iptvsimple"].endswith(
        "pvr.iptvsimple+osx-arm64/pvr.iptvsimple-21.11.0.zip"
    )
    assert "kodi.binary.instance.pvr" not in closure  # system import skipped


def test_resolve_closure_ordered_unresolvable(lib):
    closure = lib.t7.resolve_closure_ordered(["does.not.exist"], [("https://x", {})])
    assert closure == []


def test_load_index_simple_filters_other_arch(lib, monkeypatch):
    xml = (
        b'<?xml version="1.0"?><addons>'
        b'<addon id="pvr.iptvsimple" version="21.11.0"><requires/>'
        b'<extension point="xbmc.addon.metadata"><platform>osx-x86_64</platform>'
        b"<path>pvr.iptvsimple+osx-x86_64/pvr.iptvsimple-21.11.0.zip</path>"
        b"</extension></addon>"
        b'<addon id="weather.multi" version="1.1.0"><requires/>'
        b'<extension point="xbmc.addon.metadata"><platform>all</platform>'
        b"</extension></addon></addons>"
    )

    def _open(req, timeout=None):
        url = req.full_url if hasattr(req, "full_url") else req
        return _FakeResp(_gzip.compress(xml) if url.endswith(".gz") else xml)

    monkeypatch.setattr(urllib.request, "urlopen", _open)
    idx = lib.t7.load_index_simple("https://official", "osx-arm64")
    # the arm64 box must NOT keep the x86_64-only binary entry, but keeps 'all'
    assert "pvr.iptvsimple" not in idx
    assert "weather.multi" in idx


# --------------------------------------------------------------------------- #
# Combined (video-Setup) index + origins + installed-aware resolver
# --------------------------------------------------------------------------- #
def test_ver_key_orders_numerically(lib):
    vk = lib.t7.ver_key
    assert vk("5.1.200") > vk("5.0.38")
    assert vk("5.1.61") > vk("5.1.9")


def test_parse_index_carries_origin_and_skips_optional(lib):
    xml = (
        b'<?xml version="1.0"?><addons>'
        b'<addon id="plugin.video.the-loop" version="7.9"><requires>'
        b'<import addon="script.module.requests" version="1.0.0"/>'
        b'<import addon="plugin.googledrive" version="1.0.0" optional="true"/>'
        b"</requires></addon></addons>"
    )
    idx = lib.t7.parse_index(xml, "https://base", None, "repository.loop")
    ver, deps, url, origin = idx["plugin.video.the-loop"]
    assert origin == "repository.loop"
    assert url == "https://base/plugin.video.the-loop/plugin.video.the-loop-7.9.zip"
    assert "plugin.googledrive" not in deps


def test_merge_index_official_preferred_and_newest_wins(lib):
    combined = {}
    # third-party A has resolveurl 5.0.09, third-party B has 5.1.200 -> B wins
    lib.t7.merge_index(
        combined,
        {"script.module.resolveurl": ("5.0.09", [], "urlA", "repoA")},
        prefer=False,
    )
    lib.t7.merge_index(
        combined,
        {"script.module.resolveurl": ("5.1.200", [], "urlB", "repoB")},
        prefer=False,
    )
    assert combined["script.module.resolveurl"][0] == "5.1.200"
    # official (prefer=True) overrides even a higher third-party version
    lib.t7.merge_index(
        combined,
        {"script.module.resolveurl": ("5.0.00", [], "urlOff", "repository.xbmc.org")},
        prefer=True,
    )
    assert combined["script.module.resolveurl"][3] == "repository.xbmc.org"


_COMBINED_INDEX = {
    "plugin.video.the-loop": (
        "7.9",
        ["script.module.requests", "plugin.video.dailymotion_com"],
        "https://repo/plugin.video.the-loop-7.9.zip",
        "repository.loop",
    ),
    "script.module.requests": (
        "2.31.0",
        [],
        "https://repo/script.module.requests-2.31.0.zip",
        "repository.loop",
    ),
    "plugin.video.dailymotion_com": (
        "1.0",
        [],
        "https://repo/plugin.video.dailymotion_com-1.0.zip",
        "repository.loop",
    ),
}


def test_resolve_closure_combined_installs_dailymotion_for_loop(lib):
    closure, missing = lib.t7.resolve_closure_combined(
        ["plugin.video.the-loop"], _COMBINED_INDEX
    )
    ids = [aid for aid, _u, _o in closure]
    assert "plugin.video.dailymotion_com" in ids, (
        "Dailymotion is a REQUIRED import — must be installed (then disabled later)"
    )
    assert not missing


def test_resolve_closure_combined_reports_missing(lib):
    closure, missing = lib.t7.resolve_closure_combined(["nope"], {})
    assert closure == []
    assert "nope" in missing


def test_resolve_closure_combined_skips_installed(lib):
    lib.state["installed"].add("script.module.requests")
    closure, _missing = lib.t7.resolve_closure_combined(
        ["plugin.video.the-loop"], _COMBINED_INDEX
    )
    ids = [aid for aid, _u, _o in closure]
    assert "script.module.requests" not in ids, "already-installed dep is skipped"


# --------------------------------------------------------------------------- #
# repo discovery / source-repo enabling / origins
# --------------------------------------------------------------------------- #
def _write_repo(addons, repo_id, info_url, *, minver=None, maxver=None):
    d = addons / repo_id
    d.mkdir()
    attrs = ""
    if minver:
        attrs += f' minversion="{minver}"'
    if maxver:
        attrs += f' maxversion="{maxver}"'
    (d / "addon.xml").write_text(
        f'<?xml version="1.0"?><addon id="{repo_id}" version="1.0.0">'
        f'<extension point="xbmc.addon.repository"><dir{attrs}>'
        f"<info>{info_url}</info>"
        f"<datadir>{info_url.rsplit('/', 1)[0]}/</datadir>"
        f"</dir></extension></addon>"
    )


def test_repo_dirs_discovers_filters_and_skips_proxy(lib):
    _write_repo(lib.addons, "repository.fake", "https://fake/zips/addons.xml")
    _write_repo(
        lib.addons,
        "repository.old",
        "https://old/zips/addons.xml",
        minver="19.0.0",
        maxver="20.89.0",
    )
    _write_repo(
        lib.addons, "repository.tony7bones", "http://127.0.0.1:61234/addons.xml"
    )
    triples = lib.t7.repo_dirs(lambda *a, **k: None)
    infos = [i for _r, i, _b in triples]
    assert "https://fake/zips/addons.xml" in infos
    assert "https://old/zips/addons.xml" not in infos, (
        "Nexus-gated dir must be filtered"
    )
    assert not any("127.0.0.1" in i for i in infos), "host proxy must be skipped"


def test_have_source_repos(lib):
    assert lib.t7.have_source_repos(lambda *a, **k: None) is False
    _write_repo(lib.addons, "repository.fake", "https://fake/zips/addons.xml")
    assert lib.t7.have_source_repos(lambda *a, **k: None) is True


def test_enable_source_repos_enables_real_repos_not_proxy(lib):
    _write_repo(lib.addons, "repository.fake", "https://fake/zips/addons.xml")
    _write_repo(
        lib.addons, "repository.tony7bones", "http://127.0.0.1:61234/addons.xml"
    )
    # mark them extracted so enable -> installed in the mock
    lib.state["extracted"].update({"repository.fake", "repository.tony7bones"})
    lib.t7.enable_source_repos(lambda *a, **k: None)
    assert "repository.fake" in lib.state["installed"]
    assert "repository.tony7bones" not in lib.state["installed"], "proxy not enabled"


def _make_addons_db(database):
    import sqlite3

    db = database / "Addons33.db"
    con = sqlite3.connect(str(db))
    con.execute("CREATE TABLE installed (addonID TEXT, origin TEXT, enabled INT)")
    con.execute("INSERT INTO installed VALUES ('plugin.video.pov','',1)")
    con.execute("INSERT INTO installed VALUES ('plugin.video.x','repository.keep',1)")
    con.commit()
    con.close()
    return db


def test_set_origins_stamps_only_blank_rows(lib):
    db = _make_addons_db(lib.database)
    lib.t7.set_origins(
        {
            "plugin.video.pov": "repository.kodifitzwell",
            "plugin.video.x": "repository.other",  # already has origin -> untouched
        },
        lambda *a, **k: None,
    )
    import sqlite3

    con = sqlite3.connect(str(db))
    rows = dict(con.execute("SELECT addonID, origin FROM installed").fetchall())
    con.close()
    assert rows["plugin.video.pov"] == "repository.kodifitzwell"
    assert rows["plugin.video.x"] == "repository.keep", "non-blank origin preserved"


def test_set_origins_never_raises_without_db(lib):
    # no Addons*.db present -> logs and returns, never raises
    lib.t7.set_origins({"a": "b"}, lambda *a, **k: None)


# --------------------------------------------------------------------------- #
# install orchestration
# --------------------------------------------------------------------------- #
def test_install_with_deps_extracts_and_enables(lib, monkeypatch):
    monkeypatch.setattr(
        urllib.request, "urlopen", _simple_index_opener(_SIMPLE_INDEX, lib.state)
    )
    ok = lib.t7.install_with_deps(
        "script.ezmaintenanceplus",
        None,
        ["https://repo"],
        "https://official",
        lambda *a, **k: None,
    )
    assert ok
    assert "script.ezmaintenanceplus" in lib.state["installed"]
    assert "script.module.requests" in lib.state["installed"]


def test_install_with_deps_skips_already_installed(lib):
    lib.state["installed"].add("script.realdebrid")
    assert lib.t7.install_with_deps(
        "script.realdebrid", None, ["https://repo"], "https://official", lambda *a: None
    )


def test_install_with_deps_reports_failure_when_unresolvable(lib, monkeypatch):
    monkeypatch.setattr(urllib.request, "urlopen", _simple_index_opener({}))
    assert (
        lib.t7.install_with_deps(
            "does.not.exist",
            None,
            ["https://repo"],
            "https://official",
            lambda *a: None,
        )
        is False
    )


def _combined_zip_opener(state, index):
    """urlopen that serves the combined index from each repo dir AND zips."""

    def _open(req, timeout=None):
        url = req.full_url if hasattr(req, "full_url") else req
        if "addons.xml" in url:
            parts = ['<?xml version="1.0"?>', "<addons>"]
            for aid, (ver, deps, _u, _o) in index.items():
                parts.append(f'<addon id="{aid}" version="{ver}"><requires>')
                for d in deps:
                    parts.append(f'<import addon="{d}" version="1.0.0"/>')
                parts.append("</requires></addon>")
            parts.append("</addons>")
            data = "".join(parts).encode()
            return _FakeResp(_gzip.compress(data) if url.endswith(".gz") else data)
        if url.endswith(".zip"):
            aid = url.rsplit("/", 1)[-1].rsplit("-", 1)[0]
            state["extracted"].add(aid)
            buf = io.BytesIO()
            with _zipfile.ZipFile(buf, "w") as z:
                z.writestr(f"{aid}/addon.xml", f'<addon id="{aid}"/>')
            return _FakeResp(buf.getvalue())
        return _FakeResp(b"")

    return _open


def test_install_closure_stamps_origins_and_disables_dailymotion(lib, monkeypatch):
    monkeypatch.setattr(
        urllib.request, "urlopen", _combined_zip_opener(lib.state, _COMBINED_INDEX)
    )
    _make_addons_db(lib.database)
    closure, _missing = lib.t7.resolve_closure_combined(
        ["plugin.video.the-loop"], _COMBINED_INDEX
    )
    lib.t7.install_closure(
        closure, None, {"plugin.video.dailymotion_com"}, lambda *a, **k: None
    )
    # everything installed; Dailymotion installed-but-disabled
    assert "plugin.video.the-loop" in lib.state["installed"]
    assert "plugin.video.dailymotion_com" in lib.state["installed"]
    assert "plugin.video.dailymotion_com" in lib.state["disabled"]
    assert "plugin.video.the-loop" not in lib.state["disabled"]


def test_install_closure_no_disable_without_dailymotion(lib, monkeypatch):
    idx = {
        "plugin.video.pov": (
            "6.0",
            [],
            "https://repo/plugin.video.pov-6.0.zip",
            "repository.kodifitzwell",
        )
    }
    monkeypatch.setattr(urllib.request, "urlopen", _combined_zip_opener(lib.state, idx))
    closure, _m = lib.t7.resolve_closure_combined(["plugin.video.pov"], idx)
    lib.t7.install_closure(
        closure, None, {"plugin.video.dailymotion_com"}, lambda *a, **k: None
    )
    assert lib.state["disabled"] == set(), "nothing to disable when no Dailymotion"


def test_disable_after_install_only_present_ids(lib):
    lib.state["installed"].add("plugin.video.dailymotion_com")
    lib.t7.disable_after_install(
        {"plugin.video.dailymotion_com"},
        {"plugin.video.dailymotion_com", "plugin.video.absent"},
        lambda *a, **k: None,
    )
    assert "plugin.video.dailymotion_com" in lib.state["disabled"]
    assert "plugin.video.absent" not in lib.state["disabled"]


# --------------------------------------------------------------------------- #
# self-uninstall guard
# --------------------------------------------------------------------------- #
def test_self_uninstall_removes_own_dir(lib):
    (lib.addons / "script.tony7bones.video").mkdir()
    lib.t7.self_uninstall("script.tony7bones.video", lambda *a, **k: None)
    assert not (lib.addons / "script.tony7bones.video").exists()


def test_self_uninstall_only_touches_own_dir(lib):
    (lib.addons / "script.tony7bones.video").mkdir()
    (lib.addons / "plugin.video.pov").mkdir()
    lib.t7.self_uninstall("script.tony7bones.video", lambda *a, **k: None)
    assert (lib.addons / "plugin.video.pov").exists(), "must not touch other add-ons"


def test_self_uninstall_never_raises(lib, monkeypatch):
    import tony7bones.system as sysmod

    monkeypatch.setattr(
        sysmod.xbmcvfs, "translatePath", lambda p: (_ for _ in ()).throw(OSError("x"))
    )
    lib.t7.self_uninstall("script.tony7bones.video", lambda *a, **k: None)
