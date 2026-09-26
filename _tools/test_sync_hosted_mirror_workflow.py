"""Source-level pins on .github/workflows/sync_hosted_mirror.yml.

Same style as test_pages_workflow.py: the workflow is parsed as TEXT and the
load-bearing structure is asserted, so a refactor cannot silently drop the
trigger, the write permission, the gates, or the rebuild handoff that make the
hosted mirror follow a release without a human.
"""

from pathlib import Path

WORKFLOW = (
    Path(__file__).parent.parent / ".github" / "workflows" / "sync_hosted_mirror.yml"
)


def _text() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def test_workflow_exists():
    assert WORKFLOW.is_file()


def test_fires_on_the_ezmpp_release_dispatch_and_daily():
    text = _text()
    assert "repository_dispatch:" in text
    assert "ezmpp-release" in text
    assert "schedule:" in text and "cron:" in text
    assert "workflow_dispatch:" in text


def test_can_push_the_bump_and_dispatch_the_rebuild():
    text = _text()
    assert "contents: write" in text
    assert "actions: write" in text
    assert "gh workflow run pages.yml" in text


def test_runs_the_sync_tool_and_the_gates_before_committing():
    text = _text()
    assert "sync_hosted_mirror.py" in text
    assert "check_hosted_release_sync.py" in text
    assert "pytest _tools/" in text
    assert "generate_repo.py" in text
    assert "git push origin HEAD:main" in text
    assert text.index("check_hosted_release_sync.py") < text.index("git push")
