#!/usr/bin/env python3
"""One-command release for the Tony.7.Bones Kodi repository.

Bumps the version, builds deterministically, syncs ALL FIVE version-bearing
locations from a single version string, commits main + virtual-repo, tags, and
atomic-pushes the three refs together. CI stays validate-only — this script is
the only thing that commits a release.

Gates enforced before anything is pushed:
  * working tree clean, on main, not behind origin
  * next version strictly greater than current (every deploy MUST bump)
  * tag / root zip for the new version must not already exist
  * generator output is byte-reproducible (re-run produces zero diff)
  * root zip is byte-identical to the generated zip
  * cross-branch version consistency (check_consistency) passes

Any failure before the push rolls main, the tag, and virtual-repo back to where
they started, and the working tree is left on main.

Usage:
    python3 _tools/deploy.py --news "What changed"          # patch bump
    python3 _tools/deploy.py --minor --news "..."
    python3 _tools/deploy.py --major --news "..."
    python3 _tools/deploy.py --version 1.4.0 --news "..."   # explicit
    python3 _tools/deploy.py --news "..." --dry-run         # show plan only
    python3 _tools/deploy.py --news "..." --no-push         # local only
    python3 _tools/deploy.py --news "..." --no-verify       # skip live polling
    python3 _tools/deploy.py check                          # consistency gate only
"""

from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import check_consistency as cc  # noqa: E402
import release_lib as rl  # noqa: E402

REPO = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
MAIN_ADDON = os.path.join(REPO, "repo", "repository.tony7bones", "addon.xml")
GENERATED_ZIP_DIR = os.path.join(REPO, "repo", "repository.tony7bones")
ROOT_INDEX = os.path.join(REPO, "index.html")
HOSTED_ADDON_REL = os.path.join("hosted", "repository.tony7bones", "addon.xml")
GENERATOR = os.path.join(REPO, "_tools", "generate_repo.py")
BASE_URL = "https://tony7bones.github.io"


# --------------------------------------------------------------------------- #
# Small helpers
# --------------------------------------------------------------------------- #
def git(*args: str, check: bool = True, repo: str = REPO, env=None) -> str:
    r = subprocess.run(
        ["git", "-C", repo, *args], capture_output=True, text=True, env=env
    )
    if check and r.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed:\n{r.stderr.strip()}")
    return r.stdout.strip()


def sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def read(path: str) -> str:
    with open(path, encoding="utf-8") as f:
        return f.read()


def write(path: str, text: str) -> None:
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def run_generator() -> None:
    subprocess.run(
        [sys.executable, GENERATOR],
        cwd=REPO,
        check=True,
        capture_output=True,
        text=True,
    )


# --------------------------------------------------------------------------- #
# Planning
# --------------------------------------------------------------------------- #
def current_version() -> str:
    return rl.read_addon_version(read(MAIN_ADDON))


def compute_next(args, cur: str) -> str:
    if args.version:
        rl.parse_version(args.version)
        return args.version
    level = "major" if args.major else "minor" if args.minor else "patch"
    return rl.bump(cur, level)


def preflight(nxt: str, cur: str) -> list[str]:
    problems: list[str] = []
    if git("rev-parse", "--abbrev-ref", "HEAD") != "main":
        problems.append("not on the main branch")
    if git("status", "--porcelain"):
        problems.append("working tree is not clean")
    problems.extend(_behind_origin())
    if not rl.is_greater(nxt, cur):
        problems.append(
            f"next version {nxt} is not greater than current {cur} "
            "(every deploy MUST bump the version)"
        )
    if git("tag", "-l", rl.tag_name(nxt)):
        problems.append(f"tag {rl.tag_name(nxt)} already exists")
    if os.path.exists(os.path.join(REPO, rl.zip_name(nxt))):
        problems.append(f"root zip {rl.zip_name(nxt)} already exists")
    return problems


