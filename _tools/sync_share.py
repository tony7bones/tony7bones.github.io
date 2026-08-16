"""Mirror the installable zips to the local Kodi share backup.

Two share dirs, two contracts:

`/Volumes/Kodi/Share/repositories/` holds a backup-install copy of the same
zips the site serves: the current `repository.tony7bones-<version>.zip` root
installer plus the hand-authored third-party installer zips from
`dropbox/repositories/`. Without this step it goes stale on every proxy
release (a stale `repository.tony7bones-1.0.5.zip` sat there pointing at the
long-dead `repo/` layout - it installed on a fresh box and then silently
served nothing).

`/Volumes/Kodi/Share/apps/` holds sideloadable copies of first-party add-on
zips - most importantly EZ Maintenance++, the RESTORE tool: a wiped box
sideloads it from this share to recover, so a stale copy there resurrects
exactly the backup/restore bugs later releases fixed. Membership is
OPT-IN-BY-PRESENCE: the owner curates WHICH add-ons belong by having any
version of them in the dir; the sync refreshes those to the current release
and prunes their superseded versions. It never adds add-ons on its own.

Contract (both dirs):

  * BEST-EFFORT, NEVER BLOCKS A RELEASE. `best_effort()` catches everything
    and only prints; a release must succeed identically whether the share is
    mounted, unmounted, or broken.
  * ONLY when the destination is available. If a share dir does not exist
    (volume not mounted), that sync is skipped with a note - nothing is
    created, no mount is attempted.
  * ADDITIVE for foreign files. Files on the share that are not ours are
    never touched (the owner curates extras there). The ONLY deletions are
    superseded versions of zips we own.
  * SANDBOX-SAFE by construction. The release system tests copy an
    explicit whitelist of _tools files into a sandbox repo; this module is
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
APPS_DIR = SHARE_ROOT + "/apps"

# Add-ons whose real source + installable release live in a SIBLING repo, kept
# here only as a metadata mirror (addon.xml + icon). The zip generate_repo.py
# builds for such an id is a tiny NON-INSTALLABLE stub, so sync_apps must never
# copy it into apps/ - a wiped box sideloading it would get a broken package.
# The real, current release zip is placed into apps/ by the kodishare-sync skill
# (which pulls the GitHub Release asset). script.ezmaintenanceplusplus is the
# restore tool: its source was extracted to moquette/ezmaintenanceplusplus on
# 2026-07-14, leaving the stub behind. Keep sync_apps and the skill from fighting
# over the same apps/ filename by owning it in exactly one place - the skill.
_RELEASE_MANAGED = frozenset({"script.ezmaintenanceplusplus"})

# Canvas asset dirs mirrored 1:1 (additive) to same-named share dirs. NOT
# iptv/ - the mini's populator daemon owns the share's iptv output.
CANVAS_ASSET_DIRS = ("media", "rss")

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


def _first_party_versions(repo_root: str) -> dict[str, str]:
    """{addon-id: current version} for every addons/<id>/addon.xml (not hosted)."""
    versions: dict[str, str] = {}
    addons = os.path.join(repo_root, "addons")
    if not os.path.isdir(addons):
        return versions
    for entry in sorted(os.listdir(addons)):
        xml = os.path.join(addons, entry, "addon.xml")
        if not os.path.isfile(xml):
            continue  # hosted/, packages/, loose files
        try:
            root = ET.parse(xml).getroot()
            aid, ver = root.get("id"), root.get("version")
            if aid and ver:
                versions[aid] = ver
        except ET.ParseError:
            continue
    return versions


def sync_apps(repo_root: str = REPO, apps_dir: str = APPS_DIR, dry_run: bool = False):
    """Refresh the sideload copies in apps_dir (opt-in-by-presence).

    For every first-party add-on that already has SOME `<id>-*.zip` in
    apps_dir, copy the current `<id>-<version>.zip` from the repo and prune
    that add-on's superseded versions. Add-ons with no zip present are never
    added; foreign files are never touched. Same action tuples as sync().
    """
    if not os.path.isdir(apps_dir):
        return [("unavailable", apps_dir)]

    actions: list[tuple[str, str]] = []
    existing = sorted(os.listdir(apps_dir))

    for aid, version in _first_party_versions(repo_root).items():
        if aid in _RELEASE_MANAGED:
            continue  # owned by the kodishare-sync skill; in-repo zip is a stub
        mine = [n for n in existing if n.startswith(aid + "-") and n.endswith(".zip")]
        if not mine:
            continue  # not opted in
        current = f"{aid}-{version}.zip"
        src = os.path.join(repo_root, "addons", aid, current)
        if not os.path.isfile(src):
            actions.append((f"error:no built zip for {aid} {version}", current))
            continue
        dst = os.path.join(apps_dir, current)
        try:
            if os.path.isfile(dst) and _sha256(dst) == _sha256(src):
                actions.append(("unchanged", current))
            else:
                if not dry_run:
                    shutil.copyfile(src, dst)
                actions.append(("copied", current))
        except OSError as exc:
            actions.append((f"error:{exc}", current))
            continue  # do not prune if the fresh copy did not land
        for name in mine:
            if name != current:
                try:
                    if not dry_run:
                        os.remove(os.path.join(apps_dir, name))
                    actions.append(("pruned", name))
                except OSError as exc:
                    actions.append((f"error:{exc}", name))

    return actions


def sync_canvas_assets(
    repo_root: str = REPO, share_root: str = SHARE_ROOT, dry_run: bool = False
):
    """Mirror the canvas asset dirs (media/, rss/) to same-named share dirs.

    STRICTLY ADDITIVE: these are unversioned filenames, so a changed file is
    overwritten but NOTHING is ever deleted (the share media/ held the old
    canvas image under its old name - it simply stays, alongside the fresh
    copies). A missing share subdir is skipped, never created. Same action
    tuples as sync().
    """
    actions: list[tuple[str, str]] = []
    for sub in CANVAS_ASSET_DIRS:
        src_dir = os.path.join(repo_root, "dropbox", sub)
        dst_dir = os.path.join(share_root, sub)
        if not os.path.isdir(dst_dir):
            actions.append(("unavailable", dst_dir))
            continue
        if not os.path.isdir(src_dir):
            continue
        for name in sorted(os.listdir(src_dir)):
            src = os.path.join(src_dir, name)
            if not os.path.isfile(src):
                continue
            dst = os.path.join(dst_dir, name)
            rel = f"{sub}/{name}"
            try:
                if os.path.isfile(dst) and _sha256(dst) == _sha256(src):
                    actions.append(("unchanged", rel))
                    continue
                if not dry_run:
                    shutil.copyfile(src, dst)
                actions.append(("copied", rel))
            except OSError as exc:
                actions.append((f"error:{exc}", rel))
    return actions


def best_effort(
    repo_root: str = REPO,
    share_dir: str = SHARE_DIR,
    apps_dir: str = APPS_DIR,
    share_root: str = SHARE_ROOT,
) -> None:
    """Run all syncs and only ever print - a release must never fail on the share."""
    try:
        _report(sync(repo_root, share_dir), share_dir)
        _report(sync_apps(repo_root, apps_dir), apps_dir)
        _report(sync_canvas_assets(repo_root, share_root), share_root + "/{media,rss}")
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
        description="Mirror installer/canvas/app zips to the Kodi share backup."
    )
    ap.add_argument(
        "--share", default=SHARE_DIR, help=f"repositories dir (default {SHARE_DIR})"
    )
    ap.add_argument("--apps", default=APPS_DIR, help=f"apps dir (default {APPS_DIR})")
    ap.add_argument(
        "--root",
        default=SHARE_ROOT,
        help=f"share root for media/rss (default {SHARE_ROOT})",
    )
    ap.add_argument(
        "--dry-run", action="store_true", help="report what would change, copy nothing"
    )
    args = ap.parse_args(argv)
    _report(sync(REPO, args.share, dry_run=args.dry_run), args.share)
    _report(sync_apps(REPO, args.apps, dry_run=args.dry_run), args.apps)
    _report(
        sync_canvas_assets(REPO, args.root, dry_run=args.dry_run),
        args.root + "/{media,rss}",
    )
    if args.dry_run:
        print("--dry-run: nothing was changed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
