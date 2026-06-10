"""Per-device config (tony7bones.env) parsing — pure Python, no Kodi deps.

The provisioner derives a per-device ``tony7bones.env`` (KEY=value, shell-style)
from the owner's master ``.env`` and pushes it to the box; this reads it and feeds
the values into the existing idempotent settings writers. Pure-Python + no Kodi
deps so it is unit-testable in isolation and importable outside Kodi. NEVER log a
parsed value (secrets).

These three functions (``parse_env``, ``split_list``, ``read_box_env``) were moved
VERBATIM out of ``script.tony7bones.bootstrap/default.py`` into this shared
sublibrary so the new ``setup/`` orchestrator + layer modules and the existing
bootstrap re-export the same single implementation. No logic change.
(``env_has_iptv`` followed in Phase 6 — same move, same reason: the probes
module needs it for ``assert_box_complete`` and must not import the bootstrap.)

Phase N1 (the no-computer track) generalized the env SOURCE from the single
Android constant to an ORDERED path list: the provisioner's pushed file
(``BOX_ENV_PATH`` — wins when present) first, then the PROFILE-LOCAL persisted
env (``PROFILE_ENV_SPECIAL`` — what the on-box config collector writes; lives
inside Kodi's own writable profile, so it works on every platform with no adb /
scoped-storage dependency). ``box_env_paths`` / ``read_first_env`` /
``delete_box_envs`` are the three helpers; the module stays import-clean
without Kodi (``xbmcvfs`` is imported LAZILY, only to translate the
``special://`` profile path, and its absence simply omits that candidate).
"""

import os as _os
import re as _re

# The per-device config the provisioner derives from the owner's master .env and
# pushes to the box (the COMPUTER-path producer). Moved here from the bootstrap
# in Phase N1 so the path list has one home; the bootstrap re-exports it.
BOX_ENV_PATH = "/storage/emulated/0/kodi/tony.7.bones/tony7bones.env"

# The PROFILE-LOCAL env (the NO-COMPUTER-path producer — the on-box collector
# persists here from Phase N2 on). Inside Kodi's own profile: writable
# everywhere Kodi runs, no adb, no scoped-storage exposure.
PROFILE_ENV_SPECIAL = (
    "special://profile/addon_data/script.tony7bones.bootstrap/tony7bones.env"
)


def profile_env_path():
    """The translated real path of the profile-local env, or ``None`` when not
    running under Kodi (``xbmcvfs`` unavailable — pure-Python callers)."""
    try:
        import xbmcvfs

        return xbmcvfs.translatePath(PROFILE_ENV_SPECIAL)
    except Exception:  # noqa: BLE001 - off-Kodi: no profile path to offer
        return None


def box_env_paths(primary=None):
    """The ORDERED env-source candidates: the pushed ``BOX_ENV_PATH`` (or the
    caller's ``primary`` override) FIRST — the provisioned path is byte-compatible
    because its file always wins — then the profile-local persisted env (omitted
    off-Kodi)."""
    paths = [primary or BOX_ENV_PATH]
    profile = profile_env_path()
    if profile:
        paths.append(profile)
    return paths


def read_first_env(paths, reader=None):
    """Read the FIRST candidate path that parses to a NON-EMPTY env dict.

    An absent, unreadable, empty, or comment-only file is skipped (it carries
    no configuration — same class as absent, so a degenerate push can never
    shadow a real profile-local env). Returns ``{}`` when no candidate yields
    config — the bootstrap's no-env signal (→ the Guided wizard). ``reader``
    defaults to :func:`read_box_env`; injectable so the bootstrap's re-exported
    (monkeypatchable) name keeps working."""
    reader = reader or read_box_env
    for path in paths:
        env = reader(path)
        if env:
            return env
    return {}


def delete_box_envs(paths):
    """Remove EVERY env candidate (guarded; a missing file is a no-op). The
    terminal ops (Express completion, Guided Finish / Remove Setup) call this so
    no secret-bearing env lingers in EITHER location (Model A semantics)."""
    for path in paths:
        try:
            _os.remove(path)
        except OSError:
            pass


# IPTV env detection: an IPTV provider is configured when the per-device env
# carries a PLAYLIST SOURCE — a multi-provider ``IPTV_<N>_M3U`` /
# ``IPTV_<N>_PORTAL`` key (N a 1-based provider index) OR the single-instance
# ``IPTV_M3U`` / ``IPTV_PORTAL``. NOTE: ``IPTV_EPG`` alone does NOT trip the
# gate — an EPG with no playlist is a channel-less PVR (guide metadata, zero
# channels), not a usable source; ``apply_iptv`` still consumes ``IPTV_EPG``
# when a real playlist provider IS present. ``IPTV_GROUPS`` alone (group names,
# useless without a playlist) likewise does not count.
_IPTV_PROVIDER_KEY = _re.compile(r"^IPTV_(?:\d+_)?(?:M3U|PORTAL)$")


def env_has_iptv(box_env):
    """True when the per-device env carries an IPTV provider PLAYLIST source.

    Scans the env keys for any ``IPTV_<N>_M3U`` / ``IPTV_<N>_PORTAL``
    (multi-provider) or the single-instance ``IPTV_M3U`` / ``IPTV_PORTAL`` —
    and only counts a key whose VALUE is non-empty (an empty ``IPTV_M3U=`` is
    not a provider). This is the gate the orchestrators use to decide whether
    the IPTV layer applies to this box; the probes use it the same way for
    ``assert_box_complete``. Pure-Python; never raises.
    """
    box_env = box_env or {}
    for key, val in box_env.items():
        if _IPTV_PROVIDER_KEY.match(key) and (val or "").strip():
            return True
    return False


def parse_env(text):
    """Parse KEY=value config text into a dict. Tolerant of the real .env shape:
    blank lines and full-line `#` comments are ignored; a value may be single- or
    double-quoted (quotes stripped, inline `#` kept if inside quotes); an UNquoted
    value drops an inline `# comment`; CRLF is handled; a line without `=` is
    skipped. Values stay raw strings — callers split `;`-lists via split_list()."""
    env = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        val = val.strip()
        if val[:1] in ("'", '"'):
            val = val[1:].split(val[0], 1)[0]  # quoted body up to the closing quote
        else:
            val = val.split("#", 1)[0].strip()  # drop inline comment when unquoted
        if key:
            env[key] = val
    return env


def split_list(value, sep=";"):
    """Split a `sep`-delimited multi-value field; trim each item, drop empties."""
    return [item.strip() for item in (value or "").split(sep) if item.strip()]


def read_box_env(path):
    """Read + parse the per-device tony7bones.env at `path`. Returns {} when the
    file is absent or unreadable (the no-env fallback — never raises)."""
    try:
        with open(path, encoding="utf-8") as fh:
            return parse_env(fh.read())
    except OSError:
        return {}
