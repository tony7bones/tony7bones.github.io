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
upstream zip; with ``upstream_index`` the version and metadata come from the
upstream repo's addons.xml and zip instead, nothing committed), streamed
(metadata AND zip fetched from the upstream repo), release-asset (version
resolved from the source repo's GitHub Releases at build time, plain
``v{version}`` tags or the namespaced ``{id}-v{version}`` shape, metadata
taken from the release zip, nothing committed). Since 2026-09-26 every add-on
we own is build-resolved: THERE MUST BE NO MIRROR VERSION TO BE WRONG.

Two of those resolve their VERSION at build time, on every build, and take
their metadata from the zip itself, so there is no committed copy to rot
(since 2026-09-26 that is every add-on we own AND the eleven official-library
modules their closures reach, which follow the official Kodi repository's
Piers index, https://mirrors.kodi.tv/addons/piers/addons.xml.gz, exactly the
way plugin.video.pov follows its upstream's; addons/hosted/ holds only the
seven third-party repository installers):

  - release-asset: the source repo's LATEST published release is the version
    (GitHub REST API with GH_TOKEN/GITHUB_TOKEN when present, else the
    unauthenticated redirect of github.com/<owner>/<repo>/releases/latest).
    A source repo that ships SEVERAL add-ons (estuary-pov since 2026-09-26)
    tags each in its own namespace, ``<id>-v<version>``, which the zip
    template spells out; the build then lists the repo's releases and takes
    the newest in that namespace, since releases/latest can only name one;
  - hybrid with an ``upstream_index`` (a Kodi addons.xml the upstream
    repository publishes, plain or gzipped): the version that index declares
    for the add-on. One index is fetched and parsed ONCE per build however
    many entries point at it (BuildContext), and a zip is accepted only if it
    packages exactly the id and version the index named, so a mirror that
    answers with the wrong file is refused before the download cache.

Both replaced a hand-maintained addons/hosted/<id>/addon.xml on 2026-09-26,
after EZ Maintenance++ sat nine days behind its release and plugin.video.pov
404ed and was DROPPED from the build for days. A hybrid entry WITHOUT an
upstream_index keeps the committed addon.xml as its truth.

The import closure of every build-resolved entry is walked at build time,
transitively through the other build-resolved entries (_check_imports_hosted
with BuildContext.addon_xml_for), since no committed addon.xml is left for
test_closure.py to walk offline.

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
re-fetched only with --refresh-third-party. The version lookups above never
touch the cache at all: owned content has a minutes staleness bound, so the
latest release and the upstream index are read fresh on every build, on push,
cron and repository_dispatch alike. Two builds in one run still produce
byte-identical trees - the determinism gate depends on it.

Usage:
    python3 _tools/static_catalog.py --out _site/static
        [--refresh-third-party] [--allow-catalog-shrink]
        [--baseline-url https://tony7bones.github.io/static/catalog.json]
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import http.client
import io
import json
import os
import re
import shutil
import sys
import time
import urllib.error
import urllib.request
import zipfile
from collections.abc import Callable
from dataclasses import dataclass, field
from xml.etree import ElementTree as ET

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Kodi-provided extension points / built-ins that are never separate add-ons,
# so the import walk (_check_imports_hosted) never looks for them in the
# catalog. Lived in mirror_closure.py until 2026-09-26, when that tool (a
# writer of committed addons/hosted/ copies, retired with the owner's rule
# THERE MUST BE NO MIRROR VERSION TO BE WRONG) was deleted and the two
# constants the gates imported from it moved here.
BUILTINS = frozenset(
    {
        "xbmc.python",
        "xbmc.gui",
        "xbmc.addon",
        "xbmc.json",
        "xbmc.metadata",
        "kodi.resource",
        "xbmc.webinterface",
        "xbmc.audioencoder",
        "xbmc.python.pluginsource",
        "xbmc.python.module",
        "xbmc.python.script",
        "xbmc.python.library",
        "xbmc.gui.skin",
        "xbmc.service",
        "kodi.context.item",
    }
)

# Dependencies this tree is FORBIDDEN to host. Unlike BUILTINS, which are Kodi
# extension points no repository could host, these are REAL add-ons that Kodi
# resolves from its own official library. test_closure.py gates this set.
#
# EMPTY since 2026-08-31, and that is a ledger entry, not an invitation. Its
# one entry ever was `script.skinshortcuts`: mirrored here at 2.0.3 until
# 2026-07-29 (owner order: "we do not patch it, fork it, version it, host it,
# mirror it, or ship it"), then carried in this set because the decommissioned
# skin.estuary7 imported it and Kodi resolves it from the official library.
# The skin's unpublishing on 2026-08-31 removed the last importer, so the
# entry left with it. The mechanism stays, gated by test_closure.py: anything
# added here needs a written reason of that same kind, because a silent entry
# turns a real gate into a rubber stamp.
OFFICIAL_LIBRARY: frozenset[str] = frozenset()

REPO_ROOT = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
)
REPO_JSON = os.path.join(REPO_ROOT, "_tools", "catalog.json")
OWN_RAW = "https://raw.githubusercontent.com/tony7bones/tony7bones.github.io/"
DEFAULT_BASE_URL = "https://tony7bones.github.io"
MAX_FILE_BYTES = 90 * 1024 * 1024
_USER_AGENT = "t7b-static-builder/1.0"
GITHUB_API = "https://api.github.com"
# mirrors.kodi.tv answers a zip URL with a 302 to a volunteer mirror, and a
# mirror can accept the redirect and still not deliver the file (measured
# 2026-09-26: a certifi download came back as the requests zip's bytes). A
# transient failure is retried this many times; a 4xx is final on first answer.
_DOWNLOAD_ATTEMPTS = 3
_RETRY_DELAY_S = 1.0

