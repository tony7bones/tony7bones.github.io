"""Coverage for the Tony.7.Bones Bootstrap add-on.

Two layers:

* Static contract — manifest is well-formed and version-bumped, the script
  compiles, every repo zip it references exists in the published repositories/
  folder (so installs won't 404), and no IPTV secret is embedded.
* Runtime behavior — default.py is imported under mocked Kodi modules (run() is
  __main__-guarded, so import is side-effect-free) and the install flow is
  exercised directly: repos extract, the first-party patch resolves live, and
  the requested apps install through Kodi's own repo installer (InstallAddon)
  one at a time so they register and actually run.
"""

from __future__ import annotations

import ast
import os
import py_compile
import sys
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
import release_lib as rl  # noqa: E402

REPO_ROOT = HERE.parent
ADDON_DIR = REPO_ROOT / "addons" / "script.tony7bones.bootstrap"
ADDON_XML = ADDON_DIR / "addon.xml"
DEFAULT_PY = ADDON_DIR / "default.py"
REPOSITORIES = REPO_ROOT / "repositories"
# The Add-ons layer source — the literal home of the REPO_ZIPS / ADDONS /
# FIRST_PARTY / VIDEO_APPS constants since Phase 2c (default.py re-exports them as
# `X = _addons.X` shims, which ast.literal_eval cannot evaluate, so the constant
# tests parse them from their literal source here).
ADDONS_PY = (
    REPO_ROOT
    / "addons"
    / "script.module.tony7bones"
    / "lib"
    / "tony7bones"
    / "setup"
    / "addons.py"
)
# The IPTV layer source — the literal home of PVR_BACKEND_ID since Phase 3a (the
# pvr.iptvsimple INSTALL moved here from the base ADDONS list).
IPTV_PY = ADDONS_PY.parent / "iptv.py"
# The Foundation layer source — the home of WEATHER_ADDON since the
# weather-into-Foundation change (weather.multi install + config moved here from the
# base ADDONS list — weather is branded look, not content).
FOUNDATION_PY = ADDONS_PY.parent / "foundation.py"


def _iptv_assign(name):
    """Literal value assigned to `name` in the IPTV layer source (iptv.py)."""
    return _assign(name, IPTV_PY)


def _addon_root():
    return ET.parse(ADDON_XML).getroot()


