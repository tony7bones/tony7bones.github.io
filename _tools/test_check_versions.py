"""Coverage for the versioning gate (check_versions.py).

Builds throwaway git repos with a simulated origin/main and runs the real
check_versions.py to prove it blocks a source change that forgot to bump the
add-on version, and passes when the version is bumped (or only generated files
changed).
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path


HERE = Path(__file__).parent


def _run(cmd, cwd, check=True, env=None):
    import os as _os

    e = dict(_os.environ, **(env or {}))
    r = subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True, env=e)
    if check and r.returncode != 0:
        raise AssertionError(f"{cmd} failed:\n{r.stdout}\n{r.stderr}")
    return r


def _git(repo, *args, **kw):
    return _run(["git", "-C", str(repo), *args], cwd=repo, **kw)


def _scaffold(tmp_path, with_origin=True):
    repo = tmp_path / "repo_work"
    (repo / "_tools").mkdir(parents=True)
    for name in ("check_versions.py", "release_lib.py", "release_detect.py"):
        shutil.copyfile(HERE / name, repo / "_tools" / name)
    addon = repo / "addons" / "plugin.test"
    addon.mkdir(parents=True)
    (addon / "addon.xml").write_text('<addon id="plugin.test" version="1.0.0"/>\n')
    (addon / "default.py").write_text("# v1\n")
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "t@e.com")
    _git(repo, "config", "user.name", "T")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "base")
    if with_origin:
        base = _git(repo, "rev-parse", "HEAD").stdout.strip()
        _run(
            ["git", "-C", str(repo), "update-ref", "refs/remotes/origin/main", base],
            cwd=repo,
        )
    return repo


def _check(repo, env=None):
    return _run(
        [sys.executable, str(repo / "_tools" / "check_versions.py")],
        cwd=repo,
        check=False,
        env=env,
    )


def test_blocks_source_change_without_bump(tmp_path):
    repo = _scaffold(tmp_path)
    (repo / "addons" / "plugin.test" / "default.py").write_text("# changed, no bump\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "change without bump")
    r = _check(repo)
    assert r.returncode == 1
    assert "not bumped" in r.stdout


def test_allows_source_change_with_bump(tmp_path):
    repo = _scaffold(tmp_path)
    (repo / "addons" / "plugin.test" / "default.py").write_text("# changed\n")
    (repo / "addons" / "plugin.test" / "addon.xml").write_text(
        '<addon id="plugin.test" version="1.0.1"/>\n'
    )
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "change + bump")
    r = _check(repo)
    assert r.returncode == 0, r.stdout + r.stderr


def test_ignores_generated_zip_and_index(tmp_path):
    repo = _scaffold(tmp_path)
    (repo / "addons" / "plugin.test" / "plugin.test-1.0.0.zip").write_bytes(b"zip")
    (repo / "addons" / "plugin.test" / "index.html").write_text("<html/>")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "generated files only")
    r = _check(repo)
    assert r.returncode == 0, r.stdout + r.stderr


def _seed_base_version(repo, version):
    """Advance the add-on (and origin/main baseline) to `version` cleanly."""
    (repo / "addons" / "plugin.test" / "addon.xml").write_text(
        f'<addon id="plugin.test" version="{version}"/>\n'
    )
    (repo / "addons" / "plugin.test" / "default.py").write_text(f"# base {version}\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", f"base {version}")
    base = _git(repo, "rev-parse", "HEAD").stdout.strip()
    _run(
        ["git", "-C", str(repo), "update-ref", "refs/remotes/origin/main", base],
        cwd=repo,
    )


def test_rejects_double_digit_bump(tmp_path):
    """A hand-edited 1.0.9 -> 1.0.10 bump is rejected (component >= 10)."""
    repo = _scaffold(tmp_path)
    _seed_base_version(repo, "1.0.9")
    (repo / "addons" / "plugin.test" / "default.py").write_text("# changed\n")
    (repo / "addons" / "plugin.test" / "addon.xml").write_text(
        '<addon id="plugin.test" version="1.0.10"/>\n'
    )
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "double-digit bump")
    r = _check(repo)
    assert r.returncode == 1
    assert "single-digit" in r.stdout


def test_allows_clean_rollover_bump(tmp_path):
    """A 1.0.9 -> 1.1.0 rollover bump is accepted."""
    repo = _scaffold(tmp_path)
    _seed_base_version(repo, "1.0.9")
    (repo / "addons" / "plugin.test" / "default.py").write_text("# changed\n")
    (repo / "addons" / "plugin.test" / "addon.xml").write_text(
        '<addon id="plugin.test" version="1.1.0"/>\n'
    )
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "rollover bump")
    r = _check(repo)
    assert r.returncode == 0, r.stdout + r.stderr


def test_skips_when_no_origin(tmp_path):
    repo = _scaffold(tmp_path, with_origin=False)
    (repo / "addons" / "plugin.test" / "default.py").write_text("# changed\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "change")
    r = _check(repo)
    assert r.returncode == 0
    assert "skipping" in r.stdout


# --------------------------------------------------------------------------- #
# O7 — the CI baseline override (CHECK_VERSIONS_BASE_REF). On a main push,
# origin/main == HEAD, so CI must compare against the push's "before" SHA
# instead. These prove the env override makes the gate validate the pushed
# RANGE, catching an unbumped change CI would otherwise miss.
# --------------------------------------------------------------------------- #
def test_ci_baseline_override_blocks_unbumped_range(tmp_path):
    repo = _scaffold(tmp_path)
    before = _git(repo, "rev-parse", "HEAD").stdout.strip()
    # advance "main" with a source change but NO bump, then point origin/main at
    # the new HEAD (simulating a main push where origin/main == HEAD).
    (repo / "addons" / "plugin.test" / "default.py").write_text("# changed no bump\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "unbumped change")
    _set_origin = _git(repo, "rev-parse", "HEAD").stdout.strip()
    _run(
        ["git", "-C", str(repo), "update-ref", "refs/remotes/origin/main", _set_origin],
        cwd=repo,
    )
    # default origin/main baseline == HEAD → passes vacuously
    assert _check(repo).returncode == 0
    # CI override against the "before" SHA → catches the unbumped change
    r = _check(repo, env={"CHECK_VERSIONS_BASE_REF": before})
    assert r.returncode == 1
    assert "not bumped" in r.stdout


def test_ci_baseline_override_passes_bumped_range(tmp_path):
    repo = _scaffold(tmp_path)
    before = _git(repo, "rev-parse", "HEAD").stdout.strip()
    (repo / "addons" / "plugin.test" / "default.py").write_text("# changed\n")
    (repo / "addons" / "plugin.test" / "addon.xml").write_text(
        '<addon id="plugin.test" version="1.0.1"/>\n'
    )
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "change + bump")
    r = _check(repo, env={"CHECK_VERSIONS_BASE_REF": before})
    assert r.returncode == 0, r.stdout + r.stderr


def test_ci_baseline_override_blank_falls_back_to_origin(tmp_path):
    # An empty override must be ignored (fall back to origin/main), so a
    # misconfigured CI env var never silently changes the baseline.
    repo = _scaffold(tmp_path)
    (repo / "addons" / "plugin.test" / "default.py").write_text("# changed no bump\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "unbumped")
    r = _check(repo, env={"CHECK_VERSIONS_BASE_REF": "   "})
    assert r.returncode == 1  # origin/main baseline still catches it
    assert "not bumped" in r.stdout
