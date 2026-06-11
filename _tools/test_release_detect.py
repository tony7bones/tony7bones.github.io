"""Coverage for the shared change detector (release_detect.changed_addons).

The detector is the ONE function behind both the pre-push gate and the release
tool, with an explicit ``worktree`` mode flag (QA must-fix MF-1). These tests
build throwaway git repos with a simulated ``origin/main`` and prove:

  * gate mode (committed ``base_ref..HEAD``) and tool mode (working tree vs
    ``base_ref``) return the SAME set on a committed tree — the MF-1 regression
    guard, the test that makes "tool and gate cannot disagree" real, not a
    comment;
  * a source change is detected; a zip-only / index-only change is NOT (the
    generated artifacts are excluded);
  * a working-tree-only (uncommitted) edit is invisible to gate mode but visible
    to tool mode (the whole reason the flag exists);
  * a missing ``origin/main`` baseline yields ``[]`` (skip, never fail closed);
  * ``changed_files`` lists exactly the changed source files for ``--dry-run``.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
import release_detect as rd  # noqa: E402


def _run(cmd, cwd, check=True):
    r = subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True)
    if check and r.returncode != 0:
        raise AssertionError(f"{cmd} failed:\n{r.stdout}\n{r.stderr}")
    return r


def _git(repo, *args, **kw):
    return _run(["git", "-C", str(repo), *args], cwd=repo, **kw)


def _set_origin_main(repo):
    base = _git(repo, "rev-parse", "HEAD").stdout.strip()
    _run(
        ["git", "-C", str(repo), "update-ref", "refs/remotes/origin/main", base],
        cwd=repo,
    )


def _scaffold(tmp_path, addons=("plugin.alpha", "plugin.beta"), with_origin=True):
    repo = tmp_path / "repo_work"
    (repo / "addons").mkdir(parents=True)
    for aid in addons:
        d = repo / "addons" / aid
        d.mkdir(parents=True)
        (d / "addon.xml").write_text(f'<addon id="{aid}" version="1.0.0"/>\n')
        (d / "default.py").write_text("# v1\n")
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "t@e.com")
    _git(repo, "config", "user.name", "T")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "base")
    if with_origin:
        _set_origin_main(repo)
    return repo


def _edit_and_commit(repo, aid, text="# changed\n", msg="edit"):
    (repo / "addons" / aid / "default.py").write_text(text)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", msg)


# --------------------------------------------------------------------------- #
# MF-1 — tool mode and gate mode agree on a committed tree.
# --------------------------------------------------------------------------- #
def test_tool_and_gate_modes_agree_on_committed_tree(tmp_path):
    repo = _scaffold(tmp_path)
    _edit_and_commit(repo, "plugin.alpha")

    gate = rd.changed_addons(str(repo), "origin/main", worktree=False)
    tool = rd.changed_addons(str(repo), "origin/main", worktree=True)
    assert gate == tool == ["plugin.alpha"]


def test_tool_and_gate_modes_agree_when_nothing_changed(tmp_path):
    repo = _scaffold(tmp_path)  # HEAD == origin/main
    assert rd.changed_addons(str(repo), "origin/main", worktree=False) == []
    assert rd.changed_addons(str(repo), "origin/main", worktree=True) == []


def test_tool_and_gate_agree_on_multiple_changed(tmp_path):
    repo = _scaffold(tmp_path)
    _edit_and_commit(repo, "plugin.alpha", msg="a")
    _edit_and_commit(repo, "plugin.beta", msg="b")
    gate = rd.changed_addons(str(repo), "origin/main", worktree=False)
    tool = rd.changed_addons(str(repo), "origin/main", worktree=True)
    assert gate == tool == ["plugin.alpha", "plugin.beta"]  # sorted


# --------------------------------------------------------------------------- #
# The worktree flag actually matters: an uncommitted edit is the ONLY thing the
# two modes legitimately disagree about (and only because it isn't committed).
# --------------------------------------------------------------------------- #
def test_worktree_mode_sees_uncommitted_edit_gate_does_not(tmp_path):
    repo = _scaffold(tmp_path)
    # uncommitted working-tree edit
    (repo / "addons" / "plugin.alpha" / "default.py").write_text("# dirty\n")

    # gate (committed) sees nothing — HEAD still == origin/main
    assert rd.changed_addons(str(repo), "origin/main", worktree=False) == []
    # tool (working tree) sees the pending change it is about to commit
    assert rd.changed_addons(str(repo), "origin/main", worktree=True) == [
        "plugin.alpha"
    ]


def test_worktree_mode_sees_staged_edit(tmp_path):
    repo = _scaffold(tmp_path)
    (repo / "addons" / "plugin.beta" / "default.py").write_text("# staged\n")
    _git(repo, "add", "-A")  # staged, not committed
    assert rd.changed_addons(str(repo), "origin/main", worktree=True) == ["plugin.beta"]


# --------------------------------------------------------------------------- #
# Generated artifacts (zip + index) are excluded — same definition as the gate.
# --------------------------------------------------------------------------- #
def test_zip_and_index_only_change_is_not_detected(tmp_path):
    repo = _scaffold(tmp_path)
    d = repo / "addons" / "plugin.alpha"
    (d / "plugin.alpha-1.0.0.zip").write_bytes(b"zip")
    (d / "index.html").write_text("<html/>")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "generated only")
    assert rd.changed_addons(str(repo), "origin/main", worktree=False) == []
    assert rd.changed_addons(str(repo), "origin/main", worktree=True) == []


def test_source_change_alongside_generated_is_detected(tmp_path):
    repo = _scaffold(tmp_path)
    d = repo / "addons" / "plugin.alpha"
    (d / "default.py").write_text("# real change\n")
    (d / "plugin.alpha-1.0.0.zip").write_bytes(b"zip")  # also regenerated
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "source + generated")
    assert rd.changed_addons(str(repo), "origin/main", worktree=False) == [
        "plugin.alpha"
    ]


def test_addon_xml_version_line_counts_as_changed(tmp_path):
    repo = _scaffold(tmp_path)
    (repo / "addons" / "plugin.alpha" / "addon.xml").write_text(
        '<addon id="plugin.alpha" version="1.1.0"/>\n'
    )
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "bump only")
    # the bump commit IS its release — it reads as changed (matches the gate).
    assert rd.changed_addons(str(repo), "origin/main", worktree=False) == [
        "plugin.alpha"
    ]


# --------------------------------------------------------------------------- #
# Baseline / edge cases.
# --------------------------------------------------------------------------- #
def test_no_origin_main_returns_empty(tmp_path):
    repo = _scaffold(tmp_path, with_origin=False)
    _edit_and_commit(repo, "plugin.alpha")
    assert rd.changed_addons(str(repo), "origin/main", worktree=False) == []
    assert rd.changed_addons(str(repo), "origin/main", worktree=True) == []
    assert rd.base_ref_exists(str(repo), "origin/main") is False


def test_new_addon_with_no_baseline_is_detected_not_crash(tmp_path):
    repo = _scaffold(tmp_path)
    d = repo / "addons" / "plugin.gamma"  # brand new, not in origin/main
    d.mkdir(parents=True)
    (d / "addon.xml").write_text('<addon id="plugin.gamma" version="1.0.0"/>\n')
    (d / "default.py").write_text("# new\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "new add-on")
    assert "plugin.gamma" in rd.changed_addons(str(repo), "origin/main", worktree=False)


def test_addon_dirs_only_yields_dirs_with_addon_xml(tmp_path):
    repo = _scaffold(tmp_path)
    (repo / "addons" / "not_an_addon").mkdir()  # no addon.xml
    (repo / "addons" / "not_an_addon" / "readme.txt").write_text("x")
    ids = [aid for aid, _ in rd.addon_dirs(str(repo))]
    assert ids == ["plugin.alpha", "plugin.beta"]


def test_addon_dirs_missing_addons_dir(tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    assert list(rd.addon_dirs(str(empty))) == []


# --------------------------------------------------------------------------- #
# changed_files (the --dry-run "why is this changed?" support, MF-4).
# --------------------------------------------------------------------------- #
def test_changed_files_lists_the_changed_sources(tmp_path):
    repo = _scaffold(tmp_path)
    _edit_and_commit(repo, "plugin.alpha")
    files = rd.changed_files(str(repo), "plugin.alpha", "origin/main", worktree=False)
    assert files == ["addons/plugin.alpha/default.py"]


def test_changed_files_excludes_zip_and_index(tmp_path):
    repo = _scaffold(tmp_path)
    d = repo / "addons" / "plugin.alpha"
    (d / "default.py").write_text("# real\n")
    (d / "plugin.alpha-1.0.0.zip").write_bytes(b"zip")
    (d / "index.html").write_text("<html/>")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "mix")
    files = rd.changed_files(str(repo), "plugin.alpha", "origin/main", worktree=False)
    assert files == ["addons/plugin.alpha/default.py"]