def _assign(name, src=DEFAULT_PY):
    """Return the literal value assigned to `name` in `src` (no import/exec).

    Defaults to default.py; the REPO_ZIPS / ADDONS / FIRST_PARTY / VIDEO_APPS
    constants now live literally in tony7bones.setup.addons (Phase 2c), so those
    tests pass `src=ADDONS_PY` — default.py only re-exports them as `X = _addons.X`
    shims, which ast.literal_eval cannot evaluate."""
    tree = ast.parse(Path(src).read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for tgt in node.targets:
                if isinstance(tgt, ast.Name) and tgt.id == name:
                    return ast.literal_eval(node.value)
    raise AssertionError(f"{name} not found in {Path(src).name}")


# --------------------------------------------------------------------------- #
# Manifest
# --------------------------------------------------------------------------- #
def test_addon_id_unchanged():
    assert _addon_root().get("id") == "script.tony7bones.bootstrap"


def test_addon_name_is_branded():
    assert _addon_root().get("name") == "Tony.7.Bones Setup"


def test_version_bumped_past_old():
    v = _addon_root().get("version")
    assert rl.is_greater(v, "1.0.22"), f"version {v} must exceed the old 1.0.22"


# --------------------------------------------------------------------------- #
# Script
# --------------------------------------------------------------------------- #
def test_script_is_a_proper_program_addon():
    """The setup is a normal runnable Program add-on while it briefly exists.

    The old 'image' content-type hack (to hide it from Estuary's home Programs
    widget) is gone: the add-on now keeps itself off the home screen by REMOVING
    ITSELF after a successful run (see test_self_uninstall_logic_exists), so it
    can declare the correct content type. It must provide 'executable' so that,
    for the one run it exists, it behaves like the Program add-on it is."""
    ext = _addon_root().find("extension[@point='xbmc.python.script']")
    assert ext is not None, "must keep the xbmc.python.script extension (runnable)"
    assert ext.get("library") == "default.py"
    provides = [p.text for p in ext.findall("provides")]
    assert provides == ["executable"], (
        "must declare <provides>executable</provides> (a proper Program add-on); "
        f"got {provides!r}"
    )


def test_default_py_compiles():
    py_compile.compile(str(DEFAULT_PY), doraise=True)


def test_referenced_repo_zips_exist():
    """Every repo zip the bootstrap downloads must exist in repositories/."""
    for zip_name, _repo_id in _assign("REPO_ZIPS", ADDONS_PY):
        assert (REPOSITORIES / zip_name).exists(), f"missing repo zip: {zip_name}"


def test_repo_zip_count_is_twelve():
    # repository.tony7bones (the 13th) is the host repo, already installed.
    assert len(_assign("REPO_ZIPS", ADDONS_PY)) == 12


def test_addons_are_plain_id_strings_no_labels():
    """No display-name labels: ADDONS and FIRST_PARTY are lists of id strings."""
    for item in _assign("ADDONS", ADDONS_PY):
        assert isinstance(item, str), f"ADDONS entry is not a bare id: {item!r}"
    for item in _assign("FIRST_PARTY", ADDONS_PY):
        assert isinstance(item, str), f"FIRST_PARTY entry is not a bare id: {item!r}"


def test_addons_includes_peno64_apps_only():
    """Base ADDONS install set: ONLY the two peno64 apps.

    pvr.iptvsimple moved into the IPTV layer (apply_iptv / _install_pvr_backend) and
    weather.multi moved into the Foundation layer (apply_foundation) — so the base
    list is content-only and carries neither the PVR backend nor the branded-look
    weather provider. A FULL run STILL installs BOTH (pvr via apply_iptv, weather via
    apply_foundation), proven by the net-set equivalence invariant in
    test_modular_setup.py."""
    assert _assign("ADDONS", ADDONS_PY) == [
        "script.ezmaintenanceplus",
        "script.realdebrid",
    ]
    # The moves precisely: pvr -> IPTV layer, weather -> Foundation layer.
    assert "pvr.iptvsimple" not in _assign("ADDONS", ADDONS_PY)
    assert "weather.multi" not in _assign("ADDONS", ADDONS_PY)
    assert _iptv_assign("PVR_BACKEND_ID") == "pvr.iptvsimple", (
        "apply_iptv must own the pvr.iptvsimple backend after Phase 3a"
    )
    assert _assign("WEATHER_ADDON", FOUNDATION_PY) == "weather.multi", (
        "apply_foundation must own the weather.multi provider"
    )


def test_peno64_repo_is_installed_so_apps_resolve():
    """The apps live in peno64 — its repo zip must be in the install list."""
    repo_ids = {rid for _zip, rid in _assign("REPO_ZIPS", ADDONS_PY)}
    assert "repository.peno64" in repo_ids


def test_patch_is_first_party_direct_extract():
    """The MOD V2 patch must NOT be auto-installed by the setup. It is neither in
    the first-party direct-extract list nor in the apps list — a user installs it
    by hand only if they adopt the Estuary MOD V2 skin. It stays HOST-provided
    (see test_modv2plus_is_host_provided)."""
    assert "script.tony7bones.modv2plus" not in _assign("FIRST_PARTY", ADDONS_PY)
    assert "script.tony7bones.modv2plus" not in _assign("ADDONS", ADDONS_PY)


def test_first_party_is_empty():
    """Nothing is auto-installed from our Pages as a 'first-party' add-on now
    that the MOD V2 patch is opt-in. run() must skip the first-party loop."""
    assert _assign("FIRST_PARTY", ADDONS_PY) == []


def test_apps_install_without_modal_installer():
    """Apps must NOT use Kodi's InstallAddon builtin — it pops a blocking modal
    install dialog that deadlocks the GUI when driven from a script. They are
    installed by resolving the dependency closure and extracting directly."""
    src = DEFAULT_PY.read_text()
    assert "InstallAddon(" not in src, "InstallAddon modal must not be used"
    # The closure-resolve + direct-extract install now lives in the shared
    # library; the base Setup drives it through install_with_deps().
    assert "install_with_deps" in src


def test_never_toggles_unknown_sources():
    """The bootstrap must NOT touch addons.unknownsources. Flipping it
    false->true pops a blocking "access to personal data... Proceed?" warning.
    Direct-extract + SetAddonEnabled installs/enables add-ons without that
    setting, so a real user running the setup never sees the prompt."""
    src = DEFAULT_PY.read_text()
    assert "addons.unknownsources" not in src, (
        "must not write addons.unknownsources (it pops the security prompt)"
    )
    assert "_set_unknown_sources" not in src, (
        "the unknown-sources toggle helper must be removed"
    )


def test_installs_weather_and_pvr_binary():
    """A full run must install the weather add-on AND the binary PVR client, with
    runtime platform detection picking the right build.

    The HOMES are now split three ways: weather.multi moved to the Foundation layer
    (branded look), pvr.iptvsimple moved to the IPTV layer (apply_iptv /
    _install_pvr_backend), and neither is in the base ADDONS list anymore. Both still
    install on a full run — the binary platform detection lives in the shared
    library's install_with_deps (it loads the official index with the platform tag),
    which the Foundation weather install, the base loop, and apply_iptv all drive."""
    addons = _assign("ADDONS", ADDONS_PY)
    assert "pvr.iptvsimple" not in addons, "pvr moved to the IPTV layer (Phase 3a)"
    assert "weather.multi" not in addons, (
        "weather.multi moved to the Foundation layer (weather-into-Foundation)"
    )
    # Foundation owns weather.multi now and resolves it from the official repo.
    assert _assign("WEATHER_ADDON", FOUNDATION_PY) == "weather.multi"
    fnd_src = FOUNDATION_PY.read_text()
    assert "install_with_deps" in fnd_src, (
        "apply_foundation must install weather.multi via install_with_deps"
    )
    # The IPTV layer owns the PVR backend now and resolves it from the official repo.
    assert _iptv_assign("PVR_BACKEND_ID") == "pvr.iptvsimple"
    iptv_src = IPTV_PY.read_text()
    assert "install_with_deps" in iptv_src, (
        "apply_iptv must install the PVR backend via install_with_deps "
        "(binary platform-aware closure)"
    )
    assert "OFFICIAL_BASE" in iptv_src, (
        "the IPTV backend resolves from the official repo"
    )
    # The base Setup still hands the official + peno64 bases to its base/video loop.
    src = DEFAULT_PY.read_text()
    assert "install_with_deps" in src
    assert "OFFICIAL_BASE" in src and "PENO64_BASE" in src


@pytest.mark.parametrize(
    "needle",
    # m3uUrl/epgUrl are NOT here: they are legitimate setting IDs the env-driven
    # IPTV writer references (the VALUE always comes from the env, never hardcoded
    # — test_secret_leak.py scans tracked files for the real provider URL/creds).
    ["bit.ly", "cutt.ly", "xtream", "get.php", "player_api"],
)
def test_no_iptv_secret_embedded(needle):
    assert needle not in DEFAULT_PY.read_text(), (
        f"secret-ish token in default.py: {needle}"
    )


# --------------------------------------------------------------------------- #
# QA-added coverage
# --------------------------------------------------------------------------- #
def test_repo_zip_inner_id_matches_declared():
    """Each zip's inner addon.xml id must equal the id declared in REPO_ZIPS."""
    import zipfile

    for zip_name, repo_id in _assign("REPO_ZIPS", ADDONS_PY):
        with zipfile.ZipFile(REPOSITORIES / zip_name) as z:
            axml = next(n for n in z.namelist() if n.endswith("addon.xml"))
            root = ET.fromstring(z.read(axml))
        assert root.get("id") == repo_id, (
            f"{zip_name}: inner id {root.get('id')} != {repo_id}"
        )


def test_no_empty_addon_ids():
    assert all(_assign("ADDONS", ADDONS_PY)), "ADDONS must contain no empty ids"
    assert all(_assign("FIRST_PARTY", ADDONS_PY)), (
        "FIRST_PARTY must contain no empty ids"
    )


def test_success_dialog_does_not_overclaim():
    """The final dialog must report counts, not an unconditional 'apps installed'."""
    src = DEFAULT_PY.read_text()
    assert "Repos and apps installed" not in src
    assert "{repo_ok}" in src and "{app_ok}" in src


def test_modv2plus_is_host_provided():
    """The patch must exist in the host addons.xml and be served statically."""
    addons = (REPO_ROOT / "addons" / "addons.xml").read_text()
    assert 'id="script.tony7bones.modv2plus"' in addons


# --------------------------------------------------------------------------- #
# End-of-setup restart flow (the Fire Stick end-freeze fix)
# --------------------------------------------------------------------------- #
def test_restart_flow_present_and_prompted():
    """After the success summary the script must offer a platform-correct
    restart. The restart machinery (RestartApp/Quit/yesno, Android branch) now
    lives in the shared library's restart_kodi(); the base Setup must call it."""
    src = DEFAULT_PY.read_text()
    assert "restart_kodi" in src, "must invoke the shared restart helper"
    assert 'restart_kodi("Tony.7.Bones Setup"' in src, (
        "the base Setup must drive restart_kodi with its own title"
    )


def test_restart_comes_after_success_summary():
    """The restart prompt must follow the counts dialog, not replace it."""
    src = DEFAULT_PY.read_text()
    ok_pos = src.rfind("Restart will finish setup.")
    restart_pos = src.rfind("restart_kodi(")
    assert ok_pos != -1 and restart_pos != -1
    assert restart_pos > ok_pos, "restart prompt must come after the summary dialog"


# --------------------------------------------------------------------------- #
# Self-uninstall (run once, then disappear — no leftover home tile)
# --------------------------------------------------------------------------- #
def test_self_uninstall_logic_exists():
    """The setup must remove itself after a successful run. The deletion
    machinery (rmtree of its own addons/ dir, with the own-id guard) now lives in
    the shared library's self_uninstall(); the base Setup must invoke it with its
    own add-on id."""
    src = DEFAULT_PY.read_text()
    assert "self_uninstall" in src, "must invoke the shared self-uninstall helper"
    assert 'MY_ID = "script.tony7bones.bootstrap"' in src, (
        "the base Setup must define its own id"
    )
    assert "self_uninstall(MY_ID" in src, (
        "self-uninstall must target the add-on's own id"
    )


def test_self_uninstall_runs_after_summary_and_before_restart():
    """Sequence must be: summary dialog -> self-uninstall -> restart prompt.
    The restart is what finalises the removal (startup scan drops the DB row)."""
    src = DEFAULT_PY.read_text()
    ok_pos = src.rfind("Restart will finish setup.")
    uninstall_pos = src.rfind("self_uninstall(MY_ID")
    restart_pos = src.rfind("restart_kodi(")
    assert ok_pos != -1 and uninstall_pos != -1 and restart_pos != -1
    assert ok_pos < uninstall_pos < restart_pos, (
        "order must be summary -> self-uninstall -> restart"
    )


# --------------------------------------------------------------------------- #
# Runtime coverage — import default.py under mocked Kodi APIs and run it
# --------------------------------------------------------------------------- #
import json as _json  # noqa: E402
import urllib.request  # noqa: E402

# The fake-Kodi ``boot`` fixture lives in conftest.py so the modular-setup test
# files can share the exact same fake Kodi. It is auto-discovered by pytest — the
# tests below simply request it as a fixture argument.


def test_no_unknown_sources_jsonrpc_during_run(boot):
    """A full run must never send a Settings.SetSettingValue for
    addons.unknownsources — that is what pops the security prompt."""
    boot.mod.run()
    assert not any("addons.unknownsources" in s for s in boot.state["jsonrpc"])


def test_latest_zip_url_resolves_live_version(boot):
    url = boot.mod._latest_zip_url("script.tony7bones.modv2plus")
    assert url == (
        "https://tony7bones.github.io/addons/script.tony7bones.modv2plus/"
        "script.tony7bones.modv2plus-1.0.0.zip"
    )


def test_latest_zip_url_handles_error(boot, monkeypatch):
    def boom(*a, **k):
        raise OSError("no net")

    monkeypatch.setattr(urllib.request, "urlopen", boom)
    assert boot.mod._latest_zip_url("script.tony7bones.modv2plus") is None


def test_run_installs_apps_without_modal(boot):
    boot.mod.run()
    s = boot.state
    # NO unknown-sources toggle — that prompt must never fire for a real user
    assert not any("addons.unknownsources" in j for j in s["jsonrpc"])
    # local add-on store rescanned so Kodi sees the freshly extracted dirs
    assert "UpdateLocalAddons()" in s["builtins"]
    # NO modal installer was ever used — that is what caused the GUI freeze
    assert not any(b.startswith("InstallAddon(") for b in s["builtins"])
    # each app and its dependency closure ended up installed + enabled
    for aid in boot.mod.ADDONS:
        assert aid in s["installed"], f"{aid} not installed"
    assert "script.module.requests" in s["installed"]  # resolved dependency
    # weather add-on and the binary PVR client both installed + enabled
    assert "weather.multi" in s["installed"]
    assert "pvr.iptvsimple" in s["installed"]
    assert "inputstream.ffmpegdirect" in s["installed"]  # binary dep of the PVR
    # the one-shot now ALSO installs the MOD V2+ patch add-on, direct-extracted —
    # our first-party add-on is served only by the proxy the resolver skips
    assert "script.tony7bones.modv2plus" in s["installed"]
    assert "script.tony7bones.modv2plus" in s["extracted"]
    assert s["ok"], "no completion dialog shown"
    _title, msg = s["ok"][-1]
    assert "Repos:" in msg and "Apps:" in msg and "Video add-ons:" in msg


def test_run_self_uninstalls_at_end(boot):
    """A full run must end by removing the setup's own add-on directory."""
    mine = boot.addons / "script.tony7bones.bootstrap"
    mine.mkdir()
    (mine / "addon.xml").write_text('<addon id="script.tony7bones.bootstrap"/>')
    boot.mod.run()
    assert not mine.exists(), "run() must self-uninstall at the end"


def test_run_aborts_cleanly_on_cancel(boot, monkeypatch):
    monkeypatch.setattr(
        boot.mod.xbmcgui.DialogProgress, "iscanceled", lambda self: True
    )
    boot.mod.run()  # must not raise
    # cancelled before finishing → no completion dialog
    assert boot.state["ok"] == []


# --------------------------------------------------------------------------- #
# File-Manager sources (Kodi home + sources dirs added to sources.xml)
# --------------------------------------------------------------------------- #
def _files_sources(boot):
    """Parse sources.xml and return [(name, path), ...] from the <files> section."""
    root = ET.parse(boot.sources_xml).getroot()
    files = root.find("files")
    assert files is not None, "<files> section must exist"
    return [(s.findtext("name"), s.findtext("path")) for s in files.findall("source")]


_HOME = ("special://home", "special://home")
_SRC = ("special://kodi", "/storage/emulated/0/kodi/")
_T7B = (".tony.7.bones", "https://tony7bones.github.io/")


def test_add_file_sources_helper_exists():
    """The helper must still be reachable (a re-export shim over the Foundation
    layer's lifted body) and the Foundation layer it now lives in must be wired
    into run() BEFORE the restart (Kodi caches sources.xml at startup). The exact
    file-sources slot/order is pinned at RUNTIME by the modular_setup snapshot;
    this guards the shim + the apply_foundation-before-restart wiring."""
    src = DEFAULT_PY.read_text()
    assert "_add_file_sources" in src, "shim must exist"
    assert "_add_file_sources = _foundation._add_file_sources" in src, (
        "_add_file_sources must be a re-export shim over the Foundation layer"
    )
    assert "apply_foundation(" in src, "apply_foundation must be invoked in run()"
    found_pos = src.rfind("apply_foundation(")
    restart_pos = src.rfind("restart_kodi(")
    assert found_pos != -1 and restart_pos != -1
    assert found_pos < restart_pos, "apply_foundation() must come before the restart"


def test_add_file_sources_creates_file_when_missing(boot):
    """No sources.xml → it creates the structure and adds both sources."""
    assert not boot.sources_xml.exists()
    boot.mod._add_file_sources()
    entries = _files_sources(boot)
    assert _HOME in entries
    assert _SRC in entries
    assert _T7B in entries
    # canonical shape: <files> opens with a <default> element
    root = ET.parse(boot.sources_xml).getroot()
    assert root.find("files")[0].tag == "default"
    # path entries carry pathversion="1"
    for s in root.find("files").findall("source"):
        assert s.find("path").get("pathversion") == "1"
        assert s.findtext("allowsharing") == "true"


def test_add_file_sources_both_present_with_names_and_paths(boot):
    boot.mod._add_file_sources()
    entries = dict(_files_sources(boot))
    assert entries["special://home"] == "special://home"
    assert entries["special://kodi"] == "/storage/emulated/0/kodi/"
    assert entries[".tony.7.bones"] == "https://tony7bones.github.io/"


def test_add_file_sources_preserves_others_and_normalizes_repo(boot):
    """Unrelated existing sources survive untouched; an existing source pointing at
    our repo URL is RENAMED to the canonical .tony.7.bones (whatever its label)."""
    boot.sources_xml.write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<sources>\n"
        "  <video>\n"
        "    <default></default>\n"
        "    <source><name>Movies</name>"
        "<path>/Users/x/Movies</path><allowsharing>true</allowsharing></source>\n"
        "  </video>\n"
        "  <files>\n"
        "    <default></default>\n"
        "    <source><name>my repo</name>"
        "<path>https://tony7bones.github.io/</path>"
        "<allowsharing>true</allowsharing></source>\n"
        "  </files>\n"
        "</sources>\n"
    )
    boot.mod._add_file_sources()
    root = ET.parse(boot.sources_xml).getroot()
    # the unrelated video/Movies source is preserved untouched
    movies = [s.findtext("name") for s in root.find("video").findall("source")]
    assert "Movies" in movies
    files_entries = _files_sources(boot)
    names = [n for n, _p in files_entries]
    paths = [p for _n, p in files_entries]
    # the repo source was renamed from "my repo" -> canonical, not duplicated
    assert ".tony.7.bones" in names
    assert "my repo" not in names
    assert paths.count("https://tony7bones.github.io/") == 1
    # the home/kodi sources also landed
    assert "special://home" in names
    assert "special://kodi" in names


def test_add_file_sources_normalizes_repo_url_without_slash(boot):
    """A repo source WITHOUT a trailing slash (any label) is renamed to
    .tony.7.bones and its path canonicalized to the trailing-slash form."""
    boot.sources_xml.write_text(
        "<sources><files><default></default>"
        "<source><name>.xyz</name>"
        '<path pathversion="1">https://tony7bones.github.io</path>'
        "<allowsharing>true</allowsharing></source>"
        "</files></sources>"
    )
    boot.mod._add_file_sources()
    entries = dict(_files_sources(boot))
    assert ".xyz" not in entries
    assert entries[".tony.7.bones"] == "https://tony7bones.github.io/"
    paths = [p for _n, p in _files_sources(boot)]
    assert paths.count("https://tony7bones.github.io/") == 1
    assert "https://tony7bones.github.io" not in paths  # no-slash form normalized


