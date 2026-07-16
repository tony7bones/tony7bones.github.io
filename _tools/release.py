#!/usr/bin/env python3
"""One-command release for EVERY add-on in the Tony.7.Bones repo.

THE single release entry point. Every add-on - including
`repository.tony7bones`, now a normal static-only repository add-on - releases
the same way: detect which changed since the last released state
(`origin/main`), compute the next version (MINOR by default), auto-draft and
prepend the news line, regenerate the repo deterministically,
run the gates, and commit ON THE BRANCH - then STOP. No auto-push, no
auto-merge (the owner keeps the branch -> merge -> main flow); `--push` is
opt-in. On push, CI builds and deploys the static site.

Shares the SAME change detector + version math as the pre-push gate so the two
can never disagree.

Usage:
    python3 _tools/release.py                 # minor bump every changed add-on, commit
    python3 _tools/release.py --dry-run       # show the plan (incl. WHICH files), change nothing
    python3 _tools/release.py --patch         # patch level instead of minor
    python3 _tools/release.py --major
    python3 _tools/release.py --version 3.1.0 --addon repository.tony7bones
    python3 _tools/release.py --news "repository.tony7bones=Add a new hosted add-on"
    python3 _tools/release.py --push          # also push the branch (default: do not)
    python3 _tools/release.py check           # the script-side consistency gate only
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import release_detect as rd  # noqa: E402
import release_lib as rl  # noqa: E402

REPO = rd.REPO_ROOT
ADDON_DIR = os.path.join(REPO, "addons")
GENERATOR = os.path.join(REPO, "_tools", "generate_repo.py")

# Strip a leading conventional-commit prefix when drafting a news line.
_CONVENTIONAL_RE = re.compile(r"^[a-z]+(\([^)]*\))?!?:\s*")


# --------------------------------------------------------------------------- #
# git / fs helpers
# --------------------------------------------------------------------------- #
def git(*args: str, check: bool = True, repo: str | None = None) -> str:
    # Resolve REPO at CALL time (not as a default arg, which binds at import) so a
    # test monkeypatching release.REPO to a sandbox makes EVERY git call — incl.
    # the rollback `git reset --hard` — follow the sandbox, never the real repo.
    r = subprocess.run(
        ["git", "-C", repo or REPO, *args], capture_output=True, text=True
    )
    if check and r.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed:\n{r.stderr.strip()}")
    return r.stdout.strip()


def read(path: str) -> str:
    with open(path, encoding="utf-8") as f:
        return f.read()


def write(path: str, text: str) -> None:
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def addon_xml_path(addon_id: str) -> str:
    return os.path.join(ADDON_DIR, addon_id, "addon.xml")


def run_generator() -> None:
    subprocess.run(
        [sys.executable, GENERATOR],
        cwd=REPO,
        check=True,
        capture_output=True,
        text=True,
    )


# --------------------------------------------------------------------------- #
# Reading manifests
# --------------------------------------------------------------------------- #
def current_version(addon_id: str) -> str:
    return rl.read_addon_version(read(addon_xml_path(addon_id)))


def baseline_version(addon_id: str, base_ref: str) -> str | None:
    """The add-on's version on `base_ref`, or None if it is a new add-on."""
    r = subprocess.run(
        ["git", "-C", REPO, "show", f"{base_ref}:addons/{addon_id}/addon.xml"],
        capture_output=True,
        text=True,
    )
    if r.returncode != 0:
        return None
    return rl.read_addon_version(r.stdout)


def first_party_ids() -> list[str]:
    """All add-on ids under addons/. Includes repository.tony7bones, which is
    now a normal static-only add-on released the same way as every other."""
    return [aid for aid, _ in rd.addon_dirs(REPO)]


# --------------------------------------------------------------------------- #
# News drafting
# --------------------------------------------------------------------------- #
def _strip_conventional(subject: str) -> str:
    return _CONVENTIONAL_RE.sub("", subject).strip()


