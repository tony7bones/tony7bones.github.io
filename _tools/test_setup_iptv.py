"""Unit tests for the IPTV layer (Phase 2d).

``tony7bones.setup.iptv`` holds the LIFTED bodies of the monolith's
``_copy_device_files`` / ``_copy_one_device_file`` (+ ``DEVICE_FILE_COPIES``) and
``_ensure_iptv_custom_tv_groups`` (+ its helper ``_set_instance_setting`` and the
IPTV instance-settings constants) out of
``script.tony7bones.bootstrap/default.py`` — behaviour-identical (the in-Kodi
CONFIG half of the IPTV layer). It also adds the composed ``apply_iptv`` layer
entry point (device-copy + instance-settings enforce together), which the Phase-4
orchestrator will adopt; ``run()``/``_configure_box`` does NOT call it yet (they
keep calling the individual bodies in their existing interleaved slots — copy
BEFORE enforce — so the characterization snapshot stays byte-identical).

These tests drive the iptv module DIRECTLY against the shared fake-Kodi ``boot``
fixture (conftest.py) — the same real fake Kodi the bootstrap suite uses, reached
via ``boot.mod._iptv`` (the iptv module the bootstrap imports under the fake
Kodi). This is the behaviour-preserving oracle for the move: the lifted bodies
must land the SAME state the monolith's inline functions did. The whole-``run()``
interleaving is pinned separately by the modular_setup characterization snapshot;
here we pin the layer (and its parts) in isolation.

NO deps-injection seam (Tech-debt ledger). The moved bodies touch only
``xbmc`` / ``xbmcvfs`` / ``os`` / ``ElementTree`` — no monkeypatched install
primitives — so the tests patch ``boot.mod._iptv.*`` (or the shared fake-Kodi
modules) directly, no injected ``deps`` object.

No real provider credentials appear anywhere here: the m3u/epg values are
obviously-fake ``http://iptv.example`` / ``http://h/...`` URLs.
"""

from __future__ import annotations

import os
from xml.etree import ElementTree as ET


def _iptv(boot):
    """The iptv module bound under the fake Kodi (via the bootstrap)."""
    return boot.mod._iptv


# special:// destinations of the three configured copies.
_RSS_DST = "special://home/userdata/RssFeeds.xml"
_IPTV_INSTANCE_DST = (
    "special://home/userdata/addon_data/pvr.iptvsimple/instance-settings-1.xml"
)
_IPTV_GROUPS_DST = (
    "special://home/userdata/addon_data/pvr.iptvsimple/channelGroups/"
    "customTVGroups-Network24.xml"
)


def _dst_path(boot, special):
    """Absolute (translated) path of a special:// destination."""
    return boot.mod.xbmcvfs.translatePath(special)


def _instance_path(boot):
    return _dst_path(boot, _iptv(boot).IPTV_INSTANCE_SETTINGS_SPECIAL)


def _read_instance_settings(boot):
    """Parse instance-settings-1.xml and return {id: text} for its <setting>s."""
    root = ET.parse(_instance_path(boot)).getroot()
    return {s.get("id"): (s.text or "") for s in root.findall("setting")}


def _make_groups_file(boot):
    """Create the custom-groups file the enforce GATES on, so the enforce runs."""
    path = _dst_path(boot, _iptv(boot).IPTV_CUSTOM_TV_GROUPS_FILE_VALUE)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(
            "<customChannelGroups><channelGroupName>X</channelGroupName>"
            "</customChannelGroups>"
        )
    return path


def _point_copies(boot, monkeypatch, tmp_path, mapping):
    """Repoint the iptv module's DEVICE_FILE_COPIES so the given special:// dests
    read from temp files (others get a guaranteed-missing source)."""
    iptv = _iptv(boot)
    new = []
    for src, dst in iptv.DEVICE_FILE_COPIES:
        if dst in mapping:
            new.append((str(mapping[dst]), dst))
        else:
            new.append((str(tmp_path / "missing" / os.path.basename(src)), dst))
    monkeypatch.setattr(iptv, "DEVICE_FILE_COPIES", new)


# --------------------------------------------------------------------------- #
# Constants — the enforced schema values.
# --------------------------------------------------------------------------- #
def test_iptv_constants_match_schema(boot):
    """The enforced values must be the CUSTOM_GROUPS enum (2) + a channelGroups
    path pointing at the Network24 file we copy."""
    iptv = _iptv(boot)
    assert iptv.IPTV_TV_GROUP_MODE_KEY == "tvGroupMode"
    assert iptv.IPTV_TV_GROUP_MODE_CUSTOM == "2"
    assert iptv.IPTV_CUSTOM_TV_GROUPS_FILE_KEY == "customTvGroupsFile"
    assert iptv.IPTV_CUSTOM_TV_GROUPS_FILE_VALUE.endswith(
        "customTVGroups-Network24.xml"
    )
    assert "channelGroups" in iptv.IPTV_CUSTOM_TV_GROUPS_FILE_VALUE
    assert iptv.IPTV_TV_CHANNEL_GROUPS_ONLY_KEY == "tvChannelGroupsOnly"


def test_iptv_default_device_copies_are_the_three_expected(boot):
    """The data-driven list holds the RSS feed + the two pvr.iptvsimple files, each
    to userdata/addon_data (private config never goes near the repo)."""
    iptv = _iptv(boot)
    dsts = [d for _s, d in iptv.DEVICE_FILE_COPIES]
    assert _RSS_DST in dsts
    assert _IPTV_INSTANCE_DST in dsts
    assert _IPTV_GROUPS_DST in dsts
    assert len(iptv.DEVICE_FILE_COPIES) == 3
    for src, dst in iptv.DEVICE_FILE_COPIES:
        assert src.startswith("/storage/")
        assert dst.startswith("special://home/userdata/")


# --------------------------------------------------------------------------- #
# Device → userdata file copies (guarded / overwrite / auto-create dirs).
# --------------------------------------------------------------------------- #
def test_copy_device_files_copies_rss_when_present(boot, monkeypatch, tmp_path):
    src = tmp_path / "RssFeeds.xml"
    src.write_text("<rssfeeds>CUSTOM</rssfeeds>")
    _point_copies(boot, monkeypatch, tmp_path, {_RSS_DST: src})
    _iptv(boot)._copy_device_files()
    dst = _dst_path(boot, _RSS_DST)
    assert os.path.exists(dst) and "CUSTOM" in open(dst).read()