# A GitHub Releases asset template pointing at a source repo: owner/repo are
# literal in the URL (distinct from the entry's own username/repository, which
# only shape its raw.githubusercontent asset_prefix). Matched on the RAW
# template, so the literal tag segment is part of the shape, and the tag
# segment names the release namespace:
#
#   .../releases/download/v{version}/...        one add-on per source repo
#                                               (ezmpp): the repo's LATEST
#                                               release IS the add-on's.
#   .../releases/download/{id}-v{version}/...   several add-ons per source repo
#                                               (estuary-pov ships the skin AND
#                                               service.tvos.pythonfix): a
#                                               repo has ONE releases/latest,
#                                               so each add-on tags its own
#                                               namespace and the build lists
#                                               the releases and takes the
#                                               newest whose tag starts with
#                                               ``<id>-v``.
#
# ``tag_prefix`` is the literal text before ``v{version}`` in the tag
# (``""`` or ``"{id}-"``), substituted per entry before use.
_RELEASE_ASSET_RE = re.compile(
    r"^https://github\.com/(?P<owner>[^/{}]+)/(?P<repo>[^/{}]+)"
    r"/releases/download/(?P<tag_prefix>(?:\{id\}-)?)v\{version\}/"
    r"(?P<asset_template>.+)$"
)
_LATEST_TAG_RE = re.compile(r"/releases/tag/v(?P<version>[^/?#]+)$")

KIND_FIRST_PARTY = "first-party"
KIND_HOSTED = "hosted"
KIND_HYBRID = "hybrid"
KIND_STREAMED = "streamed"
KIND_RELEASE_ASSET = "release-asset"

