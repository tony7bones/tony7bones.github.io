"""Shared pytest fixtures for the Tony.7.Bones test suite.

The keystone asset here is the ``boot`` fixture: a self-contained fake Kodi
runtime (``xbmc`` / ``xbmcgui`` / ``xbmcvfs`` / ``xbmcaddon``) used to import the
``script.tony7bones.bootstrap`` ``default.py`` under mocked Kodi modules and drive
its install flow without a real Kodi. It was extracted verbatim from
``test_bootstrap.py`` so future modular setup test files can reuse the exact same
fake Kodi (its JSON-RPC enable/extract state machine, the urlopen fake that builds
real zips, ``special://`` path translation, and the Android ``mkdirs`` mimicry that
refuses ``/storage`` paths). Keep its behaviour identical to that original.
"""

from __future__ import annotations

import gzip as _gzip
import importlib.util
import io
import json as _json
import os
import sys
import types
import urllib.request
import zipfile as _zipfile
from pathlib import Path

import pytest

HERE = Path(__file__).parent
REPO_ROOT = HERE.parent
ADDON_DIR = REPO_ROOT / "addons" / "script.tony7bones.bootstrap"
DEFAULT_PY = ADDON_DIR / "default.py"


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
            # On-screen-keyboard autocomplete — a pure-python QoL UTILITY add-on in
            # the official repo, installed by the Foundation layer. Listed so a bare
            # full run genuinely resolves + installs it (the net-set growth is real,
            # not asserted-only).
            "script.module.autocompletion": ("2.1.1", [], None),
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
    xbmc.LOGWARNING = 2
    xbmc.log = lambda *a, **k: None
    xbmc.sleep = lambda ms: None
    # Active skin — default to Estuary so _trim_home_menu() is exercised. Tests
    # that need another skin monkeypatch this.
    xbmc.getSkinDir = lambda: "skin.estuary"
    # activate_skin polls this for the "Keep this skin?" dialog; default False so
    # it falls through quickly (the JSON-RPC skin-set still happens regardless).
    xbmc.getCondVisibility = lambda cond: state.get("condvis", False)

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
            # Optional scripted answers (Phase 5d, e.g. the Guided wizard's
            # "Remove Setup?" confirm): a test may queue answers in
            # state["yesno_queue"]; they are consumed FIRST, in order. Tests
            # that never set the queue see the original behaviour unchanged.
            queue = state.get("yesno_queue")
            if queue:
                return bool(queue.pop(0))
            if msg.startswith("Include video"):
                return bool(state.get("also_video", False))
            return False

        def multiselect(self, title, options, preselect=None):
            state.setdefault("multiselect", []).append((title, options, preselect))
            # state['video_pick']: None = cancel, [] = nothing, else indexes.
            pick = state.get("video_pick", preselect)
            return None if pick is None else list(pick)

        def select(self, title, options):
            # Kodi's list-picker (Phase 5d: the Guided wizard menu). Every call
            # is recorded; the pick comes from state["select_queue"] (a list of
            # indexes, consumed in order) so a test can script a multi-step
            # wizard walk. Default with no queue = -1 (back/cancel), so an
            # unscripted test can never accidentally run a gate.
            state.setdefault("select", []).append((title, list(options)))
            queue = state.get("select_queue")
            if queue:
                return queue.pop(0)
            return -1

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
            .replace("special://userdata/", str(profile) + "/")
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
                b'<addon id="script.tony7bones.modv2plus" version="1.0.0"/>'
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
    _LIB = REPO_ROOT / "addons" / "script.module.tony7bones" / "lib"
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
