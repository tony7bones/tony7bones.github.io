#!/usr/bin/env python3
"""Publish canvas-only changes (commit -> push to main; CI builds the site).

The LIGHT publish path for hand-authored content under dropbox/ (repository
installer zips, media, iptv, rss). The served mirror is generated in CI by
build_site.py, so publishing a canvas edit is just: commit the dropbox/
change, push main — WITHOUT cutting a release (no version bump, no git tag).
Use this for canvas edits; use `release.py` only when an add-on itself
changes.

What it does:
  1. fetch + guard: on main, not behind origin
  2. run the generator (keeps the committed add-on artifacts fresh)
  3. `git add -A`, show exactly what will be committed
  4. SECRET GUARD: scan the staged additions for credential patterns
     (username=/password= in URLs, api keys). Aborts unless --allow-secrets,
     because the repo is PUBLIC and a published secret is immediately burned.
  5. commit, push (the pre-push hook still runs tests/lint/staleness); the
     push triggers the CI build+deploy, which regenerates the served mirror.

Usage:
    python3 _tools/publish_canvas.py -m "Add foo repo zip to canvas"
    python3 _tools/publish_canvas.py -m "..." --dry-run     # show plan, change nothing
    python3 _tools/publish_canvas.py -m "..." --no-push     # regenerate + commit only
    python3 _tools/publish_canvas.py -m "..." --allow-secrets  # publish flagged content anyway
"""

from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from release import git, run_generator  # noqa: E402

# The KodiShare backup mirror - guarded exactly as in deploy.py (not in any
# sandbox copy list; a missing module means "no share sync in this env").
try:
    import sync_share  # noqa: E402
except ImportError:
    sync_share = None

# Credential shapes that must never reach a PUBLIC page. Shared with the
# CI-built-artifact gate (check_site_secrets.py); the canonical list lives in
# secret_patterns.py. Scanned against ADDED lines only.
from secret_patterns import ALLOW_FILES as _ALLOW_FILES  # noqa: E402
from secret_patterns import SECRET_PATTERNS as _SECRET_PATTERNS  # noqa: E402


def current_branch() -> str:
    return git("rev-parse", "--abbrev-ref", "HEAD")


def staged_additions() -> list[tuple[str, str]]:
    """(file, added_line) for every '+' line in the staged diff, secret-scannable."""
    diff = git("diff", "--cached", "-U0", "--no-color")
    out: list[tuple[str, str]] = []
    path = ""
    for line in diff.splitlines():
        if line.startswith("+++ b/"):
            path = line[6:]
        elif line.startswith("+") and not line.startswith("+++"):
            out.append((path, line[1:]))
    return out


def scan_for_secrets() -> list[tuple[str, str]]:
    """List (file, matched-snippet) for staged additions that look like secrets."""
    hits: list[tuple[str, str]] = []
    for path, added in staged_additions():
        if os.path.basename(path) in _ALLOW_FILES:
            continue
        for pat in _SECRET_PATTERNS:
            m = pat.search(added)
            if m:
                hits.append((path, m.group(0)))
                break
    return hits


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Publish canvas-only changes (regenerate -> commit -> push)."
    )
    ap.add_argument("-m", "--message", help="commit message (required to commit)")
    ap.add_argument(
        "--dry-run", action="store_true", help="show the plan, change nothing"
    )
    ap.add_argument("--no-push", action="store_true", help="regenerate + commit only")
    ap.add_argument(
        "--allow-secrets",
        action="store_true",
        help="publish even if the secret guard flags staged content",
    )
    ap.add_argument("--branch", default="main", help="expected branch (default: main)")
    args = ap.parse_args(argv)

    # 1. Guards: right branch, not behind origin.
    branch = current_branch()
    if branch != args.branch:
        print(f"refusing: on '{branch}', expected '{args.branch}'.", file=sys.stderr)
        return 2
    git("fetch", "-q", "origin", args.branch, check=False)
    behind = git("rev-list", "--count", f"HEAD..origin/{args.branch}", check=False)
    if behind and behind != "0":
        print(
            f"refusing: {behind} commit(s) behind origin/{args.branch}. "
            "Pull/rebase first.",
            file=sys.stderr,
        )
        return 2

    # 2. Keep the committed add-on artifacts fresh (the served mirror itself
    # is generated in CI by build_site.py, not here).
    print("Regenerating committed add-on artifacts ...")
    run_generator()

    # 3. Stage the canvas edits (and anything the generator refreshed).
    git("add", "-A")
    staged = git("diff", "--cached", "--name-only")
    if not staged:
        print("Nothing to publish — no canvas changes to commit.")
        return 0

    print("\nChanges to publish:")
    print(git("diff", "--cached", "--stat"))

    # 4. Secret guard (safe-by-default).
    hits = scan_for_secrets()
    if hits:
        print(
            "\n*** SECRET GUARD: credential-like content in staged changes ***",
            file=sys.stderr,
        )
        for path, snippet in hits:
            print(f"  {path}: {snippet}", file=sys.stderr)
        if not args.allow_secrets:
            print(
                "\nRefusing to publish to a PUBLIC site. Remove the secret, or pass "
                "--allow-secrets if this is intentional (and rotate it afterwards).",
                file=sys.stderr,
            )
            # Leave the regenerated tree staged so the user can inspect/fix it.
            return 3
        print("  --allow-secrets set: proceeding despite the guard.", file=sys.stderr)

    if args.dry_run:
        print("\n--dry-run: not committing or pushing. Staged changes left in place.")
        return 0

    if not args.message:
        print("refusing: -m/--message is required to commit.", file=sys.stderr)
        return 2

    # 5. Commit, push, force a Pages build.
    git("commit", "-m", args.message)
    print(f"\nCommitted: {args.message}")

    if args.no_push:
        print("--no-push: committed locally only.")
        return 0

    print(f"Pushing {args.branch} ...")
    git("push", "origin", args.branch)
    # The push triggers the Pages build+deploy workflow (Pages source is now
    # GitHub Actions); no manual build trigger is needed.
    # Refresh the KodiShare backup copies of the canvas installer zips
    # (best-effort, mount-guarded; publishing never fails on the share).
    if sync_share is not None:
        sync_share.best_effort()
    print("Pushed. CI will build and deploy the site shortly.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
