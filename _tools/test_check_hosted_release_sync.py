"""Tests for check_hosted_release_sync.py — the hosted-mirror release-freshness gate.

No test here talks to the real network: every GitHub API call is routed through
a fake `urllib.request.urlopen` keyed by exact URL, so the suite is fast,
deterministic, and cannot flake on GitHub rate limits or an outage.
"""

from __future__ import annotations

import io
import json
import sys
import urllib.error
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
import check_hosted_release_sync as gate  # noqa: E402


# --------------------------------------------------------------------------- #
# fixtures / helpers
# --------------------------------------------------------------------------- #
def _write_addon_xml(path: Path, addon_id: str, version: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f'<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<addon id="{addon_id}" version="{version}" name="Test" '
        f'provider-name="test">\n</addon>\n'
    )


def _write_repository_json(root: Path, entries: list) -> None:
    p = root / "_tools" / "catalog.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(entries))


def _sandbox(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    return root


class _FakeResp:
    def __init__(self, data: bytes):
        self._data = data

    def read(self):
        return self._data

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _fake_urlopen(routes: dict):
    """routes: {url: (status, json_body_or_None)}.

    status 404 -> HTTPError(404) (gh_get treats this as "not found", returns None).
    status >= 400 (not 404) -> HTTPError with a body (gh_get raises GateError).
    otherwise -> a 200-shaped fake response carrying the JSON body.
    """

    def _fake(req, timeout=None):  # noqa: ARG001 - signature must match urlopen
        url = req.full_url
        if url not in routes:
            raise AssertionError(f"unexpected URL requested: {url}")
        status, payload = routes[url]
        if status == 404:
            raise urllib.error.HTTPError(
                url, 404, "Not Found", None, io.BytesIO(b'{"message":"Not Found"}')
            )
        if status >= 400:
            raise urllib.error.HTTPError(
                url, status, "Error", None, io.BytesIO(b'{"message":"boom"}')
            )
        return _FakeResp(json.dumps(payload).encode("utf-8"))

    return _fake


ESTUARY_ENTRY = {
    "id": "skin.estuary7",
    "username": "tony7bones",
    "repository": "tony7bones.github.io",
    "branch": "main",
    "asset_prefix": "https://raw.githubusercontent.com/{username}/{repository}/{ref}/addons/hosted/{id}/",
    "assets": {
        "zip": "https://github.com/moquette/kodi-estuary7/releases/download/v{version}/{id}-{version}.zip"
    },
}

EZM_ENTRY = {
    "id": "script.ezmaintenanceplusplus",
    "username": "tony7bones",
    "repository": "tony7bones.github.io",
    "branch": "main",
    "asset_prefix": "https://raw.githubusercontent.com/{username}/{repository}/{ref}/addons/hosted/{id}/",
    "assets": {
        "zip": "https://github.com/moquette/kodi-ezmpp/releases/download/v{version}/{id}-{version}.zip"
    },
}

# An entry shaped like the third-party raw.githubusercontent mirrors — must be
# ignored by this gate entirely (out of scope, different trust model).
NON_RELEASE_ENTRY = {
    "id": "repository.umbrella",
    "username": "tony7bones",
    "repository": "tony7bones.github.io",
    "branch": "main",
    "asset_prefix": "https://raw.githubusercontent.com/{username}/{repository}/{ref}/addons/hosted/{id}/",
    "assets": {
        "zip": "https://raw.githubusercontent.com/umbrellaplug/umbrellaplug.github.io/master/repository.umbrella-{version}.zip"
    },
}


# --------------------------------------------------------------------------- #
# hosted_release_entries — parsing / discovery
# --------------------------------------------------------------------------- #
def test_hosted_release_entries_parses_owner_repo_from_url(tmp_path):
    root = _sandbox(tmp_path)
    _write_repository_json(root, [ESTUARY_ENTRY, EZM_ENTRY, NON_RELEASE_ENTRY])
    _write_addon_xml(
        root / "addons/hosted/skin.estuary7/addon.xml", "skin.estuary7", "1.0.38"
    )
    _write_addon_xml(
        root / "addons/hosted/script.ezmaintenanceplusplus/addon.xml",
        "script.ezmaintenanceplusplus",
        "2026.07.14.1",
    )
    # repository.umbrella has no hosted/ dir here at all — also correctly skipped.

    entries = gate.hosted_release_entries(str(root))

    assert [e["id"] for e in entries] == [
        "script.ezmaintenanceplusplus",
        "skin.estuary7",
    ]
    estuary = next(e for e in entries if e["id"] == "skin.estuary7")
    assert estuary["owner"] == "moquette"
    assert estuary["repo"] == "kodi-estuary7"
    assert estuary["asset_template"] == "{id}-{version}.zip"


def test_hosted_release_entries_skips_non_release_template(tmp_path):
    root = _sandbox(tmp_path)
    _write_repository_json(root, [NON_RELEASE_ENTRY])
    _write_addon_xml(
        root / "addons/hosted/repository.umbrella/addon.xml",
        "repository.umbrella",
        "2.2.6",
    )

    assert gate.hosted_release_entries(str(root)) == []


def test_hosted_release_entries_skips_missing_hosted_dir(tmp_path):
    root = _sandbox(tmp_path)
    _write_repository_json(root, [ESTUARY_ENTRY])
    # No addons/hosted/skin.estuary7/addon.xml written at all.

    assert gate.hosted_release_entries(str(root)) == []


# --------------------------------------------------------------------------- #
# gh_get — HTTP status handling
# --------------------------------------------------------------------------- #
def test_gh_get_returns_none_on_404(monkeypatch):
    monkeypatch.setattr(
        gate.urllib.request,
        "urlopen",
        _fake_urlopen(
            {"https://api.github.com/repos/a/b/releases/tags/v1.0.0": (404, None)}
        ),
    )
    assert gate.gh_get("/repos/a/b/releases/tags/v1.0.0", None) is None


def test_gh_get_raises_gate_error_on_server_error(monkeypatch):
    monkeypatch.setattr(
        gate.urllib.request,
        "urlopen",
        _fake_urlopen(
            {"https://api.github.com/repos/a/b/releases/latest": (500, None)}
        ),
    )
    with pytest.raises(gate.GateError):
        gate.gh_get("/repos/a/b/releases/latest", None)


def test_gh_get_includes_authorization_header_when_token_given(monkeypatch):
    captured = {}

    def _fake(req, timeout=None):
        captured["auth"] = req.headers.get("Authorization")
        return _FakeResp(json.dumps({"ok": True}).encode())

    monkeypatch.setattr(gate.urllib.request, "urlopen", _fake)
    gate.gh_get("/repos/a/b", "secret-token")
    assert captured["auth"] == "Bearer secret-token"


def test_gh_get_omits_authorization_header_when_no_token(monkeypatch):
    captured = {}

    def _fake(req, timeout=None):
        captured["auth"] = req.headers.get("Authorization")
        return _FakeResp(json.dumps({"ok": True}).encode())

    monkeypatch.setattr(gate.urllib.request, "urlopen", _fake)
    gate.gh_get("/repos/a/b", None)
    assert captured["auth"] is None


# --------------------------------------------------------------------------- #
# waiver_reason
# --------------------------------------------------------------------------- #
def test_waiver_reason_absent_file(tmp_path):
    assert gate.waiver_reason(str(tmp_path / "nope.json"), "1.0.0") is None


def test_waiver_reason_matches_version(tmp_path):
    p = tmp_path / "release-sync-waiver.json"
    p.write_text(json.dumps({"version": "1.0.0", "waived": "known lag, ticket #42"}))
    assert gate.waiver_reason(str(p), "1.0.0") == "known lag, ticket #42"


def test_waiver_reason_stale_version_does_not_cover(tmp_path):
    """A waiver recorded for an OLDER version must not silently cover a new one."""
    p = tmp_path / "release-sync-waiver.json"
    p.write_text(json.dumps({"version": "1.0.0", "waived": "old reason"}))
    assert gate.waiver_reason(str(p), "1.0.1") is None


def test_waiver_reason_malformed_json_is_ignored(tmp_path):
    p = tmp_path / "release-sync-waiver.json"
    p.write_text("not json{")
    assert gate.waiver_reason(str(p), "1.0.0") is None


def test_waiver_reason_blank_reason_is_ignored(tmp_path):
    p = tmp_path / "release-sync-waiver.json"
    p.write_text(json.dumps({"version": "1.0.0", "waived": "   "}))
    assert gate.waiver_reason(str(p), "1.0.0") is None


# --------------------------------------------------------------------------- #
# check() / check_entry() — end to end against a fake API
# --------------------------------------------------------------------------- #
_UNSET = object()


def _ago(**delta) -> str:
    """An ISO8601 UTC 'Z' timestamp that far in the past, as GitHub would send it."""
    when = datetime.now(timezone.utc) - timedelta(**delta)
    return when.strftime("%Y-%m-%dT%H:%M:%SZ")


def _release_payload(assets):
    return {"tag_name": None, "assets": [{"name": n} for n in assets]}


def _routes_for(
    owner,
    repo,
    tag,
    tag_assets,
    latest_tag,
    latest_assets,
    latest_published_at=_UNSET,
):
    """Fake the two API calls the gate makes for one mirror.

    ``latest_published_at`` defaults to the sentinel ``_UNSET``, which omits the
    field entirely - that is the pre-existing shape every older test relies on,
    and it exercises the fail-open-to-warning path. Pass an ISO8601 string (or
    an explicit None / garbage) to drive the time-aware branch.
    """
    tags_payload = None if tag_assets is None else _release_payload(tag_assets)
    if tags_payload is not None:
        tags_payload["tag_name"] = tag
    latest_payload = None if latest_assets is None else _release_payload(latest_assets)
    if latest_payload is not None:
        latest_payload["tag_name"] = latest_tag
        if latest_published_at is not _UNSET:
            latest_payload["published_at"] = latest_published_at
    return {
        f"https://api.github.com/repos/{owner}/{repo}/releases/tags/{tag}": (
            404 if tag_assets is None else 200,
            tags_payload,
        ),
        f"https://api.github.com/repos/{owner}/{repo}/releases/latest": (
            404 if latest_assets is None else 200,
            latest_payload,
        ),
    }


def _setup_sandbox(tmp_path, version="1.0.38"):
    root = _sandbox(tmp_path)
    _write_repository_json(root, [ESTUARY_ENTRY])
    _write_addon_xml(
        root / "addons/hosted/skin.estuary7/addon.xml", "skin.estuary7", version
    )
    return root


def test_check_happy_path_mirror_matches_latest(tmp_path, monkeypatch):
    root = _setup_sandbox(tmp_path, "1.0.38")
    routes = _routes_for(
        "moquette",
        "kodi-estuary7",
        "v1.0.38",
        tag_assets=["skin.estuary7-1.0.38.zip"],
        latest_tag="v1.0.38",
        latest_assets=["skin.estuary7-1.0.38.zip"],
    )
    monkeypatch.setattr(gate.urllib.request, "urlopen", _fake_urlopen(routes))

    ok, info, problems = gate.check(token=None, repo_root=str(root))

    assert ok is True
    assert problems == []
    assert any("matches the latest release" in line for line in info)


def test_check_fails_when_tag_release_missing(tmp_path, monkeypatch):
    """The mirror's declared version has no matching GitHub release at all — this
    is exactly the silent-404-on-fresh-install bug the gate exists to catch."""
    root = _setup_sandbox(tmp_path, "1.0.99")
    routes = _routes_for(
        "moquette",
        "kodi-estuary7",
        "v1.0.99",
        tag_assets=None,  # no release tagged v1.0.99
        latest_tag="v1.0.38",
        latest_assets=["skin.estuary7-1.0.38.zip"],
    )
    monkeypatch.setattr(gate.urllib.request, "urlopen", _fake_urlopen(routes))

    ok, info, problems = gate.check(token=None, repo_root=str(root))

    assert ok is False
    assert any("no published release tagged 'v1.0.99'" in p for p in problems)
    # The version-vs-latest mismatch is now a non-failing WARNING (info), not a
    # hard problem - the hard failure is the broken pointer above.
    assert any("latest published release" in line for line in info)


def test_check_fails_when_asset_name_missing_from_release(tmp_path, monkeypatch):
    root = _setup_sandbox(tmp_path, "1.0.38")
    routes = _routes_for(
        "moquette",
        "kodi-estuary7",
        "v1.0.38",
        tag_assets=["some-other-file.zip"],  # release exists, wrong asset
        latest_tag="v1.0.38",
        latest_assets=["some-other-file.zip"],
    )
    monkeypatch.setattr(gate.urllib.request, "urlopen", _fake_urlopen(routes))

    ok, info, problems = gate.check(token=None, repo_root=str(root))

    assert ok is False
    assert any("does not carry the expected asset" in p for p in problems)


def test_check_warns_not_fails_when_mirror_lags_latest_release(tmp_path, monkeypatch):
    """A mirror pointing at a REAL, installable release that is merely BEHIND the
    latest is a transient release-race state (a sibling just published; the
    follow-up mirror-bump push lands seconds later). It must WARN, never fail:
    hard-failing it spammed GitHub failure emails on every release AND every
    unrelated push that landed in the window. Only genuinely-broken pointers
    (no release / missing asset) hard-fail."""
    root = _setup_sandbox(tmp_path, "1.0.38")
    routes = _routes_for(
        "moquette",
        "kodi-estuary7",
        "v1.0.38",
        tag_assets=["skin.estuary7-1.0.38.zip"],
        latest_tag="v1.0.39",
        latest_assets=["skin.estuary7-1.0.39.zip"],
    )
    monkeypatch.setattr(gate.urllib.request, "urlopen", _fake_urlopen(routes))

    ok, info, problems = gate.check(token=None, repo_root=str(root))

    assert ok is True
    assert problems == []
    assert any(
        "WARNING" in line and "1.0.39" in line and "behind" in line for line in info
    )


def test_check_passes_when_lag_is_waived_for_exact_version(tmp_path, monkeypatch):
    root = _setup_sandbox(tmp_path, "1.0.38")
    (root / "addons/hosted/skin.estuary7/release-sync-waiver.json").write_text(
        json.dumps({"version": "1.0.38", "waived": "hotfix rollout in progress"})
    )
    routes = _routes_for(
        "moquette",
        "kodi-estuary7",
        "v1.0.38",
        tag_assets=["skin.estuary7-1.0.38.zip"],
        latest_tag="v1.0.39",
        latest_assets=["skin.estuary7-1.0.39.zip"],
    )
    monkeypatch.setattr(gate.urllib.request, "urlopen", _fake_urlopen(routes))

    ok, info, problems = gate.check(token=None, repo_root=str(root))

    assert ok is True
    assert problems == []
    assert any("WAIVED (hotfix rollout in progress)" in line for line in info)


def test_check_stale_waiver_does_not_mark_lag_as_waived(tmp_path, monkeypatch):
    """A waiver committed for a PRIOR mirror version must not label the current
    lag as WAIVED. The lag itself is now a non-failing warning either way, but a
    stale waiver must not silently claim this lag was a deliberate, reviewed
    decision - the warning must read as an un-waived 'behind latest'."""
    root = _setup_sandbox(tmp_path, "1.0.39")
    (root / "addons/hosted/skin.estuary7/release-sync-waiver.json").write_text(
        json.dumps({"version": "1.0.38", "waived": "old, no-longer-relevant reason"})
    )
    routes = _routes_for(
        "moquette",
        "kodi-estuary7",
        "v1.0.39",
        tag_assets=["skin.estuary7-1.0.39.zip"],
        latest_tag="v1.0.40",
        latest_assets=["skin.estuary7-1.0.40.zip"],
    )
    monkeypatch.setattr(gate.urllib.request, "urlopen", _fake_urlopen(routes))

    ok, info, problems = gate.check(token=None, repo_root=str(root))

    assert ok is True
    assert problems == []
    assert not any("WAIVED" in line for line in info)
    assert any("WARNING" in line and "1.0.40" in line for line in info)


def test_check_fails_when_source_repo_has_no_releases_at_all(tmp_path, monkeypatch):
    root = _setup_sandbox(tmp_path, "1.0.38")
    routes = _routes_for(
        "moquette",
        "kodi-estuary7",
        "v1.0.38",
        tag_assets=None,
        latest_tag=None,
        latest_assets=None,
    )
    monkeypatch.setattr(gate.urllib.request, "urlopen", _fake_urlopen(routes))

    ok, info, problems = gate.check(token=None, repo_root=str(root))

    assert ok is False
    assert any("has no published releases at all" in p for p in problems)


def test_check_no_hosted_release_mirrors_is_a_clean_pass(tmp_path):
    root = _sandbox(tmp_path)
    _write_repository_json(root, [NON_RELEASE_ENTRY])

    ok, info, problems = gate.check(token=None, repo_root=str(root))

    assert ok is True
    assert problems == []


# --------------------------------------------------------------------------- #
# main() — CLI wiring
# --------------------------------------------------------------------------- #
def test_main_returns_1_and_prints_to_stderr_on_gate_error(
    tmp_path, monkeypatch, capsys
):
    root = _setup_sandbox(tmp_path, "1.0.38")
    monkeypatch.setattr(gate, "REPO_ROOT", str(root))
    monkeypatch.setattr(
        gate.urllib.request,
        "urlopen",
        _fake_urlopen(
            {
                "https://api.github.com/repos/moquette/kodi-estuary7/releases/tags/v1.0.38": (
                    500,
                    None,
                )
            }
        ),
    )

    rc = gate.main()

    assert rc == 1
    assert "ERROR" in capsys.readouterr().err


def test_main_returns_0_on_happy_path(tmp_path, monkeypatch, capsys):
    root = _setup_sandbox(tmp_path, "1.0.38")
    monkeypatch.setattr(gate, "REPO_ROOT", str(root))
    routes = _routes_for(
        "moquette",
        "kodi-estuary7",
        "v1.0.38",
        tag_assets=["skin.estuary7-1.0.38.zip"],
        latest_tag="v1.0.38",
        latest_assets=["skin.estuary7-1.0.38.zip"],
    )
    monkeypatch.setattr(gate.urllib.request, "urlopen", _fake_urlopen(routes))

    rc = gate.main()

    assert rc == 0
    assert "OK" in capsys.readouterr().out


def test_main_returns_0_and_warns_on_behind_latest(tmp_path, monkeypatch, capsys):
    """The whole point of the gate change: a mirror that is merely BEHIND the
    latest release must exit 0 (no CI failure, no email) while printing a
    WARNING. This pins the exit-code boundary the CI workflows key off."""
    root = _setup_sandbox(tmp_path, "1.0.38")
    monkeypatch.setattr(gate, "REPO_ROOT", str(root))
    routes = _routes_for(
        "moquette",
        "kodi-estuary7",
        "v1.0.38",
        tag_assets=["skin.estuary7-1.0.38.zip"],
        latest_tag="v1.0.39",
        latest_assets=["skin.estuary7-1.0.39.zip"],
    )
    monkeypatch.setattr(gate.urllib.request, "urlopen", _fake_urlopen(routes))

    rc = gate.main()

    out = capsys.readouterr().out
    assert rc == 0
    assert "WARNING" in out
    assert "behind" in out and "1.0.39" in out


# --------------------------------------------------------------------------- #
# time-aware freshness: the grace window
# --------------------------------------------------------------------------- #
def test_grace_seconds_defaults_to_two_hours(monkeypatch):
    monkeypatch.delenv(gate.GRACE_ENV_VAR, raising=False)
    assert gate.FRESHNESS_GRACE_SECONDS == 2 * 60 * 60
    assert gate.grace_seconds() == 2 * 60 * 60


@pytest.mark.parametrize("raw", ["", "   ", "not-a-number", "-1", "1.5"])
def test_grace_seconds_falls_back_on_unusable_env_value(monkeypatch, raw):
    """A typo in the env var must not silently disable or invert the gate."""
    monkeypatch.setenv(gate.GRACE_ENV_VAR, raw)
    assert gate.grace_seconds() == gate.FRESHNESS_GRACE_SECONDS


def test_grace_seconds_honors_valid_env_override(monkeypatch):
    monkeypatch.setenv(gate.GRACE_ENV_VAR, "600")
    assert gate.grace_seconds() == 600


@pytest.mark.parametrize(
    "raw",
    [None, "", "   ", "not-a-timestamp", 12345, "2026-13-45T99:99:99Z"],
)
def test_parse_published_at_returns_none_on_unusable_input(raw):
    assert gate.parse_published_at(raw) is None


def test_parse_published_at_reads_github_z_suffixed_utc():
    parsed = gate.parse_published_at("2026-07-19T21:42:29Z")
    assert parsed == datetime(2026, 7, 19, 21, 42, 29, tzinfo=timezone.utc)
    assert parsed.tzinfo is not None


def test_parse_published_at_normalizes_offset_to_utc():
    """A non-Z offset must be converted, not truncated, or the age is wrong."""
    parsed = gate.parse_published_at("2026-07-19T14:42:29-07:00")
    assert parsed == datetime(2026, 7, 19, 21, 42, 29, tzinfo=timezone.utc)


def test_check_warns_when_behind_a_release_inside_the_grace_window(
    tmp_path, monkeypatch
):
    """CASE 1, the legitimate race: the sibling published 10 minutes ago and the
    mirror-bump push has not landed yet. This is the exact condition that spammed
    failure emails before 83ec255, and it must stay a non-failing WARNING."""
    monkeypatch.delenv(gate.GRACE_ENV_VAR, raising=False)
    root = _setup_sandbox(tmp_path, "1.0.38")
    routes = _routes_for(
        "moquette",
        "kodi-estuary7",
        "v1.0.38",
        tag_assets=["skin.estuary7-1.0.38.zip"],
        latest_tag="v1.0.39",
        latest_assets=["skin.estuary7-1.0.39.zip"],
        latest_published_at=_ago(minutes=10),
    )
    monkeypatch.setattr(gate.urllib.request, "urlopen", _fake_urlopen(routes))

    ok, info, problems = gate.check(token=None, repo_root=str(root))

    assert ok is True
    assert problems == []
    assert any(
        "WARNING" in line and "1.0.39" in line and "grace window" in line
        for line in info
    )


def test_check_fails_when_behind_a_release_older_than_the_grace_window(
    tmp_path, monkeypatch
):
    """CASE 2, the REAL INCIDENT: skin.estuary7 1.0.71 was published
    2026-07-19T21:42:29Z and the hub mirror sat at 1.0.70 for roughly 15 hours
    until a human noticed on 2026-07-20. The warn-only gate stayed green the
    whole time. Nothing self-heals that far past the release, so this must be a
    hard failure that names the exact fix."""
    monkeypatch.delenv(gate.GRACE_ENV_VAR, raising=False)
    root = _setup_sandbox(tmp_path, "1.0.70")
    routes = _routes_for(
        "moquette",
        "kodi-estuary7",
        "v1.0.70",
        tag_assets=["skin.estuary7-1.0.70.zip"],
        latest_tag="v1.0.71",
        latest_assets=["skin.estuary7-1.0.71.zip"],
        latest_published_at="2026-07-19T21:42:29Z",
    )
    monkeypatch.setattr(gate.urllib.request, "urlopen", _fake_urlopen(routes))
    monkeypatch.setattr(
        gate, "_now", lambda: datetime(2026, 7, 20, 12, 45, 0, tzinfo=timezone.utc)
    )

    ok, info, problems = gate.check(token=None, repo_root=str(root))

    assert ok is False
    assert len(problems) == 1
    problem = problems[0]
    assert "1.0.70" in problem and "1.0.71" in problem
    # how long it has been stale, and the exact fix
    assert "15h 2m" in problem
    assert "addons/hosted/skin.estuary7/addon.xml" in problem
    assert "1.0.71" in problem.split("Fix:")[1]


def test_check_ok_when_mirror_matches_latest_even_with_an_ancient_release(
    tmp_path, monkeypatch
):
    """CASE 3: age is irrelevant when the mirror is not behind. A long-stable
    add-on whose latest release is a year old must never trip the freshness gate."""
    monkeypatch.delenv(gate.GRACE_ENV_VAR, raising=False)
    root = _setup_sandbox(tmp_path, "1.0.38")
    routes = _routes_for(
        "moquette",
        "kodi-estuary7",
        "v1.0.38",
        tag_assets=["skin.estuary7-1.0.38.zip"],
        latest_tag="v1.0.38",
        latest_assets=["skin.estuary7-1.0.38.zip"],
        latest_published_at=_ago(days=365),
    )
    monkeypatch.setattr(gate.urllib.request, "urlopen", _fake_urlopen(routes))

    ok, info, problems = gate.check(token=None, repo_root=str(root))

    assert ok is True
    assert problems == []
    assert any("matches the latest release" in line for line in info)


def test_check_broken_pointer_still_hard_fails_when_release_is_brand_new(
    tmp_path, monkeypatch
):
    """CASE 4a: the grace window governs ONLY 'behind latest'. A mirror version
    with no release at all 404s a fresh install right now, so it hard-fails even
    when the latest release is seconds old and everything looks like a race."""
    monkeypatch.delenv(gate.GRACE_ENV_VAR, raising=False)
    root = _setup_sandbox(tmp_path, "1.0.99")
    routes = _routes_for(
        "moquette",
        "kodi-estuary7",
        "v1.0.99",
        tag_assets=None,
        latest_tag="v1.0.38",
        latest_assets=["skin.estuary7-1.0.38.zip"],
        latest_published_at=_ago(seconds=5),
    )
    monkeypatch.setattr(gate.urllib.request, "urlopen", _fake_urlopen(routes))

    ok, info, problems = gate.check(token=None, repo_root=str(root))

    assert ok is False
    assert any("no published release tagged 'v1.0.99'" in p for p in problems)


def test_check_missing_asset_still_hard_fails_regardless_of_release_age(
    tmp_path, monkeypatch
):
    """CASE 4b: same for a release that exists but lacks the expected asset, at
    both extremes of release age."""
    monkeypatch.delenv(gate.GRACE_ENV_VAR, raising=False)
    for label, published in (("new", _ago(seconds=5)), ("old", _ago(days=400))):
        case_dir = tmp_path / label
        case_dir.mkdir()
        root = _setup_sandbox(case_dir, "1.0.38")
        routes = _routes_for(
            "moquette",
            "kodi-estuary7",
            "v1.0.38",
            tag_assets=["some-other-file.zip"],
            latest_tag="v1.0.38",
            latest_assets=["some-other-file.zip"],
            latest_published_at=published,
        )
        monkeypatch.setattr(gate.urllib.request, "urlopen", _fake_urlopen(routes))

        ok, info, problems = gate.check(token=None, repo_root=str(root))

        assert ok is False
        assert any("does not carry the expected asset" in p for p in problems)


def test_check_no_releases_at_all_still_hard_fails(tmp_path, monkeypatch):
    """CASE 4c: no releases means there is no published_at to age at all, and it
    must remain a hard failure rather than falling into the warn path."""
    monkeypatch.delenv(gate.GRACE_ENV_VAR, raising=False)
    root = _setup_sandbox(tmp_path, "1.0.38")
    routes = _routes_for(
        "moquette",
        "kodi-estuary7",
        "v1.0.38",
        tag_assets=None,
        latest_tag=None,
        latest_assets=None,
    )
    monkeypatch.setattr(gate.urllib.request, "urlopen", _fake_urlopen(routes))

    ok, info, problems = gate.check(token=None, repo_root=str(root))

    assert ok is False
    assert any("has no published releases at all" in p for p in problems)


def test_check_waiver_still_waives_a_long_stale_lag(tmp_path, monkeypatch):
    """CASE 5: a version-scoped waiver is a recorded, deliberate decision and
    outranks the freshness window. A 15-hour lag under a matching waiver must
    still pass, or the waiver mechanism is worthless for exactly the deliberate
    long lags it exists to cover."""
    monkeypatch.delenv(gate.GRACE_ENV_VAR, raising=False)
    root = _setup_sandbox(tmp_path, "1.0.70")
    (root / "addons/hosted/skin.estuary7/release-sync-waiver.json").write_text(
        json.dumps({"version": "1.0.70", "waived": "1.0.71 held for hardware soak"})
    )
    routes = _routes_for(
        "moquette",
        "kodi-estuary7",
        "v1.0.70",
        tag_assets=["skin.estuary7-1.0.70.zip"],
        latest_tag="v1.0.71",
        latest_assets=["skin.estuary7-1.0.71.zip"],
        latest_published_at=_ago(hours=15),
    )
    monkeypatch.setattr(gate.urllib.request, "urlopen", _fake_urlopen(routes))

    ok, info, problems = gate.check(token=None, repo_root=str(root))

    assert ok is True
    assert problems == []
    assert any("WAIVED (1.0.71 held for hardware soak)" in line for line in info)


@pytest.mark.parametrize(
    "published",
    [_UNSET, None, "not-a-timestamp", "", 12345],
    ids=["absent", "null", "garbage", "blank", "wrong-type"],
)
def test_check_fails_open_to_warning_when_published_at_is_unusable(
    tmp_path, monkeypatch, published
):
    """CASE 6: a timestamp we cannot read is OUR parsing problem, not evidence of
    a stale mirror. It must degrade to the warning (exit 0), say so in the
    output, and never crash."""
    monkeypatch.delenv(gate.GRACE_ENV_VAR, raising=False)
    root = _setup_sandbox(tmp_path, "1.0.38")
    routes = _routes_for(
        "moquette",
        "kodi-estuary7",
        "v1.0.38",
        tag_assets=["skin.estuary7-1.0.38.zip"],
        latest_tag="v1.0.39",
        latest_assets=["skin.estuary7-1.0.39.zip"],
        latest_published_at=published,
    )
    monkeypatch.setattr(gate.urllib.request, "urlopen", _fake_urlopen(routes))

    ok, info, problems = gate.check(token=None, repo_root=str(root))

    assert ok is True
    assert problems == []
    assert any("WARNING" in line and "missing or unparseable" in line for line in info)


def test_env_override_shortens_window_and_turns_a_warning_into_a_failure(
    tmp_path, monkeypatch
):
    """CASE 7a: the same 10-minute-old release that warns under the 2-hour
    default must hard-fail once the window is tightened to 60 seconds. This
    proves the env var actually drives the threshold."""
    root = _setup_sandbox(tmp_path, "1.0.38")
    routes = _routes_for(
        "moquette",
        "kodi-estuary7",
        "v1.0.38",
        tag_assets=["skin.estuary7-1.0.38.zip"],
        latest_tag="v1.0.39",
        latest_assets=["skin.estuary7-1.0.39.zip"],
        latest_published_at=_ago(minutes=10),
    )
    monkeypatch.setattr(gate.urllib.request, "urlopen", _fake_urlopen(routes))

    monkeypatch.delenv(gate.GRACE_ENV_VAR, raising=False)
    ok_default, _, problems_default = gate.check(token=None, repo_root=str(root))

    monkeypatch.setenv(gate.GRACE_ENV_VAR, "60")
    ok_tight, _, problems_tight = gate.check(token=None, repo_root=str(root))

    assert ok_default is True and problems_default == []
    assert ok_tight is False
    assert any("freshness grace window" in p for p in problems_tight)


def test_env_override_widens_window_and_turns_a_failure_into_a_warning(
    tmp_path, monkeypatch
):
    """CASE 7b: the other direction. The 15-hour incident lag becomes a mere
    warning under a 24-hour window, so an operator can deliberately widen the
    gate without editing code."""
    root = _setup_sandbox(tmp_path, "1.0.70")
    routes = _routes_for(
        "moquette",
        "kodi-estuary7",
        "v1.0.70",
        tag_assets=["skin.estuary7-1.0.70.zip"],
        latest_tag="v1.0.71",
        latest_assets=["skin.estuary7-1.0.71.zip"],
        latest_published_at=_ago(hours=15),
    )
    monkeypatch.setattr(gate.urllib.request, "urlopen", _fake_urlopen(routes))

    monkeypatch.delenv(gate.GRACE_ENV_VAR, raising=False)
    ok_default, _, _ = gate.check(token=None, repo_root=str(root))

    monkeypatch.setenv(gate.GRACE_ENV_VAR, str(24 * 60 * 60))
    ok_wide, info_wide, problems_wide = gate.check(token=None, repo_root=str(root))

    assert ok_default is False
    assert ok_wide is True and problems_wide == []
    assert any("WARNING" in line and "1.0.71" in line for line in info_wide)


def test_main_returns_1_and_prints_fix_on_a_genuinely_stale_mirror(
    tmp_path, monkeypatch, capsys
):
    """The exit-code boundary CI keys off, for the incident case: a mirror stale
    past the grace window must exit 1 and print the FAIL block naming the fix."""
    monkeypatch.delenv(gate.GRACE_ENV_VAR, raising=False)
    root = _setup_sandbox(tmp_path, "1.0.70")
    monkeypatch.setattr(gate, "REPO_ROOT", str(root))
    routes = _routes_for(
        "moquette",
        "kodi-estuary7",
        "v1.0.70",
        tag_assets=["skin.estuary7-1.0.70.zip"],
        latest_tag="v1.0.71",
        latest_assets=["skin.estuary7-1.0.71.zip"],
        latest_published_at=_ago(hours=15),
    )
    monkeypatch.setattr(gate.urllib.request, "urlopen", _fake_urlopen(routes))

    rc = gate.main()

    out = capsys.readouterr().out
    assert rc == 1
    assert "FAIL" in out
    assert "addons/hosted/skin.estuary7/addon.xml" in out


def test_format_age_reads_as_hours_and_minutes():
    assert gate._format_age(15 * 3600 + 2 * 60) == "15h 2m"
    assert gate._format_age(42 * 60) == "42m"
    assert gate._format_age(7) == "7s"
    assert gate._format_age(-5) == "0s"
