"""Coverage for the virtual proxy add-on (repository.tony7bones).

This is the runtime engine that actually serves add-on metadata and zips to
Kodi at install/upgrade time: it parses the ``repository.json`` manifest,
resolves each entry's GitHub ref (branch / latest release / matching tag /
default branch), streams ``addons.xml`` + assets through a local HTTP server,
and decides — via the version comparison in ``lib/version.py`` — whether the
proxy should self-update.  None of that was previously exercised by any test.

The proxy's ``lib`` package is pure Python except for a handful of modules that
import Kodi's ``xbmc*`` runtime; the high-value logic here (version math, the
manifest schema validators, tag resolution, the GitHub URL builder, the loading
cache, and OS platform detection) imports nothing from Kodi, so it is imported
directly off ``repo/repository.tony7bones`` and exercised without mocks.  The
two modules that do touch Kodi (``lib/kodi.py``, ``lib/entries.py``) and the
network/HTTP-server modules are intentionally out of scope for this file.
"""

from __future__ import annotations

import importlib
import json
import os
import sys
import types
from pathlib import Path

import pytest

HERE = Path(__file__).parent
REPO_ROOT = HERE.parent
PROXY_ROOT = REPO_ROOT / "addons" / "repository.tony7bones"


# --------------------------------------------------------------------------- #
# Import fixture — put the proxy add-on root on sys.path so its ``lib`` package
# resolves, and purge any cached copy so each test binds a fresh module set.
# --------------------------------------------------------------------------- #
@pytest.fixture
def proxy(monkeypatch):
    monkeypatch.syspath_prepend(str(PROXY_ROOT))
    for name in list(sys.modules):
        if name == "lib" or name.startswith("lib."):
            monkeypatch.delitem(sys.modules, name, raising=False)

    mods = {}
    for name in (
        "lib.version",
        "lib.utils",
        "lib.cache",
        "lib.github",
        "lib.repository",
        "lib.platform.definitions",
        "lib.platform.os_platform",
    ):
        mods[name.split(".")[-1]] = importlib.import_module(name)
    return types.SimpleNamespace(**mods)


# --------------------------------------------------------------------------- #
# Fakes
# --------------------------------------------------------------------------- #
class _FakeUrlResp:
    """Stand-in for the object urllib's urlopen returns."""

    def __init__(self, data=b"", code=200, headers=None):
        self._data = data
        self._code = code
        self._headers = headers or {}
        self.closed = False

    def read(self):
        return self._data

    def getcode(self):
        return self._code

    def info(self):
        return self._headers

    def close(self):
        self.closed = True


# =========================================================================== #
# lib/version.py  — drives the proxy's self-update decision
# =========================================================================== #
def test_version_parses_release_tuple(proxy):
    v = proxy.version.Version("1.2.3")
    assert v._release == (1, 2, 3)


def test_version_strips_v_prefix_and_is_case_insensitive(proxy):
    assert proxy.version.Version("V1.2.0") == proxy.version.Version("1.2.0")


def test_version_trailing_zeros_compare_equal(proxy):
    # 1.0 and 1.0.0 must resolve to the same upgrade key, else Kodi loops.
    assert proxy.version.Version("1.0") == proxy.version.Version("1.0.0")


def test_version_ordering_is_numeric_not_lexical(proxy):
    Version = proxy.version.Version
    assert Version("1.2") < Version("1.10")
    assert Version("2.0.0") > Version("1.9.9")
    assert sorted([Version("1.10"), Version("1.2"), Version("1.1")]) == [
        Version("1.1"),
        Version("1.2"),
        Version("1.10"),
    ]


def test_version_invalid_raises(proxy):
    with pytest.raises(ValueError):
        proxy.version.Version("not-a-version")


def test_try_parse_version_returns_default_on_garbage(proxy):
    sentinel = object()
    assert proxy.version.try_parse_version("garbage", default=sentinel) is sentinel
    assert proxy.version.try_parse_version("garbage") is None


def test_try_parse_version_returns_version_on_valid(proxy):
    assert proxy.version.try_parse_version("3.1.4") == proxy.version.Version("3.1.4")


def test_version_cross_type_compare_is_falsy_not_raising(proxy):
    # Documents current behaviour: comparing against a foreign type does not
    # raise.  (lib/version.py returns None rather than NotImplemented here —
    # a latent quirk worth fixing, but pinned so a change is deliberate.)
    assert not (proxy.version.Version("1.0") == "1.0")