def draft_news(addon_id: str, base_ref: str) -> str:
    """Draft a news line from the add-on's commit subjects since `base_ref`.

    Uses `git log base_ref..HEAD` scoped to the add-on dir (the generated zip +
    index excluded), strips conventional-commit prefixes, and joins the unique
    subjects. Falls back to a generic line when there are no scoped commits yet
    (the source edit is uncommitted — the tool runs pre-commit).
    """
    rel = f"addons/{addon_id}"
    out = git(
        "log",
        f"{base_ref}..HEAD",
        "--format=%s",
        "--",
        rel,
        f":(exclude){rel}/*.zip",
        f":(exclude){rel}/index.html",
        check=False,
    )
    subjects: list[str] = []
    for line in out.splitlines():
        cleaned = _strip_conventional(line)
        if cleaned and cleaned not in subjects:
            subjects.append(cleaned)
    if not subjects:
        return "Maintenance release."
    return "; ".join(subjects)


# --------------------------------------------------------------------------- #
# The plan
# --------------------------------------------------------------------------- #
class AddonBump:
    def __init__(
        self,
        addon_id: str,
        cur: str,
        nxt: str,
        news: str,
        reason: str,
        files: list[str],
    ):
        self.addon_id = addon_id
        self.cur = cur
        self.nxt = nxt
        self.news = news
        self.reason = reason  # "source"
        self.files = files


def _level(args) -> str:
    return "major" if args.major else "patch" if args.patch else "minor"


def _next_for(addon_id: str, cur: str, args) -> str:
    if args.version and (args.addon is None or args.addon == addon_id):
        # An add-on whose CURRENT version already predates the single-digit
        # scheme (EZ Maintenance++'s date-stamped 2026.07.02.0 - four
        # components, not X.Y.Z) must be allowed to stay in that same scheme;
        # enforcing single-digit X.Y.Z here would make it impossible to ever
        # explicitly version-bump one of these add-ons at all.
        if not rl.is_single_digit(cur):
            try:
                rl.parse_version_loose(args.version)
            except ValueError as exc:
                raise SystemExit(
                    f"PRE-FLIGHT FAILED:\n  - version {args.version!r} is not "
                    f"a valid dotted numeric version ({exc})"
                ) from exc
            return args.version
        rl.parse_version(args.version)
        if not rl.is_single_digit(args.version):
            raise SystemExit(
                "PRE-FLIGHT FAILED:\n"
                f"  - version {args.version} is not single-digit "
                "(each of MAJOR.MINOR.PATCH must be 0-9)"
            )
        return args.version
    try:
        return rl.next_version(cur, _level(args))
    except ValueError as exc:
        raise SystemExit(
            "PRE-FLIGHT FAILED:\n"
            f"  - {addon_id}: {exc} (use --version to reset MAJOR by hand)"
        ) from exc


def _news_for(addon_id: str, base_ref: str, args) -> str:
    """The owner's --news override (per-addon `id=line` or a bare line) or a draft."""
    if args.news:
        if "=" in args.news:
            target, line = args.news.split("=", 1)
            if target.strip() == addon_id:
                return line.strip()
        elif args.addon in (None, addon_id):
            return args.news.strip()
    return draft_news(addon_id, base_ref)


def _last_version_change_commit(addon_id: str) -> str | None:
    """The newest commit whose diff TOUCHED this add-on's addon.xml, or None.

    That commit is where the current version was introduced — the add-on's last
    release point. We use it to ask "did any SOURCE change after the bump?".
    """
    rel = f"addons/{addon_id}/addon.xml"
    out = git("log", "-1", "--format=%H", "--", rel, check=False)
    return out.strip() or None


def _source_changed_since(addon_id: str, ref: str) -> bool:
    """True iff the add-on's SOURCE (excluding addon.xml + generated zip/index)
    changed between `ref` and the working tree.

    Excluding addon.xml means a pure version/news bump does NOT count as a source
    change — only real code/resource edits do. This is the signal that a NEW
    release is warranted after the last bump (vs an idempotent re-run).
    """
    rel = f"addons/{addon_id}"
    diff = subprocess.run(
        [
            "git",
            "-C",
            REPO,
            "diff",
            "--quiet",
            ref,
            "--",
            rel,
            f":(exclude){rel}/addon.xml",
            f":(exclude){rel}/*.zip",
            f":(exclude){rel}/index.html",
        ],
        capture_output=True,
        text=True,
    )
    return diff.returncode != 0


