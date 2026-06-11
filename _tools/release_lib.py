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

# Single-digit-per-component version scheme: each of MAJOR.MINOR.PATCH is 0-9,
# with rollover on bump. This is deliberately NOT enforced inside parse_version
# (the live baseline is the legacy 1.0.14, and is_greater must keep comparing
# against it during the transition to 2.0.0). The rule lives only in the
# is_single_digit validator and the gates that call it.
MAX_COMPONENT = 9

_VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")
_ADDON_VERSION_RE = re.compile(r'(<addon\b[^>]*?\bversion=")([^"]*)(")')
_ZIP_RE = re.compile(re.escape(ADDON_ID) + r"-(\d+\.\d+\.\d+)\.zip")
_NEWS_RE = re.compile(r"(<news>)(.*?)(</news>)", re.DOTALL)

# Default rolling-history cap for the prepend-mode news (O3: keep ~6 entries).
NEWS_CAP = 6


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


def is_single_digit(version: str) -> bool:
    """True iff `version` parses AND every component is 0-9 (<= MAX_COMPONENT).

    parse_version stays lenient (it accepts 1.0.14); the single-digit rule is
    enforced only here and at the gates that call this.
    """
    try:
        parts = parse_version(version)
    except (ValueError, TypeError):
        return False
    return all(c <= MAX_COMPONENT for c in parts)


def bump(version: str, level: str = "patch") -> str:
    """Return the next version after `version` at the given level, with rollover.

    Each component is kept in 0-9: a patch carry rolls into minor, a minor carry
    rolls into major. Overflowing major (past 9.9.9) exhausts the version space
    and raises ValueError.
    """
    a, b, c = parse_version(version)
    if level == "patch":
        c += 1
        if c > MAX_COMPONENT:
            c = 0
            b += 1
        if b > MAX_COMPONENT:
            b = 0
            a += 1
    elif level == "minor":
        b += 1
        c = 0
        if b > MAX_COMPONENT:
            b = 0
            a += 1
    elif level == "major":
        a += 1
        b = 0
        c = 0
    else:
        raise ValueError(f"unknown bump level: {level!r}")
    if a > MAX_COMPONENT:
        raise ValueError(
            f"version ceiling reached: cannot bump {version!r} past 9.9.9 "
            "(single-digit version space exhausted)"
        )
    return format_version((a, b, c))


def next_version(current: str, level: str = "minor") -> str:
    """Compute the next version from `current` at `level`.

    A thin, explicitly-named alias over ``bump`` for the release tool, whose
    locked default level is MINOR (the proxy's ``deploy.py`` keeps its own PATCH
    default by calling ``bump`` directly). Keeping the math here means the tool
    never re-implements version arithmetic — single source of truth (single-digit
    rollover, 9.9.9 ceiling) stays in ``bump``.
    """
    return bump(current, level)


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


def prepend_addon_news(
    xml_text: str, news_line: str, *, version: str, cap: int = NEWS_CAP
) -> str:
    """Prepend ``vX.Y.Z: <news_line>`` to the <news> body, keeping a rolling cap.

    Unlike ``set_addon_news`` (which REPLACES the body with one line — the proxy's
    ``deploy.py`` behaviour), this keeps a bounded rolling changelog: one entry per
    line, newest first, at most ``cap`` entries. This is the locked O3 model for the
    script.* release tool.

    Idempotent (MF-9): if the top entry already begins with ``vX.Y.Z:`` for the
    version being shipped, the body is returned unchanged — a re-run does not stack a
    duplicate. Existing entries are split on newlines (each non-blank line is one
    historical entry); the indentation of the manifests in this repo (8 spaces) is
    preserved.
    """
    parse_version(version)
    m = _NEWS_RE.search(xml_text)
    if not m:
        raise ValueError("no <news> block found")

    new_entry = f"v{version}: {news_line}"
    existing = [ln.strip() for ln in m.group(2).splitlines() if ln.strip()]

    # Idempotency: a re-run for the SAME version must not re-prepend.
    prefix = f"v{version}:"
    if existing and existing[0].startswith(prefix):
        return xml_text

    entries = [new_entry, *existing][:cap]
    indent = "        "  # 8 spaces — matches this repo's manifests
    body = "\n" + "\n".join(f"{indent}{e}" for e in entries) + "\n" + indent
    return _NEWS_RE.sub(lambda mm: mm.group(1) + body + mm.group(3), xml_text, count=1)


