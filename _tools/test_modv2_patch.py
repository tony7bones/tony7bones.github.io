"""Coverage for the Estuary MOD V2 Patch add-on (script.tony7bones.modv2.patch).

Two layers, mirroring test_video.py / test_bootstrap.py:

* Static contract — the manifest is well-formed (id / name / version), the
  script compiles, Font.xml is in the FILES copy list, and the shipped
  resources/xml/Font.xml has a neutralized Economica fontset (no Economica-*.ttf
  body filenames) while the other fontsets keep their original .ttf references.
* Runtime behaviour — default.py is imported under mocked Kodi modules (run() is
  __main__-guarded, so import is side-effect-free, but the module top-level does
  build an xbmcaddon.Addon(), so the mocks must satisfy that) and the font flow
  is exercised: on a fake MOD V2 skin, run() forces lookandfeel.font=Default via
  the JSON-RPC path and copies every file in FILES (including Font.xml).
"""

from __future__ import annotations

import ast
import importlib.util
import json as _json
import py_compile
import sys
import types
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest

HERE = Path(__file__).parent
REPO_ROOT = HERE.parent
ADDON_DIR = REPO_ROOT / "repo" / "script.tony7bones.modv2.patch"
ADDON_XML = ADDON_DIR / "addon.xml"
DEFAULT_PY = ADDON_DIR / "default.py"
FONT_XML = ADDON_DIR / "resources" / "xml" / "Font.xml"


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
    assert _addon_root().get("id") == "script.tony7bones.modv2.patch"


def test_addon_name():
    assert _addon_root().get("name") == "Estuary MOD V2 Patch"


def test_addon_version_bumped():
    sys.path.insert(0, str(HERE))
    import release_lib as rl  # noqa: PLC0415

    v = _addon_root().get("version")
    assert rl.is_greater(v, "1.0.4"), f"version {v} must exceed the prior 1.0.4"


def test_has_news():
    news = _addon_root().find("extension[@point='xbmc.addon.metadata']/news")
    assert news is not None and news.text and news.text.strip()


def test_default_py_compiles():
    py_compile.compile(str(DEFAULT_PY), doraise=True)


# --------------------------------------------------------------------------- #
# Static contract — Font.xml shipped + neutralized
# --------------------------------------------------------------------------- #
def test_font_xml_is_in_files():
    files = _assign("FILES")
    assert "Font.xml" in files, "Font.xml must be in the FILES copy list"


def test_font_xml_resource_exists():
    assert FONT_XML.exists(), "must ship resources/xml/Font.xml"


def _economica_block(text):
    """Return the substring of Font.xml spanning the Economica fontset block."""
    start = text.find('<fontset id="Economica"')
    assert start != -1, "Economica fontset not found"
    end = text.find("</fontset>", start)
    assert end != -1, "Economica fontset close not found"
    return text[start:end]


def test_economica_fontset_has_no_economica_ttf():
    """The neutralized Economica fontset must reference zero Economica-*.ttf
    body filenames — they were swapped to NotoSans-*.ttf."""
    text = FONT_XML.read_text(encoding="utf-8")
    block = _economica_block(text)
    # parse so we assert against real <filename> bodies, not e.g. the id/name
    frag = ET.fromstring(
        text[
            text.find('<fontset id="Economica"') : text.find(
                "</fontset>", text.find('<fontset id="Economica"')
            )
            + len("</fontset>")
        ]
    )
    filenames = [el.text for el in frag.iter("filename")]
    assert filenames, "Economica fontset should still contain <filename> entries"
    offenders = [
        f for f in filenames if f and f.startswith("Economica-") and f.endswith(".ttf")
    ]
    assert not offenders, (
        f"Economica-*.ttf still present in Economica block: {offenders}"
    )
    # and it now points at the stock Noto Sans faces
    assert "NotoSans-Regular.ttf" in block
    assert "NotoSans-Bold.ttf" in block


def test_other_fontsets_keep_their_fonts():
    """The Default fontset is left untouched (still Noto Sans) and the
    Economica fontset is the ONLY one that changed — confirm Default/Arial
    fontsets are still present with intact ttf references."""
    text = FONT_XML.read_text(encoding="utf-8")
    for fid in ("Default", "Arial", "Arial Unicode MS", "Economica"):
        assert f'<fontset id="{fid}"' in text, f"fontset {fid} must remain present"
    # Default fontset still uses NotoSans (unchanged from upstream)
    default_start = text.find('<fontset id="Default"')
    default_end = text.find("</fontset>", default_start)
    default_block = text[default_start:default_end]
    assert "NotoSans-Regular.ttf" in default_block


