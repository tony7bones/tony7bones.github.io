"""Unit tests for the Foundation layer (Phase 2b).

``tony7bones.setup.foundation.apply_foundation`` is the Layer 0 entry point: it
installs the File-Manager sources (incl. the mini's KodiShare/KodiBackup NFS
shares and our own proxy source), the branded-look weather provider
(weather.multi) + env-driven locations, the RSS news ticker (core setting +
env-driven RssFeeds.xml), and the on-screen-keyboard autocomplete QoL utility
(script.module.autocompletion). It installs NO skin — the Estuary MOD V2 skin
closure + the home-menu trim live in the Skin layer instead
(``tony7bones.setup.skin`` — see ``test_setup_skin.py``), split out because the
skin is curatorial branding, not a Foundation prerequisite.

These tests drive ``apply_foundation`` DIRECTLY against the shared fake-Kodi
``boot`` fixture (conftest.py) — the same real engine the bootstrap suite uses,
reached via ``boot.mod._foundation`` (the foundation module the bootstrap
imports under the fake Kodi). This is the behaviour-preserving oracle for the
move: the foundation bodies must land the SAME state the monolith's inline
``_add_file_sources`` did. The whole-``run()`` ordering is pinned separately by
the modular_setup characterization snapshot; here we pin the layer in
isolation. Because this layer has ZERO skin dependency, none of these tests
need to stub the skin closure (unlike the Skin layer's own tests).
"""

from __future__ import annotations

from xml.etree import ElementTree as ET


def _foundation(boot):
    """The foundation module bound under the fake Kodi (via the bootstrap)."""
    return boot.mod._foundation


def _settings_set(boot):
    """{setting_id: value} from captured Settings.SetSettingValue JSON-RPC calls."""
    import json

    out = {}
    for s in boot.state["jsonrpc"]:
        try:
            d = json.loads(s)
        except ValueError:
            continue
        if d.get("method") == "Settings.SetSettingValue":
            out[d["params"]["setting"]] = d["params"]["value"]
    return out


def _files_sources(boot):
    root = ET.parse(boot.sources_xml).getroot()
    files = root.find("files")
    assert files is not None, "<files> section must exist"
    return [(s.findtext("name"), s.findtext("path")) for s in files.findall("source")]


# --------------------------------------------------------------------------- #
# apply_foundation — the LayerResult contract
# --------------------------------------------------------------------------- #
def test_apply_foundation_returns_foundation_layerresult_on_success(boot):
    """ok is always True (content-free, best-effort config with no user-cancelable
    step), needs_restart REQUESTED, weather.multi + autocomplete recorded
    installed, layer tag is 'foundation'. No skin dependency at all — the real
    engine resolves weather.multi/autocomplete from the fake index directly."""
    fnd = _foundation(boot)
    res = fnd.apply_foundation({}, dialog=None, log=boot.mod._log)

    assert res.layer == "foundation"
    assert res.ok is True
    assert res.needs_restart is True
    assert res.needs_skin_activation is False, (
        "Foundation must NOT request skin activation — that is the Skin layer's job"
    )
    assert res.installed.get("weather.multi") == "installed"
    assert res.installed.get("script.module.autocompletion") == "installed"
    assert res.failed == {}


def test_apply_foundation_does_not_touch_skin_at_all(boot):
    """Foundation never sets lookandfeel.skin and never installs skin.estuary.modv2
    — the skin closure lives in the Skin layer now."""
    fnd = _foundation(boot)
    fnd.apply_foundation({}, dialog=None, log=boot.mod._log)
    assert "lookandfeel.skin" not in _settings_set(boot)
    assert "skin.estuary.modv2" not in boot.state["installed"]


