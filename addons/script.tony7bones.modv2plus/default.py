import os
import shutil
import sys
import xbmc
import xbmcgui
import xbmcaddon

try:
    from xbmcvfs import translatePath
except ImportError:
    from xbmc import translatePath

ADDON = xbmcaddon.Addon()
ADDON_PATH = translatePath(ADDON.getAddonInfo("path"))
SKIN_ID = "skin.estuary.modv2"

# XML files copied into the skin's xml/ dir (one-time .bak, then overwrite).
FILES = [
    "Home.xml",
    "SkinSettings.xml",
    "Settings.xml",
    "Includes.xml",
    "Variables.xml",
]

# Loose media assets copied to a path OUTSIDE xml/. Each entry maps a source
# (relative to ADDON_PATH) to a destination (relative to the skin root), both as
# forward-slash POSIX paths normalized at use. These are NEW files in the skin
# (no .bak); Restore deletes them.
MEDIA = [
    (
        "resources/media/extras/logo-text-hires.png",
        "media/extras/logo-text-hires.png",
    ),
]


def apply_patches(skin_xml):
    """Copy each XML in FILES into the skin's xml/ dir.

    The original is snapshotted once as ``<file>.bak`` before the first
    overwrite. Each file is handled defensively: a failure is logged and never
    aborts the run. Returns (applied, failed).

    NB: use ``shutil.copyfile`` (content only), NOT ``copy2``. On Fire OS 8 /
    Android 11 the skin lives on an sdcardfs/FUSE volume where copy2's copystat
    (os.utime / os.chmod) raises OSError(EPERM) *after* the bytes are written —
    which made every copy count as "failed", tripping the "Partly Applied" early
    return before the menu-trim + skin-settings steps. copyfile skips copystat.
    """
    applied = 0
    failed = 0

    for fname in FILES:
        src = os.path.join(ADDON_PATH, "resources", "xml", fname)
        dst = os.path.join(skin_xml, fname)
        bak = dst + ".bak"

        try:
            if os.path.exists(dst) and not os.path.exists(bak):
                shutil.copyfile(dst, bak)
            shutil.copyfile(src, dst)
            applied += 1
            xbmc.log("[mod v2+] applied {}".format(fname), xbmc.LOGINFO)
        except Exception as e:
            xbmc.log("[mod v2+] failed {}: {}".format(fname, e), xbmc.LOGERROR)
            failed += 1

    return applied, failed


def apply_media(skin_root):
    """Copy each loose MEDIA asset into the skin (a NEW file — no .bak).

    Creates the destination directory as needed and overwrites. Each entry is
    handled defensively. Returns (applied, failed).
    """
    applied = 0
    failed = 0

    for rel_src, rel_dst in MEDIA:
        src = os.path.join(ADDON_PATH, *rel_src.split("/"))
        dst = os.path.join(skin_root, *rel_dst.split("/"))

        try:
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copyfile(src, dst)
            applied += 1
            xbmc.log("[mod v2+] applied media {}".format(rel_dst), xbmc.LOGINFO)
        except Exception as e:
            xbmc.log("[mod v2+] failed media {}: {}".format(rel_dst, e), xbmc.LOGERROR)
            failed += 1

    return applied, failed


def restore_patches(skin_xml):
    """Revert the patched XML files to their pre-patch originals.

    For each file in FILES, if a one-time ``<file>.bak`` snapshot exists, copy
    it back over the live file and remove the .bak. Files with no .bak are
    counted as skipped. Each file is handled defensively. Returns
    (restored, failed, skipped).
    """
    restored = 0
    failed = 0
    skipped = 0

    for fname in FILES:
        dst = os.path.join(skin_xml, fname)
        bak = dst + ".bak"

        try:
            if os.path.exists(bak):
                shutil.copyfile(bak, dst)
                os.remove(bak)
                restored += 1
                xbmc.log("[mod v2+] restored {}".format(fname), xbmc.LOGINFO)
            else:
                skipped += 1
                xbmc.log(
                    "[mod v2+] no backup for {}, skipped".format(fname),
                    xbmc.LOGINFO,
                )
        except Exception as e:
            xbmc.log(
                "[mod v2+] failed restoring {}: {}".format(fname, e),
                xbmc.LOGERROR,
            )
            failed += 1

    return restored, failed, skipped


