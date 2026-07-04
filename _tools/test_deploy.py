"""Full coverage for the release automation.

Two layers:
  * unit tests for the pure logic in release_lib (version math, file transforms,
    the single-source-of-truth DeployPlan);
  * a real end-to-end system test that runs the ACTUAL deploy.py against a
    throwaway git repo with a bare "remote" — proving the whole bump -> build ->
    commit-main -> tag -> push (main + tag) pipeline, plus every guardrail,
    without ever touching the live remote.

Single-branch model: there is no virtual-repo branch and no separate hosted
self-update addon.xml; the proxy's self-update source is the canonical main
addon.xml itself. The three version-bearing locations are main addon.xml, the
root zip filename, and the git tag (the root index.html no longer carries a link).
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

# ============================================================================ #
# Unit tests — pure version math
# ============================================================================ #


@pytest.mark.parametrize("s", ["1.0.0", "0.0.1", "10.20.30"])
def test_parse_version_valid(s):
    assert rl.format_version(rl.parse_version(s)) == s


@pytest.mark.parametrize("s", ["v1.0.0", "1.0", "1.0.x", "", "1..0", "1.0.0.0", None])
def test_parse_version_rejects_garbage(s):
    with pytest.raises((ValueError, TypeError)):
        rl.parse_version(s)


def test_bump_patch_default():
    assert rl.bump("1.0.7") == "1.0.8"


def test_bump_minor_resets_patch():
    assert rl.bump("1.0.7", "minor") == "1.1.0"


def test_bump_major_resets_lower():
    assert rl.bump("1.2.3", "major") == "2.0.0"


def test_bump_unknown_level():
    with pytest.raises(ValueError):
        rl.bump("1.0.0", "mega")


def test_is_greater_true_and_false():
    assert rl.is_greater("1.0.8", "1.0.7")
    assert not rl.is_greater("1.0.7", "1.0.7")  # equal — the #1 failure mode
    assert not rl.is_greater("1.0.6", "1.0.7")  # lower


# ============================================================================ #
# Unit tests — single-digit-per-component scheme (rollover bump + validator)
# ============================================================================ #


@pytest.mark.parametrize(
    "start,expected",
    [
        ("1.1.3", "1.1.4"),  # plain patch
        ("1.0.9", "1.1.0"),  # patch carries into minor
        ("1.9.9", "2.0.0"),  # patch carries all the way into major
    ],
)
def test_bump_patch_rollover(start, expected):
    assert rl.bump(start) == expected


@pytest.mark.parametrize(
    "start,expected",
    [
        ("1.3.7", "1.4.0"),  # plain minor (patch reset)
        ("1.9.0", "2.0.0"),  # minor carries into major
    ],
)
def test_bump_minor_rollover(start, expected):
    assert rl.bump(start, "minor") == expected


def test_bump_major_rollover():
    assert rl.bump("2.1.1", "major") == "3.0.0"


def test_bump_patch_ceiling_raises():
    with pytest.raises(ValueError, match="ceiling"):
        rl.bump("9.9.9")


def test_bump_major_ceiling_raises():
    with pytest.raises(ValueError, match="9.9.9"):
        rl.bump("9.9.9", "major")


def test_is_greater_across_rollover():
    assert rl.is_greater("1.1.0", "1.0.9")
    assert rl.is_greater("2.0.0", "1.9.9")
    # the legacy baseline (1.0.14) still parses and compares — parse_version is
    # deliberately NOT tightened, so the transition to 2.0.0 keeps working.
    assert rl.is_greater("2.0.0", "1.0.14")


@pytest.mark.parametrize("v", ["0.0.0", "9.9.9", "1.1.0"])
def test_is_single_digit_true(v):
    assert rl.is_single_digit(v)


@pytest.mark.parametrize("v", ["10.0.0", "1.10.0", "1.0.10"])
def test_is_single_digit_false(v):
    assert not rl.is_single_digit(v)


def test_is_single_digit_false_on_garbage():
    assert not rl.is_single_digit("1.0")
    assert not rl.is_single_digit(None)


# ============================================================================ #
# Unit tests — filename / tag construction
# ============================================================================ #


def test_zip_name():
    assert rl.zip_name("1.0.8") == "repository.tony7bones-1.0.8.zip"


def test_zip_name_roundtrip():
    for v in ("1.0.0", "2.5.9", "10.0.1"):
        assert rl.version_from_zip_name(rl.zip_name(v)) == v


def test_version_from_zip_name_rejects_foreign():
    with pytest.raises(ValueError):
        rl.version_from_zip_name("repository.umbrella-2.2.6.zip")


def test_tag_name():
    assert rl.tag_name("1.0.8") == "v1.0.8"


def test_stale_root_zips_keeps_only_current():
    names = [
        "repository.tony7bones-1.0.12.zip",
        "repository.tony7bones-1.0.13.zip",
        "repository.tony7bones-1.0.14.zip",
        "index.html",
        "style.css",
        "repository.umbrella-2.2.6.zip",  # third-party, must never be touched
    ]
    stale = rl.stale_root_zips(names, "1.0.14")
    assert stale == [
        "repository.tony7bones-1.0.12.zip",
        "repository.tony7bones-1.0.13.zip",
    ]


def test_stale_root_zips_noop_when_only_current_present():
    names = ["repository.tony7bones-1.0.14.zip", "index.html"]
    assert rl.stale_root_zips(names, "1.0.14") == []


# ============================================================================ #
# Unit tests — file-content transforms
# ============================================================================ #

ADDON_XML = """<?xml version="1.0" encoding="UTF-8"?>
<addon id="repository.tony7bones" name="Tony.7.Bones Repository" provider-name="Tony.7.Bones" version="1.0.7">
    <extension point="xbmc.addon.metadata">
        <news>