def test_add_file_sources_collapses_repo_slash_variants(boot):
    """Both slash variants of the repo URL collapse to a single .tony.7.bones."""
    boot.sources_xml.write_text(
        "<sources><files><default></default>"
        "<source><name>a</name><path>https://tony7bones.github.io</path>"
        "<allowsharing>true</allowsharing></source>"
        "<source><name>b</name><path>https://tony7bones.github.io/</path>"
        "<allowsharing>true</allowsharing></source>"
        "</files></sources>"
    )
    boot.mod._add_file_sources()
    entries = _files_sources(boot)
    names = [n for n, _p in entries]
    paths = [p for _n, p in entries]
    assert names.count(".tony.7.bones") == 1
    assert paths.count("https://tony7bones.github.io/") == 1


def test_add_file_sources_dedupes_on_second_run(boot):
    """Running twice must not duplicate (dedupe on name OR path)."""
    boot.mod._add_file_sources()
    boot.mod._add_file_sources()
    entries = _files_sources(boot)
    assert entries.count(_HOME) == 1
    assert entries.count(_SRC) == 1
    assert entries.count(_T7B) == 1


def test_add_file_sources_dedupes_on_path_with_different_name(boot):
    """A pre-existing source sharing only the PATH must block re-adding."""
    boot.sources_xml.write_text(
        "<sources><files><default></default>"
        "<source><name>my home</name>"
        '<path pathversion="1">special://home</path>'
        "<allowsharing>true</allowsharing></source>"
        "</files></sources>"
    )
    boot.mod._add_file_sources()
    paths = [p for _n, p in _files_sources(boot)]
    # special://home appears exactly once (the pre-existing one), not duplicated
    assert paths.count("special://home") == 1
    # the sources dir was still added
    assert "/storage/emulated/0/kodi/" in paths


def test_add_file_sources_handles_malformed_xml(boot):
    """A corrupt sources.xml must be recreated, not crash the run."""
    boot.sources_xml.write_text("<sources><files><not closed")
    boot.mod._add_file_sources()  # must not raise
    entries = _files_sources(boot)
    assert _HOME in entries
    assert _SRC in entries
    assert _T7B in entries


def test_add_file_sources_attempts_guarded_mkdirs(boot):
    """mkdirs must be ATTEMPTED for the Android path and guarded so a failure
    off Android is harmless — the source entry lands regardless."""
    boot.mod._add_file_sources()
    # the directory-create was attempted on the Android internal-storage path
    assert "/storage/emulated/0/kodi/" in boot.state["mkdirs"], (
        "mkdirs must be attempted for the Android storage path"
    )
    # and even though that mkdirs returns False on this host, the source landed
    paths = [p for _n, p in _files_sources(boot)]
    assert "/storage/emulated/0/kodi/" in paths


def test_add_file_sources_never_raises_on_write_error(boot, monkeypatch):
    """Any failure must be swallowed (never aborts the rest of setup)."""
    real_open = open

    def boom(path, *a, **k):
        if str(path).endswith("sources.xml") and (
            "w" in (a[0] if a else k.get("mode", ""))
        ):
            raise OSError("disk full")
        return real_open(path, *a, **k)

    monkeypatch.setattr("builtins.open", boom)
    boot.mod._add_file_sources()  # must not raise


def test_run_adds_file_sources(boot):
    """A full run must add the two File-Manager sources to sources.xml."""
    boot.mod.run()
    entries = _files_sources(boot)
    assert _HOME in entries
    assert _SRC in entries
    assert _T7B in entries


# --------------------------------------------------------------------------- #
# Estuary home-menu trim (hide 8 items; keep TV, Add-ons, Favourites, Weather)
# --------------------------------------------------------------------------- #
# The eight hide-ids and the four kept-ids, in the exact lowercase form Estuary
# persists in addon_data/skin.estuary/settings.xml (verified on Kodi 21 Omega).
_HIDE_IDS = [
    "homemenunomoviebutton",
    "homemenunotvshowbutton",
    "homemenunomusicbutton",
    "homemenunomusicvideobutton",
    "homemenunoradiobutton",
    "homemenunopicturesbutton",
    "homemenunovideosbutton",
    "homemenunogamesbutton",
]
_KEEP_IDS = [
    "homemenunotvbutton",
    "homemenunoprogramsbutton",
    "homemenunofavbutton",
    "homemenunoweatherbutton",
]


def _estuary_bools(boot):
    """Return {id: text} for every <setting> in the Estuary settings.xml."""
    root = ET.parse(boot.estuary_settings).getroot()
    return {
        (s.get("id") or "").lower(): (s.text or "").strip()
        for s in root.findall("setting")
    }


def test_trim_home_menu_helper_exists_and_wired_before_restart():
    """The helper must still be reachable (a re-export shim over the Foundation
    layer's lifted body) and the Foundation layer it now lives in must be invoked
    in run() BEFORE the restart (the restart is what makes Estuary re-read
    settings.xml). The exact home-trim slot/order is pinned at RUNTIME by the
    modular_setup snapshot; this guards the shim + apply_foundation wiring."""
    src = DEFAULT_PY.read_text()
    assert "_trim_home_menu" in src, "shim must exist"
    assert "_trim_home_menu = _foundation._trim_home_menu" in src, (
        "_trim_home_menu must be a re-export shim over the Foundation layer"
    )
    assert "apply_foundation(" in src, "apply_foundation must be invoked in run()"
    trim_pos = src.rfind("apply_foundation(")
    restart_pos = src.rfind("restart_kodi(")
    assert trim_pos != -1 and restart_pos != -1
    assert trim_pos < restart_pos, "apply_foundation() must come before the restart"


# The eight camel-case ids the skin XML / Skin.SetBool use (the part that
# survives the restart), and the four kept camel-case ids that must never be set.
_HIDE_CAMEL = [
    "HomeMenuNoMovieButton",
    "HomeMenuNoTVShowButton",
    "HomeMenuNoMusicButton",
    "HomeMenuNoMusicVideoButton",
    "HomeMenuNoRadioButton",
    "HomeMenuNoPicturesButton",
    "HomeMenuNoVideosButton",
    "HomeMenuNoGamesButton",
]
_KEEP_CAMEL = [
    "HomeMenuNoTVButton",
    "HomeMenuNoProgramsButton",
    "HomeMenuNoFavButton",
    "HomeMenuNoWeatherButton",
]


def test_trim_home_menu_uses_setbool_for_active_skin(boot):
    """It MUST set the live in-memory skin booleans via Skin.SetBool — that is
    the only mechanism that survives the end-of-setup restart (Kodi rewrites
    settings.xml from memory on shutdown, clobbering a file-only write). It must
    SetBool exactly the eight hide-ids (camel-case) and never the four kept."""
    boot.mod._trim_home_menu()
    setbools = [b for b in boot.state["builtins"] if b.startswith("Skin.SetBool(")]
    for cid in _HIDE_CAMEL:
        assert f"Skin.SetBool({cid})" in setbools, f"must Skin.SetBool({cid})"
    for cid in _KEEP_CAMEL:
        assert f"Skin.SetBool({cid})" not in setbools, f"must NOT set kept {cid}"
    assert len(setbools) == 8, f"exactly 8 SetBool calls expected, got {setbools}"


def test_trim_home_menu_setbool_skipped_on_other_skin(boot, monkeypatch):
    """Off Estuary, no Skin.SetBool is issued (the whole helper no-ops)."""
    monkeypatch.setattr(boot.mod.xbmc, "getSkinDir", lambda: "skin.confluence")
    boot.mod._trim_home_menu()
    assert not any(b.startswith("Skin.SetBool(") for b in boot.state["builtins"])


def test_trim_home_menu_writes_eight_hide_settings(boot):
    """Creates the file and sets all eight hide-booleans to true."""
    assert not boot.estuary_settings.exists()
    boot.mod._trim_home_menu()
    bools = _estuary_bools(boot)
    for sid in _HIDE_IDS:
        assert bools.get(sid) == "true", f"{sid} must be set true (hidden)"
    # exactly the eight singular ids the real skin uses (Movie/MusicVideo/TVShow)
    assert "homemenunomoviebutton" in bools and "homemenunomoviesbutton" not in bools
    assert (
        "homemenunomusicvideobutton" in bools
        and "homemenunomusicvideosbutton" not in bools
    )


def test_trim_home_menu_does_not_set_the_four_kept(boot):
    """The four kept items (TV, Add-ons, Favourites, Weather) must NOT be written
    when starting from no file — they stay visible by their absence."""
    boot.mod._trim_home_menu()
    bools = _estuary_bools(boot)
    for sid in _KEEP_IDS:
        assert sid not in bools, f"{sid} must NOT be set (kept visible)"


def test_trim_home_menu_preserves_existing_settings(boot):
    """Existing unrelated skin settings — and a pre-existing kept-id set to
    false — must survive untouched."""
    boot.estuary_settings.parent.mkdir(parents=True)
    boot.estuary_settings.write_text(
        "<settings>"
        '<setting id="homemenunofavbutton" type="bool">false</setting>'
        '<setting id="no_fanart" type="bool">false</setting>'
        '<setting id="HomeFanart.ext" type="string">.jpg</setting>'
        "</settings>"
    )
    boot.mod._trim_home_menu()
    bools = _estuary_bools(boot)
    # unrelated settings preserved
    assert bools.get("no_fanart") == "false"
    root = ET.parse(boot.estuary_settings).getroot()
    fanart = root.find("setting[@id='HomeFanart.ext']")
    assert fanart is not None and (fanart.text or "") == ".jpg"
    # the pre-existing kept-id stays false (not flipped to hide)
    assert bools.get("homemenunofavbutton") == "false"
    # and the eight hide-ids are now true
    for sid in _HIDE_IDS:
        assert bools.get(sid) == "true"


def test_trim_home_menu_is_idempotent(boot):
    """Running twice must not duplicate <setting> elements or change values."""
    boot.mod._trim_home_menu()
    boot.mod._trim_home_menu()
    root = ET.parse(boot.estuary_settings).getroot()
    ids = [s.get("id") for s in root.findall("setting")]
    for sid in _HIDE_IDS:
        assert ids.count(sid) == 1, f"{sid} duplicated on re-run"
    bools = _estuary_bools(boot)
    for sid in _HIDE_IDS:
        assert bools.get(sid) == "true"


def test_trim_home_menu_noop_on_other_skin(boot, monkeypatch):
    """When the active skin is not Estuary, it must be a safe no-op (write
    nothing)."""
    monkeypatch.setattr(boot.mod.xbmc, "getSkinDir", lambda: "skin.confluence")
    boot.mod._trim_home_menu()
    assert not boot.estuary_settings.exists(), "must not write when skin != estuary"


def test_trim_home_menu_recreates_malformed_file(boot):
    """A corrupt settings.xml must be rebuilt, not crash the run."""
    boot.estuary_settings.parent.mkdir(parents=True)
    boot.estuary_settings.write_text("<settings><setting not closed")
    boot.mod._trim_home_menu()  # must not raise
    bools = _estuary_bools(boot)
    for sid in _HIDE_IDS:
        assert bools.get(sid) == "true"


def test_trim_home_menu_never_raises(boot, monkeypatch):
    """Any failure must be swallowed so it can't abort the rest of setup."""
    real_open = open

    def boom(path, *a, **k):
        if str(path).endswith("settings.xml") and (
            "w" in (a[0] if a else k.get("mode", ""))
        ):
            raise OSError("disk full")
        return real_open(path, *a, **k)

    monkeypatch.setattr("builtins.open", boom)
    boot.mod._trim_home_menu()  # must not raise