# --------------------------------------------------------------------------- #
# File-Manager sources
# --------------------------------------------------------------------------- #
def test_apply_foundation_writes_file_sources(boot):
    """The three File-Manager sources land in sources.xml (the lifted
    _add_file_sources body)."""
    fnd = _foundation(boot)
    assert not boot.sources_xml.exists()
    fnd.apply_foundation({}, dialog=None, log=boot.mod._log)
    entries = dict(_files_sources(boot))
    assert entries["special://home"] == "special://home"
    assert entries["special://kodi"] == "/storage/emulated/0/kodi/"
    assert entries[".tony.7.bones"] == "https://tony7bones.github.io/"


# --------------------------------------------------------------------------- #
# Injection: run() forwards the bootstrap's monkeypatchable shim
# --------------------------------------------------------------------------- #
def test_apply_foundation_uses_injected_add_file_sources(boot):
    """When run() injects its own step shim, apply_foundation uses THAT (not its
    module-default body) — the behaviour-preservation hook that keeps
    boot.mod-level monkeypatches effective for the run()-driven path."""
    fnd = _foundation(boot)
    marker = {"sources": False}
    res = fnd.apply_foundation(
        {},
        dialog=None,
        log=boot.mod._log,
        add_file_sources=lambda box_env: marker.__setitem__("sources", True),
    )
    assert marker == {"sources": True}
    assert res.ok is True


# --------------------------------------------------------------------------- #
# Weather into Foundation (weather-into-Foundation change). The weather provider
# install + env-driven location config MOVED out of the Add-ons layer into
# Foundation — weather is part of the branded look (the MOD V2 skin renders a
# weather readout + a Weather home-menu item, once the Skin layer's box is
# active). The unit tests for the lifted weather helpers moved here with it.
# --------------------------------------------------------------------------- #
def _weather_settings(boot):
    """Multi Weather settings.xml as {id: text} (or {} if unwritten)."""
    import os
    from xml.etree import ElementTree as ET

    path = _foundation(boot)._weather_multi_settings_path()
    if not os.path.exists(path):
        return {}
    root = ET.parse(path).getroot()
    return {s.get("id"): (s.text or "") for s in root.findall("setting")}


def test_apply_weather_resolves_locations_and_keys(boot, monkeypatch):
    """Up to N resolved locations land as loc1..N (+ unused slots cleared), and the
    Weatherbit / OWM keys enable the optional upgrade layers."""
    fnd = _foundation(boot)
    locs = {
        "Sacramento": {
            "name": "Sacramento, CA, US",
            "url": "us/ca/sacramento",
            "lat": "38.5",
            "lon": "-121.4",
        },
        "Reno": {
            "name": "Reno, NV, US",
            "url": "us/nv/reno",
            "lat": "39.5",
            "lon": "-119.8",
        },
    }
    monkeypatch.setattr(
        fnd,
        "_resolve_weather_location",
        lambda q, **k: next((v for n, v in locs.items() if n in q), None),
    )
    fnd._apply_weather_from_env(
        {
            "WEATHER_LOCATIONS": "Sacramento, CA; Reno, NV",
            "WEATHERBIT_API_KEY": "WBITKEY",
            "OWM_API_KEY": "OWMKEY",
        }
    )
    got = _weather_settings(boot)
    assert got["loc1_url"] == "us/ca/sacramento"
    assert got["loc2_url"] == "us/nv/reno"
    assert got["loc3_url"] == ""  # unused slot cleared, never stale
    assert got["WAdd"] == "true" and got["API"] == "WBITKEY"
    assert got["WMaps"] == "true" and got["MAPAPI"] == "OWMKEY"


def test_apply_weather_falls_back_to_sacramento_never_empty(boot, monkeypatch):
    """No resolvable env locations -> the keyless Sacramento default, NEVER an empty
    loc1_url (the load-bearing fetch field)."""
    fnd = _foundation(boot)
    monkeypatch.setattr(fnd, "_resolve_weather_location", lambda q, **k: None)
    fnd._apply_weather_from_env({"WEATHER_LOCATIONS": "Nowhere, ZZ"})
    got = _weather_settings(boot)
    assert got["loc1_url"] == "us/ca/sacramento" and got["loc1_url"]
    assert "WAdd" not in got  # no keys -> no upgrade layer


