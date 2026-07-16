"""Negative tests: no secret artifact or value ever reaches the committed
(git-tracked) tree.

The forbidden secret VALUES are sourced at runtime from the gitignored local
`.env` — never hardcoded here. Where no local `.env` exists (CI), the value-scan
is skipped and only the structural artifact check runs. All scans look at
git-tracked files ONLY (a developer's own gitignored `.env` is never flagged).

Per the env-config-consolidation plan (Phase 0, QA criterion C).
"""

import os
import re
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

# Committed config TEMPLATES — placeholder values only, never real secrets.
_EXAMPLE_ENVS = {".env.example", ".env.device.example"}


def _git(*args):
    return subprocess.run(["git", *args], cwd=REPO, capture_output=True, text=True)


def _tracked():
    return _git("ls-files").stdout.splitlines()


def test_secret_artifacts_not_tracked():
    """The gitignored config artifacts must never be tracked: any *.env (incl.
    the per-device tony7bones.env), the iptv-build/ staging dir, and ANY *.m3u
    playlist (host-built curated playlists carry provider creds in every
    channel URL — they live only in gitignored staging / the box profile).
    (.env.example is allowed — it does not end in `.env`.)"""
    offenders = [
        f
        for f in _tracked()
        if (
            os.path.basename(f).startswith(".env")
            and os.path.basename(f) not in _EXAMPLE_ENVS
        )
        or os.path.basename(f).endswith(".env")
        or f.startswith("iptv-build/")
        or os.path.basename(f).endswith(".m3u")
        or (
            os.path.basename(f).startswith("instance-settings")
            and os.path.basename(f).endswith(".xml")
        )
    ]
    assert not offenders, f"secret-bearing artifacts are TRACKED: {offenders}"


def _read_env(path):
    env = {}
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        val = val.strip()
        if val[:1] in ("'", '"'):
            val = val[1:].split(val[0], 1)[0]  # take quoted body
        else:
            val = val.split("#", 1)[0].strip()  # drop inline comment when unquoted
        env[key.strip()] = val
    return env


def _secret_tokens(env):
    """High-signal secret substrings to forbid in tracked files: the two weather
    API keys, the IPTV provider host / username / password from every m3u/epg/
    portal URL (legacy AND numbered ``IPTV_<N>_*`` shapes), and the raw
    ``IPTV_<N>_USER`` / ``IPTV_<N>_PASS`` xtream credentials."""
    tokens = set()
    for k in ("WEATHERBIT_API_KEY", "OWM_API_KEY"):
        if env.get(k):
            tokens.add(env[k])
    url_key = re.compile(r"^IPTV(?:_\d+)?_(?:M3U|EPG|PORTAL)$")
    cred_key = re.compile(r"^IPTV(?:_\d+)?_(?:USER|PASS)$")
    for k, val in env.items():
        if url_key.match(k):
            for pat in (
                r"https?://([^/:]+)",
                r"username=([^&]+)",
                r"password=([^&]+)",
            ):
                m = re.search(pat, val)
                if m:
                    tokens.add(m.group(1))
        elif cred_key.match(k) and val:
            tokens.add(val)
    return {t for t in tokens if len(t) >= 6}


def test_no_env_secret_value_in_tracked_files():
    """No secret VALUE from any local .env* (the per-device .env.<device> files)
    appears in any git-tracked file."""
    env_files = [p for p in REPO.glob(".env*") if p.name not in _EXAMPLE_ENVS]
    if not env_files:
        return  # CI / no local env — value-scan not applicable
    tokens = set()
    for ef in env_files:
        tokens |= _secret_tokens(_read_env(ef))
    if not tokens:
        return
    leaks = []
    for tok in tokens:
        res = _git("grep", "-F", "-l", tok)  # tracked files only; rc 0 = found
        if res.returncode == 0:
            leaks.append((tok[:6] + "…", res.stdout.split()))
    assert not leaks, f"secret value leaked into tracked files: {leaks}"
