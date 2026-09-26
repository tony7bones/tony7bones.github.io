"""Coverage for _tools/sync_share.py - the Kodi share backup mirror.

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
    sync_share.best_effort(str(tmp_path), str(tmp_path))  # must not raise
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
    lists - a sandboxed publish_canvas.py must fail its guarded import and
    skip the share entirely, or sandbox artifacts could reach the REAL share
    mounted on this machine."""
    for name in ("test_publish_canvas.py", "test_check_versions.py"):
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
    sync_share.best_effort(str(root), str(share))
    out = capsys.readouterr().out
    assert "Share sync ->" in out and "copied" in out


def test_report_unavailable_and_up_to_date_branches(tmp_path, capsys):
    root = _repo(tmp_path)
    missing = tmp_path / "missing"
    sync_share.best_effort(str(root), str(missing))
    assert "not mounted - skipped" in capsys.readouterr().out
    share = tmp_path / "share"
    share.mkdir()
    sync_share.sync(str(root), str(share))
    capsys.readouterr()
    sync_share.best_effort(str(root), str(share))
    assert "already up to date" in capsys.readouterr().out


def test_cli_real_run_copies(tmp_path, monkeypatch, capsys):
    root = _repo(tmp_path)
    share = tmp_path / "share"
    share.mkdir()
    monkeypatch.setattr(sync_share, "REPO", str(root))
    rc = sync_share.main(["--share", str(share)])
    assert rc == 0
    assert (share / "repository.tony7bones-2.2.6.zip").exists()


def test_dead_share_halves_are_gone():
    """/Volumes/Kodi/Share has no apps/, media/ or rss/ (measured 2026-09-26),
    so the syncs that targeted them were unreachable and were deleted."""
    src = (HERE / "sync_share.py").read_text()
    for name in ("sync_apps", "sync_canvas_assets", "APPS_DIR", "CANVAS_ASSET_DIRS"):
        assert f"{name}(" not in src and f"{name} =" not in src, name
    assert not hasattr(sync_share, "sync_apps")
    assert not hasattr(sync_share, "sync_canvas_assets")
