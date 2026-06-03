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


def _run(cmd, cwd, check=True):
    r = subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True)
    if check and r.returncode != 0:
        raise AssertionError(f"{cmd} failed:\n{r.stdout}\n{r.stderr}")
    return r


def _git(repo, *args, **kw):
    return _run(["git", "-C", str(repo), *args], cwd=repo, **kw)


def _scaffold(tmp_path, with_origin=True):
    repo = tmp_path / "repo_work"
    (repo / "_tools").mkdir(parents=True)
    for name in ("check_versions.py", "release_lib.py"):
        shutil.copyfile(HERE / name, repo / "_tools" / name)
    addon = repo / "repo" / "plugin.test"
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


def _check(repo):
    return _run(
        [sys.executable, str(repo / "_tools" / "check_versions.py")],
        cwd=repo,
        check=False,
    )


def test_blocks_source_change_without_bump(tmp_path):
    repo = _scaffold(tmp_path)
    (repo / "repo" / "plugin.test" / "default.py").write_text("# changed, no bump\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "change without bump")
    r = _check(repo)
    assert r.returncode == 1
    assert "not bumped" in r.stdout


def test_allows_source_change_with_bump(tmp_path):
    repo = _scaffold(tmp_path)
    (repo / "repo" / "plugin.test" / "default.py").write_text("# changed\n")
    (repo / "repo" / "plugin.test" / "addon.xml").write_text(
        '<addon id="plugin.test" version="1.0.1"/>\n'
    )
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "change + bump")
    r = _check(repo)
    assert r.returncode == 0, r.stdout + r.stderr


def test_ignores_generated_zip_and_index(tmp_path):
    repo = _scaffold(tmp_path)
    (repo / "repo" / "plugin.test" / "plugin.test-1.0.0.zip").write_bytes(b"zip")
    (repo / "repo" / "plugin.test" / "index.html").write_text("<html/>")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "generated files only")
    r = _check(repo)
    assert r.returncode == 0, r.stdout + r.stderr


def test_skips_when_no_origin(tmp_path):
    repo = _scaffold(tmp_path, with_origin=False)
    (repo / "repo" / "plugin.test" / "default.py").write_text("# changed\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "change")
    r = _check(repo)
    assert r.returncode == 0
    assert "skipping" in r.stdout
