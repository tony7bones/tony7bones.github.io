#!/usr/bin/env python3
"""Shared change detector — the SINGLE source of "which add-ons changed".

The whole safety claim of the release automation rests on the detector and the
gate never disagreeing. So there is exactly ONE function, ``changed_addons``,
imported by BOTH the pre-push gate (``check_versions.py``, post-commit) and the
release tool (``release.py``, pre-commit). The only difference between the two
call sites is an EXPLICIT mode flag — ``worktree`` — so the two comparisons can
never silently diverge (QA must-fix MF-1).

Definition of "changed" (must match ``check_versions.py``'s historical diff
exactly): an add-on is changed iff its ``addons/<id>`` tree differs from the
baseline, EXCLUDING the generated ``*.zip`` and ``index.html``. Source and
``resources/`` files count; the version line inside ``addon.xml`` counts (a
release commit that bumped it still reads as "changed" — that commit IS its
release).

Two modes, one function:
  * ``worktree=False`` (gate, post-commit): diff ``base_ref..HEAD`` — what is
    committed, exactly what ``check_versions.py`` did inline before.
  * ``worktree=True`` (tool, pre-commit): diff ``base_ref`` against the WORKING
    TREE (no ``HEAD``) — what the tool is about to commit, plus any staged or
    unstaged edits.

Both skip cleanly when ``base_ref`` cannot be resolved (a fresh clone or a
shallow CI checkout with no ``origin/main``), mirroring ``check_versions``'s skip
so a missing baseline never fails closed for the wrong reason.
"""

from __future__ import annotations

import os
import subprocess

REPO_ROOT = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
)
ADDON_DIRNAME = "addons"
BASE_REF = "origin/main"


def _git(repo_root: str, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", repo_root, *args], capture_output=True, text=True
    )


def base_ref_exists(repo_root: str, base_ref: str) -> bool:
    """True iff ``base_ref`` resolves in ``repo_root`` (else the caller skips)."""
    return _git(repo_root, "rev-parse", "--verify", "--quiet", base_ref).returncode == 0


def addon_dirs(repo_root: str):
    """Yield ``(id, abspath)`` for every ``addons/<id>/`` holding an addon.xml.

    Sorted for deterministic ordering (the gate prints in this order). This is
    the same iteration ``check_versions.py`` used, so the detector and the gate
    consider exactly the same set of add-ons.
    """
    base = os.path.join(repo_root, ADDON_DIRNAME)
    if not os.path.isdir(base):
        return
    for entry in sorted(os.listdir(base)):
        path = os.path.join(base, entry)
        if os.path.isfile(os.path.join(path, "addon.xml")):
            yield entry, path


def _diff_args(rel: str) -> list[str]:
    """The exclude pathspec for one add-on dir — generated zip + index excluded."""
    return [
        "--",
        rel,
        f":(exclude){rel}/*.zip",
        f":(exclude){rel}/index.html",
    ]


def addon_changed(
    repo_root: str, addon_id: str, base_ref: str, *, worktree: bool
) -> bool:
    """True iff ``addons/<addon_id>`` changed vs ``base_ref`` (excluding zip/index).

    ``worktree`` selects the comparison endpoint:
      * False → ``git diff --quiet base_ref HEAD -- …`` (committed; the gate).
      * True  → ``git diff --quiet base_ref -- …``      (working tree; the tool).

    ``git diff --quiet`` returns 0 when there is NO diff, 1 when there is — so a
    non-zero return code means the add-on changed.
    """
    rel = f"{ADDON_DIRNAME}/{addon_id}"
    endpoints = [base_ref, "HEAD"] if not worktree else [base_ref]
    diff = _git(repo_root, "diff", "--quiet", *endpoints, *_diff_args(rel))
    return diff.returncode != 0


def changed_files(
    repo_root: str, addon_id: str, base_ref: str, *, worktree: bool
) -> list[str]:
    """The list of changed files under ``addons/<addon_id>`` (excluding zip/index).

    Used by the tool's ``--dry-run`` to show WHY an add-on is considered changed
    (QA must-fix MF-4), so the owner can spot a no-op/whitespace trigger before
    burning a version.
    """
    rel = f"{ADDON_DIRNAME}/{addon_id}"
    endpoints = [base_ref, "HEAD"] if not worktree else [base_ref]
    out = _git(repo_root, "diff", "--name-only", *endpoints, *_diff_args(rel)).stdout
    return [ln for ln in out.splitlines() if ln.strip()]


def changed_addons(
    repo_root: str = REPO_ROOT,
    base_ref: str = BASE_REF,
    *,
    worktree: bool = False,
) -> list[str]:
    """Return the sorted ids of first-party add-ons changed vs ``base_ref``.

    The ONE detector behind both the gate (``worktree=False``) and the tool
    (``worktree=True``). When ``base_ref`` does not resolve, returns ``[]`` (the
    callers treat a missing baseline as "nothing to gate / nothing to release").

    A divergence between tool and gate is structurally impossible because both
    route through this function; the only difference is the explicit ``worktree``
    flag, and the e2e suite asserts the two modes return the SAME set on a
    committed tree (MF-1 regression guard).
    """
    if not base_ref_exists(repo_root, base_ref):
        return []
    return [
        addon_id
        for addon_id, _ in addon_dirs(repo_root)
        if addon_changed(repo_root, addon_id, base_ref, worktree=worktree)
    ]
