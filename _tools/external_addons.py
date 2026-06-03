#!/usr/bin/env python3
"""Prototype: manifest-driven external Kodi add-ons (the "hybrid" model).

Borrows the declarative idea from ``i96751414/repository.github`` — describe an
add-on by its GitHub coordinates and let tooling resolve the version and zip
URL — but keeps Tony 7 Bones' *static* serving model. Instead of a runtime HTTP
server inside Kodi, we resolve at *generate time* and emit committed zips plus
``addons.xml`` entries, exactly like the in-tree add-ons.

This is OFF by default. It does nothing unless a manifest file exists and holds
entries, so ``generate_repo.py`` output stays byte-identical until someone opts
in by creating the manifest.

Manifest schema (see ``external-addons.example.json``):

    [
      {
        "id":          "plugin.video.example",   # required: Kodi add-on id
        "username":    "someuser",                # required: GitHub owner
        "repository":  "plugin.video.example",    # optional: defaults to id
        "tag_pattern": "v{version}",              # optional: how tags map to versions
        "asset_prefix": "https://raw.githubusercontent.com/{username}/{repository}/{ref}/",
        "assets": {
          "zip": "https://github.com/{username}/{repository}/releases/download/{tag}/{id}-{version}.zip"
        },
        "token": "ghp_..."                        # optional: for private repos
      }
    ]

Run a dry run (resolve + print, write nothing):

    python3 _tools/external_addons.py

Resolve, download zips into ``repo/<id>/`` and write per-addon indexes:

    python3 _tools/external_addons.py --write
"""

from __future__ import annotations

import argparse
import json
import os
import re
from dataclasses import dataclass
from typing import Callable
from xml.etree import ElementTree as ET

_HERE = os.path.abspath(os.path.dirname(__file__))
REPO_DIR = os.path.normpath(os.path.join(_HERE, "..", "repo"))
DEFAULT_MANIFEST = os.path.join(_HERE, "external-addons.json")

DEFAULT_ASSET_PREFIX = (
    "https://raw.githubusercontent.com/{username}/{repository}/{ref}/"
)
DEFAULT_ZIP_ASSET = (
    "https://github.com/{username}/{repository}/releases/download/{tag}/"
    "{id}-{version}.zip"
)

# Injected network functions: real implementations live in _urllib_fetchers().
TextFetcher = Callable[[str, dict], str]
BytesFetcher = Callable[[str, dict], bytes]


class _SafeDict(dict):
    """format_map helper that leaves unknown ``{placeholders}`` untouched."""

    def __missing__(self, key: str) -> str:
        return "{" + key + "}"


def _subst(template: str, **kw: str) -> str:
    return template.format_map(_SafeDict(**kw))


def _version_from_tag(tag: str, pattern: str | None) -> str:
    """Invert ``tag_pattern`` to extract a version from a release tag.

    With no pattern, strip a leading ``v`` (the common ``v1.2.3`` convention).
    """
    if pattern and "{version}" in pattern:
        regex = re.escape(pattern).replace(re.escape("{version}"), "(?P<version>.+)")
        m = re.fullmatch(regex, tag)
        if m:
            return m.group("version")
    return tag[1:] if tag.startswith("v") else tag


@dataclass
class ResolvedAddon:
    """An external add-on resolved to a concrete version, zip URL and metadata."""

    id: str
    version: str
    tag: str
    ref: str
    zip_url: str
    root: ET.Element  # the <addon> element to merge into addons.xml


class GitHubResolver:
    """Resolves manifest entries to concrete versions via the GitHub API.

    Network access is injected so the resolver is fully unit-testable offline.
    """

    def __init__(
        self,
        fetch_text: TextFetcher | None = None,
        fetch_bytes: BytesFetcher | None = None,
    ) -> None:
        real_text, real_bytes = _urllib_fetchers()
        self.fetch_text = fetch_text or real_text
        self.fetch_bytes = fetch_bytes or real_bytes

    @staticmethod
    def _headers(entry: dict) -> dict:
        token = entry.get("token")
        return {"Authorization": f"token {token}"} if token else {}

    def _latest_tag(self, entry: dict) -> str:
        user, repo = entry["username"], entry.get("repository", entry["id"])
        url = f"https://api.github.com/repos/{user}/{repo}/releases/latest"
        data = json.loads(self.fetch_text(url, self._headers(entry)))
        tag = data.get("tag_name")
        if not tag:
            raise ValueError(f"{entry['id']}: latest release has no tag_name")
        return tag

    def resolve(self, entry: dict) -> ResolvedAddon:
        if not entry.get("id") or not entry.get("username"):
            raise ValueError(f"manifest entry missing id/username: {entry!r}")

        addon_id = entry["id"]
        repository = entry.get("repository", addon_id)
        tag = self._latest_tag(entry)
        version = _version_from_tag(tag, entry.get("tag_pattern"))
        ref = tag  # a tag is a valid git ref for raw.githubusercontent.com

        subst = dict(
            id=addon_id,
            username=entry["username"],
            repository=repository,
            tag=tag,
            ref=ref,
            version=version,
        )
        asset_prefix = _subst(entry.get("asset_prefix", DEFAULT_ASSET_PREFIX), **subst)
        zip_template = entry.get("assets", {}).get("zip", DEFAULT_ZIP_ASSET)
        zip_url = _subst(zip_template, **subst)

        addon_xml = self.fetch_text(asset_prefix + "addon.xml", self._headers(entry))
        root = ET.fromstring(addon_xml)
        if root.get("id") != addon_id:
            raise ValueError(
                f"{addon_id}: remote addon.xml declares id={root.get('id')!r}"
            )
        return ResolvedAddon(addon_id, version, tag, ref, zip_url, root)


