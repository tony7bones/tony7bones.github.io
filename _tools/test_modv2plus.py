"""Coverage for the Estuary MOD V2+ add-on (script.tony7bones.modv2plus).

Two layers, mirroring the other add-on tests:

* Static contract — the manifest is well-formed (id / name / version / news), the
  script compiles, FILES is exactly the shipped XMLs (incl. Variables.xml), the
  loose media logo mapping is present and its source PNG ships. The shipped XMLs
  carry the features: Home.xml gates the system-info overlay (default ON) on
  !Skin.HasSetting(hide_system_info_overlay) AND Control.HasFocus(802) and
  retargets both wordmark textures to the hi-res logo while leaving the MARK
  controls (logo.png / LogoVar) untouched; SkinSettings.xml carries a new
  "Tony.7.Bones MOD V2+" category (list 9000 item id=11) whose panel (grouplist
  1100) holds the single "Enable System Info overlay" radiobutton toggling
  hide_system_info_overlay (default ON), the old toggle is gone from Extras
  (grouplist 500), and the scrollbar navigates into 1100 on HasFocus(11);
  Variables.xml carries the HasFocus(11) help value; Settings.xml lists Skin
  Settings before Media sources.

* Runtime behaviour — default.py is imported under mocked Kodi modules. run() is
  __main__-guarded so importing is side-effect-free, but the module top-level
  builds an xbmcaddon.Addon(), so the mocks satisfy that. The Apply / Restore /
  Cancel routing is exercised: Apply copies the FILES + the media PNG (with a
  one-time .bak for FILES, none for the media), Restore reverts the FILES from
  .bak and DELETES the loose PNG, Cancel does nothing. force_default_fontset must
  no longer exist anywhere in the module.
"""

from __future__ import annotations

import ast
import importlib.util
import sys
import types
import py_compile
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest

HERE = Path(__file__).parent
REPO_ROOT = HERE.parent
ADDON_DIR = REPO_ROOT / "repo" / "script.tony7bones.modv2plus"
ADDON_XML = ADDON_DIR / "addon.xml"
DEFAULT_PY = ADDON_DIR / "default.py"
HOME_XML = ADDON_DIR / "resources" / "xml" / "Home.xml"
SKINSETTINGS_XML = ADDON_DIR / "resources" / "xml" / "SkinSettings.xml"
SETTINGS_XML = ADDON_DIR / "resources" / "xml" / "Settings.xml"
INCLUDES_XML = ADDON_DIR / "resources" / "xml" / "Includes.xml"
VARIABLES_XML = ADDON_DIR / "resources" / "xml" / "Variables.xml"
LOGO_PNG = ADDON_DIR / "resources" / "media" / "extras" / "logo-text-hires.png"
WEATHER_STOCK_DIR = ADDON_DIR / "resources" / "media" / "extras" / "weather-stock"


def test_includes_clock_is_not_bold():
    """The top-right clock must render in the thin Roboto clock font like stock —
    MOD V2's [B]...[/B] bold wrapper around the time is removed, and the control
    still uses font_clock."""
    text = INCLUDES_XML.read_text(encoding="utf-8")
    assert "<label>$INFO[System.Time]</label>" in text, "clock label must be plain"
    assert "[B]$INFO[System.Time][/B]" not in text, (
        "the bold clock wrapper must be gone"
    )
    assert "<font>font_clock</font>" in text, "clock must keep the font_clock font"


def test_includes_weather_icons_point_at_stock_white_set():
    """The top-right weather condition icon must resolve from the stock-white
    extras/weather-stock/ set, not MOD V2's coloured extras/weather/ set. The
    clock de-bold fix must remain in place."""
    text = INCLUDES_XML.read_text(encoding="utf-8")
    assert (
        "$INFO[Weather.FanartCode,special://skin/extras/weather-stock/,.png]" in text
    ), "weather icon must point at the stock-white weather-stock set"
    assert "special://skin/extras/weather/," not in text, (
        "MOD V2's coloured weather/ prefix must be gone"
    )
    # the clock de-bold fix from 1.0.3 stays intact
    assert "<label>$INFO[System.Time]</label>" in text
    assert "[B]$INFO[System.Time][/B]" not in text
    assert "<font>font_clock</font>" in text