def test_debian_version_orders_pre_release_below_release(proxy):
    DebianVersion = proxy.version.DebianVersion
    # The "~" segment sorts *before* the empty suffix, marking a pre-release.
    assert DebianVersion("1.0~beta") < DebianVersion("1.0")
    assert DebianVersion("1.0") < DebianVersion("1.1")


def test_infinity_helpers(proxy):
    assert proxy.version.Infinity == proxy.version.InfinityType()
    assert proxy.version.NegativeInfinity < proxy.version.Infinity
    assert -proxy.version.Infinity == proxy.version.NegativeInfinity


# =========================================================================== #
# lib/utils.py
# =========================================================================== #
def test_remove_prefix(proxy):
    assert proxy.utils.remove_prefix("refs/tags/v1", "refs/tags/") == "v1"
    assert proxy.utils.remove_prefix("v1", "refs/tags/") == "v1"


@pytest.mark.parametrize(
    "url,expected",
    [
        ("http://example.com/x", True),
        ("https://example.com", True),
        ("ftp://example.com", False),
        ("/local/path", False),
        ("not a url", False),
    ],
)
def test_is_http_like(proxy, url, expected):
    assert bool(proxy.utils.is_http_like(url)) is expected


def test_response_status_json_and_content_cached(proxy):
    raw = _FakeUrlResp(data=b'{"a": 1}', code=200)
    resp = proxy.utils.Response(raw)
    assert resp.status_code == 200
    assert resp.json() == {"a": 1}
    # content is read once and cached
    assert resp.content == b'{"a": 1}'
    assert resp.content == b'{"a": 1}'


def test_response_raise_for_status(proxy):
    ok = proxy.utils.Response(_FakeUrlResp(code=200))
    ok.raise_for_status()  # no raise

    for code in (404, 503):
        resp = proxy.utils.Response(_FakeUrlResp(code=code))
        with pytest.raises(proxy.utils.HTTPResponseError) as ei:
            resp.raise_for_status()
        assert ei.value.response is resp


def test_response_context_manager_closes(proxy):
    raw = _FakeUrlResp()
    with proxy.utils.Response(raw) as resp:
        assert resp.raw is raw
    assert raw.closed is True


def test_request_appends_params_and_wraps_response(proxy, monkeypatch):
    seen = {}

    def fake_urlopen(req, **kwargs):
        seen["url"] = req.full_url
        return _FakeUrlResp(data=b"ok", code=200)

    monkeypatch.setattr(proxy.utils, "urlopen", fake_urlopen)
    resp = proxy.utils.request("http://h/api", params={"ref": "main"})
    assert "?ref=main" in seen["url"]
    assert resp.content == b"ok"


def test_request_maps_httperror_to_response(proxy, monkeypatch):
    err = proxy.utils.HTTPError("http://h", 404, "nf", {}, None)
    monkeypatch.setattr(
        proxy.utils, "urlopen", lambda *a, **k: (_ for _ in ()).throw(err)
    )
    resp = proxy.utils.request("http://h")
    assert resp.status_code == 404


# =========================================================================== #
# lib/cache.py
# =========================================================================== #
def test_loading_cache_memoizes_per_key(proxy):
    calls = []

    def f(x):
        calls.append(x)
        return x * 2

    cache = proxy.cache.LoadingCache(f, ttl_seconds=1000)
    assert cache.get(2) == 4
    assert cache.get(2) == 4
    assert cache.get(3) == 6
    assert calls == [2, 3]  # 2 computed once, 3 once


def test_loading_cache_expires(proxy, monkeypatch):
    calls = []
    cache = proxy.cache.LoadingCache(
        lambda: calls.append(1) or len(calls), ttl_seconds=10
    )

    now = [1000.0]
    monkeypatch.setattr(proxy.cache.time, "time", lambda: now[0])
    assert cache.get() == 1
    now[0] += 5
    assert cache.get() == 1  # within ttl
    now[0] += 100
    assert cache.get() == 2  # expired -> recomputed


def test_loading_cache_clear_forces_refetch(proxy):
    calls = []
    cache = proxy.cache.LoadingCache(lambda: calls.append(1) or len(calls))
    assert cache.get() == 1
    cache.clear()
    assert cache.get() == 2


