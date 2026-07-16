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
        "zip": "https://github.com/moquette/estuary7/releases/download/v{version}/{id}-{version}.zip"
    },
}

EZM_ENTRY = {
    "id": "script.ezmaintenanceplusplus",
    "username": "tony7bones",
    "repository": "tony7bones.github.io",
    "branch": "main",
    "asset_prefix": "https://raw.githubusercontent.com/{username}/{repository}/{ref}/addons/hosted/{id}/",
    "assets": {
        "zip": "https://github.com/moquette/ezmaintenanceplusplus/releases/download/v{version}/{id}-{version}.zip"
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
    assert estuary["repo"] == "estuary7"
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
def _release_payload(assets):
    return {"tag_name": None, "assets": [{"name": n} for n in assets]}


def _routes_for(owner, repo, tag, tag_assets, latest_tag, latest_assets):
    tags_payload = None if tag_assets is None else _release_payload(tag_assets)
    if tags_payload is not None:
        tags_payload["tag_name"] = tag
    latest_payload = None if latest_assets is None else _release_payload(latest_assets)
    if latest_payload is not None:
        latest_payload["tag_name"] = latest_tag
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
        "estuary7",
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
        "estuary7",
        "v1.0.99",
        tag_assets=None,  # no release tagged v1.0.99
        latest_tag="v1.0.38",
        latest_assets=["skin.estuary7-1.0.38.zip"],
    )
    monkeypatch.setattr(gate.urllib.request, "urlopen", _fake_urlopen(routes))

    ok, info, problems = gate.check(token=None, repo_root=str(root))

    assert ok is False
    assert any("no published release tagged 'v1.0.99'" in p for p in problems)
    # also flagged as stale vs latest — both symptoms of the same drift
    assert any("LATEST published release" in p for p in problems)


def test_check_fails_when_asset_name_missing_from_release(tmp_path, monkeypatch):
    root = _setup_sandbox(tmp_path, "1.0.38")
    routes = _routes_for(
        "moquette",
        "estuary7",
        "v1.0.38",
        tag_assets=["some-other-file.zip"],  # release exists, wrong asset
        latest_tag="v1.0.38",
        latest_assets=["some-other-file.zip"],
    )
    monkeypatch.setattr(gate.urllib.request, "urlopen", _fake_urlopen(routes))

    ok, info, problems = gate.check(token=None, repo_root=str(root))

    assert ok is False
    assert any("does not carry the expected asset" in p for p in problems)


def test_check_fails_when_mirror_lags_latest_release_unwaived(tmp_path, monkeypatch):
    root = _setup_sandbox(tmp_path, "1.0.38")
    routes = _routes_for(
        "moquette",
        "estuary7",
        "v1.0.38",
        tag_assets=["skin.estuary7-1.0.38.zip"],
        latest_tag="v1.0.39",
        latest_assets=["skin.estuary7-1.0.39.zip"],
    )
    monkeypatch.setattr(gate.urllib.request, "urlopen", _fake_urlopen(routes))

    ok, info, problems = gate.check(token=None, repo_root=str(root))

    assert ok is False
    assert any(
        "mirror addon.xml is 1.0.38 but the LATEST published release" in p
        and "1.0.39" in p
        for p in problems
    )
    assert any("release-sync-waiver.json" in p for p in problems)


def test_check_passes_when_lag_is_waived_for_exact_version(tmp_path, monkeypatch):
    root = _setup_sandbox(tmp_path, "1.0.38")
    (root / "addons/hosted/skin.estuary7/release-sync-waiver.json").write_text(
        json.dumps({"version": "1.0.38", "waived": "hotfix rollout in progress"})
    )
    routes = _routes_for(
        "moquette",
        "estuary7",
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


def test_check_stale_waiver_does_not_cover_new_version(tmp_path, monkeypatch):
    """A waiver committed for a PRIOR mirror version must not silently keep
    passing once the mirror moves — proves the waiver is not a permanent
    silencer."""
    root = _setup_sandbox(tmp_path, "1.0.39")
    (root / "addons/hosted/skin.estuary7/release-sync-waiver.json").write_text(
        json.dumps({"version": "1.0.38", "waived": "old, no-longer-relevant reason"})
    )
    routes = _routes_for(
        "moquette",
        "estuary7",
        "v1.0.39",
        tag_assets=["skin.estuary7-1.0.39.zip"],
        latest_tag="v1.0.40",
        latest_assets=["skin.estuary7-1.0.40.zip"],
    )
    monkeypatch.setattr(gate.urllib.request, "urlopen", _fake_urlopen(routes))

    ok, info, problems = gate.check(token=None, repo_root=str(root))

    assert ok is False
    assert any("LATEST published release" in p for p in problems)


def test_check_fails_when_source_repo_has_no_releases_at_all(tmp_path, monkeypatch):
    root = _setup_sandbox(tmp_path, "1.0.38")
    routes = _routes_for(
        "moquette",
        "estuary7",
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
                "https://api.github.com/repos/moquette/estuary7/releases/tags/v1.0.38": (
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
        "estuary7",
        "v1.0.38",
        tag_assets=["skin.estuary7-1.0.38.zip"],
        latest_tag="v1.0.38",
        latest_assets=["skin.estuary7-1.0.38.zip"],
    )
    monkeypatch.setattr(gate.urllib.request, "urlopen", _fake_urlopen(routes))

    rc = gate.main()

    assert rc == 0
    assert "OK" in capsys.readouterr().out