def test_copy_device_files_copies_iptv_instance_settings(boot, monkeypatch, tmp_path):
    src = tmp_path / "instance-settings-1.xml"
    src.write_text("<settings>INSTANCE</settings>")
    _point_copies(boot, monkeypatch, tmp_path, {_IPTV_INSTANCE_DST: src})
    _iptv(boot)._copy_device_files()
    dst = _dst_path(boot, _IPTV_INSTANCE_DST)
    assert os.path.exists(dst) and "INSTANCE" in open(dst).read()
    # The addon_data/pvr.iptvsimple/ dir must have been created on the fresh box.
    assert os.path.isdir(os.path.dirname(dst))


def test_copy_device_files_creates_channelgroups_dir(boot, monkeypatch, tmp_path):
    """The customTVGroups copy auto-creates the channelGroups/ subdir (absent on a
    fresh box), then lands the file inside it."""
    src = tmp_path / "customTVGroups-Network24.xml"
    src.write_text("<groups>NET24</groups>")
    _point_copies(boot, monkeypatch, tmp_path, {_IPTV_GROUPS_DST: src})
    dst = _dst_path(boot, _IPTV_GROUPS_DST)
    assert not os.path.isdir(os.path.dirname(dst))  # absent before
    _iptv(boot)._copy_device_files()
    assert os.path.isdir(os.path.dirname(dst)), "channelGroups/ must be auto-created"
    assert os.path.exists(dst) and "NET24" in open(dst).read()


def test_copy_device_files_skips_when_source_missing(boot, monkeypatch, tmp_path):
    """Guarded: every source absent -> no copy, no error (the desktop no-op)."""
    _point_copies(boot, monkeypatch, tmp_path, {})
    _iptv(boot)._copy_device_files()
    for special in (_RSS_DST, _IPTV_INSTANCE_DST, _IPTV_GROUPS_DST):
        assert not os.path.exists(_dst_path(boot, special))


def test_copy_device_files_overwrites_existing(boot, monkeypatch, tmp_path):
    """Each copy overwrites a pre-existing destination."""
    seeds = {
        _RSS_DST: ("RssFeeds.xml", "<rssfeeds>CUSTOM</rssfeeds>"),
        _IPTV_INSTANCE_DST: ("instance-settings-1.xml", "<settings>NEW</settings>"),
        _IPTV_GROUPS_DST: ("customTVGroups-Network24.xml", "<groups>NEW</groups>"),
    }
    mapping = {}
    for special, (fname, content) in seeds.items():
        dst = _dst_path(boot, special)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        with open(dst, "w") as f:
            f.write("<x>DEFAULT</x>")
        src = tmp_path / fname
        src.write_text(content)
        mapping[special] = src
    _point_copies(boot, monkeypatch, tmp_path, mapping)
    _iptv(boot)._copy_device_files()
    for special, (_fname, content) in seeds.items():
        got = open(_dst_path(boot, special)).read()
        assert content in got and "DEFAULT" not in got, f"must overwrite {special}"


def test_copy_device_files_never_raises(boot, monkeypatch):
    """Even if xbmcvfs.copy blows up for every entry, the step swallows each error
    and continues (never aborts the rest of setup)."""

    def boom(*a, **k):
        raise RuntimeError("boom")

    monkeypatch.setattr(boot.mod.xbmcvfs, "exists", lambda p: True)
    monkeypatch.setattr(boot.mod.xbmcvfs, "copy", boom)
    _iptv(boot)._copy_device_files()  # must not raise


def test_copy_one_device_file_logs_failure_on_copy_false(boot, monkeypatch, tmp_path):
    """When xbmcvfs.copy reports failure (returns False) for a present source, the
    step logs the failure and returns without raising (the dst is not written)."""
    src = tmp_path / "RssFeeds.xml"
    src.write_text("<rssfeeds>X</rssfeeds>")
    monkeypatch.setattr(boot.mod.xbmcvfs, "copy", lambda s, d: False)
    _iptv(boot)._copy_one_device_file(str(src), _RSS_DST)
    assert not os.path.exists(_dst_path(boot, _RSS_DST))


# --------------------------------------------------------------------------- #
# Instance-settings enforce — group mode + custom-groups file + groups-only.
# --------------------------------------------------------------------------- #
def test_enforce_creates_file_with_keys_when_absent(boot):
    """Fresh box, a groups file present -> the enforce creates instance-settings
    with tvGroupMode=2 + the Network24 file + groups-only true."""
    assert not os.path.exists(_instance_path(boot))
    _make_groups_file(boot)
    _iptv(boot)._ensure_iptv_custom_tv_groups()
    got = _read_instance_settings(boot)
    assert got["tvGroupMode"] == "2"
    assert got["customTvGroupsFile"].endswith("customTVGroups-Network24.xml")
    assert "channelGroups" in got["customTvGroupsFile"]
    assert got["tvChannelGroupsOnly"] == "true"


def test_enforce_patches_copied_file_preserving_others(boot):
    """A copied file with the DEFAULT tvGroupMode=0 + example path gets both keys
    rewritten; unrelated settings (m3uUrl) survive; default flags drop."""
    path = _instance_path(boot)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(
            '<settings version="2">'
            '<setting id="m3uUrl">http://iptv.example/list.m3u</setting>'
            '<setting id="tvGroupMode" default="true">0</setting>'
            '<setting id="customTvGroupsFile" default="true">'
            "special://userdata/addon_data/pvr.iptvsimple/channelGroups/"
            "customTVGroups-example.xml</setting>"
            "</settings>"
        )
    _make_groups_file(boot)
    _iptv(boot)._ensure_iptv_custom_tv_groups()
    got = _read_instance_settings(boot)
    assert got["tvGroupMode"] == "2"
    assert got["customTvGroupsFile"].endswith("customTVGroups-Network24.xml")
    assert got["m3uUrl"] == "http://iptv.example/list.m3u"  # untouched
    root = ET.parse(path).getroot()
    for s in root.findall("setting"):
        if s.get("id") in ("tvGroupMode", "customTvGroupsFile"):
            assert s.get("default") is None


