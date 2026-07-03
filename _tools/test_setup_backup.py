"""Unit tests for the Backup layer (plan section 3.1a).

``tony7bones.setup.backup`` installs EZ Maintenance++ (this repo's own `++` fork)
by DIRECT EXTRACT — the normal closure resolver cannot see it, since its
repository.json entry is served only by our own 127.0.0.1 proxy, which the
resolver explicitly skips — then configures it with a port-free, per-device NFS
backup destination on the mini's Backup share.

These tests drive the backup module DIRECTLY against the shared fake-Kodi
``boot`` fixture (conftest.py), reached via ``boot.mod._backup`` (imported by the
bootstrap so it shares the same fake-Kodi environment as every other layer, even
though ``apply_backup`` is not yet wired into run_express/run_guided).
"""

from __future__ import annotations

import urllib.request
from xml.etree import ElementTree as ET


def _backup(boot):
    return boot.mod._backup


def _ezm_settings_path(boot):
    import xbmcvfs

    return xbmcvfs.translatePath(
        "special://profile/addon_data/script.ezmaintenanceplusplus/settings.xml"
    )


def _stub_install_success(boot, monkeypatch):
    """Stub the direct-extract so EZM++ reports INSTALLED (the bare fake-Kodi
    index has no entry for it — same story as pvr.artwork/modv2plus)."""
    bak = _backup(boot)
    extracted = []

    def _extract(url, dialog, pct, log):
        extracted.append(url)
        boot.state["installed"].add(bak.EZM_ID)
        return True

    monkeypatch.setattr(bak, "extract_zip", _extract)
    monkeypatch.setattr(
        bak, "_latest_zip_url", lambda aid: "http://local/{}-9.9.9.zip".format(aid)
    )
    return extracted


def _read_ezm_settings(boot):
    path = _ezm_settings_path(boot)
    root = ET.parse(path).getroot()
    return {s.get("id"): (s.text or "") for s in root.findall("setting")}


# --------------------------------------------------------------------------- #
# apply_backup — the LayerResult contract
# --------------------------------------------------------------------------- #
def test_apply_backup_returns_backup_layerresult_on_success(boot, monkeypatch):
    _stub_install_success(boot, monkeypatch)
    bak = _backup(boot)
    res = bak.apply_backup({}, dialog=None, log=boot.mod._log)

    assert res.layer == "backup"
    assert res.ok is True
    assert res.needs_restart is True
    assert bak.EZM_ID in res.installed
    assert res.failed == {}


def test_apply_backup_ok_false_when_zip_url_unresolvable(boot, monkeypatch):
    """Unlike the skin closure (which fails against the bare fake index with no
    real network involved), EZM++'s direct-extract path has NO closure-resolve
    step to naturally block it in tests — `_latest_zip_url` is a REAL network
    call that would otherwise hit the actually-deployed add-on. Stub it
    explicitly to simulate an unresolvable URL (e.g. the repo is unreachable)."""
    bak = _backup(boot)
    monkeypatch.setattr(bak, "_latest_zip_url", lambda aid: None)
    res = bak.apply_backup({}, dialog=None, log=boot.mod._log)
    assert res.ok is False
    assert bak.EZM_ID in res.failed
    assert bak.EZM_ID not in res.installed


# --------------------------------------------------------------------------- #
# Device-name resolution — the collision-prevention fix (QA finding).
#
# DEVICE_NAME ships commented-out by default in the env template, so a real
# box easily reaches apply_backup with NO env value. Without a fallback,
# EVERY such box would collapse to the same generic "device" slug and
# silently overwrite each other's backups on the shared remote destination.
# apply_backup must use the FULL fallback chain (env.resolve_device_name):
# env DEVICE_NAME -> Kodi's own services.devicename -> the generic slug.
# --------------------------------------------------------------------------- #
def test_apply_backup_uses_env_device_name_when_present(boot, monkeypatch):
    _stub_install_success(boot, monkeypatch)
    bak = _backup(boot)
    calls = []
    monkeypatch.setattr(bak, "_configure_backup", lambda env, name: calls.append(name))
    bak.apply_backup({"DEVICE_NAME": "Office"}, dialog=None)
    assert calls == ["Office"]


