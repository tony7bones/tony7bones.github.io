#!/usr/bin/env python3
"""Bump every hosted GitHub-Releases mirror to its source repo's latest release.

THE GAP this closes: releasing is not publishing. A source repo (today only
``moquette/kodi-ezmpp`` -> ``addons/hosted/script.ezmaintenanceplusplus``)
tags and publishes a release in CI, but the fleet reads the MIRROR's
``addon.xml`` version, and that bump was hand-done. Forgotten, it serves a
stale build forever with no error anywhere; ``check_hosted_release_sync.py``
turns that into a red build after a 2h grace window, but red is still not
fixed. On 2026-09-26 the mirror had been nine days behind 2026.09.17.1.

TWO KINDS of mirror are followed, and both are discovered from
``_tools/catalog.json`` so a future add-on of either shape is covered with no
code change:

  * GitHub-Releases mirrors (``check_hosted_release_sync.hosted_release_entries``,
    the same discovery as the gate): the source repo's LATEST release is the
    truth. Today ``script.ezmaintenanceplusplus`` -> ``moquette/kodi-ezmpp``.
  * Upstream-indexed mirrors: any hosted entry carrying an ``upstream_index``
    URL, a Kodi ``addons.xml`` published by the upstream repository. The
    version that index declares for the add-on is the truth. Today
    ``plugin.video.pov`` -> ``kodiyashimaru.github.io/repo/packages/addons.xml``.
    Before this, the mirror's version was typed by hand and rotted the moment
    upstream moved: on 2026-09-26 it said 6.08.15 against an upstream 6.09.06,
    the zip 404ed, the build DROPPED POV from the catalog, and the skin that
    hard-depends on it could not install. Hard-coded versions are the bug.

WHAT IT DOES, per mirror:

  1. Ask the source repo for its latest release.
  2. If the mirror already declares that version, do nothing.
  3. Otherwise download the release's asset zip (the exact filename the
     catalog template would build), pull ``<id>/addon.xml`` out of it, and
     write that file over the mirror's ``addon.xml``. The mirror is by
     definition the published add-on's own manifest (version, news, assets,
     dependencies), so the whole file is copied, never patched line by line.

Never downgrades: a mirror declaring a HIGHER version than the latest release
is left alone and reported, because that is the broken-pointer case the gate
hard-fails on and a human must look at.

Exit status is 0 whether or not anything changed; ``--dry-run`` reports
without writing. When ``GITHUB_OUTPUT`` is set, ``bumped=<space-separated
"id=version" list>`` (empty when nothing changed) is appended for the
workflow to branch on. Any API or download failure exits 1 loudly: a sync
that silently did nothing is the failure mode this tool exists to kill.

Run by ``.github/workflows/sync_hosted_mirror.yml`` on every ``ezmpp-release``
dispatch, daily, and by hand.
"""

from __future__ import annotations

import argparse
import io
import json
import os
import sys
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
import zipfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import check_hosted_release_sync as gate  # noqa: E402
import release_lib as rl  # noqa: E402


class SyncError(Exception):
    """A step that must not fail silently did fail."""


