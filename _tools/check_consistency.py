#!/usr/bin/env python3
"""Version-consistency gate.

Reads every version-bearing location from git refs on both branches and fails
loudly on any mismatch. The SAME function backs three call sites — the pre-push
hook, CI, and the deploy tool's pre-push assertion — so the guard and the gate
can never drift apart.

Reads from git refs (not the working tree) so it validates what will actually
ship.

Usage:
    python3 _tools/check_consistency.py        # exit 0 = consistent, 1 = mismatch
"""

from __future__ import annotations

import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import release_lib as rl  # noqa: E402

MAIN = "main"
VIRTUAL = "virtual-repo"
MAIN_ADDON = "repo/repository.tony7bones/addon.xml"
HOSTED_ADDON = "hosted/repository.tony7bones/addon.xml"
INDEX = "index.html"

REPO_ROOT = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
)


def _git(repo: str, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True)


def _show(repo: str, ref: str, path: str) -> str:
    r = _git(repo, "show", f"{ref}:{path}")
    if r.returncode != 0:
        raise RuntimeError(f"git show {ref}:{path} failed: {r.stderr.strip()}")
    return r.stdout


def _resolve(repo: str, name: str) -> str:
    """Return a usable ref for `name`, falling back to origin/<name>.

    Local checkouts have `main`/`virtual-repo` branches; a CI runner that only
    checked out one branch sees the other as a remote-tracking ref after fetch.
    """
    if _git(repo, "rev-parse", "--verify", "--quiet", name).returncode == 0:
        return name
    if _git(repo, "rev-parse", "--verify", "--quiet", f"origin/{name}").returncode == 0:
        return f"origin/{name}"
    return name  # let _show raise a clear error


def gather(repo: str) -> dict:
    """Read the observed version at every location, from git refs."""
    main_ref = _resolve(repo, MAIN)
    virtual_ref = _resolve(repo, VIRTUAL)

    main_addon = rl.read_addon_version(_show(repo, main_ref, MAIN_ADDON))
    index_v = rl.version_from_index(_show(repo, main_ref, INDEX))
    hosted = rl.read_addon_version(_show(repo, virtual_ref, HOSTED_ADDON))

    tree = _git(repo, "ls-tree", "--name-only", main_ref).stdout.split()
    zip_present = rl.zip_name(index_v) in tree

    tag = rl.tag_name(index_v)
    tag_exists = (
        _git(repo, "rev-parse", "--verify", "--quiet", f"refs/tags/{tag}").returncode
        == 0
    )
    return {
        "main_addon": main_addon,
        "index": index_v,
        "hosted_addon": hosted,
        "root_zip": rl.zip_name(index_v),
        "root_zip_present": zip_present,
        "tag": tag,
        "tag_exists": tag_exists,
    }


def check(repo: str) -> tuple[bool, dict, list[str]]:
    """Return (ok, observed, problems)."""
    info = gather(repo)
    problems: list[str] = []

    versions = {info["main_addon"], info["index"], info["hosted_addon"]}
    if len(versions) != 1:
        problems.append(
            "version mismatch: "
            f"main_addon={info['main_addon']} "
            f"index={info['index']} "
            f"hosted={info['hosted_addon']}"
        )
    if not info["root_zip_present"]:
        problems.append(f"root zip {info['root_zip']} not present in main tree")
    if not info["tag_exists"]:
        problems.append(f"tag {info['tag']} does not exist")
    return (not problems, info, problems)


def main() -> int:
    ok, info, problems = check(REPO_ROOT)
    print("version consistency check:")
    for k, v in info.items():
        print(f"  {k:18}: {v}")
    if ok:
        print("OK — all version-bearing locations agree")
        return 0
    print("FAIL:")
    for p in problems:
        print(f"  - {p}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