@pytest.mark.xfail(
    reason="lib/cache.py:85 eviction bug — min(self._store, key=attrgetter('modified')) "
    "is applied to the cache KEYS, not the _CacheValue values, so it raises "
    "AttributeError once a LoadingCache reaches max_size (default 128). "
    "Fix: key=lambda k: self._store[k].modified.",
    raises=AttributeError,
    strict=True,
)
def test_loading_cache_evicts_when_full(proxy):
    cache = proxy.cache.LoadingCache(lambda x: x, max_size=2)
    cache.get(1)
    cache.get(2)
    cache.get(3)  # triggers eviction of the oldest
    assert len(cache._store) == 2


def test_make_key_fast_path_for_single_scalar(proxy):
    assert proxy.cache._make_key((5,), {}, typed=False) == 5
    assert proxy.cache._make_key(("a",), {}, typed=False) == "a"
    # kwargs force the hashed-tuple form
    assert isinstance(proxy.cache._make_key((1,), {"k": "v"}, typed=False), tuple)


# =========================================================================== #
# lib/github.py
# =========================================================================== #
def _patch_github_request(proxy, monkeypatch, *, code=200, payload=None, data=b""):
    seen = {}

    class _Resp:
        status_code = code

        def __init__(self):
            self.closed = False

        def json(self, **kwargs):
            hook = kwargs.get("object_pairs_hook", dict)
            return json.loads(json.dumps(payload or {}), object_pairs_hook=hook)

        def close(self):
            self.closed = True

        def __enter__(self):
            return self

        def __exit__(self, *a):
            self.close()

    last = {}

    def fake_request(url, params=None, data=None, headers=None, **kw):
        seen["url"] = url
        seen["params"] = params
        seen["headers"] = headers
        r = _Resp()
        last["resp"] = r
        return r

    monkeypatch.setattr(proxy.github, "request", fake_request)
    return seen, last


def test_github_builds_base_url(proxy):
    api = proxy.github.GitHubRepositoryApi("octocat", "Hello-World")
    assert api._base_url == "https://api.github.com/repos/octocat/Hello-World"


def test_github_request_paths_and_headers(proxy, monkeypatch):
    seen, _ = _patch_github_request(
        proxy, monkeypatch, payload={"default_branch": "main"}
    )
    api = proxy.github.GitHubRepositoryApi("u", "r", token="secret")
    info = api.get_repository_info()
    assert info.default_branch == "main"  # _Dict attribute access
    assert seen["url"] == "https://api.github.com/repos/u/r"
    assert seen["headers"]["Authorization"] == "Bearer secret"
    assert seen["headers"]["X-GitHub-Api-Version"] == "2022-11-28"


def test_github_release_by_tag_path(proxy, monkeypatch):
    seen, _ = _patch_github_request(proxy, monkeypatch, payload={"tag_name": "v9"})
    api = proxy.github.GitHubRepositoryApi("u", "r")
    rel = api.get_release_by_tag("v9")
    assert seen["url"].endswith("/releases/tags/v9")
    assert rel.tag_name == "v9"


def test_github_error_raises_and_closes(proxy, monkeypatch):
    _, last = _patch_github_request(proxy, monkeypatch, code=404)
    api = proxy.github.GitHubRepositoryApi("u", "r")
    with pytest.raises(proxy.github.GitHubApiError):
        api.get_repository_info()
    assert last["resp"].closed is True


def test_github_equality_and_hash(proxy):
    a = proxy.github.GitHubRepositoryApi("u", "r", token="t")
    b = proxy.github.GitHubRepositoryApi("u", "r", token="t")
    c = proxy.github.GitHubRepositoryApi("u", "r", token="other")
    assert a == b
    assert a != c
    assert hash(a) == hash(b)
    assert a.__eq__(object()) is NotImplemented


# =========================================================================== #
# lib/repository.py  — manifest schema + tag resolution
# =========================================================================== #
def _platform(proxy, name="linux-x64", system="linux", arch="x64"):
    p = types.SimpleNamespace()
    p.name = lambda sep="-": name
    p.system = system
    p.arch = arch
    return p


def test_schema_validators_accept_and_reject(proxy):
    R = proxy.repository
    R.validate_string("id", "ok")
    R.validate_string_map("assets", {"a": "b"})
    R.validate_string_list("platforms", ["linux-x64"])
    with pytest.raises(R.InvalidSchemaError):
        R.validate_string("id", 5)
    with pytest.raises(R.InvalidSchemaError):
        R.validate_string_map("assets", {"a": 1})
    with pytest.raises(R.InvalidSchemaError):
        R.validate_string_list("platforms", "linux-x64")


