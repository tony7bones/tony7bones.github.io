"""Tests for tony7bones.setup.probes — the Guided wizard's done-probes (5d,
redefined per docs/plans/automate-share-and-backup-config.md section 2/3.6 for
the Foundation/Skin/Backup split).

The probes answer "is this layer's target state already on the box?" from the
box's ACTUAL state (the re-entrancy principle: installed-state, never marker
files). They are the wizard's resume mechanism, so their honesty matters more
than their optimism: a wrong False merely re-offers an idempotent gate (cheap
self-heal); a wrong True would SKIP a gate (a real hole). The tests therefore
pin the False-by-default shape hard:

* ``foundation_done`` — all source repos + our proxy repo + autocomplete
  installed, KodiShare/KodiBackup sources at their EXPECTED (env-resolved)
  URLs (content-checked), and weather.multi configured with a real loc1_url
  (content-checked). Does NOT check skin state (that's ``skin_done``'s job)
  or RSS (env-optional).
* ``backup_done`` — script.ezmaintenanceplusplus ACTUALLY installed (the
  install-invisibility trap) AND its settings.xml has non-empty
  download.path/restore.path rooted at the expected backup share.
* ``iptv_done`` — backend installed AND at least one env provider's
  instance-settings FILE exists (never the async channel list; "at least one"
  because an unstaged portal-API provider can never land in-Kodi, and
  requiring ALL files would re-offer the gate forever on such an env).
* ``skin_done`` — MOD V2 installed AND active (``getSkinDir()==SKIN_ID``) AND
  the MOD V2+ patch applied — reusing modv2plus's own
  ``service.py::_is_applied()`` (dynamically loaded from its real install
  path) rather than re-deriving the check. Activation is part of done-ness
  because Kodi's "Keep this skin?" timeout can silently revert a set skin
  (the 5b·3 leg-1 race) — a reverted box must read "not done" so the wizard
  re-offers Skin (which re-activates).
* ``addons_done`` — per-id ``is_installed`` over base apps + curated video.
  Origin deliberately NOT probed (the peno64 apps ship blank origins by
  design — live-proven under Express in the 5c verify).

All probes are defensive: any raising primitive reads as "not done".
"""

from __future__ import annotations

import os
from xml.etree import ElementTree as ET


def _probes(boot):
    return boot.mod._probes


def _mark_installed(boot, *ids):
    for aid in ids:
        boot.state["installed"].add(aid)


def _write_instance_file(boot, n):
    special = boot.mod._iptv._instance_settings_special(n)
    path = boot.mod.xbmcvfs.translatePath(special)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write('<settings version="2"/>')
    return path


# --------------------------------------------------------------------------- #
# Foundation content-check helpers.
# --------------------------------------------------------------------------- #
def _write_sources(boot, share_url=None, backup_url=None):
    """Write KodiShare/KodiBackup <source> entries directly into sources.xml
    at the given URLs (defaults: the canonical mini-host URLs)."""
    fnd = boot.mod._foundation
    share_url = share_url or fnd.kodi_share_url({})
    backup_url = backup_url or fnd.kodi_backup_url({})
    root = ET.Element("sources")
    files = ET.SubElement(root, "files")
    ET.SubElement(files, "default")
    for name, path in (
        (fnd.KODI_SHARE_SOURCE_NAME, share_url),
        (fnd.KODI_BACKUP_SOURCE_NAME, backup_url),
    ):
        src = ET.SubElement(files, "source")
        ET.SubElement(src, "name").text = name
        ET.SubElement(src, "path").text = path
        ET.SubElement(src, "allowsharing").text = "true"
    path = fnd._sources_xml_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(ET.tostring(root, encoding="unicode"))


def _write_weather_settings(boot, loc1_url="us/ca/sacramento"):
    fnd = boot.mod._foundation
    path = fnd._weather_multi_settings_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    root = ET.Element("settings")
    s = ET.SubElement(root, "setting")
    s.set("id", "loc1_url")
    s.text = loc1_url
    with open(path, "w", encoding="utf-8") as f:
        f.write(ET.tostring(root, encoding="unicode"))


