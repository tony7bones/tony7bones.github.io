#!/usr/bin/env python3
"""One-command release for EVERY add-on in the Tony.7.Bones repo.

THE single release entry point (Phase 5 unified both paths):

  * The first-party **script.* / script.module.*** add-ons (the default mode).
    Detects which changed since the last released state (`origin/main`), computes
    the correct next version (MINOR by default), auto-drafts and prepends the news
    line, raises the lockstep `<import>` when the shared library moves (and bumps
    its holder atomically), regenerates the repo deterministically, runs the
    gates, and commits ON THE BRANCH — then STOPS. No auto-push, no auto-merge
    (the owner keeps the branch -> merge -> main flow); `--push` is opt-in.

  * The **`repository.tony7bones` proxy** (`--proxy`, or auto-detected when the
    proxy is the changed add-on). The proxy release is FUNDAMENTALLY different:
    it IS the push. It runs the proven atomic transaction — bump -> deterministic
    build -> sync all three version-bearing locations -> commit main -> tag ->
    `git push --atomic main <tag>` -> force a Pages build -> verify live, with
    rollback on any failure. This mode DELEGATES to `deploy.py`'s exact, proven
    transaction (`deploy.deploy`) — it does NOT reimplement it — so the proxy
    release is byte-for-byte the same code that has shipped every proxy release.
    `deploy.py` itself stays a fully-working independent entry point (its whole
    `test_deploy.py` suite passes unchanged); `release.py --proxy` is a thin
    front door onto the same transaction.

This is the script.* analog of the proxy's `deploy.py`, sharing its atomic
structure (preflight -> write -> build -> determinism gate -> commit, with full
rollback on any failure) and the SAME shared change detector + version math so
the tool and the pre-push gate can never disagree (QA must-fix MF-1).

Usage:
    python3 _tools/release.py                 # minor bump every changed add-on, commit
    python3 _tools/release.py --dry-run       # show the plan (incl. WHICH files), change nothing
    python3 _tools/release.py --patch         # patch level instead of minor
    python3 _tools/release.py --major
    python3 _tools/release.py --version 1.6.0 --addon script.module.tony7bones
    python3 _tools/release.py --news "script.tony7bones.bootstrap=Fix first-boot race"
    python3 _tools/release.py --push          # also push the branch (default: do not)
    python3 _tools/release.py check           # the script-side consistency gate only

    # Proxy (repository.tony7bones) — the full atomic push+tag+Pages+verify:
    python3 _tools/release.py --proxy --news "What changed"   # patch bump (proxy default)
    python3 _tools/release.py --proxy --minor --news "..."    # or --major / --version
    python3 _tools/release.py --proxy --news "..." --dry-run  # show the plan only
    python3 _tools/release.py --proxy --news "..." --no-push  # local commit + tag only
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
LIBRARY_ID = "script.module.tony7bones"
PROXY_ID = "repository.tony7bones"

# Strip a leading conventional-commit prefix when drafting a news line.
_CONVENTIONAL_RE = re.compile(r"^[a-z]+(\([^)]*\))?!?:\s*")


# --------------------------------------------------------------------------- #
# git / fs helpers (mirror deploy.py)
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
# Reading manifests / the lockstep graph
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
    """All add-on ids under addons/ EXCEPT the proxy (deploy.py owns that path)."""
    return [aid for aid, _ in rd.addon_dirs(REPO) if aid != "repository.tony7bones"]


def dependents_of(library_id: str) -> list[str]:
    """First-party add-ons whose <import> targets `library_id` (the lockstep).

    Read from the live manifests so a future third dependency is picked up with
    no code change — the graph is data, not a hard-coded library->bootstrap edge.
    """
    out = []
    for aid in first_party_ids():
        if aid == library_id:
            continue
        if rl.read_import_version(read(addon_xml_path(aid)), library_id) is not None:
            out.append(aid)
    return out


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
        lockstep_import: tuple[str, str] | None = None,
    ):
        self.addon_id = addon_id
        self.cur = cur
        self.nxt = nxt
        self.news = news
        self.reason = reason  # "source" | "lockstep" | "source+lockstep"
        self.files = files
        # (library_id, new_version) when this add-on must raise an import.
        self.lockstep_import = lockstep_import


def _level(args) -> str:
    return "major" if args.major else "patch" if args.patch else "minor"


def _next_for(addon_id: str, cur: str, args) -> str:
    if args.version and (args.addon is None or args.addon == addon_id):
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

    Two-pass over the shallow first-party graph (library is the only dependency):
      1. Direct source changes -> a bump each.
      2. If the library is bumping, every dependent must raise its <import> to the
         library's new version AND bump (MF-2 atomic: never raise an import
         without bumping its holder).
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

    # Pass 1 — direct source changes (skip already-released, MF-6).
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

    # Pass 2 — lockstep: if the library is bumping, force every dependent.
    if LIBRARY_ID in bumps:
        lib_new = bumps[LIBRARY_ID].nxt
        for dep in dependents_of(LIBRARY_ID):
            cur_imp = rl.read_import_version(read(addon_xml_path(dep)), LIBRARY_ID)
            if cur_imp == lib_new:
                continue  # already in lockstep (idempotent re-run)
            if dep in bumps:
                # dependent already bumping for its own source — just also raise
                # its import (single bump, MF-7).
                bumps[dep].lockstep_import = (LIBRARY_ID, lib_new)
                bumps[dep].reason = "source+lockstep"
            else:
                cur = current_version(dep)
                nxt = _next_for(dep, cur, args)
                bumps[dep] = AddonBump(
                    dep,
                    cur,
                    nxt,
                    _news_for(dep, base_ref, args),
                    "lockstep",
                    [],
                    lockstep_import=(LIBRARY_ID, lib_new),
                )

    return [bumps[k] for k in sorted(bumps)], sorted(already)


# --------------------------------------------------------------------------- #
# Preflight (mirror deploy.py guards)
# --------------------------------------------------------------------------- #
def _behind_origin(base_ref: str) -> list[str]:
    """MF-5: refuse when the local branch is behind its origin counterpart.

    Mirrors deploy.py: fetch, then count how far behind. A fetch failure
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
        if not rl.is_single_digit(b.nxt):
            problems.append(
                f"{b.addon_id}: next version {b.nxt} is not single-digit (0-9)"
            )
        if not rl.is_greater(b.nxt, b.cur):
            problems.append(
                f"{b.addon_id}: next version {b.nxt} is not greater than current "
                f"{b.cur} (every release MUST bump)"
            )
    return problems