# Hosted-dir files that are repo plumbing, not served metadata/art.
_HOSTED_EXCLUDE = {"index.html"}


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

    def _download(self, url: str, headers: dict[str, str] | None = None) -> bytes:
        """One uncached GET, redirects followed (urllib's default opener
        follows 301/302/303/307/308, which is how a mirrors.kodi.tv zip URL
        resolves to a volunteer mirror). A transient failure (connection
        reset, timeout, 5xx, a mirror that took the redirect and dropped the
        transfer) is retried up to _DOWNLOAD_ATTEMPTS times, each attempt
        re-running the redirect and so possibly landing on another mirror; a
        4xx is final at the first answer. Every version lookup and every
        last-good fallback goes through here, never through ``fetch``."""
        hdrs = {"User-Agent": _USER_AGENT, **(headers or {})}
        last: Exception | None = None
        for attempt in range(1, _DOWNLOAD_ATTEMPTS + 1):
            req = urllib.request.Request(url, headers=hdrs)
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    return resp.read()
            except urllib.error.HTTPError as exc:
                last = exc
                if 400 <= exc.code < 500:
                    break
            except (
                urllib.error.URLError,
                http.client.HTTPException,
                OSError,
                TimeoutError,
            ) as exc:
                last = exc
            if attempt < _DOWNLOAD_ATTEMPTS:
                warn(
                    f"download attempt {attempt}/{_DOWNLOAD_ATTEMPTS} failed for "
                    f"{url}: {last} (retrying)"
                )
                time.sleep(_RETRY_DELAY_S * attempt)
        raise FetchError(f"{url}: {last}") from last

    def get_json(self, url: str, headers: dict[str, str] | None = None) -> dict:
        """Uncached GET of a JSON document (the GitHub REST API)."""
        data = self._download(url, headers)
        try:
            return json.loads(data.decode("utf-8"))
        except (UnicodeDecodeError, ValueError) as exc:
            raise FetchError(f"{url}: not JSON ({exc})") from exc

    def redirect_location(self, url: str) -> str:
        """The Location header of a redirecting URL, without following it.

        github.com/<owner>/<repo>/releases/latest answers 302 to
        /releases/tag/<tag> for anyone, no token and no API rate limit, which
        is what lets a developer machine with no token resolve the latest
        release. A 200 (no redirect) or any other status is a FetchError."""

        class _NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, req, fp, code, msg, headers, newurl):
                return None

        opener = urllib.request.build_opener(_NoRedirect)
        req = urllib.request.Request(
            url, method="HEAD", headers={"User-Agent": _USER_AGENT}
        )
        try:
            with opener.open(req, timeout=self.timeout):
                raise FetchError(f"{url}: expected a redirect, got 200")
        except urllib.error.HTTPError as exc:
            if exc.code in (301, 302, 303, 307, 308):
                location = exc.headers.get("Location")
                if location:
                    return location
            raise FetchError(f"{url}: HTTP {exc.code} without a Location") from exc
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
        headers: dict[str, str] | None = None,
        expect_addon: tuple[str, str] | None = None,
    ) -> bytes | None:
        """Fetch a URL through the cache. Returns None only when the URL 404s
        AND ``tolerate_missing`` is set (optional art). Raises FetchError
        otherwise on failure. ``headers`` ride along on the download only;
        the cache key is the URL.

        ``expect_zip=True`` validates the payload is a readable zip BEFORE the
        cache write - a truncated/HTML-error download must never poison the
        cache (an immutable key would re-serve the corrupt bytes on every
        subsequent build until someone hand-bumps the cache prefix). A cached
        entry that fails the same check self-heals: treated as a miss and
        re-downloaded.

        ``expect_addon=(id, version)`` goes one step further, for zips whose
        URL names the add-on and version: the zip must package exactly
        ``<id>/addon.xml`` with that id and version, or it is refused before
        the cache write. A mirror that answers one URL with another file's
        bytes (measured 2026-09-26 on mirrors.kodi.tv: a certifi download
        that was the requests zip) is a valid zip of the wrong add-on, which
        ``expect_zip`` alone would have cached under certifi's URL forever.
        """
        cache_path = self._cache_path(url)
        cached = os.path.isfile(cache_path)
        if cached and not (mutable and self.refresh_mutable):
            with open(cache_path, "rb") as fh:
                data = fh.read()
            problem = _payload_problem(data, expect_zip, expect_addon)
            if problem is None:
                return data
            warn(f"corrupt cached zip for {url} ({problem}) - re-downloading")
            os.remove(cache_path)
            cached = False
        try:
            data = self._download(url, headers)
        except FetchError as exc:
            if cached:
                warn(f"refresh failed, using cached copy: {exc}")
                with open(cache_path, "rb") as fh:
                    return fh.read()
            if tolerate_missing and _is_404(exc):
                return None
            raise
        problem = _payload_problem(data, expect_zip, expect_addon)
        if problem is not None:
            raise FetchError(f"{url}: {problem} (not cached)")
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


def _zip_mismatch(data: bytes, addon_id: str, version: str) -> str | None:
    """Why ``data`` is NOT the zip of ``addon_id`` at ``version``, or None
    when it is: reads ``<id>/addon.xml`` out of the zip and compares."""
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            xml = zf.read(f"{addon_id}/addon.xml")
        root = ET.fromstring(xml)
    except (zipfile.BadZipFile, KeyError, OSError) as exc:
        return f"zip carries no {addon_id}/addon.xml ({exc})"
    except ET.ParseError as exc:
        return f"packaged addon.xml unparseable ({exc})"
    if root.get("id") != addon_id or root.get("version") != version:
        return (
            f"zip packages {root.get('id')!r} {root.get('version')!r}, "
            f"expected {addon_id!r} {version!r}"
        )
    return None


