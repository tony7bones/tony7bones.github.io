"""Tests for run_iptv — the standalone IPTV orchestrator (Phase 5b·3).

``run_iptv`` makes the IPTV layer INDEPENDENTLY-RUNNABLE: the 0-1-2 model's
"stopped at skin-only, later adds live TV" story — Layer 1 applied on top of an
existing Foundation box with no redo. Stop here = branded Kodi + your live TV.

What it MUST do:
  * drive the SAME ``apply_iptv`` the Express one-shot drives (the no-fork
    invariant) — pvr.iptvsimple install-or-fail-loud (+ its binary inputstream
    closure from the OFFICIAL repo), the PVR-disabled config window, the
    HOST-BUILT staged-first consumption (``IPTV_STAGING_DIR``) with per-provider
    direct-env fallback, one ``instance-settings-<N>.xml`` per env provider;
  * show an HONEST summary (the backend state + whether instance settings were
    actually WRITTEN this run — never a false "configured"), then
    self-uninstall, then ONE platform-aware restart — in that order.

What it MUST NOT do — the layer invariants (the heart of this phase):
  * NO skin touch: no ``activate_skin``, no ``lookandfeel.skin``, no
    ``Skin.SetBool`` (re-setting the skin re-arms Kodi's "Keep this skin?"
    revert timeout; Foundation owns the active skin);
  * NO ``install_repos`` (Foundation owns plumbing — apply_iptv resolves its
    backend straight from the official repo and needs none of our repos);
  * NO ``apply_foundation`` / ``apply_addons`` (one layer per runner — no skin
    closure, no weather install, no base apps, no curated video, no RSS).

Failure semantics (decided per the 5b·3 prep): ``apply_iptv`` has NO user-cancel
path by construction (``install_with_deps`` never polls the dialog's cancel
button — unlike the Add-ons layer's per-repo loop), so ``ok=False`` means
exactly one thing: the backend did not install. The summary then says FAILED
(fail-loud wrote no instance-settings), and the runner STILL self-uninstalls and
restarts once — the box is unchanged, so the restart lands on the same working
Foundation box; the DRIVER keeps the env (delete-only-on-ok) for the retry.

These tests drive ``run_iptv`` against the shared fake-Kodi ``boot`` fixture
(conftest.py) — the same real engine the Express/Foundation/Add-ons orchestrator
tests use (its fake index resolves pvr.iptvsimple's platform-tagged binary
closure for real). The bare fixture is a FOUNDATION-LESS box, so every
real-engine test here also proves the tolerant Foundation-missing semantics:
the backend installs from the official repo regardless, no probe-and-abort.

Mutation proof (the killers this phase demands):
  * ``test_run_iptv_installs_pvr_backend`` / ``..._writes_instance_settings`` —
    drop the ``apply_iptv`` call and the backend/config is absent.
  * ``test_run_iptv_never_touches_skin`` / ``..._no_skin_or_plumbing_calls`` —
    add an ``activate_skin`` / ``lookandfeel.skin`` / ``install_repos`` call to
    the orchestrator body and these fail.
  * ``test_run_iptv_self_uninstalls_after_summary_before_restart`` — drop the
    ``self_uninstall`` call (or reorder the seam) and this fails.
  * ``test_run_iptv_summary_honest_on_backend_failure`` — claim success on a
    failed backend install and this fails.
"""

from __future__ import annotations

import json
import os
from xml.etree import ElementTree as ET


def _settings_set(boot):
    """{setting_id: value} from captured Settings.SetSettingValue JSON-RPC calls."""
    out = {}
    for s in boot.state["jsonrpc"]:
        try:
            d = json.loads(s)
        except ValueError:
            continue
        if d.get("method") == "Settings.SetSettingValue":
            out[d["params"]["setting"]] = d["params"]["value"]
    return out


def _instance_path_n(boot, n):
    return boot.mod.xbmcvfs.translatePath(boot.mod._iptv._instance_settings_special(n))


