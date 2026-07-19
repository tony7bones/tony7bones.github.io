#!/usr/bin/env python3
"""Build the static Kodi repository tree (/static/) from repository.json.

The static conversion's core: resolves every entry of the proxy's manifest
(_tools/catalog.json, 31 entries) into a
plain static Kodi repo layout that Kodi's own repository client consumes with
no on-box engine:

    static/
      addons.xml            all entries, one <addon> root each, sorted by id
      addons.xml.md5        md5 of the exact bytes above (single writer)
      catalog.json          build manifest: per-id version/sha256/source/kind
      <id>/<id>-<v>.zip     every entry's zip materialized at ONE datadir base
      <id>/addon.xml        metadata snapshot (also the last-good fallback key)
      <id>/icon.png ...     art, so Kodi's add-on browser renders entries

Entry classes (classified from URL shapes, same logic the engine applied at
runtime): first-party (built from addons/<id>/ source), hosted mirror (zip +
metadata committed under addons/hosted/<id>/), hybrid (hosted metadata,
upstream zip), streamed (metadata AND zip fetched from the upstream repo),
release-asset (hosted metadata, zip from a GitHub Release on the source repo).

Fault policy (parity with the hardened 2.4.9 engine, moved to build time):
  - one dead upstream -> fall back to the LAST-GOOD copy already served at the
    live /static/ tree (addon.xml + zip at the baseline version), mark the
    entry ``stale`` and warn; if there is no baseline either, drop the entry
    with a warning;
  - the produced catalog may never lose ids vs the live baseline (shrink
    guard) unless explicitly allowed (--allow-catalog-shrink);
  - zero resolvable entries -> hard fail (never publish an empty catalog);
  - any output file over 90MB -> hard fail (GitHub's 100MB ceiling, never met
    by surprise);
  - a missing FIRST-PARTY zip is a build bug, not an upstream flake -> hard
    fail immediately.

Downloads go through a content-addressed cache (T7B_FETCH_CACHE or
~/.cache/t7b-fetch): version-bearing URLs are immutable (fetched once per
version); mutable URLs (upstream addon.xml of streamed entries, art) are
re-fetched only with --refresh-third-party. Two builds in one run therefore
produce byte-identical trees - the determinism gate depends on it.

Usage:
    python3 _tools/static_catalog.py --out _site/static
        [--refresh-third-party] [--allow-catalog-shrink]
        [--baseline-url https://tony7bones.github.io/static/catalog.json]
"""

from __future__ import annotations

import argparse
import hashlib
import http.client
import io
import json
import os
import shutil
import sys
import urllib.error
import urllib.request
import zipfile
from dataclasses import dataclass, field
from xml.etree import ElementTree as ET

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from check_hosted_release_sync import _RELEASE_ASSET_RE  # noqa: E402

REPO_ROOT = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
)
REPO_JSON = os.path.join(REPO_ROOT, "_tools", "catalog.json")
OWN_RAW = "https://raw.githubusercontent.com/tony7bones/tony7bones.github.io/"
DEFAULT_BASE_URL = "https://tony7bones.github.io"
MAX_FILE_BYTES = 90 * 1024 * 1024
_USER_AGENT = "t7b-static-builder/1.0"

KIND_FIRST_PARTY = "first-party"
KIND_HOSTED = "hosted"
KIND_HYBRID = "hybrid"
KIND_STREAMED = "streamed"
KIND_RELEASE_ASSET = "release-asset"

# Hosted-dir files that are repo plumbing, not served metadata/art.
_HOSTED_EXCLUDE = {"index.html", "release-sync-waiver.json"}


class BuildError(Exception):
    """A named, loud whole-build failure - the deploy must not happen."""


class FetchError(Exception):
    """A single URL could not be fetched (entry-scoped, may be recoverable)."""


def warn(msg: str, sink: list[str] | None = None) -> None:
    """GitHub-Actions-visible warning that also lands in the run log."""
    print(f"::warning::{msg}")
    if sink is not None:
        sink.append(msg)


