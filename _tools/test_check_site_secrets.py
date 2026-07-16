"""Tests for check_site_secrets.py - the built-artifact secret gate."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import check_site_secrets as css


def _site(tmp_path, files: dict[str, str | bytes]) -> Path:
    site = tmp_path / "_site"
    for rel, content in files.items():
        p = site / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            p.write_bytes(content)
        else:
            p.write_text(content)
    return site


def _findings(tmp_path, files):
    return css.scan_site(str(_site(tmp_path, files)))


def test_clean_site_passes(tmp_path):
    assert (
        _findings(
            tmp_path,
            {
                "index.html": "<a href='repositories/'>r</a>",
                "static/addons.xml": "<addons/>",
                "media/logo.png": b"\x89PNG",
            },
        )
        == []
    )


def test_env_file_is_structural_violation(tmp_path):
    hits = _findings(tmp_path, {"iptv/tony7bones.env": "DEVICE_IP=1.2.3.4"})
    assert hits and hits[0][1] == "env file"


def test_m3u_playlist_is_structural_violation(tmp_path):
    hits = _findings(tmp_path, {"iptv/Provider.m3u": "#EXTM3U"})
    assert hits and hits[0][1] == "m3u playlist"


def test_pvr_instance_settings_is_structural_violation(tmp_path):
    hits = _findings(tmp_path, {"iptv/instance-settings-1.xml": "<settings/>"})
    assert hits and hits[0][1] == "pvr instance settings"


def test_iptv_build_dir_is_structural_violation(tmp_path):
    hits = _findings(tmp_path, {"iptv-build/office/x.txt": "hello"})
    assert hits and hits[0][1] == "iptv-build artifact"


def test_credential_content_in_served_xml_is_flagged(tmp_path):
    hits = _findings(
        tmp_path,
        {"rss/feeds.xml": "<url>http://h/get.php?username=bob&password=hunter2</url>"},
    )
    assert hits and "credential-like content" in hits[0][1]


def test_source_dirs_are_exempt_from_content_scan(tmp_path):
    # the pattern definitions themselves live in _tools/ - must not self-flag
    assert (
        _findings(tmp_path, {"_tools/x.yml": "password=not-a-real-served-secret"}) == []
    )


def test_placeholder_env_examples_are_allowed(tmp_path):
    assert (
        _findings(tmp_path, {".env.device.example": "IPTV_1_USERNAME=changeme"}) == []
    )


def test_structural_rules_apply_even_inside_source_dirs(tmp_path):
    hits = _findings(tmp_path, {"_tools/leftover.env": "SECRET=x"})
    assert hits and hits[0][1] == "env file"