def _complete_foundation(boot, box_env=None):
    """Drive the fake box to Foundation's full done-state: all repos + our
    proxy repo + autocomplete installed, KodiShare/KodiBackup sources at their
    expected URLs, weather.multi installed with a real loc1_url."""
    box_env = box_env or {}
    addons = boot.mod._addons
    fnd = boot.mod._foundation
    _mark_installed(boot, *(rid for _z, rid in addons.REPO_ZIPS if rid))
    _mark_installed(boot, addons.PROXY_REPO_ID)
    _mark_installed(boot, fnd.AUTOCOMPLETE_ID)
    _mark_installed(boot, fnd.WEATHER_ADDON)
    _write_sources(boot, fnd.kodi_share_url(box_env), fnd.kodi_backup_url(box_env))
    _write_weather_settings(boot)


# --------------------------------------------------------------------------- #
# Backup content-check helpers.
# --------------------------------------------------------------------------- #
def _write_ezm_settings(boot, box_env=None, download_path=None, restore_path=None):
    bak = boot.mod._backup
    box_env = box_env or {}
    path = download_path or (bak.kodi_backup_url(box_env).rstrip("/") + "/mybox/")
    rpath = restore_path or path
    xml_path = bak._ezm_settings_path()
    os.makedirs(os.path.dirname(xml_path), exist_ok=True)
    root = ET.Element("settings")
    for setting_id, value in (
        ("destination", "1"),
        ("download.path", path),
        ("restore.path", rpath),
    ):
        s = ET.SubElement(root, "setting")
        s.set("id", setting_id)
        s.text = value
    with open(xml_path, "w", encoding="utf-8") as f:
        f.write(ET.tostring(root, encoding="unicode"))


def _complete_backup(boot, box_env=None):
    bak = boot.mod._backup
    _mark_installed(boot, bak.EZM_ID)
    _write_ezm_settings(boot, box_env)


# --------------------------------------------------------------------------- #
# Skin content-check helpers (the modv2plus _is_applied() reuse).
# --------------------------------------------------------------------------- #
def _mark_modv2plus_applied(boot):
    """Write the REAL marker _is_applied() (modv2plus's own, dynamically
    loaded from its actual service.py) checks for: the patched Home.xml
    string, at the skin's installed path under the fake Kodi tree."""
    path = boot.mod.xbmcvfs.translatePath(
        "special://home/addons/{}/xml/Home.xml".format(boot.mod.SKIN_ID)
    )
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write("<window><control><show_system_info_overlay/></control></window>")


def _mark_menu_is_ours(boot):
    """Write the REAL marker _menu_is_ours() checks for: the built
    skinshortcuts includes file containing the POV action."""
    path = boot.mod.xbmcvfs.translatePath(
        "special://home/addons/{}/xml/script-skinshortcuts-includes.xml".format(
            boot.mod.SKIN_ID
        )
    )
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(
            "<includes><include><onclick>plugin.video.pov</onclick></include></includes>"
        )


def _mark_settings_applied(boot):
    """Write the REAL marker _settings_applied() checks for: the skin's own
    settings.xml with the weather-readout toggle on + the Outline-HD icon set."""
    path = boot.mod.xbmcvfs.translatePath(
        "special://profile/addon_data/{}/settings.xml".format(boot.mod.SKIN_ID)
    )
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(
            "<settings>"
            '<setting id="show_weatherinfo">true</setting>'
            '<setting id="WeatherIcons.path">resource://resource.images.weathericons.outline-hd/</setting>'
            "</settings>"
        )


def _complete_skin(boot, monkeypatch):
    """Drive the fake box to Skin's FULL done-state — all three of
    modv2plus's own patch-applied checks, matching exactly what its service
    considers "nothing to do" (not just the file patch alone)."""
    _mark_installed(boot, boot.mod.SKIN_ID, boot.mod.MODV2PLUS_ID)
    monkeypatch.setattr(boot.mod.xbmc, "getSkinDir", lambda: boot.mod.SKIN_ID)
    _mark_modv2plus_applied(boot)
    _mark_menu_is_ours(boot)
    _mark_settings_applied(boot)


def _complete_box(boot, monkeypatch, with_iptv=False):
    """Drive the fake box to a fully complete state via the probes' own
    real content-check primitives (not a shortcut stub)."""
    _complete_foundation(boot)
    _complete_backup(boot)
    _complete_skin(boot, monkeypatch)
    _mark_installed(boot, *(list(boot.mod.ADDONS) + list(boot.mod.VIDEO_APPS)))
    if with_iptv:
        _mark_installed(boot, "pvr.iptvsimple")
        _write_instance_file(boot, 1)


