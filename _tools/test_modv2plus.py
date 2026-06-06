"""Coverage for the Estuary MOD V2+ add-on (script.tony7bones.modv2plus).

Two layers, mirroring the other add-on tests:

* Static contract — the manifest is well-formed (id / name / version / news), the
  script compiles, FILES is exactly the shipped XMLs (incl. Variables.xml), the
  loose media logo mapping is present and its source PNG ships. The shipped XMLs
  carry the features: Home.xml gates the system-info overlay (default HIDDEN) on
  Skin.HasSetting(show_system_info_overlay) AND Control.HasFocus(802);
  SkinSettings.xml carries a "Tony.7.Bones MOD V2+" category (list 9000 item
  id=11) whose panel (grouplist 1100) holds a "Disable System Info overlay"
  radiobutton toggling show_system_info_overlay (checked-by-default, overlay
  hidden by default), plus the clock and nav-logo per-item toggles and the
  in-tab Apply / Restore buttons; the weather texture is wired directly to the
  Outline HD resource pack (no toggle). Variables.xml carries the HasFocus(11)
  help value; Settings.xml lists Skin Settings before Media sources.

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
MAINMENU_DATA = ADDON_DIR / "resources" / "shortcuts" / "mainmenu.DATA.xml"
HOME_MENU_REMOVED = ("music", "musicvideos", "radio", "games", "pictures", "video")
HOME_MENU_KEPT = ("movies", "tvshows", "livetv", "addons", "favorites", "weather")
WEATHER_STOCK_DIR = ADDON_DIR / "resources" / "media" / "extras" / "weather-stock"
WEATHER_RESOURCE = "resource.images.weathericons.outline-hd"
WEATHER_TEXTURE = (
    "$INFO[Weather.FanartCode,resource://resource.images.weathericons.outline-hd/,.png]"
)


def test_includes_clock_label_uses_var():
    """The top-right clock label now routes through $VAR[ClockLabelVar] so the
    Tony.7.Bones MOD V2+ clock toggle can switch stock-thin <-> MOD V2 bold. The
    raw bold/plain literals must no longer be hard-wired in the clock control, and
    the control still uses font_clock."""
    text = INCLUDES_XML.read_text(encoding="utf-8")
    assert "<label>$VAR[ClockLabelVar]</label>" in text, (
        "clock label must route through ClockLabelVar"
    )
    # the hard-wired literals are gone from the control (they live in the $VAR now)
    assert "<label>$INFO[System.Time]</label>" not in text, (
        "the plain literal clock label must be gone (moved into ClockLabelVar)"
    )
    assert "<label>[B]$INFO[System.Time][/B]</label>" not in text, (
        "the bold literal clock label must not be hard-wired"
    )
    assert "<font>font_clock</font>" in text, "clock must keep the font_clock font"


def test_includes_weather_icon_uses_outline_hd_resource():
    """The top-right weather condition icon is now wired directly (no toggle) to
    the official Outline HD weather resource pack. The old $VAR indirection and
    the legacy stock/colored literals must be gone."""
    text = INCLUDES_XML.read_text(encoding="utf-8")
    assert "<texture>{}</texture>".format(WEATHER_TEXTURE) in text, (
        "weather icon texture must point at the Outline HD resource pack"
    )
    assert "$VAR[WeatherIconTextureVar]" not in text, (
        "the WeatherIconTextureVar indirection must be gone from Includes.xml"
    )
    assert "extras/weather-stock/" not in text, (
        "the legacy stock-white weather literal must be gone"
    )
    assert "special://skin/extras/weather/" not in text, (
        "the legacy MOD V2 colored weather literal must be gone"
    )


def test_includes_no_weather_var_or_flag_remains():
    """No WeatherIconTextureVar / weather_modv2_colored reference may remain
    anywhere in the shipped XMLs — the toggle path is fully removed."""
    for xml in (INCLUDES_XML, VARIABLES_XML, SKINSETTINGS_XML, HOME_XML):
        text = xml.read_text(encoding="utf-8")
        assert "WeatherIconTextureVar" not in text, (
            f"WeatherIconTextureVar must be gone from {xml.name}"
        )
        assert "weather_modv2_colored" not in text, (
            f"weather_modv2_colored must be gone from {xml.name}"
        )


def test_variables_clock_var_defaults_to_stock():
    """ClockLabelVar exists and defaults (unset flag) to the stock thin time,
    switching to the MOD V2 bold look only when the opt-in flag is set. The
    weather variable must no longer exist."""
    root = ET.parse(VARIABLES_XML).getroot()
    by_name = {v.get("name"): v for v in root.iter("variable")}

    assert "WeatherIconTextureVar" not in by_name, (
        "WeatherIconTextureVar must be removed from Variables.xml"
    )

    cv = by_name.get("ClockLabelVar")
    assert cv is not None, "ClockLabelVar must exist in Variables.xml"
    cvals = list(cv.findall("value"))
    bold = [
        e.text
        for e in cvals
        if e.get("condition") == "Skin.HasSetting(clock_modv2_bold)"
    ]
    assert bold == ["[B]$INFO[System.Time][/B]"], (
        f"bold clock value must gate on the flag, got {bold}"
    )
    assert cvals[-1].get("condition") is None
    assert cvals[-1].text == "$INFO[System.Time]", (
        "ClockLabelVar default must be the stock thin time"
    )


def test_weather_stock_icons_removed():
    """The bundled stock-white weather icon set is no longer shipped — the
    official Outline HD resource pack replaces it."""
    assert not WEATHER_STOCK_DIR.exists(), (
        "resources/media/extras/weather-stock/ must be removed"
    )


def test_addon_requires_outline_hd_weather_pack():
    """addon.xml <requires> imports the Outline HD weather resource so Kodi
    auto-installs it from the official repo for real users."""
    root = _addon_root()
    imports = [imp.get("addon") for imp in root.iter("import")]
    assert WEATHER_RESOURCE in imports, (
        f"addon.xml must import {WEATHER_RESOURCE}, got imports: {imports}"
    )


def test_no_media_dirs_in_default():
    """MEDIA_DIRS (the weather-stock dir copy) must be gone from default.py along
    with its apply/restore helpers."""
    text = DEFAULT_PY.read_text()
    assert "MEDIA_DIRS" not in text, "MEDIA_DIRS must be removed from default.py"
    assert "weather-stock" not in text, "no weather-stock reference may remain"
    assert "apply_media_dirs" not in text, "apply_media_dirs must be removed"
    assert "restore_media_dirs" not in text, "restore_media_dirs must be removed"


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


def test_addon_version_floor_1_3_3():
    parts = tuple(int(p) for p in _addon_root().get("version").split("."))
    assert parts >= (1, 3, 3), "version must be at least 1.3.3"


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


# --------------------------------------------------------------------------- #
# Static contract — trimmed home menu (skinshortcuts default)
# --------------------------------------------------------------------------- #
def test_mainmenu_data_ships_and_parses():
    """The trimmed skinshortcuts default ships and is well-formed XML."""
    assert MAINMENU_DATA.exists(), "must ship resources/shortcuts/mainmenu.DATA.xml"
    root = ET.parse(MAINMENU_DATA).getroot()
    assert root.tag == "shortcuts"


def test_mainmenu_data_drops_the_six_items():
    """The trimmed default must contain NONE of the 6 removed defaultIDs while
    keeping movies / tvshows / livetv / addons / favorites / weather."""
    root = ET.parse(MAINMENU_DATA).getroot()
    ids = {s.findtext("defaultID") for s in root.findall("shortcut")}
    for removed in HOME_MENU_REMOVED:
        assert removed not in ids, (
            f"{removed} must be removed from the trimmed home menu, got {sorted(ids)}"
        )
    for kept in HOME_MENU_KEPT:
        assert kept in ids, (
            f"{kept} must remain in the trimmed home menu, got {sorted(ids)}"
        )


def test_default_defines_home_menu_helpers():
    """default.py defines apply_home_menu / restore_home_menu /
    _clear_skinshortcuts_cache, and _apply / _restore call the apply / restore
    helpers respectively."""
    src = DEFAULT_PY.read_text()
    tree = ast.parse(src)
    funcs = {n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
    for name in (
        "apply_home_menu",
        "restore_home_menu",
        "_clear_skinshortcuts_cache",
    ):
        assert name in funcs, f"default.py must define {name}()"

    def _calls_within(func_name):
        body = next(
            n
            for n in tree.body
            if isinstance(n, ast.FunctionDef) and n.name == func_name
        )
        return {
            c.func.id
            for c in ast.walk(body)
            if isinstance(c, ast.Call) and isinstance(c.func, ast.Name)
        }

    assert "apply_home_menu" in _calls_within("_apply"), (
        "_apply must call apply_home_menu"
    )
    assert "restore_home_menu" in _calls_within("_restore"), (
        "_restore must call restore_home_menu"
    )


def test_clear_skinshortcuts_targets_skin_and_addon():
    """_clear_skinshortcuts_cache must target script.skinshortcuts' addon_data
    and filter on the skin id skin.estuary.modv2."""
    src = DEFAULT_PY.read_text()
    assert "addon_data/script.skinshortcuts" in src, (
        "cache clear must target script.skinshortcuts addon_data"
    )
    # the skin id is referenced via the SKIN_ID constant; confirm it is the
    # modv2 skin and that the clear filters file names by it.
    assert 'SKIN_ID = "skin.estuary.modv2"' in src
    assert "name.startswith(SKIN_ID)" in src, (
        "cache clear must filter files by the skin id prefix"
    )


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


def test_home_overlay_gated_on_optin_toggle_and_focus():
    """The system-info overlay is now default HIDDEN via an OPT-IN flag: it shows
    only when show_system_info_overlay is set, and only on gear focus. The old
    opt-out flag (hide_system_info_overlay) must be gone."""
    visible = _group_18000_own_visible(HOME_XML.read_text(encoding="utf-8"))
    assert visible != "false", f"group 18000 must not be hard-disabled, got {visible!r}"
    assert "Skin.HasSetting(show_system_info_overlay)" in visible, (
        f"overlay must gate (default hidden) on the opt-in flag, got {visible!r}"
    )
    assert "hide_system_info_overlay" not in visible, (
        f"the old opt-out flag must be gone, got {visible!r}"
    )
    assert "Control.HasFocus(802)" in visible, (
        f"overlay must gate on gear focus, got {visible!r}"
    )


def test_home_stock_wordmark_variants_point_at_hires():
    """The DEFAULT (stock) wordmark variant in each of the two logo groups uses
    the loose hi-res white logo. There are exactly two such hi-res textures (one
    per group), each gated to show when the MOD V2 original flag is NOT set."""
    text = HOME_XML.read_text(encoding="utf-8")
    assert text.count("<texture>extras/logo-text-hires.png</texture>") == 2, (
        "expected exactly two stock hi-res wordmark textures (one per group)"
    )


def test_home_wordmark_toggle_provides_modv2_original_variants():
    """The wordmark toggle adds a MOD V2 ORIGINAL variant to each group, gated to
    show only when Skin.HasSetting(wordmark_modv2_original): the fallback group
    restores icons/logo-text.png and the main group restores $VAR[LogoTextVar]."""
    text = HOME_XML.read_text(encoding="utf-8")
    # both original textures reappear, but only inside the gated original variants
    assert "<texture>icons/logo-text.png</texture>" in text, (
        "fallback original wordmark (icons/logo-text.png) must be present as a variant"
    )
    assert "<texture>$VAR[LogoTextVar]</texture>" in text, (
        "main original wordmark ($VAR[LogoTextVar]) must be present as a variant"
    )
    # every line referencing either original texture must be inside an original
    # variant — i.e. the file must gate all wordmark images on the flag
    blocks = _all_wordmark_control_blocks(text)
    for block in blocks:
        assert "wordmark_modv2_original" in block, (
            f"each wordmark control must gate on the toggle flag, got: {block!r}"
        )


def _all_wordmark_control_blocks(text):
    """Return every <control type="image"> block carrying a wordmark texture —
    the two stock hi-res variants plus the two MOD V2 original variants (4)."""
    blocks = []
    needles = (
        "extras/logo-text-hires.png",
        "<texture>icons/logo-text.png</texture>",
        "<texture>$VAR[LogoTextVar]</texture>",
    )
    seen = set()
    for needle in needles:
        pos = 0
        while True:
            hit = text.find(needle, pos)
            if hit == -1:
                break
            start = text.rfind('<control type="image">', 0, hit)
            end = text.find("</control>", hit)
            assert start != -1 and end != -1, "malformed wordmark control block"
            if start not in seen:
                seen.add(start)
                blocks.append(text[start : end + len("</control>")])
            pos = end + 1
    return blocks


def test_home_wordmark_variant_count_and_visibility():
    """Each group carries exactly two wordmark variants: a stock one visible when
    the flag is unset, and a MOD V2 original visible when the flag is set. Four
    wordmark image controls total, two stock + two original, balanced."""
    text = HOME_XML.read_text(encoding="utf-8")
    blocks = _all_wordmark_control_blocks(text)
    assert len(blocks) == 4, f"expected four wordmark variants, found {len(blocks)}"
    stock = [b for b in blocks if "!Skin.HasSetting(wordmark_modv2_original)" in b]
    original = [
        b
        for b in blocks
        if "wordmark_modv2_original" in b
        and "!Skin.HasSetting(wordmark_modv2_original)" not in b
    ]
    assert len(stock) == 2, f"expected two stock wordmark variants, got {len(stock)}"
    assert len(original) == 2, (
        f"expected two MOD V2 original wordmark variants, got {len(original)}"
    )
    # the original variants restore the MOD V2 heights (36 fallback / 50 main)
    heights = sorted(
        h
        for b in original
        for h in ("36", "50")
        if "<height>{}</height>".format(h) in b
    )
    assert heights == ["36", "50"], (
        f"original variants must use MOD V2 heights 36 and 50, got {heights}"
    )


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
    """The old opt-in/opt-out overlay radiobuttons must be gone from Extras
    (grouplist 500) — and from the whole file (the new toggle lives in the
    Tony.7.Bones MOD V2+ panel)."""
    root = ET.parse(SKINSETTINGS_XML).getroot()
    grouplist = _find_grouplist(root, "500")
    stale = [
        ctrl
        for ctrl in grouplist.iter("control")
        if ctrl.get("type") == "radiobutton"
        and ctrl.findtext("onclick")
        in (
            "Skin.ToggleSetting(enable_info_overlay)",
            "Skin.ToggleSetting(hide_system_info_overlay)",
            "Skin.ToggleSetting(show_system_info_overlay)",
        )
    ]
    assert not stale, "no overlay toggle may remain in Extras (grouplist 500)"
    text = SKINSETTINGS_XML.read_text(encoding="utf-8")
    assert "enable_info_overlay" not in text, (
        "no enable_info_overlay reference may remain in SkinSettings.xml"
    )
    assert "hide_system_info_overlay" not in text, (
        "no hide_system_info_overlay reference may remain in SkinSettings.xml"
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
    one 'Disable System Info overlay' radiobutton that toggles the opt-in flag
    show_system_info_overlay and is CHECKED by default (overlay hidden by
    default, i.e. "Disable" is on unless the flag is set)."""
    root = ET.parse(SKINSETTINGS_XML).getroot()
    panel = _find_grouplist(root, "1100")
    assert panel.findtext("visible") == "Container(9000).HasFocus(11)", (
        "panel 1100 must be gated on the new category's HasFocus(11)"
    )
    toggles = [
        ctrl
        for ctrl in panel.iter("control")
        if ctrl.get("type") == "radiobutton"
        and ctrl.findtext("onclick") == "Skin.ToggleSetting(show_system_info_overlay)"
    ]
    assert len(toggles) == 1, (
        f"expected exactly one show_system_info_overlay toggle in panel 1100, "
        f"found {len(toggles)}"
    )
    ctrl = toggles[0]
    assert ctrl.findtext("label") == "Disable System Info overlay"
    # default checked: "Disable" is on (overlay hidden) unless the flag is set
    assert ctrl.findtext("selected") == "!Skin.HasSetting(show_system_info_overlay)"