def _read_instance_n(boot, n):
    root = ET.parse(_instance_path_n(boot, n)).getroot()
    return {s.get("id"): (s.text or "") for s in root.findall("setting")}


def _no_restart(boot, monkeypatch):
    monkeypatch.setattr(boot.mod, "restart_kodi", lambda *a, **k: None)


def _fake_ok_result():
    """A minimal successful IPTV LayerResult for orchestrator-only tests."""
    from tony7bones.setup.result import LayerResult

    return LayerResult(layer="iptv", ok=True, installed={}, needs_restart=True)


def _fail_backend_install(boot, monkeypatch):
    """Make the PVR backend install FAIL through the layer's real fail-loud path
    (patch the iptv module's install_with_deps — _install_pvr_backend resolves it
    from those globals)."""
    monkeypatch.setattr(boot.mod._iptv, "install_with_deps", lambda *a, **k: 0)


# Foundation/Add-ons add-on ids that must NEVER be installed by the IPTV runner.
_FOUNDATION_IDS = [
    "skin.estuary.modv2",
    "script.tony7bones.modv2plus",
    "script.module.pvr.artwork",
    "resource.images.weathericons.outline-hd",
    "weather.multi",
    "script.module.autocompletion",
]
_CONTENT_IDS = [
    "script.ezmaintenanceplus",
    "script.realdebrid",
    "plugin.video.pov",
    "plugin.video.theloop",
    "plugin.video.sportshd",
    "plugin.video.youtube",
    "plugin.video.dailymotion_com",
]

# --------------------------------------------------------------------------- #
# Staged host-built artifacts (the 5b·2 shape — all values fabricated).
# --------------------------------------------------------------------------- #
_PLAYLISTS_SPECIAL = "special://userdata/addon_data/pvr.iptvsimple/playlists/"
_GROUPS_DIR_SPECIAL = "special://userdata/addon_data/pvr.iptvsimple/channelGroups/"


def _stage(tmp_path, n=1, tok="Network24"):
    """Write a host-style staged artifact set for instance `n` into tmp."""
    staging = tmp_path / "staging"
    staging.mkdir(exist_ok=True)
    (staging / f"instance-settings-{n}.xml").write_text(
        '<settings version="2">\n'
        f'  <setting id="kodi_addon_instance_name">{tok}</setting>\n'
        '  <setting id="kodi_addon_instance_enabled">true</setting>\n'
        '  <setting id="m3uPathType">0</setting>\n'
        f'  <setting id="m3uPath">{_PLAYLISTS_SPECIAL}{tok}.m3u</setting>\n'
        '  <setting id="tvGroupMode">2</setting>\n'
        '  <setting id="customTvGroupsFile">'
        f"{_GROUPS_DIR_SPECIAL}customTVGroups-{tok}.xml</setting>\n"
        '  <setting id="tvChannelGroupsOnly">true</setting>\n'
        "</settings>"
    )
    (staging / f"{tok}.m3u").write_text(
        '#EXTM3U\n#EXTINF:-1 group-title="X",C\nhttp://iptv.example/s\n'
    )
    (staging / f"customTVGroups-{tok}.xml").write_text(
        "<customChannelGroups><channelGroupName>X</channelGroupName>"
        "</customChannelGroups>"
    )
    return staging


# --------------------------------------------------------------------------- #
# run_iptv returns the IPTV LayerResult.
# --------------------------------------------------------------------------- #
def test_run_iptv_returns_iptv_layerresult(boot, monkeypatch):
    """run_iptv returns the IPTV LayerResult (layer='iptv', ok=True on a
    successful run, needs_restart requested)."""
    _no_restart(boot, monkeypatch)
    res = boot.mod.run_iptv({})
    assert res.layer == "iptv"
    assert res.ok is True
    assert res.needs_restart is True