# --------------------------------------------------------------------------- #
# foundation_done
# --------------------------------------------------------------------------- #
def test_foundation_done_false_on_fresh_box(boot):
    assert _probes(boot).foundation_done({}) is False


def test_foundation_done_false_when_a_repo_missing(boot):
    _complete_foundation(boot)
    missing_rid = next(rid for _z, rid in boot.mod._addons.REPO_ZIPS if rid)
    boot.state["installed"].discard(missing_rid)
    assert _probes(boot).foundation_done({}) is False


def test_foundation_done_false_when_proxy_repo_missing(boot):
    _complete_foundation(boot)
    boot.state["installed"].discard(boot.mod._addons.PROXY_REPO_ID)
    assert _probes(boot).foundation_done({}) is False


def test_foundation_done_false_when_autocomplete_missing(boot):
    _complete_foundation(boot)
    boot.state["installed"].discard(boot.mod._foundation.AUTOCOMPLETE_ID)
    assert _probes(boot).foundation_done({}) is False


def test_foundation_done_false_when_sources_missing(boot):
    """Content-checked: no sources.xml at all -> not done."""
    _complete_foundation(boot)
    os.remove(boot.mod._foundation._sources_xml_path())
    assert _probes(boot).foundation_done({}) is False


def test_foundation_done_false_when_source_url_wrong(boot):
    """Content-checked: a KodiShare entry present under the right name but the
    WRONG url (e.g. a stale mini IP) does not satisfy the probe."""
    _complete_foundation(boot)
    _write_sources(boot, share_url="nfs://10.0.0.9/Wrong/Path/")
    assert _probes(boot).foundation_done({}) is False


def test_foundation_done_false_when_weather_addon_not_installed(boot):
    _complete_foundation(boot)
    boot.state["installed"].discard(boot.mod._foundation.WEATHER_ADDON)
    assert _probes(boot).foundation_done({}) is False


def test_foundation_done_false_when_weather_loc1_url_empty(boot):
    """Content-checked: weather.multi installed but loc1_url is empty (the
    load-bearing fetch field) -> not done."""
    _complete_foundation(boot)
    _write_weather_settings(boot, loc1_url="")
    assert _probes(boot).foundation_done({}) is False


def test_foundation_done_true_when_fully_configured(boot):
    _complete_foundation(boot)
    assert _probes(boot).foundation_done({}) is True


def test_foundation_done_honors_env_resolved_urls(boot):
    """A non-default MINI_HOST env override is honored: sources written at the
    OVERRIDDEN url satisfy the probe when the SAME env is passed in."""
    env = {"MINI_HOST": "10.0.0.9"}
    _complete_foundation(boot, box_env=env)
    assert _probes(boot).foundation_done(env) is True
    # The default (no override) URL does NOT match the overridden sources.
    assert _probes(boot).foundation_done({}) is False


def test_foundation_done_never_raises(boot, monkeypatch):
    """A raising primitive reads as 'not done' (defensive contract)."""

    def _boom(_aid):
        raise RuntimeError("boom")

    monkeypatch.setattr(_probes(boot), "is_installed", _boom)
    assert _probes(boot).foundation_done({}) is False


# --------------------------------------------------------------------------- #
# backup_done
# --------------------------------------------------------------------------- #
def test_backup_done_false_on_fresh_box(boot):
    assert _probes(boot).backup_done({}) is False


def test_backup_done_false_when_settings_present_but_not_installed(boot):
    """The install-invisibility trap: settings.xml correct but EZM_ID never
    actually registered -> not done (never trust settings alone)."""
    _write_ezm_settings(boot)
    assert _probes(boot).backup_done({}) is False


def test_backup_done_false_when_installed_but_no_settings(boot):
    _mark_installed(boot, boot.mod._backup.EZM_ID)
    assert _probes(boot).backup_done({}) is False


def test_backup_done_false_when_path_not_rooted_at_expected_share(boot):
    _mark_installed(boot, boot.mod._backup.EZM_ID)
    _write_ezm_settings(
        boot,
        download_path="nfs://10.0.0.9/Somewhere/Else/",
        restore_path="nfs://10.0.0.9/Somewhere/Else/",
    )
    assert _probes(boot).backup_done({}) is False