def _behind_origin() -> list[str]:
    """Refuse to deploy when a local branch is behind its origin counterpart.

    A non-fast-forward would otherwise only surface at the atomic push — after
    the whole local transaction has run. Catch it up front. Fetch failures
    (offline) are a warning, not a hard block, so a release is still possible
    without network if the caller knows refs are current.
    """
    problems: list[str] = []
    if "origin" not in git("remote").split():
        return problems
    fetched = subprocess.run(
        ["git", "-C", REPO, "fetch", "origin", "--quiet"],
        capture_output=True,
        text=True,
    )
    if fetched.returncode != 0:
        print(
            f"warning: could not fetch origin ({fetched.stderr.strip()}); "
            "skipping behind-origin check",
            file=sys.stderr,
        )
        return problems
    for branch in ("main", "virtual-repo"):
        if not git(
            "rev-parse",
            "--verify",
            "--quiet",
            f"refs/remotes/origin/{branch}",
            check=False,
        ):
            continue
        behind = git("rev-list", "--count", f"{branch}..origin/{branch}", check=False)
        if behind not in ("", "0"):
            problems.append(
                f"{branch} is behind origin/{branch} by {behind} commit(s) — pull first"
            )
    return problems


def plan_text(nxt: str, cur: str, news: str) -> str:
    plan = rl.DeployPlan(nxt)
    return "\n".join(
        [
            f"  current version  : {cur}",
            f"  next version     : {nxt}   (tag {plan.tag})",
            f"  news             : {news}",
            f"  main addon.xml   : version -> {nxt}",
            f"  root zip         : {plan.root_zip}",
            f"  index.html link  : {plan.root_zip}",
            f"  hosted addon.xml : version -> {nxt}  (virtual-repo)",
            f"  push (--atomic)  : main, virtual-repo, {plan.tag}",
        ]
    )


# --------------------------------------------------------------------------- #
# Deploy
# --------------------------------------------------------------------------- #
def deploy(args) -> int:
    cur = current_version()
    nxt = compute_next(args, cur)

    problems = preflight(nxt, cur)
    if problems:
        print("PRE-FLIGHT FAILED:", file=sys.stderr)
        for p in problems:
            print(f"  - {p}", file=sys.stderr)
        return 1

    print("Deploy plan:")
    print(plan_text(nxt, cur, args.news))
    if args.dry_run:
        print("\n--dry-run: nothing was changed.")
        return 0

    # Clear any worktree left registered by a previously crashed deploy so the
    # `worktree add` below can re-check-out virtual-repo.
    git("worktree", "prune", check=False)

    plan = rl.DeployPlan(nxt)
    tag = plan.tag
    main_head = git("rev-parse", "HEAD")
    vr_head = git("rev-parse", "virtual-repo")
    worktree: str | None = None

    try:
        # 1. main: bump addon.xml (version + news)
        xml = read(MAIN_ADDON)
        xml = rl.set_addon_version(xml, nxt)
        xml = rl.set_addon_news(xml, f"v{nxt}: {args.news}")
        write(MAIN_ADDON, xml)

        # 2. build deterministically, sync root zip, assert byte-identity
        run_generator()
        gen_zip = os.path.join(GENERATED_ZIP_DIR, plan.root_zip)
        root_zip = os.path.join(REPO, plan.root_zip)
        shutil.copyfile(gen_zip, root_zip)
        if sha256(gen_zip) != sha256(root_zip):
            raise RuntimeError("root zip is not byte-identical to the generated zip")

        # 3. root index link -> new zip
        write(ROOT_INDEX, rl.rewrite_index_link(read(ROOT_INDEX), nxt))

        # 4. commit main
        git("add", "-A")
        git("commit", "-m", f"Release {tag}\n\n{args.news}")

        # 5. determinism gate: regenerate; the tree must stay clean
        run_generator()
        if git("status", "--porcelain"):
            raise RuntimeError(
                "generator is non-deterministic: regeneration produced a diff"
            )

        # 6. virtual-repo via a worktree (main never leaves main)
        worktree = tempfile.mkdtemp(prefix="t7b-vr-")
        git("worktree", "add", worktree, "virtual-repo")
        hosted = os.path.join(worktree, HOSTED_ADDON_REL)
        hx = read(hosted)
        hx = rl.set_addon_version(hx, nxt)
        hx = rl.set_addon_news(hx, f"v{nxt}: {args.news}")
        write(hosted, hx)

        archived = os.path.join(worktree, plan.root_zip)
        archived_bytes = subprocess.run(
            ["git", "-C", REPO, "show", f"main:{plan.root_zip}"],
            check=True,
            capture_output=True,
        ).stdout
        with open(archived, "wb") as f:
            f.write(archived_bytes)
        if sha256(archived) != sha256(root_zip):
            raise RuntimeError("archived virtual-repo zip is not byte-identical")

        env = dict(os.environ, PRE_COMMIT_ALLOW_NO_CONFIG="1")
        git("add", "-A", repo=worktree)
        git(
            "commit",
            "-m",
            f"Release {tag} (hosted self-update source)",
            repo=worktree,
            env=env,
        )

        # 7. tag the main release commit
        git("tag", "-a", tag, "-m", f"Release {tag}")

        # 8. cross-branch consistency gate BEFORE pushing
        ok, info, cproblems = cc.check(REPO)
        if not ok:
            raise RuntimeError("consistency gate failed: " + "; ".join(cproblems))

        # 9. publish all-or-nothing
        if args.no_push:
            print(f"\n--no-push: committed + tagged {tag} locally. To publish:")
            print(f"  git push --atomic origin main virtual-repo {tag}")
        else:
            git(
                "push", "--atomic", "origin", "main", "virtual-repo", f"refs/tags/{tag}"
            )
            print(f"\nPushed main + virtual-repo + {tag}.")

    except Exception as exc:  # noqa: BLE001 — we re-raise after rollback
        print(
            f"\nDEPLOY FAILED: {exc}\nRolling back to pre-deploy state...",
            file=sys.stderr,
        )
        # Remove the worktree first so virtual-repo is no longer checked out,
        # then restore all three refs to their pre-deploy state.
        if worktree:
            git("worktree", "remove", "--force", worktree, check=False)
            git("worktree", "prune", check=False)
            worktree = None
        git("reset", "--hard", main_head, check=False)
        git("tag", "-d", tag, check=False)
        restored = git("update-ref", "refs/heads/virtual-repo", vr_head, check=False)
        if git("rev-parse", "virtual-repo", check=False) != vr_head:
            print(
                f"WARNING: could not restore virtual-repo to {vr_head[:9]} "
                f"({restored}); inspect manually before retrying.",
                file=sys.stderr,
            )
        raise
    finally:
        if worktree:
            git("worktree", "remove", "--force", worktree, check=False)
            git("worktree", "prune", check=False)

    if not args.no_push and not args.no_verify:
        verify_live(nxt, os.path.join(REPO, plan.root_zip))
    return 0


