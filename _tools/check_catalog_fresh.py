#!/usr/bin/env python3
"""Fail when the built catalog serves any entry ``stale``, AFTER it deployed.

A build-resolved entry whose lookup fails (release API down, upstream index
empty or unreachable, zip 404) falls back to the live last-good copy and is
marked ``stale`` in /static/catalog.json. The fallback is right: the boxes
keep a working catalog. The silence was not: from 2026-10-01 to 2026-10-15
the POV upstream index answered an empty ``<addons />``, POV and the skin
were served stale, every run stayed green with only a ::warning::, and skin
1.5.2 was released but never served.

pages.yml runs this as its own job after the deploy, so the last-good site
still goes live, and the red run is what ci_failure_alert.yml turns into an
issue assigned to the owner; the next run with nothing stale closes it.

Usage:
    python3 _tools/check_catalog_fresh.py catalog.json
"""

from __future__ import annotations

import argparse
import json
import sys


def stale_entries(manifest: dict) -> list[str]:
    """Ids the manifest marks stale, sorted."""
    entries = manifest.get("entries") or {}
    return sorted(i for i, e in entries.items() if e.get("stale"))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("manifest", help="the build's static/catalog.json")
    args = ap.parse_args(argv)
    with open(args.manifest, encoding="utf-8") as fh:
        manifest = json.load(fh)
    stale = stale_entries(manifest)
    if stale:
        for aid in stale:
            version = manifest["entries"][aid].get("version")
            print(
                f"::error::{aid} served STALE at last-good {version}: its "
                f"upstream lookup failed in this build (see the Build site "
                f"step's ::warning:: lines for why)"
            )
        print(f"{len(stale)} stale entr{'y' if len(stale) == 1 else 'ies'}: {stale}")
        return 1
    print(f"catalog fresh: 0 stale of {manifest.get('count', 0)} entries")
    return 0


if __name__ == "__main__":
    sys.exit(main())