def test_apply_backup_falls_back_to_kodi_device_name_when_env_empty(boot, monkeypatch):
    """The collision-prevention fix: with NO DEVICE_NAME in the env, apply_backup
    must fall back to Kodi's own services.devicename setting — NOT go straight
    to the generic slug — so two real boxes with different Kodi device names
    (the common real-world case) get different, non-colliding subfolders."""
    _stub_install_success(boot, monkeypatch)
    boot.state["settings_values"] = {"services.devicename": "Bedroom Fire TV"}
    bak = _backup(boot)
    calls = []
    monkeypatch.setattr(bak, "_configure_backup", lambda env, name: calls.append(name))
    bak.apply_backup({}, dialog=None)  # no DEVICE_NAME in the env at all
    assert calls == ["Bedroom Fire TV"]


def test_apply_backup_two_boxes_with_different_kodi_names_get_different_slugs(
    boot, monkeypatch
):
    """The actual collision-prevention proof: two boxes that BOTH leave
    DEVICE_NAME unset in their env, but have DIFFERENT Kodi device names,
    must resolve to DIFFERENT backup subfolders — not the same generic one."""
    _stub_install_success(boot, monkeypatch)
    bak = _backup(boot)

    boot.state["settings_values"] = {"services.devicename": "Office Fire TV"}
    bak._configure_backup({}, bak.resolve_device_name({}))
    office_settings = dict(_read_ezm_settings(boot))

    boot.state["settings_values"] = {"services.devicename": "Bedroom Fire TV"}
    bak._configure_backup({}, bak.resolve_device_name({}))
    bedroom_settings = dict(_read_ezm_settings(boot))

    assert office_settings["download.path"] != bedroom_settings["download.path"]
    assert "/office-fire-tv/" in office_settings["download.path"]
    assert "/bedroom-fire-tv/" in bedroom_settings["download.path"]


def test_apply_backup_falls_back_to_generic_slug_when_everything_empty(
    boot, monkeypatch
):
    """Only when BOTH the env AND Kodi's device name are unreadable does this
    degrade to the generic slug — the SAME residual risk this codebase already
    accepts for the master-env scaffold's local file, not a new, worse one."""
    _stub_install_success(boot, monkeypatch)
    bak = _backup(boot)
    assert bak.resolve_device_name({}) == "", (
        "with no env and no readable Kodi device name, resolution must be empty "
        "(sanitize_device_name is what turns that into the generic slug)"
    )
    bak.apply_backup({}, dialog=None)  # no env, no settings_values seeded
    settings = _read_ezm_settings(boot)
    assert "/device/" in settings["download.path"]


def test_apply_backup_treats_kodi_stock_default_as_no_identity(boot, monkeypatch):
    """A never-renamed box reports Kodi's own STOCK default ("Kodi", confirmed
    against guisettings.xml's shipped default) — NOT an empty string. Trusting
    that as a real name would defeat the whole fallback: every unconfigured box
    of the same build would collide on the SAME non-empty-but-generic slug.
    Must be treated exactly like blank."""
    _stub_install_success(boot, monkeypatch)
    boot.state["settings_values"] = {"services.devicename": "Kodi"}
    bak = _backup(boot)
    assert bak.resolve_device_name({}) == "", (
        "Kodi's stock default device name must resolve the same as no name at all"
    )
    bak.apply_backup({}, dialog=None)
    settings = _read_ezm_settings(boot)
    assert "/device/" in settings["download.path"]


