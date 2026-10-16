"""check_catalog_fresh: a stale entry fails the run after the deploy.

The 2026-10-01..15 silence: POV's upstream index went empty, POV and the
skin were served stale for two weeks, and every run stayed green.
"""

import gzip
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))

import check_catalog_fresh as ccf  # noqa: E402
import static_catalog as sc  # noqa: E402

WORKFLOWS = Path(__file__).parent.parent / ".github" / "workflows"


def _manifest(tmp_path, **stale_by_id):
    entries = {
        aid: {"version": "1.0", "stale": is_stale}
        for aid, is_stale in stale_by_id.items()
    }
    path = tmp_path / "catalog.json"
    path.write_text(json.dumps({"count": len(entries), "entries": entries}))
    return str(path)


def test_fresh_catalog_passes(tmp_path, capsys):
    path = _manifest(tmp_path, a=False, b=False)
    assert ccf.main([path]) == 0
    assert "0 stale of 2" in capsys.readouterr().out


def test_any_stale_entry_fails_with_an_error_annotation(tmp_path, capsys):
    path = _manifest(
        tmp_path, **{"plugin.video.pov": True, "skin.estuary.plusplus": True, "x": False}
    )
    assert ccf.main([path]) == 1
    out = capsys.readouterr().out
    assert "::error::plugin.video.pov served STALE" in out
    assert "::error::skin.estuary.plusplus served STALE" in out
    assert "::error::x " not in out


def test_stale_entries_tolerates_missing_keys():
    assert ccf.stale_entries({}) == []
    assert ccf.stale_entries({"entries": {"a": {}}}) == []


def test_empty_upstream_index_is_a_lookup_failure():
    for url, data in (
        ("u://x.xml", b"<addons />"),
        ("u://x.gz", gzip.compress(b'<?xml version="1.0"?><addons></addons>')),
    ):
        with pytest.raises(sc.FetchError, match="upstream index empty"):
            sc._parse_index(url, data)


def test_pages_runs_the_stale_gate_after_the_deploy_not_before():
    text = (WORKFLOWS / "pages.yml").read_text(encoding="utf-8")
    assert "check_catalog_fresh.py" in text
    job = text[text.index("\n  freshness:") :]
    # After deploy, so the last-good site still goes live; outside verify, so
    # a stale run never fires verify's redeploy-once step.
    assert "needs: deploy" in job.split("steps:")[0]
    build = text[text.index("\n  build:") : text.index("\n  deploy:")]
    assert "check_catalog_fresh.py" not in build
    alert = (WORKFLOWS / "ci_failure_alert.yml").read_text(encoding="utf-8")
    assert 'workflows: ["Build & Deploy Pages"]' in alert