def test_run_trims_home_menu(boot):
    """A full run must hide the eight Estuary home items."""
    boot.mod.run()
    bools = _estuary_bools(boot)
    for sid in _HIDE_IDS:
        assert bools.get(sid) == "true"
    for sid in _KEEP_IDS:
        assert sid not in bools


# --------------------------------------------------------------------------- #
# Shared-library wiring + unattended video add-ons (one-tap onboarding)
# --------------------------------------------------------------------------- #
def test_requires_the_shared_module():
    """The manifest must declare the shared library as a required import so Kodi
    auto-installs script.module.tony7bones when this Setup is installed."""
    imp = _addon_root().find("requires/import[@addon='script.module.tony7bones']")
    assert imp is not None, "must <import> script.module.tony7bones"
    assert imp.get("version") == "1.3.0"


def test_imports_from_shared_module():
    """The duplicated machinery is gone — default.py imports it from the library."""
    src = DEFAULT_PY.read_text()
    assert "from tony7bones import" in src
    # the moved helpers must NOT be redefined locally any more
    assert "def _resolve_closure" not in src
    assert "def _install_with_deps" not in src
    assert "def _platform_tag" not in src
    assert "def _self_uninstall" not in src
    assert "def _restart_kodi" not in src
    # the folded video entry point comes from the library now
    assert "install_selection" in src


def test_no_video_picker_in_source():
    """The video picker is gone — no prompt, no multiselect. Video installs
    unattended as part of one-tap onboarding."""
    src = DEFAULT_PY.read_text()
    assert "_ask_also_video" not in src
    assert "multiselect" not in src
    assert "Include video" not in src


def test_video_apps_are_the_four_without_umbrella(boot):
    """VIDEO_APPS is exactly POV + The Loop + Sports HD + YouTube — Umbrella dropped."""
    assert boot.mod.VIDEO_APPS == [
        "plugin.video.pov",
        "plugin.video.the-loop",
        "plugin.video.sporthdme",
        "plugin.video.youtube",
    ]
    assert "plugin.video.umbrella" not in boot.mod.VIDEO_APPS


def test_video_installs_unattended(boot, monkeypatch):
    """run() installs the curated video apps via the shared library with NO prompt
    and reports them in the single combined summary."""
    calls = []

    def _stub(selected, official_base, disable_ids, dialog, log):
        calls.append((list(selected), set(disable_ids)))
        return len(selected)

    # The video install body moved to tony7bones.setup.addons (Phase 2c) and
    # resolves install_selection from THAT module's globals, so patch it there (the
    # repointed boot.mod patch — no deps-injection seam, per the Tech-debt ledger).
    monkeypatch.setattr(boot.mod._addons, "install_selection", _stub)
    boot.mod.run()

    # _addons.install_selection drives the video apps; find the video call.
    video_call = next((c for c in calls if "plugin.video.pov" in c[0]), None)
    assert video_call is not None, "video apps must install via install_selection"
    assert video_call[0] == [
        "plugin.video.pov",
        "plugin.video.the-loop",
        "plugin.video.sporthdme",
        "plugin.video.youtube",
    ]
    assert "plugin.video.dailymotion_com" in video_call[1]
    # no picker was ever shown
    assert not boot.state.get("multiselect")
    # the single combined summary reports the video count
    _title, msg = boot.state["ok"][-1]
    assert "Video add-ons: 4/4" in msg
    # exactly one restart prompt for the whole run
    restarts = [m for _t, m in boot.state.get("yesno", []) if "needs to restart" in m]
    assert len(restarts) == 1


def test_video_failure_is_nonfatal(boot, monkeypatch):
    """A video install failure must not abort the box: base still installs and the
    summary reports 0 video add-ons."""

    def _boom(*a, **k):
        raise RuntimeError("video boom")

    # Video install resolves install_selection from the addons module (Phase 2c).
    monkeypatch.setattr(boot.mod._addons, "install_selection", _boom)
    boot.mod.run()

    for aid in boot.mod.ADDONS:
        assert aid in boot.state["installed"]
    _title, msg = boot.state["ok"][-1]
    assert "Video add-ons: 0/4" in msg


def test_skin_install_resolves_closure_and_sets_skin(boot, monkeypatch):
    """run() direct-installs pvr.artwork (the proxy-invisible, GitHub-only dep),
    resolves the skin + patch closure via install_selection, and sets
    lookandfeel.skin so the end-of-Setup restart activates Estuary MOD V2."""
    sel_calls = []
    extracted = []

    def _sel(selected, official_base, disable_ids, dialog, log):
        sel_calls.append(list(selected))
        for aid in selected:  # mark installed so the set-skin guard passes
            boot.state["installed"].add(aid)
        return len(selected)

    def _extract(url, dialog, pct, log):
        extracted.append(url)
        if "pvr.artwork" in url:
            boot.state["installed"].add(boot.mod.PVR_ARTWORK_ID)
        if "modv2plus" in url:
            boot.state["installed"].add(boot.mod.MODV2PLUS_ID)
        return True

    # Phase 3a: run_express calls apply_foundation via the BARE form (the deps-
    # injection seam is killed — Tech-debt ledger), so the skin closure resolves its
    # primitives from the FOUNDATION module's globals, not boot.mod's. Patch the
    # stubs onto _foundation (where the skin closure now lives) as well as boot.mod.
    # _addons gets them too for the base/video install. (Same repointing pattern
    # Phase 2c/2d used; the stub objects are identical, so behaviour is unchanged.)
    for tgt in (boot.mod, boot.mod._foundation, boot.mod._addons):
        monkeypatch.setattr(tgt, "install_selection", _sel, raising=False)
        monkeypatch.setattr(tgt, "extract_zip", _extract, raising=False)
        monkeypatch.setattr(
            tgt, "install_with_deps", lambda *a, **k: True, raising=False
        )
        monkeypatch.setattr(
            tgt,
            "_latest_zip_url",
            lambda aid: "http://local/{}-9.9.9.zip".format(aid),
            raising=False,
        )
    boot.mod.run()

    # BOTH proxy-invisible first-party pieces are direct-extracted: pvr.artwork
    # (GitHub-only) and our own modv2plus patch add-on (proxy-only).
    assert any("script.module.pvr.artwork-2.2.10.zip" in u for u in extracted), (
        "pvr.artwork must be direct-installed from the hosted mirror"
    )
    assert any("script.tony7bones.modv2plus" in u for u in extracted), (
        "modv2plus must be direct-installed (resolver can't see our proxy)"
    )
    # the skin itself resolves via install_selection from the installed repos
    assert ["skin.estuary.modv2"] in sel_calls
    # lookandfeel.skin set (set-and-restart activation, no modal)
    assert any(
        "lookandfeel.skin" in s and "skin.estuary.modv2" in s
        for s in boot.state["jsonrpc"]
    ), "must set lookandfeel.skin so the restart activates MOD V2"
    # summary reports the skin installed
    _title, msg = boot.state["ok"][-1]
    assert "Estuary MOD V2: installed" in msg


def test_video_runs_before_self_uninstall_and_restart(boot, monkeypatch):
    """Ordering guard (Phase 3a): the curated video install runs BEFORE the
    self-uninstall, which runs BEFORE the restart.

    run() no longer calls a bare `_install_video(dialog)` — the video install moved
    INTO apply_addons (Phase 2c) and run_express drives the composed layers. The
    ORDERING INTENT is unchanged and is now pinned at RUNTIME (surviving the
    decomposition) by spying the imported symbols run_express actually calls:
    install_selection (which apply_addons drives to install the video closure),
    self_uninstall, and restart_kodi — asserting that call order. The full
    skin/video success stubs make the run reach the terminal seam."""
    events = []

    def _wrap(name):
        real = getattr(boot.mod, name)

        def _w(*a, **k):
            events.append(name)
            return real(*a, **k)

        return _w

    # Drive video install to success and reach the terminal seam (same technique as
    # the snapshot's _stub_skin_and_video_success: patch the layer modules).
    def _sel(selected, official_base, disable_ids, dialog, log):
        events.append("install_selection")
        for aid in selected:
            boot.state["extracted"].add(aid)
            boot.state["installed"].add(aid)
        return len(selected)

    def _extract(url, dialog, pct, log):
        if "pvr.artwork" in url:
            boot.state["installed"].add(boot.mod.PVR_ARTWORK_ID)
        if "modv2plus" in url:
            boot.state["installed"].add(boot.mod.MODV2PLUS_ID)
        return True

    for tgt in (boot.mod, boot.mod._addons, boot.mod._foundation):
        monkeypatch.setattr(tgt, "install_selection", _sel, raising=False)
        monkeypatch.setattr(tgt, "extract_zip", _extract, raising=False)
        monkeypatch.setattr(
            tgt, "install_with_deps", lambda *a, **k: True, raising=False
        )
        monkeypatch.setattr(
            tgt,
            "_latest_zip_url",
            lambda aid: f"http://local/{aid}-9.9.9.zip",
            raising=False,
        )
    monkeypatch.setattr(boot.mod._iptv, "install_with_deps", lambda *a, **k: True)
    monkeypatch.setattr(boot.mod, "self_uninstall", _wrap("self_uninstall"))
    monkeypatch.setattr(boot.mod, "restart_kodi", _wrap("restart_kodi"))

    boot.mod.run()

    # The first install_selection (video closure) precedes self_uninstall precedes
    # restart_kodi. (install_selection also resolves the skin closure later; we pin
    # the FIRST occurrence as the video install.)
    assert "install_selection" in events
    assert "self_uninstall" in events and "restart_kodi" in events
    iv = events.index("install_selection")
    un = events.index("self_uninstall")
    rs = events.index("restart_kodi")
    assert iv < un < rs, (
        f"order must be video-install -> self-uninstall -> restart: {events}"
    )


# --------------------------------------------------------------------------- #
# Base box configuration (_configure_box): weather provider + Sacramento
# location, RSS news ticker off, Estuary top-bar weather.
# --------------------------------------------------------------------------- #
def _settings_set(boot):
    """{setting_id: value} from captured Settings.SetSettingValue JSON-RPC calls."""
    out = {}
    for s in boot.state["jsonrpc"]:
        try:
            d = _json.loads(s)
        except ValueError:
            continue
        if d.get("method") == "Settings.SetSettingValue":
            out[d["params"]["setting"]] = d["params"]["value"]
    return out


def test_box_configuration_runs_before_restart(boot, monkeypatch):
    """The base-box configuration (weather provider + RSS-enable core settings, the
    Estuary top-bar weather toggle) must be applied BEFORE the restart, so Kodi
    re-reads it on the single end-of-setup restart.

    Phase 3a: run() no longer calls a monolithic `_configure_box(box_env)` — the
    config moved INTO the composed layers (apply_addons writes the weather/RSS core
    settings; run_express sets the top-bar weather bool) and run_express owns the
    terminal restart. The ordering INTENT survives the decomposition and is pinned
    at RUNTIME: the weather.addon + lookandfeel.enablerssfeeds settings and the
    show_weatherinfo Skin.SetBool are all emitted before restart_kodi is invoked."""
    restart_at = {"settings": None, "builtins": None}
    real_restart = boot.mod.restart_kodi

    def _restart(*a, **k):
        # Snapshot how many config effects have landed at restart time.
        restart_at["settings"] = list(boot.state["jsonrpc"])
        restart_at["builtins"] = list(boot.state["builtins"])
        return real_restart(*a, **k)

    monkeypatch.setattr(boot.mod, "restart_kodi", _restart)
    boot.mod.run()

    assert restart_at["settings"] is not None, "run() must reach the restart"
    # The two core config settings were emitted before the restart.
    joined = "".join(restart_at["settings"])
    assert "weather.addon" in joined, "weather provider must be set before restart"
    assert "lookandfeel.enablerssfeeds" in joined, "RSS must be enabled before restart"
    # The Estuary top-bar weather toggle landed before the restart too.
    assert "Skin.SetBool(show_weatherinfo)" in restart_at["builtins"], (
        "top-bar weather toggle must be set before the restart"
    )