# --------------------------------------------------------------------------- #
# The backend + config land (mutation killer #1: drop apply_iptv).
# --------------------------------------------------------------------------- #
def test_run_iptv_installs_pvr_backend(boot, monkeypatch):
    """The PVR backend (+ its binary inputstream closure) is installed BY THIS
    LAYER through the real engine, and ends ENABLED (the PVR-disabled config
    window must re-enable it). MUTATION: drop the apply_iptv call and the
    backend is absent."""
    _no_restart(boot, monkeypatch)
    res = boot.mod.run_iptv({})
    assert "pvr.iptvsimple" in boot.state["installed"], "the backend must install"
    assert "inputstream.ffmpegdirect" in boot.state["installed"], (
        "the backend's binary closure must install"
    )
    assert "pvr.iptvsimple" not in boot.state["disabled"], (
        "the clobber-fix window must RE-ENABLE the backend"
    )
    assert res.installed.get("pvr.iptvsimple") in ("installed", "configured")


def test_run_iptv_writes_instance_settings_from_env(boot, monkeypatch):
    """An env provider's config lands: the legacy single-instance IPTV_M3U is
    written into instance-settings-1.xml and the LayerResult reports the backend
    'configured' (the enforce actually wrote this run)."""
    _no_restart(boot, monkeypatch)
    res = boot.mod.run_iptv({"IPTV_M3U": "http://provider.example/playlist.m3u"})
    assert res.ok is True
    assert res.installed.get("pvr.iptvsimple") == "configured"
    vals = _read_instance_n(boot, 1)
    assert vals.get("m3uUrl") == "http://provider.example/playlist.m3u"
    assert vals.get("m3uPathType") == "1"


def test_run_iptv_multi_provider_env_one_instance_per_provider(boot, monkeypatch):
    """The REAL per-device env shape: a numbered multi-provider env (m3u
    provider 1 + unstaged xtream provider 2) → provider 1 lands in
    instance-settings-1.xml (identity keys + custom groups from the grammar's
    SOURCE side); the unstaged xtream provider honestly writes NO instance file
    (host-side derivation is the only xtream path)."""
    _no_restart(boot, monkeypatch)
    env = {
        "IPTV_1_NAME": "Network 24",
        "IPTV_1_MODE": "m3u",
        "IPTV_1_M3U": "http://iptv.example/1.m3u?password=p1",
        "IPTV_1_GROUPS": "USA ENTERTAINMENT > US Entertainment | sort; PPV EVENTS",
        "IPTV_2_NAME": "Streamvision",
        "IPTV_2_MODE": "xtream",
        "IPTV_2_PORTAL": "http://portal.example:8080",
        "IPTV_2_USER": "u",
        "IPTV_2_PASS": "p",
    }
    res = boot.mod.run_iptv(env)
    assert res.ok is True
    assert res.installed.get("pvr.iptvsimple") == "configured"
    vals = _read_instance_n(boot, 1)
    assert vals["kodi_addon_instance_name"] == "Network 24"
    assert vals["tvGroupMode"] == "2"
    gpath = boot.mod.xbmcvfs.translatePath(vals["customTvGroupsFile"])
    gtext = open(gpath).read()
    assert "USA ENTERTAINMENT" in gtext and "PPV EVENTS" in gtext
    assert not os.path.exists(_instance_path_n(boot, 2)), (
        "an UNSTAGED xtream provider must be skipped honestly (no instance file)"
    )


def test_run_iptv_consumes_staged_artifacts(boot, monkeypatch, tmp_path):
    """The staged-first path works END-TO-END through the runner: with
    IPTV_STAGING_DIR in the env the host-built instance file lands with m3uPath
    REWRITTEN to the translated absolute local path (NOT the env's remote URL)
    and the side-files copied — the only path an xtream provider can land
    through, proven here via the standalone runner."""
    _no_restart(boot, monkeypatch)
    staging = _stage(tmp_path)
    res = boot.mod.run_iptv(
        {
            "IPTV_1_NAME": "Network 24",
            "IPTV_1_M3U": "http://iptv.example/remote.m3u?password=REMOTESECRET",
            "IPTV_STAGING_DIR": str(staging),
        }
    )
    assert res.ok is True
    assert res.installed.get("pvr.iptvsimple") == "configured"
    vals = _read_instance_n(boot, 1)
    playlist_abs = boot.mod.xbmcvfs.translatePath(_PLAYLISTS_SPECIAL + "Network24.m3u")
    assert vals["m3uPath"] == playlist_abs, "m3uPath must be the translated abs path"
    assert os.path.exists(playlist_abs), "the staged playlist must be copied"
    assert vals.get("m3uUrl", "") == "", "the staged config is authoritative"


