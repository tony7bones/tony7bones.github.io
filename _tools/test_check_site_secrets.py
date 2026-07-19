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


def test_tooling_is_refused_by_the_publish_allowlist(tmp_path):
    # _tools/ used to be content-scan-exempt so the pattern definitions living
    # there could not self-flag. Since the 2026-07-18 allowlist inversion it is
    # not published at all, which is a stronger guarantee: it can neither leak
    # nor self-flag. The content-scan exemption (_SOURCE_DIRS) was then deleted
    # as fail-open, so anything that DOES reach the artifact is scanned - hence
    # the second assertion now expects a finding, not silence.
    import check_site_secrets as c

    assert c.publish_refusal("_tools/x.yml") == "not on the publish allowlist"
    hits = _findings(tmp_path, {"_tools/x.yml": "password=not-a-real-served-secret"})
    assert hits and "credential-like content" in hits[0][1]


def test_placeholder_env_examples_are_allowed(tmp_path):
    assert (
        _findings(tmp_path, {".env.device.example": "IPTV_1_USERNAME=changeme"}) == []
    )


def test_structural_rules_apply_even_inside_source_dirs(tmp_path):
    # An env file inside the PUBLISHED set must still be caught by the specific
    # rule, not merely by the allowlist. addons/ is published, so it is the
    # right place to assert this now that _tools/ is refused outright.
    hits = _findings(tmp_path, {"addons/leftover.env": "SECRET=x"})
    assert hits and hits[0][1] == "env file"
    # and the same rule fires at copy time, inside the allowed set
    import check_site_secrets as c

    assert c.publish_refusal("addons/leftover.env") == "env file"


def test_publish_allowlist_refuses_internal_material(tmp_path):
    """The inversion's whole point: unlisted paths are refused whatever they are
    called, in any case, at any depth. Each of these bypassed the denylist that
    preceded it."""
    import check_site_secrets as c

    for rel in (
        "docs/playbooks/firetv-adb-dev.md",
        "docs/Playbooks/firetv-adb-dev.md",
        ".claude/skills/x/SKILL.md",
        ".CLAUDE/skills/x/SKILL.md",
        "vendor/_tools/leak.md",
        "TASKS.md",
        "CLAUDE.md",
        "subdir/TASKS.md",
        "./docs/playbooks/leak.md",
    ):
        assert c.publish_refusal(rel) == "not on the publish allowlist", rel


def test_publish_allowlist_still_serves_the_site(tmp_path):
    """The failure mode of an allowlist is a missing public file, so assert the
    things visitors actually need are still allowed."""
    import check_site_secrets as c

    for rel in (
        "addons/repository.tony7bones/addon.xml",
        "images/logo.png",
        "dropbox/rss/feed.xml",
        "README.md",
        "style.css",
        ".nojekyll",
    ):
        assert c.publish_refusal(rel) is None, rel