@pytest.mark.parametrize(
    "flag,label",
    [
        ("clock_modv2_bold", "Stock clock (thin)"),
        ("wordmark_modv2_original", "Stock nav logo (white)"),
    ],
)
def test_skinsettings_panel_has_the_clock_and_logo_toggles(flag, label):
    """Panel 1100 carries each opt-out toggle: it toggles the opt-in flag and
    is checked (selected) by default, i.e. selected = !Skin.HasSetting(<flag>) so
    the stock look is on unless the user opts into the MOD V2 look. The weather
    toggle is gone (weather is now the fixed Outline HD set)."""
    root = ET.parse(SKINSETTINGS_XML).getroot()
    panel = _find_grouplist(root, "1100")
    toggles = [
        ctrl
        for ctrl in panel.iter("control")
        if ctrl.get("type") == "radiobutton"
        and ctrl.findtext("onclick") == "Skin.ToggleSetting({})".format(flag)
    ]
    assert len(toggles) == 1, (
        f"expected exactly one {flag} toggle in panel 1100, found {len(toggles)}"
    )
    ctrl = toggles[0]
    assert ctrl.findtext("label") == label, (
        f"{flag} toggle label must be {label!r}, got {ctrl.findtext('label')!r}"
    )
    assert ctrl.findtext("selected") == "!Skin.HasSetting({})".format(flag), (
        f"{flag} toggle must default ON (stock): selected = !Skin.HasSetting({flag})"
    )


