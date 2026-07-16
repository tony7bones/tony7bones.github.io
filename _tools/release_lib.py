#!/usr/bin/env python3
"""Pure release logic: version math and file-content transforms.

No git, no filesystem, no network - every function is a pure transformation so
it can be exhaustively unit-tested.

Everything is served statically from `main` via GitHub Pages; there is no proxy
engine and no second branch. A release bumps one place - the add-on's
`addon.xml` version (and prepends a news line) - and CI builds and deploys the
static site on push.
"""

from __future__ import annotations

import re

# Single-digit-per-component version scheme: each of MAJOR.MINOR.PATCH is 0-9,
# with rollover on bump. This is deliberately NOT enforced inside parse_version
# (the live baseline is the legacy 1.0.14, and is_greater must keep comparing
# against it during the transition to 2.0.0). The rule lives only in the
# is_single_digit validator and the gates that call it.
MAX_COMPONENT = 9

_VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")
_ADDON_VERSION_RE = re.compile(r'(<addon\b[^>]*?\bversion=")([^"]*)(")')
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
    locked default level is MINOR. Keeping the math here means the tool never
    re-implements version arithmetic - single source of truth (single-digit
    rollover, 9.9.9 ceiling) stays in ``bump``.
    """
    return bump(current, level)


def is_greater(new: str, old: str) -> bool:
    """True iff `new` is strictly greater than `old`. Enforces 'every deploy bumps'."""
    return parse_version(new) > parse_version(old)


_LOOSE_VERSION_RE = re.compile(r"^\d+(\.\d+)*$")


def parse_version_loose(s: str) -> tuple[int, ...]:
    """Parse an arbitrary-length dotted numeric version (e.g. a legacy
    date-stamped scheme like 2026.07.01.1) into a comparable tuple. Raises
    ValueError on anything that isn't purely dot-separated digits."""
    if not isinstance(s, str) or not _LOOSE_VERSION_RE.match(s.strip()):
        raise ValueError(f"invalid version: {s!r}")
    return tuple(int(x) for x in s.strip().split("."))


def validate_version_for_write(version: str) -> None:
    """Accept anything a write-only helper (set_addon_version,
    prepend_addon_news) may legitimately be asked to write: a proper 3
    component X.Y.Z (parse_version - any magnitude, e.g. modv2plus's real
    1.4.10) OR a legacy 4+-component scheme (EZ Maintenance++'s real
    date-stamped 2026.07.02.0). Rejects anything with FEWER than 3
    components either way - an incomplete version like "1.9" is never a
    valid write target, single-digit scheme or not. The strict single-digit
    RULE itself is a gate concern (preflight/script_consistency, already run
    before any of these write helpers), not this check's job."""
    try:
        parse_version(version)
        return
    except ValueError:
        pass
    parts = parse_version_loose(version)  # raises ValueError on real garbage
    if len(parts) < 3:
        raise ValueError(f"invalid version: {version!r}")


def is_greater_loose(new: str, old: str) -> bool:
    """True iff `new` is strictly greater than `old`, comparing dotted numeric
    versions of ANY length component-wise (this is how Kodi's own AddonVersion
    compares them too). For add-ons that predate the single-digit X.Y.Z scheme
    and must keep their own real, Kodi-comparable version lineage - forcing
    those onto single-digit X.Y.Z would look like a downgrade to every box
    (2026.07.01.1 > 9.9.9 under Kodi's own comparison) and updates would
    silently stop landing."""
    return parse_version_loose(new) > parse_version_loose(old)


# --------------------------------------------------------------------------- #
# File-content transforms (take text, return text)
# --------------------------------------------------------------------------- #
def read_addon_version(xml_text: str) -> str:
    m = _ADDON_VERSION_RE.search(xml_text)
    if not m:
        raise ValueError("no <addon ... version=...> found")
    return m.group(2)


def set_addon_version(xml_text: str, version: str) -> str:
    # Single-digit-per-component enforcement belongs at the gate
    # (preflight/script_consistency), which already ran before this is ever
    # called - this just guards against a structurally malformed value.
    validate_version_for_write(version)
    new, n = _ADDON_VERSION_RE.subn(
        lambda m: m.group(1) + version + m.group(3), xml_text, count=1
    )
    if n != 1:
        raise ValueError("could not set <addon version>")
    return new


def prepend_addon_news(
    xml_text: str, news_line: str, *, version: str, cap: int = NEWS_CAP
) -> str:
    """Prepend ``vX.Y.Z: <news_line>`` to the <news> body, keeping a rolling cap.

    Keeps a bounded rolling changelog: one entry per line, newest first, at most
    ``cap`` entries. This is the locked O3 model for the release tool.

    Idempotent (MF-9): if the top entry already begins with ``vX.Y.Z:`` for the
    version being shipped, the body is returned unchanged - a re-run does not stack a
    duplicate. Existing entries are split on newlines (each non-blank line is one
    historical entry); the indentation of the manifests in this repo (8 spaces) is
    preserved.
    """
    # Single-digit-per-component enforcement belongs at the gate, same
    # reasoning as set_addon_version - this just guards against a
    # structurally malformed value.
    validate_version_for_write(version)
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
    indent = "        "  # 8 spaces - matches this repo's manifests
    body = "\n" + "\n".join(f"{indent}{e}" for e in entries) + "\n" + indent
    return _NEWS_RE.sub(lambda mm: mm.group(1) + body + mm.group(3), xml_text, count=1)
