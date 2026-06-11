#!/usr/bin/env python3
"""Versioning gate — every push that changes an add-on must bump its version.

For each add-on directory under addons/, compares local HEAD against origin/main
(ignoring the generated zip + index.html). If the add-on's SOURCE changed but
its addon.xml version did not increase, the push is blocked.

Runs in the pre-push hook. Skips cleanly if there is no origin/main to compare
against (fresh repo).

Usage:
    python3 _tools/check_versions.py        # exit 0 = ok, 1 = a change lacks a bump
"""

from __future__ import annotations

import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import release_detect as rd  # noqa: E402
import release_lib as rl  # noqa: E402

REPO_ROOT = rd.REPO_ROOT
ADDON_BASE = os.path.join(REPO_ROOT, "addons")
# Baseline = the last released state. Defaults to origin/main (the pre-push hook
# case). CI overrides it with CHECK_VERSIONS_BASE_REF=<github.event.before> so a
# main push validates the bump across the pushed RANGE — on main, origin/main
# already equals the pushed HEAD, so without this the gate would compare a commit
# against itself and pass vacuously. An empty/whitespace override is ignored.
BASE_REF = (os.environ.get("CHECK_VERSIONS_BASE_REF") or "").strip() or rd.BASE_REF


def _git(*args):
    return subprocess.run(
        ["git", "-C", REPO_ROOT, *args], capture_output=True, text=True
    )


def check(base_ref: str = BASE_REF):
    """Return (ok, info_lines, problems).

    Uses the SHARED detector (release_detect.changed_addons, gate mode =
    committed `base_ref..HEAD`) so the per-add-on "did the source change?"
    decision is byte-for-byte the same one the release tool makes — the detector
    and the gate can never disagree (MF-1).
    """
    if not rd.base_ref_exists(REPO_ROOT, base_ref):
        return True, [f"no {base_ref} to compare against — skipping"], []

    changed = set(rd.changed_addons(REPO_ROOT, base_ref, worktree=False))
    info, problems = [], []
    for name, path in rd.addon_dirs(REPO_ROOT):
        rel = f"addons/{name}"
        if name not in changed:
            continue  # no source change → no bump required

        base_xml = _git("show", f"{base_ref}:{rel}/addon.xml")
        if base_xml.returncode != 0:
            info.append(f"{name}: new add-on (no {base_ref} baseline)")
            continue

        with open(os.path.join(path, "addon.xml"), encoding="utf-8") as fh:
            cur_ver = rl.read_addon_version(fh.read())
        base_ver = rl.read_addon_version(base_xml.stdout)
        # Range-check the NEW (current) version only. base_ver is read from
        # origin/main and may be the legacy 1.0.14, which parse_version (and
        # is_greater below) still accept; only the version being introduced must
        # obey the single-digit-per-component rule.
        if not rl.is_single_digit(cur_ver):
            problems.append(
                f"{name}: version {cur_ver} is not single-digit "
                "(each component must be 0-9)"
            )
            continue
        if rl.is_greater(cur_ver, base_ver):
            info.append(f"{name}: {base_ver} -> {cur_ver} (bumped)")
        else:
            problems.append(
                f"{name}: source changed but version not bumped ({base_ver} -> {cur_ver})"
            )
    return (not problems), info, problems


def main() -> int:
    ok, info, problems = check()
    print("versioning gate:")
    for line in info:
        print(f"  {line}")
    if ok:
        print("OK — every changed add-on bumped its version")
        return 0
    print("FAIL:")
    for p in problems:
        print(f"  - {p}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
