"""Tests for build_iptv.py — the HOST half of the IPTV layer (Phase 5b·2).

Adapted from the `iptv` branch POC suite for the integrated builder: token
naming (matches the in-Kodi ``_groups_file_special`` derivation), the staged
``instance-settings-<N>.xml`` with the portable special:// m3uPath, custom
group mode GATED on a non-empty curated group list, env-driven
``GROUPS_ONLY``, m3u-mode favorites, and the build()/main() per-provider
failure + exit-code contract. The POC's direct-to-Kodi ``provision`` mode is
GONE — applying staged artifacts is the in-Kodi half's job
(``tony7bones.setup.iptv._apply_staged_provider``, tested in
test_setup_iptv.py).

HARD rules baked into every test here:

* NO real network I/O. ``build_iptv.http_get`` / ``build_iptv.xtream_api`` are
  monkeypatched to fixtures; no test makes an HTTP request.
* NO real credentials or real provider hosts — every host/user/pass/stream is
  fabricated (``http://prov.example``, ``user1``, ``pw1``, fake stream ids).
  This is a PUBLIC repo guarded by test_secret_leak.py.
* Everything written lands under a pytest tmp_path.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
import build_iptv as bi  # noqa: E402

# ---------------------------------------------------------------------------
# fixtures / helpers — fabricated provider data (no real hosts/creds)
# ---------------------------------------------------------------------------
PORTAL = "http://prov.example:8080"
USER = "user1"
PW = "pw1"


def _xtream_streams():
    """Fabricated get_live_streams payload spanning several categories."""
    return [
        {
            "stream_id": 1,
            "name": "ESPN HD",
            "category_id": "10",
            "epg_channel_id": "espn.us",
            "stream_icon": "http://prov.example/espn.png",
        },
        {
            "stream_id": 2,
            "name": "Fox Sports",
            "category_id": "10",
            "epg_channel_id": "fox.us",
            "stream_icon": "",
        },
        {
            "stream_id": 3,
            "name": "CNN",
            "category_id": "20",
            "epg_channel_id": "cnn.us",
            "stream_icon": "",
        },
        {
            "stream_id": 4,
            "name": "PPV Boxing Event",
            "category_id": "30",
            "epg_channel_id": "",
            "stream_icon": "",
        },
        {
            "stream_id": 5,
            "name": "Boxing Classics",
            "category_id": "20",
            "epg_channel_id": "",
            "stream_icon": "",
        },
        {
            "stream_id": 6,
            "name": "HBO",
            "category_id": "40",
            "epg_channel_id": "hbo.us",
            "stream_icon": "",
        },
    ]


def _xtream_cats():
    return [
        {"category_id": "10", "category_name": "Sports"},
        {"category_id": "20", "category_name": "News"},
        {"category_id": "30", "category_name": "PPV Events"},
        {"category_id": "40", "category_name": "Movies"},
    ]


def _patch_xtream(monkeypatch, streams=None, cats=None):
    """Replace build_iptv.xtream_api with a fixture dispatcher (no network)."""
    streams = streams if streams is not None else _xtream_streams()
    cats = cats if cats is not None else _xtream_cats()

    def fake(portal, user, pw, action, **params):
        assert "player_api" not in portal  # we get the raw portal here
        if action == "get_live_categories":
            return cats
        if action == "get_live_streams":
            return streams
        raise AssertionError(f"unexpected action {action}")

    monkeypatch.setattr(bi, "xtream_api", fake)


_M3U_BODY = (
    "#EXTM3U\n"
    '#EXTINF:-1 tvg-name="Zeta" group-title="Sports",Zeta\n'
    "http://prov.example/z\n"
    '#EXTINF:-1 tvg-name="Alpha" group-title="Sports",Alpha\n'
    "http://prov.example/a\n"
    '#EXTINF:-1 tvg-name="News1" group-title="News",News1\n'
    "http://prov.example/n\n"
    '#EXTINF:-1 tvg-name="Junk" group-title="Other",Junk\n'
    "http://prov.example/j\n"
)


def _patch_http(monkeypatch, status=200, body=None):
    body = _M3U_BODY.encode() if body is None else body
    monkeypatch.setattr(bi, "http_get", lambda url: (status, body))


# ===========================================================================
# load_env
# ===========================================================================
def test_load_env_quotes_comments_and_blanks(tmp_path):
    env_file = tmp_path / ".env.local"
    env_file.write_text(
        "\n".join(
            [
                "# a comment line",
                "",
                'DOUBLE="hello world"',
                "SINGLE='single quoted'",
                "UNQUOTED=plainvalue",
                "INLINE=value # trailing comment",
                "   # indented comment",
                "EMPTY=",
                "NOT A KEY LINE",
            ]
        ),
        encoding="utf-8",
    )
    env = bi.load_env(env_file)
    assert env["DOUBLE"] == "hello world"
    assert env["SINGLE"] == "single quoted"
    assert env["UNQUOTED"] == "plainvalue"
    assert env["INLINE"] == "value"  # inline comment stripped on unquoted
    assert env["EMPTY"] == ""
    assert "NOT A KEY LINE".split()[0] not in env  # malformed line skipped


def test_load_env_hash_inside_quotes_preserved(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text('PASS="a#b#c"\n', encoding="utf-8")
    assert bi.load_env(env_file)["PASS"] == "a#b#c"


# ===========================================================================
# providers — numbered blocks + mode inference (mirrors the in-Kodi parser)
# ===========================================================================
def test_providers_groups_numbered_keys_ordered():
    env = {
        "IPTV_2_NAME": "Second",
        "IPTV_1_NAME": "First",
        "IPTV_1_MODE": "m3u",
        "IPTV_10_NAME": "Tenth",
        "UNRELATED": "x",
    }
    out = bi.providers(env)
    assert [p["_n"] for p in out] == [1, 2, 10]  # numeric, not lexical, order
    assert out[0]["name"] == "First"
    assert out[0]["mode"] == "m3u"
    assert out[1]["name"] == "Second"
    assert "unrelated" not in out[0]  # non IPTV_ keys excluded


def test_providers_mode_inference_matches_in_kodi_parser():
    """No MODE: xtream iff PORTAL with no M3U, else m3u — the same default the
    in-Kodi _iptv_providers applies (the two halves must agree on a provider's
    mode or the fallback path would mis-handle it)."""
    out = bi.providers(
        {
            "IPTV_1_M3U": "http://prov.example/list.m3u",
            "IPTV_2_PORTAL": PORTAL,
            "IPTV_3_PORTAL": PORTAL,
            "IPTV_3_M3U": "http://prov.example/3.m3u",
        }
    )
    assert [p["mode"] for p in out] == ["m3u", "xtream", "m3u"]


def test_providers_empty():
    assert bi.providers({"FOO": "bar"}) == []


# ===========================================================================
# parse_groups
# ===========================================================================
def test_parse_groups_full_grammar():
    specs = bi.parse_groups("Sports > Live Sports | sort; News; 30 > PPV")
    assert specs == [
        {"src": "Sports", "label": "Live Sports", "sort": True},
        {"src": "News", "label": "News", "sort": False},
        {"src": "30", "label": "PPV", "sort": False},
    ]


def test_parse_groups_omitted_label_uses_src():
    assert bi.parse_groups("Sports") == [
        {"src": "Sports", "label": "Sports", "sort": False}
    ]


def test_parse_groups_sort_without_label():
    assert bi.parse_groups("Sports | sort") == [
        {"src": "Sports", "label": "Sports", "sort": True}
    ]


def test_parse_groups_blank_and_empty_entries():
    assert bi.parse_groups("") == []
    assert bi.parse_groups(None) == []
    # leading/trailing/empty ';' entries are dropped, order preserved
    assert bi.parse_groups("; A ; ; B ;") == [
        {"src": "A", "label": "A", "sort": False},
        {"src": "B", "label": "B", "sort": False},
    ]


# ===========================================================================
# token — MUST match the in-Kodi _groups_file_special derivation
# ===========================================================================
@pytest.mark.parametrize(
    "raw, n, expected",
    [
        ("Network 24", 1, "Network24"),  # the historical legacy filename
        ("My-Provider!", 2, "MyProvider"),
        ("UPPER", 1, "UPPER"),
        ("", 3, "Provider3"),
        (None, 7, "Provider7"),
        ("!!!", 2, "Provider2"),
    ],
)
def test_token(raw, n, expected):
    assert bi.token(raw, n) == expected


def test_token_matches_in_kodi_groups_file_derivation():
    """The two halves derive the SAME artifact token from a provider name —
    drift here would scatter device dirs with mismatched filenames."""
    import re as _re

    name = "Network 24"
    in_kodi = _re.sub(r"[^A-Za-z0-9]+", "", name)  # _groups_file_special's rule
    assert bi.token(name, 1) == in_kodi == "Network24"


# ===========================================================================
# parse_m3u_text / _chan_name / _chan_group / _set_group_title
# ===========================================================================
def test_parse_m3u_text_header_skip_and_pairing():
    text = (
        "#EXTM3U\n"
        '#EXTINF:-1 group-title="A",Chan 1\n'
        "http://prov.example/1\n"
        '#EXTINF:-1 group-title="B",Chan 2\n'
        "http://prov.example/2\n"
    )
    chans = bi.parse_m3u_text(text)
    assert len(chans) == 2
    assert chans[0][1] == "http://prov.example/1"
    assert 'group-title="B"' in chans[1][0]


def test_parse_m3u_text_no_header_and_dangling_extinf():
    text = '#EXTINF:-1 group-title="A",Solo'  # no URL line after it
    chans = bi.parse_m3u_text(text)
    assert chans == [('#EXTINF:-1 group-title="A",Solo', "")]


def test_parse_m3u_text_skips_stray_lines():
    text = (
        "#EXTM3U\n"
        "# a comment in the body\n"
        '#EXTINF:-1 group-title="A",Chan 1\n'
        "http://prov.example/1\n"
    )
    assert bi.parse_m3u_text(text) == [
        ('#EXTINF:-1 group-title="A",Chan 1', "http://prov.example/1")
    ]


def test_chan_name_prefers_tvg_name_falls_back_to_display():
    assert bi._chan_name('#EXTINF:-1 tvg-name="TVG",Display') == "TVG"
    assert bi._chan_name("#EXTINF:-1,Display Name") == "Display Name"
    assert bi._chan_name("#EXTINF:-1") == ""


def test_chan_group_extracts_or_empty():
    assert bi._chan_group('#EXTINF:-1 group-title="G",X') == "G"
    assert bi._chan_group("#EXTINF:-1,X") == ""


def test_set_group_title_replaces_or_injects():
    assert (
        bi._set_group_title('#EXTINF:-1 group-title="Old",X', "New")
        == '#EXTINF:-1 group-title="New",X'
    )
    out = bi._set_group_title("#EXTINF:-1,X", "New")
    assert out.startswith('#EXTINF:-1 group-title="New"') and out.endswith(",X")


# ===========================================================================
# build_m3u_mode — curation (select / relabel / sort) + favorites
# ===========================================================================
def test_build_m3u_mode_filters_relabels_and_sorts(monkeypatch):
    _patch_http(monkeypatch)
    p = {
        "m3u": "http://prov.example/list.m3u",
        "groups": "Sports > Live Sports | sort; News",
    }
    text, counts, labels = bi.build_m3u_mode(p)

    assert labels == ["Live Sports", "News"]
    assert counts == {"Live Sports": 2, "News": 1}
    # relabelled to the display label, "Other" filtered out
    assert 'group-title="Live Sports"' in text
    assert 'group-title="Sports"' not in text
    assert "Junk" not in text
    # alpha-sorted by tvg-name: Alpha before Zeta
    assert text.index("Alpha") < text.index("Zeta")


def test_build_m3u_mode_no_groups_passthrough(monkeypatch):
    _patch_http(monkeypatch)
    text, counts, labels = bi.build_m3u_mode({"m3u": "http://prov.example/x"})
    # every channel kept, grouped by source group-title
    assert counts == {"Sports": 2, "News": 1, "Other": 1}
    assert labels == ["Sports", "News", "Other"]
    assert text.count("#EXTINF") == 4


def test_build_m3u_mode_passthrough_counts_missing_group(monkeypatch):
    body = ("#EXTM3U\n#EXTINF:-1,Nogroup\nhttp://prov.example/1\n").encode()
    _patch_http(monkeypatch, body=body)
    _, counts, labels = bi.build_m3u_mode({"m3u": "http://prov.example/x"})
    assert counts == {"(none)": 1}
    assert labels == []  # a group-less channel never lands in the groups file


def test_build_m3u_mode_favorites_multigroup_and_first_label(monkeypatch):
    _patch_http(monkeypatch)
    p = {
        "m3u": "http://prov.example/x",
        "groups": "Sports > Live Sports",
        "favorites": "Alpha",
    }
    text, counts, labels = bi.build_m3u_mode(p)
    assert labels[0] == "24/7 Favorites"
    assert counts["24/7 Favorites"] == 1
    # a favorite inside a selected group gets a multi-group title
    assert 'group-title="Live Sports;24/7 Favorites"' in text


def test_build_m3u_mode_favorite_outside_selection_emitted_favorites_only(
    monkeypatch,
):
    _patch_http(monkeypatch)
    p = {
        "m3u": "http://prov.example/x",
        "groups": "News",
        "favorites": "Zeta",  # lives in trimmed-away "Sports"
        "favorites_name": "Best Of",
    }
    text, counts, labels = bi.build_m3u_mode(p)
    assert labels == ["Best Of", "News"]
    assert 'group-title="Best Of"' in text
    assert text.count("http://prov.example/z") == 1  # emitted exactly once


def test_build_m3u_mode_favorites_xtream_forms_ignored(monkeypatch, capsys):
    """id:/bare-category favorites are xtream concepts — in m3u mode they are
    ignored with a printed note, never crash, never match."""
    _patch_http(monkeypatch)
    p = {
        "m3u": "http://prov.example/x",
        "groups": "Sports",
        "favorites": "id:123; 58; Alpha",
    }
    _, counts, labels = bi.build_m3u_mode(p)
    assert counts["24/7 Favorites"] == 1  # only Alpha resolved
    out = capsys.readouterr().out
    assert "xtream-only" in out


def test_build_m3u_mode_favorites_prefer_non_ppv(monkeypatch):
    body = (
        "#EXTM3U\n"
        '#EXTINF:-1 group-title="PPV EVENTS",Boxing Special\n'
        "http://prov.example/ppv\n"
        '#EXTINF:-1 group-title="Sports",Boxing Special\n'
        "http://prov.example/real\n"
    ).encode()
    _patch_http(monkeypatch, body=body)
    p = {"m3u": "http://prov.example/x", "favorites": "Boxing"}
    text, _, _ = bi.build_m3u_mode(p)
    # the non-PPV copy is the favorite
    favline = [
        ln for ln in text.splitlines() if "24/7 Favorites" in ln and "Boxing" in ln
    ]
    assert favline and "PPV EVENTS;24/7" not in favline[0]


def test_build_m3u_mode_favorites_no_match_noted(monkeypatch, capsys):
    _patch_http(monkeypatch)
    _, counts, labels = bi.build_m3u_mode(
        {"m3u": "http://prov.example/x", "favorites": "NoSuchChannel"}
    )
    assert "24/7 Favorites" not in labels
    assert "matched no channel" in capsys.readouterr().out


def test_build_m3u_mode_raises_on_non_200(monkeypatch):
    _patch_http(monkeypatch, status=404)
    with pytest.raises(RuntimeError):
        bi.build_m3u_mode({"m3u": "http://prov.example/x"})


def test_build_m3u_mode_raises_when_no_extinf(monkeypatch):
    _patch_http(monkeypatch, status=200, body=b"not a playlist at all")
    with pytest.raises(RuntimeError):
        bi.build_m3u_mode({"m3u": "http://prov.example/x"})


# ===========================================================================
# xtream_api (URL construction; http_get faked)
# ===========================================================================
def test_xtream_api_builds_player_api_url(monkeypatch):
    captured = {}

    def fake_http(url):
        captured["url"] = url
        return 200, b'{"ok": true}'

    monkeypatch.setattr(bi, "http_get", fake_http)
    out = bi.xtream_api(PORTAL + "/", USER, PW, "get_live_streams", foo="bar")
    assert out == {"ok": True}
    url = captured["url"]
    assert url.startswith(PORTAL + "/player_api.php?")
    assert "username=user1" in url
    assert "password=pw1" in url
    assert "action=get_live_streams" in url
    assert "foo=bar" in url


# ===========================================================================
# _resolve_favorites (xtream)
# ===========================================================================
def _fav_indexes():
    streams = _xtream_streams()
    by_cat = {}
    for s in streams:
        by_cat.setdefault(str(s["category_id"]), []).append(s)
    cat_name = {c["category_id"]: c["category_name"] for c in _xtream_cats()}
    return streams, by_cat, cat_name


def test_resolve_favorites_name_prefers_non_ppv():
    streams, by_cat, cat_name = _fav_indexes()
    # "Boxing" matches both PPV Boxing Event (cat 30 PPV) and Boxing Classics
    # (cat 20 News) -> the non-PPV one (id 5) is preferred.
    ids = bi._resolve_favorites("Boxing", streams, by_cat, cat_name)
    assert ids == [5]


def test_resolve_favorites_id_pin_exact():
    streams, by_cat, cat_name = _fav_indexes()
    assert bi._resolve_favorites("id:4", streams, by_cat, cat_name) == [4]


def test_resolve_favorites_numeric_category_all():
    streams, by_cat, cat_name = _fav_indexes()
    # category 10 = Sports -> both stream ids 1 and 2
    assert bi._resolve_favorites("10", streams, by_cat, cat_name) == [1, 2]


def test_resolve_favorites_dedupes_and_orders():
    streams, by_cat, cat_name = _fav_indexes()
    # ESPN (id 1) then category 10 (ids 1,2): id 1 must not repeat.
    assert bi._resolve_favorites("ESPN; 10; id:1", streams, by_cat, cat_name) == [1, 2]


def test_resolve_favorites_blank_and_no_match():
    streams, by_cat, cat_name = _fav_indexes()
    assert bi._resolve_favorites("", streams, by_cat, cat_name) == []
    assert bi._resolve_favorites("NoSuchChannel", streams, by_cat, cat_name) == []
    assert bi._resolve_favorites("id:999", streams, by_cat, cat_name) == []


# ===========================================================================
# build_xtream_mode
# ===========================================================================
def test_build_xtream_mode_selected_categories_and_urls(monkeypatch):
    _patch_xtream(monkeypatch)
    p = {"portal": PORTAL, "user": USER, "pass": PW, "groups": "10 > Sports; 20 > News"}
    text, counts, labels = bi.build_xtream_mode(p)

    assert labels == ["Sports", "News"]
    assert counts == {"Sports": 2, "News": 2}
    # correct stream URL form .../live/user/pass/<id>.ts
    assert f"{PORTAL}/live/{USER}/{PW}/1.ts" in text
    assert f"{PORTAL}/live/{USER}/{PW}/3.ts" in text
    # epg-id / logo carried through
    assert 'tvg-id="espn.us"' in text
    assert 'tvg-logo="http://prov.example/espn.png"' in text


def test_build_xtream_mode_favorites_group_first_and_multigroup(monkeypatch):
    _patch_xtream(monkeypatch)
    p = {
        "portal": PORTAL,
        "user": USER,
        "pass": PW,
        "groups": "10 > Sports",
        "favorites": "ESPN HD",  # id 1, IN the selected Sports group
        "favorites_name": "24/7 Favorites",
    }
    text, counts, labels = bi.build_xtream_mode(p)

    # favorites label is FIRST
    assert labels[0] == "24/7 Favorites"
    assert counts["24/7 Favorites"] == 1
    # a favorite inside a selected group gets multi-group title
    assert 'group-title="Sports;24/7 Favorites"' in text


def test_build_xtream_mode_favorite_outside_selected_emitted_favorites_only(
    monkeypatch,
):
    _patch_xtream(monkeypatch)
    p = {
        "portal": PORTAL,
        "user": USER,
        "pass": PW,
        "groups": "20 > News",
        "favorites": "id:1",  # ESPN, category 10 (NOT in selected News group)
    }
    text, _, labels = bi.build_xtream_mode(p)

    assert labels[0] == "24/7 Favorites"
    # ESPN emitted once, into Favorites only
    assert 'group-title="24/7 Favorites",ESPN HD' in text
    assert text.count(f"{PORTAL}/live/{USER}/{PW}/1.ts") == 1


def test_build_xtream_mode_blank_groups_all_categories(monkeypatch):
    _patch_xtream(monkeypatch)
    p = {"portal": PORTAL, "user": USER, "pass": PW}  # no groups
    _, counts, labels = bi.build_xtream_mode(p)
    assert set(labels) == {"Sports", "News", "PPV Events", "Movies"}
    assert counts["Sports"] == 2
    assert counts["Movies"] == 1


def test_build_xtream_mode_sort_within_category(monkeypatch):
    _patch_xtream(monkeypatch)
    p = {"portal": PORTAL, "user": USER, "pass": PW, "groups": "10 > Sports | sort"}
    text, _, _ = bi.build_xtream_mode(p)
    # ESPN HD vs Fox Sports -> alpha by name, ESPN first
    assert text.index("ESPN HD") < text.index("Fox Sports")


# ===========================================================================
# _custom_groups_xml / _instance_xml
# ===========================================================================
def test_custom_groups_xml_escapes_and_structure():
    xml = bi._custom_groups_xml(["Sports", "News & Talk", "<b>"])
    assert xml.startswith("<customChannelGroups>\n")
    assert xml.rstrip().endswith("</customChannelGroups>")
    assert "<channelGroupName>Sports</channelGroupName>" in xml
    assert "News &amp; Talk" in xml  # & escaped
    assert "&lt;b&gt;" in xml  # < > escaped


def test_instance_xml_contains_required_settings():
    p = {
        "_n": 2,
        "name": "My Provider",
        "epg": "http://prov.example/epg.xml",
        "groups": "10 > Sports; 20 > News",
    }
    xml = bi._instance_xml(p, "MyProvider", ["Sports", "News"])
    assert '<setting id="kodi_addon_instance_name">My Provider</setting>' in xml
    assert '<setting id="kodi_addon_instance_enabled">true</setting>' in xml
    assert '<setting id="m3uPathType">0</setting>' in xml
    # the PORTABLE special:// playlist path — the in-Kodi consumer rewrites it
    assert (
        f'<setting id="m3uPath">{bi.PLAYLISTS_SPECIAL}/MyProvider.m3u</setting>' in xml
    )
    assert '<setting id="epgPathType">1</setting>' in xml
    assert '<setting id="epgUrl">http://prov.example/epg.xml</setting>' in xml
    assert '<setting id="tvGroupMode">2</setting>' in xml
    assert '<setting id="tvChannelGroupsOnly">true</setting>' in xml
    assert (
        '<setting id="customTvGroupsFile">'
        f"{bi.GROUPS_SPECIAL}/customTVGroups-MyProvider.xml</setting>"
    ) in xml


def test_instance_xml_groups_only_env_false():
    p = {"_n": 1, "name": "P", "groups": "A", "groups_only": "false"}
    xml = bi._instance_xml(p, "P", ["A"])
    assert '<setting id="tvChannelGroupsOnly">false</setting>' in xml


def test_instance_xml_no_labels_keeps_all_channels_mode():
    """No curated groups -> NEVER tvGroupMode=2 (an empty custom-groups file
    would load zero channels): all-channels default, groups-only off, no
    customTvGroupsFile reference."""
    p = {"_n": 1, "name": "P"}
    xml = bi._instance_xml(p, "P", [])
    assert '<setting id="tvGroupMode">0</setting>' in xml
    assert '<setting id="tvChannelGroupsOnly">false</setting>' in xml
    assert "customTvGroupsFile" not in xml


def test_instance_xml_favorites_without_groups_never_hides_the_rest():
    """Favorites-only curation (blank GROUPS): custom mode carries the favorites
    group, but groups-only is FORCED false so the uncurated playlist stays
    visible."""
    p = {"_n": 1, "name": "P", "favorites": "Alpha", "groups_only": "true"}
    xml = bi._instance_xml(p, "P", ["24/7 Favorites"])
    assert '<setting id="tvGroupMode">2</setting>' in xml
    assert '<setting id="tvChannelGroupsOnly">false</setting>' in xml


# ===========================================================================
# build_provider — the three artifacts per provider
# ===========================================================================
def test_build_provider_m3u_writes_three_artifacts(tmp_path, monkeypatch):
    _patch_http(monkeypatch)
    p = {
        "_n": 1,
        "name": "My Prov",
        "mode": "m3u",
        "m3u": "http://prov.example/x",
        "groups": "Sports > S",
        "epg": "http://prov.example/epg.xml",
    }
    name, mode, counts, labels = bi.build_provider(p, tmp_path)
    assert (name, mode) == ("My Prov", "m3u")
    assert counts == {"S": 2}
    playlist = tmp_path / "MyProv.m3u"
    groups = tmp_path / "customTVGroups-MyProv.xml"
    inst = tmp_path / "instance-settings-1.xml"
    assert playlist.read_text().startswith("#EXTM3U")
    assert "<channelGroupName>S</channelGroupName>" in groups.read_text()
    ibody = inst.read_text()
    assert f"{bi.PLAYLISTS_SPECIAL}/MyProv.m3u" in ibody
    assert "customTVGroups-MyProv.xml" in ibody
    assert "http://prov.example/epg.xml" in ibody


def test_build_provider_xtream_default_name_token(tmp_path, monkeypatch):
    _patch_xtream(monkeypatch)
    p = {
        "_n": 3,
        "mode": "xtream",
        "portal": PORTAL,
        "user": USER,
        "pass": PW,
        "groups": "10 > Sports",
    }
    name, mode, counts, labels = bi.build_provider(p, tmp_path)
    assert name == "Provider3"  # falls back to Provider<N>
    assert (tmp_path / "Provider3.m3u").exists()
    assert (tmp_path / "customTVGroups-Provider3.xml").exists()
    assert (tmp_path / "instance-settings-3.xml").exists()


def test_build_provider_no_labels_emits_no_groups_file(tmp_path, monkeypatch):
    body = ("#EXTM3U\n#EXTINF:-1,Nogroup\nhttp://prov.example/1\n").encode()
    _patch_http(monkeypatch, body=body)
    p = {"_n": 1, "name": "Bare", "mode": "m3u", "m3u": "http://prov.example/x"}
    bi.build_provider(p, tmp_path)
    assert (tmp_path / "Bare.m3u").exists()
    assert not (tmp_path / "customTVGroups-Bare.xml").exists()
    assert (
        '<setting id="tvGroupMode">0</setting>'
        in (tmp_path / "instance-settings-1.xml").read_text()
    )


def test_build_provider_missing_required_fields_raise(tmp_path):
    with pytest.raises(RuntimeError, match="IPTV_1_M3U"):
        bi.build_provider({"_n": 1, "mode": "m3u"}, tmp_path)
    with pytest.raises(RuntimeError, match="IPTV_2_PORTAL"):
        bi.build_provider({"_n": 2, "mode": "xtream"}, tmp_path)
    with pytest.raises(RuntimeError, match="unknown"):
        bi.build_provider({"_n": 3, "mode": "weird"}, tmp_path)


# ===========================================================================
# build / main — the multi-provider walk + failure contract
# ===========================================================================
def _write_env(tmp_path, lines):
    env_file = tmp_path / ".env.local"
    env_file.write_text("\n".join(lines), encoding="utf-8")
    return env_file


def _two_provider_env(tmp_path):
    return _write_env(
        tmp_path,
        [
            "IPTV_1_NAME=My Prov",
            "IPTV_1_MODE=m3u",
            "IPTV_1_M3U=http://prov.example/list.m3u",
            "IPTV_1_GROUPS=Sports > Live Sports; News",
            "IPTV_2_NAME=Xt Prov",
            "IPTV_2_MODE=xtream",
            "IPTV_2_PORTAL=" + PORTAL,
            "IPTV_2_USER=" + USER,
            "IPTV_2_PASS=" + PW,
            "IPTV_2_GROUPS=10 > Sports",
            "IPTV_2_EPG=http://prov.example/epg.xml",
        ],
    )


def test_build_walks_both_modes(tmp_path, monkeypatch, capsys):
    _patch_http(monkeypatch)
    _patch_xtream(monkeypatch)
    env_file = _two_provider_env(tmp_path)
    out = tmp_path / "staging"
    failed = bi.build(env_file, out)
    assert failed == []
    assert (out / "MyProv.m3u").exists()
    assert (out / "instance-settings-1.xml").exists()
    assert (out / "XtProv.m3u").exists()
    assert (out / "instance-settings-2.xml").exists()
    printed = capsys.readouterr().out
    assert "My Prov" in printed and "Xt Prov" in printed
    # no creds in the printout
    assert USER not in printed and PW not in printed and PORTAL not in printed


def test_build_one_failed_provider_continues_and_reports(tmp_path, monkeypatch, capsys):
    # m3u fetch breaks (HTTP 500) but the xtream provider still builds
    monkeypatch.setattr(bi, "http_get", lambda url: (500, b""))
    _patch_xtream(monkeypatch)
    env_file = _two_provider_env(tmp_path)
    out = tmp_path / "staging"
    failed = bi.build(env_file, out)
    assert failed == [1]
    assert not (out / "instance-settings-1.xml").exists()
    assert (out / "instance-settings-2.xml").exists()
    assert "ERROR" in capsys.readouterr().out


def test_build_no_providers_is_a_clean_noop(tmp_path, capsys):
    env_file = _write_env(tmp_path, ["FOO=bar"])
    assert bi.build(env_file, tmp_path / "staging") == []
    assert "nothing to build" in capsys.readouterr().out


def test_main_exit_1_when_any_provider_failed(tmp_path, monkeypatch):
    monkeypatch.setattr(bi, "http_get", lambda url: (500, b""))
    _patch_xtream(monkeypatch)
    env_file = _two_provider_env(tmp_path)
    monkeypatch.setattr(
        sys,
        "argv",
        ["build_iptv.py", "--env", str(env_file), "--out", str(tmp_path / "s")],
    )
    with pytest.raises(SystemExit) as ei:
        bi.main()
    assert ei.value.code == 1


def test_main_green_run_exits_zero(tmp_path, monkeypatch, capsys):
    _patch_http(monkeypatch)
    _patch_xtream(monkeypatch)
    env_file = _two_provider_env(tmp_path)
    out = tmp_path / "s"
    monkeypatch.setattr(
        sys, "argv", ["build_iptv.py", "--env", str(env_file), "--out", str(out)]
    )
    bi.main()  # no SystemExit
    assert (out / "instance-settings-1.xml").exists()
    assert (out / "instance-settings-2.xml").exists()


def test_main_truncates_huge_group_lists(tmp_path, monkeypatch, capsys):
    # >40 categories exercises the xtream branch AND the group-list truncation
    cats = [{"category_id": str(i), "category_name": f"Cat{i}"} for i in range(50)]
    streams = [
        {"stream_id": i, "name": f"Ch{i}", "category_id": str(i)} for i in range(50)
    ]
    _patch_xtream(monkeypatch, streams=streams, cats=cats)
    env_file = _write_env(
        tmp_path,
        [
            "IPTV_1_NAME=Big",
            "IPTV_1_MODE=xtream",
            "IPTV_1_PORTAL=" + PORTAL,
            "IPTV_1_USER=" + USER,
            "IPTV_1_PASS=" + PW,
        ],
    )
    out = tmp_path / "build"
    monkeypatch.setattr(
        sys, "argv", ["build_iptv.py", "--env", str(env_file), "--out", str(out)]
    )
    bi.main()
    printed = capsys.readouterr().out
    assert (out / "Big.m3u").exists()
    assert "more groups" in printed  # truncation line printed