def test_apply_weather_skips_unresolvable_keeps_resolved_no_gap(boot, monkeypatch):
    """An unresolvable location is skipped; the resolved one becomes loc1 (no gap)."""
    fnd = _foundation(boot)
    monkeypatch.setattr(
        fnd,
        "_resolve_weather_location",
        lambda q, **k: (
            {"name": "Reno, NV, US", "url": "us/nv/reno", "lat": "39", "lon": "-119"}
            if "Reno" in q
            else None
        ),
    )
    fnd._apply_weather_from_env({"WEATHER_LOCATIONS": "Badtown; Reno, NV"})
    got = _weather_settings(boot)
    assert got["loc1_url"] == "us/nv/reno"
    assert got.get("loc2_url", "") == ""


def test_apply_weather_never_raises(boot, monkeypatch):
    """Defensive: any failure inside the writer is swallowed (never aborts setup)."""
    fnd = _foundation(boot)

    def _boom(*a, **k):
        raise RuntimeError("boom")

    monkeypatch.setattr(fnd, "_set_weather_settings", _boom)
    fnd._apply_weather_from_env({"WEATHER_LOCATIONS": ""})  # must not raise


def test_resolve_weather_location_returns_none_on_bad_response(boot):
    """The conftest urlopen fake returns empty bytes for the Yahoo search-assist
    endpoint, so the JSON parse fails on every retry -> None (the caller then falls
    back to the Sacramento default). Exercises the real network/parse body."""
    fnd = _foundation(boot)
    assert fnd._resolve_weather_location("Sacramento, CA") is None


def test_resolve_weather_location_parses_suggestions(boot, monkeypatch):
    """A well-formed search-assist response is parsed into {name,url,lat,lon} in the
    add-on's own field shape (name 'Town, Region, Country'; url 'country/region/town')."""
    import json as _json

    fnd = _foundation(boot)
    payload = {
        "suggestions": [
            {
                "location": {
                    "town": {"name": "Reno", "latitude": 39.5, "longitude": -119.8},
                    "region": {"code": "NV"},
                    "country": {"code": "US"},
                }
            }
        ]
    }

    class _Resp:
        def read(self):
            return _json.dumps(payload).encode("utf-8")

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr("urllib.request.urlopen", lambda req, timeout=None: _Resp())
    loc = fnd._resolve_weather_location("Reno, NV")
    assert loc == {
        "name": "Reno, NV, US",
        "url": "us/nv/reno",
        "lat": "39.5",
        "lon": "-119.8",
    }


def test_set_weather_settings_recreates_malformed_file(boot):
    """A malformed Multi Weather settings.xml is replaced with a valid tree (the
    ET.ParseError recovery branch) while still writing the requested settings."""
    import os

    fnd = _foundation(boot)
    path = fnd._weather_multi_settings_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write("<<not xml>>")
    fnd._set_weather_settings({"loc1_url": "us/ca/sacramento"})
    got = _weather_settings(boot)
    assert got["loc1_url"] == "us/ca/sacramento"


def test_set_weather_location_default_is_sacramento(boot):
    """The keyless fallback writes the Sacramento default location."""
    fnd = _foundation(boot)
    fnd._set_weather_location()
    got = _weather_settings(boot)
    assert got["loc1_url"] == "us/ca/sacramento"
    assert "Sacramento" in got["loc1_name"]


def test_apply_foundation_installs_and_configures_weather(boot):
    """apply_foundation installs weather.multi + sets the core provider + writes the
    keyless default location — weather is part of Foundation's branded-look config.
    No skin stubbing needed: weather.multi resolves from the fake index directly."""
    res = boot.mod._foundation.apply_foundation({}, dialog=None, log=boot.mod._log)
    assert "weather.multi" in boot.state["installed"], (
        "Foundation must install weather.multi"
    )
    assert res.installed.get("weather.multi") == "installed"
    assert _settings_set(boot).get("weather.addon") == "weather.multi"
    assert _weather_settings(boot)["loc1_url"] == "us/ca/sacramento"


