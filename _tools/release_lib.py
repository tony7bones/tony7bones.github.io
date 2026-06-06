#!/usr/bin/env python3
"""Pure release logic: version math and file-content transforms.

No git, no filesystem, no network — every function is a pure transformation so
it can be exhaustively unit-tested. Every version-bearing location in a release
is derived from a single version string (see DeployPlan), which makes version
drift across the (now four) locations structurally impossible.

Single-branch model: the proxy fetches everything from `main`. The proxy's
self-update version source is the canonical `repo/repository.tony7bones/addon.xml`
itself (the manifest's repository.tony7bones entry points its asset_prefix at
`.../main/repo/repository.tony7bones/`), so there is no longer a separate
`hosted/repository.tony7bones/addon.xml` on a second branch. The four
version-bearing locations are: main addon.xml, root zip filename, root
index.html link, and the git tag.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

ADDON_ID = "repository.tony7bones"

_VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")
_ADDON_VERSION_RE = re.compile(r'(<addon\b[^>]*?\bversion=")([^"]*)(")')
_ZIP_RE = re.compile(re.escape(ADDON_ID) + r"-(\d+\.\d+\.\d+)\.zip")
_NEWS_RE = re.compile(r"(<news>)(.*?)(</news>)", re.DOTALL)


# --------------------------------------------------------------------------- #
# Version math
# --------------------------------------------------------------------------- #
def parse_version(s: str) -> tuple[int, int, int]:
    """Parse 'X.Y.Z' into a comparable tuple. Raises ValueError on anything else."""
    if not isinstance(s, str) or not _VERSION_RE.match(s.strip()):
        raise ValueError(f"invalid version: {s!r}")
    a, b, c = (int(x) for x in s.strip().split("."))
    return (a, b, c)


def format_version(parts: tuple[int, int, int]) -> str:
    return ".".join(str(x) for x in parts)


def bump(version: str, level: str = "patch") -> str:
    """Return the next version after `version` at the given level."""
    a, b, c = parse_version(version)
    if level == "patch":
        return format_version((a, b, c + 1))
    if level == "minor":
        return format_version((a, b + 1, 0))
    if level == "major":
        return format_version((a + 1, 0, 0))
    raise ValueError(f"unknown bump level: {level!r}")


def is_greater(new: str, old: str) -> bool:
    """True iff `new` is strictly greater than `old`. Enforces 'every deploy bumps'."""
    return parse_version(new) > parse_version(old)


def zip_name(version: str) -> str:
    parse_version(version)  # validate
    return f"{ADDON_ID}-{version}.zip"


def version_from_zip_name(name: str) -> str:
    m = _ZIP_RE.search(name)
    if not m:
        raise ValueError(f"not a {ADDON_ID} zip name: {name!r}")
    return m.group(1)


def tag_name(version: str) -> str:
    parse_version(version)
    return f"v{version}"


def stale_root_zips(filenames, keep_version: str) -> list[str]:
    """Given root-dir filenames, return the repository.tony7bones-*.zip names to
    remove: every versioned installer zip except the one for ``keep_version``.

    The install URL is the repo root and Kodi installs whatever filename
    index.html links to, so only the current zip is ever needed at the root;
    older versioned zips are pure clutter in the Kodi file-manager listing.
    """
    keep = zip_name(keep_version)
    out = []
    for name in filenames:
        if name == keep:
            continue
        if _ZIP_RE.fullmatch(name):
            out.append(name)
    return out


# --------------------------------------------------------------------------- #
# File-content transforms (take text, return text)
# --------------------------------------------------------------------------- #
def read_addon_version(xml_text: str) -> str:
    m = _ADDON_VERSION_RE.search(xml_text)
    if not m:
        raise ValueError("no <addon ... version=...> found")
    return m.group(2)


def set_addon_version(xml_text: str, version: str) -> str:
    parse_version(version)
    new, n = _ADDON_VERSION_RE.subn(
        lambda m: m.group(1) + version + m.group(3), xml_text, count=1
    )
    if n != 1:
        raise ValueError("could not set <addon version>")
    return new


def set_addon_news(xml_text: str, news_line: str) -> str:
    """Replace the <news> body with a single changelog line.

    NOTE: this REPLACES the entire <news> block with one line (8-space indent,
    matching this repo's manifests). It does not prepend to a multi-line
    changelog history. That is intentional for this single-line-news repo; if a
    rolling changelog is ever wanted, change this to prepend instead.
    """
    if not _NEWS_RE.search(xml_text):
        raise ValueError("no <news> block found")
    body = f"\n{news_line}\n        "
    return _NEWS_RE.sub(lambda m: m.group(1) + body + m.group(3), xml_text, count=1)


def version_from_index(html_text: str) -> str:
    m = _ZIP_RE.search(html_text)
    if not m:
        raise ValueError("no repository zip link found in index.html")
    return m.group(1)


def rewrite_index_link(html_text: str, version: str) -> str:
    """Rewrite every occurrence of the repo zip name (href AND link text) to `version`."""
    new_zip = zip_name(version)
    new, n = _ZIP_RE.subn(lambda m: new_zip, html_text)
    if n == 0:
        raise ValueError("no repository zip link to rewrite")
    return new


# --------------------------------------------------------------------------- #
# The single source of truth for a release
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class DeployPlan:
    """All four version-bearing locations derived from ONE version string.

    There is deliberately no way to set the four locations independently —
    this collapses an entire class of version-drift bugs into a single input.

    Single-branch model: the proxy's self-update source is the canonical main
    addon.xml itself, so there is no separate hosted self-update addon.xml. The
    four locations are: main addon.xml, root zip filename, root index.html link,
    and the git tag.
    """

    version: str

    def __post_init__(self) -> None:
        parse_version(self.version)  # fail fast on a bad version

    @property
    def main_addon_version(self) -> str:
        return self.version

    @property
    def root_zip(self) -> str:
        return zip_name(self.version)

    @property
    def index_version(self) -> str:
        return self.version

    @property
    def tag(self) -> str:
        return tag_name(self.version)

    def all_versions(self) -> dict[str, str]:
        """The version observed at each location — used to prove consistency."""
        return {
            "main_addon": self.main_addon_version,
            "root_zip": version_from_zip_name(self.root_zip),
            "index": self.index_version,
            "tag": self.tag[1:],
        }

    def is_consistent(self) -> bool:
        return len(set(self.all_versions().values())) == 1