def test_backup_done_true_when_installed_and_configured(boot):
    _complete_backup(boot)
    assert _probes(boot).backup_done({}) is True


def test_backup_done_never_raises(boot, monkeypatch):
    def _boom(_aid):
        raise RuntimeError("boom")

    monkeypatch.setattr(_probes(boot), "is_installed", _boom)
    assert _probes(boot).backup_done({}) is False


# --------------------------------------------------------------------------- #
# iptv_done
# --------------------------------------------------------------------------- #
def test_iptv_done_false_without_backend(boot):
    env = {"IPTV_M3U": "http://provider.example/x.m3u"}
    assert _probes(boot).iptv_done(env) is False


def test_iptv_done_false_with_backend_but_no_instance_file(boot):
    """Backend installed but the apply never wrote a provider's instance file
    (e.g. a crash before the enforce): NOT done — the gate is re-offered."""
    _mark_installed(boot, "pvr.iptvsimple")
    env = {"IPTV_M3U": "http://provider.example/x.m3u"}
    assert _probes(boot).iptv_done(env) is False


def test_iptv_done_true_with_backend_and_legacy_instance_file(boot):
    _mark_installed(boot, "pvr.iptvsimple")
    _write_instance_file(boot, 1)
    env = {"IPTV_M3U": "http://provider.example/x.m3u"}
    assert _probes(boot).iptv_done(env) is True


def test_iptv_done_at_least_one_numbered_provider_file_counts(boot):
    """The numbered multi-provider shape: ONE provider's file existing is done
    (an unstaged portal-API provider never writes a file — requiring all would
    re-offer the gate forever; the deliberate 'at least one' semantics)."""
    _mark_installed(boot, "pvr.iptvsimple")
    env = {
        "IPTV_1_NAME": "P1",
        "IPTV_1_M3U": "http://provider.example/1.m3u",
        "IPTV_2_NAME": "P2",
        "IPTV_2_MODE": "xtream",
        "IPTV_2_PORTAL": "http://portal.example",
    }
    assert _probes(boot).iptv_done(env) is False
    _write_instance_file(boot, 1)
    assert _probes(boot).iptv_done(env) is True


def test_iptv_done_never_raises(boot, monkeypatch):
    def _boom(_env):
        raise RuntimeError("boom")

    _mark_installed(boot, "pvr.iptvsimple")
    monkeypatch.setattr(_probes(boot), "_iptv_providers", _boom)
    assert _probes(boot).iptv_done({"IPTV_M3U": "x"}) is False


# --------------------------------------------------------------------------- #
# skin_done
# --------------------------------------------------------------------------- #
def test_skin_done_false_on_fresh_box(boot):
    assert _probes(boot).skin_done() is False


def test_skin_done_false_when_installed_but_not_active(boot):
    """Installed-but-reverted (the keep-skin race): NOT done — the wizard must
    re-offer Skin so the re-run re-activates (the self-heal). All three patch
    markers are present, isolating "not active" as the ONLY failing condition."""
    _mark_installed(boot, boot.mod.SKIN_ID, boot.mod.MODV2PLUS_ID)
    _mark_modv2plus_applied(boot)
    _mark_menu_is_ours(boot)
    _mark_settings_applied(boot)
    assert boot.mod.xbmc.getSkinDir() == "skin.estuary"
    assert _probes(boot).skin_done() is False


def test_skin_done_false_when_active_but_not_installed(boot, monkeypatch):
    """An active-but-uninstalled skin is an inconsistent half-state: NOT done."""
    monkeypatch.setattr(boot.mod.xbmc, "getSkinDir", lambda: boot.mod.SKIN_ID)
    assert _probes(boot).skin_done() is False


def test_skin_done_false_when_installed_and_active_but_patch_not_applied(
    boot, monkeypatch
):
    """MOD V2 installed + active but the patch marker is absent (e.g. a MOD V2
    skin UPDATE overwrote Home.xml with stock): NOT done — re-offers Skin,
    which re-applies via the closure's re-entrant install."""
    _mark_installed(boot, boot.mod.SKIN_ID, boot.mod.MODV2PLUS_ID)
    monkeypatch.setattr(boot.mod.xbmc, "getSkinDir", lambda: boot.mod.SKIN_ID)
    assert _probes(boot).skin_done() is False