def test_apply_foundation_weather_install_failure_is_non_fatal(boot, monkeypatch):
    """A weather install failure does NOT abort Foundation — it is recorded in
    failed{} but the layer remains ok (Foundation has no cancel concept at all)."""

    def _boom(addon_id, *a, **k):
        if addon_id == "weather.multi":
            raise RuntimeError("weather boom")
        return True

    monkeypatch.setattr(boot.mod._foundation, "install_with_deps", _boom)
    res = boot.mod._foundation.apply_foundation({}, dialog=None, log=boot.mod._log)
    assert res.ok is True, "a weather failure must not flip the layer"
    assert res.failed.get("weather.multi") == "weather install failed"


# --------------------------------------------------------------------------- #
# RSS news ticker — env-driven, MOVED here from the Add-ons layer (RSS is
# branded-look CONFIG, not content, same as weather). _apply_rss_from_env is a
# direct lift of the old addons.py body; _apply_rss composes the core-setting
# toggle + the env writer, mirroring _apply_weather's shape.
# --------------------------------------------------------------------------- #
def _rss_path(boot):
    return boot.mod.xbmcvfs.translatePath("special://home/userdata/RssFeeds.xml")


def test_apply_rss_writes_feeds_with_interval(boot):
    """RSS_FEEDS -> userdata/RssFeeds.xml with each feed at the RSS_INTERVAL."""
    fnd = _foundation(boot)
    fnd._apply_rss_from_env(
        {"RSS_FEEDS": "http://a/feed; http://b/feed", "RSS_INTERVAL": "45"}
    )
    feeds = ET.parse(_rss_path(boot)).getroot().findall("set/feed")
    assert [f.text for f in feeds] == ["http://a/feed", "http://b/feed"]
    assert all(f.get("updateinterval") == "45" for f in feeds)


def test_apply_rss_noop_when_absent(boot):
    """No RSS_FEEDS -> no write (a device-copied file / the Kodi default stands)."""
    import os

    fnd = _foundation(boot)
    fnd._apply_rss_from_env({})
    assert not os.path.exists(_rss_path(boot))


def test_apply_rss_default_interval_is_30(boot):
    """Absent RSS_INTERVAL defaults to 30 (the monolith's default)."""
    fnd = _foundation(boot)
    fnd._apply_rss_from_env({"RSS_FEEDS": "http://a/feed"})
    feeds = ET.parse(_rss_path(boot)).getroot().findall("set/feed")
    assert feeds[0].get("updateinterval") == "30"


def test_apply_rss_never_raises(boot, monkeypatch):
    """Defensive: a write failure is swallowed (never aborts the rest of setup)."""
    import os

    fnd = _foundation(boot)

    def _boom(*a, **k):
        raise OSError("disk full")

    monkeypatch.setattr(fnd.os, "makedirs", _boom)
    fnd._apply_rss_from_env({"RSS_FEEDS": "http://a/feed"})  # must not raise
    assert not os.path.exists(_rss_path(boot))


def test_set_setting_emits_jsonrpc_and_reports_ok(boot):
    """_set_setting sends a Settings.SetSettingValue JSON-RPC and returns True on a
    `"result":true` reply (the fake jsonrpc returns `{}` -> False; patch a true
    reply to exercise the OK branch)."""
    fnd = _foundation(boot)
    # Default fake jsonrpc returns "{}" -> no '"result":true' -> False.
    assert fnd._set_setting("lookandfeel.enablerssfeeds", True) is False
    assert _settings_set(boot).get("lookandfeel.enablerssfeeds") is True