class Fetcher:
    """Content-addressed download cache (key = sha256 of the URL).

    ``mutable=True`` marks URLs whose content can move under the same URL
    (streamed upstream addon.xml, art at a branch ref); those re-fetch only
    when ``refresh_mutable`` is set, otherwise the cached copy is used, which
    keeps repeat builds deterministic and kind to upstreams. A refresh attempt
    that fails falls back to the cached copy rather than erroring.
    """

    def __init__(
        self,
        cache_dir: str | None = None,
        refresh_mutable: bool = False,
        timeout: int = 60,
    ):
        self.cache_dir = cache_dir or os.environ.get(
            "T7B_FETCH_CACHE", os.path.expanduser("~/.cache/t7b-fetch")
        )
        self.refresh_mutable = refresh_mutable
        self.timeout = timeout

    def _cache_path(self, url: str) -> str:
        return os.path.join(self.cache_dir, hashlib.sha256(url.encode()).hexdigest())

    def _download(self, url: str) -> bytes:
        req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return resp.read()
        except (
            urllib.error.URLError,
            http.client.HTTPException,
            OSError,
            TimeoutError,
        ) as exc:
            raise FetchError(f"{url}: {exc}") from exc

    def fetch(
        self,
        url: str,
        mutable: bool = False,
        tolerate_missing: bool = False,
        expect_zip: bool = False,
    ) -> bytes | None:
        """Fetch a URL through the cache. Returns None only when the URL 404s
        AND ``tolerate_missing`` is set (optional art). Raises FetchError
        otherwise on failure.

        ``expect_zip=True`` validates the payload is a readable zip BEFORE the
        cache write - a truncated/HTML-error download must never poison the
        cache (an immutable key would re-serve the corrupt bytes on every
        subsequent build until someone hand-bumps the cache prefix). A cached
        entry that fails the same check self-heals: treated as a miss and
        re-downloaded.
        """
        cache_path = self._cache_path(url)
        cached = os.path.isfile(cache_path)
        if cached and not (mutable and self.refresh_mutable):
            with open(cache_path, "rb") as fh:
                data = fh.read()
            if not expect_zip or _is_readable_zip(data):
                return data
            warn(f"corrupt cached zip for {url} - re-downloading")
            os.remove(cache_path)
            cached = False
        try:
            data = self._download(url)
        except FetchError as exc:
            if cached:
                warn(f"refresh failed, using cached copy: {exc}")
                with open(cache_path, "rb") as fh:
                    return fh.read()
            if tolerate_missing and _is_404(exc):
                return None
            raise
        if expect_zip and not _is_readable_zip(data):
            raise FetchError(f"{url}: payload is not a readable zip (not cached)")
        os.makedirs(self.cache_dir, exist_ok=True)
        tmp = cache_path + ".tmp"
        with open(tmp, "wb") as fh:
            fh.write(data)
        os.replace(tmp, cache_path)
        return data


def _is_readable_zip(data: bytes) -> bool:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            return zf.testzip() is None
    except (zipfile.BadZipFile, OSError):
        return False


def _is_404(exc: Exception) -> bool:
    cause = exc.__cause__
    return isinstance(cause, urllib.error.HTTPError) and cause.code == 404


def _relativize_source(source_url: str) -> str:
    """Strip build-machine absolute paths out of anything we serve.

    A locally-sourced entry carries the on-disk path it was built from. That is
    fine internally and wrong to publish: it leaks the operator's username and
    checkout layout into the deployed catalog.json. Remote URLs pass through
    untouched; local paths become repo-relative.
    """
    if not source_url or "://" in source_url:
        return source_url
    try:
        if os.path.isabs(source_url):
            rel = os.path.relpath(source_url, REPO_ROOT)
            # A path outside the repo tells the reader nothing useful and can
            # still leak layout, so report only the basename.
            return rel if not rel.startswith("..") else os.path.basename(source_url)
    except Exception:
        return os.path.basename(source_url)
    return source_url


def _subst(template: str, entry: dict, version: str | None = None) -> str:
    out = (
        template.replace("{username}", entry.get("username", ""))
        .replace("{repository}", entry.get("repository", ""))
        .replace("{ref}", entry.get("branch") or "main")
        .replace("{id}", entry["id"])
    )
    if version is not None:
        out = out.replace("{version}", version)
    return out