def test_entry_schema_required_unknown_and_type(proxy):
    R = proxy.repository
    with pytest.raises(R.InvalidSchemaError):
        R.validate_entry_schema({"id": "x"})  # missing username
    with pytest.raises(R.InvalidSchemaError):
        R.validate_entry_schema({"id": "x", "username": "u", "bogus": "v"})
    with pytest.raises(R.InvalidSchemaError):
        R.validate_entry_schema({"id": "x", "username": 1})
    # happy path
    R.validate_entry_schema({"id": "x", "username": "u", "branch": "main"})


def test_validate_schema_rejects_non_list(proxy):
    with pytest.raises(proxy.repository.InvalidSchemaError):
        proxy.repository.validate_schema({"id": "x"})


def test_repository_loads_entries_and_applies_defaults(proxy, tmp_path):
    manifest = [
        {
            "id": "plugin.video.foo",
            "username": "bar",
            "tag_pattern": r"v(?P<version>\d+)",
        }
    ]
    path = tmp_path / "repository.json"
    path.write_text(json.dumps(manifest))

    repo = proxy.repository.Repository(
        files=(str(path),), platform=_platform(proxy), max_threads=1
    )
    addon = repo._addons["plugin.video.foo"]
    assert addon.username == "bar"
    assert addon.repository == "plugin.video.foo"  # defaults to id
    assert addon.assets == {}
    assert addon.tag_pattern.match("v3")  # compiled


def test_repository_filters_unsupported_platform(proxy, tmp_path):
    manifest = [
        {"id": "a", "username": "u", "platforms": ["windows-x64"]},
        {"id": "b", "username": "u", "platforms": ["linux-x64"]},
    ]
    path = tmp_path / "repository.json"
    path.write_text(json.dumps(manifest))

    repo = proxy.repository.Repository(
        files=(str(path),), platform=_platform(proxy), max_threads=1
    )
    assert "a" not in repo._addons
    assert "b" in repo._addons


def test_repository_get_asset_unknown_raises(proxy, tmp_path):
    path = tmp_path / "repository.json"
    path.write_text("[]")
    repo = proxy.repository.Repository(
        files=(str(path),), platform=_platform(proxy), max_threads=1
    )
    with pytest.raises(proxy.repository.AddonNotFound):
        repo.get_asset("nope", "addon.xml")


def test_repository_missing_file_does_not_raise(proxy, tmp_path):
    # entries.json (the user's optional imported-entries store) can be absent
    # if its first-run creation failed on a restrictive filesystem (tvOS). The
    # whole service imports Repository(...) synchronously at add-on-enable
    # time, so this must degrade, not crash.
    missing = tmp_path / "does-not-exist.json"
    repo = proxy.repository.Repository(
        files=(str(missing),), platform=_platform(proxy), max_threads=1
    )
    assert repo._addons == {}


def test_repository_malformed_file_does_not_raise(proxy, tmp_path):
    path = tmp_path / "repository.json"
    path.write_text("not valid json")
    repo = proxy.repository.Repository(
        files=(str(path),), platform=_platform(proxy), max_threads=1
    )
    assert repo._addons == {}


def test_repository_one_bad_file_does_not_block_a_good_one(proxy, tmp_path):
    good = tmp_path / "repository.json"
    good.write_text(json.dumps([{"id": "plugin.video.foo", "username": "bar"}]))
    bad = tmp_path / "entries.json"
    bad.write_text("{not json")

    repo = proxy.repository.Repository(
        files=(str(good), str(bad)), platform=_platform(proxy), max_threads=1
    )
    assert "plugin.video.foo" in repo._addons


def test_repository_addons_xml_and_md5(proxy, tmp_path):
    from xml.etree import ElementTree as ET
    from hashlib import md5

    manifest = [{"id": "a", "username": "u"}, {"id": "b", "username": "u"}]
    path = tmp_path / "repository.json"
    path.write_text(json.dumps(manifest))
    repo = proxy.repository.Repository(
        files=(str(path),), platform=_platform(proxy), max_threads=1
    )

    # Skip the network: synthesize each add-on's <addon> element.
    repo._get_addon_xml = lambda addon: ET.Element("addon", id=addon.id)
    xml = repo.get_addons_xml()
    assert b'id="a"' in xml and b'id="b"' in xml
    assert repo.get_addons_xml_md5() == md5(xml).hexdigest().encode("utf-8")