def test_set_setting_true_reply_is_ok(boot, monkeypatch):
    """A `"result":true` JSON-RPC reply makes _set_setting return True."""
    fnd = _foundation(boot)
    monkeypatch.setattr(fnd.xbmc, "executeJSONRPC", lambda s: '{"result":true}')
    assert fnd._set_setting("lookandfeel.enablerssfeeds", True) is True


def test_apply_foundation_sets_rss_core_setting_and_writes_feeds(boot):
    """apply_foundation emits the RSS-enable core setting (lookandfeel.enablerssfeeds
    -> True) and writes the env-driven RSS feeds — RSS moved here from the Add-ons
    layer alongside weather (both are branded-look config, not content)."""
    import os

    fnd = _foundation(boot)
    fnd.apply_foundation({"RSS_FEEDS": "http://a/feed"}, dialog=None, log=boot.mod._log)
    s = _settings_set(boot)
    assert s.get(fnd.RSS_ENABLE_SETTING) is True
    assert fnd.RSS_ENABLE_SETTING == "lookandfeel.enablerssfeeds"
    assert os.path.exists(_rss_path(boot))


# --------------------------------------------------------------------------- #
# script.module.autocompletion — the on-screen-keyboard autocomplete QoL utility,
# installed by Foundation from the official repo (NOT content).
# --------------------------------------------------------------------------- #
def test_apply_foundation_installs_autocomplete(boot):
    """Foundation installs script.module.autocompletion — the keyboard autocomplete
    QoL utility (helps search / IPTV portal+login typing). MUTATION: if Foundation
    stops installing it (the _install_autocomplete call dropped), it is absent from
    installed and this fails. No skin stubbing needed: it resolves from the fake
    index directly."""
    res = boot.mod._foundation.apply_foundation({}, dialog=None, log=boot.mod._log)
    assert boot.mod._foundation.AUTOCOMPLETE_ID == "script.module.autocompletion"
    assert "script.module.autocompletion" in boot.state["installed"], (
        "Foundation must install the keyboard autocomplete utility"
    )
    assert res.installed.get("script.module.autocompletion") == "installed", (
        "the Foundation LayerResult must record autocomplete installed"
    )


def test_apply_foundation_autocomplete_from_official_repo(boot, monkeypatch):
    """The autocomplete install resolves from the OFFICIAL Kodi repo (official base),
    via install_with_deps — proving it is fetched from repository.xbmc.org, not our
    proxy/third-party repos."""
    calls = []

    def _iwd(addon_id, dialog, extra_bases, official_base, log):
        calls.append((addon_id, official_base))
        boot.state["installed"].add(addon_id)
        return True

    monkeypatch.setattr(boot.mod._foundation, "install_with_deps", _iwd)
    boot.mod._foundation.apply_foundation({}, dialog=None, log=boot.mod._log)
    ac = [c for c in calls if c[0] == "script.module.autocompletion"]
    assert ac, "autocomplete must be installed via install_with_deps"
    assert ac[0][1] == boot.mod._foundation.OFFICIAL_BASE, (
        "autocomplete must resolve from the official Kodi repo"
    )


def test_apply_foundation_autocomplete_failure_is_non_fatal(boot, monkeypatch):
    """An autocomplete install failure does NOT abort Foundation — it is recorded
    in failed{} but the layer remains ok."""

    def _boom(addon_id, *a, **k):
        if addon_id == "script.module.autocompletion":
            raise RuntimeError("autocomplete boom")
        return True

    monkeypatch.setattr(boot.mod._foundation, "install_with_deps", _boom)
    res = boot.mod._foundation.apply_foundation({}, dialog=None, log=boot.mod._log)
    assert res.ok is True, "an autocomplete failure must not flip the layer"
    assert res.failed.get("script.module.autocompletion") == (
        "autocomplete install failed"
    )