def restore_media(skin_root):
    """Remove the loose MEDIA assets we added (they didn't exist originally).

    A missing file is treated as already-removed (skipped). Each entry is
    handled defensively. Returns (removed, failed, skipped).
    """
    removed = 0
    failed = 0
    skipped = 0

    for _rel_src, rel_dst in MEDIA:
        dst = os.path.join(skin_root, *rel_dst.split("/"))

        try:
            if os.path.exists(dst):
                os.remove(dst)
                removed += 1
                xbmc.log("[mod v2+] removed media {}".format(rel_dst), xbmc.LOGINFO)
            else:
                skipped += 1
                xbmc.log(
                    "[mod v2+] media {} absent, skipped".format(rel_dst),
                    xbmc.LOGINFO,
                )
        except Exception as e:
            xbmc.log(
                "[mod v2+] failed removing media {}: {}".format(rel_dst, e),
                xbmc.LOGERROR,
            )
            failed += 1

    return removed, failed, skipped


def _clear_skinshortcuts_cache():
    """Delete script.skinshortcuts' built data for this skin so it re-seeds the
    home menu from our shipped shortcuts/mainmenu.DATA.xml default.

    Removes every file under special://profile/addon_data/script.skinshortcuts/
    whose name starts with the skin id (the built menu DATA + properties + hash).
    This wipes any user menu customizations — intended for our opinionated default;
    Restore reverts it by rebuilding from the restored full default. Defensive:
    a missing dir is fine, each removal is logged, failures never abort the run.
    Returns the number of files removed.
    """
    removed = 0
    try:
        cache_dir = translatePath("special://profile/addon_data/script.skinshortcuts/")
        if not os.path.isdir(cache_dir):
            xbmc.log(
                "[mod v2+] skinshortcuts cache dir absent, nothing to clear",
                xbmc.LOGINFO,
            )
            return 0
        for name in os.listdir(cache_dir):
            if not name.startswith(SKIN_ID):
                continue
            path = os.path.join(cache_dir, name)
            try:
                if os.path.isfile(path):
                    os.remove(path)
                    removed += 1
                    xbmc.log(
                        "[mod v2+] cleared skinshortcuts {}".format(name),
                        xbmc.LOGINFO,
                    )
            except Exception as e:
                xbmc.log(
                    "[mod v2+] failed clearing skinshortcuts {}: {}".format(name, e),
                    xbmc.LOGERROR,
                )
    except Exception as e:
        xbmc.log(
            "[mod v2+] failed clearing skinshortcuts cache: {}".format(e),
            xbmc.LOGERROR,
        )
    return removed


def _drop_skinshortcuts_hash(dst_dir):
    """Delete the built script.skinshortcuts <skin>.hash for skin.estuary.modv2.

    The hash is how script.skinshortcuts decides whether to REBUILD the home menu:
    on a build it hashes its inputs (the deployed DATA + the skin's template) and,
    if a stored <skin>.hash still matches on the next boot, it SKIPS the rebuild and
    reuses the previously-built includes. That is the caching race this whole path
    defeats: Setup's live skin-switch can race skinshortcuts into building the STOCK
    menu (and writing its hash) BEFORE our menu is deployed; the matching hash then
    makes skinshortcuts skip rebuilding from OUR menu on the next boot, leaving the
    wrong (stock) menu even though ours is on disk. Dropping the hash forces a
    regenerate from our freshly-deployed menu. Unconditional + defensive (a missing
    hash is the desired end-state). Returns True if a hash file was removed.
    """
    hsh = os.path.join(dst_dir, SKIN_ID + ".hash")
    try:
        if os.path.exists(hsh):
            os.remove(hsh)
            xbmc.log("[mod v2+] dropped skinshortcuts hash for rebuild", xbmc.LOGINFO)
            return True
    except Exception as e:
        xbmc.log(
            "[mod v2+] failed dropping skinshortcuts hash: {}".format(e),
            xbmc.LOGERROR,
        )
    return False