def test_enforce_noop_when_already_custom(boot):
    """Already-correct file -> byte-identical no-op (no rewrite)."""
    path = _instance_path(boot)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    good_file = _iptv(boot).IPTV_CUSTOM_TV_GROUPS_FILE_VALUE
    with open(path, "w") as f:
        f.write(
            '<settings version="2">'
            '<setting id="tvGroupMode">2</setting>'
            f'<setting id="customTvGroupsFile">{good_file}</setting>'
            '<setting id="tvChannelGroupsOnly">true</setting>'
            "</settings>"
        )
    _make_groups_file(boot)
    before = open(path).read()
    _iptv(boot)._ensure_iptv_custom_tv_groups()
    assert open(path).read() == before


def test_enforce_recreates_malformed_file(boot):
    """A malformed instance-settings file is replaced with a valid one, no raise."""
    path = _instance_path(boot)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write("<settings><not-closed>")
    _make_groups_file(boot)
    _iptv(boot)._ensure_iptv_custom_tv_groups()
    got = _read_instance_settings(boot)
    assert got["tvGroupMode"] == "2"


def test_enforce_is_idempotent(boot):
    """Two runs converge — the second changes nothing."""
    _make_groups_file(boot)
    _iptv(boot)._ensure_iptv_custom_tv_groups()
    first = open(_instance_path(boot)).read()
    _iptv(boot)._ensure_iptv_custom_tv_groups()
    assert open(_instance_path(boot)).read() == first


def test_enforce_skipped_without_groups_file(boot):
    """No groups file + no m3u/epg -> NO-OP: never points tvGroupMode=2 at a
    missing file (the no-env IPTV contract; an empty channel list otherwise)."""
    path = _instance_path(boot)
    if os.path.exists(path):
        os.remove(path)
    _iptv(boot)._ensure_iptv_custom_tv_groups()
    assert not os.path.exists(path), "no instance-settings written w/o a groups file"


def test_enforce_never_raises(boot, monkeypatch):
    """Any write failure is swallowed by the outer except (never aborts setup).

    Pass m3u so the gate opens and the body reaches os.makedirs (which booms),
    exercising the defensive except — a no-env call would return at the gate
    before any write."""

    def boom(*a, **k):
        raise RuntimeError("boom")

    monkeypatch.setattr(_iptv(boot).os, "makedirs", boom)
    _iptv(boot)._ensure_iptv_custom_tv_groups(
        {"IPTV_M3U": "http://iptv.example/list"}
    )  # must not raise


# --------------------------------------------------------------------------- #
# Instance-settings from env — generate groups + inject m3u/epg + groups-only.
# (m3u/epg are obviously-fake URLs — no real provider creds.)
# --------------------------------------------------------------------------- #
def test_env_generates_groups_and_injects_m3u_epg(boot):
    _iptv(boot)._ensure_iptv_custom_tv_groups(
        {
            "IPTV_GROUPS": "USA ENTERTAINMENT; USA NEWS/WEATHER; PPV EVENTS",
            "IPTV_M3U": "http://iptv.example:8080/get.php?username=u&password=p",
            "IPTV_EPG": "http://iptv.example:8080/xmltv.php?username=u&password=p",
            "IPTV_GROUPS_ONLY": "true",
        }
    )
    gpath = _dst_path(boot, _iptv(boot).IPTV_CUSTOM_TV_GROUPS_FILE_VALUE)
    gtext = open(gpath).read()
    assert "USA ENTERTAINMENT" in gtext and "PPV EVENTS" in gtext
    got = _read_instance_settings(boot)
    assert got["tvGroupMode"] == "2"
    assert got["tvChannelGroupsOnly"] == "true"
    assert got["m3uUrl"].endswith("password=p") and got["m3uPathType"] == "1"
    assert got["epgUrl"].startswith("http://iptv.example") and got["epgPathType"] == "1"


def test_env_groups_only_false(boot):
    _iptv(boot)._ensure_iptv_custom_tv_groups(
        {"IPTV_GROUPS": "A; B", "IPTV_GROUPS_ONLY": "false"}
    )
    assert _read_instance_settings(boot)["tvChannelGroupsOnly"] == "false"


def test_env_m3u_injected_without_groups(boot):
    """m3u/epg present but NO IPTV_GROUPS / no groups file -> inject the playlist
    source, but DON'T force custom group mode (crit A; m3u/epg decoupled)."""
    _iptv(boot)._ensure_iptv_custom_tv_groups(
        {"IPTV_M3U": "http://h/list?password=x", "IPTV_EPG": "http://h/epg"}
    )
    got = _read_instance_settings(boot)
    assert got["m3uUrl"].endswith("password=x") and got["m3uPathType"] == "1"
    assert got["epgUrl"] == "http://h/epg" and got["epgPathType"] == "1"
    assert got.get("tvGroupMode") != "2"  # no groups file -> no custom mode
    assert "customTvGroupsFile" not in got


def test_env_m3u_epg_never_logged(boot, monkeypatch):
    """Secret playlist URLs must never appear in any log line."""
    logged = []
    monkeypatch.setattr(
        boot.mod.xbmc, "log", lambda msg, *a, **k: logged.append(str(msg))
    )
    _iptv(boot)._ensure_iptv_custom_tv_groups(
        {
            "IPTV_GROUPS": "A",
            "IPTV_M3U": "http://host/get?password=SUPERSECRET123",
            "IPTV_EPG": "http://host/epg?password=SUPERSECRET123",
        }
    )
    blob = "\n".join(logged)
    assert "SUPERSECRET123" not in blob and "http://host/get" not in blob


# --------------------------------------------------------------------------- #
# _set_instance_setting helper — change detection + default-flag drop.
# --------------------------------------------------------------------------- #
def test_set_instance_setting_creates_updates_and_noops(boot):
    set_one = _iptv(boot)._set_instance_setting
    root = ET.Element("settings")
    # create
    assert set_one(root, "k", "v") is True
    # no-op (same value)
    assert set_one(root, "k", "v") is False
    # update
    assert set_one(root, "k", "v2") is True
    assert root.find("setting").text == "v2"


def test_set_instance_setting_drops_default_flag(boot):
    set_one = _iptv(boot)._set_instance_setting
    root = ET.fromstring(
        '<settings><setting id="k" default="true">0</setting></settings>'
    )
    assert set_one(root, "k", "2") is True
    el = root.find("setting")
    assert el.text == "2" and el.get("default") is None