v1.0.7: old line
        </news>
    </extension>
</addon>"""


def test_read_addon_version():
    assert rl.read_addon_version(ADDON_XML) == "1.0.7"


def test_read_addon_version_ignores_xml_declaration():
    # the <?xml version="1.0"?> must not be mistaken for the addon version
    assert rl.read_addon_version(ADDON_XML) == "1.0.7"


def test_set_addon_version():
    out = rl.set_addon_version(ADDON_XML, "1.0.8")
    assert rl.read_addon_version(out) == "1.0.8"
    assert '<?xml version="1.0"' in out  # xml decl untouched


def test_set_addon_version_allows_legacy_date_stamped_scheme():
    # EZ Maintenance++'s real shipped scheme: four components, not X.Y.Z -
    # the strict parser used to run unconditionally here and reject this.
    out = rl.set_addon_version(ADDON_XML, "2026.07.04.0")
    assert rl.read_addon_version(out) == "2026.07.04.0"


def test_set_addon_news():
    out = rl.set_addon_news(ADDON_XML, "v1.0.8: brand new")
    assert "v1.0.8: brand new" in out
    assert "old line" not in out


def test_set_addon_news_missing_block():
    with pytest.raises(ValueError):
        rl.set_addon_news('<addon version="1.0.0"/>', "x")


# ============================================================================ #
# Unit tests — Phase 0: release_lib generalization for the script.* tool
# (next_version, prepend_addon_news with cap, set_import_version lockstep)
# ============================================================================ #

# A bootstrap-shaped manifest: multiple imports, one of which is the lockstep
# target (the shared library). Mirrors the real addon.xml attribute order.
BOOTSTRAP_XML = """<?xml version="1.0" encoding="UTF-8"?>
<addon id="script.tony7bones.bootstrap" version="1.8.0" provider-name="tony7bones">
  <requires>
    <import addon="xbmc.python" version="3.0.0"/>
    <import addon="xbmc.addon" version="12.0.0"/>
    <import addon="script.module.tony7bones" version="1.5.0"/>
  </requires>
  <extension point="xbmc.addon.metadata">
    <news>
        v1.8.0: latest line
        v1.7.0: prior line
    </news>
  </extension>