def _deploy_skinshortcuts_menu():
    """Deploy our shipped, GUI-built skinshortcuts menu into the user's addon_data
    so script.skinshortcuts builds OUR exact home menu — the six-item trim, the
    Movies/TV shows -> POV actions, TV -> TVGuide, the Favorites relabel, and the
    Movies List / TV Shows List custom-list widgets — verbatim, instead of seeding
    the stock default and approximating it.

    Atomic (re)deploy that DEFEATS the skinshortcuts caching race in one step:
      1. CLEAR the built skinshortcuts cache for skin.estuary.modv2 (the stale
         built menu/properties/hash a racing stock-menu build may have left), then
      2. copy every file under resources/skinshortcuts/ (the mainmenu + per-item
         DATA + the widget .properties) over addon_data, then
      3. DROP the built <skin>.hash so script.skinshortcuts regenerates from OUR
         freshly-deployed menu on the next build/boot instead of skipping the
         rebuild on a matching (stale, stock) hash.

    Clearing BEFORE the copy (then dropping the hash AFTER) is what guarantees the
    deployed menu is the only menu data present and is rebuilt-from on the next
    boot — even when the Setup skin-switch already raced a stock-menu build + hash
    in. Defensive: logged, never aborts the run. Returns the number of files
    deployed.
    """
    deployed = 0
    try:
        src_dir = os.path.join(ADDON_PATH, "resources", "skinshortcuts")
        if not os.path.isdir(src_dir):
            return 0
        # 1. clear any stale built cache (stock-menu race) BEFORE deploying ours.
        _clear_skinshortcuts_cache()
        dst_dir = translatePath("special://profile/addon_data/script.skinshortcuts/")
        os.makedirs(dst_dir, exist_ok=True)
        # 2. deploy our exact menu DATA + widget .properties.
        for name in os.listdir(src_dir):
            shutil.copyfile(os.path.join(src_dir, name), os.path.join(dst_dir, name))
            deployed += 1
        # 3. drop the built hash so the next build regenerates from our menu.
        _drop_skinshortcuts_hash(dst_dir)
        xbmc.log(
            "[mod v2+] deployed skinshortcuts menu ({} files: POV actions + widgets)".format(
                deployed
            ),
            xbmc.LOGINFO,
        )
    except Exception as e:
        xbmc.log(
            "[mod v2+] failed deploying skinshortcuts menu: {}".format(e),
            xbmc.LOGERROR,
        )
    return deployed


def _build_skinshortcuts_menu(skin_root):
    """Build the skinshortcuts home-menu includes from the trimmed mainmenu.DATA.xml
    and BLOCK until they are written, so the home renders WITH the menu on the next
    skin reload.

    Why this is needed (fresh-box bug): on a brand-new box script.skinshortcuts has
    never built, and the skin's OWN first-load build is asynchronous — it finishes
    AFTER the home window has already rendered (blank, logging "Control 9000 ... has
    been asked to focus, but it can't" because script-skinshortcuts-includes.xml is
    missing). Worse, our cache-clear above can race and clobber that build. So we
    drive the build ourselves, deterministically, and wait for the output before the
    caller reloads the skin. MOD V2's own build uses exactly these params
    (mainmenuID=9000, group=mainmenu).
    """
    includes = os.path.join(skin_root, "xml", "script-skinshortcuts-includes.xml")
    try:
        if os.path.exists(includes):
            os.remove(includes)  # force a clean rebuild from the trimmed menu
    except OSError:
        pass
    xbmc.executebuiltin(
        "RunScript(script.skinshortcuts,type=buildxml&mainmenuID=9000&group=mainmenu)"
    )
    # Poll until the includes file exists and its size stops growing (build done).
    # buildxml is fire-and-forget, and a slow Fire TV first build can take ~20s.
    last = -1
    for _ in range(40):
        xbmc.sleep(1000)
        try:
            size = os.path.getsize(includes)
        except OSError:
            continue
        if size > 0 and size == last:
            xbmc.log(
                "[mod v2+] skinshortcuts menu built ({} bytes)".format(size),
                xbmc.LOGINFO,
            )
            return
        last = size
    xbmc.log(
        "[mod v2+] skinshortcuts menu build did not settle in time (continuing)",
        xbmc.LOGERROR,
    )


