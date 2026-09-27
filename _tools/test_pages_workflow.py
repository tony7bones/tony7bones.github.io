"""Source-level pins on .github/workflows/pages.yml - the static pipeline.

Same style as test_update_propagation.py's service-wiring pin: the workflow
is parsed as TEXT (no yaml dep in the gate env) and the load-bearing
structure is asserted so a refactor cannot silently drop a trigger or gate.
These pins are the build-time home of the engine's staleness-bound contract:
owned content propagates on push, third-party within 24h (the daily cron).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

WORKFLOW = Path(__file__).parent.parent / ".github" / "workflows" / "pages.yml"


def _text() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def test_workflow_exists():
    assert WORKFLOW.is_file()


def test_daily_cron_bounds_third_party_staleness():
    assert "schedule:" in _text()
    assert "cron:" in _text()


def test_release_dispatch_types_are_wired():
    # estuary7-release left 2026-08-31 with the skin's decommission; ezmpp is
    # the one sibling repo that still dispatches a release event here.
    text = _text()
    assert "repository_dispatch:" in text
    assert "estuary7-release" not in text
    assert "ezmpp-release" in text


def test_dispatch_inputs_exist():
    text = _text()
    assert "allow_catalog_shrink" in text
    assert "refresh_third_party" in text


def test_verify_runs_after_deploy_from_the_consumer_seat():
    text = _text()
    assert "needs: deploy" in text
    assert "verify_live_site.py" in text
    assert "needs: build" in text


def test_pre_deploy_gates_are_present():
    text = _text()
    assert "check_site_secrets.py" in text, "artifact secret gate"
    assert "diff -r _site _site2" in text, "determinism double-build gate"
    assert "check_hosted_release_sync.py" not in text, (
        "the freshness gate retired 2026-09-26: the build resolves the version"
    )
    assert "generate_repo.py" in text, "transition staleness gate (drop at Phase 6)"


def test_build_resolves_release_versions_with_the_workflow_token():
    """Both site builds pass GH_TOKEN so static_catalog resolves the latest
    EZM++ release through the REST API rather than the anonymous redirect,
    and no separate freshness gate or hosted-mirror sync workflow exists to
    fall behind (both retired 2026-09-26). The token is the stored
    T7B_SOURCE_READ_TOKEN when present, kept from when the skin repo (now
    moquette/kodi-estuarypp) was private, else GITHUB_TOKEN; the
    SAME expression in both steps, or the determinism diff compares a
    resolved skin against a stale one."""
    text = _text()
    token = "GH_TOKEN: ${{ secrets.T7B_SOURCE_READ_TOKEN || secrets.GITHUB_TOKEN }}"
    build = text[text.index("- name: Build site") : text.index("- name: Secret gate")]
    assert token in build
    determinism = text[
        text.index("- name: Determinism gate") : text.index(
            "- name: Upload build manifest"
        )
    ]
    assert token in determinism
    workflows = WORKFLOW.parent
    assert not (workflows / "sync_hosted_mirror.yml").exists()
    assert "sync_hosted_mirror" not in text
    assert "check_hosted_release_sync" not in text


def test_pages_is_the_only_push_workflow():
    """generate_repo.yml ("Validate Kodi Repository") duplicated this
    workflow's build job step for step, and its one extra trigger was a
    branch that does not exist; deleted 2026-09-26. The source gates it
    carried (tests, lint, generator staleness, version bump) live here."""
    workflows = WORKFLOW.parent
    assert not (workflows / "generate_repo.yml").exists()
    names = sorted(p.name for p in workflows.glob("*.yml"))
    assert names == ["ci_failure_alert.yml", "pages.yml", "pages_source_guard.yml"]
    text = _text()
    assert "python3 -m pytest _tools/ -q" in text
    assert "ruff check _tools/" in text
    assert "generate_repo.py" in text


def _step(text: str, name: str) -> str:
    start = text.index(f"- name: {name}")
    nxt = text.find("\n      - ", start + 1)
    return text[start : nxt if nxt != -1 else len(text)]


def test_source_gates_run_on_push_only_and_artifact_gates_on_every_event():
    """The suite, lint and the version-bump gate judge the pushed source and
    run on push only; the cron and repository_dispatch runs change no source
    and used to spend 40s re-running them. The build, secret gate, determinism
    diff and live verify judge the artifact and stay unconditional."""
    text = _text()
    for name in ("Test suite", "Lint", "Version-bump gate (every changed add-on bumped)"):
        assert "if: github.event_name == 'push'" in _step(text, name), name
    for name in (
        "Build site",
        "Secret gate on the built artifact",
        "Determinism gate (double build, byte diff)",
        "Consumer-seat verification (the same URLs Kodi uses)",
    ):
        assert "if:" not in _step(text, name), name


def test_version_bump_gate_uses_the_push_before_sha_as_baseline():
    """On main, origin/main already equals the pushed HEAD, so the gate must
    compare across the pushed range (github.event.before) or it judges the
    commit against itself and passes vacuously."""
    step = _step(_text(), "Version-bump gate (every changed add-on bumped)")
    assert "BEFORE_SHA: ${{ github.event.before }}" in step
    assert 'CHECK_VERSIONS_BASE_REF="$BEFORE_SHA" python3 _tools/check_versions.py' in step
    assert "0000000000000000000000000000000000000000" in step
    assert "git rev-parse --verify --quiet" in step


def test_deploys_via_pages_from_actions():
    text = _text()
    assert "upload-pages-artifact" in text
    assert "deploy-pages" in text
    assert "pages: write" in text


def test_concurrency_never_cancels_a_deploy_mid_flight():
    text = _text()
    assert "concurrency:" in text
    assert "cancel-in-progress: false" in text


def test_verify_redeploys_once_when_the_branch_build_wins_the_race():
    text = _text()
    assert "Redeploy once if the branch build clobbered this deploy" in text
    assert "if: failure() && github.event_name == 'push'" in text
    assert "gh workflow run pages.yml --ref main" in text
    assert "actions: write" in text