def test_repository_addons_xml_skips_failed_fetches(proxy, tmp_path):
    from xml.etree import ElementTree as ET

    manifest = [{"id": "a", "username": "u"}, {"id": "b", "username": "u"}]
    path = tmp_path / "repository.json"
    path.write_text(json.dumps(manifest))
    repo = proxy.repository.Repository(
        files=(str(path),), platform=_platform(proxy), max_threads=1
    )

    repo._get_addon_xml = lambda addon: (
        None if addon.id == "a" else ET.Element("addon", id=addon.id)
    )
    xml = repo.get_addons_xml()
    assert b'id="a"' not in xml
    assert b'id="b"' in xml


def test_repository_format_invalid_param_raises(proxy):
    with pytest.raises(proxy.repository.InvalidSchemaError):
        proxy.repository.Repository._format("{nope}", id="x")


# --- TagMatchPredicate ----------------------------------------------------- #
def test_tag_match_plain_version(proxy):
    pred = proxy.repository.TagMatchPredicate("1.2.3")
    assert pred("1.2.3")
    assert not pred("1.2.4")


def test_tag_match_with_named_group(proxy):
    import re

    pred = proxy.repository.TagMatchPredicate(
        "1.2.3", tag_pattern=re.compile(r"release-(?P<version>[\d.]+)")
    )
    assert pred("release-1.2.3")
    assert not pred("nightly-1.2.3")


def test_tag_match_parsed_equivalence(proxy):
    # "1.2.0" and "1.2" parse to the same version even though the strings differ.
    pred = proxy.repository.TagMatchPredicate("1.2.0")
    assert pred("1.2")


# --- fallback ref resolution ---------------------------------------------- #
class _FakeRepo:
    def __init__(self, proxy, *, tags=(), latest=None, default_branch=None):
        self._proxy = proxy
        self._tags = tags
        self._latest = latest
        self._default_branch = default_branch

    def _ref(self, name):
        return types.SimpleNamespace(ref="refs/tags/" + name)

    def get_refs_tags(self):
        if self._tags is None:
            raise self._proxy.github.GitHubApiError("boom")
        return [self._ref(t) for t in self._tags]

    def get_latest_release(self):
        if self._latest is None:
            raise self._proxy.github.GitHubApiError("none")
        return types.SimpleNamespace(tag_name=self._latest)

    def get_repository_info(self):
        if self._default_branch is None:
            raise self._proxy.github.GitHubApiError("none")
        return types.SimpleNamespace(default_branch=self._default_branch)


def _empty_repo(proxy, tmp_path):
    path = tmp_path / "repository.json"
    path.write_text("[]")
    return proxy.repository.Repository(
        files=(str(path),), platform=_platform(proxy), max_threads=1
    )


def test_fallback_ref_prefers_latest_release_without_pattern(proxy, tmp_path):
    repo = _empty_repo(proxy, tmp_path)
    fake = _FakeRepo(proxy, tags=["v1", "v2"], latest="v2")
    assert repo._get_fallback_ref(fake) == "v2"


def test_fallback_ref_uses_matching_tag_when_no_release(proxy, tmp_path):
    repo = _empty_repo(proxy, tmp_path)
    fake = _FakeRepo(proxy, tags=["v1", "v2"], latest=None)
    # No release -> falls back to a matching tag; _get_matching_tag walks the
    # ref list reversed, so the last tag ("v2") wins under a match-all predicate.
    assert repo._get_fallback_ref(fake) == "v2"


def test_fallback_ref_falls_back_to_default_branch(proxy, tmp_path):
    repo = _empty_repo(proxy, tmp_path)
    fake = _FakeRepo(proxy, tags=[], latest=None, default_branch="develop")
    assert repo._get_fallback_ref(fake) == "develop"


def test_fallback_ref_final_default_when_all_fail(proxy, tmp_path):
    repo = _empty_repo(proxy, tmp_path)
    fake = _FakeRepo(proxy, tags=None, latest=None, default_branch=None)
    assert repo._get_fallback_ref(fake) == "main"  # the constructor default


def test_fallback_ref_with_pattern_prefers_matching_tag(proxy, tmp_path):
    import re

    repo = _empty_repo(proxy, tmp_path)
    fake = _FakeRepo(proxy, tags=["nightly", "stable-1.0"], latest="ignored")
    assert (
        repo._get_fallback_ref(fake, tag_pattern=re.compile(r"stable-.*"))
        == "stable-1.0"
    )


# =========================================================================== #
# lib/platform/definitions.py + os_platform.py
# =========================================================================== #
def test_platform_definitions_enum_values_and_name(proxy):
    d = proxy.definitions
    assert set(d.System.values()) == {"linux", "android", "darwin", "windows"}
    assert "x64" in d.Arch.values()
    assert d.Platform("linux", "5", "x64").name() == "linux-x64"
    assert d.Platform("linux", "5", "x64").name(sep="/") == "linux/x64"


