"""Coverage for _tools/sync_share.py - the KodiShare backup mirror.

Contract pinned here (see the module docstring):
  * skipped ENTIRELY when the share dir does not exist (volume unmounted) -
    the sync must never create the dir or attempt a mount;
  * additive: foreign zips on the share are NEVER touched; the only deletions
    are superseded repository.tony7bones-*.zip versions;
  * idempotent, per-file fail-soft, and best_effort() NEVER raises (a release
    must succeed identically with the share broken);
  * sandbox safety is STRUCTURAL: the deploy/release/system-test sandboxes copy
    an explicit whitelist of _tools files, and sync_share.py must never appear
    in one - a sandboxed deploy.py skips the sync via ImportError. The last
    test enforces that invariant against the test sources themselves.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import sync_share  # noqa: E402

HERE = Path(__file__).parent


def _repo(tmp_path, installer="repository.tony7bones-2.2.6.zip"):
    root = tmp_path / "repo"
    (root / "dropbox" / "repositories").mkdir(parents=True)
    if installer:
        # The installer is sourced from the committed add-on tree (the root
        # copy is a CI artifact now): addon.xml's version names the zip.
        version = installer[len("repository.tony7bones-") : -len(".zip")]
        addon_dir = root / "addons" / "repository.tony7bones"
        addon_dir.mkdir(parents=True)
        (addon_dir / "addon.xml").write_text(
            f'<addon id="repository.tony7bones" version="{version}"/>'
        )
        (addon_dir / installer).write_bytes(b"INSTALLER-CURRENT")
    (root / "dropbox" / "repositories" / "repository.peno64-1.5.zip").write_bytes(
        b"PENO"
    )
    (root / "dropbox" / "repositories" / "notes.txt").write_bytes(b"not a zip")
    return root


def test_current_installer_reads_addon_xml_version(tmp_path):
    root = _repo(tmp_path)
    path = sync_share._current_installer(str(root))
    assert path is not None and path.endswith(
        "addons/repository.tony7bones/repository.tony7bones-2.2.6.zip"
    )


def test_current_installer_none_when_zip_for_version_missing(tmp_path):
    """addon.xml names a version whose zip is absent -> None (never guess)."""
    root = _repo(tmp_path)
    (
        root / "addons" / "repository.tony7bones" / "repository.tony7bones-2.2.6.zip"
    ).unlink()
    assert sync_share._current_installer(str(root)) is None


def test_missing_installer_zip_is_surfaced_as_error_and_no_prune(tmp_path):
    """Mid-release state (addon.xml bumped, zip not built): sync records an
    error instead of silently skipping, and never prunes the share copy."""
    root = _repo(tmp_path)
    (
        root / "addons" / "repository.tony7bones" / "repository.tony7bones-2.2.6.zip"
    ).unlink()
    share = tmp_path / "share"
    share.mkdir()
    (share / "repository.tony7bones-1.0.5.zip").write_bytes(b"STALE")
    actions = sync_share.sync(str(root), str(share))
    assert any(a.startswith("error:no built zip") for a, _ in actions), actions
    assert (share / "repository.tony7bones-1.0.5.zip").exists()
    assert not any(a == "pruned" for a, _ in actions)


def test_unmounted_share_is_skipped_untouched(tmp_path):
    root = _repo(tmp_path)
    share = tmp_path / "not-mounted" / "repositories"  # does not exist
    actions = sync_share.sync(str(root), str(share))
    assert actions == [("unavailable", str(share))]
    assert not share.exists()  # never created


def test_copies_installer_and_canvas_zips(tmp_path):
    root = _repo(tmp_path)
    share = tmp_path / "share"
    share.mkdir()
    actions = sync_share.sync(str(root), str(share))
    assert ("copied", "repository.tony7bones-2.2.6.zip") in actions
    assert ("copied", "repository.peno64-1.5.zip") in actions
    assert (
        share / "repository.tony7bones-2.2.6.zip"
    ).read_bytes() == b"INSTALLER-CURRENT"
    assert not (share / "notes.txt").exists()  # only zips mirror


def test_prunes_only_superseded_own_installer(tmp_path):
    root = _repo(tmp_path)
    share = tmp_path / "share"
    share.mkdir()
    (share / "repository.tony7bones-1.0.5.zip").write_bytes(b"STALE")
    (share / "repository.thelab-25.3.27.zip").write_bytes(b"FOREIGN")
    (share / "repository.umbrella-2.2.6.zip").write_bytes(b"FOREIGN2")
    actions = sync_share.sync(str(root), str(share))
    assert ("pruned", "repository.tony7bones-1.0.5.zip") in actions
    assert not (share / "repository.tony7bones-1.0.5.zip").exists()
    # Foreign zips untouched even when version-suffixed or same-versioned.
    assert (share / "repository.thelab-25.3.27.zip").read_bytes() == b"FOREIGN"
    assert (share / "repository.umbrella-2.2.6.zip").read_bytes() == b"FOREIGN2"


def test_idempotent_second_run_reports_unchanged(tmp_path):
    root = _repo(tmp_path)
    share = tmp_path / "share"
    share.mkdir()
    sync_share.sync(str(root), str(share))
    actions = sync_share.sync(str(root), str(share))
    assert all(a == "unchanged" for a, _ in actions)


def test_changed_file_is_overwritten(tmp_path):
    root = _repo(tmp_path)
    share = tmp_path / "share"
    share.mkdir()
    (share / "repository.tony7bones-2.2.6.zip").write_bytes(b"CORRUPT")
    actions = sync_share.sync(str(root), str(share))
    assert ("copied", "repository.tony7bones-2.2.6.zip") in actions
    assert (
        share / "repository.tony7bones-2.2.6.zip"
    ).read_bytes() == b"INSTALLER-CURRENT"


def test_no_installer_in_repo_still_mirrors_canvas_and_prunes_nothing(tmp_path):
    root = _repo(tmp_path, installer=None)
    share = tmp_path / "share"
    share.mkdir()
    (share / "repository.tony7bones-1.0.5.zip").write_bytes(b"STALE")
    actions = sync_share.sync(str(root), str(share))
    assert ("copied", "repository.peno64-1.5.zip") in actions
    # Without a known current installer we must not guess at pruning.
    assert (share / "repository.tony7bones-1.0.5.zip").exists()
    assert not any(a == "pruned" for a, _ in actions)


def test_dry_run_changes_nothing(tmp_path):
    root = _repo(tmp_path)
    share = tmp_path / "share"
    share.mkdir()
    (share / "repository.tony7bones-1.0.5.zip").write_bytes(b"STALE")
    actions = sync_share.sync(str(root), str(share), dry_run=True)
    assert ("copied", "repository.tony7bones-2.2.6.zip") in actions
    assert ("pruned", "repository.tony7bones-1.0.5.zip") in actions
    assert not (share / "repository.tony7bones-2.2.6.zip").exists()
    assert (share / "repository.tony7bones-1.0.5.zip").exists()


def test_per_file_error_is_recorded_not_raised(tmp_path, monkeypatch):
    root = _repo(tmp_path)
    share = tmp_path / "share"
    share.mkdir()

    def boom(src, dst):
        raise OSError("share went away")

    monkeypatch.setattr(sync_share.shutil, "copyfile", boom)
    actions = sync_share.sync(str(root), str(share))  # must not raise
    assert any(a.startswith("error:") for a, _ in actions)


def test_best_effort_never_raises(tmp_path, monkeypatch, capsys):
    def explode(*a, **k):
        raise RuntimeError("catastrophic")

    monkeypatch.setattr(sync_share, "sync", explode)
    sync_share.best_effort(
        str(tmp_path), str(tmp_path), str(tmp_path), str(tmp_path)
    )  # must not raise
    assert "share sync skipped" in capsys.readouterr().err


def test_cli_dry_run_reports_and_exits_zero(tmp_path, monkeypatch, capsys):
    share = tmp_path / "share"
    share.mkdir()
    rc = sync_share.main(["--share", str(share), "--dry-run"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "--dry-run: nothing was changed." in out


def test_sandbox_copy_lists_never_include_sync_share():
    """STRUCTURAL sandbox safety: the system tests copy production tools into
    sandbox repos by explicit whitelist. sync_share.py must never join those
    lists - a sandboxed deploy.py/release.py must fail its guarded import and
    skip the share entirely, or sandbox artifacts could reach the REAL share
    mounted on this machine."""
    for name in ("test_release.py", "test_publish_canvas.py"):
        src = (HERE / name).read_text()
        assert "sync_share" not in src.replace("test_sync_share", ""), (
            f"{name} references sync_share - sandbox isolation broken"
        )


def test_prune_error_is_recorded_not_raised(tmp_path, monkeypatch):
    root = _repo(tmp_path)
    share = tmp_path / "share"
    share.mkdir()
    (share / "repository.tony7bones-1.0.5.zip").write_bytes(b"STALE")

    def boom(path):
        raise OSError("busy")

    monkeypatch.setattr(sync_share.os, "remove", boom)
    actions = sync_share.sync(str(root), str(share))  # must not raise
    assert any(a.startswith("error:") for a, n in actions if "1.0.5" in n)
    assert (share / "repository.tony7bones-1.0.5.zip").exists()


def test_best_effort_reports_on_success(tmp_path, capsys):
    root = _repo(tmp_path)
    share = tmp_path / "share"
    share.mkdir()
    sync_share.best_effort(
        str(root),
        str(share),
        str(tmp_path / "apps-missing"),
        str(tmp_path / "root-missing"),
    )
    out = capsys.readouterr().out
    assert "Share sync ->" in out and "copied" in out


def test_report_unavailable_and_up_to_date_branches(tmp_path, capsys):
    root = _repo(tmp_path)
    missing = tmp_path / "missing"
    sync_share.best_effort(
        str(root),
        str(missing),
        str(tmp_path / "apps-missing"),
        str(tmp_path / "root-missing"),
    )
    assert "not mounted - skipped" in capsys.readouterr().out
    share = tmp_path / "share"
    share.mkdir()
    sync_share.sync(str(root), str(share))
    capsys.readouterr()
    sync_share.best_effort(
        str(root),
        str(share),
        str(tmp_path / "apps-missing"),
        str(tmp_path / "root-missing"),
    )
    assert "already up to date" in capsys.readouterr().out


def test_cli_real_run_copies(tmp_path, monkeypatch, capsys):
    root = _repo(tmp_path)
    share = tmp_path / "share"
    share.mkdir()
    monkeypatch.setattr(sync_share, "REPO", str(root))
    rc = sync_share.main(["--share", str(share)])
    assert rc == 0
    assert (share / "repository.tony7bones-2.2.6.zip").exists()


# ----------------------------------------------------------------- apps sync


ADDON_XML = '<?xml version="1.0"?>\n<addon id="{aid}" version="{ver}" name="X" provider-name="T"/>\n'


def _repo_with_addons(tmp_path):
    root = _repo(tmp_path)
    for aid, ver in (
        ("plugin.video.demo", "2026.07.09.1"),
        ("script.module.tony7bones", "1.8.0"),
        # A release-managed add-on (source in a sibling repo, in-repo zip is a
        # stub): sync_apps must SKIP it even when a copy is present in apps/.
        ("script.ezmaintenanceplusplus", "2026.07.09.1"),
    ):
        d = root / "addons" / aid
        d.mkdir(parents=True)
        (d / "addon.xml").write_text(ADDON_XML.format(aid=aid, ver=ver))
        (d / f"{aid}-{ver}.zip").write_bytes(b"CURRENT-" + aid.encode())
    return root


def test_apps_unmounted_is_skipped_untouched(tmp_path):
    root = _repo_with_addons(tmp_path)
    apps = tmp_path / "not-mounted" / "apps"
    actions = sync_share.sync_apps(str(root), str(apps))
    assert actions == [("unavailable", str(apps))]
    assert not apps.exists()


def test_apps_opt_in_by_presence_refreshes_and_prunes(tmp_path):
    root = _repo_with_addons(tmp_path)
    apps = tmp_path / "apps"
    apps.mkdir()
    (apps / "plugin.video.demo-2026.06.30.28.zip").write_bytes(b"STALE")
    (apps / "some.foreign.tool-9.9.zip").write_bytes(b"FOREIGN")
    actions = sync_share.sync_apps(str(root), str(apps))
    assert ("copied", "plugin.video.demo-2026.07.09.1.zip") in actions
    assert ("pruned", "plugin.video.demo-2026.06.30.28.zip") in actions
    # The library was NOT opted in (no zip present) -> never added.
    assert not any("script.module.tony7bones" in n for _, n in actions)
    assert not (apps / "script.module.tony7bones-1.8.0.zip").exists()
    # Foreign zip untouched.
    assert (apps / "some.foreign.tool-9.9.zip").read_bytes() == b"FOREIGN"


def test_apps_release_managed_addon_is_skipped_even_if_present(tmp_path):
    """A release-managed add-on (source in a sibling repo; in-repo zip is a
    non-installable stub) is NEVER copied or pruned by sync_apps, even when a
    copy is already opted-in in apps/. The kodishare-sync skill owns its apps/
    copy from the real GitHub Release, so sync_apps must not fight it with the
    stub. Regression guard for the broken-restore-zip class."""
    root = _repo_with_addons(tmp_path)
    apps = tmp_path / "apps"
    apps.mkdir()
    real = apps / "script.ezmaintenanceplusplus-2026.07.17.5.zip"
    real.write_bytes(b"REAL-RELEASE-FROM-SKILL")
    actions = sync_share.sync_apps(str(root), str(apps))
    # No action of any kind touches the release-managed add-on.
    assert not any("script.ezmaintenanceplusplus" in n for _, n in actions)
    # The skill-placed real zip is left exactly as-is (not overwritten/pruned).
    assert real.read_bytes() == b"REAL-RELEASE-FROM-SKILL"
    # And the stub version from the repo is never introduced.
    assert not (apps / "script.ezmaintenanceplusplus-2026.07.09.1.zip").exists()


def test_apps_idempotent_and_dry_run(tmp_path):
    root = _repo_with_addons(tmp_path)
    apps = tmp_path / "apps"
    apps.mkdir()
    (apps / "plugin.video.demo-2026.06.30.28.zip").write_bytes(b"STALE")
    dry = sync_share.sync_apps(str(root), str(apps), dry_run=True)
    assert ("copied", "plugin.video.demo-2026.07.09.1.zip") in dry
    assert not (apps / "plugin.video.demo-2026.07.09.1.zip").exists()
    assert (apps / "plugin.video.demo-2026.06.30.28.zip").exists()
    sync_share.sync_apps(str(root), str(apps))
    again = sync_share.sync_apps(str(root), str(apps))
    assert all(a == "unchanged" for a, _ in again)


def test_apps_missing_built_zip_is_error_and_no_prune(tmp_path):
    root = _repo_with_addons(tmp_path)
    aid = "plugin.video.demo"
    (root / "addons" / aid / f"{aid}-2026.07.09.1.zip").unlink()
    apps = tmp_path / "apps"
    apps.mkdir()
    (apps / f"{aid}-2026.06.30.28.zip").write_bytes(b"STALE")
    actions = sync_share.sync_apps(str(root), str(apps))
    assert any(a.startswith("error:no built zip") for a, _ in actions)
    # A stale copy is better than none: no prune without a fresh copy landing.
    assert (apps / f"{aid}-2026.06.30.28.zip").exists()


def test_apps_copy_failure_skips_prune(tmp_path, monkeypatch):
    root = _repo_with_addons(tmp_path)
    apps = tmp_path / "apps"
    apps.mkdir()
    (apps / "plugin.video.demo-2026.06.30.28.zip").write_bytes(b"STALE")

    def boom(src, dst):
        raise OSError("share went away")

    monkeypatch.setattr(sync_share.shutil, "copyfile", boom)
    actions = sync_share.sync_apps(str(root), str(apps))
    assert any(a.startswith("error:") for a, _ in actions)
    assert (apps / "plugin.video.demo-2026.06.30.28.zip").exists()


def test_best_effort_covers_both_dirs(tmp_path, capsys):
    root = _repo_with_addons(tmp_path)
    share = tmp_path / "share"
    share.mkdir()
    apps = tmp_path / "apps"
    apps.mkdir()
    (apps / "plugin.video.demo-2026.06.30.28.zip").write_bytes(b"STALE")
    sync_share.best_effort(
        str(root), str(share), str(apps), str(tmp_path / "root-missing")
    )
    out = capsys.readouterr().out
    assert "repository.tony7bones-2.2.6.zip" in out
    assert "plugin.video.demo-2026.07.09.1.zip" in out
    assert (apps / "plugin.video.demo-2026.07.09.1.zip").exists()
    assert not (apps / "plugin.video.demo-2026.06.30.28.zip").exists()


# -------------------------------------------------------------- canvas assets


def _repo_with_assets(tmp_path):
    root = _repo(tmp_path)
    (root / "dropbox" / "media").mkdir()
    (root / "dropbox" / "media" / "splash.jpg").write_bytes(b"NEW-SPLASH")
    (root / "dropbox" / "media" / "background.jpg").write_bytes(b"NEW-BACKGROUND")
    (root / "dropbox" / "rss").mkdir()
    (root / "dropbox" / "rss" / "RssFeeds.xml").write_bytes(b"<rss/>")
    return root


def test_assets_copies_new_and_overwrites_changed_never_deletes(tmp_path):
    root = _repo_with_assets(tmp_path)
    share_root = tmp_path / "shareroot"
    (share_root / "media").mkdir(parents=True)
    (share_root / "rss").mkdir()
    # The real-world stale state: the old canvas image sitting under the old
    # name, plus a file foreign to the canvas.
    (share_root / "media" / "splash.jpg").write_bytes(b"OLD-IMAGE")
    (share_root / "media" / "owner-extra.png").write_bytes(b"MINE")
    actions = sync_share.sync_canvas_assets(str(root), str(share_root))
    assert ("copied", "media/splash.jpg") in actions
    assert ("copied", "media/background.jpg") in actions
    assert ("copied", "rss/RssFeeds.xml") in actions
    assert (share_root / "media" / "splash.jpg").read_bytes() == b"NEW-SPLASH"
    assert (share_root / "media" / "owner-extra.png").read_bytes() == b"MINE"
    # additive: nothing is ever deleted
    assert not any(a == "pruned" for a, _ in actions)


def test_assets_missing_share_subdir_skipped_not_created(tmp_path):
    root = _repo_with_assets(tmp_path)
    share_root = tmp_path / "shareroot"
    (share_root / "rss").mkdir(parents=True)  # media/ absent
    actions = sync_share.sync_canvas_assets(str(root), str(share_root))
    assert ("unavailable", str(share_root / "media")) in actions
    assert ("copied", "rss/RssFeeds.xml") in actions
    assert not (share_root / "media").exists()


def test_assets_missing_canvas_subdir_is_noop(tmp_path):
    root = _repo(tmp_path)  # no dropbox/media or dropbox/rss
    share_root = tmp_path / "shareroot"
    (share_root / "media").mkdir(parents=True)
    (share_root / "rss").mkdir()
    assert sync_share.sync_canvas_assets(str(root), str(share_root)) == []


def test_assets_dry_run_changes_nothing(tmp_path):
    root = _repo_with_assets(tmp_path)
    share_root = tmp_path / "shareroot"
    (share_root / "media").mkdir(parents=True)
    (share_root / "rss").mkdir()
    actions = sync_share.sync_canvas_assets(str(root), str(share_root), dry_run=True)
    assert ("copied", "media/splash.jpg") in actions
    assert not (share_root / "media" / "splash.jpg").exists()


def test_assets_idempotent(tmp_path):
    root = _repo_with_assets(tmp_path)
    share_root = tmp_path / "shareroot"
    (share_root / "media").mkdir(parents=True)
    (share_root / "rss").mkdir()
    sync_share.sync_canvas_assets(str(root), str(share_root))
    again = sync_share.sync_canvas_assets(str(root), str(share_root))
    assert all(a == "unchanged" for a, _ in again)