def _payload_problem(
    data: bytes, expect_zip: bool, expect_addon: tuple[str, str] | None
) -> str | None:
    """The reason a fetched payload must not be served or cached, or None."""
    if (expect_zip or expect_addon) and not _is_readable_zip(data):
        return "payload is not a readable zip"
    if expect_addon:
        return _zip_mismatch(data, *expect_addon)
    return None


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
    which matches the raw template (its regex expects the literal
    ``v{version}`` segment). No kind needs a committed addon.xml to be
    decided: the two build-resolved kinds have none.
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


def metadata_resolved_at_build(entry: dict) -> bool:
    """True when the entry's version AND addon.xml come from upstream at
    build time (release-asset, or hybrid with an ``upstream_index``), so no
    addons/hosted/<id>/addon.xml exists for it and none may be added."""
    kind = classify(entry)
    if kind == KIND_RELEASE_ASSET:
        return True
    return kind == KIND_HYBRID and bool(entry.get("upstream_index"))


def gh_token() -> str | None:
    """GH_TOKEN wins, then GITHUB_TOKEN; both unset is a supported state."""
    return os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN") or None


def _version_key(version: str) -> tuple:
    """Sort key for dotted add-on versions: numeric components compare as
    numbers (2026.09.17.1 > 2026.09.2.0, 1.10.0 > 1.9.0), anything else as
    text after every numeric one."""
    return tuple(
        (0, int(part), "") if part.isdigit() else (1, 0, part)
        for part in version.split(".")
    )


def _github_headers() -> dict[str, str]:
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    token = gh_token()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _latest_namespaced_release(
    owner: str, repo: str, tag_prefix: str, asset_name: str, fetcher: Fetcher
) -> tuple[str, str]:
    """The newest published release of ``owner/repo`` whose tag is
    ``<tag_prefix>v<version>``: (bare version, API URL of its ``asset_name``).

    A repository has exactly one ``releases/latest``, so a repo that ships
    several add-ons (estuary-pov: the skin and service.tvos.pythonfix) cannot
    use it for any of them. GET /repos/{owner}/{repo}/releases lists them
    all; drafts, prereleases and every other namespace are skipped and the
    highest version wins (by component, not by list position, so a re-cut of
    an older version can never outrank a newer one). Works without a token
    (anonymous, rate-limited) on a public repo; with a token that can read
    the repo it works on a private one too, and the asset is then fetched
    through its API URL (``Accept: application/octet-stream``), which is the
    one download path GitHub honours for both visibilities. Never cached:
    this IS the freshness. No release in the namespace, or a release without
    its zip attached, is a FetchError, so the live last-good copy is served
    exactly as for any dead upstream."""
    url = f"{GITHUB_API}/repos/{owner}/{repo}/releases?per_page=100"
    releases = fetcher.get_json(url, _github_headers())
    if not isinstance(releases, list):
        raise FetchError(f"{url}: expected a JSON list of releases")
    want = f"{tag_prefix}v"
    candidates = {
        rel["tag_name"][len(want) :]: rel
        for rel in releases
        if isinstance(rel, dict)
        and isinstance(rel.get("tag_name"), str)
        and rel["tag_name"].startswith(want)
        and len(rel["tag_name"]) > len(want)
        and not rel.get("draft")
        and not rel.get("prerelease")
    }
    if not candidates:
        raise FetchError(f"{owner}/{repo}: no published release tagged {want}<version>")
    version = max(candidates, key=_version_key)
    name = asset_name.replace("{version}", version)
    for asset in candidates[version].get("assets") or []:
        if isinstance(asset, dict) and asset.get("name") == name and asset.get("url"):
            return version, asset["url"]
    raise FetchError(
        f"{owner}/{repo}: release {want}{version} carries no asset named {name}"
    )


