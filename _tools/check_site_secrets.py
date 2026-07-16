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

# Dirs whose CONTENT scan is skipped (source, not served content; covered by
# test_secret_leak.py on the tracked tree). The STRUCTURAL check still applies.
_SOURCE_DIRS = {"_tools", "docs", ".github", ".githooks", ".claude", "node_modules"}

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


def _structural_violation(relpath: str) -> str | None:
    base = os.path.basename(relpath)
    parts = relpath.split(os.sep)
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
        top = rel_dir.split(os.sep)[0] if rel_dir != "." else ""
        dirnames.sort()
        for fname in sorted(filenames):
            relpath = os.path.normpath(os.path.join(rel_dir, fname))
            struct = _structural_violation(relpath)
            if struct:
                findings.append((relpath, struct))
                continue
            if top in _SOURCE_DIRS:
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