# --------------------------------------------------------------------------- #
# The no-skin-touch invariant (mutation killer #2).
# --------------------------------------------------------------------------- #
def test_run_iptv_never_touches_skin(boot, monkeypatch):
    """run_iptv NEVER touches the skin: activate_skin is not called,
    lookandfeel.skin is not set, and no Skin.Set* builtin is issued — re-setting
    the skin would re-arm Kodi's "Keep this skin?" revert timeout (Foundation
    owns the active skin). MUTATION: add any skin call to the orchestrator and
    this fails."""
    _no_restart(boot, monkeypatch)
    activated = []
    monkeypatch.setattr(boot.mod, "activate_skin", lambda *a, **k: activated.append(a))
    boot.mod.run_iptv({"IPTV_M3U": "http://provider.example/playlist.m3u"})

    assert activated == [], "run_iptv must never call activate_skin"
    settings = _settings_set(boot)
    assert "lookandfeel.skin" not in settings, "run_iptv must never set the skin"
    skin_builtins = [b for b in boot.state["builtins"] if b.startswith("Skin.Set")]
    assert skin_builtins == [], (
        f"run_iptv must issue no Skin.Set* builtin; got {skin_builtins}"
    )


# --------------------------------------------------------------------------- #
# One layer per runner: no Foundation, no Add-ons, no repos (installed-set proof).
# --------------------------------------------------------------------------- #
def test_run_iptv_installs_no_foundation_or_addons_content(boot, monkeypatch):
    """run_iptv installs NONE of the Foundation closure (skin / modv2plus /
    pvr.artwork / outline-hd / weather.multi / autocomplete), NO content add-ons
    (base apps / curated video), and NONE of our source repos — at the
    REAL-engine level. MUTATION: calling apply_foundation / apply_addons /
    install_repos from the orchestrator leaks an id here and fails."""
    _no_restart(boot, monkeypatch)
    boot.mod.run_iptv({})

    leaked = [
        aid for aid in _FOUNDATION_IDS + _CONTENT_IDS if aid in boot.state["installed"]
    ]
    assert leaked == [], f"run_iptv leaked foreign-layer add-ons: {leaked}"
    for _z, rid in boot.mod.REPO_ZIPS:
        assert rid not in boot.state["installed"], (
            f"run_iptv must not install source repo {rid} (Foundation owns plumbing)"
        )
    # weather/RSS are other layers' jobs: no provider set, no RSS toggle.
    settings = _settings_set(boot)
    assert "weather.addon" not in settings
    assert "lookandfeel.enablerssfeeds" not in settings


def test_run_iptv_orchestrator_no_skin_or_plumbing_calls(boot, monkeypatch):
    """STRUCTURAL invariant on the orchestrator BODY (apply_iptv stubbed out):
    run_iptv itself calls neither install_repos (Foundation owns plumbing) nor
    apply_foundation / apply_addons / activate_skin. MUTATION: adding any such
    call to the body — e.g. mirroring _foundation_core's install_repos(dialog)
    — fails here even though the layer call is stubbed."""
    called = []
    monkeypatch.setattr(boot.mod, "apply_iptv", lambda *a, **k: _fake_ok_result())
    for name in ("install_repos", "apply_foundation", "apply_addons", "activate_skin"):
        monkeypatch.setattr(boot.mod, name, lambda *a, _n=name, **k: called.append(_n))
    _no_restart(boot, monkeypatch)
    boot.mod.run_iptv({})
    assert called == [], (
        f"the run_iptv body must make no skin/plumbing/foreign-layer call; got {called}"
    )


