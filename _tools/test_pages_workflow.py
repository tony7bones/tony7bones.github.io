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
    assert "check_hosted_release_sync.py" in text, "release freshness gate"
    assert "generate_repo.py" in text, "transition staleness gate (drop at Phase 6)"


def test_deploys_via_pages_from_actions():
    text = _text()
    assert "upload-pages-artifact" in text
    assert "deploy-pages" in text
    assert "pages: write" in text


def test_concurrency_never_cancels_a_deploy_mid_flight():
    text = _text()
    assert "concurrency:" in text
    assert "cancel-in-progress: false" in text