# --------------------------------------------------------------------------- #
# Apply (atomic, rollback on failure — mirror deploy.py)
# --------------------------------------------------------------------------- #
def _write_bump(b: AddonBump) -> None:
    path = addon_xml_path(b.addon_id)
    xml = read(path)
    if b.lockstep_import is not None:
        dep_id, dep_v = b.lockstep_import
        xml = rl.set_import_version(xml, dep_id, dep_v)
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
        # 1. write every bump (version + lockstep import + news)
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
        ok, info, problems = script_consistency(base_ref)
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
# Script-side consistency gate (well-formed, single-digit, monotonic, lockstep)
# --------------------------------------------------------------------------- #
def script_consistency(
    base_ref: str = rd.BASE_REF,
) -> tuple[bool, list[str], list[str]]:
    """Return (ok, info, problems) for the first-party script.* add-ons.

    Asserts, reading the WORKING TREE manifests: every add-on version is
    well-formed + single-digit; every changed add-on is strictly greater than its
    base_ref version; and every dependent's <import> of the library EQUALS the
    library's shipped version (strict lockstep). Reused by the `check`
    sub-command. Skips the monotonic half cleanly when base_ref is absent.
    """
    info: list[str] = []
    problems: list[str] = []
    have_base = rd.base_ref_exists(REPO, base_ref)

    lib_version = (
        current_version(LIBRARY_ID) if LIBRARY_ID in first_party_ids() else None
    )

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

    # Lockstep: every dependent's import == the library's shipped version.
    if lib_version is not None:
        for dep in dependents_of(LIBRARY_ID):
            imp = rl.read_import_version(read(addon_xml_path(dep)), LIBRARY_ID)
            if imp != lib_version:
                problems.append(
                    f"{dep}: <import {LIBRARY_ID}> is {imp}, but the library ships "
                    f"{lib_version} (lockstep out of sync)"
                )
            else:
                info.append(f"{dep}: lockstep {LIBRARY_ID} == {lib_version} OK")

    return (not problems), info, problems


# --------------------------------------------------------------------------- #
# Proxy mode — delegate to deploy.py's PROVEN atomic transaction
# --------------------------------------------------------------------------- #
class _ProxyArgs:
    """Translate release.py's flags into the attribute shape ``deploy.deploy``
    expects, so the proxy release runs deploy.py's exact code (no reimplementation).

    ``deploy.deploy`` reads: ``version``, ``major``, ``minor``, ``news``,
    ``dry_run``, ``no_push``, ``no_verify``. The proxy keeps deploy.py's own
    default level (PATCH) when no level flag is given — identical to running
    ``deploy.py`` directly.
    """

    def __init__(self, args):
        self.version = args.version
        self.major = args.major
        # release.py's --patch maps to deploy's "not --minor and not --major"
        # (deploy's default level is patch); --minor is explicit.
        self.minor = args.minor
        self.news = args.news
        self.dry_run = args.dry_run
        # release.py uses opt-in --push; deploy.py uses opt-out --no-push. The
        # proxy release IS the push, so the default is to push (no_push=False)
        # unless the caller explicitly passed --no-push.
        self.no_push = args.no_push
        self.no_verify = args.no_verify