def test_two_never_renamed_boxes_resolve_the_same_known_residual_slug(boot):
    """Two boxes that BOTH still report Kodi's stock "Kodi" device name (never
    renamed) resolve to the SAME empty identity, not one of them accidentally
    keeping "kodi" as if it were a real, distinguishing name. Documents this as
    a known, accepted residual (same class the master-env scaffold already
    tolerates for its local file) — not a NEW, silently-different-per-box bug."""
    bak = _backup(boot)
    boot.state["settings_values"] = {"services.devicename": "Kodi"}
    first = bak.resolve_device_name({})
    boot.state["settings_values"] = {"services.devicename": "kodi"}  # case-insensitive
    second = bak.resolve_device_name({})
    assert first == second == ""


# --------------------------------------------------------------------------- #
# Install mechanism — DIRECT EXTRACT is REQUIRED (section 2's install-
# invisibility trap: the normal closure resolver cannot see this add-on).
# --------------------------------------------------------------------------- #
def test_latest_zip_url_resolves_live_version(boot):
    """The REAL _latest_zip_url body (not the stub every other test uses) —
    mirrors test_bootstrap.py's equivalent coverage of the bootstrap's own
    copy. Every other test in this file monkeypatches this function directly,
    so without this test 100% of its actual logic (the urlopen call, the
    version regex, the URL assembly) would be untested, not just its happy
    path — a real gap an earlier QA pass caught."""
    bak = _backup(boot)
    url = bak._latest_zip_url("script.ezmaintenanceplusplus")
    assert url == (
        "https://tony7bones.github.io/addons/script.ezmaintenanceplusplus/"
        "script.ezmaintenanceplusplus-1.0.0.zip"
    )


def test_latest_zip_url_handles_error(boot, monkeypatch):
    def boom(*a, **k):
        raise OSError("no net")

    monkeypatch.setattr(urllib.request, "urlopen", boom)
    bak = _backup(boot)
    assert bak._latest_zip_url("script.ezmaintenanceplusplus") is None


def test_install_ezm_uses_direct_extract_not_closure_resolver(boot, monkeypatch):
    """EZM++ must be installed via extract_zip + _latest_zip_url — this module
    has no `install_selection`/`install_with_deps` NAME bound in its namespace at
    all (a structural guarantee: the closure resolver is not merely unused here,
    it is not even reachable from this module)."""
    bak = _backup(boot)
    assert not hasattr(bak, "install_selection")
    assert not hasattr(bak, "install_with_deps")

    extracted = _stub_install_success(boot, monkeypatch)
    ok = bak._install_ezm(dialog=None)
    assert ok is True
    assert any("script.ezmaintenanceplusplus" in u for u in extracted)


def test_install_ezm_reentry_short_circuits(boot, monkeypatch):
    """Already-installed EZM++ skips the extract entirely (re-entry, no
    redundant network fetch)."""
    bak = _backup(boot)
    boot.state["installed"].add(bak.EZM_ID)
    calls = []
    monkeypatch.setattr(bak, "extract_zip", lambda *a, **k: calls.append(1) or True)
    assert bak._install_ezm(dialog=None) is True
    assert calls == []


def test_install_ezm_verifies_registry_not_extract_return_value(boot, monkeypatch):
    """A non-raising extract that does NOT actually register the add-on must
    still report False — is_installed() is the source of truth, not extract_zip's
    own return value (the install-invisibility trap named in section 2)."""
    bak = _backup(boot)
    monkeypatch.setattr(bak, "extract_zip", lambda *a, **k: True)  # "succeeds"
    monkeypatch.setattr(bak, "_latest_zip_url", lambda aid: "http://local/x.zip")
    # note: does NOT add EZM_ID to state["installed"] — extract lied
    assert bak._install_ezm(dialog=None) is False


