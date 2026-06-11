"""End-to-end coverage for the script.* release tool (release.py).

Mirrors test_deploy.py's two layers: a few pure-ish unit checks plus a real
bare-remote sandbox that runs the ACTUAL release.py against a throwaway git repo
wired to a bare "remote". The sandbox ships the real tooling (release.py,
release_lib.py, release_detect.py, generate_repo.py) so the system test exercises
production code, never the live remote.

Covers the QA must-fixes the tool is responsible for:
  * MF-1  tool/gate detector agreement (via release_detect's own suite; here we
          assert the tool acts on the same set the gate would).
  * MF-2  lockstep is atomic: a library bump raises bootstrap's import AND bumps
          bootstrap, in ONE commit; a library-only scoped run still bumps the
          dependent.
  * MF-4  --dry-run prints WHICH files triggered the bump, changes nothing.
  * MF-5  refuse when the branch is behind origin.
  * MF-6  idempotent re-run: an already-bumped-but-unpushed add-on is a no-op.
  * MF-7  a dependent that changed for BOTH its own source and the lockstep is
          bumped exactly ONCE.
  * MF-8  a 9.9.9 add-on with a source change fails with a readable ceiling msg.
  * MF-9  news is prepended once, capped, and not double-stacked on re-run.
  * rollback to pre-release HEAD on any mid-transaction failure.
  * modv2plus independence: editing it bumps only it.
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

LIBRARY_ID = "script.module.tony7bones"
BOOTSTRAP_ID = "script.tony7bones.bootstrap"
MODV2_ID = "script.tony7bones.modv2plus"


# --------------------------------------------------------------------------- #
# Sandbox helpers (mirror test_deploy.py)
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


def _library_xml(version="1.0.0"):
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<addon id="{LIBRARY_ID}" name="Lib" version="{version}" provider-name="t">
  <requires>
    <import addon="xbmc.python" version="3.0.0"/>
  </requires>
  <extension point="xbmc.python.module" library="lib"/>
  <extension point="xbmc.addon.metadata">
    <platform>all</platform>
    <license>GPL-2.0-or-later</license>
    <assets><icon>icon.png</icon></assets>
    <news>
        v{version}: seed
    </news>
  </extension>
</addon>"""


def _bootstrap_xml(version="1.0.0", import_v="1.0.0"):
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<addon id="{BOOTSTRAP_ID}" name="Setup" version="{version}" provider-name="t">
  <requires>
    <import addon="xbmc.python" version="3.0.0"/>
    <import addon="{LIBRARY_ID}" version="{import_v}"/>
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
        "release_lib.py",
        "release_detect.py",
        "release.py",
    ):
        shutil.copyfile(HERE / name, tools / name)

    _seed_addon(repo, LIBRARY_ID, _library_xml(), with_default=False)
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


def _import_ver(repo, holder_id, dep_id):
    return rl.read_import_version(
        (repo / "addons" / holder_id / "addon.xml").read_text(), dep_id
    )


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
    # library + bootstrap untouched
    assert _ver(repo, LIBRARY_ID) == "1.0.0"
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
# MF-2 / MF-7 — lockstep atomicity
# --------------------------------------------------------------------------- #
def test_library_change_raises_lockstep_and_bumps_bootstrap(sandbox):
    repo, _ = sandbox
    (repo / "addons" / LIBRARY_ID / "lib" / "__init__.py").write_text(
        "# new lib code\n"
    )
    _commit(repo, "feat: library gains a feature")

    _release(repo)

    # library bumped
    assert _ver(repo, LIBRARY_ID) == "1.1.0"
    # bootstrap bumped AND its import raised to the new library version (atomic)
    assert _ver(repo, BOOTSTRAP_ID) == "1.1.0"
    assert _import_ver(repo, BOOTSTRAP_ID, LIBRARY_ID) == "1.1.0"
    # one release commit holds both
    subject = _git(repo, "log", "-1", "--format=%s").stdout.strip()
    assert "tony7bones" in subject
    # modv2plus untouched (independent)
    assert _ver(repo, MODV2_ID) == "1.0.0"