# Matches the version= of an <import addon="ID" ... version="..."/>. Both repos'
# manifests put addon= before version=; the second alternative keeps it correct
# if a future manifest reverses the attribute order (version= before addon=).
_IMPORT_RE_TMPL = (
    r'(<import\b[^>]*?\baddon="{addon_id}"[^>]*?\bversion=")([^"]*)(")'
    r'|(<import\b[^>]*?\bversion=")([^"]*)("[^>]*?\baddon="{addon_id}")'
)


def _import_re(addon_id: str) -> re.Pattern:
    return re.compile(_IMPORT_RE_TMPL.format(addon_id=re.escape(addon_id)))


def _import_match_version(m: re.Match) -> str:
    """The captured version= regardless of which attribute-order alternative hit."""
    return m.group(2) if m.group(2) is not None else m.group(5)


def read_import_version(xml_text: str, addon_id: str) -> str | None:
    """Return the ``version=`` of the ``<import addon="addon_id" .../>``, or None.

    Used to read the lockstep target (bootstrap's import of the shared library).
    Returns None when the add-on is not imported at all (the import is absent),
    distinguishing "not a dependency" from a present-but-stale pin.
    """
    m = _import_re(addon_id).search(xml_text)
    return _import_match_version(m) if m else None


def set_import_version(xml_text: str, addon_id: str, version: str) -> str:
    """Rewrite the ``version=`` of ``<import addon="addon_id" .../>`` (the lockstep).

    Mirrors ``set_addon_version`` for the dependency import. Only the matching
    import is touched — other ``<import>`` lines (xbmc.python, xbmc.addon, a second
    dependency) are left byte-for-byte unchanged. Idempotent: setting the version it
    already holds is a no-op. Raises ValueError if ``addon_id`` is not imported, so a
    caller never silently believes it raised a lockstep that does not exist.
    """
    parse_version(version)

    def _repl(m: re.Match) -> str:
        if m.group(2) is not None:  # addon= before version=
            return m.group(1) + version + m.group(3)
        return m.group(4) + version + m.group(6)  # version= before addon=

    new, n = _import_re(addon_id).subn(_repl, xml_text, count=1)
    if n != 1:
        raise ValueError(f"no <import addon={addon_id!r} version=...> found to set")
    return new


def is_root_zip_name(name: str) -> bool:
    """True if `name` is a root proxy installer zip (repository.tony7bones-X.Y.Z.zip).

    The release-consistency gate reads the shipped version from THIS filename — the
    zip is served at the repo root for the proxy self-update — because the root
    index.html is the bare-URL canvas listing and no longer carries a zip link.
    """
    return bool(_ZIP_RE.fullmatch(name))


# --------------------------------------------------------------------------- #
# The single source of truth for a release
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class DeployPlan:
    """All three version-bearing locations derived from ONE version string.

    There is deliberately no way to set the locations independently — this
    collapses an entire class of version-drift bugs into a single input.

    Single-branch model: the proxy's self-update source is the canonical main
    addon.xml itself, so there is no separate hosted self-update addon.xml. The
    three locations are: main addon.xml, the root zip filename, and the git tag.
    (The root index.html is the bare-URL canvas listing and no longer carries a
    zip link — the install zip is browsed from the served repositories/ folder.)
    """

    version: str

    def __post_init__(self) -> None:
        parse_version(self.version)  # fail fast on a bad version
        if not is_single_digit(self.version):
            raise ValueError(
                f"version {self.version!r} is not single-digit "
                "(each of MAJOR.MINOR.PATCH must be 0-9)"
            )

    @property
    def main_addon_version(self) -> str:
        return self.version

    @property
    def root_zip(self) -> str:
        return zip_name(self.version)

    @property
    def tag(self) -> str:
        return tag_name(self.version)

    def all_versions(self) -> dict[str, str]:
        """The version observed at each location — used to prove consistency."""
        return {
            "main_addon": self.main_addon_version,
            "root_zip": version_from_zip_name(self.root_zip),
            "tag": self.tag[1:],
        }

    def is_consistent(self) -> bool:
        return len(set(self.all_versions().values())) == 1
