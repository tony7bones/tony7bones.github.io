#!/usr/bin/env python3
"""Version-consistency gate (single-branch model).

Reads every version-bearing location from git refs on `main` and fails loudly
on any mismatch. The SAME function backs three call sites — the pre-push hook,
CI, and the deploy tool's pre-push assertion — so the guard and the gate can
never drift apart.

Reads from git refs (not the working tree) so it validates what will actually
ship.

Single-branch model: the proxy fetches everything from `main`, and its
self-update source is the canonical `addons/repository.tony7bones/addon.xml`
itself (the manifest points the repository.tony7bones entry's asset_prefix at
`.../main/addons/repository.tony7bones/`). There is no longer a separate
`virtual-repo` branch or a `hosted/repository.tony7bones/addon.xml` mirror to
keep in sync. The version-bearing locations are: the main addon.xml, the
committed root zip filename, and the git tag. (The root index.html is the
bare-URL canvas listing and no longer carries a zip link to read.)

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
MAIN_ADDON = "addons/repository.tony7bones/addon.xml"

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
    """Read the observed version at every location, from git refs.

    The shipped version is read from the root installer zip's FILENAME (the zip is
    served at the repo root for the proxy self-update). The root index.html is the
    bare-URL canvas listing and no longer carries a zip link, so it is not read.
    """
    main_ref = _resolve(repo, MAIN)

    main_addon = rl.read_addon_version(_show(repo, main_ref, MAIN_ADDON))

    tree = _git(repo, "ls-tree", "--name-only", main_ref).stdout.split()
    root_zips = sorted(n for n in tree if rl.is_root_zip_name(n))
    zip_v = rl.version_from_zip_name(root_zips[0]) if len(root_zips) == 1 else None

    tag = rl.tag_name(zip_v) if zip_v else None
    tag_exists = bool(tag) and (
        _git(repo, "rev-parse", "--verify", "--quiet", f"refs/tags/{tag}").returncode
        == 0
    )
    return {
        "main_addon": main_addon,
        "root_zip_version": zip_v,
        "root_zips": root_zips,
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

    if len(info["root_zips"]) != 1:
        problems.append(
            "expected exactly one root installer zip (repository.tony7bones-*.zip), "
            f"found {info['root_zips']}"
        )
    elif info["main_addon"] != info["root_zip_version"]:
        problems.append(
            f"version mismatch: main_addon={info['main_addon']} "
            f"root_zip={info['root_zip_version']}"
        )
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