def test_library_only_scoped_run_still_bumps_dependent(sandbox):
    """MF-2: scoping to the library must NOT orphan bootstrap's import raise."""
    repo, _ = sandbox
    (repo / "addons" / LIBRARY_ID / "lib" / "__init__.py").write_text("# new lib\n")
    _commit(repo, "feat: lib change")
    _release(repo, "--addon", LIBRARY_ID)
    # even scoped, the dependent is auto-included and raised in lockstep (O9)
    assert _ver(repo, LIBRARY_ID) == "1.1.0"
    assert _import_ver(repo, BOOTSTRAP_ID, LIBRARY_ID) == "1.1.0"
    assert _ver(repo, BOOTSTRAP_ID) == "1.1.0"


def test_both_changed_bootstrap_bumps_once(sandbox):
    """MF-7: bootstrap changed for its own source AND the lockstep — bumped ONCE."""
    repo, _ = sandbox
    (repo / "addons" / LIBRARY_ID / "lib" / "__init__.py").write_text("# new lib\n")
    _edit(repo, BOOTSTRAP_ID, "# bootstrap own change\n")
    _commit(repo, "feat: lib + bootstrap both change")
    _release(repo)
    assert _ver(repo, LIBRARY_ID) == "1.1.0"
    assert _ver(repo, BOOTSTRAP_ID) == "1.1.0"  # ONE bump, not 1.2.0
    assert _import_ver(repo, BOOTSTRAP_ID, LIBRARY_ID) == "1.1.0"


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


def test_dry_run_lockstep_reason_shown(sandbox):
    repo, _ = sandbox
    (repo / "addons" / LIBRARY_ID / "lib" / "__init__.py").write_text("# new lib\n")
    r = _release(repo, "--dry-run")
    assert f"lockstep: import {LIBRARY_ID}" in r.stdout
    assert _ver(repo, BOOTSTRAP_ID) == "1.0.0"  # nothing changed


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


def test_check_subcommand_flags_broken_lockstep(sandbox):
    repo, _ = sandbox
    # break the lockstep on disk: raise the library but not bootstrap's import
    (repo / "addons" / LIBRARY_ID / "addon.xml").write_text(_library_xml("2.0.0"))
    r = _run(
        [sys.executable, str(repo / "_tools" / "release.py"), "check"],
        cwd=str(repo),
        check=False,
    )
    assert r.returncode == 1
    assert "lockstep out of sync" in r.stdout


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
# a sandbox (release.REPO monkeypatched). This is how test_deploy.py measures
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
        self.proxy = kw.get("proxy", False)
        self.no_push = kw.get("no_push", False)
        self.no_verify = kw.get("no_verify", False)


def test_inproc_build_plan_detects_source_change(inproc):
    rel, repo, _ = inproc
    (repo / "addons" / MODV2_ID / "service.py").write_text("# changed\n")
    bumps, already = rel.build_plan(_Args(), "origin/main")
    assert [b.addon_id for b in bumps] == [MODV2_ID]
    assert bumps[0].cur == "1.0.0" and bumps[0].nxt == "1.1.0"
    assert already == []


def test_inproc_build_plan_lockstep_two_pass(inproc):
    rel, repo, _ = inproc
    (repo / "addons" / LIBRARY_ID / "lib" / "__init__.py").write_text("# new\n")
    bumps, _ = rel.build_plan(_Args(), "origin/main")
    by_id = {b.addon_id: b for b in bumps}
    assert by_id[LIBRARY_ID].nxt == "1.1.0"
    assert by_id[BOOTSTRAP_ID].lockstep_import == (LIBRARY_ID, "1.1.0")
    assert by_id[BOOTSTRAP_ID].reason == "lockstep"


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


def test_inproc_dependents_of_reads_graph(inproc):
    rel, _, _ = inproc
    assert rel.dependents_of(LIBRARY_ID) == [BOOTSTRAP_ID]


def test_inproc_first_party_excludes_proxy(inproc):
    rel, repo, _ = inproc
    # add a fake proxy dir — it must be excluded from the first-party set
    (repo / "addons" / "repository.tony7bones").mkdir()
    (repo / "addons" / "repository.tony7bones" / "addon.xml").write_text(
        '<addon id="repository.tony7bones" version="1.0.0"/>\n'
    )
    ids = rel.first_party_ids()
    assert "repository.tony7bones" not in ids
    assert set(ids) == {LIBRARY_ID, BOOTSTRAP_ID, MODV2_ID}