def apply_home_menu(skin_root):
    """Install our trimmed home menu over the skin's skinshortcuts default.

    Copies resources/shortcuts/mainmenu.DATA.xml -> <skin_root>/shortcuts/
    mainmenu.DATA.xml, taking a one-time mainmenu.DATA.xml.bak of the original
    first (creating the shortcuts dir if needed), then (re)deploys our skinshortcuts
    menu — which itself CLEARS skinshortcuts' built cache for skin.estuary.modv2 and
    DROPS the built <skin>.hash so skinshortcuts regenerates from OUR menu (defeating
    the stock-menu caching race) — then rebuilds the menu includes and BLOCKS until
    they are written so the home renders with the menu on the next reload.
    Defensive: logged, never aborts the run. Returns True if the default was copied.
    """
    src = os.path.join(ADDON_PATH, "resources", "shortcuts", "mainmenu.DATA.xml")
    dst_dir = os.path.join(skin_root, "shortcuts")
    dst = os.path.join(dst_dir, "mainmenu.DATA.xml")
    bak = dst + ".bak"

    try:
        os.makedirs(dst_dir, exist_ok=True)
        if os.path.exists(dst) and not os.path.exists(bak):
            shutil.copyfile(dst, bak)
        shutil.copyfile(src, dst)
        xbmc.log(
            "[mod v2+] applied home menu (trimmed mainmenu.DATA.xml)", xbmc.LOGINFO
        )
        # _deploy_skinshortcuts_menu clears the built cache + drops the hash itself
        # (atomic with the deploy), so the menu is rebuilt from OURS on the next boot.
        _deploy_skinshortcuts_menu()
        _build_skinshortcuts_menu(skin_root)
        return True
    except Exception as e:
        xbmc.log("[mod v2+] failed applying home menu: {}".format(e), xbmc.LOGERROR)
        return False


def restore_home_menu(skin_root):
    """Revert the home menu to the skin's original full default.

    If a mainmenu.DATA.xml.bak snapshot exists, copy it back over
    mainmenu.DATA.xml and remove the .bak, then clear skinshortcuts' built data
    so the menu rebuilds from the restored full default. Defensive: logged, never
    aborts the run. Returns True if a backup was restored.
    """
    dst = os.path.join(skin_root, "shortcuts", "mainmenu.DATA.xml")
    bak = dst + ".bak"

    restored = False
    try:
        if os.path.exists(bak):
            shutil.copyfile(bak, dst)
            os.remove(bak)
            restored = True
            xbmc.log(
                "[mod v2+] restored home menu (original mainmenu.DATA.xml)",
                xbmc.LOGINFO,
            )
        else:
            xbmc.log("[mod v2+] no home-menu backup, skipped restore", xbmc.LOGINFO)
    except Exception as e:
        xbmc.log("[mod v2+] failed restoring home menu: {}".format(e), xbmc.LOGERROR)
    # Clear the built data regardless so the menu rebuilds from whatever default
    # is now in place (restored original, or the skin's own if no backup existed).
    _clear_skinshortcuts_cache()
    return restored


