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
"""

import re as _re

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
