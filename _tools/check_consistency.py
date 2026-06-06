#!/usr/bin/env python3
"""Version-consistency gate (single-branch model).

Reads every version-bearing location from git refs on `main` and fails loudly
on any mismatch. The SAME function backs three call sites — the pre-push hook,
CI, and the deploy tool's pre-push assertion — so the guard and the gate can
never drift apart.

Reads from git refs (not the working tree) so it validates what will actually
ship.

Single-branch model: the proxy fetches everything from `main`, and its
self-update source is the canonical `repo/repository.tony7bones/addon.xml`
itself (the manifest points the repository.tony7bones entry's asset_prefix at
`.../main/repo/repository.tony7bones/`). There is no longer a separate
`virtual-repo` branch or a `hosted/repository.tony7bones/addon.xml` mirror to
keep in sync. The version-bearing locations are: the main addon.xml, the root
index.html link, the committed root zip, and the git tag.

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
MAIN_ADDON = "repo/repository.tony7bones/addon.xml"
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

    A CI runner or shallow checkout may only have the remote-tracking ref.
    """
    if _git(repo, "rev-parse", "--verify", "--quiet", name).returncode == 0:
        return name
    if _git(repo, "rev-parse", "--verify", "--quiet", f"origin/{name}").returncode == 0:
        return f"origin/{name}"
    return name  # let _show raise a clear error


def gather(repo: str) -> dict:
    """Read the observed version at every location, from git refs."""
    main_ref = _resolve(repo, MAIN)

    main_addon = rl.read_addon_version(_show(repo, main_ref, MAIN_ADDON))
    index_v = rl.version_from_index(_show(repo, main_ref, INDEX))

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
        "root_zip": rl.zip_name(index_v),
        "root_zip_present": zip_present,
        "tag": tag,
        "tag_exists": tag_exists,
    }


def check(repo: str) -> tuple[bool, dict, list[str]]:
    """Return (ok, observed, problems)."""
    info = gather(repo)
    problems: list[str] = []

    # Enforce the single-digit-per-component scheme on the version that will
    # ship. 9.9.9 is the legal ceiling and remains valid; only a component >= 10
    # is rejected. Append a problem instead of raising so the gate reports
    # cleanly rather than crashing.
    if not rl.is_single_digit(info["main_addon"]):
        problems.append(
            f"main addon version {info['main_addon']} is not single-digit "
            "(each of MAJOR.MINOR.PATCH must be 0-9)"
        )

    versions = {info["main_addon"], info["index"]}
    if len(versions) != 1:
        problems.append(
            f"version mismatch: main_addon={info['main_addon']} index={info['index']}"
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
