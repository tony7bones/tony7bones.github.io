#!/usr/bin/env python3
"""Hosted-mirror release-freshness gate.

THE PROBLEM this closes: a fleet box picks what to install by reading the
proxy's ``addons/hosted/<id>/addon.xml`` version. Two mirrors under
``addons/hosted/`` point their GitHub-Releases asset template at a SOURCE
repo we also own (``skin.estuary7`` -> ``moquette/estuary7``,
``script.ezmaintenanceplusplus`` -> ``moquette/ezmaintenanceplusplus``), and
nothing verified that the mirrored version corresponds to a real, LATEST
published release on that source repo. The sync is hand-done; a silent
mismatch 404s a fresh install (no release for that version at all) or serves
a stale build forever (a real but out-of-date release), with no error
anywhere. This is the drift the whole EZM++ migration was meant to kill.

WHAT IT CHECKS, per hosted mirror whose ``repository.json`` asset template
matches ``github.com/<owner>/<repo>/releases/download/v{version}/...`` (owner
and repo are parsed out of the URL, never hardcoded here — a future
third add-on using the same template shape is covered automatically):

  1. The mirror's ``addon.xml`` version has a real release on the source
     repo, tagged ``v<version>``, carrying the exact asset filename the
     template would build.
  2. That version is the source repo's LATEST published release — the design
     intent is "the proxy mirrors the latest release", not just "a" release.
     This one is TIME-AWARE. A mirror that is behind a release published
     within ``FRESHNESS_GRACE_SECONDS`` is the normal release-to-mirror-bump
     race and only WARNS (exit 0). A mirror behind a release OLDER than that
     window is a forgotten bump and hard-fails (exit 1). Override the window
     with ``HOSTED_FRESHNESS_GRACE_SECONDS``.

A broken pointer (check 1: no release for the declared version, or the release
is missing the expected asset, or the source repo has no releases at all) always
hard-fails, regardless of any timing.

A genuine, deliberate lag may ship by committing
``addons/hosted/<id>/release-sync-waiver.json`` with
``{"version": "<mirror version>", "waived": "<reason>"}``. This is scoped to
the EXACT version under review (mirrors the EZ Maintenance++ hardware gate's
fingerprint-scoped waiver): the moment the mirror version changes again, the
old waiver stops covering it and the gate re-fails until a fresh, reviewable
decision is committed. A lag is a recorded, deliberate act — never silent.

Talks to the real GitHub REST API. Uses ``GH_TOKEN``/``GITHUB_TOKEN`` from the
environment when present (CI's built-in token — authenticated, no rate-limit
worry); falls back to an unauthenticated request otherwise, which still works
for these PUBLIC repos (just rate-limited), so this also runs on a developer
machine with no token configured.

Usage:
    python3 _tools/check_hosted_release_sync.py   # exit 0 = ok, 1 = mismatch
"""

from __future__ import annotations

import datetime as dt
import json
import os
import re
import sys
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import release_lib as rl  # noqa: E402

REPO_ROOT = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
)
API_BASE = "https://api.github.com"
WAIVER_NAME = "release-sync-waiver.json"

# How long a mirror is allowed to sit behind its source repo's LATEST release
# before "behind" stops being the normal release-to-mirror-bump race and becomes
# a real, human-forgot-to-bump staleness PROBLEM.
#
# Calibration: an observed healthy bump (skin.estuary7 1.0.70) followed its
# release by about 13 minutes. The incident this window exists to catch was
# skin.estuary7 1.0.71, released 2026-07-19T21:42:29Z, with the hub mirror still
# on 1.0.70 roughly 15 hours later. 2 hours sits an order of magnitude above the
# healthy bump latency and an order of magnitude below the incident, so it warns
# through every legitimate race and fails on a genuinely forgotten bump.
#
# Override without editing code by setting HOSTED_FRESHNESS_GRACE_SECONDS (a
# non-negative integer count of seconds). A missing, blank, non-integer or
# negative value falls back to this default.
FRESHNESS_GRACE_SECONDS = 2 * 60 * 60
GRACE_ENV_VAR = "HOSTED_FRESHNESS_GRACE_SECONDS"

