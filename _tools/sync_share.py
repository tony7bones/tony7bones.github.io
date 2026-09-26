"""Mirror the installer zips to the local Kodi share backup.

`/Volumes/Kodi/Share/repositories/` holds a backup-install copy of the same
zips the site serves: the current `repository.tony7bones-<version>.zip` root
installer plus the hand-authored third-party installer zips from
`dropbox/repositories/`. Without this step it goes stale on every release (a
stale `repository.tony7bones-1.0.5.zip` sat there pointing at the long-dead
`repo/` layout - it installed on a fresh box and then silently served
nothing).

That is the ONE share directory this module touches. `apps/` (sideload
copies of first-party zips) and `media/`, `rss/` (canvas asset mirrors) were
synced here until 2026-09-26; none of those directories exists on the share
any more (measured that day: `/Volumes/Kodi/Share` holds `iptv/`,
`repositories/` and `userdata/` only), so the two syncs were unreachable code
and were deleted.

Contract:

  * BEST-EFFORT, NEVER BLOCKS A RELEASE. `best_effort()` catches everything
    and only prints; a push must succeed identically whether the share is
    mounted, unmounted, or broken.
  * ONLY when the destination is available. If the share dir does not exist
    (volume not mounted), the sync is skipped with a note - nothing is
    created, no mount is attempted.
  * ADDITIVE for foreign files. Files on the share that are not ours are
    never touched (the owner curates extras there). The ONLY deletions are
    superseded versions of our own installer.
  * SANDBOX-SAFE by construction. The system tests copy an explicit
    whitelist of _tools files into a sandbox repo; this module is
    deliberately NOT on that list, and publish_canvas.py imports it inside a
    try/except ImportError. A sandboxed run therefore cannot reach the real
    share no matter what paths exist on the machine. Do not add
    sync_share.py to the sandbox copy lists.

Triggers: publish_canvas.py calls `best_effort()` after a successful push,
and `.githooks/pre-push` runs this module (best-effort, main only) so plain
`git push` releases refresh the share too.

Manual run: `python3 _tools/sync_share.py [--dry-run]`.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import shutil
import sys
import xml.etree.ElementTree as ET

REPO = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
SHARE_ROOT = "/Volumes/Kodi/Share"
SHARE_DIR = SHARE_ROOT + "/repositories"

_INSTALLER_RE = re.compile(r"^repository\.tony7bones-(\d+(?:\.\d+)*)\.zip$")


def _sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _current_installer(repo_root: str) -> str | None:
    """Path of the current repository.tony7bones zip, or None if absent.

    The root installer is no longer committed (build_site.py places it in the
    CI artifact every deploy), so the share sources it from the committed
    add-on tree: addons/repository.tony7bones/<id>-<addon.xml version>.zip.
    """
    addon_dir = os.path.join(repo_root, "addons", "repository.tony7bones")
    xml = os.path.join(addon_dir, "addon.xml")
    try:
        version = ET.parse(xml).getroot().get("version")
    except (ET.ParseError, OSError):
        return None
    if not version:
        return None
    path = os.path.join(addon_dir, f"repository.tony7bones-{version}.zip")
    return path if os.path.isfile(path) else None


def sync(repo_root: str = REPO, share_dir: str = SHARE_DIR, dry_run: bool = False):
    """Mirror the installer + canvas repo zips to share_dir.

    Returns a list of (action, filename) tuples. Actions: "unavailable",
    "copied", "pruned", "unchanged", "error:<msg>". Per-file errors are
    recorded, not raised.
    """
    if not os.path.isdir(share_dir):
        return [("unavailable", share_dir)]

    actions: list[tuple[str, str]] = []

    # Source set: the current installer + every canvas third-party zip.
    sources: list[str] = []
    current_path = _current_installer(repo_root)
    current = os.path.basename(current_path) if current_path else None
    if current_path:
        sources.append(current_path)
    elif os.path.isfile(
        os.path.join(repo_root, "addons", "repository.tony7bones", "addon.xml")
    ):
        # addon.xml names a version whose zip is absent (mid-release state):
        # surface it instead of silently skipping copy + prune.
        actions.append(
            ("error:no built zip for repository.tony7bones", "repository.tony7bones")
        )
    canvas = os.path.join(repo_root, "dropbox", "repositories")
    if os.path.isdir(canvas):
        sources.extend(
            os.path.join(canvas, n)
            for n in sorted(os.listdir(canvas))
            if n.endswith(".zip")
        )

    for src in sources:
        name = os.path.basename(src)
        dst = os.path.join(share_dir, name)
        try:
            if os.path.isfile(dst) and _sha256(dst) == _sha256(src):
                actions.append(("unchanged", name))
                continue
            if not dry_run:
                shutil.copyfile(src, dst)
            actions.append(("copied", name))
        except OSError as exc:
            actions.append((f"error:{exc}", name))

    # Prune ONLY superseded copies of OUR installer; foreign zips stay.
    if current:
        for name in sorted(os.listdir(share_dir)):
            if _INSTALLER_RE.match(name) and name != current:
                try:
                    if not dry_run:
                        os.remove(os.path.join(share_dir, name))
                    actions.append(("pruned", name))
                except OSError as exc:
                    actions.append((f"error:{exc}", name))

    return actions


def best_effort(repo_root: str = REPO, share_dir: str = SHARE_DIR) -> None:
    """Run the sync and only ever print - a push must never fail on the share."""
    try:
        _report(sync(repo_root, share_dir), share_dir)
    except Exception as exc:  # noqa: BLE001 - deliberately fail-soft
        print(f"note: share sync skipped ({exc})", file=sys.stderr)


def _report(actions, share_dir: str) -> None:
    if actions and all(a == "unavailable" for a, _ in actions):
        print(f"Share sync: {share_dir} not mounted - skipped.")
        return
    changed = [(a, n) for a, n in actions if a in ("copied", "pruned", "unavailable")]
    errors = [(a, n) for a, n in actions if a.startswith("error:")]
    if not changed and not errors:
        print(f"Share sync: {share_dir} already up to date.")
        return
    print(f"Share sync -> {share_dir}:")
    for action, name in actions:
        if action == "unchanged":
            continue
        print(f"  {action:9s} {name}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Mirror the installer zips to the Kodi share backup."
    )
    ap.add_argument(
        "--share", default=SHARE_DIR, help=f"repositories dir (default {SHARE_DIR})"
    )
    ap.add_argument(
        "--dry-run", action="store_true", help="report what would change, copy nothing"
    )
    args = ap.parse_args(argv)
    _report(sync(REPO, args.share, dry_run=args.dry_run), args.share)
    if args.dry_run:
        print("--dry-run: nothing was changed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
