#!/usr/bin/env python3
"""Consumer-seat verification of the DEPLOYED site - the post-deploy CI gate.

The 2026-07-15 lesson institutionalized: a release that cannot propagate must
fail in CI, not on the fleet. This tool fetches through the SAME public URLs
Kodi uses (never raw.githubusercontent, never the git tree) and asserts:

  1. /static/addons.xml + /static/addons.xml.md5: the sidecar is the md5 of
     the exact served bytes, and the entry set + versions match the build's
     catalog.json manifest.
  2. Every /static/<id>/<id>-<version>.zip answers 200 (HEAD).
  3. At least two zips (always repository.tony7bones, plus the first other id)
     full-GET with sha256 matching the manifest.
  4. The root canvas answers: / lists the canvas folders, and the root
     installer repository.tony7bones-<version>.zip answers 200.
  5. Transition only (--transition): the legacy /addons/addons.xml the engine
     era exposed still answers 200.

Polling shape mirrors deploy.py's verify_live (attempts x delay) because
Pages/CDN propagation lags a deploy by up to a couple of minutes.

Usage:
    python3 _tools/verify_live_site.py --manifest _site/static/catalog.json
        [--base-url https://tony7bones.github.io] [--attempts 18] [--delay 10]
        [--transition]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import time
import urllib.error
import urllib.request
from xml.etree import ElementTree as ET

_USER_AGENT = "t7b-live-verify/1.0"


class VerifyError(Exception):
    """One named check failed this attempt."""


def _request(url: str, method: str = "GET") -> bytes:
    req = urllib.request.Request(
        url, method=method, headers={"User-Agent": _USER_AGENT}
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            if resp.status != 200:
                raise VerifyError(f"{method} {url}: http {resp.status}")
            return resp.read() if method == "GET" else b""
    except urllib.error.HTTPError as exc:
        raise VerifyError(f"{method} {url}: http {exc.code}") from exc
    except (urllib.error.URLError, OSError, TimeoutError) as exc:
        raise VerifyError(f"{method} {url}: {exc}") from exc


def _check_catalog(base_url: str, manifest: dict) -> None:
    xml_bytes = _request(f"{base_url}/static/addons.xml")
    md5_sidecar = _request(f"{base_url}/static/addons.xml.md5").decode().strip()
    if hashlib.md5(xml_bytes).hexdigest() != md5_sidecar:
        raise VerifyError("addons.xml.md5 does not match the served addons.xml bytes")
    served = {el.get("id"): el.get("version") for el in ET.fromstring(xml_bytes)}
    expected = {i: e["version"] for i, e in manifest["entries"].items()}
    if served != expected:
        missing = sorted(set(expected) - set(served))
        extra = sorted(set(served) - set(expected))
        drift = sorted(
            i for i in set(served) & set(expected) if served[i] != expected[i]
        )
        raise VerifyError(
            f"served catalog != build manifest "
            f"(missing={missing} extra={extra} version-drift={drift})"
        )


def _check_zips(base_url: str, manifest: dict) -> None:
    entries = manifest["entries"]
    for entry_id, info in sorted(entries.items()):
        _request(f"{base_url}/static/{info['zip']}", method="HEAD")
    full = ["repository.tony7bones"] if "repository.tony7bones" in entries else []
    others = sorted(i for i in entries if i != "repository.tony7bones")
    if others:
        # Rotate which extra zip gets content-verified: derive the pick from
        # the catalog state itself (deterministic per deploy, different picks
        # as the catalog evolves) so every entry gets full-GET coverage over
        # time instead of the same one forever.
        digest = hashlib.md5(
            json.dumps(
                {i: e["version"] for i, e in entries.items()}, sort_keys=True
            ).encode()
        ).hexdigest()
        full.append(others[int(digest, 16) % len(others)])
    for entry_id in full:
        info = entries[entry_id]
        data = _request(f"{base_url}/static/{info['zip']}")
        got = hashlib.sha256(data).hexdigest()
        if got != info["zip_sha256"]:
            raise VerifyError(
                f"{entry_id}: served zip sha256 {got[:12]}... != "
                f"manifest {info['zip_sha256'][:12]}..."
            )


def _check_canvas(base_url: str, manifest: dict) -> None:
    root_html = _request(f"{base_url}/").decode(errors="ignore")
    for folder in ("repositories/", "media/", "iptv/", "rss/"):
        if f'href="{folder}"' not in root_html:
            raise VerifyError(f"root canvas listing is missing {folder}")
    proxy = manifest["entries"].get("repository.tony7bones")
    if proxy is None:
        raise VerifyError("repository.tony7bones is missing from the manifest")
    _request(f"{base_url}/repository.tony7bones-{proxy['version']}.zip", method="HEAD")


def verify(
    manifest: dict,
    base_url: str,
    attempts: int = 18,
    delay: int = 10,
    transition: bool = False,
    expect_count: int | None = None,
) -> bool:
    # Absolute entry floor: the manifest is the BUILD's own output, so
    # comparing site-to-manifest alone can bless a shrunken build. When the
    # caller knows the source-of-truth count (repository.json length), a
    # smaller manifest fails immediately - no retry will fix it.
    if expect_count is not None and manifest["count"] != expect_count:
        print(
            f"LIVE VERIFY FAILED up front: manifest has {manifest['count']} "
            f"entries but the source catalog defines {expect_count}"
        )
        return False
    for i in range(1, attempts + 1):
        try:
            _check_catalog(base_url, manifest)
            _check_zips(base_url, manifest)
            _check_canvas(base_url, manifest)
            if transition:
                _request(f"{base_url}/addons/addons.xml", method="HEAD")
            print(
                f"LIVE VERIFIED from the consumer seat: "
                f"{manifest['count']} entries, md5 match, all zips answer"
            )
            return True
        except VerifyError as exc:
            print(f"  attempt {i}/{attempts}: {exc}")
            if i < attempts:
                time.sleep(delay)
    return False


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--manifest", required=True, help="the build's catalog.json")
    ap.add_argument("--base-url", default="https://tony7bones.github.io")
    ap.add_argument("--attempts", type=int, default=18)
    ap.add_argument("--delay", type=int, default=10)
    ap.add_argument("--transition", action="store_true")
    ap.add_argument(
        "--expect-count",
        type=int,
        default=None,
        help="source-of-truth entry count (len of repository.json); omit only "
        "when a catalog shrink was explicitly allowed",
    )
    args = ap.parse_args(argv)
    with open(args.manifest, encoding="utf-8") as fh:
        manifest = json.load(fh)
    ok = verify(
        manifest,
        args.base_url.rstrip("/"),
        attempts=args.attempts,
        delay=args.delay,
        transition=args.transition,
        expect_count=args.expect_count,
    )
    if not ok:
        print("LIVE VERIFY FAILED: the deployed site does not match the build")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