def _set_uname(proxy, monkeypatch, *, system, machine, maxsize=2**63, android=False):
    op = proxy.os_platform
    monkeypatch.setattr(op.platform, "system", lambda: system)
    monkeypatch.setattr(op.platform, "machine", lambda: machine)
    monkeypatch.setattr(op.platform, "release", lambda: "0")
    monkeypatch.setattr(op.sys, "maxsize", maxsize)
    if android:
        monkeypatch.setenv("ANDROID_STORAGE", "/storage")
    else:
        monkeypatch.delenv("ANDROID_STORAGE", raising=False)


def test_os_platform_linux_x64(proxy, monkeypatch):
    _set_uname(proxy, monkeypatch, system="Linux", machine="x86_64")
    p = proxy.os_platform.get_platform()
    assert p.system == "linux" and p.arch == "x64"


def test_os_platform_linux_arm64(proxy, monkeypatch):
    _set_uname(proxy, monkeypatch, system="Linux", machine="aarch64")
    p = proxy.os_platform.get_platform()
    assert p.system == "linux" and p.arch == "arm64"


def test_os_platform_windows_64(proxy, monkeypatch):
    _set_uname(proxy, monkeypatch, system="Windows", machine="AMD64")
    p = proxy.os_platform.get_platform()
    assert p.system == "windows" and p.arch == "x64"


def test_os_platform_darwin_arm64(proxy, monkeypatch):
    # Apple Silicon Mac / Apple TV (tvOS) / iOS all report an "arm64" machine
    # under Darwin — must resolve to arm64, not the Intel x64 default, or any
    # platform-gated dependency (a binary add-on with separate arm64/x64
    # zips) silently resolves the wrong one.
    _set_uname(proxy, monkeypatch, system="Darwin", machine="arm64")
    p = proxy.os_platform.get_platform()
    assert p.system == "darwin" and p.arch == "arm64"


def test_os_platform_darwin_x64(proxy, monkeypatch):
    _set_uname(proxy, monkeypatch, system="Darwin", machine="x86_64")
    p = proxy.os_platform.get_platform()
    assert p.system == "darwin" and p.arch == "x64"


def test_os_platform_android_arm64(proxy, monkeypatch):
    _set_uname(proxy, monkeypatch, system="Linux", machine="aarch64", android=True)
    p = proxy.os_platform.get_platform()
    assert p.system == "android" and p.arch == "arm64"


# =========================================================================== #
# lib/platform/kodi_platform.py — the PRIMARY path (parses Kodi's own log
# line); os_platform.py above is only the fallback used when this raises
# PlatformError. Needs a minimal fake ``xbmc`` since the module imports it
# directly; deliberately does not register ``xbmcvfs`` so the import exercises
# the real fallback `from xbmc import translatePath` branch.
# =========================================================================== #
def _import_kodi_platform(monkeypatch, tmp_path, second_log_line):
    log_path = tmp_path / "kodi.log"
    log_path.write_text("startup\n" + second_log_line + "\n", encoding="utf-8")

    fake_xbmc = types.SimpleNamespace(
        executeJSONRPC=lambda cmd: json.dumps({"result": {"name": "Kodi"}}),
        translatePath=lambda p: str(tmp_path) + os.sep,
    )
    monkeypatch.setitem(sys.modules, "xbmc", fake_xbmc)
    monkeypatch.delitem(sys.modules, "xbmcvfs", raising=False)
    monkeypatch.delitem(sys.modules, "lib.platform.kodi_platform", raising=False)
    return importlib.import_module("lib.platform.kodi_platform")


def test_kodi_platform_apple_tv_arm64(proxy, monkeypatch, tmp_path):
    # An Apple TV (tvOS) box hitting "Install from zip" runs this at
    # add-on-service-startup time; before this fix, ANY ARM Darwin device
    # (tvOS, iOS, Apple Silicon Mac) raised PlatformError here uncaught by the
    # inner branch, which used to surface as an install-time add-on error.
    kodi_platform = _import_kodi_platform(
        monkeypatch, tmp_path, "...Platform: tvOS ARM 64-bit"
    )
    p = kodi_platform.get_platform()
    assert p.system == "darwin" and p.arch == "arm64"