def release_proxy(args) -> int:
    """Run the proxy (`repository.tony7bones`) release via deploy.py's transaction.

    Imported lazily so the script.* path never pays deploy.py's import cost (and
    so a test exercising only the script.* flow needs no deploy.py on the path).
    ``--news`` is required by the proxy transaction (deploy.py asserts it).
    """
    if not args.news:
        print(
            'PRE-FLIGHT FAILED:\n  - the proxy release requires --news "What changed"',
            file=sys.stderr,
        )
        return 1
    import deploy as dp  # lazy: only the proxy path needs it

    return dp.deploy(_ProxyArgs(args))


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def _print_plan(bumps: list[AddonBump], already: list[str], base_ref: str) -> None:
    print(f"Release plan (baseline {base_ref}):")
    if not bumps:
        print("  no changed add-ons to release.")
    for b in bumps:
        lock = ""
        if b.lockstep_import is not None:
            lock = f"   [lockstep: import {b.lockstep_import[0]} -> {b.lockstep_import[1]}]"
        print(f"  {b.addon_id}  {b.cur} -> {b.nxt}  ({b.reason}){lock}")
        if b.files:
            for f in b.files:
                print(f"      changed: {f}")
        elif b.reason == "lockstep":
            print("      changed: (lockstep-only — forced by the library bump)")
        print(f"      news:    v{b.nxt}: {b.news}")
    for aid in already:
        print(f"  {aid}: already released (greater than {base_ref}, bump-only) — no-op")


def _proxy_requested(args) -> bool:
    """True when this invocation should run the proxy transaction.

    Explicit ``--proxy`` always wins. Otherwise auto-detect: if the ONLY add-on
    changed vs the baseline is the proxy (`repository.tony7bones`), route to the
    proxy path — the proxy is excluded from the script.* flow, so a bare
    ``release.py`` on a proxy-only change would otherwise report "nothing to
    release". A mixed change (proxy + a script.* add-on) is NOT auto-routed: the
    two transactions are distinct and the owner must pick (`--proxy` for the
    proxy, a plain run for the script.* add-ons) so neither is silently skipped.
    """
    if args.proxy:
        return True
    if args.addon == PROXY_ID:
        return True
    if not rd.base_ref_exists(REPO, rd.BASE_REF):
        return False
    changed = set(rd.changed_addons(REPO, rd.BASE_REF, worktree=True))
    return changed == {PROXY_ID}


def run(args) -> int:
    if _proxy_requested(args):
        return release_proxy(args)

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
        ok, info, problems = script_consistency()
        print("script-side consistency check:")
        for line in info:
            print(f"  {line}")
        if ok:
            print("OK — versions well-formed, bumped, and in lockstep")
            return 0
        print("FAIL:")
        for p in problems:
            print(f"  - {p}")
        return 1

    ap = argparse.ArgumentParser(
        description=(
            "Release any add-on: the first-party script.* add-ons (auto bump + "
            "news + lockstep, commit-on-branch) or the repository.tony7bones proxy "
            "(--proxy: the atomic push + tag + Pages + verify, via deploy.py)."
        )
    )
    grp = ap.add_mutually_exclusive_group()
    grp.add_argument(
        "--patch",
        action="store_true",
        help="patch bump (script default: minor; proxy default: patch)",
    )
    grp.add_argument(
        "--minor",
        action="store_true",
        help="minor bump (the proxy default is patch — use this for a proxy minor)",
    )
    grp.add_argument("--major", action="store_true", help="major bump")
    grp.add_argument("--version", help="explicit X.Y.Z (use with --addon, or --proxy)")
    ap.add_argument("--addon", help="scope the release to a single first-party add-on")
    ap.add_argument(
        "--proxy",
        action="store_true",
        help="release the repository.tony7bones proxy (delegates to deploy.py's "
        "atomic push+tag+Pages+verify transaction)",
    )
    ap.add_argument(
        "--news",
        help="override the drafted news: 'id=line' for one add-on, a bare line, "
        "or (with --proxy) the proxy changelog line (required for the proxy)",
    )
    ap.add_argument(
        "--dry-run", action="store_true", help="show the plan, change nothing"
    )
    ap.add_argument(
        "--push", action="store_true", help="push the branch (default: commit only)"
    )
    ap.add_argument(
        "--no-push",
        action="store_true",
        help="proxy only: commit + tag locally, do not push",
    )
    ap.add_argument(
        "--no-verify",
        action="store_true",
        help="proxy only: skip the live Pages verification poll",
    )
    args = ap.parse_args(argv)
    return run(args)


if __name__ == "__main__":
    sys.exit(main())