# --------------------------------------------------------------------------- #
# Post-deploy live verification (Pages CDN can lag a minute or two)
# --------------------------------------------------------------------------- #
def _get(url: str) -> tuple[int, bytes]:
    try:
        with urllib.request.urlopen(url, timeout=15) as r:  # noqa: S310 (https only)
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, b""
    except Exception:  # noqa: BLE001
        return 0, b""


def verify_live(
    version: str, local_zip: str, attempts: int = 18, delay: int = 10
) -> bool:
    print("\nVerifying live on Pages (CDN may lag)...")
    zip_url = f"{BASE_URL}/{rl.zip_name(version)}"
    local_sha = sha256(local_zip)
    for i in range(1, attempts + 1):
        status, body = _get(zip_url)
        if status == 200 and hashlib.sha256(body).hexdigest() == local_sha:
            _, addons = _get(f"{BASE_URL}/repo/addons.xml")
            _, index = _get(f"{BASE_URL}/index.html")
            addons_ok = f'version="{version}"'.encode() in addons
            index_ok = rl.zip_name(version).encode() in index
            print(f"  zip 200 + sha match ......... OK (attempt {i})")
            print(f"  addons.xml = {version} ...... {'OK' if addons_ok else 'STALE'}")
            print(f"  index links {version} ....... {'OK' if index_ok else 'STALE'}")
            if addons_ok and index_ok:
                print("LIVE — deploy verified.")
                return True
        print(f"  attempt {i}/{attempts}: not propagated yet (zip http {status})")
        if i < attempts:
            time.sleep(delay)
    print(
        "Live verification timed out — the deploy is pushed; Pages may still be building."
    )
    return False


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if argv and argv[0] == "check":
        return cc.main()

    ap = argparse.ArgumentParser(description="Release the Tony.7.Bones repository.")
    ap.add_argument("--news", required=True, help="changelog line for this release")
    grp = ap.add_mutually_exclusive_group()
    grp.add_argument("--version", help="explicit version X.Y.Z (must exceed current)")
    grp.add_argument("--minor", action="store_true", help="bump the minor field")
    grp.add_argument("--major", action="store_true", help="bump the major field")
    ap.add_argument(
        "--dry-run", action="store_true", help="show the plan, change nothing"
    )
    ap.add_argument("--no-push", action="store_true", help="commit + tag locally only")
    ap.add_argument("--no-verify", action="store_true", help="skip live Pages polling")
    args = ap.parse_args(argv)
    return deploy(args)


if __name__ == "__main__":
    sys.exit(main())