def test_configure_box_still_callable_standalone(boot):
    """`_configure_box(box_env)` remains a callable pure-consumer helper (it neither
    reads nor deletes the env) even though run_express no longer drives it — the
    standalone weather/RSS/IPTV config tests below exercise it directly. This pins
    that the helper was not deleted, only un-wired from the orchestrator path."""
    assert callable(boot.mod._configure_box)
    boot.mod._configure_box({})  # must not raise
    assert _settings_set(boot).get("weather.addon") == "weather.multi"


def test_configure_box_sets_weather_provider(boot):
    boot.mod._configure_box()
    assert _settings_set(boot).get("weather.addon") == "weather.multi"


def test_configure_box_enables_rss_feeds(boot):
    boot.mod._configure_box()
    assert _settings_set(boot).get("lookandfeel.enablerssfeeds") is True


def test_configure_box_writes_sacramento_location(boot):
    boot.mod._configure_box()
    path = boot.mod._weather_multi_settings_path()
    vals = {
        s.get("id"): (s.text or "") for s in ET.parse(path).getroot().findall("setting")
    }
    assert vals.get("loc1_name") == "Sacramento, CA, US"
    # loc1_url is the load-bearing field: weather.multi fetches the forecast from
    # https://weather.yahoo.com/<loc1_url>; an empty url means no fetch at all.
    assert vals.get("loc1_url") == "us/ca/sacramento", "fetch url must be written"
    assert vals.get("loc1_lat") and vals.get("loc1_lon"), "coords must be written"


def test_configure_box_sets_topbar_weather_skin_bool(boot):
    boot.mod._configure_box()
    assert "Skin.SetBool(show_weatherinfo)" in boot.state["builtins"]


def test_configure_box_topbar_skipped_off_estuary_but_core_settings_apply(
    boot, monkeypatch
):
    monkeypatch.setattr(boot.mod.xbmc, "getSkinDir", lambda: "skin.confluence")
    boot.mod._configure_box()
    assert "Skin.SetBool(show_weatherinfo)" not in boot.state["builtins"]
    # Core (non-skin) settings still apply regardless of skin.
    assert _settings_set(boot).get("weather.addon") == "weather.multi"