def test_kodi_platform_macos_x64(proxy, monkeypatch, tmp_path):
    kodi_platform = _import_kodi_platform(
        monkeypatch, tmp_path, "...Platform: macOS x86 64-bit"
    )
    p = kodi_platform.get_platform()
    assert p.system == "darwin" and p.arch == "x64"


# =========================================================================== #
# lib/entries.py — the module-level entries.json bootstrap that runs the
# instant service.py (the xbmc.service extension) imports it, i.e. the instant
# Kodi enables the add-on. Needs a minimal fake xbmcaddon/xbmcvfs/xbmcgui/xbmc
# since lib.kodi (which this imports) touches all four at import time.
# =========================================================================== #
def _import_lib_entries(monkeypatch, tmp_path, *, makedirs=None, builtin_open=None):
    fake_addon = types.SimpleNamespace(
        getAddonInfo=lambda key: {
            "id": "repository.tony7bones",
            "name": "Tony.7.Bones repository",
            "path": str(tmp_path),
            "icon": "icon.png",
            "profile": "special://profile/addon_data/repository.tony7bones/",
        }[key],
        getLocalizedString=lambda i: str(i),
        getSetting=lambda key: "61234",
    )
    fake_xbmcaddon = types.SimpleNamespace(Addon=lambda: fake_addon)
    fake_xbmcvfs = types.SimpleNamespace(translatePath=lambda p: str(tmp_path) + os.sep)
    fake_xbmc = types.SimpleNamespace(
        log=lambda *a, **k: None,
        LOGFATAL=0,
        LOGERROR=1,
        LOGWARNING=2,
        LOGINFO=3,
        LOGDEBUG=4,
        LOGNONE=5,
    )
    fake_xbmcgui = types.SimpleNamespace(Dialog=lambda: None)

    monkeypatch.setitem(sys.modules, "xbmcaddon", fake_xbmcaddon)
    monkeypatch.setitem(sys.modules, "xbmcvfs", fake_xbmcvfs)
    monkeypatch.setitem(sys.modules, "xbmc", fake_xbmc)
    monkeypatch.setitem(sys.modules, "xbmcgui", fake_xbmcgui)
    for mod in (
        "lib.kodi",
        "lib.entries",
        "lib.platform.core",
        "lib.platform.kodi_platform",
    ):
        monkeypatch.delitem(sys.modules, mod, raising=False)

    if makedirs is not None:
        monkeypatch.setattr(os, "makedirs", makedirs)
    if builtin_open is not None:
        import builtins

        monkeypatch.setattr(builtins, "open", builtin_open)

    return importlib.import_module("lib.entries")


def test_entries_module_creates_storage_on_happy_path(proxy, monkeypatch, tmp_path):
    entries = _import_lib_entries(monkeypatch, tmp_path)
    assert os.path.exists(entries.ENTRIES_PATH)
    with open(entries.ENTRIES_PATH) as f:
        assert f.read() == "[]"


def test_entries_module_survives_sandboxed_write_failure(proxy, monkeypatch, tmp_path):
    # This is the leading hypothesis for the Apple TV (tvOS) "Install from
    # zip" -> "ERROR CHECK THE LOGS" failure: a sandboxed filesystem denies
    # this module-level write, and before this fix that exception propagated
    # out of the import, crashing the whole service (service.py imports
    # lib.entries at module scope). Importing must now survive it.
    def _denied_makedirs(path, *a, **k):
        raise PermissionError("Operation not permitted: {}".format(path))

    # Force the "directory missing" branch so makedirs is actually attempted.
    missing_dir = tmp_path / "does-not-exist-yet"
    entries = _import_lib_entries(monkeypatch, missing_dir, makedirs=_denied_makedirs)
    assert not os.path.exists(entries.ENTRIES_PATH)  # degraded, not crashed
    # And the rest of the module is still usable — Entries() just sees no file.
    e = entries.Entries()
    assert e.length() == 0