# --------------------------------------------------------------------------- #
# Runtime behaviour — mocked Kodi
# --------------------------------------------------------------------------- #
@pytest.fixture
def patch_env(tmp_path, monkeypatch):
    """Import the patch default.py under mocked xbmc* with a fake MOD V2 skin
    laid down on disk so run() proceeds past the skin/dir checks."""
    state = {
        "jsonrpc": [],
        "builtins": [],
        "ok": [],
        "log": [],
        "skin": "skin.estuary.modv2",
    }

    home = tmp_path / "home"
    addon_path = home / "addons" / "script.tony7bones.modv2.patch"
    skin_xml = home / "addons" / "skin.estuary.modv2" / "xml"
    skin_xml.mkdir(parents=True)
    (addon_path / "resources" / "xml").mkdir(parents=True)
    # the patch copies from ADDON_PATH/resources/xml/<f> -> seed the real files
    for fname in _assign("FILES"):
        src = ADDON_DIR / "resources" / "xml" / fname
        (addon_path / "resources" / "xml" / fname).write_bytes(src.read_bytes())

    xbmc = types.ModuleType("xbmc")
    xbmc.LOGERROR = 4
    xbmc.LOGINFO = 1
    xbmc.LOGWARNING = 3
    xbmc.log = lambda msg, level=1: state["log"].append((level, msg))
    xbmc.getSkinDir = lambda: state["skin"]

    def _builtin(cmd, wait=False):
        state["builtins"].append(cmd)

    xbmc.executebuiltin = _builtin

    def _jsonrpc(s):
        state["jsonrpc"].append(s)
        d = _json.loads(s)
        if d.get("method") == "Settings.SetSettingValue":
            return _json.dumps({"jsonrpc": "2.0", "id": d.get("id"), "result": True})
        return "{}"

    xbmc.executeJSONRPC = _jsonrpc

    xbmcaddon = types.ModuleType("xbmcaddon")

    class _Addon:
        def getAddonInfo(self, key):
            return str(addon_path) if key == "path" else ""

    xbmcaddon.Addon = lambda *a, **k: _Addon()

    xbmcgui = types.ModuleType("xbmcgui")

    class _Dialog:
        def ok(self, title, msg):
            state["ok"].append((title, msg))

    xbmcgui.Dialog = _Dialog

    xbmcvfs = types.ModuleType("xbmcvfs")

    def _translate(p):
        return p.replace("special://home/", str(home) + "/")

    xbmcvfs.translatePath = _translate

    for nm, mod in (
        ("xbmc", xbmc),
        ("xbmcaddon", xbmcaddon),
        ("xbmcgui", xbmcgui),
        ("xbmcvfs", xbmcvfs),
    ):
        monkeypatch.setitem(sys.modules, nm, mod)

    spec = importlib.util.spec_from_file_location("modv2_patch_default", DEFAULT_PY)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    # default.py calls run() at import time (no __main__ guard), which fires the
    # font/copy/reload flow once under the default (correct) mock skin. Wipe the
    # recorded effects + any copied file so each test starts from a clean slate.
    for key in ("jsonrpc", "builtins", "ok", "log"):
        state[key].clear()
    copied = skin_xml / "Font.xml"
    if copied.exists():
        copied.unlink()
    return types.SimpleNamespace(
        mod=mod, state=state, skin_xml=skin_xml, addon_path=addon_path
    )


def test_run_forces_default_fontset_via_jsonrpc(patch_env):
    patch_env.mod.run()
    calls = [_json.loads(s) for s in patch_env.state["jsonrpc"]]
    setting_calls = [
        c
        for c in calls
        if c.get("method") == "Settings.SetSettingValue"
        and c.get("params", {}).get("setting") == "lookandfeel.font"
    ]
    assert setting_calls, (
        "run() must call Settings.SetSettingValue for lookandfeel.font"
    )
    assert setting_calls[0]["params"]["value"] == "Default"


def test_run_copies_font_xml_into_skin(patch_env):
    patch_env.mod.run()
    dst = patch_env.skin_xml / "Font.xml"
    assert dst.exists(), "Font.xml must be copied into the skin xml dir"
    # the copied file is byte-identical to the shipped neutralized resource
    assert dst.read_bytes() == FONT_XML.read_bytes()


def test_run_reloads_skin(patch_env):
    patch_env.mod.run()
    assert any("ReloadSkin" in b for b in patch_env.state["builtins"])


def test_run_bails_on_wrong_skin(patch_env):
    patch_env.state["skin"] = "skin.estuary"
    patch_env.mod.run()
    # wrong-skin guard: no JSON-RPC font call, no copy
    assert not patch_env.state["jsonrpc"]
    assert not (patch_env.skin_xml / "Font.xml").exists()
    assert patch_env.state["ok"], "should show the Wrong Skin dialog"