def test_apply_foundation_runs_weather_rss_autocomplete_in_order(boot, monkeypatch):
    """Pins the internal call order of the three config/install steps: weather,
    then RSS, then autocomplete — the only thing enforcing this order is
    otherwise the whole-run golden snapshot, which a future reorder would only
    break if someone diffs it by eye."""
    fnd = _foundation(boot)
    order = []
    monkeypatch.setattr(
        fnd, "_apply_weather", lambda *a, **k: order.append("weather") or True
    )
    monkeypatch.setattr(fnd, "_apply_rss", lambda *a, **k: order.append("rss") or True)
    monkeypatch.setattr(
        fnd, "_install_autocomplete", lambda *a, **k: order.append("autocomplete")
    )
    fnd.apply_foundation({}, dialog=None, log=boot.mod._log)
    assert order == ["weather", "rss", "autocomplete"]


# --------------------------------------------------------------------------- #
# The mini's NFS shares — port-free by construction (plan Part 1, section 3.1).
# --------------------------------------------------------------------------- #
def test_nfs_url_builds_port_free(boot):
    """_nfs_url(host, path) never emits a port, whatever the host looks like."""
    fnd = _foundation(boot)
    assert fnd._nfs_url("192.168.7.2", "Users/moquette/Kodi/Share/") == (
        "nfs://192.168.7.2/Users/moquette/Kodi/Share/"
    )


def test_nfs_url_sanitizes_existing_port(boot):
    """_nfs_url(url) strips a :<port> from an EXISTING nfs:// URL — the exact
    :2049 class that broke VfsCopyError writes when hand-typed."""
    fnd = _foundation(boot)
    assert fnd._nfs_url("nfs://192.168.7.2:2049/Users/moquette/Kodi/Backup/") == (
        "nfs://192.168.7.2/Users/moquette/Kodi/Backup/"
    )
    # no port present: passthrough, unchanged
    assert fnd._nfs_url("nfs://192.168.7.2/Users/moquette/Kodi/Backup/") == (
        "nfs://192.168.7.2/Users/moquette/Kodi/Backup/"
    )


def test_nfs_url_invariant_no_port_anywhere(boot):
    """Invariant: no NFS URL this module can emit ever contains a :<port>,
    across every construction path (build, override, sanitize)."""
    fnd = _foundation(boot)
    import re

    port_re = re.compile(r"^nfs://[^/]+:\d+")
    candidates = [
        fnd.kodi_share_url({}),
        fnd.kodi_backup_url({}),
        fnd.kodi_share_url({"MINI_HOST": "10.0.0.5"}),
        fnd.kodi_backup_url({"KODI_BACKUP_NFS": "nfs://10.0.0.5:2049/Backup/"}),
    ]
    for url in candidates:
        assert not port_re.match(url), f"port leaked into {url!r}"


def test_kodi_share_backup_urls_default_to_mini_host(boot):
    fnd = _foundation(boot)
    assert fnd.kodi_share_url({}) == "nfs://192.168.7.2/Users/moquette/Kodi/Share/"
    assert fnd.kodi_backup_url({}) == "nfs://192.168.7.2/Users/moquette/Kodi/Backup/"


def test_kodi_share_backup_urls_honor_mini_host_override(boot):
    fnd = _foundation(boot)
    env = {"MINI_HOST": "10.0.0.9"}
    assert fnd.kodi_share_url(env) == "nfs://10.0.0.9/Users/moquette/Kodi/Share/"
    assert fnd.kodi_backup_url(env) == "nfs://10.0.0.9/Users/moquette/Kodi/Backup/"


def test_kodi_share_backup_urls_honor_explicit_overrides(boot):
    fnd = _foundation(boot)
    env = {
        "KODI_SHARE_NFS": "nfs://10.0.0.9/Somewhere/Else/",
        "KODI_BACKUP_NFS": "nfs://10.0.0.9:2049/Somewhere/Backup/",
    }
    assert fnd.kodi_share_url(env) == "nfs://10.0.0.9/Somewhere/Else/"
    # even an explicit override sheds a stray port — the invariant holds
    # regardless of where the URL came from.
    assert fnd.kodi_backup_url(env) == "nfs://10.0.0.9/Somewhere/Backup/"