def _latest_release_version(owner: str, repo: str, fetcher: Fetcher) -> str:
    """The source repo's LATEST published release, as a bare version.

    One add-on per repo (ezmpp, plain ``v<version>`` tags); a repo that
    ships several add-ons resolves through _latest_namespaced_release
    instead, since releases/latest would name whichever released last.

    Authenticated: GET
    /repos/{owner}/{repo}/releases/latest (CI passes secrets.GITHUB_TOKEN, no
    shared-runner rate limit). Otherwise, or when the API call fails for any
    reason but "no release at all", the unauthenticated 302 of
    github.com/{owner}/{repo}/releases/latest, whose Location ends in
    /releases/tag/v<version>. Never cached: this IS the freshness."""
    token = gh_token()
    if token:
        url = f"{GITHUB_API}/repos/{owner}/{repo}/releases/latest"
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "Authorization": f"Bearer {token}",
        }
        try:
            tag = fetcher.get_json(url, headers).get("tag_name") or ""
        except FetchError as exc:
            if _is_404(exc):
                raise FetchError(f"{owner}/{repo}: no published release") from exc
            warn(f"{owner}/{repo}: releases API failed, using the redirect: {exc}")
        else:
            if not tag.startswith("v") or len(tag) < 2:
                raise FetchError(
                    f"{owner}/{repo}: latest tag {tag!r} is not v<version>"
                )
            return tag[1:]
    location = fetcher.redirect_location(
        f"https://github.com/{owner}/{repo}/releases/latest"
    )
    m = _LATEST_TAG_RE.search(location)
    if not m:
        raise FetchError(
            f"{owner}/{repo}: releases/latest redirected to {location!r}, "
            f"not a /releases/tag/v<version> (no release published?)"
        )
    return m.group("version")


def _parse_index(index_url: str, data: bytes) -> ET.Element:
    """An upstream Kodi addons.xml, plain or gzipped (the official
    repository publishes addons.xml.gz; detected by the gzip magic bytes,
    with the .gz suffix as the second opinion), parsed once."""
    if data[:2] == b"\x1f\x8b" or index_url.endswith(".gz"):
        try:
            data = gzip.decompress(data)
        except (OSError, EOFError) as exc:
            raise FetchError(f"{index_url}: not gzip ({exc})") from exc
    try:
        return ET.fromstring(data)
    except ET.ParseError as exc:
        raise FetchError(f"{index_url}: not XML ({exc})") from exc


def _version_from_index(
    index_url: str,
    entry_id: str,
    fetcher: Fetcher,
    ctx: BuildContext | None = None,
) -> str:
    """The version an upstream Kodi addons.xml declares for ``entry_id``.
    Fetched fresh every build, never from the cache; within one build the
    document is fetched and parsed once per URL (``BuildContext.index``)."""
    if ctx is not None:
        root = ctx.index(index_url)
    else:
        root = _parse_index(index_url, fetcher._download(index_url))
    for node in root.iter("addon"):
        if node.get("id") == entry_id:
            version = node.get("version")
            if version:
                return version
            break
    raise FetchError(f"{index_url}: does not list {entry_id} with a version")


class BuildContext:
    """Per-build memo for everything resolved upstream.

    Eleven official-library modules point at ONE index
    (mirrors.kodi.tv/addons/piers/addons.xml.gz: 13MB unpacked, 340 add-ons,
    measured 2026-09-26); without this each entry would fetch and parse it
    again. A build-resolved entry's (version, zip, addon.xml) is likewise
    resolved once, whether it is first met as its own catalog entry or as
    another entry's <import> (the closure walk reaches script.module.requests
    from service.tvos.pythonfix before requests' own turn). A failure is
    memoized too, so the entry falls back the same way whichever path met it
    first. Scoped to ONE build, never to the Fetcher: the determinism gate's
    second build, and every test that builds twice, must re-read the index."""

    def __init__(
        self,
        entries: list[dict],
        fetcher: Fetcher,
        warnings: list[str],
        repo_root: str = REPO_ROOT,
    ):
        self.entries = {e["id"]: e for e in entries}
        self.fetcher = fetcher
        self.warnings = warnings
        self.repo_root = repo_root
        self.indexes: dict[str, ET.Element] = {}
        self.index_fetches = 0
        self.upstream: dict[str, tuple[str, bytes, bytes, str] | FetchError] = {}

    def index(self, index_url: str) -> ET.Element:
        if index_url not in self.indexes:
            self.index_fetches += 1
            self.indexes[index_url] = _parse_index(
                index_url, self.fetcher._download(index_url)
            )
        return self.indexes[index_url]

    def resolve_upstream(self, entry: dict) -> tuple[str, bytes, bytes, str]:
        """(version, zip_bytes, addon_xml, source_url) of a build-resolved
        entry, memoized for the build; a memoized FetchError is re-raised."""
        aid = entry["id"]
        if aid not in self.upstream:
            try:
                self.upstream[aid] = _resolve_upstream(entry, self.fetcher, self)
            except FetchError as exc:
                self.upstream[aid] = exc
        got = self.upstream[aid]
        if isinstance(got, FetchError):
            raise got
        return got

    def addon_xml_for(self, aid: str) -> bytes | None:
        """The addon.xml of a build-resolved catalog id, resolving it now if
        this build has not met it yet; None for any other id."""
        entry = self.entries.get(aid)
        if entry is None or not metadata_resolved_at_build(entry):
            return None
        return self.resolve_upstream(entry)[2]