def test_weather_stock_icons_ship_and_nonempty():
    """The stock-white weather icon set must ship as loose PNGs and include the
    sunny condition (32.png) plus the na fallback."""
    assert WEATHER_STOCK_DIR.is_dir(), "must ship resources/media/extras/weather-stock/"
    pngs = sorted(p.name for p in WEATHER_STOCK_DIR.glob("*.png"))
    assert pngs, "weather-stock must contain PNG icons"
    assert "32.png" in pngs, "the sunny condition icon (32) must ship"
    assert "na.png" in pngs, "the na fallback icon must ship"
    for p in WEATHER_STOCK_DIR.glob("*.png"):
        assert p.stat().st_size > 0, f"{p.name} must be non-empty"


def test_media_dirs_maps_weather_stock():
    media_dirs = _assign("MEDIA_DIRS")
    matches = [
        (src, dst)
        for (src, dst) in media_dirs
        if dst.replace("\\", "/") == "extras/weather-stock"
        and src.replace("\\", "/") == "resources/media/extras/weather-stock"
    ]
    assert len(matches) == 1, (
        f"expected one weather-stock dir mapping, got {media_dirs}"
    )
    # the dst must be the skin ROOT's extras/ (special://skin/extras/), NOT
    # media/extras/ — Includes.xml uses special://skin/extras/weather-stock/.
    _src, dst = matches[0]
    assert not dst.replace("\\", "/").startswith("media/"), (
        f"weather-stock dst must be skin-root extras/, not media/extras/: {dst}"
    )


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
    assert _addon_root().get("id") == "script.tony7bones.modv2plus"


def test_addon_name():
    assert _addon_root().get("name") == "Estuary MOD V2+"


def test_addon_version_floor_1_1_0():
    parts = tuple(int(p) for p in _addon_root().get("version").split("."))
    assert parts >= (1, 1, 0), "version must be at least 1.1.0"


def test_no_provides_executable():
    """It must NOT declare itself an executable, else it earns a home Programs
    tile (the same trap the old patch avoided)."""
    text = ADDON_XML.read_text()
    assert "<provides>executable</provides>" not in text


def test_has_news():
    news = _addon_root().find("extension[@point='xbmc.addon.metadata']/news")
    assert news is not None and news.text and news.text.strip()


def test_default_py_compiles():
    py_compile.compile(str(DEFAULT_PY), doraise=True)


# --------------------------------------------------------------------------- #
# Static contract — FILES / MEDIA
# --------------------------------------------------------------------------- #
def test_files_is_exactly_the_shipped_xml():
    assert _assign("FILES") == [
        "Home.xml",
        "SkinSettings.xml",
        "Settings.xml",
        "Includes.xml",
        "Variables.xml",
    ]


def test_media_maps_the_loose_logo():
    media = _assign("MEDIA")
    # MEDIA is a list of (src, dst) tuples; the dst lands under media/extras/
    matches = [
        (src, dst)
        for (src, dst) in media
        if dst.replace("\\", "/") == "media/extras/logo-text-hires.png"
        and src.replace("\\", "/") == "resources/media/extras/logo-text-hires.png"
    ]
    assert len(matches) == 1, f"expected exactly one logo media mapping, got {media}"


def test_logo_png_resource_exists():
    assert LOGO_PNG.exists(), "must ship resources/media/extras/logo-text-hires.png"
    assert LOGO_PNG.stat().st_size > 0


def test_force_default_fontset_removed():
    """The font sledgehammer is gone — no reference to it anywhere in default.py."""
    text = DEFAULT_PY.read_text()
    assert "force_default_fontset" not in text
    assert "lookandfeel.font" not in text


# --------------------------------------------------------------------------- #
# Static contract — Home.xml (overlay gate + wordmark + untouched mark)
# --------------------------------------------------------------------------- #
def _group_18000_block(text):
    start = text.find('<control type="group" id="18000">')
    assert start != -1, "group 18000 control not found in Home.xml"
    depth = 0
    i = start
    while i < len(text):
        nxt_open = text.find("<control", i + 1)
        nxt_close = text.find("</control>", i + 1)
        if nxt_close == -1:
            break
        if nxt_open != -1 and nxt_open < nxt_close:
            depth += 1
            i = nxt_open
        else:
            if depth == 0:
                return text[start : nxt_close + len("</control>")]
            depth -= 1
            i = nxt_close
    raise AssertionError("matching </control> for group 18000 not found")


