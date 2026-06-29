"""Tests for publish_canvas.py — the canvas-only publish path.

Covers the secret guard (the safety-critical part) and the staged-diff parser
by monkeypatching the `git` helper, so no real repo or network is touched.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import publish_canvas as pc  # noqa: E402

# A staged diff carrying a real-shaped Xtream credential plus innocuous lines.
_DIFF_WITH_SECRET = """\
diff --git a/iptv/configs/instance-settings-1.xml b/iptv/configs/instance-settings-1.xml
+++ b/iptv/configs/instance-settings-1.xml
+<setting id="m3uUrl">http://op.web24.live:8080/get.php?username=tonybones&password=tonybones123</setting>
+<setting id="m3uCache">true</setting>
diff --git a/rss/RssFeeds.xml b/rss/RssFeeds.xml
+++ b/rss/RssFeeds.xml
+<feed>http://example.com/news.rss</feed>
"""

_DIFF_CLEAN = """\
diff --git a/media/index.html b/media/index.html
+++ b/media/index.html
+<a href="splash.jpg">splash.jpg</a>
"""

_DIFF_TEMPLATE_ONLY = """\
diff --git a/.env.device.example b/.env.device.example
+++ b/.env.device.example
+WEATHERBIT_API_KEY=your_key_here
+password=PLACEHOLDER
"""


def _patch_git(monkeypatch, diff_text):
    monkeypatch.setattr(pc, "git", lambda *a, **k: diff_text)


def test_staged_additions_parses_added_lines_with_paths(monkeypatch):
    _patch_git(monkeypatch, _DIFF_WITH_SECRET)
    adds = pc.staged_additions()
    # `+++ b/...` header lines are NOT additions; real `+` lines are.
    paths = {p for p, _ in adds}
    assert paths == {"iptv/configs/instance-settings-1.xml", "rss/RssFeeds.xml"}
    assert all(not line.startswith("+") for _, line in adds)


def test_scan_flags_embedded_credentials(monkeypatch):
    _patch_git(monkeypatch, _DIFF_WITH_SECRET)
    hits = pc.scan_for_secrets()
    files = {p for p, _ in hits}
    assert "iptv/configs/instance-settings-1.xml" in files
    assert "rss/RssFeeds.xml" not in files  # a plain feed URL is not a secret
    assert any("username=tonybones" in snippet for _, snippet in hits)


def test_scan_passes_clean_canvas_changes(monkeypatch):
    _patch_git(monkeypatch, _DIFF_CLEAN)
    assert pc.scan_for_secrets() == []


def test_scan_allows_placeholder_templates(monkeypatch):
    _patch_git(monkeypatch, _DIFF_TEMPLATE_ONLY)
    # .env.device.example is allowlisted — its placeholder assignments are fine.
    assert pc.scan_for_secrets() == []


@pytest.mark.parametrize(
    "line",
    [
        "url?username=bob&password=hunter2",
        "API_KEY=sk-abcdef123456",
        "token: ghp_realtokenvalue",
    ],
)
def test_secret_patterns_match_known_shapes(line):
    assert any(p.search(line) for p in pc._SECRET_PATTERNS)