# --------------------------------------------------------------------------- #
# Composed apply_iptv — the layer entry point (copy + enforce together).
# --------------------------------------------------------------------------- #
def test_apply_iptv_writes_instance_and_reports_configured(boot):
    """env with m3u/epg+groups -> apply_iptv writes instance-settings and reports
    ok / not already_done / pvr.iptvsimple configured / needs_restart."""
    res = _iptv(boot).apply_iptv(
        {
            "IPTV_GROUPS": "A; B",
            "IPTV_M3U": "http://iptv.example/get?password=p",
            "IPTV_EPG": "http://iptv.example/epg",
            "IPTV_GROUPS_ONLY": "true",
        }
    )
    assert res.layer == "iptv"
    assert res.ok is True
    assert res.already_done is False
    assert res.installed.get("pvr.iptvsimple") == "configured"
    assert res.failed == {}
    assert res.needs_restart is True
    # And the file landed with the enforced keys.
    got = _read_instance_settings(boot)
    assert got["tvGroupMode"] == "2" and got["m3uPathType"] == "1"


def test_apply_iptv_empty_env_installs_backend_but_writes_no_config(boot):
    """Phase 3a — empty env is NO LONGER a pure no-op: apply_iptv now INSTALLS the
    PVR backend FIRST (pvr.iptvsimple's install moved here from the base ADDONS), so
    on a fresh box even with no env the backend is installed (real work) while the
    CONFIG half is the no-op (no device files / no groups file -> nothing written).

    New semantics:
      * ok=True (the backend installed).
      * installed records pvr.iptvsimple "installed" (NOT empty — the backend landed).
      * already_done=False because a FRESH backend install is real work (already_done
        is True only when the backend was ALREADY installed AND no config was written).
      * no instance-settings file is written (config is the no-op part).
      * a restart is still requested (pvr re-reads settings on restart)."""
    res = _iptv(boot).apply_iptv({})
    assert res.ok is True
    assert res.installed == {"pvr.iptvsimple": "installed"}
    assert res.already_done is False  # fresh backend install IS work
    assert res.needs_restart is True
    assert not os.path.exists(_instance_path(boot)), "config half writes nothing"


def test_apply_iptv_empty_env_already_done_when_backend_preinstalled(boot, monkeypatch):
    """The TRUE empty-env no-op: when pvr.iptvsimple is ALREADY installed (re-entry)
    AND there is no config to write, apply_iptv reports already_done=True. This is
    the no-NEW-work path now that the backend install is part of the layer — pin the
    is_installed short-circuit (no re-install) plus the config no-op together."""
    # Pretend the backend is already installed: the engine's is_installed checks the
    # fake-Kodi 'installed' set via xbmcaddon.Addon, so seed it there.
    boot.state["installed"].add("pvr.iptvsimple")
    # If _install_pvr_backend tried to re-install, this would blow up the count.
    installs = []
    monkeypatch.setattr(
        _iptv(boot), "install_with_deps", lambda *a, **k: installs.append(a) or True
    )
    res = _iptv(boot).apply_iptv({})
    assert installs == [], "already-installed backend must NOT be re-installed"
    assert res.ok is True
    assert res.already_done is True  # backend already there + no config written
    assert res.installed == {"pvr.iptvsimple": "installed"}
    assert not os.path.exists(_instance_path(boot))


def test_apply_iptv_none_env_is_empty(boot):
    """None is treated as the empty env: no crash, the backend installs, no config is
    written (mirrors test_apply_iptv_empty_env_installs_backend_but_writes_no_config
    — None and {} are the same no-config path)."""
    res = _iptv(boot).apply_iptv(None)
    assert res.ok is True
    assert res.installed == {"pvr.iptvsimple": "installed"}
    assert res.already_done is False  # fresh backend install on a no-config env


# --------------------------------------------------------------------------- #
# Phase 3a — _install_pvr_backend (install-or-fail-loud) + apply_iptv's fail path.
#
# The IPTV gate OWNS its own PVR backend now (pvr.iptvsimple's install moved out of
# the base ADDONS). _install_pvr_backend installs it (+ binary inputstream closure)
# from the official repo, no-ops on re-entry, and apply_iptv FAILS LOUD (ok=False,
# failed[pvr.iptvsimple], no instance-settings written) if the backend does not land
# — never silently configuring a missing add-on.
# --------------------------------------------------------------------------- #
def test_install_pvr_backend_installs_when_absent(boot, monkeypatch):
    """When pvr.iptvsimple is NOT installed, _install_pvr_backend drives
    install_with_deps for it against the official repo and reports True."""
    calls = []

    def _iwd(aid, dialog, optional, base, log):
        calls.append((aid, base))
        return True

    monkeypatch.setattr(_iptv(boot), "install_with_deps", _iwd)
    ok = _iptv(boot)._install_pvr_backend(boot.mod.xbmcgui.DialogProgress())
    assert ok is True
    assert calls == [("pvr.iptvsimple", _iptv(boot).OFFICIAL_BASE)], (
        "must install pvr.iptvsimple from the official repo (binary closure)"
    )


def test_install_pvr_backend_noop_when_already_installed(boot, monkeypatch):
    """Re-entry: when the backend is ALREADY installed, _install_pvr_backend
    short-circuits to True WITHOUT calling install_with_deps (no re-install)."""
    boot.state["installed"].add("pvr.iptvsimple")
    calls = []
    monkeypatch.setattr(
        _iptv(boot), "install_with_deps", lambda *a, **k: calls.append(a) or True
    )
    ok = _iptv(boot)._install_pvr_backend(None)
    assert ok is True
    assert calls == [], "an already-installed backend must not be re-installed"


def test_install_pvr_backend_returns_false_on_install_failure(boot, monkeypatch):
    """When install_with_deps reports the backend did NOT land,
    _install_pvr_backend returns False (the loud-fail signal apply_iptv consumes)."""
    monkeypatch.setattr(_iptv(boot), "install_with_deps", lambda *a, **k: False)
    assert _iptv(boot)._install_pvr_backend(None) is False