def test_skinsettings_panel_has_apply_and_restore_buttons():
    """Panel 1100 carries two buttons that run the add-on directly: an Apply
    button (RunScript ...,apply) and a Restore button (RunScript ...,restore)."""
    root = ET.parse(SKINSETTINGS_XML).getroot()
    panel = _find_grouplist(root, "1100")
    buttons = {
        ctrl.findtext("onclick"): ctrl.findtext("label")
        for ctrl in panel.iter("control")
        if ctrl.get("type") == "button"
    }
    assert (
        buttons.get("RunScript(script.tony7bones.modv2plus,apply)")
        == "Apply Tony.7.Bones tweaks"
    ), f"missing/incorrect Apply button, got buttons: {buttons}"
    assert (
        buttons.get("RunScript(script.tony7bones.modv2plus,restore)")
        == "Restore stock MOD V2"
    ), f"missing/incorrect Restore button, got buttons: {buttons}"


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
        "yesno": True,
        "yesno_calls": [],
    }

    home = tmp_path / "home"
    addon_path = home / "addons" / "script.tony7bones.modv2plus"
    skin_root = home / "addons" / "skin.estuary.modv2"
    skin_xml = skin_root / "xml"
    skin_xml.mkdir(parents=True)
    (addon_path / "resources" / "xml").mkdir(parents=True)
    (addon_path / "resources" / "media" / "extras").mkdir(parents=True)
    (addon_path / "resources" / "shortcuts").mkdir(parents=True)
    # seed the real shipped FILES + media so apply copies genuine bytes
    for fname in _assign("FILES"):
        (addon_path / "resources" / "xml" / fname).write_bytes(
            (ADDON_DIR / "resources" / "xml" / fname).read_bytes()
        )
    for rel_src, _rel_dst in _assign("MEDIA"):
        (addon_path / rel_src).write_bytes((ADDON_DIR / rel_src).read_bytes())
    # seed the trimmed skinshortcuts default so apply_home_menu copies real bytes
    (addon_path / "resources" / "shortcuts" / "mainmenu.DATA.xml").write_bytes(
        MAINMENU_DATA.read_bytes()
    )
    # a profile dir so _clear_skinshortcuts_cache has a real path to scan
    (home / "userdata" / "addon_data" / "script.skinshortcuts").mkdir(parents=True)

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

        def yesno(self, title, msg, *a, **k):
            state["yesno_calls"].append((title, msg))
            return state["yesno"]

    xbmcgui.Dialog = _Dialog
    xbmcgui.NOTIFICATION_INFO = "info"

    xbmcvfs = types.ModuleType("xbmcvfs")
    xbmcvfs.translatePath = lambda p: p.replace(
        "special://home/", str(home) + "/"
    ).replace("special://profile/", str(home / "userdata") + "/")

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
    # Default to the no-arg invocation (interactive chooser path); arg-routing
    # tests override mod.sys.argv themselves. Without this, run() would read
    # pytest's own argv and misbehave.
    monkeypatch.setattr(mod.sys, "argv", ["default.py"])
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
    # the trimmed home menu is copied into the skin's shortcuts dir
    menu = patch_env.skin_root / "shortcuts" / "mainmenu.DATA.xml"
    assert menu.exists(), "the trimmed home menu must be copied on Apply"
    assert menu.read_bytes() == MAINMENU_DATA.read_bytes()
    assert any("ReloadSkin" in b for b in patch_env.state["builtins"])
    # The reload must be automatic: a non-blocking notification, never a modal
    # ok() that waits for a click before reloading.
    assert not patch_env.state["ok"], (
        "Apply success must not show a blocking ok() dialog"
    )
    assert patch_env.state.get("notify"), "Apply success must show a notification"
    # Apply points MOD V2's weather widgets at the Outline HD set via skin strings.
    assert any(
        "Skin.SetString(WeatherIcons.path" in b and "outline-hd" in b
        for b in patch_env.state["builtins"]
    ), "Apply must set WeatherIcons.path to the Outline HD pack"
    assert any(
        "Skin.SetString(WeatherIcons.name" in b for b in patch_env.state["builtins"]
    ), "Apply must set WeatherIcons.name"
    # Apply also turns ON the top-bar weather/temp readout (off on a fresh skin).
    assert any(
        "Skin.SetBool(show_weatherinfo)" in b for b in patch_env.state["builtins"]
    ), "Apply must enable the top-bar weather readout (show_weatherinfo)"
    # ...and applies the other Extras defaults: splash OFF, themes OFF (both
    # opt-out flags), power menu -> Classic list.
    for flag in ("EnableSplashScreen", "DisableThemes", "powermenu_list"):
        assert any(
            "Skin.SetBool({})".format(flag) in b for b in patch_env.state["builtins"]
        ), "Apply must set {}".format(flag)


