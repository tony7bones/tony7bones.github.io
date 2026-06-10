"""Tests for tony7bones.setup.probes — the Guided wizard's done-probes (5d).

The probes answer "is this layer's target state already on the box?" from the
box's ACTUAL state (the re-entrancy principle: installed-state, never marker
files). They are the wizard's resume mechanism, so their honesty matters more
than their optimism: a wrong False merely re-offers an idempotent gate (cheap
self-heal); a wrong True would SKIP a gate (a real hole). The tests therefore
pin the False-by-default shape hard:

* ``foundation_done`` — skin installed AND active (``getSkinDir()==SKIN_ID``).
  Activation is part of done-ness because Kodi's "Keep this skin?" timeout can
  silently revert a set skin (the 5b·3 leg-1 race) — a reverted box must read
  "not done" so the wizard re-offers Foundation (which re-activates).
* ``iptv_done`` — backend installed AND at least one env provider's
  instance-settings FILE exists (never the async channel list; "at least one"
  because an unstaged portal-API provider can never land in-Kodi, and
  requiring ALL files would re-offer the gate forever on such an env).
* ``addons_done`` — per-id ``is_installed`` over base apps + curated video.
  Origin deliberately NOT probed (the peno64 apps ship blank origins by
  design — live-proven under Express in the 5c verify).

All probes are defensive: any raising primitive reads as "not done".
"""

from __future__ import annotations

import os


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
# foundation_done
# --------------------------------------------------------------------------- #
def test_foundation_done_false_on_fresh_box(boot):
    assert _probes(boot).foundation_done() is False


def test_foundation_done_false_when_installed_but_not_active(boot):
    """Installed-but-reverted (the keep-skin race): NOT done — the wizard must
    re-offer Foundation so the re-run re-activates (the self-heal)."""
    _mark_installed(boot, boot.mod.SKIN_ID)
    assert boot.mod.xbmc.getSkinDir() == "skin.estuary"
    assert _probes(boot).foundation_done() is False


def test_foundation_done_false_when_active_but_not_installed(boot, monkeypatch):
    """An active-but-uninstalled skin is an inconsistent half-state: NOT done."""
    monkeypatch.setattr(boot.mod.xbmc, "getSkinDir", lambda: boot.mod.SKIN_ID)
    assert _probes(boot).foundation_done() is False


def test_foundation_done_true_when_installed_and_active(boot, monkeypatch):
    _mark_installed(boot, boot.mod.SKIN_ID)
    monkeypatch.setattr(boot.mod.xbmc, "getSkinDir", lambda: boot.mod.SKIN_ID)
    assert _probes(boot).foundation_done() is True


def test_foundation_done_never_raises(boot, monkeypatch):
    """A raising primitive reads as 'not done' (defensive contract)."""

    def _boom(_aid):
        raise RuntimeError("boom")

    monkeypatch.setattr(_probes(boot), "is_installed", _boom)
    assert _probes(boot).foundation_done() is False


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
def _complete_box(boot, monkeypatch, with_iptv=False):
    """Drive the fake box to a complete state via the probes' own primitives."""
    _mark_installed(boot, boot.mod.SKIN_ID)
    monkeypatch.setattr(boot.mod.xbmc, "getSkinDir", lambda: boot.mod.SKIN_ID)
    _mark_installed(boot, *(list(boot.mod.ADDONS) + list(boot.mod.VIDEO_APPS)))
    if with_iptv:
        _mark_installed(boot, "pvr.iptvsimple")
        _write_instance_file(boot, 1)


def test_box_state_fresh_box_no_iptv_env(boot):
    """Fresh box, no IPTV in the env: iptv reads None (NOT EXPECTED — distinct
    from 'expected and missing')."""
    assert _probes(boot).box_state({}) == {
        "foundation": False,
        "iptv": None,
        "addons": False,
    }


def test_box_state_iptv_expected_and_missing_is_false(boot):
    state = _probes(boot).box_state({"IPTV_M3U": "http://provider.example/x.m3u"})
    assert state["iptv"] is False


def test_box_state_complete_with_iptv(boot, monkeypatch):
    _complete_box(boot, monkeypatch, with_iptv=True)
    assert _probes(boot).box_state({"IPTV_M3U": "http://provider.example/x.m3u"}) == {
        "foundation": True,
        "iptv": True,
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
    assert state == {"foundation": True, "iptv": True, "addons": True}


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


def test_assert_box_complete_layers_param_scopes_the_check(boot, monkeypatch):
    """layers=["foundation"] checks ONLY Foundation — usable right after a
    single gate, before the rest of the box exists."""
    _mark_installed(boot, boot.mod.SKIN_ID)
    monkeypatch.setattr(boot.mod.xbmc, "getSkinDir", lambda: boot.mod.SKIN_ID)
    state = _probes(boot).assert_box_complete({}, layers=["foundation"])
    assert state["foundation"] is True


def test_addons_missing_names_the_gaps(boot):
    _mark_installed(boot, *boot.mod.ADDONS)
    missing = _probes(boot)._addons_missing()
    assert missing == list(boot.mod.VIDEO_APPS)
