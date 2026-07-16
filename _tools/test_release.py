"""End-to-end coverage for the release tool (release.py).

Two layers: a few pure-ish unit checks plus a real bare-remote sandbox that runs
the ACTUAL release.py against a throwaway git repo wired to a bare "remote". The
sandbox ships the real tooling (release.py, release_lib.py, release_detect.py,
generate_repo.py) so the system test exercises production code, never the live
remote.

Covers the QA must-fixes the tool is responsible for:
  * MF-1  tool/gate detector agreement (via release_detect's own suite; here we
          assert the tool acts on the same set the gate would).
  * MF-4  --dry-run prints WHICH files triggered the bump, changes nothing.
  * MF-5  refuse when the branch is behind origin.
  * MF-6  idempotent re-run: an already-bumped-but-unpushed add-on is a no-op.
  * MF-8  a 9.9.9 add-on with a source change fails with a readable ceiling msg.
  * MF-9  news is prepended once, capped, and not double-stacked on re-run.
  * rollback to pre-release HEAD on any mid-transaction failure.
  * add-on independence: the seeded add-ons are independent, so editing one
    bumps only it (there is no shared library / lockstep).
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
import release_lib as rl  # noqa: E402

BOOTSTRAP_ID = "script.tony7bones.bootstrap"
MODV2_ID = "script.tony7bones.modv2plus"


# --------------------------------------------------------------------------- #
# Sandbox helpers
# --------------------------------------------------------------------------- #
def _run(cmd, cwd, env=None, check=True):
    e = dict(os.environ, **(env or {}))
    r = subprocess.run(cmd, cwd=cwd, env=e, capture_output=True, text=True)
    if check and r.returncode != 0:
        raise AssertionError(f"cmd {cmd} failed:\nSTDOUT{r.stdout}\nSTDERR{r.stderr}")
    return r


def _git(repo, *args, **kw):
    return _run(["git", "-C", str(repo), *args], cwd=str(repo), **kw)


def _git_identity(repo):
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test")


def _bootstrap_xml(version="1.0.0"):
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<addon id="{BOOTSTRAP_ID}" name="Setup" version="{version}" provider-name="t">
  <requires>
    <import addon="xbmc.python" version="3.0.0"/>
  </requires>
  <extension point="xbmc.python.script" library="default.py">
    <provides>executable</provides>
  </extension>
  <extension point="xbmc.addon.metadata">
    <platform>all</platform>
    <license>GPL-2.0-or-later</license>
    <assets><icon>icon.png</icon></assets>
    <news>
        v{version}: seed
    </news>
  </extension>
</addon>"""


def _modv2_xml(version="1.0.0"):
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<addon id="{MODV2_ID}" name="MOD V2+" version="{version}" provider-name="t">
  <requires>
    <import addon="xbmc.python" version="3.0.0"/>
  </requires>
  <extension point="xbmc.service" library="service.py"/>
  <extension point="xbmc.addon.metadata">
    <platform>all</platform>
    <license>GPL-2.0-or-later</license>
    <assets><icon>icon.png</icon></assets>
    <news>
        v{version}: seed
    </news>
  </extension>