def test_configure_box_never_raises(boot, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("boom")

    monkeypatch.setattr(boot.mod.xbmc, "executeJSONRPC", boom)
    boot.mod._configure_box()  # must not raise


def test_run_configures_box(boot):
    boot.mod.run()
    s = _settings_set(boot)
    assert s.get("weather.addon") == "weather.multi"
    assert s.get("lookandfeel.enablerssfeeds") is True


# --------------------------------------------------------------------------- #
# Per-device env LIFECYCLE OWNERSHIP (Phase 1 of modular-setup).
#
# The orchestrator run() — not _configure_box — owns reading and DELETING the
# per-device tony7bones.env. _configure_box is a pure consumer of the dict passed
# into it: it must make ZERO read_box_env / os.remove calls. run() must read the
# env exactly once and delete it exactly once, AFTER configuration completes. This
# is what lets a future multi-gate Guided flow share the env across gates instead
# of having an early layer delete it out from under a later one.
# --------------------------------------------------------------------------- #
def test_configure_box_does_not_read_or_delete_env(boot, monkeypatch):
    """_configure_box must neither read_box_env nor os.remove — env lifecycle is
    the orchestrator's job. Spies prove zero calls (mutation guard: re-adding a
    read/delete inside _configure_box flips these counts and fails)."""
    reads = {"n": 0}
    removes = {"n": 0}
    real_read = boot.mod.read_box_env
    real_remove = boot.mod.os.remove

    def _spy_read(*a, **k):
        reads["n"] += 1
        return real_read(*a, **k)

    def _spy_remove(*a, **k):
        removes["n"] += 1
        return real_remove(*a, **k)

    monkeypatch.setattr(boot.mod, "read_box_env", _spy_read)
    monkeypatch.setattr(boot.mod.os, "remove", _spy_remove)

    boot.mod._configure_box({"DEVICE_NAME": "Office"})

    assert reads["n"] == 0, "_configure_box must not read the env (orchestrator does)"
    assert removes["n"] == 0, (
        "_configure_box must not delete the env (orchestrator does)"
    )


def test_configure_box_consumes_passed_env_not_the_file(boot, monkeypatch, tmp_path):
    """The env _configure_box acts on is the dict PASSED IN, never one it reads from
    BOX_ENV_PATH. Point BOX_ENV_PATH at a file with a DIFFERENT OWM key; pass an env
    carrying its own OWM key -> the OWM key Multi Weather stores (MAPAPI) is the one
    from the PASSED env, proving _configure_box ignored the file entirely."""
    # A file on disk that, if _configure_box (wrongly) read it, would win.
    envfile = tmp_path / "tony7bones.env"
    envfile.write_text('OWM_API_KEY="from-file-should-be-ignored"\n')
    monkeypatch.setattr(boot.mod, "BOX_ENV_PATH", str(envfile))

    boot.mod._configure_box({"OWM_API_KEY": "from-passed-dict"})

    path = boot.mod._weather_multi_settings_path()
    vals = {
        s.get("id"): (s.text or "") for s in ET.parse(path).getroot().findall("setting")
    }
    # MAPAPI is where _apply_weather_from_env stores the OWM key. It must reflect the
    # PASSED dict, not the on-disk file.
    assert vals.get("MAPAPI") == "from-passed-dict"
    # And the file is left untouched (no delete happened in _configure_box).
    assert envfile.exists(), "_configure_box must not delete BOX_ENV_PATH"


def test_run_reads_env_once_and_deletes_after_express(boot, monkeypatch, tmp_path):
    """run() owns the env lifecycle: it reads BOX_ENV_PATH exactly once, passes the
    parsed dict into run_express (which drives the composed layers that CONSUME the
    env), and deletes the file exactly once AFTER run_express returns. Spies record
    call order so 'delete after the env is consumed' is a runtime observation, not a
    source grep.

    Phase 3a: run() no longer calls `_configure_box` — the env-consuming work moved
    into run_express's composed layers (apply_addons/foundation/iptv). The lifecycle
    INTENT is unchanged (read once -> consume -> delete after), so the spy now wraps
    run_express (the consumer) instead of the retired _configure_box call site. The
    delete-after-consume ordering is what lets a future multi-gate flow share the
    env across gates."""
    envfile = tmp_path / "tony7bones.env"
    envfile.write_text('DEVICE_NAME="Office"\nWEATHER_LOCATIONS="Sacramento, CA"\n')
    monkeypatch.setattr(boot.mod, "BOX_ENV_PATH", str(envfile))

    events = []
    real_read = boot.mod.read_box_env
    real_remove = boot.mod.os.remove
    real_express = boot.mod.run_express

    def _read(path, *a, **k):
        events.append(("read", path))
        return real_read(path, *a, **k)

    def _remove(path, *a, **k):
        # Only record removals of the env file — run() also removes other paths
        # (self_uninstall, etc.); those are not the lifecycle under test.
        if path == str(envfile):
            events.append(("remove", path))
        return real_remove(path, *a, **k)

    def _express(box_env=None, *a, **k):
        # The env dict the orchestrator parsed is passed straight through.
        events.append(("express_start", box_env))
        out = real_express(box_env, *a, **k)
        events.append(("express_end", None))
        return out

    monkeypatch.setattr(boot.mod, "read_box_env", _read)
    monkeypatch.setattr(boot.mod.os, "remove", _remove)
    monkeypatch.setattr(boot.mod, "run_express", _express)

    boot.mod.run()

    kinds = [e[0] for e in events]
    # Exactly one read of BOX_ENV_PATH, exactly one remove of it.
    assert kinds.count("read") == 1, f"run() must read the env once, got {events}"
    assert kinds.count("remove") == 1, f"run() must delete the env once, got {events}"
    read_event = next(e for e in events if e[0] == "read")
    remove_event = next(e for e in events if e[0] == "remove")
    assert read_event[1] == str(envfile)
    assert remove_event[1] == str(envfile)
    # The parsed env dict is what run_express received (read-once feeds the consumer).
    express_event = next(e for e in events if e[0] == "express_start")
    assert express_event[1].get("DEVICE_NAME") == "Office", (
        "run() must pass the parsed env dict into run_express"
    )
    # Order: read -> express_start -> express_end -> remove. The delete happens AFTER
    # the layers consumed the env (so a future gate could still read it if the
    # orchestrator deferred the delete).
    assert kinds.index("read") < kinds.index("express_start")
    assert kinds.index("express_end") < kinds.index("remove")
    # And the file is actually gone (the real remove ran).
    assert not envfile.exists(), "run() must delete the env file on the env path"


def test_run_no_env_does_not_delete(boot, monkeypatch, tmp_path):
    """On a no-env run (every env candidate absent), run() routes to the
    Guided wizard (Phase N1 — the no-computer path; routing matrix pinned in
    test_no_computer_routing.py) and never attempts an env delete: os.remove
    is not called for the env path, and no Express install runs."""
    envpath = str(tmp_path / "absent" / "tony7bones.env")
    monkeypatch.setattr(boot.mod, "BOX_ENV_PATH", envpath)
    removes = {"env": 0}
    real_remove = boot.mod.os.remove

    def _remove(path, *a, **k):
        # Count only attempts to delete the env file; run() removes other paths.
        if path == envpath:
            removes["env"] += 1
        return real_remove(path, *a, **k)

    monkeypatch.setattr(boot.mod.os, "remove", _remove)

    boot.mod.run()

    assert removes["env"] == 0, "no-env run must not attempt to delete the env"
    # N1: the no-env launch is the WIZARD, not Express — nothing installs on a
    # declined (unscripted) menu, and the wizard menu was actually shown.
    assert boot.state["installed"] == set(), "no-env run must install nothing"
    assert boot.state["select"], "no-env run must show the Guided wizard menu"


# --------------------------------------------------------------------------- #
# Device → userdata file copies (DEVICE_FILE_COPIES / _copy_device_files, called
# from _configure_box). The sources are device /storage/emulated/0/kodi/ paths;
# on the test host they do not exist, so we point DEVICE_FILE_COPIES at real temp
# files to exercise the copy path, and leave them unmapped for the guarded-skip
# path. Covers the custom RssFeeds.xml plus pvr.iptvsimple's instance settings
# and custom TV channel groups (whose channelGroups/ dir must be auto-created).
# --------------------------------------------------------------------------- #
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


def test_default_device_file_copies_are_the_three_expected(boot):
    """The data-driven list must hold the RSS feed + the two pvr.iptvsimple files,
    each to userdata/addon_data (private config never goes near the repo)."""
    dsts = [d for _s, d in boot.mod.DEVICE_FILE_COPIES]
    assert _RSS_DST in dsts
    assert _IPTV_INSTANCE_DST in dsts
    assert _IPTV_GROUPS_DST in dsts
    assert len(boot.mod.DEVICE_FILE_COPIES) == 3
    # Every source is a device path; every dest lives under userdata.
    for src, dst in boot.mod.DEVICE_FILE_COPIES:
        assert src.startswith("/storage/")
        assert dst.startswith("special://home/userdata/")


def _point_copies(boot, monkeypatch, tmp_path, mapping):
    """Repoint DEVICE_FILE_COPIES so the given special:// dests read from temp
    files (others get a guaranteed-missing source).

    Phase 2d: _copy_device_files moved to tony7bones.setup.iptv and loops over
    THAT module's DEVICE_FILE_COPIES, so the patch targets boot.mod._iptv (the
    repointed boot.mod patch — no deps-injection seam), not the bootstrap
    re-export. boot.mod.DEVICE_FILE_COPIES is still read to build the mapping (it
    is the same list object)."""
    new = []
    for src, dst in boot.mod.DEVICE_FILE_COPIES:
        if dst in mapping:
            new.append((str(mapping[dst]), dst))
        else:
            new.append((str(tmp_path / "missing" / os.path.basename(src)), dst))
    monkeypatch.setattr(boot.mod._iptv, "DEVICE_FILE_COPIES", new)


def test_copy_device_files_copies_rss_when_source_present(boot, monkeypatch, tmp_path):
    src = tmp_path / "RssFeeds.xml"
    src.write_text("<rssfeeds>CUSTOM</rssfeeds>")
    _point_copies(boot, monkeypatch, tmp_path, {_RSS_DST: src})
    boot.mod._copy_device_files()
    dst = _dst_path(boot, _RSS_DST)
    assert os.path.exists(dst), "custom RssFeeds.xml must be copied to userdata"
    assert "CUSTOM" in open(dst).read()


def test_copy_device_files_copies_iptv_instance_settings(boot, monkeypatch, tmp_path):
    src = tmp_path / "instance-settings-1.xml"
    src.write_text("<settings>INSTANCE</settings>")
    _point_copies(boot, monkeypatch, tmp_path, {_IPTV_INSTANCE_DST: src})
    boot.mod._copy_device_files()
    dst = _dst_path(boot, _IPTV_INSTANCE_DST)
    assert os.path.exists(dst), "instance-settings-1.xml must be copied to addon_data"
    assert "INSTANCE" in open(dst).read()
    # The addon_data/pvr.iptvsimple/ dir must have been created on the fresh box.
    assert os.path.isdir(os.path.dirname(dst))


def test_copy_device_files_copies_tv_groups_creating_channelgroups_dir(
    boot, monkeypatch, tmp_path
):
    """The customTVGroups copy must auto-create the channelGroups/ subdir, which
    does NOT exist on a fresh box, then land the file inside it."""
    src = tmp_path / "customTVGroups-Network24.xml"
    src.write_text("<groups>NET24</groups>")
    _point_copies(boot, monkeypatch, tmp_path, {_IPTV_GROUPS_DST: src})
    dst = _dst_path(boot, _IPTV_GROUPS_DST)
    # Prove the channelGroups/ dir is absent before the copy runs.
    assert not os.path.isdir(os.path.dirname(dst))
    boot.mod._copy_device_files()
    assert os.path.isdir(os.path.dirname(dst)), "channelGroups/ must be auto-created"
    assert os.path.exists(dst) and "NET24" in open(dst).read()


def test_copy_device_files_skips_when_source_missing(boot, monkeypatch, tmp_path):
    # All sources point at non-existent files (the default /storage path stand-in).
    _point_copies(boot, monkeypatch, tmp_path, {})
    boot.mod._copy_device_files()  # guarded no-op
    for special in (_RSS_DST, _IPTV_INSTANCE_DST, _IPTV_GROUPS_DST):
        assert not os.path.exists(_dst_path(boot, special)), "no copy when src absent"


def test_copy_device_files_overwrites_existing_destinations(
    boot, monkeypatch, tmp_path
):
    # Seed each destination with old content, then copy custom content over it.
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
    boot.mod._copy_device_files()
    for special, (_fname, content) in seeds.items():
        got = open(_dst_path(boot, special)).read()
        assert content in got and "DEFAULT" not in got, f"must overwrite {special}"


def test_copy_device_files_never_raises(boot, monkeypatch):
    # Even if xbmcvfs.copy blows up for every entry, the step must swallow each
    # error and continue through the rest of the list.
    def boom(*a, **k):
        raise RuntimeError("boom")

    monkeypatch.setattr(boot.mod.xbmcvfs, "exists", lambda p: True)
    monkeypatch.setattr(boot.mod.xbmcvfs, "copy", boom)
    boot.mod._copy_device_files()  # must not raise


def test_configure_box_default_sources_missing_is_guarded(boot):
    # With the real default /storage/... sources the files cannot exist on the
    # test host: _configure_box must still complete and apply the other settings
    # without raising or copying anything. The two USER-PROVIDED-ONLY copies (RSS
    # feeds + custom TV groups) must NOT appear. And with NO custom-groups file
    # present, the IPTV enforce is gated OFF: it must not force tvGroupMode=2 at a
    # missing file (which would empty the channel list — the no-env contract).
    boot.mod._configure_box()
    for special in (_RSS_DST, _IPTV_GROUPS_DST):
        assert not os.path.exists(_dst_path(boot, special)), "no copy on desktop"
    inst = _dst_path(boot, _IPTV_INSTANCE_DST)
    if os.path.exists(inst):
        got = _read_instance_settings(boot)
        assert got.get("tvGroupMode") != "2", (
            "must not force custom mode w/o a groups file"
        )
    assert _settings_set(boot).get("weather.addon") == "weather.multi"


# --------------------------------------------------------------------------- #
# IPTV custom-TV-groups instance-settings keys (1a/1b). These are pvr.iptvsimple
# INSTANCE settings — they live ONLY in instance-settings-1.xml (JSON-RPC's
# Settings.SetSettingValue cannot reach add-on instance settings), so the Setup
# enforces them by writing that file directly, after the device-file copy.
# --------------------------------------------------------------------------- #


def _read_instance_settings(boot):
    """Parse instance-settings-1.xml and return {id: text} for its <setting>s."""
    path = _dst_path(boot, boot.mod.IPTV_INSTANCE_SETTINGS_SPECIAL)
    root = ET.parse(path).getroot()
    return {s.get("id"): (s.text or "") for s in root.findall("setting")}


def _make_groups_file(boot):
    """Create the custom-TV-groups file the IPTV enforce now GATES on, so the
    enforce actually runs in these tests (post no-env-contract fix)."""
    path = boot.mod.xbmcvfs.translatePath(boot.mod.IPTV_CUSTOM_TV_GROUPS_FILE_VALUE)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(
            "<customChannelGroups><channelGroupName>X</channelGroupName>"
            "</customChannelGroups>"
        )
    return path


def test_ensure_iptv_groups_constants_match_schema(boot):
    """The enforced values must be the schema's CUSTOM_GROUPS enum (2) and a
    channelGroups path pointing at the Network24 file we copy.

    Phase 2d: the IPTV instance-settings constants moved to
    tony7bones.setup.iptv; assert the live VALUES via the bootstrap re-exports
    (boot.mod.*) rather than source-grepping default.py, so the check survives the
    move and stays a behavioural assertion on the actual enforced values."""
    assert boot.mod.IPTV_TV_GROUP_MODE_CUSTOM == "2"
    assert boot.mod.IPTV_TV_GROUP_MODE_KEY == "tvGroupMode"
    assert boot.mod.IPTV_CUSTOM_TV_GROUPS_FILE_KEY == "customTvGroupsFile"
    assert boot.mod.IPTV_CUSTOM_TV_GROUPS_FILE_VALUE.endswith(
        "customTVGroups-Network24.xml"
    )
    assert boot.mod.IPTV_TV_CHANNEL_GROUPS_ONLY_KEY == "tvChannelGroupsOnly"


def test_ensure_iptv_groups_creates_file_when_absent(boot):
    """On a fresh box with no copied instance-settings file, the step creates one
    with both keys correct (and the addon_data dir)."""
    path = _dst_path(boot, boot.mod.IPTV_INSTANCE_SETTINGS_SPECIAL)
    assert not os.path.exists(path)
    _make_groups_file(boot)
    boot.mod._ensure_iptv_custom_tv_groups()
    got = _read_instance_settings(boot)
    assert got["tvGroupMode"] == "2"
    assert got["customTvGroupsFile"].endswith("customTVGroups-Network24.xml")
    assert "channelGroups" in got["customTvGroupsFile"]
    assert got["tvChannelGroupsOnly"] == "true"


def test_ensure_iptv_groups_patches_copied_file(boot):
    """When the user's instance-settings-1.xml was copied with the DEFAULT
    tvGroupMode=0 + example file, the step rewrites both keys and preserves the
    other settings (e.g. m3uUrl)."""
    path = _dst_path(boot, boot.mod.IPTV_INSTANCE_SETTINGS_SPECIAL)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(
            '<settings version="2">'
            '<setting id="m3uUrl">http://example/list.m3u</setting>'
            '<setting id="tvGroupMode" default="true">0</setting>'
            '<setting id="customTvGroupsFile" default="true">'
            "special://userdata/addon_data/pvr.iptvsimple/channelGroups/"
            "customTVGroups-example.xml</setting>"
            "</settings>"
        )
    _make_groups_file(boot)
    boot.mod._ensure_iptv_custom_tv_groups()
    got = _read_instance_settings(boot)
    assert got["tvGroupMode"] == "2"
    assert got["customTvGroupsFile"].endswith("customTVGroups-Network24.xml")
    # Unrelated user settings survive untouched.
    assert got["m3uUrl"] == "http://example/list.m3u"
    # The default="true" flag is dropped on the keys we now override.
    root = ET.parse(path).getroot()
    for s in root.findall("setting"):
        if s.get("id") in ("tvGroupMode", "customTvGroupsFile"):
            assert s.get("default") is None


def test_ensure_iptv_groups_respects_user_value_when_already_custom(boot):
    """If the copied file already sets tvGroupMode=2 + the Network24 file, the
    step is a no-op (no rewrite needed) and the values stay correct."""
    path = _dst_path(boot, boot.mod.IPTV_INSTANCE_SETTINGS_SPECIAL)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    good_file = boot.mod.IPTV_CUSTOM_TV_GROUPS_FILE_VALUE
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
    boot.mod._ensure_iptv_custom_tv_groups()
    got = _read_instance_settings(boot)
    assert got["tvGroupMode"] == "2"
    assert got["customTvGroupsFile"] == good_file
    assert got["tvChannelGroupsOnly"] == "true"
    # No-op: content unchanged byte-for-byte.
    assert open(path).read() == before


def test_ensure_iptv_groups_recreates_malformed_file(boot):
    """A malformed instance-settings file is replaced with a valid one carrying
    both keys, never raising."""
    path = _dst_path(boot, boot.mod.IPTV_INSTANCE_SETTINGS_SPECIAL)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write("<settings><not-closed>")
    _make_groups_file(boot)
    boot.mod._ensure_iptv_custom_tv_groups()
    got = _read_instance_settings(boot)
    assert got["tvGroupMode"] == "2"
    assert got["customTvGroupsFile"].endswith("customTVGroups-Network24.xml")


def test_ensure_iptv_groups_is_idempotent(boot):
    """Two runs converge — second run changes nothing."""
    _make_groups_file(boot)
    boot.mod._ensure_iptv_custom_tv_groups()
    path = _dst_path(boot, boot.mod.IPTV_INSTANCE_SETTINGS_SPECIAL)
    first = open(path).read()
    boot.mod._ensure_iptv_custom_tv_groups()
    assert open(path).read() == first


def test_ensure_iptv_groups_never_raises(boot, monkeypatch):
    """Any write failure is swallowed (never aborts the rest of setup)."""

    def boom(*a, **k):
        raise RuntimeError("boom")

    # makedirs is the first filesystem op in the step — make it explode.
    monkeypatch.setattr(boot.mod.os, "makedirs", boom)
    boot.mod._ensure_iptv_custom_tv_groups()  # must not raise


def test_ensure_iptv_groups_wired_into_configure_box_after_copy():
    """_configure_box must call the enforce step, and AFTER the device-file copy
    (so it patches the copied file rather than being overwritten by it)."""
    src = DEFAULT_PY.read_text()
    assert "_ensure_iptv_custom_tv_groups(box_env)" in src
    copy_at = src.find("_copy_device_files()", src.find("def _configure_box"))
    ensure_at = src.find(
        "_ensure_iptv_custom_tv_groups(box_env)", src.find("def _configure_box")
    )
    assert 0 < copy_at < ensure_at, "enforce step must run after the copy"


# --------------------------------------------------------------------------- #
# Per-device config (tony7bones.env) parser — Phase 1 of env consolidation.
# Cases per the QA-mandated robustness list.
# --------------------------------------------------------------------------- #


def test_parse_env_basic_quotes_and_empty(boot):
    env = boot.mod.parse_env('DEVICE_NAME="Bedroom TV"\nIPTV_NAME=Network 24\nEMPTY=\n')
    assert env["DEVICE_NAME"] == "Bedroom TV"  # surrounding quotes stripped
    assert env["IPTV_NAME"] == "Network 24"  # unquoted value with a space
    assert env["EMPTY"] == ""  # empty value preserved


def test_parse_env_inline_comment_only_when_unquoted(boot):
    env = boot.mod.parse_env(
        'KEY="8090329db7d84dae"   # forecast key\nBARE=value   # note\nHASH="a#b"\n'
    )
    assert env["KEY"] == "8090329db7d84dae"  # inline comment dropped
    assert env["BARE"] == "value"  # unquoted inline comment dropped
    assert env["HASH"] == "a#b"  # '#' inside quotes is kept


def test_parse_env_skips_comments_blanks_and_no_equals(boot):
    env = boot.mod.parse_env("# comment\n\n   \nnot_a_setting\nOK=1\n")
    assert env == {"OK": "1"}


def test_parse_env_keeps_semicolons_in_value(boot):
    env = boot.mod.parse_env('M3U="http://h/get?a=1&b=2"\nLIST="x; y; z"\n')
    assert env["M3U"] == "http://h/get?a=1&b=2"
    assert env["LIST"] == "x; y; z"  # parse_env never splits
    assert boot.mod.split_list(env["LIST"]) == ["x", "y", "z"]  # split_list does


def test_parse_env_handles_crlf(boot):
    assert boot.mod.parse_env('A="x"\r\nB="y"\r\n') == {"A": "x", "B": "y"}


def test_split_list_trims_and_drops_empties(boot):
    assert boot.mod.split_list("Sacramento, CA; Yuba City, CA ;; Reno, NV ") == [
        "Sacramento, CA",
        "Yuba City, CA",
        "Reno, NV",
    ]
    assert boot.mod.split_list("") == []
    assert boot.mod.split_list(None) == []


def test_read_box_env_absent_returns_empty(boot, tmp_path):
    assert boot.mod.read_box_env(str(tmp_path / "nope.env")) == {}


def test_read_box_env_reads_file(boot, tmp_path):
    p = tmp_path / "tony7bones.env"
    p.write_text('DEVICE_NAME="Office"\nWEATHER_LOCATIONS="A; B"\n')
    env = boot.mod.read_box_env(str(p))
    assert env["DEVICE_NAME"] == "Office"
    assert boot.mod.split_list(env["WEATHER_LOCATIONS"]) == ["A", "B"]


def test_ensure_iptv_groups_skipped_when_no_groups_file(boot):
    """No custom-groups file present -> the enforce is a NO-OP (leaves the
    all-channels default; never points tvGroupMode=2 at a missing file). This is
    the no-env IPTV contract — QA criterion A, a regression that shipped before."""
    path = _dst_path(boot, boot.mod.IPTV_INSTANCE_SETTINGS_SPECIAL)
    if os.path.exists(path):
        os.remove(path)
    boot.mod._ensure_iptv_custom_tv_groups()
    assert not os.path.exists(path), (
        "no instance-settings written without a groups file"
    )


# --------------------------------------------------------------------------- #
# Weather from env (Phase 2): multi-location resolve + provider-key layers.
# --------------------------------------------------------------------------- #


def _read_weather_settings(boot):
    path = boot.mod._weather_multi_settings_path()
    root = ET.parse(path).getroot()
    return {s.get("id"): (s.text or "") for s in root.findall("setting")}


def test_apply_weather_from_env_resolves_and_writes_keys(boot, monkeypatch):
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
        boot.mod._foundation,
        "_resolve_weather_location",
        lambda q, **k: next((v for n, v in locs.items() if n in q), None),
    )
    boot.mod._apply_weather_from_env(
        {
            "WEATHER_LOCATIONS": "Sacramento, CA; Reno, NV",
            "WEATHERBIT_API_KEY": "WBITKEY",
            "OWM_API_KEY": "OWMKEY",
        }
    )
    got = _read_weather_settings(boot)
    assert got["loc1_url"] == "us/ca/sacramento"
    assert got["loc2_url"] == "us/nv/reno"
    assert got["loc3_url"] == ""  # unused slot cleared, never stale
    assert got["WAdd"] == "true" and got["API"] == "WBITKEY"
    assert got["WMaps"] == "true" and got["MAPAPI"] == "OWMKEY"


