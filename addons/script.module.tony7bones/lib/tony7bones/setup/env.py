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
"""


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