</addon>"""


def test_next_version_default_is_minor():
    # The locked default level for the script.* tool is MINOR (deploy.py keeps
    # its own patch default by calling bump directly).
    assert rl.next_version("1.5.0") == "1.6.0"


@pytest.mark.parametrize(
    "level,expected",
    [("patch", "1.5.1"), ("minor", "1.6.0"), ("major", "2.0.0")],
)
def test_next_version_levels(level, expected):
    assert rl.next_version("1.5.0", level) == expected


def test_next_version_ceiling_raises():
    with pytest.raises(ValueError, match="ceiling"):
        rl.next_version("9.9.9", "minor")


# --- set_import_version (the lockstep transform) ---------------------------- #


def test_set_import_version_raises_the_lockstep_target():
    out = rl.set_import_version(BOOTSTRAP_XML, "script.module.tony7bones", "1.6.0")
    assert rl.read_import_version(out, "script.module.tony7bones") == "1.6.0"


def test_set_import_version_leaves_other_imports_untouched():
    out = rl.set_import_version(BOOTSTRAP_XML, "script.module.tony7bones", "1.6.0")
    # the framework imports must be byte-for-byte unchanged
    assert '<import addon="xbmc.python" version="3.0.0"/>' in out
    assert '<import addon="xbmc.addon" version="12.0.0"/>' in out
    assert rl.read_import_version(out, "xbmc.python") == "3.0.0"
    assert rl.read_import_version(out, "xbmc.addon") == "12.0.0"


def test_set_import_version_is_idempotent():
    out1 = rl.set_import_version(BOOTSTRAP_XML, "script.module.tony7bones", "1.6.0")
    out2 = rl.set_import_version(out1, "script.module.tony7bones", "1.6.0")
    assert out1 == out2


def test_set_import_version_raises_when_import_absent():
    with pytest.raises(ValueError, match="no <import"):
        rl.set_import_version(BOOTSTRAP_XML, "plugin.video.nope", "1.0.0")


def test_set_import_version_rejects_bad_version():
    with pytest.raises(ValueError):
        rl.set_import_version(BOOTSTRAP_XML, "script.module.tony7bones", "1.6")


def test_read_import_version_absent_is_none():
    assert rl.read_import_version(BOOTSTRAP_XML, "plugin.video.nope") is None


def test_set_import_version_reversed_attribute_order():
    # version= before addon= must still be rewritten correctly.
    xml = '<requires><import version="1.5.0" addon="script.module.tony7bones"/></requires>'
    assert rl.read_import_version(xml, "script.module.tony7bones") == "1.5.0"
    out = rl.set_import_version(xml, "script.module.tony7bones", "1.6.0")
    assert rl.read_import_version(out, "script.module.tony7bones") == "1.6.0"
    assert 'addon="script.module.tony7bones"' in out


# --- prepend_addon_news (rolling, capped, idempotent) ----------------------- #


def test_prepend_addon_news_prepends_newest_first():
    out = rl.prepend_addon_news(BOOTSTRAP_XML, "brand new fix", version="1.9.0")
    body = rl._NEWS_RE.search(out).group(2)
    lines = [ln.strip() for ln in body.splitlines() if ln.strip()]
    assert lines[0] == "v1.9.0: brand new fix"
    assert lines[1] == "v1.8.0: latest line"
    assert lines[2] == "v1.7.0: prior line"


def test_prepend_addon_news_caps_rolling_history():
    xml = BOOTSTRAP_XML
    # ship 1.9.0 ... up the chain past the cap; the oldest must fall off
    for i, v in enumerate(["1.9.0", "2.0.0", "2.1.0", "2.2.0", "2.3.0"]):
        xml = rl.prepend_addon_news(xml, f"entry {i}", version=v)
    body = rl._NEWS_RE.search(xml).group(2)
    lines = [ln.strip() for ln in body.splitlines() if ln.strip()]
    assert len(lines) == rl.NEWS_CAP  # capped at 6
    assert lines[0] == "v2.3.0: entry 4"
    # the original oldest (v1.7.0) has rolled off
    assert not any("v1.7.0" in ln for ln in lines)


def test_prepend_addon_news_respects_explicit_cap():
    out = rl.prepend_addon_news(BOOTSTRAP_XML, "x", version="1.9.0", cap=2)
    lines = [
        ln.strip() for ln in rl._NEWS_RE.search(out).group(2).splitlines() if ln.strip()
    ]
    assert lines == ["v1.9.0: x", "v1.8.0: latest line"]


def test_prepend_addon_news_idempotent_same_version():
    # MF-9: re-running for the SAME version must not stack a duplicate entry.
    out1 = rl.prepend_addon_news(BOOTSTRAP_XML, "the fix", version="1.9.0")
    out2 = rl.prepend_addon_news(out1, "the fix again", version="1.9.0")
    assert out1 == out2  # second prepend for v1.9.0 is a no-op


def test_prepend_addon_news_missing_block_raises():
    with pytest.raises(ValueError, match="no <news>"):
        rl.prepend_addon_news('<addon version="1.0.0"/>', "x", version="1.0.1")


def test_prepend_addon_news_rejects_bad_version():
    with pytest.raises(ValueError):
        rl.prepend_addon_news(BOOTSTRAP_XML, "x", version="1.9")


def test_prepend_addon_news_allows_legacy_date_stamped_scheme():
    # EZ Maintenance++'s real shipped scheme: four components, not X.Y.Z -
    # the strict parser used to run unconditionally here and reject this,
    # discovered while actually releasing the NFS-port fix through this
    # add-on for the first time.
    out = rl.prepend_addon_news(BOOTSTRAP_XML, "the fix", version="2026.07.04.0")
    lines = [
        ln.strip() for ln in rl._NEWS_RE.search(out).group(2).splitlines() if ln.strip()
    ]
    assert lines[0] == "v2026.07.04.0: the fix"


def test_validate_version_for_write_rejects_incomplete_version():
    # A 2-component version is never a valid write target, single-digit
    # scheme or not - it must be rejected even though it parses fine under
    # the loose (any-length) parser used for the legacy 4-component case.
    with pytest.raises(ValueError):
        rl.validate_version_for_write("1.9")


def test_validate_version_for_write_accepts_legacy_and_normal():
    rl.validate_version_for_write("1.9.0")  # normal, 3-component
    rl.validate_version_for_write("1.4.10")  # normal, double-digit component
    rl.validate_version_for_write("2026.07.04.0")  # legacy, 4-component


def test_prepend_addon_news_into_empty_body():
    xml = "<addon><extension><news>\n        </news></extension></addon>"
    out = rl.prepend_addon_news(xml, "first ever", version="1.0.0")
    lines = [
        ln.strip() for ln in rl._NEWS_RE.search(out).group(2).splitlines() if ln.strip()
    ]
    assert lines == ["v1.0.0: first ever"]


def test_is_root_zip_name():
    # the consistency gate reads the shipped version from this filename
    assert rl.is_root_zip_name("repository.tony7bones-1.0.7.zip")
    assert rl.is_root_zip_name("repository.tony7bones-2.2.1.zip")
    assert not rl.is_root_zip_name("repository.umbrella-2.2.6.zip")
    assert not rl.is_root_zip_name("index.html")
    assert not rl.is_root_zip_name("repository.tony7bones.zip")  # no version


# ============================================================================ #
# Unit tests — DeployPlan single source of truth
# ============================================================================ #


def test_deployplan_all_locations_carry_same_version():
    plan = rl.DeployPlan("1.0.8")
    assert set(plan.all_versions().values()) == {"1.0.8"}
    assert plan.is_consistent()


def test_deployplan_tag_format():
    assert rl.DeployPlan("1.0.8").tag == "v1.0.8"


def test_deployplan_rejects_bad_version():
    with pytest.raises(ValueError):
        rl.DeployPlan("1.0")


def test_deployplan_rejects_double_digit_component():
    with pytest.raises(ValueError, match="single-digit"):
        rl.DeployPlan("1.0.10")


def test_deployplan_accepts_ceiling():
    # 9.9.9 is the legal ceiling — it must remain a valid single-digit version.
    assert rl.DeployPlan("9.9.9").version == "9.9.9"


def test_deployplan_single_source_of_truth():
    # there is exactly one way to set the version: the constructor argument.
    # Three version-bearing locations now (the root index no longer carries a
    # zip link — the gate reads the version from the root zip filename).
    plan = rl.DeployPlan("3.1.4")
    locations = plan.all_versions()
    assert len(locations) == 3
    assert set(locations) == {"main_addon", "root_zip", "tag"}
    assert all(v == "3.1.4" for v in locations.values())


# ============================================================================ #
# End-to-end system test — real deploy.py against a sandbox + bare remote
# ============================================================================ #

SEED_ADDON = """<?xml version="1.0" encoding="UTF-8"?>
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