</addon>"""


def _seed_addon(repo, addon_id, xml, *, with_default=True, with_service=False):
    d = repo / "addons" / addon_id
    d.mkdir(parents=True)
    (d / "addon.xml").write_text(xml)
    (d / "icon.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 32)
    if with_default:
        (d / "default.py").write_text("# entry\n")
    if with_service:
        (d / "service.py").write_text("# service\n")
    lib = d / "lib"
    lib.mkdir()
    (lib / "__init__.py").write_text("# lib\n")


@pytest.fixture
def sandbox(tmp_path):
    """A self-contained branch repo wired to a bare 'remote', seeded at 1.0.0.

    Runs on a non-main branch (the tool's default workflow: release on a branch,
    merge to main later). origin/main is the baseline the detector compares to.
    """
    repo = tmp_path / "repo_work"
    repo.mkdir()
    tools = repo / "_tools"
    tools.mkdir()
    for name in (
        "generate_repo.py",
        "check_site_secrets.py",
        "secret_patterns.py",
        "release_lib.py",
        "release_detect.py",
        "release.py",
    ):
        shutil.copyfile(HERE / name, tools / name)

    _seed_addon(repo, BOOTSTRAP_ID, _bootstrap_xml())
    _seed_addon(repo, MODV2_ID, _modv2_xml(), with_service=True)
    (repo / ".gitignore").write_text(
        "__pycache__/\n*.pyc\n.pytest_cache/\n.ruff_cache/\n"
    )

    _git(repo, "init", "-q", "-b", "main")
    _git_identity(repo)
    _run([sys.executable, str(tools / "generate_repo.py")], cwd=str(repo))
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "seed 1.0.0")

    bare = tmp_path / "remote.git"
    _run(["git", "init", "-q", "--bare", str(bare)], cwd=str(tmp_path))
    # Pin the bare repo to its OWN hooks dir so a test's pre-receive hook runs
    # even when the developer's global git config sets core.hooksPath (which
    # would otherwise shadow the per-repo hooks/ dir and let a rejected push
    # silently "succeed", breaking the rollback tests on their machine but not CI).
    _run(
        ["git", "-C", str(bare), "config", "core.hooksPath", str(bare / "hooks")],
        cwd=str(tmp_path),
    )
    _git(repo, "remote", "add", "origin", str(bare))
    _git(repo, "push", "-q", "origin", "main")
    # work on a feature branch (the merge-to-main flow)
    _git(repo, "checkout", "-q", "-b", "feature")
    return repo, bare


def _release(repo, *flags, check=True):
    return _run(
        [sys.executable, str(repo / "_tools" / "release.py"), *flags],
        cwd=str(repo),
        env={"PRE_COMMIT_ALLOW_NO_CONFIG": "1"},
        check=check,
    )


def _ver(repo, addon_id):
    return rl.read_addon_version((repo / "addons" / addon_id / "addon.xml").read_text())


def _news_lines(repo, addon_id):
    xml = (repo / "addons" / addon_id / "addon.xml").read_text()
    body = rl._NEWS_RE.search(xml).group(2)
    return [ln.strip() for ln in body.splitlines() if ln.strip()]


def _edit(repo, addon_id, text):
    (repo / "addons" / addon_id / "default.py").write_text(text)


def _commit(repo, msg):
    _git(repo, "add", "-A")
    _run(
        ["git", "-C", str(repo), "commit", "-q", "-m", msg],
        cwd=str(repo),
        env={"PRE_COMMIT_ALLOW_NO_CONFIG": "1"},
    )


# --------------------------------------------------------------------------- #
# Happy path — a single changed add-on (modv2plus is independent)
# --------------------------------------------------------------------------- #
def test_happy_path_minor_bump_independent_addon(sandbox):
    repo, _ = sandbox
    (repo / "addons" / MODV2_ID / "service.py").write_text("# real change\n")
    _commit(repo, "feat: improve the service")

    _release(repo, "--news", f"{MODV2_ID}=Improve the boot service")

    assert _ver(repo, MODV2_ID) == "1.1.0"  # minor default
    # the other (independent) add-on is untouched
    assert _ver(repo, BOOTSTRAP_ID) == "1.0.0"
    # news prepended
    lines = _news_lines(repo, MODV2_ID)
    assert lines[0] == "v1.1.0: Improve the boot service"
    assert lines[1] == "v1.0.0: seed"
    # committed on the feature branch, tree clean
    assert _git(repo, "status", "--porcelain").stdout.strip() == ""
    assert _git(repo, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip() == "feature"


def test_patch_level_override(sandbox):
    repo, _ = sandbox
    (repo / "addons" / MODV2_ID / "service.py").write_text("# fix\n")
    _commit(repo, "fix: a small fix")
    _release(repo, "--patch")
    assert _ver(repo, MODV2_ID) == "1.0.1"


def test_explicit_version_scoped(sandbox):
    repo, _ = sandbox
    (repo / "addons" / MODV2_ID / "service.py").write_text("# x\n")
    _commit(repo, "chore: x")
    _release(repo, "--addon", MODV2_ID, "--version", "1.5.0")
    assert _ver(repo, MODV2_ID) == "1.5.0"


def test_auto_drafted_news_from_commit_subjects(sandbox):
    repo, _ = sandbox
    (repo / "addons" / MODV2_ID / "service.py").write_text("# a\n")
    _commit(repo, "feat: add a thing")
    (repo / "addons" / MODV2_ID / "service.py").write_text("# b\n")
    _commit(repo, "fix: fix another thing")
    _release(repo)  # no --news -> auto-draft from subjects
    line = _news_lines(repo, MODV2_ID)[0]
    assert line.startswith("v1.1.0: ")
    assert "add a thing" in line
    assert "fix another thing" in line
    # conventional prefixes stripped
    assert "feat:" not in line and "fix:" not in line


# --------------------------------------------------------------------------- #
# Independence: a change to one add-on never bumps another
# --------------------------------------------------------------------------- #
def test_changing_one_addon_leaves_the_other_untouched(sandbox):
    repo, _ = sandbox
    _edit(repo, BOOTSTRAP_ID, "# bootstrap own change\n")
    _commit(repo, "feat: bootstrap changes")
    _release(repo)
    assert _ver(repo, BOOTSTRAP_ID) == "1.1.0"
    assert _ver(repo, MODV2_ID) == "1.0.0"  # independent, untouched


# --------------------------------------------------------------------------- #
# MF-6 / MF-9 — idempotency
# --------------------------------------------------------------------------- #
def test_idempotent_rerun_is_noop(sandbox):
    repo, _ = sandbox
    (repo / "addons" / MODV2_ID / "service.py").write_text("# change\n")
    _commit(repo, "feat: change")
    _release(repo, "--news", f"{MODV2_ID}=The change")
    tree_after_first = _git(repo, "rev-parse", "HEAD").stdout.strip()
    news_after_first = _news_lines(repo, MODV2_ID)

    # re-run with no intervening source edit — must be a no-op
    r = _release(repo, "--news", f"{MODV2_ID}=The change")
    assert "no-op" in r.stdout or "no changed add-ons" in r.stdout
    assert _git(repo, "rev-parse", "HEAD").stdout.strip() == tree_after_first
    assert _ver(repo, MODV2_ID) == "1.1.0"  # not 1.2.0
    assert _news_lines(repo, MODV2_ID) == news_after_first  # no double-prepend


def test_news_capped_across_releases(sandbox):
    repo, _ = sandbox
    for i in range(8):
        (repo / "addons" / MODV2_ID / "service.py").write_text(f"# change {i}\n")
        _commit(repo, f"feat: change {i}")
        _release(repo, "--news", f"{MODV2_ID}=entry {i}")
    lines = _news_lines(repo, MODV2_ID)
    assert len(lines) == rl.NEWS_CAP  # rolling cap of 6
    assert lines[0].endswith("entry 7")
    assert not any("seed" in ln for ln in lines)  # oldest rolled off


# --------------------------------------------------------------------------- #
# MF-4 — dry-run shows WHICH files, changes nothing
# --------------------------------------------------------------------------- #
def test_dry_run_shows_files_and_changes_nothing(sandbox):
    repo, _ = sandbox
    _edit(repo, MODV2_ID, "# pending change\n")  # uncommitted working-tree edit
    head = _git(repo, "rev-parse", "HEAD").stdout.strip()

    r = _release(repo, "--dry-run")
    assert "1.0.0 -> 1.1.0" in r.stdout
    assert f"changed: addons/{MODV2_ID}/default.py" in r.stdout
    assert "--dry-run: nothing was changed" in r.stdout
    # nothing committed, version on disk unchanged
    assert _git(repo, "rev-parse", "HEAD").stdout.strip() == head
    assert _ver(repo, MODV2_ID) == "1.0.0"


# --------------------------------------------------------------------------- #
# MF-5 / MF-8 — guardrails
# --------------------------------------------------------------------------- #
def test_behind_origin_refused(sandbox):
    repo, bare = sandbox
    # advance origin/main from another clone so 'feature' is behind it
    other = repo.parent / "other"
    _run(["git", "clone", "-q", str(bare), str(other)], cwd=str(repo.parent))
    _git_identity(other)
    _git(other, "checkout", "-q", "main")
    (other / "advance.txt").write_text("x")
    _git(other, "add", "-A")
    _run(["git", "-C", str(other), "commit", "-q", "-m", "advance"], cwd=str(other))
    _git(other, "push", "-q", "origin", "main")

    # make 'feature' track origin/feature behind origin: push feature, then advance it
    _git(repo, "push", "-q", "origin", "feature")
    (other2 := repo.parent / "other2")
    _run(["git", "clone", "-q", str(bare), str(other2)], cwd=str(repo.parent))
    _git_identity(other2)
    _git(other2, "checkout", "-q", "feature")
    (other2 / "adv2.txt").write_text("y")
    _git(other2, "add", "-A")
    _run(["git", "-C", str(other2), "commit", "-q", "-m", "adv2"], cwd=str(other2))
    _git(other2, "push", "-q", "origin", "feature")

    _edit(repo, MODV2_ID, "# change\n")
    r = _release(repo, check=False)
    assert r.returncode != 0
    assert "behind" in (r.stdout + r.stderr)
    assert _ver(repo, MODV2_ID) == "1.0.0"  # nothing mutated


def test_ceiling_refused_with_readable_message(sandbox):
    repo, _ = sandbox
    # push modv2plus to 9.9.9 cleanly, advance origin/main to match
    _git(repo, "checkout", "-q", "main")
    (repo / "addons" / MODV2_ID / "addon.xml").write_text(_modv2_xml("9.9.9"))
    _commit(repo, "chore: at ceiling")
    _git(repo, "push", "-q", "origin", "main")
    _git(repo, "checkout", "-q", "feature")
    _git(repo, "merge", "-q", "main")
    # now a source change with no version room
    (repo / "addons" / MODV2_ID / "service.py").write_text("# more\n")
    r = _release(repo, check=False)
    assert r.returncode != 0
    assert "ceiling" in (r.stdout + r.stderr) or "exhausted" in (r.stdout + r.stderr)
    assert "--version" in (r.stdout + r.stderr)


def test_double_digit_explicit_version_refused(sandbox):
    repo, _ = sandbox
    _edit(repo, MODV2_ID, "# x\n")
    r = _release(repo, "--addon", MODV2_ID, "--version", "1.0.10", check=False)
    assert r.returncode != 0
    assert "single-digit" in (r.stdout + r.stderr)
    assert _ver(repo, MODV2_ID) == "1.0.0"


def test_unknown_addon_refused(sandbox):
    repo, _ = sandbox
    r = _release(repo, "--addon", "plugin.nope", "--version", "1.0.1", check=False)
    assert r.returncode != 0
    assert "unknown" in (r.stdout + r.stderr)


# --------------------------------------------------------------------------- #
# Determinism + consistency + push + rollback
# --------------------------------------------------------------------------- #
def test_regen_deterministic_after_release(sandbox):
    repo, _ = sandbox
    (repo / "addons" / MODV2_ID / "service.py").write_text("# change\n")
    _commit(repo, "feat: change")
    _release(repo, "--news", f"{MODV2_ID}=x")
    _run([sys.executable, str(repo / "_tools" / "generate_repo.py")], cwd=str(repo))
    assert _git(repo, "status", "--porcelain").stdout.strip() == ""


def test_check_subcommand_passes_clean_tree(sandbox):
    repo, _ = sandbox
    r = _run(
        [sys.executable, str(repo / "_tools" / "release.py"), "check"],
        cwd=str(repo),
        check=False,
    )
    assert r.returncode == 0, r.stdout + r.stderr
    assert "OK" in r.stdout


def test_push_advances_the_branch(sandbox):
    repo, bare = sandbox
    (repo / "addons" / MODV2_ID / "service.py").write_text("# change\n")
    _commit(repo, "feat: change")
    _release(repo, "--news", f"{MODV2_ID}=x", "--push")
    # the feature branch is now on the remote with the release commit
    remote_log = _git(repo, "ls-remote", "--heads", "origin", "feature").stdout
    assert remote_log.strip()
    local_head = _git(repo, "rev-parse", "feature").stdout.strip()
    assert local_head in _git(repo, "ls-remote", "origin", "feature").stdout


def test_default_does_not_push(sandbox):
    repo, bare = sandbox
    (repo / "addons" / MODV2_ID / "service.py").write_text("# change\n")
    _commit(repo, "feat: change")
    _release(repo, "--news", f"{MODV2_ID}=x")
    # feature was never pushed
    assert _git(repo, "ls-remote", "--heads", "origin", "feature").stdout.strip() == ""


def test_rollback_on_push_failure(sandbox):
    repo, bare = sandbox
    hook = bare / "hooks" / "pre-receive"
    hook.write_text("#!/bin/sh\necho 'rejected' >&2\nexit 1\n")
    hook.chmod(0o755)

    (repo / "addons" / MODV2_ID / "service.py").write_text("# change\n")
    _commit(repo, "feat: change")
    head = _git(repo, "rev-parse", "HEAD").stdout.strip()

    r = _release(repo, "--news", f"{MODV2_ID}=x", "--push", check=False)
    assert r.returncode != 0
    # rolled back to pre-release HEAD, tree clean, version restored
    assert _git(repo, "rev-parse", "HEAD").stdout.strip() == head
    assert _git(repo, "status", "--porcelain").stdout.strip() == ""
    assert _ver(repo, MODV2_ID) == "1.0.0"


def test_no_changed_addons_is_clean_noop(sandbox):
    repo, _ = sandbox
    r = _release(repo)
    assert "no changed add-ons" in r.stdout
    assert _git(repo, "rev-parse", "HEAD").stdout.strip() == (
        _git(repo, "rev-parse", "origin/main").stdout.strip()
    )


# ============================================================================ #
# In-process tests — import release.py and drive its functions DIRECTLY against
# a sandbox (release.REPO monkeypatched). This measures
# the pure logic, and it gives real line coverage of release.py (the subprocess
# e2e tests above prove the wiring; these prove the logic + raise coverage).
# ============================================================================ #


@pytest.fixture
def inproc(sandbox, monkeypatch):
    """Point the imported `release` module at the sandbox repo + its generator.

    SAFETY: these tests call release.py functions IN-PROCESS, including
    apply_release whose rollback runs `git reset --hard`. release.git() resolves
    REPO at call time so the monkeypatch below redirects EVERY git call into the
    sandbox. The assertion is a hard tripwire: if REPO is ever not the sandbox,
    fail loudly BEFORE any destructive git can touch the real working tree.
    """
    repo, bare = sandbox
    import release as rel

    monkeypatch.setattr(rel, "REPO", str(repo))
    monkeypatch.setattr(rel, "ADDON_DIR", str(repo / "addons"))
    monkeypatch.setattr(rel, "GENERATOR", str(repo / "_tools" / "generate_repo.py"))
    assert rel.REPO == str(repo), (
        "in-process tests MUST target the sandbox, not the real repo"
    )
    assert rel.REPO != str(HERE.parent), "REPO must never be the real repo in tests"
    return rel, repo, bare


class _Args:
    def __init__(self, **kw):
        self.patch = kw.get("patch", False)
        self.minor = kw.get("minor", False)
        self.major = kw.get("major", False)
        self.version = kw.get("version")
        self.addon = kw.get("addon")
        self.news = kw.get("news")
        self.dry_run = kw.get("dry_run", False)
        self.push = kw.get("push", False)


def test_inproc_build_plan_detects_source_change(inproc):
    rel, repo, _ = inproc
    (repo / "addons" / MODV2_ID / "service.py").write_text("# changed\n")
    bumps, already = rel.build_plan(_Args(), "origin/main")
    assert [b.addon_id for b in bumps] == [MODV2_ID]
    assert bumps[0].cur == "1.0.0" and bumps[0].nxt == "1.1.0"
    assert already == []


def test_inproc_draft_news_strips_prefixes(inproc):
    rel, repo, _ = inproc
    _edit(repo, MODV2_ID, "# a\n")
    _commit(repo, "feat(scope): add the thing")
    _edit(repo, MODV2_ID, "# b\n")
    _commit(repo, "fix: tidy")
    line = rel.draft_news(MODV2_ID, "origin/main")
    assert "add the thing" in line and "tidy" in line
    assert "feat" not in line and "fix:" not in line


def test_inproc_draft_news_fallback_when_no_commits(inproc):
    rel, repo, _ = inproc
    _edit(repo, MODV2_ID, "# pending uncommitted\n")  # uncommitted -> no subjects
    assert rel.draft_news(MODV2_ID, "origin/main") == "Maintenance release."


def test_inproc_first_party_includes_repo_addon(inproc):
    rel, repo, _ = inproc
    # the repository add-on is now a NORMAL static-only add-on: released the
    # same way as every other, so it must appear in the first-party set.
    (repo / "addons" / "repository.tony7bones").mkdir()
    (repo / "addons" / "repository.tony7bones" / "addon.xml").write_text(
        '<addon id="repository.tony7bones" version="1.0.0"/>\n'
    )
    ids = rel.first_party_ids()
    assert "repository.tony7bones" in ids
    assert set(ids) == {BOOTSTRAP_ID, MODV2_ID, "repository.tony7bones"}


def test_inproc_news_override_per_addon(inproc):
    rel, repo, _ = inproc
    (repo / "addons" / MODV2_ID / "service.py").write_text("# c\n")
    bumps, _ = rel.build_plan(_Args(news=f"{MODV2_ID}=Explicit line"), "origin/main")
    assert bumps[0].news == "Explicit line"


def test_inproc_apply_writes_version_and_news(inproc):
    rel, repo, _ = inproc
    (repo / "addons" / MODV2_ID / "service.py").write_text("# new\n")
    bumps, _ = rel.build_plan(_Args(news=f"{MODV2_ID}=Did a thing"), "origin/main")
    rel.apply_release(_Args(), bumps, "origin/main")
    assert _ver(repo, MODV2_ID) == "1.1.0"
    assert _news_lines(repo, MODV2_ID)[0] == "v1.1.0: Did a thing"


def test_inproc_script_consistency_ok_on_clean_tree(inproc):
    rel, _, _ = inproc
    ok, problems = rel.script_consistency("origin/main")
    assert ok, problems


def test_inproc_script_consistency_flags_unbumped(inproc):
    rel, repo, _ = inproc
    (repo / "addons" / MODV2_ID / "service.py").write_text("# changed no bump\n")
    _commit(repo, "feat: change no bump")
    ok, problems = rel.script_consistency("origin/main")
    assert not ok
    assert any("not bumped" in p for p in problems)


def test_inproc_script_consistency_flags_double_digit(inproc):
    rel, repo, _ = inproc
    (repo / "addons" / MODV2_ID / "addon.xml").write_text(_modv2_xml("1.0.10"))
    ok, problems = rel.script_consistency("origin/main")
    assert not ok
    assert any("single-digit" in p for p in problems)


def test_inproc_script_consistency_legacy_baseline_not_flagged(inproc):
    """The LIVE ezm path: an add-on whose origin/main baseline is a legacy
    date-stamped 4-component version (2026.07.02.0, EZ Maintenance++'s real
    scheme) must NOT be flagged 'not single-digit', and a legacy in-scheme bump
    is judged monotonic via is_greater_loose - not rl.is_greater's strict parser,
    which raises on a 4-component version. Exercises the legacy_baseline branch."""
    rel, repo, _ = inproc
    # establish a legacy-scheme version as the origin/main baseline itself
    (repo / "addons" / MODV2_ID / "addon.xml").write_text(_modv2_xml("2026.07.02.0"))
    _commit(repo, "chore: legacy baseline")
    _git(repo, "push", "-q", "-f", "origin", "feature:main")
    # unchanged legacy version: clean, and NOT flagged as non-single-digit
    ok, problems = rel.script_consistency("origin/main")
    assert ok, problems
    # a real in-scheme bump + source change stays clean (monotonic via loose cmp)
    (repo / "addons" / MODV2_ID / "addon.xml").write_text(_modv2_xml("2026.07.04.0"))
    (repo / "addons" / MODV2_ID / "service.py").write_text("# legacy change\n")
    _commit(repo, "feat: legacy change")
    ok2, problems2 = rel.script_consistency("origin/main")
    assert ok2, problems2


def test_inproc_already_released_is_true_after_bump(inproc):
    rel, repo, _ = inproc
    (repo / "addons" / MODV2_ID / "service.py").write_text("# change\n")
    _commit(repo, "feat: change")
    bumps, _ = rel.build_plan(_Args(), "origin/main")
    rel.apply_release(_Args(), bumps, "origin/main")
    # now it is bumped with no new source change → already-released
    assert rel._already_released(MODV2_ID, "origin/main") is True
    bumps2, already2 = rel.build_plan(_Args(), "origin/main")
    assert bumps2 == [] and already2 == [MODV2_ID]


def test_inproc_already_released_false_with_new_edit(inproc):
    rel, repo, _ = inproc
    (repo / "addons" / MODV2_ID / "service.py").write_text("# change\n")
    _commit(repo, "feat: change")
    bumps, _ = rel.build_plan(_Args(), "origin/main")
    rel.apply_release(_Args(), bumps, "origin/main")
    # a NEW source edit after the bump → re-releasable
    (repo / "addons" / MODV2_ID / "service.py").write_text("# another change\n")
    assert rel._already_released(MODV2_ID, "origin/main") is False


def test_inproc_already_released_handles_legacy_baseline_version(inproc):
    """A baseline in EZ Maintenance++'s REAL date-stamped shape (2026.07.02.0
    - four dot-separated components, not X.Y.Z) must not crash
    _already_released. rl.is_greater's strict parser (parse_version) requires
    EXACTLY three components and raises ValueError on anything else - this
    used to propagate straight out of this check the first time a change to
    an add-on with this real, currently-shipped version shape ever reached
    it (a 3-part-but-double-digit version like modv2plus's 1.4.10 does NOT
    trigger this - parse_version only checks component COUNT, not magnitude;
    only a genuinely wrong-shaped version like the date-stamped one does)."""
    rel, repo, _ = inproc
    # Establish a legacy-scheme version as the ORIGIN/MAIN baseline itself.
    (repo / "addons" / MODV2_ID / "addon.xml").write_text(_modv2_xml("2026.07.02.0"))
    _commit(repo, "chore: legacy version baseline")
    _git(repo, "push", "-q", "-f", "origin", "feature:main")
    # A genuine new source change on top of that legacy baseline.
    (repo / "addons" / MODV2_ID / "service.py").write_text("# change\n")
    _commit(repo, "feat: change")
    assert rel._already_released(MODV2_ID, "origin/main") is False


def test_inproc_next_for_explicit_version_requires_single_digit(inproc):
    rel, _, _ = inproc
    with pytest.raises(SystemExit, match="single-digit"):
        rel._next_for(MODV2_ID, "1.0.0", _Args(version="1.0.10"))


def test_inproc_next_for_explicit_version_allows_legacy_scheme(inproc):
    """An add-on already on a legacy, non-single-digit scheme (EZ
    Maintenance++'s real date-stamped 2026.07.02.0 - four components, not
    X.Y.Z) must be explicitly re-versionable within that same scheme.
    rl.parse_version's strict 3-component parser used to run unconditionally
    here and crash outright the first time anyone tried to bump one of these
    add-ons by explicit --version at all."""
    rel, _, _ = inproc
    assert (
        rel._next_for(
            "script.ezmaintenanceplusplus",
            "2026.07.02.0",
            _Args(version="2026.07.04.0"),
        )
        == "2026.07.04.0"
    )


def test_inproc_next_for_explicit_version_legacy_scheme_rejects_garbage(inproc):
    rel, _, _ = inproc
    with pytest.raises(SystemExit, match="not a valid"):
        rel._next_for(
            "script.ezmaintenanceplusplus",
            "2026.07.02.0",
            _Args(version="not-a-version"),
        )


def test_inproc_ceiling_raises_systemexit(inproc):
    rel, repo, _ = inproc
    (repo / "addons" / MODV2_ID / "addon.xml").write_text(_modv2_xml("9.9.9"))
    with pytest.raises(SystemExit, match="ceiling|exhausted"):
        rel._next_for(MODV2_ID, "9.9.9", _Args())


def test_inproc_behind_origin_clean_when_up_to_date(inproc):
    rel, _, _ = inproc
    # feature is not behind origin/feature (not pushed) → no problems
    assert rel._behind_origin("origin/main") == []


def test_inproc_run_full_path_commits(inproc, monkeypatch):
    rel, repo, _ = inproc
    monkeypatch.chdir(repo)
    (repo / "addons" / MODV2_ID / "service.py").write_text("# real\n")
    _commit(repo, "feat: real")
    rc = rel.run(_Args(news=f"{MODV2_ID}=Did a thing"))
    assert rc == 0
    assert _ver(repo, MODV2_ID) == "1.1.0"


def test_inproc_run_dry_run_changes_nothing(inproc, monkeypatch):
    rel, repo, _ = inproc
    monkeypatch.chdir(repo)
    (repo / "addons" / MODV2_ID / "service.py").write_text("# real\n")
    rc = rel.run(_Args(dry_run=True))
    assert rc == 0
    assert _ver(repo, MODV2_ID) == "1.0.0"  # unchanged


def test_inproc_run_no_base_ref_skips(inproc, monkeypatch):
    rel, repo, _ = inproc
    monkeypatch.chdir(repo)
    monkeypatch.setattr(rel.rd, "BASE_REF", "origin/does-not-exist")
    rc = rel.run(_Args())
    assert rc == 0


def test_inproc_main_check_ok(inproc, monkeypatch, capsys):
    rel, repo, _ = inproc
    monkeypatch.chdir(repo)
    rc = rel.main(["check"])
    assert rc == 0
    assert "OK" in capsys.readouterr().out


def test_inproc_main_check_fail_on_bad_version(inproc, monkeypatch, capsys):
    rel, repo, _ = inproc
    monkeypatch.chdir(repo)
    # a double-digit component violates the single-digit scheme the gate enforces
    (repo / "addons" / MODV2_ID / "addon.xml").write_text(_modv2_xml("1.0.10"))
    rc = rel.main(["check"])
    assert rc == 1
    assert "FAIL" in capsys.readouterr().out


def test_inproc_main_dry_run_via_argv(inproc, monkeypatch):
    rel, repo, _ = inproc
    monkeypatch.chdir(repo)
    (repo / "addons" / MODV2_ID / "service.py").write_text("# change\n")
    rc = rel.main(["--dry-run"])
    assert rc == 0
    assert _ver(repo, MODV2_ID) == "1.0.0"


def test_inproc_main_patch_via_argv_commits(inproc, monkeypatch):
    rel, repo, _ = inproc
    monkeypatch.chdir(repo)
    (repo / "addons" / MODV2_ID / "service.py").write_text("# change\n")
    _commit(repo, "fix: a fix")
    rc = rel.main(["--patch", "--news", f"{MODV2_ID}=Patched"])
    assert rc == 0
    assert _ver(repo, MODV2_ID) == "1.0.1"


def test_inproc_news_bare_override_applies_to_scoped_addon(inproc):
    rel, repo, _ = inproc
    (repo / "addons" / MODV2_ID / "service.py").write_text("# c\n")
    bumps, _ = rel.build_plan(
        _Args(addon=MODV2_ID, news="A bare line for the scoped add-on"), "origin/main"
    )
    assert bumps[0].news == "A bare line for the scoped add-on"


def test_inproc_print_plan_shows_changed_files(inproc, capsys):
    rel, repo, _ = inproc
    _edit(repo, MODV2_ID, "# pending change\n")
    bumps, already = rel.build_plan(_Args(), "origin/main")
    rel._print_plan(bumps, already, "origin/main")
    out = capsys.readouterr().out
    assert f"changed: addons/{MODV2_ID}/default.py" in out
    assert "1.0.0 -> 1.1.0" in out


def test_inproc_apply_push_advances_branch(inproc, monkeypatch):
    rel, repo, bare = inproc
    monkeypatch.chdir(repo)
    rel.git("push", "origin", "feature")  # publish the branch first
    (repo / "addons" / MODV2_ID / "service.py").write_text("# change\n")
    _commit(repo, "feat: change")
    bumps, _ = rel.build_plan(_Args(), "origin/main")
    rel.apply_release(_Args(push=True), bumps, "origin/main")
    # the release commit is now on origin/feature
    remote = rel.git("ls-remote", "origin", "feature")
    local = rel.git("rev-parse", "feature")
    assert local in remote


def test_inproc_apply_rollback_on_generator_failure(inproc, monkeypatch):
    rel, repo, _ = inproc
    monkeypatch.chdir(repo)
    (repo / "addons" / MODV2_ID / "service.py").write_text("# change\n")
    _commit(repo, "feat: change")
    bumps, _ = rel.build_plan(_Args(), "origin/main")

    # force the determinism gate / generator to fail mid-transaction
    def boom():
        raise RuntimeError("generator boom")

    monkeypatch.setattr(rel, "run_generator", boom)
    with pytest.raises(RuntimeError):
        rel.apply_release(_Args(), bumps, "origin/main")
    # rolled back to pre-release state in the SANDBOX (never the real repo)
    assert rel.git("status", "--porcelain") == ""
    assert _ver(repo, MODV2_ID) == "1.0.0"


def test_inproc_behind_origin_detected(inproc, monkeypatch):
    rel, repo, bare = inproc
    monkeypatch.chdir(repo)
    # publish feature, then advance origin/feature from another clone
    rel.git("push", "origin", "feature")
    other = repo.parent / "other_inproc"
    _run(["git", "clone", "-q", str(bare), str(other)], cwd=str(repo.parent))
    _git_identity(other)
    _git(other, "checkout", "-q", "feature")
    (other / "adv.txt").write_text("x")
    _git(other, "add", "-A")
    _run(["git", "-C", str(other), "commit", "-q", "-m", "adv"], cwd=str(other))
    _git(other, "push", "-q", "origin", "feature")
    problems = rel._behind_origin("origin/main")
    assert any("behind" in p for p in problems)


def test_inproc_behind_origin_no_remote(inproc, monkeypatch):
    rel, repo, _ = inproc
    monkeypatch.chdir(repo)
    rel.git("remote", "remove", "origin")