def load_catalog(repo_json: str = REPO_JSON) -> list[dict]:
    with open(repo_json, encoding="utf-8") as fh:
        entries = json.load(fh)
    return sorted(entries, key=lambda e: e["id"])


def classify(entry: dict) -> str:
    """Decide the entry class from the same URL shapes the engine resolved.

    Shapes are matched on the SUBSTITUTED urls (templates carry literal
    {username}/{repository} placeholders), except the release-asset check,
    which matches the raw template exactly as check_hosted_release_sync does
    (its regex expects the literal ``v{version}`` segment).
    """
    zip_tmpl = (entry.get("assets") or {}).get("zip", "")
    zip_url = _subst(zip_tmpl, entry)
    prefix = _subst(entry.get("asset_prefix", ""), entry)
    own_prefix = prefix.startswith(OWN_RAW)
    hosted_prefix = own_prefix and "/addons/hosted/" in prefix
    if _RELEASE_ASSET_RE.match(zip_tmpl):
        return KIND_RELEASE_ASSET
    if own_prefix and not hosted_prefix:
        return KIND_FIRST_PARTY
    if hosted_prefix and zip_url.startswith(OWN_RAW):
        return KIND_HOSTED
    if hosted_prefix:
        return KIND_HYBRID
    return KIND_STREAMED


@dataclass
class ResolvedEntry:
    id: str
    kind: str
    version: str
    addon_xml: bytes
    zip_bytes: bytes
    source_url: str
    stale: bool = False
    art: dict[str, bytes] = field(default_factory=dict)  # relpath -> bytes

    @property
    def zip_name(self) -> str:
        return f"{self.id}-{self.version}.zip"


def _local_version(addon_xml_path: str) -> tuple[str, bytes]:
    try:
        with open(addon_xml_path, "rb") as fh:
            data = fh.read()
        version = ET.fromstring(data).get("version")
    except FileNotFoundError as exc:
        raise BuildError(f"{addon_xml_path}: missing (committed metadata)") from exc
    except ET.ParseError as exc:
        raise BuildError(f"{addon_xml_path}: unparseable addon.xml ({exc})") from exc
    if not version:
        raise BuildError(f"{addon_xml_path}: addon.xml has no version")
    return version, data


def _validate_zip(
    entry_id: str,
    data: bytes,
    warnings: list[str],
    advertised_version: str | None = None,
) -> None:
    """Zip must be readable, under the size gate, and its INTERNAL addon.xml
    must agree with the advertised id/version - a mismatch ships an entry whose
    installed version never equals the catalog's (a permanent Kodi update
    loop). Mismatch raises FetchError (per-entry: fallback/drop applies);
    only the size gate is a whole-build BuildError by policy."""
    if len(data) > MAX_FILE_BYTES:
        raise BuildError(
            f"{entry_id}: zip is {len(data)} bytes, over the 90MB gate "
            f"(GitHub's 100MB ceiling must never be met by surprise)"
        )
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            names = zf.namelist()
            top = names[0].split("/")[0] if names else ""
            inner = None
            if top and f"{top}/addon.xml" in names:
                inner = ET.fromstring(zf.read(f"{top}/addon.xml"))
    except (zipfile.BadZipFile, ET.ParseError, KeyError, OSError) as exc:
        raise FetchError(f"{entry_id}: not a valid addon zip ({exc})") from exc
    if names and not all(n.split("/")[0] == top for n in names):
        raise FetchError(f"{entry_id}: zip has multiple top-level dirs")
    if top and top != entry_id:
        warn(
            f"{entry_id}: zip top-level dir is not '{entry_id}/' "
            f"(serving verbatim, engine parity)",
            warnings,
        )
    if inner is None:
        warn(f"{entry_id}: zip carries no {top}/addon.xml to cross-check", warnings)
        return
    if inner.get("id") != entry_id:
        raise FetchError(f"{entry_id}: zip's internal addon id is {inner.get('id')!r}")
    if advertised_version and inner.get("version") != advertised_version:
        raise FetchError(
            f"{entry_id}: zip's internal version {inner.get('version')!r} != "
            f"advertised {advertised_version!r} (would loop Kodi's updater)"
        )