def load_manifest(path: str = DEFAULT_MANIFEST) -> list[dict]:
    """Return manifest entries, or an empty list if the manifest is absent."""
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    if not isinstance(data, list):
        raise ValueError(f"{path}: expected a JSON list of entries")
    return data


def process_external_addons(
    manifest: list[dict] | None = None,
    resolver: GitHubResolver | None = None,
    write: bool = False,
    repo_dir: str = REPO_DIR,
) -> tuple[list[ET.Element], list[str]]:
    """Resolve every manifest entry. Returns (addon roots, addon ids).

    With ``write=True`` the zip is downloaded into ``repo/<id>/`` and a
    Kodi-compatible per-addon ``index.html`` is written (reusing the in-tree
    helpers in ``generate_repo``). The empty-manifest case short-circuits before
    any network access, which is what keeps the default ``generate()`` output
    byte-identical.
    """
    entries = load_manifest() if manifest is None else manifest
    if not entries:
        return [], []

    resolver = resolver or GitHubResolver()
    roots: list[ET.Element] = []
    ids: list[str] = []
    for entry in entries:
        resolved = resolver.resolve(entry)
        if write:
            _write_external_zip(resolved, resolver, repo_dir)
        roots.append(resolved.root)
        ids.append(resolved.id)
        print(f"  + (external) {resolved.id} {resolved.version}  →  {resolved.tag}")
    return roots, ids


def _write_external_zip(
    resolved: ResolvedAddon, resolver: GitHubResolver, repo_dir: str
) -> None:
    """Download the resolved zip into repo/<id>/ and write its index.html."""
    # Imported lazily so this module stays importable without generate_repo.
    import generate_repo as gr

    addon_dir = os.path.join(repo_dir, resolved.id)
    os.makedirs(addon_dir, exist_ok=True)
    zip_name = f"{resolved.id}-{resolved.version}.zip"
    zip_path = os.path.join(addon_dir, zip_name)
    data = resolver.fetch_bytes(resolved.zip_url, {})
    with open(zip_path, "wb") as fh:
        fh.write(data)
    rows = [
        '<a href="../">Parent Directory</a>',
        f'<a href="{zip_name}">{zip_name}</a>  '
        f"{gr._fmt_date(zip_path)}  {gr._fmt_size(os.path.getsize(zip_path))}",
    ]
    gr._make_index(
        addon_dir, f"Index of /{os.path.relpath(addon_dir, os.path.dirname(repo_dir))}/", rows
    )


def _urllib_fetchers() -> tuple[TextFetcher, BytesFetcher]:
    """Real network fetchers backed by urllib (only used outside tests)."""
    import urllib.request

    def _open(url: str, headers: dict):
        req = urllib.request.Request(url, headers={"User-Agent": "tony7bones", **headers})
        return urllib.request.urlopen(req)  # noqa: S310 (https URLs only)

    def fetch_text(url: str, headers: dict) -> str:
        with _open(url, headers) as resp:
            return resp.read().decode("utf-8")

    def fetch_bytes(url: str, headers: dict) -> bytes:
        with _open(url, headers) as resp:
            return resp.read()

    return fetch_text, fetch_bytes


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--write",
        action="store_true",
        help="download zips and write per-addon indexes (default: dry run)",
    )
    parser.add_argument(
        "--manifest", default=DEFAULT_MANIFEST, help="path to the manifest JSON"
    )
    args = parser.parse_args()

    entries = load_manifest(args.manifest)
    if not entries:
        print(f"No manifest entries at {args.manifest} — nothing to do.")
        return

    roots, ids = process_external_addons(manifest=entries, write=args.write)
    mode = "wrote" if args.write else "resolved (dry run)"
    print(f"\n{mode} {len(ids)} external add-on(s): {', '.join(ids)}")


if __name__ == "__main__":
    main()