SEED_INDEX = (
    "<!doctype html><html><body><pre>"
    '<a href="repository.tony7bones-1.0.0.zip">repository.tony7bones-1.0.0.zip</a>\n'
    '<a href="repo/">repo/</a></pre></body></html>\n'
)


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


@pytest.fixture
def sandbox(tmp_path):
    """A self-contained single-branch repo (main) wired to a bare 'remote'."""
    repo = tmp_path / "repo_work"
    repo.mkdir()
    tools = repo / "_tools"
    tools.mkdir()

    # ship the REAL tooling so the system test exercises production code
    for name in (
        "generate_repo.py",
        "release_lib.py",
        "check_consistency.py",
        "deploy.py",
    ):
        shutil.copyfile(HERE / name, tools / name)

    addon = repo / "addons" / "repository.tony7bones"
    addon.mkdir(parents=True)
    (addon / "addon.xml").write_text(SEED_ADDON)
    (addon / "default.py").write_text("# entry\n")
    (addon / "icon.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 32)
    (repo / "index.html").write_text(SEED_INDEX)
    (repo / ".gitignore").write_text(
        "__pycache__/\n*.pyc\n.pytest_cache/\n.ruff_cache/\n"
    )

    _git(repo, "init", "-q", "-b", "main")
    _git_identity(repo)

    # build the seed 1.0.0 artifacts with the real generator, sync the root zip
    _run([sys.executable, str(tools / "generate_repo.py")], cwd=str(repo))
    shutil.copyfile(
        addon / "repository.tony7bones-1.0.0.zip",
        repo / "repository.tony7bones-1.0.0.zip",
    )
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "seed 1.0.0")
    _git(repo, "tag", "-a", "v1.0.0", "-m", "seed")

    # bare "remote"
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
    _git(repo, "push", "-q", "origin", "main", "v1.0.0")

    return repo, bare