def test_skin_done_true_when_installed_active_and_patch_applied(boot, monkeypatch):
    """The full green path — proves the REAL dynamic reuse of modv2plus's own
    service.py checks, not a re-derived duplicate: every marker is written to
    the exact paths those functions check."""
    _complete_skin(boot, monkeypatch)
    assert _probes(boot).skin_done() is True


def test_skin_done_uses_modv2plus_real_is_applied_not_a_duplicate(boot, monkeypatch):
    """MUTATION: if a re-derived check were used instead of the real reuse,
    this would not notice modv2plus's OWN marker changing. Proves the probe
    tracks whatever the REAL service.py currently checks for."""
    _complete_skin(boot, monkeypatch)
    # Overwrite Home.xml WITHOUT the marker -> the real _is_applied() reads False.
    path = boot.mod.xbmcvfs.translatePath(
        "special://home/addons/{}/xml/Home.xml".format(boot.mod.SKIN_ID)
    )
    with open(path, "w", encoding="utf-8") as f:
        f.write("<window><control/></window>")
    assert _probes(boot).skin_done() is False


def test_skin_done_false_when_menu_not_ours(boot, monkeypatch):
    """QA-confirmed fidelity gap, closed: the file patch can be present while
    a live race leaves script.skinshortcuts still serving a cached STOCK
    menu (_menu_is_ours() == False). This must read as NOT done — checking
    only _is_applied() would miss it and the wizard would never re-offer
    Skin to fix the still-stock menu."""
    _mark_installed(boot, boot.mod.SKIN_ID, boot.mod.MODV2PLUS_ID)
    monkeypatch.setattr(boot.mod.xbmc, "getSkinDir", lambda: boot.mod.SKIN_ID)
    _mark_modv2plus_applied(boot)
    _mark_settings_applied(boot)
    # deliberately NOT calling _mark_menu_is_ours — the includes file is absent
    assert _probes(boot).skin_done() is False


def test_skin_done_false_when_settings_not_applied(boot, monkeypatch):
    """QA-confirmed fidelity gap, closed: an unclean first boot can lose the
    look settings even though the file patch persisted immediately
    (_settings_applied() == False). Must read as NOT done."""
    _mark_installed(boot, boot.mod.SKIN_ID, boot.mod.MODV2PLUS_ID)
    monkeypatch.setattr(boot.mod.xbmc, "getSkinDir", lambda: boot.mod.SKIN_ID)
    _mark_modv2plus_applied(boot)
    _mark_menu_is_ours(boot)
    # deliberately NOT calling _mark_settings_applied
    assert _probes(boot).skin_done() is False


def test_skin_done_never_raises(boot, monkeypatch):
    def _boom(_aid):
        raise RuntimeError("boom")

    monkeypatch.setattr(_probes(boot), "is_installed", _boom)
    assert _probes(boot).skin_done() is False


def test_skin_done_never_raises_when_modv2plus_not_installed(boot, monkeypatch):
    """The dynamic xbmcaddon.Addon(MODV2PLUS_ID) lookup raises when modv2plus
    is not installed (the fake mirrors real Kodi) — must read as not applied,
    never propagate."""
    _mark_installed(boot, boot.mod.SKIN_ID)
    monkeypatch.setattr(boot.mod.xbmc, "getSkinDir", lambda: boot.mod.SKIN_ID)
    assert _probes(boot).skin_done() is False


# --------------------------------------------------------------------------- #
# addons_done
# --------------------------------------------------------------------------- #
def test_addons_done_false_on_fresh_box(boot):
    assert _probes(boot).addons_done() is False


def test_addons_done_false_with_only_base_apps(boot):
    _mark_installed(boot, *boot.mod.ADDONS)
    assert _probes(boot).addons_done() is False


def test_addons_done_true_with_apps_and_video(boot):
    _mark_installed(boot, *(list(boot.mod.ADDONS) + list(boot.mod.VIDEO_APPS)))
    assert _probes(boot).addons_done() is True


def test_addons_done_never_raises(boot, monkeypatch):
    def _boom(_aid):
        raise RuntimeError("boom")

    monkeypatch.setattr(_probes(boot), "is_installed", _boom)
    assert _probes(boot).addons_done() is False