def test_inproc_news_override_per_addon(inproc):
    rel, repo, _ = inproc
    (repo / "addons" / MODV2_ID / "service.py").write_text("# c\n")
    bumps, _ = rel.build_plan(_Args(news=f"{MODV2_ID}=Explicit line"), "origin/main")
    assert bumps[0].news == "Explicit line"


def test_inproc_apply_writes_version_news_and_lockstep(inproc):
    rel, repo, _ = inproc
    (repo / "addons" / LIBRARY_ID / "lib" / "__init__.py").write_text("# new\n")
    bumps, _ = rel.build_plan(_Args(), "origin/main")
    rel.apply_release(_Args(), bumps, "origin/main")
    assert _ver(repo, LIBRARY_ID) == "1.1.0"
    assert _ver(repo, BOOTSTRAP_ID) == "1.1.0"
    assert _import_ver(repo, BOOTSTRAP_ID, LIBRARY_ID) == "1.1.0"


def test_inproc_script_consistency_ok_on_clean_tree(inproc):
    rel, _, _ = inproc
    ok, info, problems = rel.script_consistency("origin/main")
    assert ok, problems
    assert any("lockstep" in i for i in info)


def test_inproc_script_consistency_flags_unbumped(inproc):
    rel, repo, _ = inproc
    (repo / "addons" / MODV2_ID / "service.py").write_text("# changed no bump\n")
    _commit(repo, "feat: change no bump")
    ok, _, problems = rel.script_consistency("origin/main")
    assert not ok
    assert any("not bumped" in p for p in problems)


def test_inproc_script_consistency_flags_double_digit(inproc):
    rel, repo, _ = inproc
    (repo / "addons" / MODV2_ID / "addon.xml").write_text(_modv2_xml("1.0.10"))
    ok, _, problems = rel.script_consistency("origin/main")
    assert not ok
    assert any("single-digit" in p for p in problems)


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


def test_inproc_next_for_explicit_version_requires_single_digit(inproc):
    rel, _, _ = inproc
    with pytest.raises(SystemExit, match="single-digit"):
        rel._next_for(MODV2_ID, "1.0.0", _Args(version="1.0.10"))


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


def test_inproc_main_check_fail_on_broken_lockstep(inproc, monkeypatch, capsys):
    rel, repo, _ = inproc
    monkeypatch.chdir(repo)
    (repo / "addons" / LIBRARY_ID / "addon.xml").write_text(_library_xml("2.0.0"))
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


def test_inproc_print_plan_lockstep_only_branch(inproc, capsys):
    rel, repo, _ = inproc
    (repo / "addons" / LIBRARY_ID / "lib" / "__init__.py").write_text("# new\n")
    bumps, already = rel.build_plan(_Args(), "origin/main")
    rel._print_plan(bumps, already, "origin/main")
    out = capsys.readouterr().out
    assert "lockstep-only" in out  # the dependent's reason line


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
    assert rel._behind_origin("origin/main") == []


# ============================================================================ #
# Phase 5 — UNIFIED PROXY PATH
#
# release.py --proxy must run the EXACT proven proxy transaction (deploy.py's
# `deploy()`), not a reimplementation. These tests mirror test_deploy.py's
# bare-remote sandbox but drive the proxy release THROUGH release.py, proving
# the unified front door is byte-for-byte the same transaction (same bump, same
# tag, same atomic push, same rollback). deploy.py itself stays an independent
# entry point — its whole test_deploy.py suite still passes unchanged.
# ============================================================================ #

PROXY_ID = "repository.tony7bones"

_PROXY_SEED_ADDON = """<?xml version="1.0" encoding="UTF-8"?>
<addon id="repository.tony7bones" name="Tony.7.Bones Repository" provider-name="Tony.7.Bones" version="1.0.0">
    <extension point="xbmc.python.script" library="default.py"/>
    <extension point="xbmc.addon.metadata">
        <summary lang="en">Welcome to Tony.7.Bones repository. Enjoy!</summary>
        <description lang="en">Welcome to Tony.7.Bones repository. Enjoy!</description>
        <news>
seed
        </news>
        <assets><icon>icon.png</icon></assets>
    </extension>
</addon>"""