def test_apply_iptv_fails_loud_when_backend_install_fails(boot, monkeypatch):
    """MANDATORY fail-loud contract: if the PVR backend install FAILS, apply_iptv
    returns ok=False with failed[pvr.iptvsimple] and writes NO instance-settings —
    it must NEVER silently configure a missing backend. The orchestrator checks ok
    BEFORE restarting, so a failed backend never restarts into a half-configured box.

    Drive a real failure: install_with_deps reports False AND the env carries config
    (m3u/epg + groups) that WOULD be written if the fail-guard were broken — so this
    proves the guard, not an already-empty config path."""
    # Backend install fails.
    monkeypatch.setattr(_iptv(boot), "install_with_deps", lambda *a, **k: False)
    # Spy the enforce so we can prove it is NEVER reached on the fail path.
    enforce_calls = []
    monkeypatch.setattr(
        _iptv(boot),
        "_ensure_iptv_custom_tv_groups",
        lambda env=None: enforce_calls.append(env) or True,
    )
    res = _iptv(boot).apply_iptv(
        {
            "IPTV_GROUPS": "A; B",
            "IPTV_M3U": "http://iptv.example/get?password=p",
            "IPTV_EPG": "http://iptv.example/epg",
            "IPTV_GROUPS_ONLY": "true",
        }
    )
    assert res.ok is False, "a failed backend install must make the layer ok=False"
    assert res.failed.get("pvr.iptvsimple") == "install failed"
    assert res.installed == {}, "no add-on may be reported installed on the fail path"
    assert res.already_done is False
    assert res.needs_restart is False, "a failed layer must not request a restart"
    assert enforce_calls == [], (
        "instance-settings enforce must NOT run when the backend install failed "
        "(never configure a missing PVR backend)"
    )
    assert not os.path.exists(_instance_path(boot)), (
        "no instance-settings file may be written on the fail-loud path"
    )


def test_apply_iptv_copies_then_enforces(boot, monkeypatch, tmp_path):
    """The composed layer runs the COPY before the ENFORCE: a device-copied
    customTVGroups file makes the enforce flip to custom mode (proving the copy
    landed first and the enforce saw it)."""
    # Stage a device customTVGroups file that the copy will land into the
    # channelGroups dir the enforce gates on.
    src = tmp_path / "customTVGroups-Network24.xml"
    src.write_text(
        "<customChannelGroups><channelGroupName>X</channelGroupName></customChannelGroups>"
    )
    _point_copies(boot, monkeypatch, tmp_path, {_IPTV_GROUPS_DST: src})
    res = _iptv(boot).apply_iptv({})  # no env m3u/epg — only the copied groups file
    got = _read_instance_settings(boot)
    # Enforce saw the copied groups file -> custom mode enforced.
    assert got["tvGroupMode"] == "2"
    assert res.installed.get("pvr.iptvsimple") == "configured"
    assert res.already_done is False


# --------------------------------------------------------------------------- #
# GAP 1 regression — the pre-existing instance file (the normally-provisioned box).
#
# On a real box the device-copy stages instance-settings-1.xml BEFORE the enforce,
# so the file ALWAYS pre-exists when the enforce runs. The old report used
# `existed_before` and so claimed already_done=True / installed={} even though the
# enforce wrote real config — the OPPOSITE of the truth. apply_iptv now consumes
# the enforce's OWN write/changed return, so a pre-existing-but-stale file is
# reported as configured, and a pre-existing-AND-already-correct file is reported as
# no-new-work (already_done) honestly.
# --------------------------------------------------------------------------- #
def _seed_instance_file(boot, body):
    """Write instance-settings-1.xml at the instance dst (creating its dir),
    simulating the device-copy that stages it BEFORE the enforce."""
    path = _instance_path(boot)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(body)
    return path


# The fully-correct instance file the enforce produces for the standard env below
# (so a re-run must change nothing). Group mode + custom file + groups-only true +
# the m3u/epg playlist source — values mirror the env in the tests that follow.
_STD_M3U = "http://iptv.example/get?password=p"
_STD_EPG = "http://iptv.example/epg"


def _std_env(boot):
    return {
        "IPTV_GROUPS": "A; B",
        "IPTV_M3U": _STD_M3U,
        "IPTV_EPG": _STD_EPG,
        "IPTV_GROUPS_ONLY": "true",
    }


def test_apply_iptv_reports_configured_when_instance_file_preexists(boot):
    """GAP 1: the instance file PRE-EXISTS (device-copied) AND the env supplies
    m3u + a groups file -> the enforce writes real config; apply_iptv must report it
    truthfully (configured / not already_done), NOT the old `existed_before` lie."""
    # Simulate the device-copy staging a STALE instance file before the enforce.
    _seed_instance_file(
        boot,
        '<settings version="2">'
        '<setting id="tvGroupMode" default="true">0</setting>'
        "</settings>",
    )
    assert os.path.exists(_instance_path(boot))  # pre-exists, like a provisioned box

    res = _iptv(boot).apply_iptv(_std_env(boot))

    assert res.installed.get("pvr.iptvsimple") == "configured"
    assert res.already_done is False
    assert "written" in res.detail  # truthful, not "no-op"
    # And the enforce really did rewrite the stale file to custom mode + the source.
    got = _read_instance_settings(boot)
    assert got["tvGroupMode"] == "2"
    assert got["m3uUrl"] == _STD_M3U and got["m3uPathType"] == "1"


def test_apply_iptv_reports_no_new_work_when_instance_file_already_correct(boot):
    """The instance file pre-exists AND is ALREADY fully correct (the env supplies
    the same values) -> the enforce's `if changed:` write-skip fires; apply_iptv
    reports no new work honestly.

    Phase 3a semantics: already_done == "no NEW work this run" = the backend was
    ALREADY installed AND no config was written. The FIRST run installs the backend
    (fresh) + writes config, so already_done=False. The SECOND run finds the backend
    already installed (is_installed short-circuit) AND the config byte-identical
    (write-skip), so already_done=True. ``installed`` still RECORDS the backend
    ("pvr.iptvsimple": "installed") — it is present, just not freshly installed; the
    no-new-work signal lives in already_done, not in an empty installed map."""
    # First run lands the correct config AND installs the backend (also exercises the
    # configured path). already_done False = fresh backend + fresh config.
    first = _iptv(boot).apply_iptv(_std_env(boot))
    assert first.already_done is False
    assert first.installed.get("pvr.iptvsimple") == "configured"
    before = open(_instance_path(boot)).read()

    # Second run: backend already installed (short-circuit), file already correct
    # (write-skip) -> no NEW work.
    res = _iptv(boot).apply_iptv(_std_env(boot))

    assert res.already_done is True
    # The backend is still reported present (it IS installed), but as "installed"
    # not "configured" (no enforce write this run).
    assert res.installed == {"pvr.iptvsimple": "installed"}
    assert "no config written" in res.detail or "already correct" in res.detail
    # Byte-identical: the write-skip guard left the file untouched.
    assert open(_instance_path(boot)).read() == before