def run():
    if xbmc.getSkinDir() != SKIN_ID:
        xbmcgui.Dialog().ok(
            "Wrong Skin",
            "This only runs on Estuary MOD V2.[CR]Switch skins and run again.",
        )
        return

    skin_root = translatePath("special://home/addons/{}".format(SKIN_ID))
    skin_xml = os.path.join(skin_root, "xml")

    if not os.path.isdir(skin_xml):
        xbmcgui.Dialog().ok(
            "Failed",
            "{} not found.[CR]Install it first, then run this script.".format(SKIN_ID),
        )
        return

    # Direct-action routing: RunScript(...,apply) / RunScript(...,restore) run the
    # matching path straight away (used by the in-tab Apply / Restore buttons in
    # the "Tony.7.Bones MOD V2++" Skin Settings category). With no/unknown arg we
    # fall back to the interactive chooser.
    arg = sys.argv[1].strip().lower() if len(sys.argv) > 1 and sys.argv[1] else ""
    if arg == "apply":
        _apply(skin_root, skin_xml)
        return
    if arg == "restore":
        _restore(skin_root, skin_xml)
        return

    choice = xbmcgui.Dialog().select(
        "Estuary MOD V2++", ["Apply patches", "Restore original"]
    )

    if choice == 0:
        _apply(skin_root, skin_xml)
    elif choice == 1:
        _restore(skin_root, skin_xml)
    # choice == -1 (cancelled / back) -> do nothing


# The skin settings apply_skin_settings sets LIVE. These are ALSO written straight
# into the skin's settings.xml (below) so they survive a first boot that never
# reaches a clean shutdown — Skin.SetBool/SetString only flush to disk on a clean
# shutdown / ReloadSkin, the race that left fresh boxes looking stock.
_SKIN_BOOLS_ON = (
    "show_weatherinfo",
    "EnableSplashScreen",
    "DisableThemes",
    "powermenu_list",
    "enable_power_background",
    "enable_settings_background",
    "enable_search_background",
    "hide_recordingchannels",
    "hide_searches",
    "hide_allchannels",
    "hide_audioaddons",
    "hide_gameaddons",
    "hide_imageaddons",
)
_SKIN_STRINGS = {
    "WeatherIcons.path": "resource://resource.images.weathericons.outline-hd/",
    "WeatherIcons.name": "Weather Icons - Outline HD",
}
# Reset by apply (cleared): the two non-list power-menu styles + channel numbers.
_SKIN_RESET = ("powermenu_panel", "powermenu_iconlist", "ShowPVRChannelNumbers")


def _skin_settings_file():
    return os.path.join(
        translatePath("special://profile/addon_data/{}".format(SKIN_ID)),
        "settings.xml",
    )


def _write_skin_settings(bools_on=(), strings=None, remove=()):
    """Merge skin settings straight into the skin's settings.xml (create if absent),
    PRESERVING every other setting: bools_on -> type=bool 'true'; strings -> type
    string; remove -> deleted. Idempotent. This is the belt-and-suspenders persist
    that makes apply/restore survive a first boot with no clean shutdown."""
    import xml.etree.ElementTree as ET

    strings = strings or {}
    path = _skin_settings_file()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    root = None
    if os.path.exists(path):
        try:
            root = ET.parse(path).getroot()
        except ET.ParseError:
            root = None
    if root is None or root.tag != "settings":
        root = ET.Element("settings")
        root.set("version", "2")
    by_id = {s.get("id"): s for s in root.findall("setting") if s.get("id")}

    def _put(sid, value, stype):
        el = by_id.get(sid)
        if el is None:
            el = ET.SubElement(root, "setting")
            el.set("id", sid)
            by_id[sid] = el
        el.set("type", stype)
        el.text = value

    for b in bools_on:
        _put(b, "true", "bool")
    for sid, val in strings.items():
        _put(sid, val, "string")
    for r in remove:
        el = by_id.get(r)
        if el is not None:
            root.remove(el)
            by_id.pop(r, None)
    with open(path, "w", encoding="utf-8") as f:
        f.write(ET.tostring(root, encoding="unicode"))