# --------------------------------------------------------------------------- #
# box_state — the one honest layer-done-ness dict (Phase 6)
# --------------------------------------------------------------------------- #
def test_box_state_fresh_box_no_iptv_env(boot):
    """Fresh box, no IPTV in the env: iptv reads None (NOT EXPECTED — distinct
    from 'expected and missing')."""
    assert _probes(boot).box_state({}) == {
        "foundation": False,
        "backup": False,
        "iptv": None,
        "skin": False,
        "addons": False,
    }


def test_box_state_iptv_expected_and_missing_is_false(boot):
    state = _probes(boot).box_state({"IPTV_M3U": "http://provider.example/x.m3u"})
    assert state["iptv"] is False


def test_box_state_complete_with_iptv(boot, monkeypatch):
    _complete_box(boot, monkeypatch, with_iptv=True)
    assert _probes(boot).box_state({"IPTV_M3U": "http://provider.example/x.m3u"}) == {
        "foundation": True,
        "backup": True,
        "iptv": True,
        "skin": True,
        "addons": True,
    }


# --------------------------------------------------------------------------- #
# missing_required_imports — the dependency-closure walk (Phase 6)
# --------------------------------------------------------------------------- #
def _write_manifest(boot, aid, xml):
    d = boot.addons / aid
    d.mkdir(parents=True, exist_ok=True)
    (d / "addon.xml").write_text(xml)


def test_closure_walk_empty_tree_is_clean(boot):
    assert _probes(boot).missing_required_imports() == []


def test_closure_walk_finds_dangling_required_import(boot):
    _write_manifest(
        boot,
        "plugin.video.app",
        '<addon id="plugin.video.app"><requires>'
        '<import addon="script.module.gone"/>'
        "</requires></addon>",
    )
    assert _probes(boot).missing_required_imports() == [
        ("plugin.video.app", "script.module.gone")
    ]


def test_closure_walk_present_on_disk_satisfies_even_disabled(boot):
    """An add-on PRESENT on disk satisfies the import even when disabled — the
    dailymotion install-then-disable contract must NOT read as dangling."""
    _write_manifest(
        boot,
        "plugin.video.app",
        '<addon id="plugin.video.app"><requires>'
        '<import addon="plugin.video.dailymotion_com"/>'
        "</requires></addon>",
    )
    _write_manifest(
        boot,
        "plugin.video.dailymotion_com",
        '<addon id="plugin.video.dailymotion_com"/>',
    )
    boot.state["disabled"].add("plugin.video.dailymotion_com")
    assert _probes(boot).missing_required_imports() == []


def test_closure_walk_skips_optional_and_runtime_imports(boot):
    """optional="true" imports are on-demand (Kodi's behaviour) and xbmc.*/
    kodi.* are runtime-provided — neither is dangling."""
    _write_manifest(
        boot,
        "plugin.video.app",
        '<addon id="plugin.video.app"><requires>'
        '<import addon="xbmc.python" version="3.0.0"/>'
        '<import addon="kodi.binary.instance.pvr"/>'
        '<import addon="plugin.googledrive" optional="true"/>'
        "</requires></addon>",
    )
    assert _probes(boot).missing_required_imports() == []


def test_closure_walk_bundled_system_addon_satisfies(boot):
    """THE REAL-BOX QA FIND: a required import shipped INSIDE Kodi
    (special://xbmc/addons/ — metadata.common.*, script.module.pil, …) never
    appears under special://home, and the first cut falsely "dangled" 7 such
    imports on the owner's actual complete box. The bundled system tree must
    satisfy. MUTATION: dropping the system-tree union fails here."""
    _write_manifest(
        boot,
        "metadata.album.universal",
        '<addon id="metadata.album.universal"><requires>'
        '<import addon="metadata.common.allmusic.com"/>'
        "</requires></addon>",
    )
    sys_dir = boot.sysaddons / "metadata.common.allmusic.com"
    sys_dir.mkdir(parents=True)
    (sys_dir / "addon.xml").write_text('<addon id="metadata.common.allmusic.com"/>')
    assert _probes(boot).missing_required_imports() == []


