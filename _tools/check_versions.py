#!/usr/bin/env python3
"""Versioning gate — every push that changes an add-on must bump its version.

For each add-on directory under repo/, compares local HEAD against origin/main
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
import release_lib as rl  # noqa: E402

REPO_ROOT = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
)
ADDON_BASE = os.path.join(REPO_ROOT, "repo")
BASE_REF = "origin/main"


def _git(*args):
    return subprocess.run(
        ["git", "-C", REPO_ROOT, *args], capture_output=True, text=True
    )


def _addon_dirs():
    if not os.path.isdir(ADDON_BASE):
        return
    for entry in sorted(os.listdir(ADDON_BASE)):
        path = os.path.join(ADDON_BASE, entry)
        if os.path.isfile(os.path.join(path, "addon.xml")):
            yield entry, path


def check(base_ref: str = BASE_REF):
    """Return (ok, info_lines, problems)."""
    if _git("rev-parse", "--verify", "--quiet", base_ref).returncode != 0:
        return True, [f"no {base_ref} to compare against — skipping"], []

    info, problems = [], []
    for name, path in _addon_dirs():
        rel = f"repo/{name}"
        # Did any source file change (excluding the generated zip + index.html)?
        diff = _git(
            "diff",
            "--quiet",
            base_ref,
            "HEAD",
            "--",
            rel,
            f":(exclude){rel}/*.zip",
            f":(exclude){rel}/index.html",
        )
        if diff.returncode == 0:
            continue  # no source change → no bump required

        base_xml = _git("show", f"{base_ref}:{rel}/addon.xml")
        if base_xml.returncode != 0:
            info.append(f"{name}: new add-on (no {base_ref} baseline)")
            continue

        with open(os.path.join(path, "addon.xml"), encoding="utf-8") as fh:
            cur_ver = rl.read_addon_version(fh.read())
        base_ver = rl.read_addon_version(base_xml.stdout)
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