# =========================================================================== #
# lib/service.py — the actual `xbmc.service` entry point Kodi imports the
# instant it enables the add-on (line 25-26 there runs Repository(...) at
# module scope). This is the end-to-end proof: the real thing Kodi runs must
# survive a sandboxed filesystem denying entries.json's first-run write.
# =========================================================================== #
def test_service_module_survives_sandboxed_write_failure(proxy, monkeypatch, tmp_path):
    resources = tmp_path / "resources"
    resources.mkdir()
    (resources / "repository.json").write_text(
        json.dumps([{"id": "plugin.video.foo", "username": "bar"}])
    )

    fake_addon = types.SimpleNamespace(
        getAddonInfo=lambda key: {
            "id": "repository.tony7bones",
            "name": "Tony.7.Bones repository",
            "path": str(tmp_path),
            "icon": "icon.png",
            "profile": "special://profile/addon_data/repository.tony7bones/",
        }[key],
        getLocalizedString=lambda i: str(i),
        getSetting=lambda key: "61234",
    )
    fake_xbmc = types.SimpleNamespace(
        log=lambda *a, **k: None,
        LOGFATAL=0,
        LOGERROR=1,
        LOGWARNING=2,
        LOGINFO=3,
        LOGDEBUG=4,
        LOGNONE=5,
        Monitor=type("Monitor", (), {}),
    )
    monkeypatch.setitem(
        sys.modules, "xbmcaddon", types.SimpleNamespace(Addon=lambda: fake_addon)
    )
    # ADDON_PATH (used to locate resources/repository.json) comes straight
    # from getAddonInfo("path") = tmp_path, which exists. ADDON_DATA (where
    # entries.json is created) is a DIFFERENT, not-yet-existing directory
    # under translatePath("special://profile/...") — must not already exist,
    # or the module-level `if not os.path.exists(ADDON_DATA): os.makedirs(...)`
    # guard short-circuits and the write-denial path never even runs.
    profile_dir = tmp_path / "profile_data"
    assert not profile_dir.exists()
    monkeypatch.setitem(
        sys.modules,
        "xbmcvfs",
        types.SimpleNamespace(translatePath=lambda p: str(profile_dir) + os.sep),
    )
    monkeypatch.setitem(sys.modules, "xbmc", fake_xbmc)
    monkeypatch.setitem(
        sys.modules, "xbmcgui", types.SimpleNamespace(Dialog=lambda: None)
    )
    for mod in (
        "lib.kodi",
        "lib.entries",
        "lib.service",
        "lib.routes",
        "lib.httpserver",
        "lib.platform.core",
        "lib.platform.kodi_platform",
    ):
        monkeypatch.delitem(sys.modules, mod, raising=False)

    # The Apple TV (tvOS) sandbox condition: entries.json's first-run write
    # is denied — but this must not stop service.py itself from importing.
    def _denied_makedirs(path, *a, **k):
        raise PermissionError("Operation not permitted: {}".format(path))

    monkeypatch.setattr(os, "makedirs", _denied_makedirs)

    importlib.import_module("lib.service")  # must not raise

    # And it wasn't a no-op degrade: add_repository_routes() ran to
    # completion against a real Repository built from the bundled
    # repository.json, registering all four HTTP routes (proving the
    # module-level `Repository(...)` construction — including its `.update()`
    # file reads — completed despite ENTRIES_PATH being unwritable).
    from lib.httpserver import HTTPRequestHandler

    assert len(HTTPRequestHandler.get_routes) == 4


# =========================================================================== #
# lib/platform/core.py — the last unguarded module-level re-raise in the
# import chain. kodi_platform.get_platform() failing is expected and caught
# (falls back to os_platform); but if THAT also raises (an environment
# neither path has ever been exercised on), core.py used to log fatally and
# re-raise anyway, crashing the whole service import.
# =========================================================================== #
def test_platform_core_falls_back_to_unknown_when_both_paths_fail(
    proxy, monkeypatch, tmp_path
):
    fake_xbmc = types.SimpleNamespace(
        executeJSONRPC=lambda cmd: json.dumps({"result": {"name": "Kodi"}}),
        translatePath=lambda p: str(tmp_path) + os.sep,
    )
    monkeypatch.setitem(sys.modules, "xbmc", fake_xbmc)
    monkeypatch.delitem(sys.modules, "xbmcvfs", raising=False)
    for mod in ("lib.platform.core", "lib.platform.kodi_platform"):
        monkeypatch.delitem(sys.modules, mod, raising=False)

    # No kodi.log at tmp_path -> kodi_platform's log read raises ->
    # dump_platform() swallows it, returns "unknown" -> regex fails to match
    # -> PlatformError, caught by core.get_platform(), falls to os_platform.
    def _broken_uname():
        raise RuntimeError("sandbox denied uname()")

    monkeypatch.setattr(proxy.os_platform.platform, "system", _broken_uname)

    core = importlib.import_module("lib.platform.core")  # must not raise
    assert core.PLATFORM == core.UNKNOWN_PLATFORM
    assert core.SHARED_LIB_EXTENSION == ""
    assert core.EXECUTABLE_EXTENSION == ""