# --------------------------------------------------------------------------- #
# The terminal seam: summary -> self-uninstall -> ONE restart, restart LAST.
# --------------------------------------------------------------------------- #
def test_run_iptv_self_uninstalls_after_summary_before_restart(boot, monkeypatch):
    """run_iptv self-uninstalls exactly once, AFTER the summary Dialog().ok and
    BEFORE the restart (the terminal-seam ordering shared with run_foundation /
    run_addons). MUTATION: drop self_uninstall (or reorder) and this fails."""
    events = []
    real_ok = boot.mod.xbmcgui.Dialog.ok

    def _ok(self, title, msg):
        events.append("summary")
        return real_ok(self, title, msg)

    monkeypatch.setattr(boot.mod.xbmcgui.Dialog, "ok", _ok)
    monkeypatch.setattr(
        boot.mod, "self_uninstall", lambda *a, **k: events.append("self_uninstall")
    )
    monkeypatch.setattr(
        boot.mod, "restart_kodi", lambda *a, **k: events.append("restart")
    )
    boot.mod.run_iptv({})

    assert events == ["summary", "self_uninstall", "restart"], (
        f"order must be summary -> self_uninstall -> restart, got {events}"
    )


def test_run_iptv_restarts_exactly_once(boot, monkeypatch):
    """ONE restart, via the existing platform-aware primitive (restart_kodi) —
    honoring the layer's needs_restart request, never more than once."""
    restarts = []
    monkeypatch.setattr(boot.mod, "restart_kodi", lambda *a, **k: restarts.append(a))
    boot.mod.run_iptv({})
    assert len(restarts) == 1, f"exactly one restart, got {len(restarts)}"


# --------------------------------------------------------------------------- #
# Honest summary — straight from the LayerResult.
# --------------------------------------------------------------------------- #
def test_run_iptv_summary_reports_configured(boot, monkeypatch):
    """A run that actually wrote instance settings says so."""
    _no_restart(boot, monkeypatch)
    boot.mod.run_iptv({"IPTV_M3U": "http://provider.example/playlist.m3u"})
    assert boot.state["ok"], "the summary dialog must be shown"
    title, msg = boot.state["ok"][-1]
    assert title == "Tony.7.Bones Setup"
    assert "pvr.iptvsimple: installed" in msg
    assert "Instance settings: written" in msg
    assert "Restart will finish setup." in msg


def test_run_iptv_summary_honest_when_no_config_written(boot, monkeypatch):
    """A no-provider env (backend installed, nothing written) must NOT claim
    config was written — the summary says 'unchanged'."""
    _no_restart(boot, monkeypatch)
    boot.mod.run_iptv({})
    _title, msg = boot.state["ok"][-1]
    assert "pvr.iptvsimple: installed" in msg
    assert "Instance settings: unchanged" in msg, f"must be honest, got: {msg}"
    assert "written\n" not in msg


def test_run_iptv_summary_honest_on_backend_failure(boot, monkeypatch):
    """The decided failure semantics (apply_iptv ok=False = the backend did not
    install; fail-loud wrote NO instance-settings): the summary says FAILED and
    never claims success — and the runner STILL self-uninstalls and restarts
    once (the box is unchanged, so the restart lands on the same working
    Foundation box; the driver keeps the env for the retry). MUTATION: claim
    success on a failed install and this fails."""
    events = []
    _fail_backend_install(boot, monkeypatch)
    monkeypatch.setattr(
        boot.mod, "self_uninstall", lambda *a, **k: events.append("self_uninstall")
    )
    monkeypatch.setattr(
        boot.mod, "restart_kodi", lambda *a, **k: events.append("restart")
    )
    res = boot.mod.run_iptv({"IPTV_M3U": "http://provider.example/playlist.m3u"})

    assert res.ok is False
    assert res.failed.get("pvr.iptvsimple") == "install failed"
    _title, msg = boot.state["ok"][-1]
    assert "pvr.iptvsimple: FAILED" in msg
    assert "No instance settings were written." in msg
    assert "installed" not in msg.replace("FAILED", ""), (
        f"a failed run must never read as success: {msg}"
    )
    assert not os.path.exists(_instance_path_n(boot, 1)), (
        "fail-loud: no instance-settings on a failed backend install"
    )
    assert events == ["self_uninstall", "restart"], (
        "the runner still completes its terminal seam on a failed install"
    )