# Matches a GitHub Releases asset template pointing at a THIRD-PARTY source
# repo — owner/repo are literal in the URL, distinct from the entry's OWN
# username/repository fields (which the proxy uses for its raw.githubusercontent
# asset_prefix, i.e. fetching addon.xml/icon.png off ITS OWN tony7bones.github.io
# tree, not the source repo's release). Captures owner, repo, and whatever
# follows the tag segment as the asset-name template (still holding {id}/
# {version} placeholders, resolved per-mirror below).
_RELEASE_ASSET_RE = re.compile(
    r"^https://github\.com/(?P<owner>[^/{}]+)/(?P<repo>[^/{}]+)"
    r"/releases/download/v\{version\}/(?P<asset_template>.+)$"
)


class GateError(Exception):
    """A named, loud failure talking to the GitHub API — never silent."""


def hosted_release_entries(repo_root: str = REPO_ROOT) -> list[dict]:
    """Every ``addons/hosted/<id>`` mirror backed by a GitHub Releases URL.

    Skips entries with no matching hosted directory (nothing to check) and
    entries whose ``assets.zip`` template isn't the
    ``releases/download/v{version}/...`` shape (a different mirror kind
    entirely — e.g. the raw.githubusercontent third-party mirrors — is out of
    scope for this gate). Returns dicts sorted by id for deterministic output.
    """
    hosted_dir = os.path.join(repo_root, "addons", "hosted")
    repo_json_path = os.path.join(repo_root, "_tools", "catalog.json")
    with open(repo_json_path, encoding="utf-8") as fh:
        data = json.load(fh)

    out = []
    for entry in data:
        addon_id = entry.get("id")
        zip_tmpl = (entry.get("assets") or {}).get("zip", "")
        m = _RELEASE_ASSET_RE.match(zip_tmpl)
        if not m or not addon_id:
            continue
        addon_dir = os.path.join(hosted_dir, addon_id)
        addon_xml = os.path.join(addon_dir, "addon.xml")
        if not os.path.isfile(addon_xml):
            continue
        out.append(
            {
                "id": addon_id,
                "owner": m.group("owner"),
                "repo": m.group("repo"),
                "asset_template": m.group("asset_template"),
                "addon_xml": addon_xml,
                "waiver_path": os.path.join(addon_dir, WAIVER_NAME),
            }
        )
    return sorted(out, key=lambda e: e["id"])


def gh_token() -> str | None:
    """The token to authenticate with, if any — GH_TOKEN wins, then GITHUB_TOKEN.

    Both unset is a normal, supported state (a developer machine): callers
    fall back to an unauthenticated request.
    """
    return os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN") or None