def _hosted_art(hosted_dir: str) -> dict[str, bytes]:
    """All committed metadata/art files of a hosted mirror dir (recursive),
    excluding zips and repo plumbing. addon.xml is included."""
    art: dict[str, bytes] = {}
    for dirpath, dirnames, filenames in os.walk(hosted_dir):
        dirnames.sort()
        for fname in sorted(filenames):
            rel = os.path.relpath(os.path.join(dirpath, fname), hosted_dir)
            if fname.endswith(".zip") or fname in _HOSTED_EXCLUDE:
                continue
            with open(os.path.join(dirpath, fname), "rb") as fh:
                art[rel] = fh.read()
    return art


def _streamed_art(
    entry: dict, root: ET.Element, fetcher: Fetcher, warnings: list[str]
) -> dict[str, bytes]:
    """icon/fanart + declared <assets> for an upstream-streamed entry,
    best-effort (missing art is a warning, never fatal - engine parity)."""
    prefix = _subst(entry["asset_prefix"], entry)
    paths = {"icon.png", "fanart.jpg"}
    for asset in root.iter("assets"):
        for child in asset:
            if child.text and child.text.strip():
                paths.add(child.text.strip())
    art: dict[str, bytes] = {}
    for rel in sorted(paths):
        try:
            data = fetcher.fetch(prefix + rel, mutable=True, tolerate_missing=True)
        except FetchError as exc:
            warn(f"{entry['id']}: art fetch failed for {rel}: {exc}", warnings)
            continue
        if data is None:
            if rel == "icon.png":
                warn(f"{entry['id']}: no icon.png upstream", warnings)
            continue
        art[rel] = data
    return art


def _resolve_primary(
    entry: dict,
    kind: str,
    fetcher: Fetcher,
    warnings: list[str],
    repo_root: str = REPO_ROOT,
) -> ResolvedEntry:
    entry_id = entry["id"]
    zip_tmpl = (entry.get("assets") or {}).get("zip", "")

    if kind == KIND_FIRST_PARTY:
        addon_dir = os.path.join(repo_root, "addons", entry_id)
        version, addon_xml = _local_version(os.path.join(addon_dir, "addon.xml"))
        zip_path = os.path.join(addon_dir, f"{entry_id}-{version}.zip")
        if not os.path.isfile(zip_path):
            raise BuildError(
                f"{entry_id}: first-party zip missing at {zip_path} "
                f"(run generate_repo.py first - this is a build bug, not a flake)"
            )
        with open(zip_path, "rb") as fh:
            zip_bytes = fh.read()
        art: dict[str, bytes] = {"addon.xml": addon_xml}
        for rel in sorted(_declared_art_paths(addon_xml)):
            fpath = os.path.join(addon_dir, rel)
            if os.path.isfile(fpath):
                with open(fpath, "rb") as fh:
                    art[rel] = fh.read()
        return ResolvedEntry(
            entry_id, kind, version, addon_xml, zip_bytes, zip_path, art=art
        )

    if kind in (KIND_HOSTED, KIND_HYBRID, KIND_RELEASE_ASSET):
        hosted_dir = os.path.join(repo_root, "addons", "hosted", entry_id)
        version, addon_xml = _local_version(os.path.join(hosted_dir, "addon.xml"))
        art = _hosted_art(hosted_dir)
        if kind == KIND_HOSTED:
            src = os.path.join(hosted_dir, f"{entry_id}-{version}.zip")
            if not os.path.isfile(src):
                src = os.path.join(hosted_dir, f"{entry_id}.zip")
            if not os.path.isfile(src):
                raise FetchError(f"{entry_id}: no committed zip in {hosted_dir}")
            with open(src, "rb") as fh:
                zip_bytes = fh.read()
            source_url = src
        else:
            source_url = _subst(zip_tmpl, entry, version)
            zip_bytes = fetcher.fetch(source_url, expect_zip=True)
        return ResolvedEntry(
            entry_id, kind, version, addon_xml, zip_bytes, source_url, art=art
        )

    # KIND_STREAMED: metadata AND zip live on the upstream repo.
    prefix = _subst(entry["asset_prefix"], entry)
    addon_xml = fetcher.fetch(prefix + "addon.xml", mutable=True)
    try:
        root = ET.fromstring(addon_xml)
    except ET.ParseError as exc:
        # An upstream serving 200-with-HTML (rate limit, moved repo) is a
        # flake, not a build bug - keep it per-entry so fallback applies.
        raise FetchError(f"{entry_id}: upstream addon.xml unparseable ({exc})") from exc
    version = root.get("version")
    if not version:
        raise FetchError(f"{entry_id}: upstream addon.xml has no version")
    source_url = _subst(zip_tmpl, entry, version)
    zip_bytes = fetcher.fetch(source_url, expect_zip=True)
    art = _streamed_art(entry, root, fetcher, warnings)
    art["addon.xml"] = addon_xml
    return ResolvedEntry(
        entry_id, KIND_STREAMED, version, addon_xml, zip_bytes, source_url, art=art
    )


