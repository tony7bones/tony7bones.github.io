"""Shared credential-shape patterns for the publish/build secret gates.

Single source of truth for what "looks like a secret" across the two gates
that guard the PUBLIC site: publish_canvas.py (scans staged additions before a
canvas push) and check_site_secrets.py (scans the CI-built _site/ artifact
before deploy). Mirrors the spirit of test_secret_leak.py: Xtream provider
user/pass embedded in m3u/EPG URLs and bare api-key/secret/token assignments.
"""

import re

SECRET_PATTERNS = [
    re.compile(r"username=[^&\s\"'<]+", re.IGNORECASE),
    re.compile(r"password=[^&\s\"'<]+", re.IGNORECASE),
    re.compile(r"\bapi[_-]?key\b\s*[=:]\s*\S+", re.IGNORECASE),
    re.compile(r"\b(secret|token)\b\s*[=:]\s*\S+", re.IGNORECASE),
]

# Placeholder-bearing templates are allowed to carry example assignments.
ALLOW_FILES = {".env.example", ".env.device.example"}