def _group_18000_own_visible(text):
    block = _group_18000_block(text)
    vis_start = block.find("<visible>")
    assert vis_start != -1, "group 18000 must have a <visible> element"
    vis_end = block.find("</visible>", vis_start)
    return block[vis_start + len("<visible>") : vis_end].strip()


def test_home_overlay_gated_on_optout_toggle_and_focus():
    """The system-info overlay is now default ON via an OPT-OUT flag: it shows
    unless hide_system_info_overlay is set, and only on gear focus. The old
    opt-in flag (enable_info_overlay) must be gone."""
    visible = _group_18000_own_visible(HOME_XML.read_text(encoding="utf-8"))
    assert visible != "false", f"group 18000 must not be hard-disabled, got {visible!r}"
    assert "!Skin.HasSetting(hide_system_info_overlay)" in visible, (
        f"overlay must gate (default ON) on the opt-out flag, got {visible!r}"
    )
    assert "enable_info_overlay" not in visible, (
        f"the old opt-in flag must be gone, got {visible!r}"
    )
    assert "Control.HasFocus(802)" in visible, (
        f"overlay must gate on gear focus, got {visible!r}"
    )


def test_home_both_wordmarks_point_at_hires():
    """Both the fallback (icons/logo-text.png) and main ($VAR[LogoTextVar])
    wordmark textures must now be the loose hi-res logo, and neither original
    reference may remain."""
    text = HOME_XML.read_text(encoding="utf-8")
    assert text.count("<texture>extras/logo-text-hires.png</texture>") == 2, (
        "expected exactly two wordmark textures retargeted to the hi-res logo"
    )
    assert "icons/logo-text.png" not in text, "old fallback wordmark must be gone"
    assert "$VAR[LogoTextVar]" not in text, "old main wordmark VAR must be gone"


def test_home_mark_controls_untouched():
    """The MARK (square icon) controls keep their original logo.png / LogoVar
    references with colordiffuse so the mark stays blue."""
    text = HOME_XML.read_text(encoding="utf-8")
    assert 'colordiffuse="$VAR[SkinColorVar]">icons/logo.png' in text
    assert 'colordiffuse="$VAR[LogoColorVar]">$VAR[LogoVar]' in text


def test_home_no_colordiffuse_on_hires_wordmark():
    """The retargeted wordmark must render plain white — no colordiffuse on the
    hi-res texture lines."""
    for line in HOME_XML.read_text(encoding="utf-8").splitlines():
        if "extras/logo-text-hires.png" in line:
            assert "colordiffuse" not in line, f"wordmark must be plain white: {line!r}"


def _wordmark_control_blocks(text):
    """Return each <control type="image"> block that carries the hi-res wordmark
    texture (there are exactly two — the main and the fallback logo groups)."""
    blocks = []
    needle = "extras/logo-text-hires.png"
    pos = 0
    while True:
        hit = text.find(needle, pos)
        if hit == -1:
            break
        start = text.rfind('<control type="image">', 0, hit)
        end = text.find("</control>", hit)
        assert start != -1 and end != -1, "malformed wordmark control block"
        blocks.append(text[start : end + len("</control>")])
        pos = end + 1
    return blocks


def test_home_wordmark_height_balances_with_mark():
    """The wordmark cap-height must be sized to balance the 56px Kodi mark (~0.7x,
    matching stock Estuary), not fill its box at the old 50/36 heights that made
    the text overpower the mark. Both wordmark controls render at height 39."""
    text = HOME_XML.read_text(encoding="utf-8")
    blocks = _wordmark_control_blocks(text)
    assert len(blocks) == 2, f"expected two wordmark controls, found {len(blocks)}"
    for block in blocks:
        assert "<height>39</height>" in block, (
            f"wordmark must be sized to balance the mark (height 39), got: {block!r}"
        )
        # the old, overpowering heights must be gone from the wordmark controls
        assert "<height>50</height>" not in block
        assert "<height>36</height>" not in block
        # aspectratio=keep is preserved so width auto-follows (no distortion)
        assert "<aspectratio>keep</aspectratio>" in block


# --------------------------------------------------------------------------- #
# Static contract — SkinSettings.xml (new Tony.7.Bones MOD V2+ category)
# --------------------------------------------------------------------------- #
def _find_grouplist(root, gid):
    for ctrl in root.iter("control"):
        if ctrl.get("type") == "grouplist" and ctrl.get("id") == gid:
            return ctrl
    raise AssertionError(f"grouplist id={gid} not found in SkinSettings.xml")