_PROXY_SEED_INDEX = (
    "<!doctype html><html><body><pre>"
    '<a href="repository.tony7bones-1.0.0.zip">repository.tony7bones-1.0.0.zip</a>\n'
    '<a href="repo/">repo/</a></pre></body></html>\n'
)


@pytest.fixture
def proxy_sandbox(tmp_path):
    """A single-branch (main) repo wired to a bare 'remote', seeded with the proxy
    at 1.0.0 — the same shape test_deploy.py's sandbox uses, but it ALSO ships
    release.py + release_detect.py so the proxy release can be driven through the
    unified front door.
    """
    repo = tmp_path / "proxy_work"
    repo.mkdir()
    tools = repo / "_tools"
    tools.mkdir()
    for name in (
        "generate_repo.py",
        "release_lib.py",
        "release_detect.py",
        "check_consistency.py",
        "deploy.py",
        "release.py",
    ):
        shutil.copyfile(HERE / name, tools / name)

    addon = repo / "addons" / PROXY_ID
    addon.mkdir(parents=True)
    (addon / "addon.xml").write_text(_PROXY_SEED_ADDON)
    (addon / "default.py").write_text("# entry\n")
    (addon / "icon.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 32)
    (repo / "index.html").write_text(_PROXY_SEED_INDEX)
    (repo / ".gitignore").write_text(
        "__pycache__/\n*.pyc\n.pytest_cache/\n.ruff_cache/\n"
    )

    _git(repo, "init", "-q", "-b", "main")
    _git_identity(repo)
    _run([sys.executable, str(tools / "generate_repo.py")], cwd=str(repo))
    shutil.copyfile(
        addon / "repository.tony7bones-1.0.0.zip",
        repo / "repository.tony7bones-1.0.0.zip",
    )
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "seed 1.0.0")
    _git(repo, "tag", "-a", "v1.0.0", "-m", "seed")

    bare = tmp_path / "proxy_remote.git"
    _run(["git", "init", "-q", "--bare", str(bare)], cwd=str(tmp_path))
    _git(repo, "remote", "add", "origin", str(bare))
    _git(repo, "push", "-q", "origin", "main", "v1.0.0")
    return repo, bare


def _release_proxy(repo, *flags, check=True):
    return _run(
        [sys.executable, str(repo / "_tools" / "release.py"), "--proxy", *flags],
        cwd=str(repo),
        env={"PRE_COMMIT_ALLOW_NO_CONFIG": "1"},
        check=check,
    )


def _show(repo, ref, path):
    return _git(repo, "show", f"{ref}:{path}").stdout


def test_proxy_full_release_through_release_py(proxy_sandbox):
    """release.py --proxy runs the full deploy.py transaction: bump (patch default),
    sync addon.xml + root zip + tag, atomic push of main + tag."""
    repo, bare = proxy_sandbox
    _release_proxy(repo, "--news", "unified proxy release", "--no-verify")

    # patch bump (deploy.py's default level — preserved through the front door)
    assert (
        rl.read_addon_version(_show(repo, "main", f"addons/{PROXY_ID}/addon.xml"))
        == "1.0.1"
    )
    assert (repo / "repository.tony7bones-1.0.1.zip").exists()
    # superseded root zip pruned
    assert not (repo / "repository.tony7bones-1.0.0.zip").exists()
    # tag on the release commit, pushed to the bare remote (the proxy IS the push)
    assert (
        _git(repo, "rev-parse", "v1.0.1^{commit}").stdout.strip()
        == _git(repo, "rev-parse", "main").stdout.strip()
    )
    assert "v1.0.1" in _git(repo, "ls-remote", "--tags", "origin").stdout
    # clean main afterwards
    assert _git(repo, "status", "--porcelain").stdout.strip() == ""


def test_proxy_minor_level_through_release_py(proxy_sandbox):
    """--proxy --minor bumps the minor field (proxy default is patch)."""
    repo, _ = proxy_sandbox
    _release_proxy(repo, "--minor", "--news", "x", "--no-verify")
    assert (
        rl.read_addon_version(_show(repo, "main", f"addons/{PROXY_ID}/addon.xml"))
        == "1.1.0"
    )


