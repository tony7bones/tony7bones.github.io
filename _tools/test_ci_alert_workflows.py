"""Source-level pins on the two operational workflows added 2026-09-26.

ci_failure_alert.yml: a failed deploy run opens or updates an issue
assigned to the owner, and the next green run closes it. pages_source_guard.yml:
the Pages source is kept on the Actions artifact, never the branch. Same text
pinning style as test_pages_workflow.py.
"""

from pathlib import Path

WORKFLOWS = Path(__file__).parent.parent / ".github" / "workflows"


def test_failure_alert_watches_the_one_push_workflow():
    text = (WORKFLOWS / "ci_failure_alert.yml").read_text(encoding="utf-8")
    assert "workflow_run:" in text
    assert 'workflows: ["Build & Deploy Pages"]' in text
    # generate_repo.yml ("Validate Kodi Repository") was deleted 2026-09-26; a
    # workflow_run trigger naming a workflow that does not exist never fires,
    # so the list must not carry it.
    assert not (WORKFLOWS / "generate_repo.yml").exists()
    assert "issues: write" in text
    assert "--assignee" in text
    assert "gh issue close" in text, "a green run must close the alert"


def test_pages_source_guard_puts_the_source_back_on_workflow():
    text = (WORKFLOWS / "pages_source_guard.yml").read_text(encoding="utf-8")
    assert "schedule:" in text and "workflow_dispatch:" in text
    assert "pages: write" in text
    assert "build_type=workflow" in text