def test_closure_walk_system_addons_are_not_walked(boot):
    """The walk audits OUR install ritual — user add-ons only. A bundled
    system add-on's own imports are Kodi's responsibility, not a box-complete
    failure (and the system tree is read-only anyway)."""
    sys_dir = boot.sysaddons / "metadata.album.universal"
    sys_dir.mkdir(parents=True)
    (sys_dir / "addon.xml").write_text(
        '<addon id="metadata.album.universal"><requires>'
        '<import addon="metadata.common.gone"/>'
        "</requires></addon>"
    )
    # A user add-on must still exist or the walk returns early on an empty tree.
    _write_manifest(boot, "plugin.video.app", '<addon id="plugin.video.app"/>')
    assert _probes(boot).missing_required_imports() == []


def test_closure_walk_registry_fallback_satisfies(boot):
    """Belt-and-braces: a dep on NEITHER tree but known to Kodi's own registry
    (is_installed) is satisfied — this probe informs, so a false alarm is
    worse than a miss. MUTATION: dropping the is_installed fallback fails
    here."""
    _write_manifest(
        boot,
        "plugin.video.app",
        '<addon id="plugin.video.app"><requires>'
        '<import addon="script.module.registered.elsewhere"/>'
        "</requires></addon>",
    )
    _mark_installed(boot, "script.module.registered.elsewhere")
    assert _probes(boot).missing_required_imports() == []


def test_closure_walk_skips_unparseable_manifest(boot):
    _write_manifest(boot, "broken.addon", "<addon id=NOT-XML")
    _write_manifest(
        boot,
        "plugin.video.app",
        '<addon id="plugin.video.app"><requires>'
        '<import addon="script.module.gone"/>'
        "</requires></addon>",
    )
    assert _probes(boot).missing_required_imports() == [
        ("plugin.video.app", "script.module.gone")
    ]


# --------------------------------------------------------------------------- #
# assert_box_complete — the verification primitive (Phase 6): honest, never lies
# --------------------------------------------------------------------------- #
def test_assert_box_complete_raises_naming_whats_missing(boot):
    import pytest

    with pytest.raises(AssertionError) as e:
        _probes(boot).assert_box_complete({})
    msg = str(e.value)
    assert "box NOT complete" in msg
    assert "foundation" in msg
    assert "backup" in msg
    assert "skin" in msg
    assert "addons: not installed:" in msg
    # No IPTV in the env -> the iptv layer is NOT expected, NOT reported.
    assert "iptv:" not in msg


def test_assert_box_complete_reports_expected_missing_iptv(boot):
    import pytest

    with pytest.raises(AssertionError) as e:
        _probes(boot).assert_box_complete({"IPTV_M3U": "http://provider.example/x"})
    assert "iptv:" in str(e.value)


def test_assert_box_complete_returns_state_on_a_complete_box(boot, monkeypatch):
    _complete_box(boot, monkeypatch, with_iptv=True)
    state = _probes(boot).assert_box_complete(
        {"IPTV_M3U": "http://provider.example/x.m3u"}
    )
    assert state == {
        "foundation": True,
        "backup": True,
        "iptv": True,
        "skin": True,
        "addons": True,
    }


def test_assert_box_complete_catches_dangling_import_on_complete_box(boot, monkeypatch):
    """The closure walk has teeth: a box whose layer probes all pass but which
    carries a dangling required import is NOT complete. MUTATION: dropping the
    missing_required_imports() call from assert_box_complete fails here."""
    import pytest

    _complete_box(boot, monkeypatch)
    _write_manifest(
        boot,
        "plugin.video.app",
        '<addon id="plugin.video.app"><requires>'
        '<import addon="script.module.gone"/>'
        "</requires></addon>",
    )
    with pytest.raises(AssertionError) as e:
        _probes(boot).assert_box_complete({})
    assert "dangling required imports" in str(e.value)
    assert "plugin.video.app -> script.module.gone" in str(e.value)


def test_assert_box_complete_layers_param_scopes_the_check(boot):
    """layers=["foundation"] checks ONLY Foundation — usable right after a
    single gate, before the rest of the box exists."""
    _complete_foundation(boot)
    state = _probes(boot).assert_box_complete({}, layers=["foundation"])
    assert state["foundation"] is True


def test_addons_missing_names_the_gaps(boot):
    _mark_installed(boot, *boot.mod.ADDONS)
    missing = _probes(boot)._addons_missing()
    assert missing == list(boot.mod.VIDEO_APPS)