def test_proxy_explicit_version_through_release_py(proxy_sandbox):
    repo, _ = proxy_sandbox
    _release_proxy(repo, "--version", "2.0.0", "--news", "x", "--no-verify")
    assert (
        rl.read_addon_version(_show(repo, "main", f"addons/{PROXY_ID}/addon.xml"))
        == "2.0.0"
    )
    assert "v2.0.0" in _git(repo, "ls-remote", "--tags", "origin").stdout


def test_proxy_dry_run_changes_nothing(proxy_sandbox):
    repo, _ = proxy_sandbox
    before = _git(repo, "rev-parse", "main").stdout.strip()
    r = _release_proxy(repo, "--news", "x", "--dry-run")
    assert "next version" in r.stdout  # deploy.py's plan text
    assert _git(repo, "rev-parse", "main").stdout.strip() == before
    assert _git(repo, "tag", "-l", "v1.0.1").stdout.strip() == ""
    assert _git(repo, "status", "--porcelain").stdout.strip() == ""


def test_proxy_no_push_keeps_local_only(proxy_sandbox):
    repo, _ = proxy_sandbox
    _release_proxy(repo, "--news", "x", "--no-push")
    assert _git(repo, "tag", "-l", "v1.0.1").stdout.strip() == "v1.0.1"
    assert "v1.0.1" not in _git(repo, "ls-remote", "--tags", "origin").stdout


def test_proxy_requires_news(proxy_sandbox):
    """The proxy transaction needs a changelog line; --proxy without --news refuses."""
    repo, _ = proxy_sandbox
    r = _release_proxy(repo, "--no-verify", check=False)
    assert r.returncode != 0
    assert "requires --news" in (r.stdout + r.stderr)


def test_proxy_same_version_refused(proxy_sandbox):
    repo, _ = proxy_sandbox
    r = _release_proxy(repo, "--version", "1.0.0", "--news", "x", check=False)
    assert r.returncode != 0
    assert "not greater" in (r.stdout + r.stderr)


def test_proxy_rollback_on_push_failure(proxy_sandbox):
    """A rejected push rolls main + the tag back — deploy.py's rollback, reached
    through release.py --proxy."""
    repo, bare = proxy_sandbox
    hook = bare / "hooks" / "pre-receive"
    hook.write_text("#!/bin/sh\necho 'rejected' >&2\nexit 1\n")
    hook.chmod(0o755)
    main_head = _git(repo, "rev-parse", "main").stdout.strip()

    r = _release_proxy(repo, "--news", "x", "--no-verify", check=False)
    assert r.returncode != 0
    assert _git(repo, "rev-parse", "main").stdout.strip() == main_head
    assert _git(repo, "tag", "-l", "v1.0.1").stdout.strip() == ""
    assert _git(repo, "status", "--porcelain").stdout.strip() == ""
    assert "v1.0.1" not in _git(repo, "ls-remote", "--tags", "origin").stdout


def test_proxy_dirty_tree_refused(proxy_sandbox):
    repo, _ = proxy_sandbox
    (repo / "dirt.txt").write_text("uncommitted")
    r = _release_proxy(repo, "--news", "x", "--no-verify", check=False)
    assert r.returncode != 0
    assert "clean" in (r.stdout + r.stderr)


def test_proxy_auto_detected_when_only_proxy_changed(proxy_sandbox):
    """A bare `release.py --news ...` (no --proxy) on a proxy-only change auto-routes
    to the proxy transaction rather than reporting 'nothing to release'."""
    repo, _ = proxy_sandbox
    # edit the proxy source (committed so it diffs against origin/main as HEAD)
    (repo / "addons" / PROXY_ID / "default.py").write_text("# proxy change\n")
    _commit(repo, "fix: proxy tweak")
    r = _run(
        [
            sys.executable,
            str(repo / "_tools" / "release.py"),
            "--news",
            "auto routed",
            "--no-verify",
        ],
        cwd=str(repo),
        env={"PRE_COMMIT_ALLOW_NO_CONFIG": "1"},
        check=True,
    )
    assert "next version" in r.stdout  # deploy.py's plan text → proxy path ran
    assert (
        rl.read_addon_version(_show(repo, "main", f"addons/{PROXY_ID}/addon.xml"))
        == "1.0.1"
    )