def _already_released(addon_id: str, base_ref: str) -> bool:
    """MF-6 idempotency: the add-on is already bumped (vs base_ref) and NO source
    changed since that bump — a re-run must NOT double-bump.

    Detects the re-run footgun: the tool committed a bump but it has not been
    pushed, so the add-on still 'differs' from origin/main. The clean signal is:
    current version is already greater than the baseline version AND no real
    source (anything but addon.xml's own version/news line) changed since the
    commit that introduced the current version. A genuinely new edit after the
    bump DOES change source and is correctly NOT treated as already-released.
    """
    base_v = baseline_version(addon_id, base_ref)
    if base_v is None:
        return False  # new add-on — not already released
    cur_v = current_version(addon_id)
    # An add-on whose BASELINE predates the single-digit scheme (EZ
    # Maintenance++'s date-stamped 2026.07.02.0, modv2plus's 1.4.10) must be
    # compared within that same scheme - rl.is_greater's strict parser raises
    # ValueError on anything else, which used to crash this check outright
    # the first time a change to one of those add-ons ever reached it.
    try:
        is_bumped = (
            rl.is_greater_loose(cur_v, base_v)
            if not rl.is_single_digit(base_v)
            else rl.is_greater(cur_v, base_v)
        )
    except ValueError:
        return False  # not a valid version either way — a real pending change
    if not is_bumped:
        return False  # not yet bumped — a real pending change
    bump_commit = _last_version_change_commit(addon_id)
    if bump_commit is None:
        return False
    return not _source_changed_since(addon_id, bump_commit)


def build_plan(args, base_ref: str) -> tuple[list[AddonBump], list[str]]:
    """Return (bumps, already_released_ids).

    Each add-on with a direct source change gets one bump (already-released
    add-ons are skipped, MF-6). The add-ons are independent - there is no shared
    library, so a change to one never forces a bump of another.
    """
    changed = set(rd.changed_addons(REPO, base_ref, worktree=True))
    if args.addon:
        if args.addon not in first_party_ids():
            raise SystemExit(
                f"PRE-FLIGHT FAILED:\n  - unknown first-party add-on {args.addon!r}"
            )
        changed &= {args.addon}

    already: list[str] = []
    bumps: dict[str, AddonBump] = {}

    for addon_id in sorted(changed):
        if _already_released(addon_id, base_ref):
            already.append(addon_id)
            continue
        cur = current_version(addon_id)
        nxt = _next_for(addon_id, cur, args)
        files = rd.changed_files(REPO, addon_id, base_ref, worktree=True)
        bumps[addon_id] = AddonBump(
            addon_id, cur, nxt, _news_for(addon_id, base_ref, args), "source", files
        )

    return [bumps[k] for k in sorted(bumps)], sorted(already)