def _declared_art_paths(addon_xml: bytes) -> set[str]:
    """addon.xml-declared assets + the conventional icon/fanart names - the
    only source files that belong at the datadir (never the whole source)."""
    paths = {"icon.png", "fanart.jpg"}
    root = ET.fromstring(addon_xml)
    for asset in root.iter("assets"):
        for child in asset:
            if child.text and child.text.strip():
                paths.add(child.text.strip())
    return paths


def _fill_art_from_zip(item: ResolvedEntry) -> None:
    """Materialize declared-but-missing art out of the entry's own zip.

    Dev-Kodi finding (2026-07-15): Kodi's add-on browser fetches art at
    <datadir>/<id>/<asset path>; most hosted metadata dirs never carried an
    icon even though the ZIP does (the engine 404'd these too - this is an
    improvement over parity, required by the "visible with art" contract).
    Only paths the addon.xml declares are extracted, never the whole zip."""
    missing = [p for p in _declared_art_paths(item.addon_xml) if p not in item.art]
    if not missing:
        return
    with zipfile.ZipFile(io.BytesIO(item.zip_bytes)) as zf:
        names = set(zf.namelist())
        top = next(iter(sorted(names))).split("/")[0] if names else item.id
        for rel in missing:
            member = f"{top}/{rel}"
            if member in names:
                item.art[rel] = zf.read(member)


def _resolve_fallback(
    entry: dict,
    kind: str,
    baseline: dict,
    base_url: str,
    fetcher: Fetcher,
    warnings: list[str],
) -> ResolvedEntry | None:
    """Last-good: re-fetch the copy the live /static/ tree already serves.

    ALWAYS fetched fresh via ``_download`` - never through the cache. These
    URLs are our own site and MOVE with every deploy; a cached copy pairs an
    old addon.xml version with the baseline's newer zip name, and Kodi then
    computes a zip URL that 404s. The parsed addon.xml version must equal the
    baseline version for the same reason - any mismatch fails the fallback.
    """
    entry_id = entry["id"]
    info = (baseline.get("entries") or {}).get(entry_id)
    if not info:
        return None
    version = info["version"]
    live = f"{base_url}/static/{entry_id}/"
    try:
        addon_xml = fetcher._download(live + "addon.xml")
        zip_bytes = fetcher._download(live + f"{entry_id}-{version}.zip")
        live_version = ET.fromstring(addon_xml).get("version")
    except (FetchError, ET.ParseError) as exc:
        warn(f"{entry_id}: last-good fallback also failed: {exc}", warnings)
        return None
    if live_version != version:
        warn(
            f"{entry_id}: live addon.xml says {live_version!r} but the "
            f"baseline manifest says {version!r} - fallback refused",
            warnings,
        )
        return None
    art: dict[str, bytes] = {"addon.xml": addon_xml}
    for rel in ("icon.png", "fanart.jpg"):
        try:
            data = fetcher._download(live + rel)
        except FetchError:
            data = None
        if data is not None:
            art[rel] = data
    return ResolvedEntry(
        entry_id, kind, version, addon_xml, zip_bytes, live, stale=True, art=art
    )