def test_run_apply_arg_skips_chooser_and_applies(patch_env, monkeypatch):
    """RunScript(...,apply) applies directly without showing the chooser."""
    monkeypatch.setattr(patch_env.mod.sys, "argv", ["default.py", "apply"])
    patch_env.mod.run()
    assert not patch_env.state["select_calls"], (
        "apply arg must NOT pop the interactive chooser"
    )
    for fname in _assign("FILES"):
        assert (patch_env.skin_xml / fname).exists(), f"{fname} must be applied"
    assert any("ReloadSkin" in b for b in patch_env.state["builtins"])


def test_run_restore_arg_skips_chooser_and_restores(patch_env, monkeypatch):
    """RunScript(...,restore) restores directly without showing the chooser."""
    skin_xml = patch_env.skin_xml
    for fname in _assign("FILES"):
        (skin_xml / fname).write_text("PATCHED " + fname)
        (skin_xml / (fname + ".bak")).write_text("ORIGINAL " + fname)
    monkeypatch.setattr(patch_env.mod.sys, "argv", ["default.py", "restore"])
    patch_env.mod.run()
    assert not patch_env.state["select_calls"], (
        "restore arg must NOT pop the interactive chooser"
    )
    for fname in _assign("FILES"):
        assert (skin_xml / fname).read_text() == "ORIGINAL " + fname
    assert any("ReloadSkin" in b for b in patch_env.state["builtins"])