def _resolve_upstream(
    entry: dict, fetcher: Fetcher, ctx: BuildContext | None = None
) -> tuple[str, bytes, bytes, str]:
    """Version lookup + zip + packaged addon.xml for a build-resolved entry
    (release-asset, or hybrid with an ``upstream_index``). No committed
    metadata is read: the version is looked up fresh and the addon.xml is
    the one packaged in the zip that version names. Call through
    ``BuildContext.resolve_upstream`` so a build does it once per id."""
    entry_id = entry["id"]
    zip_tmpl = (entry.get("assets") or {}).get("zip", "")
    fetch_url, fetch_headers = None, None
    if classify(entry) == KIND_RELEASE_ASSET:
        m = _RELEASE_ASSET_RE.match(zip_tmpl)
        tag_prefix = _subst(m.group("tag_prefix"), entry)
        if tag_prefix:
            version, fetch_url = _latest_namespaced_release(
                m.group("owner"),
                m.group("repo"),
                tag_prefix,
                _subst(m.group("asset_template").rsplit("/", 1)[-1], entry),
                fetcher,
            )
            fetch_headers = {
                **_github_headers(),
                "Accept": "application/octet-stream",
            }
        else:
            version = _latest_release_version(
                m.group("owner"), m.group("repo"), fetcher
            )
    else:
        version = _version_from_index(entry["upstream_index"], entry_id, fetcher, ctx)
    # source_url is the asset's canonical (browser) location, which the
    # manifest publishes; a namespaced release is DOWNLOADED through its
    # API asset URL instead (see _latest_namespaced_release). The zip is
    # accepted only if it packages exactly this id at this version, so a
    # mirror serving the wrong file is a FetchError (fallback applies) and
    # never reaches the cache.
    source_url = _subst(zip_tmpl, entry, version)
    zip_bytes = fetcher.fetch(
        fetch_url or source_url,
        expect_zip=True,
        headers=fetch_headers,
        expect_addon=(entry_id, version),
    )
    addon_xml = _addon_xml_from_zip(entry_id, zip_bytes, version)
    return version, zip_bytes, addon_xml, source_url


def _addon_xml_from_zip(entry_id: str, zip_bytes: bytes, version: str) -> bytes:
    """``<id>/addon.xml`` out of a fetched zip, checked against the version
    the lookup resolved: a zip that packages a different version than its
    tag or index claims is a FetchError, so the last-good fallback applies."""
    member = f"{entry_id}/addon.xml"
    try:
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
            data = zf.read(member)
        packaged = ET.fromstring(data).get("version")
    except (zipfile.BadZipFile, KeyError, OSError) as exc:
        raise FetchError(f"{entry_id}: zip carries no {member} ({exc})") from exc
    except ET.ParseError as exc:
        raise FetchError(f"{entry_id}: packaged addon.xml unparseable ({exc})") from exc
    if packaged != version:
        raise FetchError(
            f"{entry_id}: resolved version {version!r} but the zip packages "
            f"addon.xml {packaged!r}"
        )
    return data


def _imports_of(addon_xml: bytes) -> list[str]:
    root = ET.fromstring(addon_xml)
    return [
        imp.get("addon")
        for imp in root.iter("import")
        if imp.get("addon") and imp.get("addon") not in BUILTINS
    ]