def _find_list(root, lid):
    for ctrl in root.iter("control"):
        if ctrl.get("type") == "list" and ctrl.get("id") == lid:
            return ctrl
    raise AssertionError(f"list id={lid} not found in SkinSettings.xml")


def test_skinsettings_old_overlay_toggle_removed_from_extras():
    """The opt-in enable_info_overlay radiobutton must be gone from Extras
    (grouplist 500) — and from the whole file (the new opt-out flag replaces it)."""
    root = ET.parse(SKINSETTINGS_XML).getroot()
    grouplist = _find_grouplist(root, "500")
    stale = [
        ctrl
        for ctrl in grouplist.iter("control")
        if ctrl.get("type") == "radiobutton"
        and ctrl.findtext("onclick") == "Skin.ToggleSetting(enable_info_overlay)"
    ]
    assert not stale, "the old enable_info_overlay toggle must be gone from Extras"
    assert "enable_info_overlay" not in SKINSETTINGS_XML.read_text(encoding="utf-8"), (
        "no enable_info_overlay reference may remain in SkinSettings.xml"
    )


def test_skinsettings_new_category_item_is_last():
    """List 9000 gains item id=11 'Tony.7.Bones MOD V2+' as the LAST item."""
    root = ET.parse(SKINSETTINGS_XML).getroot()
    lst = _find_list(root, "9000")
    content = lst.find("content")
    assert content is not None, "list 9000 must have a <content>"
    items = list(content.findall("item"))
    assert items, "list 9000 must have items"
    last = items[-1]
    assert last.get("id") == "11", (
        f"the new category must be the LAST item, got id={last.get('id')!r}"
    )
    assert last.findtext("label") == "Tony.7.Bones MOD V2+"
    # the height must have been bumped to reveal the 11th row
    assert lst.findtext("height") == "770", (
        "list 9000 height must be bumped to 770 to reveal the 11th row"
    )


def test_skinsettings_new_panel_holds_the_overlay_toggle():
    """The new panel (grouplist 1100) is gated on HasFocus(11) and holds exactly
    one 'Enable System Info overlay' radiobutton that toggles the opt-out flag
    hide_system_info_overlay and is checked (ON) by default."""
    root = ET.parse(SKINSETTINGS_XML).getroot()
    panel = _find_grouplist(root, "1100")
    assert panel.findtext("visible") == "Container(9000).HasFocus(11)", (
        "panel 1100 must be gated on the new category's HasFocus(11)"
    )
    toggles = [
        ctrl
        for ctrl in panel.iter("control")
        if ctrl.get("type") == "radiobutton"
        and ctrl.findtext("onclick") == "Skin.ToggleSetting(hide_system_info_overlay)"
    ]
    assert len(toggles) == 1, (
        f"expected exactly one hide_system_info_overlay toggle in panel 1100, "
        f"found {len(toggles)}"
    )
    ctrl = toggles[0]
    assert ctrl.findtext("label") == "Enable System Info overlay"
    # default ON: opt-out flag -> checked unless the flag is set
    assert ctrl.findtext("selected") == "!Skin.HasSetting(hide_system_info_overlay)"


def test_skinsettings_scrollbar_navigates_into_new_panel():
    """The scrollbar (id=60) must route left/right to panel 1100 on HasFocus(11),
    and show on the new panel (its visible OR-list includes Control.IsVisible(1100))."""
    root = ET.parse(SKINSETTINGS_XML).getroot()
    scrollbar = None
    for ctrl in root.iter("control"):
        if ctrl.get("type") == "scrollbar" and ctrl.get("id") == "60":
            scrollbar = ctrl
            break
    assert scrollbar is not None, "scrollbar id=60 not found"

    onleft = [
        e.text
        for e in scrollbar.findall("onleft")
        if e.get("condition") == "Container(9000).HasFocus(11)"
    ]
    onright = [
        e.text
        for e in scrollbar.findall("onright")
        if e.get("condition") == "Container(9000).HasFocus(11)"
    ]
    assert onleft == ["1100"], (
        f"scrollbar onleft for HasFocus(11) must be 1100: {onleft}"
    )
    assert onright == ["1100"], (
        f"scrollbar onright for HasFocus(11) must be 1100: {onright}"
    )
    assert "Control.IsVisible(1100)" in (scrollbar.findtext("visible") or ""), (
        "scrollbar must be visible on the new panel"
    )