def _fetch_bytes(url: str, token: str | None) -> bytes:
    headers = {"User-Agent": "tony7bones-hosted-mirror-sync"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:  # noqa: S310 (https only)
            return resp.read()
    except urllib.error.HTTPError as e:
        raise SyncError(f"download {url} failed: HTTP {e.code}") from e
    except urllib.error.URLError as e:
        raise SyncError(f"download {url} unreachable: {e}") from e


def addon_xml_from_zip(zip_bytes: bytes, addon_id: str) -> str:
    """The ``<id>/addon.xml`` inside a Kodi add-on zip, as text."""
    member = f"{addon_id}/addon.xml"
    try:
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
            return zf.read(member).decode("utf-8")
    except KeyError as e:
        raise SyncError(f"release zip has no {member}") from e
    except zipfile.BadZipFile as e:
        raise SyncError("release asset is not a zip") from e


def latest_version(owner: str, repo: str, token: str | None) -> tuple[str, dict]:
    latest = gate.get_latest_release(owner, repo, token)
    if latest is None:
        raise SyncError(f"{owner}/{repo} has no published releases")
    tag = latest.get("tag_name") or ""
    return (tag[1:] if tag.startswith("v") else tag), latest


def upstream_indexed_entries(repo_root: str = gate.REPO_ROOT) -> list[dict]:
    """Every ``addons/hosted/<id>`` mirror whose catalog entry names an
    ``upstream_index`` (a Kodi addons.xml published by the upstream repo)."""
    with open(os.path.join(repo_root, "_tools", "catalog.json"), encoding="utf-8") as fh:
        data = json.load(fh)
    out = []
    for entry in data:
        addon_id, index = entry.get("id"), entry.get("upstream_index")
        if not addon_id or not index:
            continue
        addon_xml = os.path.join(repo_root, "addons", "hosted", addon_id, "addon.xml")
        if not os.path.isfile(addon_xml):
            continue
        out.append(
            {
                "id": addon_id,
                "index": index,
                "zip_template": (entry.get("assets") or {}).get("zip", ""),
                "addon_xml": addon_xml,
            }
        )
    return sorted(out, key=lambda e: e["id"])


def version_in_index(index_xml: bytes, addon_id: str) -> str:
    try:
        root = ET.fromstring(index_xml)
    except ET.ParseError as e:
        raise SyncError(f"upstream index is not XML: {e}") from e
    for node in root.iter("addon"):
        if node.get("id") == addon_id:
            version = node.get("version")
            if version:
                return version
    raise SyncError(f"upstream index does not list {addon_id}")


def sync_indexed_entry(
    entry: dict,
    token: str | None,
    *,
    dry_run: bool = False,
    fetch=None,
) -> tuple[str | None, str]:
    """Sync one upstream-indexed mirror. Returns (new_version_or_None, message)."""
    fetch = fetch or _fetch_bytes
    addon_id = entry["id"]
    with open(entry["addon_xml"], encoding="utf-8") as fh:
        current = rl.read_addon_version(fh.read())

    newest = version_in_index(fetch(entry["index"], None), addon_id)
    if newest == current:
        return None, f"{addon_id}: mirror {current} already matches upstream index"
    if _version_tuple(newest) < _version_tuple(current):
        return None, (
            f"{addon_id}: mirror declares {current} but upstream index says {newest}; "
            f"not downgrading"
        )

    url = entry["zip_template"].format(id=addon_id, version=newest)
    xml = addon_xml_from_zip(fetch(url, None), addon_id)
    packaged = rl.read_addon_version(xml)
    if packaged != newest:
        raise SyncError(
            f"{addon_id}: upstream zip for {newest} ships an addon.xml declaring {packaged}"
        )
    if not dry_run:
        with open(entry["addon_xml"], "w", encoding="utf-8") as fh:
            fh.write(xml)
    verb = "would bump" if dry_run else "bumped"
    return newest, f"{addon_id}: {verb} mirror {current} -> {newest} from {url}"


def _version_tuple(v: str) -> tuple[int, ...]:
    try:
        return tuple(int(p) for p in v.split("."))
    except ValueError:
        return (0,)


def sync_entry(
    entry: dict,
    token: str | None,
    *,
    dry_run: bool = False,
    fetch=None,
) -> tuple[str | None, str]:
    """Sync one mirror. Returns (new_version_or_None, message)."""
    addon_id, owner, repo = entry["id"], entry["owner"], entry["repo"]
    with open(entry["addon_xml"], encoding="utf-8") as fh:
        current = rl.read_addon_version(fh.read())

    newest, release = latest_version(owner, repo, token)
    if newest == current:
        return None, f"{addon_id}: mirror {current} already matches latest release"
    if _version_tuple(newest) < _version_tuple(current):
        return None, (
            f"{addon_id}: mirror declares {current} but latest release is {newest}; "
            f"not downgrading, the freshness gate will flag this"
        )

    asset_name = entry["asset_template"].format(id=addon_id, version=newest)
    urls = {a.get("name"): a.get("browser_download_url") for a in release.get("assets", [])}
    url = urls.get(asset_name)
    if not url:
        raise SyncError(
            f"{addon_id}: release v{newest} on {owner}/{repo} has no asset {asset_name!r} "
            f"(has: {sorted(n for n in urls if n)})"
        )

    xml = addon_xml_from_zip((fetch or _fetch_bytes)(url, token), addon_id)
    packaged = rl.read_addon_version(xml)
    if packaged != newest:
        raise SyncError(
            f"{addon_id}: release v{newest} ships an addon.xml declaring {packaged}"
        )

    if not dry_run:
        with open(entry["addon_xml"], "w", encoding="utf-8") as fh:
            fh.write(xml)
    verb = "would bump" if dry_run else "bumped"
    return newest, f"{addon_id}: {verb} mirror {current} -> {newest} from {url}"


def sync(
    repo_root: str = gate.REPO_ROOT,
    token: str | None = None,
    *,
    dry_run: bool = False,
    fetch=None,
) -> tuple[list[tuple[str, str]], list[str]]:
    """Sync every mirror. Returns ([(id, new_version), ...], messages)."""
    bumped: list[tuple[str, str]] = []
    messages: list[str] = []
    for entry in gate.hosted_release_entries(repo_root):
        new, msg = sync_entry(entry, token, dry_run=dry_run, fetch=fetch)
        messages.append(msg)
        if new:
            bumped.append((entry["id"], new))
    for entry in upstream_indexed_entries(repo_root):
        new, msg = sync_indexed_entry(entry, token, dry_run=dry_run, fetch=fetch)
        messages.append(msg)
        if new:
            bumped.append((entry["id"], new))
    return bumped, messages


def write_github_output(bumped: list[tuple[str, str]]) -> None:
    path = os.environ.get("GITHUB_OUTPUT")
    if not path:
        return
    value = " ".join(f"{i}={v}" for i, v in bumped)
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(f"bumped={value}\n")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dry-run", action="store_true", help="report, write nothing")
    args = ap.parse_args(argv)

    print("hosted-mirror sync:")
    try:
        bumped, messages = sync(token=gate.gh_token(), dry_run=args.dry_run)
    except (SyncError, gate.GateError) as e:
        print(f"  ERROR: {e}", file=sys.stderr)
        return 1
    for m in messages:
        print(f"  {m}")
    if not args.dry_run:
        write_github_output(bumped)
    print(
        (f"{len(bumped)} mirror(s) " + ("to bump" if args.dry_run else "bumped"))
        if bumped
        else "nothing to do, every mirror is current"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