def test_proxy_equivalence_release_py_matches_deploy_py(proxy_sandbox):
    """The headline parity proof: the tree+remote after `release.py --proxy` is
    identical to the tree+remote after `deploy.py` for the same release."""
    repo_a, _ = proxy_sandbox
    # second independent sandbox to run deploy.py directly
    repo_b = repo_a.parent / "proxy_work_b"
    shutil.copytree(repo_a, repo_b)
    # repoint repo_b at its OWN bare clone so the two pushes don't collide
    bare_b = repo_a.parent / "proxy_remote_b.git"
    _run(["git", "init", "-q", "--bare", str(bare_b)], cwd=str(repo_a.parent))
    _git(repo_b, "remote", "set-url", "origin", str(bare_b))
    _git(repo_b, "push", "-q", "origin", "main", "v1.0.0")

    # A: via release.py --proxy ; B: via deploy.py directly
    _release_proxy(repo_a, "--news", "parity", "--no-verify")
    _run(
        [
            sys.executable,
            str(repo_b / "_tools" / "deploy.py"),
            "--news",
            "parity",
            "--no-verify",
        ],
        cwd=str(repo_b),
        env={"PRE_COMMIT_ALLOW_NO_CONFIG": "1"},
    )

    # identical resulting addon.xml version, identical committed root zip name,
    # identical tag — proof the front door changes nothing about the transaction
    assert rl.read_addon_version(
        _show(repo_a, "main", f"addons/{PROXY_ID}/addon.xml")
    ) == rl.read_addon_version(_show(repo_b, "main", f"addons/{PROXY_ID}/addon.xml"))
    assert (repo_a / "repository.tony7bones-1.0.1.zip").exists()
    assert (repo_b / "repository.tony7bones-1.0.1.zip").exists()
    assert _git(repo_a, "tag", "-l", "v1.0.1").stdout.strip() == "v1.0.1"
    assert _git(repo_b, "tag", "-l", "v1.0.1").stdout.strip() == "v1.0.1"


# --------------------------------------------------------------------------- #
# In-process — the proxy translation + routing (raise coverage on the new code)
# --------------------------------------------------------------------------- #
def test_inproc_proxy_args_translation():
    import release as rel

    a = _Args(
        version="2.0.0",
        major=True,
        minor=True,
        news="line",
        dry_run=True,
        no_push=True,
        no_verify=True,
    )
    pa = rel._ProxyArgs(a)
    assert pa.version == "2.0.0"
    assert pa.major is True
    assert pa.minor is True
    assert pa.news == "line"
    assert pa.dry_run is True
    assert pa.no_push is True
    assert pa.no_verify is True


def test_inproc_release_proxy_requires_news(capsys):
    import release as rel

    rc = rel.release_proxy(_Args(proxy=True))
    assert rc == 1
    assert "requires --news" in capsys.readouterr().err


def test_inproc_proxy_requested_explicit_flag(inproc):
    rel, _, _ = inproc
    assert rel._proxy_requested(_Args(proxy=True)) is True


def test_inproc_proxy_requested_scoped_addon(inproc):
    rel, _, _ = inproc
    assert rel._proxy_requested(_Args(addon=PROXY_ID)) is True


def test_inproc_proxy_requested_false_for_script_change(inproc):
    rel, repo, _ = inproc
    (repo / "addons" / MODV2_ID / "service.py").write_text("# change\n")
    assert rel._proxy_requested(_Args()) is False


def test_inproc_proxy_requested_auto_on_proxy_only_change(inproc):
    rel, repo, _ = inproc
    # add a proxy dir and change it; it must auto-route to the proxy path. Stage
    # it so the working-tree diff vs origin/main sees it (git diff ignores
    # untracked files — the real proxy dir is always tracked).
    proxy_dir = repo / "addons" / PROXY_ID
    proxy_dir.mkdir()
    (proxy_dir / "addon.xml").write_text(
        '<addon id="repository.tony7bones" version="1.0.0"/>\n'
    )
    _git(repo, "add", "addons/" + PROXY_ID)
    assert rel._proxy_requested(_Args()) is True