# --------------------------------------------------------------------------- #
# Static contract — Variables.xml (help text for the new category)
# --------------------------------------------------------------------------- #
def test_variables_has_help_for_new_category():
    """Variables.xml ships and SkinSettingsHelpTextVar carries a HasFocus(11)
    value so the new category renders correct (not stale) help."""
    assert VARIABLES_XML.exists(), "Variables.xml must ship"
    root = ET.parse(VARIABLES_XML).getroot()
    var = None
    for v in root.iter("variable"):
        if v.get("name") == "SkinSettingsHelpTextVar":
            var = v
            break
    assert var is not None, "SkinSettingsHelpTextVar not found in Variables.xml"
    values = [
        e.text
        for e in var.findall("value")
        if e.get("condition") == "Container(9000).HasFocus(11)"
    ]
    assert values == ["Tony.7.Bones MOD V2+ settings"], (
        f"help text for the new category must be set, got {values}"
    )


# --------------------------------------------------------------------------- #
# Static contract — Settings.xml (Skin Settings before Media sources)
# --------------------------------------------------------------------------- #
def _settings_panel_items(root):
    for ctrl in root.iter("control"):
        if ctrl.get("type") == "panel" and ctrl.get("id") == "9000":
            content = ctrl.find("content")
            assert content is not None, "panel 9000 must have a <content> block"
            return list(content.findall("item"))
    raise AssertionError("panel id=9000 not found in Settings.xml")


def test_settings_skinsettings_before_media_sources():
    items = _settings_panel_items(ET.parse(SETTINGS_XML).getroot())

    def _index(onclick_text):
        for i, item in enumerate(items):
            if item.findtext("onclick") == onclick_text:
                return i
        raise AssertionError(f"no item with onclick {onclick_text!r}")

    skin_idx = _index("ActivateWindow(SkinSettings)")
    media_idx = _index("ActivateWindow(1120)")
    assert skin_idx < media_idx, (
        f"Skin Settings (idx {skin_idx}) must come before Media sources "
        f"(idx {media_idx})"
    )
    # each kept its own label + icon
    assert items[skin_idx].findtext("label") == "$LOCALIZE[10035]"
    assert items[skin_idx].findtext("icon") == "icons/settings/skin.png"
    assert items[media_idx].findtext("label") == "$LOCALIZE[20094]"
    assert items[media_idx].findtext("icon") == "icons/settings/sources.png"