def resolve_all(
    entries: list[dict],
    fetcher: Fetcher,
    baseline: dict | None,
    base_url: str,
    warnings: list[str],
    repo_root: str = REPO_ROOT,
) -> list[ResolvedEntry]:
    resolved = []
    for entry in entries:
        kind = classify(entry)
        # Zip validation lives INSIDE the per-entry try: a corrupt primary zip
        # is a flake that must fall back, never a whole-build failure. Only
        # BuildError (size gate, first-party build bugs) escapes by design.
        try:
            item = _resolve_primary(entry, kind, fetcher, warnings, repo_root)
            _validate_zip(entry["id"], item.zip_bytes, warnings, item.version)
            _fill_art_from_zip(item)
        except FetchError as exc:
            if kind == KIND_FIRST_PARTY:
                # First-party bytes are local: a failure here is a build bug,
                # not a flake - fail the whole build, never fall back.
                raise BuildError(f"{entry['id']}: {exc}") from exc
            warn(f"{entry['id']}: primary resolution failed: {exc}", warnings)
            item = (
                _resolve_fallback(entry, kind, baseline, base_url, fetcher, warnings)
                if baseline
                else None
            )
            if item is not None:
                try:
                    _validate_zip(entry["id"], item.zip_bytes, warnings, item.version)
                    _fill_art_from_zip(item)
                except FetchError as exc2:
                    warn(f"{entry['id']}: fallback zip invalid: {exc2}", warnings)
                    item = None
            if item is None:
                warn(f"{entry['id']}: DROPPED from this build (no last-good)", warnings)
                continue
        resolved.append(item)
    return resolved