def test_run_iptv_cancel_button_is_inert_by_construction(boot, monkeypatch):
    """PINS the decided cancel semantics: the IPTV layer has NO user-cancel path
    (install_with_deps never polls the dialog's cancel button, unlike the
    Add-ons layer's per-repo loop) — so a 'cancelled' dialog changes NOTHING:
    the run completes (backend installed, config written, summary + uninstall +
    one restart). If a future change adds cancel polling to this layer, this
    test surfaces it so the orchestrator's abort contract is decided
    deliberately, not inherited silently."""
    events = []
    monkeypatch.setattr(boot.mod.xbmcgui.DialogProgress, "iscanceled", lambda s: True)
    monkeypatch.setattr(
        boot.mod, "self_uninstall", lambda *a, **k: events.append("self_uninstall")
    )
    monkeypatch.setattr(
        boot.mod, "restart_kodi", lambda *a, **k: events.append("restart")
    )
    res = boot.mod.run_iptv({"IPTV_M3U": "http://provider.example/playlist.m3u"})
    assert res.ok is True, "no cancel path exists in this layer by construction"
    assert res.installed.get("pvr.iptvsimple") == "configured"
    assert boot.state["ok"], "the summary is still shown"
    assert events == ["self_uninstall", "restart"], "the run still completes"


# --------------------------------------------------------------------------- #
# Env lifecycle: passed in, forwarded verbatim; the runner never reads/deletes.
# --------------------------------------------------------------------------- #
def test_run_iptv_passes_env_through_verbatim(boot, monkeypatch):
    """The parsed env dict is forwarded to apply_iptv VERBATIM (read-once is the
    driver's job); None is normalized to {} (the no-env desktop run)."""
    seen = []

    def _spy(env, *, dialog=None, log=None):
        seen.append(env)
        return _fake_ok_result()

    monkeypatch.setattr(boot.mod, "apply_iptv", _spy)
    _no_restart(boot, monkeypatch)
    env = {"IPTV_M3U": "http://provider.example/playlist.m3u"}
    boot.mod.run_iptv(env)
    boot.mod.run_iptv(None)
    assert seen[0] is env, "the env dict must be forwarded verbatim"
    assert seen[1] == {}, "None must normalize to the empty env"


# --------------------------------------------------------------------------- #
# Re-entry: a second run is safe by construction (no duplicates, no flips).
# --------------------------------------------------------------------------- #
def test_run_iptv_reentry_second_run_is_clean(boot, monkeypatch):
    """Running run_iptv twice with the same env leaves the box state IDENTICAL:
    the installed set does not change, the instance-settings file is
    byte-identical, the backend ends ENABLED — and the second run honestly
    reports already_done=True (backend present, nothing newly written: the
    enforce's write-only-if-changed skipped)."""
    _no_restart(boot, monkeypatch)
    env = {"IPTV_M3U": "http://provider.example/playlist.m3u"}
    res1 = boot.mod.run_iptv(env)
    first_installed = set(boot.state["installed"])
    first_bytes = open(_instance_path_n(boot, 1), "rb").read()

    res2 = boot.mod.run_iptv(env)
    assert res1.ok is True and res2.ok is True
    assert res1.already_done is False, "the first run did real work"
    assert res2.already_done is True, (
        "re-entry must report already_done (backend present, nothing written)"
    )
    assert res2.installed.get("pvr.iptvsimple") == "installed"
    assert set(boot.state["installed"]) == first_installed, (
        "re-entry must not change the installed set"
    )
    assert open(_instance_path_n(boot, 1), "rb").read() == first_bytes, (
        "re-entry must leave the instance-settings byte-identical"
    )
    assert "pvr.iptvsimple" not in boot.state["disabled"], (
        "the backend must end ENABLED after re-entry"
    )