def test_apply_iptv_no_new_work_writes_nothing(boot, monkeypatch):
    """GAP 2 probe: on the already-correct re-entry the enforce must WRITE NOTHING
    (pin the `if changed:` write-skip). Count open(...,'w') calls during the second
    apply — the no-op run opens no file for writing."""
    _iptv(boot).apply_iptv(_std_env(boot))  # land correct config

    import builtins

    real_open = builtins.open
    writes = []

    def counting_open(path, mode="r", *a, **k):
        if "w" in mode:
            writes.append(str(path))
        return real_open(path, mode, *a, **k)

    monkeypatch.setattr(builtins, "open", counting_open)
    res = _iptv(boot).apply_iptv(_std_env(boot))  # already correct -> no writes

    instance = _instance_path(boot)
    assert instance not in writes, "no-op re-entry must not rewrite instance-settings"
    assert res.already_done is True


# --------------------------------------------------------------------------- #
# _ensure_iptv_custom_tv_groups now returns the truthful "did config land?" signal.
# (apply_iptv consumes this — it is the fix's load-bearing plumbing.)
# --------------------------------------------------------------------------- #
def test_ensure_returns_true_when_it_writes(boot):
    """The enforce returns True when it actually writes the instance-settings file
    (m3u + groups file present)."""
    _make_groups_file(boot)
    wrote = _iptv(boot)._ensure_iptv_custom_tv_groups(
        {"IPTV_M3U": "http://iptv.example/get?password=p"}
    )
    assert wrote is True


def test_ensure_returns_false_on_gated_noop(boot):
    """No m3u/epg and no groups file -> gated no-op -> returns False (nothing
    written), so apply_iptv reports already_done without lying."""
    path = _instance_path(boot)
    if os.path.exists(path):
        os.remove(path)
    assert _iptv(boot)._ensure_iptv_custom_tv_groups() is False


def test_ensure_returns_false_when_already_correct(boot):
    """An already-correct file -> the `if changed:` write-skip -> returns False
    (no NEW config written), even though the file pre-exists with real config."""
    _make_groups_file(boot)
    assert _iptv(boot)._ensure_iptv_custom_tv_groups() is True  # first write
    assert _iptv(boot)._ensure_iptv_custom_tv_groups() is False  # re-run: no change


def test_ensure_returns_false_on_swallowed_failure(boot, monkeypatch):
    """A swallowed failure (os.makedirs booms past the gate) returns False — the
    enforce never claims it wrote config it didn't."""

    def boom(*a, **k):
        raise RuntimeError("boom")

    monkeypatch.setattr(_iptv(boot).os, "makedirs", boom)
    assert (
        _iptv(boot)._ensure_iptv_custom_tv_groups(
            {"IPTV_M3U": "http://iptv.example/list"}
        )
        is False
    )


# --------------------------------------------------------------------------- #
# Phase 5b·1 — the PVR-disabled config window (instance-settings clobber fix).
#
# The 5a·3 clean-Kodi live run shipped an UNCONFIGURED pvr.iptvsimple: apply_iptv
# ENABLED the backend (instantiating the live PVR client with stock in-memory
# defaults) BEFORE writing instance-settings, and the running client flushed its
# stale defaults back over the write (same class as the Skin.SetBool clobber).
# The fix: disable the backend around the copy+enforce writes, re-enable after
# (in a finally), so fresh clients start FROM the files just written.
# --------------------------------------------------------------------------- #
def _pvr_enable_calls(boot):
    """Ordered [enabled-bool] of every Addons.SetAddonEnabled for pvr.iptvsimple."""
    import json

    out = []
    for raw in boot.state["jsonrpc"]:
        d = json.loads(raw)
        if d.get("method") == "Addons.SetAddonEnabled":
            p = d["params"]
            if p.get("addonid") == "pvr.iptvsimple":
                out.append(bool(p.get("enabled", True)))
    return out


def test_apply_iptv_writes_config_inside_pvr_disabled_window(boot, monkeypatch):
    """THE BUG-1 FIX, pinned: apply_iptv must run BOTH file-writing halves (the
    device-copy AND the instance-settings enforce) while pvr.iptvsimple is
    DISABLED, then re-enable it. MUTATION: dropping the pause (or moving the
    enforce outside the window) flips the observed disabled-state to False; the
    pvr enable sequence must be exactly install-enable -> pause-disable ->
    resume-enable."""
    iptv = _iptv(boot)
    seen = {}
    real_enforce = iptv._ensure_iptv_custom_tv_groups
    real_copy = iptv._copy_device_files

    def enforce_probe(env):
        seen["disabled_during_enforce"] = "pvr.iptvsimple" in boot.state["disabled"]
        return real_enforce(env)

    def copy_probe():
        seen["disabled_during_copy"] = "pvr.iptvsimple" in boot.state["disabled"]
        return real_copy()

    monkeypatch.setattr(iptv, "_ensure_iptv_custom_tv_groups", enforce_probe)
    monkeypatch.setattr(iptv, "_copy_device_files", copy_probe)
    res = iptv.apply_iptv({"IPTV_M3U": "http://iptv.example/get?password=p"})
    assert res.ok is True
    assert seen["disabled_during_copy"] is True, "copy must run with pvr DISABLED"
    assert seen["disabled_during_enforce"] is True, (
        "enforce must run with pvr DISABLED"
    )
    assert "pvr.iptvsimple" not in boot.state["disabled"], "pvr must end RE-ENABLED"
    assert _pvr_enable_calls(boot) == [True, False, True], (
        "expected install-enable, pause-disable, resume-enable"
    )


def test_apply_iptv_reenables_pvr_even_if_enforce_raises(boot, monkeypatch):
    """The resume is in a finally: even an (out-of-contract) raising enforce must
    not leave the backend disabled — a disabled pvr is a broken box."""
    import pytest

    iptv = _iptv(boot)

    def boom(env):
        raise RuntimeError("boom")

    monkeypatch.setattr(iptv, "_ensure_iptv_custom_tv_groups", boom)
    with pytest.raises(RuntimeError):
        iptv.apply_iptv({"IPTV_M3U": "http://iptv.example/x"})
    assert "pvr.iptvsimple" not in boot.state["disabled"], "finally must re-enable"
    assert _pvr_enable_calls(boot)[-1] is True