def test_apply_backup_never_configures_on_failed_install(boot, monkeypatch):
    """A failed/unverified install must NEVER write settings.xml — otherwise the
    probe could read 'done' for an add-on that was never actually registered."""
    bak = _backup(boot)
    calls = []
    monkeypatch.setattr(bak, "_install_ezm", lambda dialog: False)
    monkeypatch.setattr(
        bak, "_configure_backup", lambda env, name: calls.append((env, name))
    )
    res = bak.apply_backup({"DEVICE_NAME": "Office"}, dialog=None)
    assert calls == []
    assert res.ok is False


# --------------------------------------------------------------------------- #
# _configure_backup — the port-free, per-device settings.xml write
# --------------------------------------------------------------------------- #
def test_configure_backup_writes_port_free_per_device_path(boot):
    bak = _backup(boot)
    bak._configure_backup({}, "Office")
    settings = _read_ezm_settings(boot)
    assert settings["destination"] == "1"
    expected = "nfs://192.168.7.2/Users/moquette/Kodi/Backup/office/"
    assert settings["download.path"] == expected
    assert settings["restore.path"] == expected
    assert ":2049" not in settings["download.path"]


def test_configure_backup_honors_mini_host_override(boot):
    bak = _backup(boot)
    bak._configure_backup({"MINI_HOST": "10.0.0.9"}, "Bedroom")
    settings = _read_ezm_settings(boot)
    assert settings["download.path"] == (
        "nfs://10.0.0.9/Users/moquette/Kodi/Backup/bedroom/"
    )


def test_configure_backup_device_slug_matches_env_sanitize(boot):
    """The per-device subfolder uses the SAME sanitizer as the master-env
    scaffold (env.sanitize_device_name) — no cross-box collisions, matches the
    existing ATV1/ATV2 shape (Decision B)."""
    bak = _backup(boot)
    bak._configure_backup({}, "Living Room TV!")
    settings = _read_ezm_settings(boot)
    assert "/living-room-tv/" in settings["download.path"]


def test_configure_backup_preserves_other_settings(boot):
    """An existing settings.xml's unrelated settings survive untouched."""
    bak = _backup(boot)
    path = _ezm_settings_path(boot)
    import os

    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(
            '<settings><setting id="notify_mode">true</setting>'
            '<setting id="filesize_alert">500</setting></settings>'
        )
    bak._configure_backup({}, "Office")
    settings = _read_ezm_settings(boot)
    assert settings["notify_mode"] == "true"
    assert settings["filesize_alert"] == "500"
    assert settings["destination"] == "1"


def test_configure_backup_idempotent_on_second_run(boot):
    bak = _backup(boot)
    bak._configure_backup({}, "Office")
    first = _read_ezm_settings(boot)
    bak._configure_backup({}, "Office")
    second = _read_ezm_settings(boot)
    assert first == second


def test_configure_backup_handles_malformed_settings_xml(boot):
    """A corrupt settings.xml is recreated, not crashed on."""
    bak = _backup(boot)
    path = _ezm_settings_path(boot)
    import os

    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write("<settings><not closed")
    bak._configure_backup({}, "Office")  # must not raise
    settings = _read_ezm_settings(boot)
    assert settings["destination"] == "1"


def test_configure_backup_mkdirs_failure_is_non_fatal(boot, monkeypatch):
    import xbmcvfs

    def _boom(path):
        raise OSError("share unreachable")

    monkeypatch.setattr(xbmcvfs, "mkdirs", _boom)
    bak = _backup(boot)
    bak._configure_backup({}, "Office")  # must not raise
    settings = _read_ezm_settings(boot)
    assert settings["destination"] == "1"


def test_configure_backup_never_raises_on_write_error(boot, monkeypatch):
    real_open = open

    def boom(path, *a, **k):
        if str(path).endswith("settings.xml") and (
            "w" in (a[0] if a else k.get("mode", ""))
        ):
            raise OSError("disk full")
        return real_open(path, *a, **k)

    monkeypatch.setattr("builtins.open", boom)
    bak = _backup(boot)
    bak._configure_backup({}, "Office")  # must not raise