def test_add_file_sources_adds_kodishare_and_kodibackup(boot):
    boot.mod._add_file_sources({})
    entries = dict(_files_sources(boot))
    assert entries["KodiShare"] == "nfs://192.168.7.2/Users/moquette/Kodi/Share/"
    assert entries["KodiBackup"] == "nfs://192.168.7.2/Users/moquette/Kodi/Backup/"


def test_add_file_sources_normalizes_legacy_share_label(boot):
    """An existing source pointing at the canonical Share path under a DIFFERENT
    label is renamed to KodiShare, not duplicated."""
    boot.sources_xml.write_text(
        "<sources><files><default></default>"
        "<source><name>KodiShare (old)</name>"
        "<path>nfs://192.168.7.2/Users/moquette/Kodi/Share/</path>"
        "<allowsharing>true</allowsharing></source>"
        "</files></sources>"
    )
    boot.mod._add_file_sources({})
    entries = _files_sources(boot)
    names = [n for n, _p in entries]
    paths = [p for _n, p in entries]
    assert "KodiShare (old)" not in names
    assert "KodiShare" in names
    assert paths.count("nfs://192.168.7.2/Users/moquette/Kodi/Share/") == 1


def test_add_file_sources_normalizes_legacy_2049_backup_variant(boot):
    """An existing Backup source carrying the old :2049 port is collapsed onto
    the canonical port-free KodiBackup entry — the bug this plan exists to kill."""
    boot.sources_xml.write_text(
        "<sources><files><default></default>"
        "<source><name>Backup</name>"
        "<path>nfs://192.168.7.2:2049/Users/moquette/Kodi/Backup/</path>"
        "<allowsharing>true</allowsharing></source>"
        "</files></sources>"
    )
    boot.mod._add_file_sources({})
    entries = _files_sources(boot)
    names = [n for n, _p in entries]
    paths = [p for _n, p in entries]
    assert "Backup" not in names
    assert "KodiBackup" in names
    assert "nfs://192.168.7.2:2049/Users/moquette/Kodi/Backup/" not in paths
    assert paths.count("nfs://192.168.7.2/Users/moquette/Kodi/Backup/") == 1


def test_add_file_sources_dedupes_share_backup_on_second_run(boot):
    boot.mod._add_file_sources({})
    boot.mod._add_file_sources({})
    entries = _files_sources(boot)
    names = [n for n, _p in entries]
    assert names.count("KodiShare") == 1
    assert names.count("KodiBackup") == 1


def test_add_file_sources_repoints_stale_entry_when_mini_host_changes(boot):
    """A re-provisioned/host-migrated box: MINI_HOST changes between two runs
    (e.g. the mini moves from WiFi .2 to a different address). The SAME-named
    KodiShare/KodiBackup entries must be REPOINTED at the new canonical URL —
    not left stale forever. Without this, the by-name dedupe in
    _add_file_sources would see "KodiShare"/"KodiBackup" already present and
    skip writing the new URL entirely, so foundation_done()'s content-check
    would correctly read False but nothing would ever converge (the Guided
    wizard would re-offer Foundation on every launch with no way to fix it)."""
    boot.mod._add_file_sources({})
    entries = dict(_files_sources(boot))
    assert entries["KodiShare"] == "nfs://192.168.7.2/Users/moquette/Kodi/Share/"

    boot.mod._add_file_sources({"MINI_HOST": "10.0.0.9"})
    entries = _files_sources(boot)
    names = [n for n, _p in entries]
    # still exactly one KodiShare/KodiBackup entry each (repointed, not duplicated)
    assert names.count("KodiShare") == 1
    assert names.count("KodiBackup") == 1
    entries = dict(entries)
    assert entries["KodiShare"] == "nfs://10.0.0.9/Users/moquette/Kodi/Share/"
    assert entries["KodiBackup"] == "nfs://10.0.0.9/Users/moquette/Kodi/Backup/"