def apply_skin_settings():
    """Apply our MOD V2 skin-setting defaults (the parts that aren't shipped files).

    - Weather icons -> the Outline HD pack via Skin.String(WeatherIcons.path) /
      WeatherIcons.name (the strings MOD V2's own picker sets; empty -> .default).
    - Top-bar weather/temp readout ON (`show_weatherinfo`) — MOD V2 leaves it OFF
      on a fresh skin, so a freshly-patched box shows the weather below the clock.
    - Splash screen OFF and seasonal Themes OFF. Both are MOD V2 **opt-out** flags
      (the toggles read `!Skin.HasSetting(...)`), so *setting* `EnableSplashScreen`
      / `DisableThemes` is what turns them off.
    - Power menu style -> "Classic list" (`powermenu_list`; the style is an
      exclusive group, so clear the other two flags `powermenu_panel` /
      `powermenu_iconlist`).
    - Plain backgrounds for the Power / Settings / Search home items. MOD V2 shows
      a dedicated image for each when its flag is UNSET (HomeFanartVar gates on
      `!Skin.HasSetting(enable_*_background)`), so *setting* each flag turns that
      background OFF.
    Defensive: logged, never aborts the run.
    """
    try:
        xbmc.executebuiltin(
            "Skin.SetString(WeatherIcons.path,"
            "resource://resource.images.weathericons.outline-hd/)"
        )
        xbmc.executebuiltin(
            "Skin.SetString(WeatherIcons.name,Weather Icons - Outline HD)"
        )
        xbmc.executebuiltin("Skin.SetBool(show_weatherinfo)")
        xbmc.executebuiltin("Skin.SetBool(EnableSplashScreen)")
        xbmc.executebuiltin("Skin.SetBool(DisableThemes)")
        # Power menu style -> "Classic list" (exclusive group: clear the other two)
        xbmc.executebuiltin("Skin.SetBool(powermenu_list)")
        xbmc.executebuiltin("Skin.Reset(powermenu_panel)")
        xbmc.executebuiltin("Skin.Reset(powermenu_iconlist)")
        # Plain backgrounds for Power / Settings / Search (opt-out flags: set = off).
        xbmc.executebuiltin("Skin.SetBool(enable_power_background)")
        xbmc.executebuiltin("Skin.SetBool(enable_settings_background)")
        xbmc.executebuiltin("Skin.SetBool(enable_search_background)")
        # Hide home-screen widgets via the skin's opt-out bools (setting
        # hide_<widget> removes that widget): TV (Recent recordings, Saved Search
        # Results, All Channels) + Add-ons (Music, Game, Picture).
        for _w in (
            "hide_recordingchannels",  # Recent recordings (#31015)
            "hide_searches",  # Saved Search Results (#31617)
            "hide_allchannels",  # All channels (#31361)
            "hide_audioaddons",  # Music add-ons (#1038)
            "hide_gameaddons",  # Game add-ons (#35049)
            "hide_imageaddons",  # Picture add-ons (#1039)
        ):
            xbmc.executebuiltin("Skin.SetBool({})".format(_w))
        # Channel numbers OFF in the Live TV lists: the skin shows them only when
        # ShowPVRChannelNumbers is set, so clearing it hides them.
        xbmc.executebuiltin("Skin.Reset(ShowPVRChannelNumbers)")
        # Persist the SAME settings straight to settings.xml so they survive a first
        # boot that never reaches a clean shutdown (the Skin.SetBool race).
        _write_skin_settings(_SKIN_BOOLS_ON, _SKIN_STRINGS, _SKIN_RESET)
        xbmc.log("[mod v2+] skin settings applied", xbmc.LOGINFO)
    except Exception as e:
        xbmc.log("[mod v2+] failed applying skin settings: {}".format(e), xbmc.LOGERROR)