def test_apply_weather_from_env_fallback_no_env(boot, monkeypatch):
    monkeypatch.setattr(
        boot.mod._foundation, "_resolve_weather_location", lambda q, **k: None
    )
    boot.mod._apply_weather_from_env({})  # no WEATHER_LOCATIONS at all
    got = _read_weather_settings(boot)
    assert got["loc1_url"] == "us/ca/sacramento"  # Sacramento default
    assert "WAdd" not in got  # no keys -> no upgrade layer


def test_apply_weather_never_empty_url_when_all_fail(boot, monkeypatch):
    monkeypatch.setattr(
        boot.mod._foundation, "_resolve_weather_location", lambda q, **k: None
    )
    boot.mod._apply_weather_from_env({"WEATHER_LOCATIONS": "Nowhere, ZZ; Atlantis"})
    got = _read_weather_settings(boot)
    assert got["loc1_url"] == "us/ca/sacramento" and got["loc1_url"]  # never empty


def test_apply_weather_skips_unresolvable_keeps_resolved(boot, monkeypatch):
    monkeypatch.setattr(
        boot.mod._foundation,
        "_resolve_weather_location",
        lambda q, **k: (
            {"name": "Reno, NV, US", "url": "us/nv/reno", "lat": "39", "lon": "-119"}
            if "Reno" in q
            else None
        ),
    )
    boot.mod._apply_weather_from_env({"WEATHER_LOCATIONS": "Badtown; Reno, NV"})
    got = _read_weather_settings(boot)
    assert got["loc1_url"] == "us/nv/reno"  # the resolved one becomes loc1 (no gap)
    assert got.get("loc2_url", "") == ""


def test_set_weather_location_default_is_sacramento(boot):
    boot.mod._set_weather_location()
    got = _read_weather_settings(boot)
    assert got["loc1_url"] == "us/ca/sacramento"
    assert "Sacramento" in got["loc1_name"]


# --------------------------------------------------------------------------- #
# IPTV from env (Phase 3): generate customTVGroups + inject m3u/epg + groups-only.
# --------------------------------------------------------------------------- #


def test_iptv_from_env_generates_groups_and_injects_m3u_epg(boot):
    boot.mod._ensure_iptv_custom_tv_groups(
        {
            "IPTV_GROUPS": "USA ENTERTAINMENT; USA NEWS/WEATHER; PPV EVENTS",
            "IPTV_M3U": "http://iptv.example:8080/get.php?username=u&password=p",
            "IPTV_EPG": "http://iptv.example:8080/xmltv.php?username=u&password=p",
            "IPTV_GROUPS_ONLY": "true",
        }
    )
    gpath = boot.mod.xbmcvfs.translatePath(boot.mod.IPTV_CUSTOM_TV_GROUPS_FILE_VALUE)
    assert os.path.exists(gpath)
    gtext = open(gpath).read()
    assert "USA ENTERTAINMENT" in gtext and "PPV EVENTS" in gtext
    got = _read_instance_settings(boot)
    assert got["tvGroupMode"] == "2"
    assert got["tvChannelGroupsOnly"] == "true"
    assert got["m3uUrl"].endswith("password=p") and got["m3uPathType"] == "1"
    assert got["epgUrl"].startswith("http://iptv.example") and got["epgPathType"] == "1"


def test_iptv_from_env_groups_only_false(boot):
    boot.mod._ensure_iptv_custom_tv_groups(
        {"IPTV_GROUPS": "A; B", "IPTV_GROUPS_ONLY": "false"}
    )
    assert _read_instance_settings(boot)["tvChannelGroupsOnly"] == "false"


def test_iptv_env_m3u_epg_never_logged(boot, monkeypatch):
    logged = []
    monkeypatch.setattr(
        boot.mod.xbmc, "log", lambda msg, *a, **k: logged.append(str(msg))
    )
    boot.mod._ensure_iptv_custom_tv_groups(
        {
            "IPTV_GROUPS": "A",
            "IPTV_M3U": "http://host/get?password=SUPERSECRET123",
            "IPTV_EPG": "http://host/epg?password=SUPERSECRET123",
        }
    )
    blob = "\n".join(logged)
    assert "SUPERSECRET123" not in blob and "http://host/get" not in blob


# --------------------------------------------------------------------------- #
# RSS feeds from env (Phase 3): generate userdata/RssFeeds.xml.
# --------------------------------------------------------------------------- #


def test_apply_rss_from_env_writes_feeds(boot):
    boot.mod._apply_rss_from_env(
        {"RSS_FEEDS": "http://a/feed; http://b/feed", "RSS_INTERVAL": "45"}
    )
    path = boot.mod.xbmcvfs.translatePath("special://home/userdata/RssFeeds.xml")
    feeds = ET.parse(path).getroot().findall("set/feed")
    assert [f.text for f in feeds] == ["http://a/feed", "http://b/feed"]
    assert all(f.get("updateinterval") == "45" for f in feeds)


def test_apply_rss_from_env_noop_when_absent(boot):
    boot.mod._apply_rss_from_env({})
    path = boot.mod.xbmcvfs.translatePath("special://home/userdata/RssFeeds.xml")
    assert not os.path.exists(path)


def test_iptv_m3u_injected_without_groups(boot):
    """m3u/epg present but NO IPTV_GROUPS and no groups file -> inject the playlist
    source, but DON'T force custom group mode (crit A intact; m3u/epg decoupled)."""
    boot.mod._ensure_iptv_custom_tv_groups(
        {"IPTV_M3U": "http://h/list?password=x", "IPTV_EPG": "http://h/epg"}
    )
    got = _read_instance_settings(boot)
    assert got["m3uUrl"].endswith("password=x") and got["m3uPathType"] == "1"
    assert got["epgUrl"] == "http://h/epg" and got["epgPathType"] == "1"
    assert got.get("tvGroupMode") != "2"  # no groups file -> no custom mode
    assert "customTvGroupsFile" not in got