def test_run_unknown_arg_falls_back_to_chooser(patch_env, monkeypatch):
    """An unrecognised arg falls back to the interactive chooser (here cancelled)."""
    monkeypatch.setattr(patch_env.mod.sys, "argv", ["default.py", "bogus"])
    patch_env.state["select"] = -1
    patch_env.mod.run()
    assert patch_env.state["select_calls"], "unknown arg must fall back to chooser"


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

    patch_env.state["select"] = 1
    patch_env.mod.run()

    for fname in files:
        assert (skin_xml / fname).read_text() == "ORIGINAL " + fname
        assert not (skin_xml / (fname + ".bak")).exists()
    assert not logo.exists(), "the loose hi-res wordmark must be removed on Restore"
    assert any("ReloadSkin" in b for b in patch_env.state["builtins"])
    # Clean restore auto-reloads via a non-blocking notification (no modal ok()).
    assert not patch_env.state["ok"], (
        "clean restore must not show a blocking ok() dialog"
    )
    assert patch_env.state.get("notify"), "restore must show a notification"
    # Restore clears the weather-icon skin strings (back to MOD V2 default).
    assert any(
        "Skin.Reset(WeatherIcons.path)" in b for b in patch_env.state["builtins"]
    ), "Restore must reset WeatherIcons.path"
    assert any(
        "Skin.Reset(show_weatherinfo)" in b for b in patch_env.state["builtins"]
    ), "Restore must turn the top-bar weather readout back off"
    # ...and clears the other Extras flags back to MOD V2 stock.
    for flag in ("EnableSplashScreen", "DisableThemes", "powermenu_list"):
        assert any(
            "Skin.Reset({})".format(flag) in b for b in patch_env.state["builtins"]
        ), "Restore must reset {}".format(flag)