# --------------------------------------------------------------------------- #
# Preflight
# --------------------------------------------------------------------------- #
def _behind_origin(base_ref: str) -> list[str]:
    """MF-5: refuse when the local branch is behind its origin counterpart.

    Fetch, then count how far behind. A fetch failure
    (offline) degrades to a warning, not a hard block.
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
    branch = git("rev-parse", "--abbrev-ref", "HEAD")
    remote = f"origin/{branch}"
    if git("rev-parse", "--verify", "--quiet", f"refs/remotes/{remote}", check=False):
        behind = git("rev-list", "--count", f"{branch}..{remote}", check=False)
        if behind not in ("", "0"):
            problems.append(
                f"{branch} is behind {remote} by {behind} commit(s) — pull first"
            )
    return problems


def preflight(bumps: list[AddonBump], base_ref: str) -> list[str]:
    problems: list[str] = []
    problems.extend(_behind_origin(base_ref))
    for b in bumps:
        # An add-on already on a legacy, non-single-digit scheme (EZ
        # Maintenance++'s real date-stamped 2026.07.02.0) must be compared
        # within that same scheme - see _next_for's identical exemption.
        legacy = not rl.is_single_digit(b.cur)
        if not legacy and not rl.is_single_digit(b.nxt):
            problems.append(
                f"{b.addon_id}: next version {b.nxt} is not single-digit (0-9)"
            )
        try:
            bumped = (
                rl.is_greater_loose(b.nxt, b.cur)
                if legacy
                else rl.is_greater(b.nxt, b.cur)
            )
        except ValueError as exc:
            problems.append(f"{b.addon_id}: {exc}")
            continue
        if not bumped:
            problems.append(
                f"{b.addon_id}: next version {b.nxt} is not greater than current "
                f"{b.cur} (every release MUST bump)"
            )
    return problems


# --------------------------------------------------------------------------- #
# Apply (atomic, rollback on failure)
# --------------------------------------------------------------------------- #
def _write_bump(b: AddonBump) -> None:
    path = addon_xml_path(b.addon_id)
    xml = read(path)
    xml = rl.set_addon_version(xml, b.nxt)
    xml = rl.prepend_addon_news(xml, b.news, version=b.nxt)
    write(path, xml)


def _commit_subject(bumps: list[AddonBump]) -> str:
    parts = [f"{b.addon_id.split('.')[-1]} {b.nxt}" for b in bumps]
    return "chore(release): " + " + ".join(parts)


def apply_release(args, bumps: list[AddonBump], base_ref: str) -> int:
    head = git("rev-parse", "HEAD")
    branch = git("rev-parse", "--abbrev-ref", "HEAD")
    try:
        # 1. write every bump (version + news)
        for b in bumps:
            _write_bump(b)

        # 2. build deterministically
        run_generator()

        # 3. commit on the branch
        git("add", "-A")
        subject = _commit_subject(bumps)
        body = "\n".join(
            f"- {b.addon_id}: {b.cur} -> {b.nxt} ({b.reason})" for b in bumps
        )
        git("commit", "-m", f"{subject}\n\n{body}")

        # 4. determinism gate: regenerate, tree must stay clean
        run_generator()
        if git("status", "--porcelain"):
            raise RuntimeError(
                "generator is non-deterministic: regeneration produced a diff"
            )

        # 5. script-side consistency gate BEFORE surfacing success / pushing
        ok, problems = script_consistency(base_ref)
        if not ok:
            raise RuntimeError("consistency gate failed: " + "; ".join(problems))

        # 6. push only when asked (default: leave on the branch)
        if args.push:
            git("push", "origin", branch)
            print(f"\nPushed {branch}.")
        else:
            print(
                f"\nCommitted {subject} on {branch}. "
                "Not pushed (merge to main per the release flow, or re-run with --push)."
            )
    except Exception as exc:  # noqa: BLE001 — re-raise after rollback
        print(
            f"\nRELEASE FAILED: {exc}\nRolling back to pre-release state...",
            file=sys.stderr,
        )
        git("reset", "--hard", head, check=False)
        raise
    return 0


# --------------------------------------------------------------------------- #
# Script-side consistency gate (well-formed, single-digit, monotonic)
# --------------------------------------------------------------------------- #
def script_consistency(
    base_ref: str = rd.BASE_REF,
) -> tuple[bool, list[str]]:
    """Return (ok, problems) for the first-party add-ons.

    Asserts, reading the WORKING TREE manifests: every add-on version is
    well-formed + single-digit, and every changed add-on is strictly greater than
    its base_ref version. Reused by the `check` sub-command. Skips the monotonic
    half cleanly when base_ref is absent.
    """
    problems: list[str] = []
    have_base = rd.base_ref_exists(REPO, base_ref)

    for addon_id in first_party_ids():
        cur = current_version(addon_id)
        base_v = baseline_version(addon_id, base_ref) if have_base else None
        # An add-on whose BASELINE already predates the single-digit scheme (a
        # real, pre-existing, Kodi-facing version lineage such as EZ
        # Maintenance++'s date-stamped 2026.07.02.0 or modv2plus's 1.4.10) must
        # keep comparing within that same scheme — mirrors check_versions.py's
        # gate exactly. Kodi's own AddonVersion comparison is component-wise
        # unbounded, so a legacy version already outranks any legal
        # single-digit X.Y.Z (max 9.9.9); forcing "compliance" here would look
        # like a downgrade to every box and the real update would never land.
        # Only enforce single-digit on add-ons whose baseline is ALREADY
        # single-digit (or brand new, no baseline at all).
        legacy_baseline = base_v is not None and not rl.is_single_digit(base_v)
        if not legacy_baseline and not rl.is_single_digit(cur):
            problems.append(f"{addon_id}: version {cur} is not single-digit (0-9)")
        if have_base:
            changed = addon_id in set(rd.changed_addons(REPO, base_ref, worktree=True))
            if base_v is not None and changed:
                try:
                    bumped = (
                        rl.is_greater_loose(cur, base_v)
                        if legacy_baseline
                        else rl.is_greater(cur, base_v)
                    )
                except ValueError:
                    problems.append(
                        f"{addon_id}: version {cur!r} (baseline {base_v!r}) is not "
                        "a valid dotted numeric version"
                    )
                    continue
                if not bumped:
                    problems.append(
                        f"{addon_id}: source changed but version not bumped "
                        f"({base_v} -> {cur})"
                    )

    return (not problems), problems


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def _print_plan(bumps: list[AddonBump], already: list[str], base_ref: str) -> None:
    print(f"Release plan (baseline {base_ref}):")
    if not bumps:
        print("  no changed add-ons to release.")
    for b in bumps:
        print(f"  {b.addon_id}  {b.cur} -> {b.nxt}  ({b.reason})")
        for f in b.files:
            print(f"      changed: {f}")
        print(f"      news:    v{b.nxt}: {b.news}")
    for aid in already:
        print(f"  {aid}: already released (greater than {base_ref}, bump-only) — no-op")


def run(args) -> int:
    base_ref = rd.BASE_REF
    if not rd.base_ref_exists(REPO, base_ref):
        print(f"no {base_ref} to compare against — nothing to release.")
        return 0

    bumps, already = build_plan(args, base_ref)

    problems = preflight(bumps, base_ref)
    if problems:
        print("PRE-FLIGHT FAILED:", file=sys.stderr)
        for p in problems:
            print(f"  - {p}", file=sys.stderr)
        return 1

    _print_plan(bumps, already, base_ref)

    if not bumps:
        return 0
    if args.dry_run:
        print("\n--dry-run: nothing was changed.")
        return 0

    # The tool runs PRE-COMMIT: the add-on source edit it is releasing is normally
    # still in the working tree (that is what `worktree=True` detection is for), so
    # a "dirty" tree is expected here — `git add -A` in apply_release stages exactly
    # the release. It then commits on the branch and STOPS (no push unless --push).
    return apply_release(args, bumps, base_ref)


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if argv and argv[0] == "check":
        ok, problems = script_consistency()
        print("script-side consistency check:")
        if ok:
            print("OK: versions well-formed and bumped")
            return 0
        print("FAIL:")
        for p in problems:
            print(f"  - {p}")
        return 1

    ap = argparse.ArgumentParser(
        description=(
            "Release any add-on (including repository.tony7bones, now a normal "
            "static-only add-on): auto bump + news, commit on the "
            "branch. CI builds and deploys the static site on push."
        )
    )
    grp = ap.add_mutually_exclusive_group()
    grp.add_argument("--patch", action="store_true", help="patch bump")
    grp.add_argument("--minor", action="store_true", help="minor bump (the default)")
    grp.add_argument("--major", action="store_true", help="major bump")
    grp.add_argument("--version", help="explicit X.Y.Z (use with --addon)")
    ap.add_argument("--addon", help="scope the release to a single add-on")
    ap.add_argument(
        "--news",
        help="override the drafted news: 'id=line' for one add-on or a bare line",
    )
    ap.add_argument(
        "--dry-run", action="store_true", help="show the plan, change nothing"
    )
    ap.add_argument(
        "--push", action="store_true", help="push the branch (default: commit only)"
    )
    args = ap.parse_args(argv)
    return run(args)


if __name__ == "__main__":
    sys.exit(main())
