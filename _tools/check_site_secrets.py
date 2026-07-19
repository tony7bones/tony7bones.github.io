#!/usr/bin/env python3
"""Secret gate for the CI-BUILT site artifact (_site/), pre-deploy.

test_secret_leak.py guards the TRACKED tree and publish_canvas.py guards
staged canvas additions; this gate guards the third surface the static
conversion introduces: the _site/ tree assembled in CI (which includes
content DOWNLOADED at build time - third-party zips, upstream metadata) just
before it is deployed to public GitHub Pages. A build whose artifact carries
a credential must die here, never deploy.

Two checks, mirroring test_secret_leak.py's rules onto the artifact:

1. STRUCTURAL: no secret-bearing artifact may exist at any path - any
   ``*.env`` / ``.env*`` file (except the placeholder examples), any
   ``*.m3u``/``*.m3u8`` playlist, any ``iptv-build`` directory, and any
   ``instance-settings*.xml`` (the pvr.iptvsimple config carries provider
   credentials by construction).
2. CONTENT: every text file in SERVED content dirs is scanned line-by-line
   against the shared credential patterns (secret_patterns.py). Source dirs
   that ride along in the artifact (_tools/, docs/, .github/) are exempt:
   they are covered by test_secret_leak.py on the tracked tree, and the
   pattern definitions themselves live there.

Usage:
    python3 _tools/check_site_secrets.py _site
Exit 0 = clean, 1 = findings (each printed), 2 = usage error.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from secret_patterns import ALLOW_FILES, SECRET_PATTERNS  # noqa: E402

# NOTE: _SOURCE_DIRS was deleted 2026-07-18. It exempted _tools, docs, .github,
# .githooks and .claude from the CONTENT scan, back when those trees rode along
# in the artifact. Since the publish allowlist they cannot appear at all, so the
# exemption bought nothing and failed OPEN: the day anyone adds "docs" to
# _PUBLISH_DIRS to publish user documentation, that content would ship AND be
# silently exempt from the credential scan, in one line, with no test failing.
# Everything that reaches the artifact is now scanned.

# Only these extensions are content-scanned (binary formats are skipped; zips
# are covered by the structural rules on what may exist at all).
_TEXT_EXTS = {
    ".xml",
    ".txt",
    ".json",
    ".html",
    ".htm",
    ".md",
    ".cfg",
    ".ini",
    ".yml",
    ".yaml",
    ".properties",
    ".css",
}

_MAX_SCAN_BYTES = 4 * 1024 * 1024


# PUBLISH ALLOWLIST. Nothing tracked reaches the public artifact unless it is
# named here.
#
# Inverted from a denylist on 2026-07-18. An audit found fleet LAN addresses in
# 17 tracked files, 39 occurrences in one playbook alone, all published, along
# with agent skills, adb runbooks, NFS export layouts and incident narratives.
# A denylist was written first and an adversarial review enumerated bypasses in
# one pass: case variants (`docs/Playbooks/`), nested copies (`x/_tools/`),
# `ALLOW_FILES` short-circuiting ahead of the rules, and any newly added
# internal doc publishing by default.
#
# The point of the inversion is the failure mode. A denylist fails toward
# "a new internal file was published", which nobody notices. An allowlist fails
# toward "a public file is missing", which someone notices immediately.
#
# Generated content (the canvas mirror, /static/, the root index and installer)
# is produced AFTER this filter and is unaffected by it.
_PUBLISH_DIRS = (
    "addons",  # the add-on payloads this repository exists to serve
    "images",  # site imagery
    "dropbox",  # source for the generated canvas mirror
)
_PUBLISH_FILES = (
    "README.md",  # the public face of the repository
    "style.css",
    ".nojekyll",
    "package.json",
)


def publish_refusal(relpath: str) -> str | None:
    """Return a reason when a TRACKED file must not be copied into the artifact.

    Allowlist: anything not explicitly published is refused, whatever it is
    called and wherever it sits. Used by build_site.copy_tracked_tree only.

    This is deliberately NOT the same function scan_site uses. scan_site walks
    the BUILT artifact, which is mostly generated content (the canvas mirror,
    /static/, the root index) that never passes through here, so applying an
    allowlist there would refuse the site's own output.
    """
    # normpath already collapses a leading "./"; do NOT lstrip("./") here, that
    # strips a CHARACTER SET and would turn ".nojekyll" into "nojekyll",
    # silently mangling every dotfile.
    norm = os.path.normpath(relpath).replace(os.sep, "/")
    lower = norm.lower()
    parts = [p for p in lower.split("/") if p]
    base = os.path.basename(norm)
    if not parts:
        return "empty path"
    if parts[0] not in [d.lower() for d in _PUBLISH_DIRS]:
        if len(parts) > 1 or base not in _PUBLISH_FILES:
            return "not on the publish allowlist"
    # Specific rules still apply inside the published set.
    return _structural_violation(relpath)


def _structural_violation(relpath: str) -> str | None:
    """Structural rules that hold anywhere, including in generated output."""
    base = os.path.basename(relpath)
    parts = relpath.replace(os.sep, "/").split("/")
    if "iptv-build" in parts:
        return "iptv-build artifact"
    if base in ALLOW_FILES:
        return None
    if base.startswith(".env") or base.endswith(".env"):
        return "env file"
    if base.endswith((".m3u", ".m3u8")):
        return "m3u playlist"
    if base.startswith("instance-settings") and base.endswith(".xml"):
        return "pvr instance settings"
    return None


def scan_site(site_dir: str) -> list[tuple[str, str]]:
    """Return (relpath, finding) for every violation in the built site."""
    findings: list[tuple[str, str]] = []
    site_dir = os.path.abspath(site_dir)
    for dirpath, dirnames, filenames in os.walk(site_dir):
        rel_dir = os.path.relpath(dirpath, site_dir)
        dirnames.sort()
        for fname in sorted(filenames):
            relpath = os.path.normpath(os.path.join(rel_dir, fname))
            struct = _structural_violation(relpath)
            if struct:
                findings.append((relpath, struct))
                continue
            if os.path.splitext(fname)[1].lower() not in _TEXT_EXTS:
                continue
            if os.path.basename(fname) in ALLOW_FILES:
                continue
            fpath = os.path.join(dirpath, fname)
            if os.path.getsize(fpath) > _MAX_SCAN_BYTES:
                print(f"::warning::secret scan skipped oversized text file {relpath}")
                continue
            with open(fpath, "rb") as fh:
                raw = fh.read()
            if raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
                text = raw.decode("utf-16", errors="ignore")
            else:
                text = raw.decode("utf-8", errors="ignore")
            for line in text.splitlines():
                hit = next(
                    (p.search(line) for p in SECRET_PATTERNS if p.search(line)), None
                )
                if hit:
                    findings.append(
                        (relpath, f"credential-like content: {hit.group(0)[:60]}")
                    )
                    break
    return findings


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1 or not os.path.isdir(args[0]):
        print("usage: check_site_secrets.py <site-dir>", file=sys.stderr)
        return 2
    findings = scan_site(args[0])
    if findings:
        print("*** SITE SECRET GATE: the built artifact carries secrets ***")
        for relpath, finding in findings:
            print(f"  {relpath}: {finding}")
        return 1
    print("site secret gate: clean")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