def test_run_restore_nothing_to_restore(patch_env):
    """choice 1 with no .bak and no loose PNG -> nothing reverted, no reload."""
    patch_env.state["select"] = 1
    patch_env.mod.run()
    assert not any("ReloadSkin" in b for b in patch_env.state["builtins"])
    assert patch_env.state["ok"], "should show the 'Nothing to Restore' dialog"
    title, _msg = patch_env.state["ok"][0]
    assert "Restore" in title


def test_run_restore_asks_confirmation_and_cancels(patch_env):
    """Restore must prompt for confirmation; answering No reverts nothing."""
    skin_xml = patch_env.skin_xml
    for fname in _assign("FILES"):
        (skin_xml / fname).write_text("PATCHED " + fname)
        (skin_xml / (fname + ".bak")).write_text("ORIGINAL " + fname)
    patch_env.state["select"] = 1
    patch_env.state["yesno"] = False  # user declines the confirmation
    patch_env.mod.run()
    assert patch_env.state["yesno_calls"], "Restore must ask for confirmation"
    for fname in _assign("FILES"):
        assert (skin_xml / fname).read_text() == "PATCHED " + fname, (
            "declining the confirm must NOT revert files"
        )
        assert (skin_xml / (fname + ".bak")).exists()
    assert not any("ReloadSkin" in b for b in patch_env.state["builtins"])


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