def reset_skin_settings():
    """Revert our skin-setting defaults to MOD V2 stock: clear the weather icon
    strings, turn the top-bar readout back off, and clear the splash / themes /
    power-menu flags so they return to MOD V2's defaults."""
    try:
        for s in (
            "WeatherIcons.path",
            "WeatherIcons.name",
            "show_weatherinfo",
            "EnableSplashScreen",
            "DisableThemes",
            "powermenu_list",
            "powermenu_panel",
            "powermenu_iconlist",
            "enable_power_background",
            "enable_settings_background",
            "enable_search_background",
            "hide_recordingchannels",
            "hide_searches",
            "hide_allchannels",
            "hide_audioaddons",
            "hide_gameaddons",
            "hide_imageaddons",
        ):
            xbmc.executebuiltin("Skin.Reset({})".format(s))
        # Restore stock: MOD V2 shows channel numbers by default.
        xbmc.executebuiltin("Skin.SetBool(ShowPVRChannelNumbers)")
        # Persist the reset to settings.xml too: drop all our keys, restore channel #s.
        _write_skin_settings(
            bools_on=("ShowPVRChannelNumbers",),
            remove=_SKIN_BOOLS_ON
            + tuple(_SKIN_STRINGS)
            + ("powermenu_panel", "powermenu_iconlist"),
        )
        xbmc.log("[mod v2+] skin settings reset", xbmc.LOGINFO)
    except Exception as e:
        xbmc.log(
            "[mod v2+] failed resetting skin settings: {}".format(e), xbmc.LOGERROR
        )


def _apply(skin_root, skin_xml):
    applied, failed = apply_patches(skin_xml)
    media_applied, media_failed = apply_media(skin_root)

    total_failed = failed + media_failed
    if total_failed > 0:
        xbmcgui.Dialog().ok(
            "Partly Applied",
            "{} files + {} media applied, {} failed.[CR]Check the Kodi log.".format(
                applied, media_applied, total_failed
            ),
        )
        return

    # Non-blocking: notify and reload immediately. A modal ok() here would block
    # the reload until the user clicked it (while claiming to be reloading).
    xbmcgui.Dialog().notification(
        "Estuary MOD V2++",
        "Applied {} files + {} media — reloading skin".format(applied, media_applied),
        xbmcgui.NOTIFICATION_INFO,
        4000,
    )
    apply_skin_settings()
    apply_home_menu(skin_root)
    xbmc.executebuiltin("ReloadSkin()")


def _restore(skin_root, skin_xml):
    if not xbmcgui.Dialog().yesno(
        "Restore stock MOD V2",
        "This reverts all Tony.7.Bones tweaks and restores the original "
        "MOD V2 skin files.[CR]Continue?",
    ):
        return
    restored, failed, _skipped = restore_patches(skin_xml)
    media_removed, media_failed, _media_skipped = restore_media(skin_root)

    if restored == 0 and media_removed == 0:
        xbmcgui.Dialog().ok(
            "Nothing to Restore",
            "No backups found.[CR]Estuary MOD V2 is already unpatched.",
        )
        return

    total_failed = failed + media_failed
    if total_failed:
        # Blocking only when there's a failure the user should read.
        xbmcgui.Dialog().ok(
            "Original Restored",
            "Restored {} files, removed {} media.[CR]{} could not be reverted "
            "— check the Kodi log.".format(restored, media_removed, total_failed),
        )
    else:
        xbmcgui.Dialog().notification(
            "Estuary MOD V2++",
            "Restored {} files, removed {} media — reloading skin".format(
                restored, media_removed
            ),
            xbmcgui.NOTIFICATION_INFO,
            4000,
        )
    reset_skin_settings()
    restore_home_menu(skin_root)
    xbmc.executebuiltin("ReloadSkin()")


if __name__ == "__main__":
    run()