# --------------------------------------------------------------------------- #
# Runtime behaviour — mocked Kodi
# --------------------------------------------------------------------------- #
@pytest.fixture
def patch_env(tmp_path, monkeypatch):
    """Import default.py under mocked xbmc* with a fake MOD V2 skin laid down on
    disk so run() proceeds past the skin/dir checks."""
    state = {
        "builtins": [],
        "ok": [],
        "log": [],
        "skin": "skin.estuary.modv2",
        "select": -1,
        "select_calls": [],
    }

    home = tmp_path / "home"
    addon_path = home / "addons" / "script.tony7bones.modv2plus"
    skin_root = home / "addons" / "skin.estuary.modv2"
    skin_xml = skin_root / "xml"
    skin_xml.mkdir(parents=True)
    (addon_path / "resources" / "xml").mkdir(parents=True)
    (addon_path / "resources" / "media" / "extras").mkdir(parents=True)
    # seed the real shipped FILES + media so apply copies genuine bytes
    for fname in _assign("FILES"):
        (addon_path / "resources" / "xml" / fname).write_bytes(
            (ADDON_DIR / "resources" / "xml" / fname).read_bytes()
        )
    for rel_src, _rel_dst in _assign("MEDIA"):
        (addon_path / rel_src).write_bytes((ADDON_DIR / rel_src).read_bytes())
    # seed the real shipped MEDIA_DIRS so apply copies genuine bytes
    for rel_src, _rel_dst in _assign("MEDIA_DIRS"):
        src_dir = ADDON_DIR / rel_src
        dst_dir = addon_path / rel_src
        dst_dir.mkdir(parents=True, exist_ok=True)
        for f in src_dir.glob("*"):
            if f.is_file():
                (dst_dir / f.name).write_bytes(f.read_bytes())

    xbmc = types.ModuleType("xbmc")
    xbmc.LOGERROR = 4
    xbmc.LOGINFO = 1
    xbmc.LOGWARNING = 3
    xbmc.log = lambda msg, level=1: state["log"].append((level, msg))
    xbmc.getSkinDir = lambda: state["skin"]
    xbmc.executebuiltin = lambda cmd, wait=False: state["builtins"].append(cmd)

    xbmcaddon = types.ModuleType("xbmcaddon")

    class _Addon:
        def getAddonInfo(self, key):
            return str(addon_path) if key == "path" else ""

    xbmcaddon.Addon = lambda *a, **k: _Addon()

    xbmcgui = types.ModuleType("xbmcgui")

    class _Dialog:
        def ok(self, title, msg):
            state["ok"].append((title, msg))

        def notification(self, title, msg, icon=None, ms=None):
            state.setdefault("notify", []).append((title, msg))

        def select(self, title, options):
            state["select_calls"].append((title, list(options)))
            return state["select"]

    xbmcgui.Dialog = _Dialog
    xbmcgui.NOTIFICATION_INFO = "info"

    xbmcvfs = types.ModuleType("xbmcvfs")
    xbmcvfs.translatePath = lambda p: p.replace("special://home/", str(home) + "/")

    for nm, mod in (
        ("xbmc", xbmc),
        ("xbmcaddon", xbmcaddon),
        ("xbmcgui", xbmcgui),
        ("xbmcvfs", xbmcvfs),
    ):
        monkeypatch.setitem(sys.modules, nm, mod)

    spec = importlib.util.spec_from_file_location("modv2plus_default", DEFAULT_PY)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # run() is __main__-guarded -> no side effects
    return types.SimpleNamespace(
        mod=mod, state=state, skin_root=skin_root, skin_xml=skin_xml
    )


def test_run_presents_chooser(patch_env):
    patch_env.state["select"] = -1
    patch_env.mod.run()
    assert patch_env.state["select_calls"], "run() must call Dialog().select(...)"
    _title, options = patch_env.state["select_calls"][0]
    assert options == ["Apply patches", "Restore original"]


def test_run_apply_copies_files_and_media(patch_env):
    patch_env.state["select"] = 0
    patch_env.mod.run()
    # every FILES entry copied into the skin xml dir
    for fname in _assign("FILES"):
        dst = patch_env.skin_xml / fname
        assert dst.exists(), f"{fname} must be copied on Apply"
    # the loose media PNG copied to <skin>/media/extras/
    logo = patch_env.skin_root / "media" / "extras" / "logo-text-hires.png"
    assert logo.exists(), "the hi-res wordmark must be copied into the skin media dir"
    assert logo.read_bytes() == LOGO_PNG.read_bytes()
    # the whole weather-stock dir is copied into <skin>/extras/weather-stock
    # (skin root, where special://skin/extras/ resolves — NOT media/extras/)
    dst_weather = patch_env.skin_root / "extras" / "weather-stock"
    assert dst_weather.is_dir(), "weather-stock dir must be copied on Apply"
    copied = sorted(p.name for p in dst_weather.glob("*.png"))
    shipped = sorted(p.name for p in WEATHER_STOCK_DIR.glob("*.png"))
    assert copied == shipped, "every weather-stock icon must be copied"
    assert (dst_weather / "32.png").read_bytes() == (
        WEATHER_STOCK_DIR / "32.png"
    ).read_bytes()
    assert any("ReloadSkin" in b for b in patch_env.state["builtins"])
    # The reload must be automatic: a non-blocking notification, never a modal
    # ok() that waits for a click before reloading.
    assert not patch_env.state["ok"], (
        "Apply success must not show a blocking ok() dialog"
    )
    assert patch_env.state.get("notify"), "Apply success must show a notification"


def test_run_cancel_does_nothing(patch_env):
    patch_env.state["select"] = -1
    patch_env.mod.run()
    for fname in _assign("FILES"):
        assert not (patch_env.skin_xml / fname).exists()
    assert not (
        patch_env.skin_root / "media" / "extras" / "logo-text-hires.png"
    ).exists()
    assert not patch_env.state["builtins"], "cancel must not ReloadSkin"
    assert not patch_env.state["ok"], "cancel must show no summary dialog"


