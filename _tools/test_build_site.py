"""Pins on build_site.copy_tracked_tree's log shape.

The allowlist refuses every tracked file outside the published dirs, which is
the DESIGNED outcome for docs/, _tools/, .github/ and the rest, not an
anomaly. Until 2026-09-26 each refusal was a GitHub ::warning:: annotation,
102 per build and 204 per run, which buried the two real warnings a run
carries and would bury a stale-catalog warning the day one appears. The
refusals are now one plain summary line plus plain per-file lines; only a
genuine anomaly (a tracked symlink) stays a ::warning::.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import build_site  # noqa: E402


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


def _tracked_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    (repo / "addons" / "repository.example").mkdir(parents=True)
    (repo / "addons" / "repository.example" / "addon.xml").write_text("<addon/>")
    (repo / "docs").mkdir()
    (repo / "docs" / "internal.md").write_text("private notes")
    (repo / "_tools").mkdir()
    (repo / "_tools" / "tool.py").write_text("print()")
    (repo / "CLAUDE.md").write_text("rules")
    os.symlink("../CLAUDE.md", repo / "addons" / "sneak.md")
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "t@e.com")
    _git(repo, "config", "user.name", "T")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "init")
    return repo


def test_allowlist_exclusions_are_one_plain_summary_not_warnings(tmp_path, capsys):
    repo = _tracked_repo(tmp_path)
    out = tmp_path / "site"
    count = build_site.copy_tracked_tree(str(out), str(repo))
    lines = capsys.readouterr().out.splitlines()

    assert count == 1
    assert (out / "addons" / "repository.example" / "addon.xml").is_file()
    assert not (out / "docs").exists()
    assert not (out / "CLAUDE.md").exists()

    warnings = [ln for ln in lines if ln.startswith("::warning::")]
    assert warnings == ["::warning::excluded from artifact (symlink): addons/sneak.md"]

    summary = [ln for ln in lines if ln.startswith("site: excluded ")]
    assert summary == [
        "site: excluded 3 tracked files from the artifact (allowlist)"
    ]
    listed = {ln.strip() for ln in lines if ln.startswith("  excluded: ")}
    assert {ln.split(" (")[0] for ln in listed} == {
        "excluded: docs/internal.md",
        "excluded: _tools/tool.py",
        "excluded: CLAUDE.md",
    }


def test_no_summary_line_when_nothing_is_excluded(tmp_path, capsys):
    repo = tmp_path / "repo"
    (repo / "addons" / "repository.example").mkdir(parents=True)
    (repo / "addons" / "repository.example" / "addon.xml").write_text("<addon/>")
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "t@e.com")
    _git(repo, "config", "user.name", "T")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "init")
    assert build_site.copy_tracked_tree(str(tmp_path / "site"), str(repo)) == 1
    out = capsys.readouterr().out
    assert "excluded" not in out
    assert "::warning::" not in out