def _deploy(repo, *flags, check=True):
    return _run(
        [sys.executable, str(repo / "_tools" / "deploy.py"), *flags],
        cwd=str(repo),
        env={"PRE_COMMIT_ALLOW_NO_CONFIG": "1"},
        check=check,
    )


def _show(repo, ref, path):
    return _git(repo, "show", f"{ref}:{path}").stdout


def test_system_full_deploy_happy_path(sandbox):
    repo, bare = sandbox
    _deploy(repo, "--news", "system test", "--no-verify")

    # all version-bearing locations land on 1.0.1 (single-branch: main addon
    # doubles as the proxy self-update source — no separate hosted addon)
    assert (
        rl.read_addon_version(
            _show(repo, "main", "addons/repository.tony7bones/addon.xml")
        )
        == "1.0.1"
    )
    # the root zip is served, but the bare-URL index no longer LISTS it (the gate
    # reads the version from the zip filename; the installer is browsed via repositories/)
    assert "repository.tony7bones-1.0.1.zip" not in _show(repo, "main", "index.html")
    assert (repo / "repository.tony7bones-1.0.1.zip").exists()
    # the superseded root installer zip is pruned (working tree + committed)
    assert not (repo / "repository.tony7bones-1.0.0.zip").exists()
    assert (
        "repository.tony7bones-1.0.0.zip"
        not in _git(repo, "ls-tree", "--name-only", "main").stdout
    )
    # there is no virtual-repo branch
    assert _git(repo, "branch", "--list", "virtual-repo").stdout.strip() == ""

    # root zip byte-identical to the generated zip
    import hashlib

    def sha(p):
        return hashlib.sha256(Path(p).read_bytes()).hexdigest()

    assert sha(repo / "repository.tony7bones-1.0.1.zip") == sha(
        repo / "addons" / "repository.tony7bones" / "repository.tony7bones-1.0.1.zip"
    )

    # tag created on the main release commit
    assert (
        _git(repo, "rev-parse", "v1.0.1^{commit}").stdout.strip()
        == _git(repo, "rev-parse", "main").stdout.strip()
    )

    # pushed to the bare remote: main moved + tag present
    assert "v1.0.1" in _git(repo, "ls-remote", "--tags", "origin").stdout

    # working tree restored to main, clean
    assert _git(repo, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip() == "main"
    assert _git(repo, "status", "--porcelain").stdout.strip() == ""


def test_system_consistency_gate_passes_after_deploy(sandbox):
    repo, _ = sandbox
    _deploy(repo, "--news", "x", "--no-verify")
    r = _run(
        [sys.executable, str(repo / "_tools" / "deploy.py"), "check"],
        cwd=str(repo),
        check=False,
    )
    assert r.returncode == 0, r.stdout + r.stderr
    assert "OK" in r.stdout


def test_system_same_version_refused(sandbox):
    repo, _ = sandbox
    r = _deploy(repo, "--version", "1.0.0", "--news", "x", check=False)
    assert r.returncode != 0
    assert "not greater" in (r.stdout + r.stderr)


def test_system_lower_version_refused(sandbox):
    repo, _ = sandbox
    r = _deploy(repo, "--version", "0.9.0", "--news", "x", check=False)
    assert r.returncode != 0


def test_system_double_digit_version_refused(sandbox):
    """An explicit non-single-digit --version is refused with no mutation."""
    repo, _ = sandbox
    before = _git(repo, "rev-parse", "main").stdout.strip()
    r = _deploy(repo, "--version", "1.0.10", "--news", "x", check=False)
    assert r.returncode != 0
    assert "single-digit" in (r.stdout + r.stderr)
    # nothing mutated locally
    assert _git(repo, "rev-parse", "main").stdout.strip() == before
    assert _git(repo, "tag", "-l", "v1.0.10").stdout.strip() == ""


def test_system_dry_run_changes_nothing(sandbox):
    repo, _ = sandbox
    before = _git(repo, "rev-parse", "main").stdout.strip()
    r = _deploy(repo, "--news", "x", "--dry-run")
    assert "next version" in r.stdout
    assert _git(repo, "rev-parse", "main").stdout.strip() == before
    assert _git(repo, "tag", "-l", "v1.0.1").stdout.strip() == ""
    assert _git(repo, "status", "--porcelain").stdout.strip() == ""


def test_system_dirty_tree_refused(sandbox):
    repo, _ = sandbox
    (repo / "dirt.txt").write_text("uncommitted")
    r = _deploy(repo, "--news", "x", "--no-verify", check=False)
    assert r.returncode != 0
    assert "clean" in (r.stdout + r.stderr)


def test_system_deterministic_regen_clean_after_deploy(sandbox):
    repo, _ = sandbox
    _deploy(repo, "--news", "x", "--no-verify")
    _run([sys.executable, str(repo / "_tools" / "generate_repo.py")], cwd=str(repo))
    assert _git(repo, "status", "--porcelain").stdout.strip() == ""


def test_system_consistency_gate_detects_mismatch(sandbox):
    repo, _ = sandbox
    _deploy(repo, "--news", "x", "--no-verify")  # now consistent at 1.0.1
    # corrupt the main addon.xml version so it disagrees with the root zip filename
    addon = repo / "addons" / "repository.tony7bones" / "addon.xml"
    addon.write_text(rl.set_addon_version(addon.read_text(), "9.9.9"))
    _git(repo, "add", "-A")
    _run(
        ["git", "-C", str(repo), "commit", "-q", "-m", "corrupt"],
        cwd=str(repo),
        env={"PRE_COMMIT_ALLOW_NO_CONFIG": "1"},
    )

    r = _run(
        [sys.executable, str(repo / "_tools" / "deploy.py"), "check"],
        cwd=str(repo),
        check=False,
    )
    assert r.returncode == 1
    assert "mismatch" in r.stdout


def test_system_two_consecutive_deploys_climb(sandbox):
    repo, _ = sandbox
    _deploy(repo, "--news", "first", "--no-verify")
    _deploy(repo, "--news", "second", "--no-verify")
    assert (
        rl.read_addon_version(
            _show(repo, "main", "addons/repository.tony7bones/addon.xml")
        )
        == "1.0.2"
    )
    assert "v1.0.2" in _git(repo, "ls-remote", "--tags", "origin").stdout


# --- failure-side coverage (architect review D1/D2/D3/D4) -------------------- #


def test_system_behind_origin_refused(sandbox):
    """D1: a local branch behind origin must be refused BEFORE any mutation."""
    repo, bare = sandbox
    other = repo.parent / "other_clone"
    _run(["git", "clone", "-q", str(bare), str(other)], cwd=str(repo.parent))
    _git_identity(other)
    _git(other, "checkout", "-q", "main")
    (other / "remote_change.txt").write_text("advance")
    _git(other, "add", "-A")
    _run(
        ["git", "-C", str(other), "commit", "-q", "-m", "remote advance"],
        cwd=str(other),
    )
    _git(other, "push", "-q", "origin", "main")

    before = _git(repo, "rev-parse", "main").stdout.strip()
    r = _deploy(repo, "--news", "x", "--no-verify", check=False)
    assert r.returncode != 0
    assert "behind" in (r.stdout + r.stderr)
    # nothing mutated locally
    assert _git(repo, "rev-parse", "main").stdout.strip() == before
    assert _git(repo, "tag", "-l", "v1.0.1").stdout.strip() == ""


def test_system_rollback_on_push_failure(sandbox):
    """A rejected push must roll main and the tag back to pre-deploy state."""
    repo, bare = sandbox
    hook = bare / "hooks" / "pre-receive"
    hook.write_text("#!/bin/sh\necho 'remote rejects this push' >&2\nexit 1\n")
    hook.chmod(0o755)

    main_head = _git(repo, "rev-parse", "main").stdout.strip()

    r = _deploy(repo, "--news", "x", "--no-verify", check=False)
    assert r.returncode != 0

    # every ref restored to pre-deploy state
    assert _git(repo, "rev-parse", "main").stdout.strip() == main_head
    assert _git(repo, "tag", "-l", "v1.0.1").stdout.strip() == ""
    # left on a clean main
    assert _git(repo, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip() == "main"
    assert _git(repo, "status", "--porcelain").stdout.strip() == ""
    # remote was never advanced
    assert "v1.0.1" not in _git(repo, "ls-remote", "--tags", "origin").stdout


def test_system_no_push_keeps_local_only(sandbox):
    """--no-push commits + tags locally but never advances the remote."""
    repo, _ = sandbox
    _deploy(repo, "--news", "x", "--no-push")
    assert _git(repo, "tag", "-l", "v1.0.1").stdout.strip() == "v1.0.1"
    assert (
        rl.read_addon_version(
            _show(repo, "main", "addons/repository.tony7bones/addon.xml")
        )
        == "1.0.1"
    )
    assert "v1.0.1" not in _git(repo, "ls-remote", "--tags", "origin").stdout


def test_system_non_main_branch_refused(sandbox):
    """Deploy must only run from main."""
    repo, _ = sandbox
    _git(repo, "checkout", "-q", "-b", "feature")
    r = _deploy(repo, "--news", "x", "--no-verify", check=False)
    assert r.returncode != 0
    assert "not on the main branch" in (r.stdout + r.stderr)


def test_system_offline_origin_warns_and_proceeds(sandbox):
    """An unreachable origin degrades the behind-check to a warning (with --no-push)."""
    repo, _ = sandbox
    _git(repo, "remote", "set-url", "origin", str(repo.parent / "missing.git"))
    r = _deploy(repo, "--news", "x", "--no-push")
    assert r.returncode == 0
    assert "could not fetch origin" in (r.stdout + r.stderr)
    assert (
        rl.read_addon_version(
            _show(repo, "main", "addons/repository.tony7bones/addon.xml")
        )
        == "1.0.1"
    )


def test_system_no_origin_remote_proceeds(sandbox):
    """No origin remote at all: behind-check is skipped, deploy still works."""
    repo, _ = sandbox
    _git(repo, "remote", "remove", "origin")
    r = _deploy(repo, "--news", "x", "--no-push")
    assert r.returncode == 0
    assert _git(repo, "tag", "-l", "v1.0.1").stdout.strip() == "v1.0.1"


# --- verify_live / _get (in-process, network mocked) ------------------------- #


def test_verify_live_success(tmp_path, monkeypatch):
    sys.path.insert(0, str(HERE))
    import deploy as dp

    z = tmp_path / "repository.tony7bones-1.0.1.zip"
    z.write_bytes(b"zipbytes")

    def fake_get(url):
        if url.endswith(".zip"):
            return 200, b"zipbytes"
        if "addons.xml" in url:
            return 200, b'<addon version="1.0.1"/>'
        return 200, b'<a href="repository.tony7bones-1.0.1.zip">'

    monkeypatch.setattr(dp, "_get", fake_get)
    assert dp.verify_live("1.0.1", str(z), attempts=2, delay=0) is True


def test_verify_live_timeout_returns_false(tmp_path, monkeypatch):
    import deploy as dp

    z = tmp_path / "x.zip"
    z.write_bytes(b"d")
    monkeypatch.setattr(dp, "_get", lambda url: (404, b""))
    assert dp.verify_live("1.0.1", str(z), attempts=2, delay=0) is False


def test_verify_live_stale_metadata_returns_false(tmp_path, monkeypatch):
    import deploy as dp

    z = tmp_path / "repository.tony7bones-1.0.1.zip"
    z.write_bytes(b"zipbytes")

    # zip is live and matches, but addons.xml/index still serve the old version
    def fake_get(url):
        if url.endswith(".zip"):
            return 200, b"zipbytes"
        return 200, b"old content version 0.0.0"

    monkeypatch.setattr(dp, "_get", fake_get)
    assert dp.verify_live("1.0.1", str(z), attempts=2, delay=0) is False


def test_get_handles_network_error(monkeypatch):
    import deploy as dp

    def boom(*a, **k):
        raise OSError("no network")

    monkeypatch.setattr(dp.urllib.request, "urlopen", boom)
    assert dp._get("https://example.invalid/x") == (0, b"")