def write_static_tree(resolved: list[ResolvedEntry], out_dir: str) -> dict:
    """Write the static repo tree. The md5 sidecar is written from the exact
    bytes of the addons.xml just written - the invariant lives HERE, in the
    single writer, and nowhere else. Returns the catalog manifest dict."""
    os.makedirs(out_dir, exist_ok=True)
    roots = []
    manifest_entries: dict[str, dict] = {}
    for item in sorted(resolved, key=lambda r: r.id):
        root = ET.fromstring(item.addon_xml)
        # The single-writer invariant: the version the addons.xml will
        # advertise MUST be the version the zip filename carries, or Kodi
        # computes a zip URL that 404s. No entry may cross this line skewed.
        if root.get("version") != item.version:
            raise BuildError(
                f"{item.id}: addon.xml advertises {root.get('version')!r} but "
                f"the materialized zip is {item.zip_name} - version skew"
            )
        entry_dir = os.path.join(out_dir, item.id)
        if os.path.isdir(entry_dir):
            shutil.rmtree(entry_dir)
        os.makedirs(entry_dir)
        with open(os.path.join(entry_dir, item.zip_name), "wb") as fh:
            fh.write(item.zip_bytes)
        for rel, data in sorted(item.art.items()):
            if len(data) > MAX_FILE_BYTES:
                raise BuildError(f"{item.id}/{rel}: over the 90MB gate")
            dest = os.path.join(entry_dir, rel)
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            with open(dest, "wb") as fh:
                fh.write(data)
        roots.append(root)
        manifest_entries[item.id] = {
            "version": item.version,
            "zip": f"{item.id}/{item.zip_name}",
            "zip_sha256": hashlib.sha256(item.zip_bytes).hexdigest(),
            "zip_size": len(item.zip_bytes),
            "kind": item.kind,
            # Relativized before serving. For locally-sourced entries this is an
            # absolute path on the build machine, which published the owner's
            # home directory and checkout layout in the deployed catalog.json
            # (16 entries, found 2026-07-18). The secret patterns do not match
            # filesystem paths, so the gate passed it. Remote URLs are unchanged.
            "source_url": _relativize_source(item.source_url),
            "stale": item.stale,
        }

    addons_el = ET.Element("addons")
    addons_el.extend(roots)
    ET.indent(addons_el, space="    ")
    xml_path = os.path.join(out_dir, "addons.xml")
    ET.ElementTree(addons_el).write(xml_path, encoding="UTF-8", xml_declaration=True)
    with open(xml_path, "rb") as fh:
        data = fh.read()
    with open(xml_path + ".md5", "w") as fh:
        fh.write(hashlib.md5(data).hexdigest())

    manifest = {"count": len(manifest_entries), "entries": manifest_entries}
    with open(os.path.join(out_dir, "catalog.json"), "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=2, sort_keys=True)
        fh.write("\n")
    return manifest


def load_baseline(
    baseline_url: str, fetcher: Fetcher, warnings: list[str]
) -> dict | None:
    """The live catalog.json - the shrink-guard + last-good reference. Always
    fetched fresh (never from the cache: it IS the current deployed state).

    A 404 means "first deploy, nothing live yet" and is fine. ANY OTHER
    failure is a hard BuildError: proceeding without a baseline silently
    disarms BOTH the shrink guard and the last-good fallback, so a transient
    503 plus one dead upstream in the same run could shrink the live catalog
    with a green build. --no-baseline remains the explicit escape."""
    last_exc: Exception | None = None
    for attempt in (1, 2):
        try:
            return json.loads(fetcher._download(baseline_url))
        except FetchError as exc:
            if _is_404(exc):
                return None
            last_exc = exc
            warn(f"baseline fetch attempt {attempt} failed: {exc}", warnings)
        except ValueError as exc:
            last_exc = exc
            warn(f"baseline unparseable: {exc}", warnings)
            break
    raise BuildError(
        f"baseline {baseline_url} unreachable/unusable ({last_exc}) - refusing "
        f"to build without the shrink-guard reference (--no-baseline is the "
        f"deliberate first-deploy escape)"
    )


def build(
    out_dir: str,
    fetcher: Fetcher | None = None,
    baseline: dict | None = None,
    baseline_url: str | None = None,
    base_url: str = DEFAULT_BASE_URL,
    allow_shrink: bool = False,
    repo_json: str = REPO_JSON,
    repo_root: str = REPO_ROOT,
) -> dict:
    """Resolve the whole catalog and write the static tree. Returns the
    manifest. Raises BuildError on any condition that must block the deploy."""
    fetcher = fetcher or Fetcher()
    warnings: list[str] = []
    entries = load_catalog(repo_json)
    if baseline is None and baseline_url:
        baseline = load_baseline(baseline_url, fetcher, warnings)

    resolved = resolve_all(entries, fetcher, baseline, base_url, warnings, repo_root)
    if not resolved:
        raise BuildError("0 resolvable entries - refusing to publish an empty catalog")

    produced = {r.id for r in resolved}
    if baseline:
        missing = sorted(set(baseline.get("entries") or {}) - produced)
        if missing and not allow_shrink:
            raise BuildError(
                f"catalog would LOSE entries vs the live baseline: {missing} "
                f"(pass --allow-catalog-shrink if this is intentional)"
            )
        if missing:
            warn(f"catalog shrink explicitly allowed; losing: {missing}", warnings)

    manifest = write_static_tree(resolved, out_dir)
    stale = sorted(i for i, e in manifest["entries"].items() if e["stale"])
    print(
        f"static catalog: {manifest['count']} entries"
        + (f" ({len(stale)} stale last-good: {stale})" if stale else "")
        + (f", {len(warnings)} warning(s)" if warnings else "")
    )
    return manifest


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", required=True, help="output dir (the /static/ tree)")
    ap.add_argument("--refresh-third-party", action="store_true")
    ap.add_argument("--allow-catalog-shrink", action="store_true")
    ap.add_argument("--baseline-url", default=f"{DEFAULT_BASE_URL}/static/catalog.json")
    ap.add_argument("--base-url", default=DEFAULT_BASE_URL)
    ap.add_argument("--no-baseline", action="store_true", help="first deploy")
    args = ap.parse_args(argv)
    try:
        build(
            args.out,
            fetcher=Fetcher(refresh_mutable=args.refresh_third_party),
            baseline_url=None if args.no_baseline else args.baseline_url,
            base_url=args.base_url,
            allow_shrink=args.allow_catalog_shrink,
        )
    except BuildError as exc:
        print(f"BUILD FAILED: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