def _check_imports_hosted(
    entry_id: str,
    addon_xml: bytes,
    catalog_ids: set[str],
    repo_root: str = REPO_ROOT,
    resolver: Callable[[str], bytes | None] | None = None,
) -> None:
    """Every non-builtin <import> in the TRANSITIVE closure of a build-resolved
    addon.xml must be an id this catalog serves. Kodi resolves a hard
    dependency only from the repository the add-on is installed FROM
    (measured on a Kodi 22 bench), so for metadata that arrives at build time
    this is THE closure gate: since 2026-09-26 no add-on of ours and none of
    their dependencies has a committed addon.xml, so test_closure.py has
    nothing to walk offline and this walk carries the whole closure
    (skin -> autocompletion plugin -> autocompletion module -> requests ->
    urllib3/certifi/chardet/idna; service.tvos.pythonfix -> requests -> ...).

    The walk continues through an import that has a committed
    addons/hosted/<id>/addon.xml (the third-party repository installers) and,
    through ``resolver`` (``BuildContext.addon_xml_for``), through every
    build-resolved import, whose addon.xml is read out of its resolved zip
    right here, before its own turn if need be. A catalog id that is neither
    (first-party, streamed) is a leaf. An import that is not a catalog entry,
    or a build-resolved import that cannot be resolved, is a per-entry
    FetchError: the live last-good copy is served instead."""
    seen: set[str] = set()
    missing: set[str] = set()
    stack = _imports_of(addon_xml)
    while stack:
        aid = stack.pop()
        if aid in seen:
            continue
        seen.add(aid)
        if aid not in catalog_ids:
            missing.add(aid)
            continue
        hosted_xml = os.path.join(repo_root, "addons", "hosted", aid, "addon.xml")
        if os.path.isfile(hosted_xml):
            with open(hosted_xml, "rb") as fh:
                try:
                    stack.extend(_imports_of(fh.read()))
                except ET.ParseError as exc:
                    raise FetchError(f"{entry_id}: {hosted_xml} unparseable ({exc})")
        elif resolver is not None:
            try:
                xml = resolver(aid)
            except FetchError as exc:
                raise FetchError(
                    f"{entry_id}: import {aid} could not be resolved ({exc})"
                ) from exc
            if xml is not None:
                try:
                    stack.extend(_imports_of(xml))
                except ET.ParseError as exc:
                    raise FetchError(f"{entry_id}: {aid} addon.xml unparseable ({exc})")
    if missing:
        raise FetchError(
            f"{entry_id}: imports {sorted(missing)}, which this catalog does not "
            f"serve (add them to catalog.json, see test_closure.py)"
        )


def _resolve_primary(
    entry: dict,
    kind: str,
    fetcher: Fetcher,
    warnings: list[str],
    repo_root: str = REPO_ROOT,
    catalog_ids: set[str] | None = None,
    ctx: BuildContext | None = None,
) -> ResolvedEntry:
    entry_id = entry["id"]
    zip_tmpl = (entry.get("assets") or {}).get("zip", "")
    if ctx is None:
        ctx = BuildContext([entry], fetcher, warnings, repo_root)

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

    if metadata_resolved_at_build(entry):
        # No committed metadata: the version is looked up fresh and the
        # addon.xml is the one packaged in the zip that version names, once
        # per build (the closure walk of another entry may have resolved this
        # one already). Its whole import closure is then walked through the
        # catalog, resolving build-resolved imports on the way.
        version, zip_bytes, addon_xml, source_url = ctx.resolve_upstream(entry)
        _check_imports_hosted(
            entry_id,
            addon_xml,
            set(ctx.entries) if catalog_ids is None else catalog_ids,
            repo_root,
            ctx.addon_xml_for,
        )
        return ResolvedEntry(
            entry_id,
            kind,
            version,
            addon_xml,
            zip_bytes,
            source_url,
            art={"addon.xml": addon_xml},
        )

    if kind in (KIND_HOSTED, KIND_HYBRID):
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
    ctx: BuildContext | None = None,
) -> list[ResolvedEntry]:
    resolved = []
    catalog_ids = {e["id"] for e in entries}
    if ctx is None:
        ctx = BuildContext(entries, fetcher, warnings, repo_root)
    for entry in entries:
        kind = classify(entry)
        # Zip validation lives INSIDE the per-entry try: a corrupt primary zip
        # is a flake that must fall back, never a whole-build failure. Only
        # BuildError (size gate, first-party build bugs) escapes by design.
        try:
            item = _resolve_primary(
                entry, kind, fetcher, warnings, repo_root, catalog_ids, ctx
            )
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

    ctx = BuildContext(entries, fetcher, warnings, repo_root)
    resolved = resolve_all(
        entries, fetcher, baseline, base_url, warnings, repo_root, ctx
    )
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
        + f", {ctx.index_fetches} upstream index fetch(es)"
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