def gh_get(path: str, token: str | None) -> dict | None:
    """GET ``api.github.com<path>``. Returns the parsed JSON body, or None on 404.

    Any other HTTP error, or a network failure, raises GateError — a gate that
    silently passed on an unreachable API would be worse than no gate at all.
    """
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        # GitHub's API rejects requests with no User-Agent (403).
        "User-Agent": "tony7bones-hosted-release-sync-gate",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(API_BASE + path, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:  # noqa: S310 (https only)
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        body = e.read().decode("utf-8", "replace")[:300]
        raise GateError(f"GitHub API {path} failed: HTTP {e.code} {body}") from e
    except urllib.error.URLError as e:
        raise GateError(f"GitHub API {path} unreachable: {e}") from e


def get_release_by_tag(
    owner: str, repo: str, tag: str, token: str | None
) -> dict | None:
    return gh_get(f"/repos/{owner}/{repo}/releases/tags/{tag}", token)


def get_latest_release(owner: str, repo: str, token: str | None) -> dict | None:
    return gh_get(f"/repos/{owner}/{repo}/releases/latest", token)


def _load_waiver(path: str) -> dict | None:
    if not os.path.isfile(path):
        return None
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def waiver_reason(path: str, version: str) -> str | None:
    """The recorded waiver reason iff a waiver exists AND is scoped to `version`.

    Deliberately version-scoped, like the hardware gate's fingerprint scope: a
    waiver committed for 1.0.37 does not silently keep covering 1.0.38. Every
    new lag is its own committed, reviewable decision.
    """
    waiver = _load_waiver(path)
    if not waiver or "waived" not in waiver:
        return None
    if waiver.get("version") != version:
        return None
    reason = waiver["waived"]
    return reason if isinstance(reason, str) and reason.strip() else None


def grace_seconds() -> int:
    """The freshness grace window in seconds, env-overridable.

    Reads ``HOSTED_FRESHNESS_GRACE_SECONDS`` so CI or a human can tune the
    window without editing code. Anything unset, blank, non-integer or negative
    falls back to ``FRESHNESS_GRACE_SECONDS``: a typo in an env var must not
    silently disable or invert the gate.
    """
    raw = os.environ.get(GRACE_ENV_VAR)
    if raw is None or not raw.strip():
        return FRESHNESS_GRACE_SECONDS
    try:
        value = int(raw.strip())
    except ValueError:
        return FRESHNESS_GRACE_SECONDS
    return value if value >= 0 else FRESHNESS_GRACE_SECONDS


def parse_published_at(value: object) -> dt.datetime | None:
    """GitHub's ``published_at`` (UTC ISO8601, e.g. ``2026-07-19T21:42:29Z``).

    Returns a timezone-AWARE UTC datetime, or None if the field is absent,
    not a string, or unparseable. Callers must treat None as "cannot judge
    age" and fail open to the warning, never hard-fail: a timestamp parsing
    problem is our bug, not evidence of a stale mirror.
    """
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    # fromisoformat only learned the trailing 'Z' in 3.11; normalize for 3.9/3.10.
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    try:
        parsed = dt.datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        # GitHub always sends an offset. A naive value means a shape we did not
        # expect, so read it as UTC rather than as local time (which would skew
        # the age by the runner's offset and could fail a fresh release).
        return parsed.replace(tzinfo=dt.timezone.utc)
    return parsed.astimezone(dt.timezone.utc)


def _now() -> dt.datetime:
    """Timezone-aware UTC now.

    A named seam, not a style flourish: tests pin an exact instant here so the
    real-incident fixture can use the literal 1.0.71 timestamps instead of
    relative offsets. Never compare a UTC ``published_at`` against a naive
    local ``datetime.now()`` - that skews the age by the runner's offset.
    """
    return dt.datetime.now(dt.timezone.utc)


def _format_age(seconds: float) -> str:
    """A short human age like '15h 3m' or '42m', for the failure message."""
    total = int(max(seconds, 0))
    hours, rem = divmod(total, 3600)
    minutes = rem // 60
    if hours:
        return f"{hours}h {minutes}m"
    if minutes:
        return f"{minutes}m"
    return f"{total}s"


def check_entry(entry: dict, token: str | None) -> tuple[bool, list[str], list[str]]:
    """Return (ok, info_lines, problems) for one hosted mirror."""
    addon_id, owner, repo = entry["id"], entry["owner"], entry["repo"]
    with open(entry["addon_xml"], encoding="utf-8") as fh:
        version = rl.read_addon_version(fh.read())

    info: list[str] = []
    problems: list[str] = []

    expected_asset = entry["asset_template"].format(id=addon_id, version=version)
    tag = f"v{version}"

    release = get_release_by_tag(owner, repo, tag, token)
    if release is None:
        problems.append(
            f"{addon_id}: addon.xml declares version {version}, but {owner}/{repo} "
            f"has no published release tagged {tag!r} — a fresh install or update "
            f"from this mirror would 404"
        )
    else:
        asset_names = {a.get("name") for a in release.get("assets", [])}
        if expected_asset not in asset_names:
            problems.append(
                f"{addon_id}: release {tag} exists on {owner}/{repo} but does not "
                f"carry the expected asset {expected_asset!r} (has: "
                f"{sorted(n for n in asset_names if n)})"
            )
        else:
            info.append(
                f"{addon_id}: {tag} exists on {owner}/{repo} with asset {expected_asset}"
            )

    latest = get_latest_release(owner, repo, token)
    if latest is None:
        problems.append(f"{addon_id}: {owner}/{repo} has no published releases at all")
    else:
        latest_tag = latest.get("tag_name") or ""
        latest_version = latest_tag[1:] if latest_tag.startswith("v") else latest_tag
        if latest_version != version:
            reason = waiver_reason(entry["waiver_path"], version)
            if reason:
                info.append(
                    f"{addon_id}: mirror is {version}, latest release is "
                    f"{latest_version} — WAIVED ({reason})"
                )
            else:
                # The mirror still points at a REAL, installable release (it passed
                # the tag+asset checks above) - it is merely not the LATEST. Whether
                # that is benign or a defect depends entirely on HOW LONG it has been
                # true, so the verdict is time-aware:
                #
                #   young latest (inside the grace window) -> WARNING, exit 0. This is
                #     the normal release-to-mirror-bump race: the sibling repo
                #     publishes v_new and the follow-up mirror-bump push lands minutes
                #     later. Hard-failing it raced EVERY release (and every unrelated
                #     push landing in the window) and spammed failure emails for a
                #     condition that self-heals.
                #
                #   old latest (past the grace window) -> PROBLEM, exit 1. This is the
                #     defect the warn-only gate stayed green through: skin.estuary7
                #     1.0.71 shipped and the hub mirror sat on 1.0.70 for ~15 hours
                #     until a human noticed. Nothing self-heals after the grace
                #     window; somebody forgot the bump.
                #
                # A missing or unparseable published_at FAILS OPEN to the warning: a
                # timestamp we cannot read is our parsing problem, not proof of a
                # stale mirror, and must never turn CI red on its own.
                grace = grace_seconds()
                published = parse_published_at(latest.get("published_at"))
                age = (
                    None if published is None else (_now() - published).total_seconds()
                )
                fix = f"bump addons/hosted/{addon_id}/addon.xml to {latest_version}"
                head = (
                    f"{addon_id}: mirror addon.xml is {version} but the "
                    f"latest published release on {owner}/{repo} is {latest_version}."
                )
                if age is not None and age > grace:
                    problems.append(
                        f"{head} The mirror has been behind for {_format_age(age)}, "
                        f"past the {_format_age(grace)} freshness grace window, so "
                        f"this is a forgotten mirror bump, not a release race. "
                        f"Fix: {fix}."
                    )
                elif age is None:
                    info.append(
                        f"WARNING: {head} The mirror is behind, and the release "
                        f"publish timestamp is missing or unparseable, so its age "
                        f"could not be judged against the {_format_age(grace)} "
                        f"freshness grace window. Treating as the transient release "
                        f"race; {fix}."
                    )
                else:
                    info.append(
                        f"WARNING: {head} The mirror is behind, but that release is "
                        f"only {_format_age(age)} old, inside the "
                        f"{_format_age(grace)} freshness grace window (transient "
                        f"during a release); {fix}."
                    )
        else:
            info.append(
                f"{addon_id}: mirror version {version} matches the latest release"
            )

    return (not problems), info, problems


def check(
    token: str | None = None, repo_root: str | None = None
) -> tuple[bool, list[str], list[str]]:
    """Return (ok, info_lines, problems) across every hosted GitHub-Releases mirror.

    ``repo_root`` resolves against the CURRENT module-level ``REPO_ROOT`` at call
    time (not a value captured at import time) so tests can monkeypatch
    ``REPO_ROOT`` and have a bare ``main()`` call pick it up.
    """
    if token is None:
        token = gh_token()
    entries = hosted_release_entries(repo_root or REPO_ROOT)
    if not entries:
        return True, ["no hosted mirror uses a releases/download asset template"], []

    info: list[str] = []
    problems: list[str] = []
    for entry in entries:
        _, e_info, e_problems = check_entry(entry, token)
        info.extend(e_info)
        problems.extend(e_problems)
    return (not problems), info, problems


def main() -> int:
    try:
        ok, info, problems = check()
    except GateError as e:
        print(f"hosted-mirror release-freshness gate: ERROR — {e}", file=sys.stderr)
        return 1

    print("hosted-mirror release-freshness gate:")
    for line in info:
        print(f"  {line}")
    if ok:
        print("OK — every hosted GitHub-Releases mirror matches a real, latest release")
        return 0
    print("FAIL:")
    for p in problems:
        print(f"  - {p}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