def test_pause_pvr_noops_when_backend_missing(boot):
    """No pvr.iptvsimple installed -> the pause is a no-op returning False (no
    SetAddonEnabled at all) — _configure_box on a pvr-less box pauses nothing."""
    assert _iptv(boot)._pause_pvr_for_config() is False
    assert _pvr_enable_calls(boot) == []


def test_pause_and_resume_failures_are_swallowed(boot, monkeypatch):
    """A failing disable returns False (the write still proceeds — a clobber risk
    beats aborting setup); a failing enable is logged, never raised (the resume
    runs in a finally)."""
    iptv = _iptv(boot)
    boot.state["installed"].add("pvr.iptvsimple")

    def boom(aid):
        raise RuntimeError("boom")

    monkeypatch.setattr(iptv, "disable", boom)
    assert iptv._pause_pvr_for_config() is False
    monkeypatch.setattr(iptv, "enable", boom)
    iptv._resume_pvr_after_config()  # must not raise


# --------------------------------------------------------------------------- #
# Phase 5b·1 — multi-provider env (IPTV_<N>_*) -> one pvr instance per provider.
# (All provider values are obviously-fake — no real creds anywhere here.)
# --------------------------------------------------------------------------- #
def _instance_path_n(boot, n):
    return _dst_path(boot, _iptv(boot)._instance_settings_special(n))


def _read_instance_n(boot, n):
    root = ET.parse(_instance_path_n(boot, n)).getroot()
    return {s.get("id"): (s.text or "") for s in root.findall("setting")}


def test_group_source_extracts_source_side_of_grammar(boot):
    """The groups grammar is `SOURCE > Display Label | sort`. pvr.iptvsimple
    matches <channelGroupName> against the playlist's group-title values — the
    SOURCE side — so that is what the in-Kodi half must emit. Display relabel and
    the sort directive are host-side build work (Phase 5b step 2)."""
    g = _iptv(boot)._group_source
    assert g("USA ENTERTAINMENT > US Entertainment | sort") == "USA ENTERTAINMENT"
    assert g("PPV EVENTS > PPV Events") == "PPV EVENTS"
    assert g("PPV EVENTS | sort") == "PPV EVENTS"
    assert g("USA ENTERTAINMENT") == "USA ENTERTAINMENT"
    assert g("  padded  >  X ") == "padded"


def test_iptv_providers_numbered_parsing_and_mode_inference(boot):
    """Numbered blocks: one provider per N (sorted, gaps preserved — the env N is
    the instance id); mode = explicit IPTV_<N>_MODE, else xtream iff PORTAL with
    no M3U, else m3u."""
    ps = _iptv(boot)._iptv_providers(
        {
            "IPTV_3_NAME": "Other One",
            "IPTV_3_M3U": "http://h/3.m3u",
            "IPTV_1_NAME": "Network 24",
            "IPTV_1_MODE": "m3u",
            "IPTV_1_M3U": "http://h/1.m3u",
            "IPTV_2_NAME": "Streamvision",
            "IPTV_2_MODE": "xtream",
            "IPTV_2_PORTAL": "http://portal.example",
            "IPTV_5_PORTAL": "http://p5.example",  # no MODE, no M3U -> xtream
        }
    )
    assert [p["n"] for p in ps] == [1, 2, 3, 5]
    assert [p["mode"] for p in ps] == ["m3u", "xtream", "m3u", "xtream"]
    assert all(p["legacy"] is False for p in ps)
    assert ps[0]["name"] == "Network 24" and ps[0]["m3u"] == "http://h/1.m3u"


def test_iptv_providers_legacy_fallback(boot):
    """With NO numbered keys the legacy single-instance shape maps to ONE
    legacy=True provider 1 — and an EMPTY env still yields it (the legacy enforce
    must run its gated no-op probe so a device-copied groups file keeps working)."""
    ps = _iptv(boot)._iptv_providers({"IPTV_M3U": "http://h/x", "IPTV_GROUPS": "A"})
    assert len(ps) == 1 and ps[0]["legacy"] is True and ps[0]["n"] == 1
    assert ps[0]["m3u"] == "http://h/x" and ps[0]["groups"] == "A"
    empty = _iptv(boot)._iptv_providers({})
    assert len(empty) == 1 and empty[0]["legacy"] is True


def test_multi_provider_env_writes_one_instance_per_provider(boot):
    """Two m3u providers (with a gap: N=1 and N=3) -> instance-settings-1.xml AND
    instance-settings-3.xml, each with its OWN m3u/epg, its OWN name-derived
    customTVGroups file, custom group mode, and the multi-instance identity keys
    (name + enabled) that make a created file real to Kodi's instance scanner."""
    wrote = _iptv(boot)._ensure_iptv_custom_tv_groups(
        {
            "IPTV_1_NAME": "Network 24",
            "IPTV_1_M3U": "http://iptv.example/1.m3u?password=p1",
            "IPTV_1_EPG": "http://iptv.example/1.xml",
            "IPTV_1_GROUPS": "USA ENTERTAINMENT > US Entertainment | sort",
            "IPTV_3_NAME": "Other One",
            "IPTV_3_M3U": "http://iptv.example/3.m3u?password=p3",
            "IPTV_3_GROUPS": "SPORTS",
            "IPTV_3_GROUPS_ONLY": "false",
        }
    )
    assert wrote is True
    one = _read_instance_n(boot, 1)
    three = _read_instance_n(boot, 3)
    assert one["m3uUrl"].endswith("password=p1") and one["m3uPathType"] == "1"
    assert one["epgUrl"] == "http://iptv.example/1.xml"
    assert three["m3uUrl"].endswith("password=p3")
    # Identity keys (numbered providers only).
    assert one["kodi_addon_instance_name"] == "Network 24"
    assert one["kodi_addon_instance_enabled"] == "true"
    assert three["kodi_addon_instance_name"] == "Other One"
    # Per-provider groups files, name-derived; group mode enforced per instance.
    assert one["tvGroupMode"] == "2" and three["tvGroupMode"] == "2"
    assert one["customTvGroupsFile"].endswith("customTVGroups-Network24.xml")
    assert three["customTvGroupsFile"].endswith("customTVGroups-OtherOne.xml")
    assert one["tvChannelGroupsOnly"] == "true"
    assert three["tvChannelGroupsOnly"] == "false"
    g1 = open(_dst_path(boot, one["customTvGroupsFile"])).read()
    g3 = open(_dst_path(boot, three["customTvGroupsFile"])).read()
    assert "USA ENTERTAINMENT" in g1 and "US Entertainment" not in g1
    assert "sort" not in g1, "the sort directive is host-side work, never emitted"
    assert "SPORTS" in g3