def test_run_bails_on_wrong_skin(patch_env):
    patch_env.state["skin"] = "skin.estuary"
    patch_env.mod.run()
    for fname in _assign("FILES"):
        assert not (patch_env.skin_xml / fname).exists()
    assert patch_env.state["ok"], "should show the Wrong Skin dialog"


def test_run_restore_reverts_xml_and_removes_loose_png(patch_env):
    """Restore copies each .bak back over the live XML, removes the .bak, AND
    deletes the loose media PNG."""
    skin_xml = patch_env.skin_xml
    files = _assign("FILES")
    for fname in files:
        (skin_xml / fname).write_text("PATCHED " + fname)
        (skin_xml / (fname + ".bak")).write_text("ORIGINAL " + fname)
    # a loose PNG present (as if Apply had placed it)
    logo = patch_env.skin_root / "media" / "extras" / "logo-text-hires.png"
    logo.parent.mkdir(parents=True, exist_ok=True)
    logo.write_bytes(b"PNGDATA")
    # a weather-stock dir present (as if Apply had placed it)
    weather = patch_env.skin_root / "extras" / "weather-stock"
    weather.mkdir(parents=True, exist_ok=True)
    (weather / "32.png").write_bytes(b"WEATHERPNG")

    patch_env.state["select"] = 1
    patch_env.mod.run()

    for fname in files:
        assert (skin_xml / fname).read_text() == "ORIGINAL " + fname
        assert not (skin_xml / (fname + ".bak")).exists()
    assert not logo.exists(), "the loose hi-res wordmark must be removed on Restore"
    assert not weather.exists(), "the weather-stock dir must be removed on Restore"
    assert any("ReloadSkin" in b for b in patch_env.state["builtins"])
    # Clean restore auto-reloads via a non-blocking notification (no modal ok()).
    assert not patch_env.state["ok"], (
        "clean restore must not show a blocking ok() dialog"
    )
    assert patch_env.state.get("notify"), "restore must show a notification"


def test_run_restore_nothing_to_restore(patch_env):
    """choice 1 with no .bak and no loose PNG -> nothing reverted, no reload."""
    patch_env.state["select"] = 1
    patch_env.mod.run()
    assert not any("ReloadSkin" in b for b in patch_env.state["builtins"])
    assert patch_env.state["ok"], "should show the 'Nothing to Restore' dialog"
    title, _msg = patch_env.state["ok"][0]
    assert "Restore" in title


def test_restore_media_handles_missing_png(patch_env):
    """restore_media() with no loose PNG present -> (0 removed, 0 failed, 1 skipped)."""
    removed, failed, skipped = patch_env.mod.restore_media(str(patch_env.skin_root))
    assert removed == 0
    assert failed == 0
    assert skipped == len(_assign("MEDIA"))


def test_restore_patches_nothing_to_restore_no_exception(patch_env):
    restored, failed, skipped = patch_env.mod.restore_patches(str(patch_env.skin_xml))
    assert restored == 0
    assert failed == 0
    assert skipped == len(_assign("FILES"))


def test_apply_media_dirs_copies_whole_dir(patch_env):
    applied, failed = patch_env.mod.apply_media_dirs(str(patch_env.skin_root))
    assert applied == len(_assign("MEDIA_DIRS"))
    assert failed == 0
    dst = patch_env.skin_root / "extras" / "weather-stock"
    copied = sorted(p.name for p in dst.glob("*.png"))
    shipped = sorted(p.name for p in WEATHER_STOCK_DIR.glob("*.png"))
    assert copied == shipped


def test_restore_media_dirs_handles_missing_dir(patch_env):
    """restore_media_dirs() with no dir present -> (0 removed, 0 failed, 1 skipped)."""
    removed, failed, skipped = patch_env.mod.restore_media_dirs(
        str(patch_env.skin_root)
    )
    assert removed == 0
    assert failed == 0
    assert skipped == len(_assign("MEDIA_DIRS"))


def test_restore_media_dirs_removes_present_dir(patch_env):
    weather = patch_env.skin_root / "extras" / "weather-stock"
    weather.mkdir(parents=True, exist_ok=True)
    (weather / "32.png").write_bytes(b"x")
    removed, failed, skipped = patch_env.mod.restore_media_dirs(
        str(patch_env.skin_root)
    )
    assert removed == 1
    assert failed == 0
    assert not weather.exists()