# --------------------------------------------------------------------------- #
# Phase 3a — run_express: the Express orchestrator that composes the three layers.
# run() delegates to it; it owns the order, the terminal seam (skin-last + restart),
# the summary, and the self-uninstall. These pin the orchestration directly.
# --------------------------------------------------------------------------- #
def _stub_layers_success(boot, monkeypatch):
    """Make the skin + video pieces install successfully and the IPTV backend land,
    so run_express reaches the terminal seam. Same repointing as the snapshot's
    _stub_skin_and_video_success: patch the LAYER modules (the seam is killed)."""

    def _sel(selected, official_base, disable_ids, dialog, log):
        for aid in selected:
            boot.state["extracted"].add(aid)
            boot.state["installed"].add(aid)
        for aid in disable_ids:
            boot.state["installed"].add(aid)
            boot.state["disabled"].add(aid)
        return len(selected)

    def _extract(url, dialog, pct, log):
        if "pvr.artwork" in url:
            boot.state["installed"].add(boot.mod.PVR_ARTWORK_ID)
        if "modv2plus" in url:
            boot.state["installed"].add(boot.mod.MODV2PLUS_ID)
        return True

    for tgt in (boot.mod, boot.mod._addons, boot.mod._foundation):
        monkeypatch.setattr(tgt, "install_selection", _sel, raising=False)
        monkeypatch.setattr(tgt, "extract_zip", _extract, raising=False)
        monkeypatch.setattr(
            tgt, "install_with_deps", lambda *a, **k: True, raising=False
        )
        monkeypatch.setattr(
            tgt,
            "_latest_zip_url",
            lambda aid: f"http://local/{aid}-9.9.9.zip",
            raising=False,
        )
    monkeypatch.setattr(boot.mod._iptv, "install_with_deps", lambda *a, **k: True)


def test_run_express_returns_three_layerresults(boot, monkeypatch):
    """run_express returns (addons, foundation, iptv) LayerResults on a full run, in
    that order, each a real LayerResult for the matching layer."""
    _stub_layers_success(boot, monkeypatch)
    # Don't actually restart: decline / no-op restart_kodi.
    monkeypatch.setattr(boot.mod, "restart_kodi", lambda *a, **k: None)
    addons_res, foundation_res, iptv_res = boot.mod.run_express({})
    assert addons_res.layer == "addons" and addons_res.ok is True
    assert foundation_res.layer == "foundation"
    assert iptv_res.layer == "iptv" and iptv_res.ok is True
    # The IPTV layer owns + installed the PVR backend.
    assert iptv_res.installed.get("pvr.iptvsimple") in ("installed", "configured")


def test_run_express_orchestration_order_addons_foundation_iptv(boot, monkeypatch):
    """The composed layers run in dependency order: apply_addons (source repos the
    skin closure needs) -> apply_foundation (skin closure) -> apply_iptv. Pinned by
    spying the three layer entry points run_express calls."""
    order = []
    real = {
        "apply_addons": boot.mod.apply_addons,
        "apply_foundation": boot.mod.apply_foundation,
        "apply_iptv": boot.mod.apply_iptv,
    }

    def _wrap(name):
        def _w(*a, **k):
            order.append(name)
            return real[name](*a, **k)

        return _w

    _stub_layers_success(boot, monkeypatch)
    monkeypatch.setattr(boot.mod, "restart_kodi", lambda *a, **k: None)
    for name in real:
        monkeypatch.setattr(boot.mod, name, _wrap(name))
    boot.mod.run_express({})
    assert order == ["apply_addons", "apply_foundation", "apply_iptv"], (
        f"layers must run addons -> foundation -> iptv, got {order}"
    )


def test_run_express_activates_skin_last_then_restarts(boot, monkeypatch):
    """The skin is activated LAST (lookandfeel.skin written) immediately before the
    restart, and only when Foundation succeeded — the activate-skin invariant that
    stops Kodi's 'Keep this skin?' timeout from reverting to stock."""
    _stub_layers_success(boot, monkeypatch)
    seq = []
    real_activate = boot.mod.activate_skin

    def _activate(*a, **k):
        seq.append("activate_skin")
        return real_activate(*a, **k)

    def _restart(*a, **k):
        seq.append("restart")
        # snapshot the settings emitted so far so we can assert skin was set before.
        seq.append(("skin_last", _settings_set(boot).get("lookandfeel.skin")))
        return None  # don't actually restart

    monkeypatch.setattr(boot.mod, "activate_skin", _activate)
    monkeypatch.setattr(boot.mod, "restart_kodi", _restart)
    boot.mod.run_express({})

    assert seq[0] == "activate_skin" and seq[1] == "restart", (
        f"skin must be activated immediately before the restart, got {seq}"
    )
    assert ("skin_last", boot.mod.SKIN_ID) in seq, (
        "lookandfeel.skin must be set (to MOD V2) before the restart"
    )
    # And it is the LAST core setting written.
    last = [s for s in seq if isinstance(s, tuple)][0]
    assert last[1] == boot.mod.SKIN_ID


def test_run_express_self_uninstalls_after_summary_before_restart(boot, monkeypatch):
    """run_express self-uninstalls exactly once, AFTER the summary Dialog().ok and
    BEFORE the restart (the restart finalises the removal)."""
    _stub_layers_success(boot, monkeypatch)
    events = []
    real_un = boot.mod.self_uninstall

    def _un(*a, **k):
        events.append(("uninstall", len(boot.state["ok"])))
        return real_un(*a, **k)

    monkeypatch.setattr(boot.mod, "self_uninstall", _un)
    monkeypatch.setattr(
        boot.mod, "restart_kodi", lambda *a, **k: events.append(("restart", None))
    )
    boot.mod.run_express({})
    kinds = [e[0] for e in events]
    assert kinds.count("uninstall") == 1, "must self-uninstall exactly once"
    # ok dialogs shown at uninstall time >= 1 -> after the summary.
    un_event = next(e for e in events if e[0] == "uninstall")
    assert un_event[1] == 1, "self-uninstall must follow the summary Dialog().ok"
    assert kinds.index("uninstall") < kinds.index("restart"), (
        "self-uninstall must precede the restart"
    )


def test_run_express_cancel_returns_early_no_terminal(boot, monkeypatch):
    """A cancelled base install (apply_addons ok=False) makes run_express abort
    cleanly: it returns (addons_res, None, None) — no foundation/iptv results — and
    fires NO summary / self-uninstall / restart (the monolith's early-return)."""
    _stub_layers_success(boot, monkeypatch)
    monkeypatch.setattr(
        boot.mod.xbmcgui.DialogProgress, "iscanceled", lambda self: True
    )
    un = []
    rs = []
    monkeypatch.setattr(boot.mod, "self_uninstall", lambda *a, **k: un.append(1))
    monkeypatch.setattr(boot.mod, "restart_kodi", lambda *a, **k: rs.append(1))
    addons_res, foundation_res, iptv_res = boot.mod.run_express({})
    assert addons_res.ok is False
    assert foundation_res is None and iptv_res is None
    assert un == [] and rs == [], "cancelled run must not self-uninstall or restart"
    assert boot.state["ok"] == [], "cancelled run must show no success summary"


def test_run_delegates_to_run_express(boot, monkeypatch):
    """run() is a thin env-lifecycle wrapper: it reads the env, calls run_express
    once with the parsed dict, and returns. Pin the delegation directly."""
    calls = []

    def _express(box_env=None, *a, **k):
        calls.append(box_env)
        # Return a non-cancelled addons_res so run()'s delete guard is exercised.
        from tony7bones.setup.result import LayerResult

        return LayerResult(layer="addons", ok=True), None, None

    monkeypatch.setattr(boot.mod, "run_express", _express)
    # No env file on this host -> read yields {} -> delete is a guarded no-op.
    boot.mod.run()
    assert len(calls) == 1, "run() must call run_express exactly once"


# --------------------------------------------------------------------------- #
# Transitional _BootSkinDeps seam + the _install_skin shim.
#
# run_express now calls apply_foundation via the BARE form (the seam is killed on
# the orchestrator path — Tech-debt ledger), so these are no longer on the run()
# path. They are STILL SHIPPED (transitional, removed when run() is fully
# decomposed), so pin them while present so they cannot silently rot.
# --------------------------------------------------------------------------- #
def test_boot_skin_deps_late_binds_module_globals(boot, monkeypatch):
    """_BootSkinDeps.__getattr__ resolves each primitive LIVE from the bootstrap
    module's globals (late binding), so monkeypatching boot.mod.* takes effect, and
    raises AttributeError for an unknown name."""
    deps = boot.mod._BootSkinDeps()
    sentinel = object()
    monkeypatch.setattr(boot.mod, "install_selection", sentinel)
    assert deps.install_selection is sentinel, "must late-bind the module global"
    # 'enable' maps to the module's _enable global; 'latest_zip_url' to _latest_zip_url.
    assert deps.enable is boot.mod._enable
    assert deps.latest_zip_url is boot.mod._latest_zip_url
    with pytest.raises(AttributeError):
        _ = deps.not_a_primitive


def test_install_skin_shim_forwards_bootstrap_deps(boot, monkeypatch):
    """The _install_skin shim forwards a _BootSkinDeps into foundation._install_skin,
    so a run driven through patched boot.mod.* primitives routes through them — the
    transitional behaviour-preservation contract. Pin that the shim reaches the
    foundation body with the bootstrap's deps object."""
    seen = {}

    def _fake_body(dialog, *, deps=None):
        seen["deps"] = deps
        return True

    monkeypatch.setattr(boot.mod._foundation, "_install_skin", _fake_body)
    assert boot.mod._install_skin(boot.mod.xbmcgui.DialogProgress()) is True
    assert isinstance(seen["deps"], boot.mod._BootSkinDeps), (
        "the shim must forward a _BootSkinDeps so boot.mod.* patches take effect"
    )


def test_configure_box_pauses_pvr_around_iptv_write(boot, monkeypatch):
    """Phase 5b·1 — the legacy `_configure_box` path has the SAME clobber race as
    apply_iptv (the monolith installed+enabled pvr.iptvsimple EARLY, then wrote
    instance-settings LATE with the client live), so its copy+enforce slots now
    run inside the PVR-disabled window too: with pvr installed, the enforce must
    observe the backend DISABLED, and it must end RE-ENABLED."""
    boot.state["installed"].add("pvr.iptvsimple")
    seen = {}
    real = boot.mod._ensure_iptv_custom_tv_groups

    def probe(env):
        seen["disabled_during_enforce"] = "pvr.iptvsimple" in boot.state["disabled"]
        return real(env)

    # _configure_box resolves the enforce through the boot.mod SHIM binding (the
    # Phase-2d re-export), so the probe must replace THAT name, not the iptv
    # module attribute the shim was bound from.
    monkeypatch.setattr(boot.mod, "_ensure_iptv_custom_tv_groups", probe)
    boot.mod._configure_box({"IPTV_M3U": "http://iptv.example/x?password=p"})
    assert seen["disabled_during_enforce"] is True, (
        "_configure_box must write IPTV config with pvr DISABLED (clobber fix)"
    )
    assert "pvr.iptvsimple" not in boot.state["disabled"], "must end re-enabled"


def test_configure_box_no_pvr_pause_when_backend_absent(boot):
    """A box without pvr.iptvsimple installed pauses nothing: `_configure_box`
    issues NO SetAddonEnabled for the backend (the guarded no-op window)."""
    import json as _json

    boot.mod._configure_box({"IPTV_M3U": "http://iptv.example/x"})
    pvr_toggles = [
        _json.loads(raw)
        for raw in boot.state["jsonrpc"]
        if _json.loads(raw).get("method") == "Addons.SetAddonEnabled"
        and _json.loads(raw)["params"].get("addonid") == "pvr.iptvsimple"
    ]
    assert pvr_toggles == [], "no pvr installed -> no pause/resume toggles"