def test_xtream_provider_is_skipped_honestly_without_secret_leak(boot, monkeypatch):
    """An xtream-mode provider is SKIPPED in-Kodi (pvr.iptvsimple Omega has no
    native Xtream connection mode — its only XTREAM schema reference is a catchup
    enum) with an honest log; its portal/user/pass never reach any log line or
    file; the m3u provider still configures, so the enforce returns True."""
    logged = []
    monkeypatch.setattr(
        boot.mod.xbmc, "log", lambda msg, *a, **k: logged.append(str(msg))
    )
    wrote = _iptv(boot)._ensure_iptv_custom_tv_groups(
        {
            "IPTV_1_NAME": "Network 24",
            "IPTV_1_M3U": "http://iptv.example/1.m3u?password=M3USECRET",
            "IPTV_2_NAME": "Streamvision",
            "IPTV_2_MODE": "xtream",
            "IPTV_2_PORTAL": "http://portal.example:8080/PORTALSECRET",
            "IPTV_2_USER": "USERSECRET",
            "IPTV_2_PASS": "PASSSECRET",
            "IPTV_2_EPG": "http://portal.example/xmltv.php?password=PASSSECRET",
            "IPTV_2_GROUPS": "58 > US Entertainment | sort",
        }
    )
    assert wrote is True, "the m3u provider must still configure"
    assert os.path.exists(_instance_path_n(boot, 1))
    assert not os.path.exists(_instance_path_n(boot, 2)), (
        "an xtream provider must write NO instance file (host-side build pending)"
    )
    blob = "\n".join(logged)
    assert "xtream" in blob.lower(), "the skip must be logged honestly"
    for secret in ("PORTALSECRET", "USERSECRET", "PASSSECRET", "M3USECRET"):
        assert secret not in blob, f"secret value {secret!r} leaked into the log"


def test_legacy_env_with_name_keeps_legacy_paths_and_no_identity_keys(boot):
    """Back-compat: the LEGACY single-instance shape keeps the monolith's exact
    file paths even when IPTV_NAME is present (no name-derived groups path) and
    never writes the instance-identity keys — instance-settings-1.xml stays
    byte-compatible with what every shipped box already has."""
    _iptv(boot)._ensure_iptv_custom_tv_groups(
        {
            "IPTV_NAME": "My Provider",
            "IPTV_M3U": "http://iptv.example/x?password=p",
            "IPTV_GROUPS": "A; B",
        }
    )
    got = _read_instance_settings(boot)
    assert got["customTvGroupsFile"] == (
        _iptv(boot).IPTV_CUSTOM_TV_GROUPS_FILE_VALUE
    ), "legacy shape must keep the historical customTVGroups-Network24.xml path"
    assert "kodi_addon_instance_name" not in got
    assert "kodi_addon_instance_enabled" not in got


def test_multi_provider_one_bad_provider_does_not_block_others(boot, monkeypatch):
    """A failing provider is logged and skipped; the OTHERS still apply and the
    aggregate return stays truthful (True because provider 3 wrote)."""
    iptv = _iptv(boot)
    real = iptv._ensure_iptv_instance

    def flaky(provider):
        if provider["n"] == 1:
            raise RuntimeError("boom")
        return real(provider)

    monkeypatch.setattr(iptv, "_ensure_iptv_instance", flaky)
    wrote = iptv._ensure_iptv_custom_tv_groups(
        {
            "IPTV_1_M3U": "http://iptv.example/1.m3u",
            "IPTV_3_M3U": "http://iptv.example/3.m3u",
        }
    )
    assert wrote is True
    assert not os.path.exists(_instance_path_n(boot, 1))
    assert os.path.exists(_instance_path_n(boot, 3))


def test_multi_provider_secrets_never_logged(boot, monkeypatch):
    """The numbered-shape twin of the legacy never-logged test: no provider URL
    value may appear in any log line."""
    logged = []
    monkeypatch.setattr(
        boot.mod.xbmc, "log", lambda msg, *a, **k: logged.append(str(msg))
    )
    _iptv(boot)._ensure_iptv_custom_tv_groups(
        {
            "IPTV_1_GROUPS": "A",
            "IPTV_1_M3U": "http://host/get?password=SUPERSECRET123",
            "IPTV_1_EPG": "http://host/epg?password=SUPERSECRET123",
        }
    )
    blob = "\n".join(logged)
    assert "SUPERSECRET123" not in blob and "http://host/get" not in blob


def test_apply_iptv_multi_provider_reports_configured(boot):
    """apply_iptv with a numbered multi-provider env installs the backend and
    reports pvr.iptvsimple 'configured' (the enforce wrote real config)."""
    res = _iptv(boot).apply_iptv(
        {
            "IPTV_1_NAME": "Network 24",
            "IPTV_1_M3U": "http://iptv.example/1.m3u?password=p",
            "IPTV_1_GROUPS": "USA ENTERTAINMENT > US Entertainment | sort",
        }
    )
    assert res.ok is True
    assert res.installed.get("pvr.iptvsimple") == "configured"
    assert _read_instance_n(boot, 1)["tvGroupMode"] == "2"


def test_ensure_outer_swallow_when_provider_parsing_fails(boot, monkeypatch):
    """The OUTER defensive except (distinct from the per-provider one): if the
    provider PARSING itself raises, the enforce still returns False and never
    raises — the never-abort-setup contract holds end to end."""

    def boom(env):
        raise RuntimeError("boom")

    monkeypatch.setattr(_iptv(boot), "_iptv_providers", boom)
    assert (
        _iptv(boot)._ensure_iptv_custom_tv_groups({"IPTV_M3U": "http://h/x"}) is False
    )
