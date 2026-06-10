#!/usr/bin/env python3
"""build_iptv.py — the HOST half of the IPTV layer (Phase 5b·2).

Builds the curated per-provider IPTV artifacts from a per-device ``.env`` into a
gitignored staging dir (``iptv-build/<device>/``). The IN-KODI half
(``tony7bones.setup.iptv._apply_staged_provider``) consumes the staged artifacts
when the per-device env carries ``IPTV_STAGING_DIR`` (the provisioner pushes the
staging dir to the box and appends that key) — the panel's "IPTV is two halves"
decision: host build + in-Kodi apply.

Per provider ``IPTV_<N>_*`` block this emits THREE artifacts into ``--out``:

  * ``<Token>.m3u``                 — the CURATED playlist (selected groups only,
                                      display-relabelled, per-group sorted,
                                      favorites tagged multi-group)
  * ``customTVGroups-<Token>.xml``  — the ordered DISPLAY-label group list
                                      (favorites first), the pvr.iptvsimple
                                      custom-groups file
  * ``instance-settings-<N>.xml``   — the full pvr.iptvsimple instance config
                                      (identity keys + local playlist +
                                      remote EPG + custom group mode), with
                                      ``m3uPath`` in the PORTABLE ``special://``
                                      form (the in-Kodi consumer rewrites it to
                                      the translated absolute path on copy)

``<Token>`` is the provider NAME with non-alphanumerics stripped (fallback
``Provider<N>``) — deliberately identical to the in-Kodi ``_groups_file_special``
derivation, so "Network 24" keeps the historical ``customTVGroups-Network24.xml``.

Two fetch modes (per provider, via ``IPTV_<N>_MODE``):

  * ``m3u``    — the provider serves a playlist: fetch ``IPTV_<N>_M3U`` and
                 curate it. Curation REQUIRES a local rewrite (relabel/sort
                 mutate ``group-title``/order), which is why a curated m3u-mode
                 provider becomes a staged LOCAL playlist, not a remote URL.
  * ``xtream`` — the m3u export is server-blocked (e.g. ``get.php`` -> HTTP 884):
                 SYNTHESIZE the playlist from the Xtream-Codes API
                 (``player_api.php`` ``get_live_categories``+``get_live_streams``;
                 channel URLs ``.../live/<user>/<pass>/<stream_id>.ts``).
                 pvr.iptvsimple Omega has NO native Xtream connection mode, so a
                 staged local playlist is the ONLY way this provider loads.

``IPTV_<N>_GROUPS`` grammar (``;``-separated): ``SOURCE > Display Label | sort``
  * SOURCE = the m3u ``group-title`` value (m3u mode) or the ``category_id``
    (xtream mode — panel category NAMES are decoration-heavy Unicode).
  * ``> Display Label`` (optional) relabels the group in Kodi.
  * ``| sort`` (optional) alpha-sorts the channels within that group.
  * groups appear in Kodi in the listed order; a group exists iff listed.
  * blank GROUPS = no curation (keep every channel/group as-is).

``IPTV_<N>_FAVORITES`` (``;``-separated) builds the hand-picked favorites group
(``IPTV_<N>_FAVORITES_NAME``, default "24/7 Favorites", emitted FIRST). Entries:
  * a channel-name substring — one best match (a non-PPV group preferred);
  * ``id:<stream_id>`` (xtream only) — pins one exact verified feed;
  * a bare ``category_id`` (xtream only) — folds that whole category in.
A favorite inside a selected group gets a multi-group title
(``group-title="Label;24/7 Favorites"``); one OUTSIDE every selected group is
emitted favorites-only (it survives trimming its origin group away).

Favorite ICONS are validated at build time (xtream mode): some panels stamp a
whole category with one dead placeholder ``stream_icon`` (live case: every
"US| CINEMA TV SHOWS" stream pointed at a 404 picon, so the curated favorites
rendered iconless in Kodi while every other group's icons worked). A favorite
whose icon is blank or not HTTP 200 borrows the icon of another copy of the
SAME channel (same normalized name core) elsewhere in the provider's stream
list that fetches live; if none exists the original is kept and noted.

Secrets: provider URLs/creds are read from the gitignored env and written ONLY
into the gitignored staging artifacts — never printed and never committed
(``test_secret_leak.py`` forbids tracked ``iptv-build/`` and ``*.m3u``).

Self-contained: stdlib only, imports no shipped add-on code, writes only to
``--out``. Exit code 1 if ANY provider failed to build (the provisioner warns
and the box falls back to the direct-env in-Kodi config for m3u providers).
"""

import argparse
import json
import re
import sys
import urllib.parse
import urllib.request
from pathlib import Path
from xml.sax.saxutils import escape as _xesc

UA = "VLC/3.0.20 LibVLC/3.0.20"
TIMEOUT = 90

_GROUP_RE = re.compile(r'group-title="([^"]*)"')
_NAME_RE = re.compile(r'tvg-name="([^"]*)"')
_EXTINF_HEAD_RE = re.compile(r"^(#EXTINF:[^\s,]*)")

DEFAULT_FAVORITES_NAME = "24/7 Favorites"

# The portable special:// dirs the staged instance-settings reference. The
# in-Kodi consumer translates them per-box; customTvGroupsFile ships the
# special:// form verbatim (live-proven), m3uPath is rewritten to the translated
# absolute path on copy (the form the POC proved pvr.iptvsimple loads).
PLAYLISTS_SPECIAL = "special://userdata/addon_data/pvr.iptvsimple/playlists"
GROUPS_SPECIAL = "special://userdata/addon_data/pvr.iptvsimple/channelGroups"


def http_get(url):
    """GET ``url`` with a player User-Agent (some panels reject default UAs)."""
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return r.status, r.read()


def load_env(path):
    """Parse the per-device .env (KEY=value; quotes, comments, blanks handled).

    Mirrors the shared ``tony7bones.setup.env.parse_env`` semantics (that module
    is not importable here without dragging the add-on package in)."""
    env = {}
    for raw in Path(path).read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        val = val.strip()
        if val[:1] in ("'", '"'):
            val = val[1:].split(val[0], 1)[0]
        else:
            val = val.split("#", 1)[0].strip()
        if key:
            env[key] = val
    return env


def providers(env):
    """The env's ``IPTV_<N>_*`` blocks as ordered provider dicts.

    One dict per N (numeric order; the env N doubles as the pvr.iptvsimple
    instance id), fields lowercased (``name``/``mode``/``m3u``/``portal``/...).
    ``mode`` defaults like the in-Kodi ``_iptv_providers``: ``xtream`` iff the
    block has a PORTAL but no M3U, else ``m3u``."""
    nums = sorted(
        {int(m.group(1)) for k in env for m in [re.match(r"^IPTV_(\d+)_", k)] if m}
    )
    out = []
    for n in nums:
        pfx = f"IPTV_{n}_"
        p = {k[len(pfx) :].lower(): v for k, v in env.items() if k.startswith(pfx)}
        p["_n"] = n
        mode = (p.get("mode") or "").strip().lower()
        if not mode:
            mode = "xtream" if (p.get("portal") and not p.get("m3u")) else "m3u"
        p["mode"] = mode
        out.append(p)
    return out


def parse_groups(spec):
    """``IPTV_<N>_GROUPS`` -> ordered [{src, label, sort}] (see module doc)."""
    groups = []
    for part in (spec or "").split(";"):
        part = part.strip()
        if not part:
            continue
        sort = False
        if "|" in part:
            head, *flags = part.split("|")
            sort = any(f.strip().lower() == "sort" for f in flags)
            part = head.strip()
        if ">" in part:
            src, label = (x.strip() for x in part.split(">", 1))
        else:
            src = label = part.strip()
        groups.append({"src": src, "label": label, "sort": sort})
    return groups


def token(name, n):
    """Provider NAME -> artifact token: non-alnum stripped, fallback Provider<N>.

    Identical to the in-Kodi ``_groups_file_special`` derivation, so
    "Network 24" -> ``Network24`` (the historical legacy filename)."""
    return re.sub(r"[^A-Za-z0-9]+", "", name or "") or f"Provider{n}"


# --------------------------------------------------------------------------- #
# m3u mode — fetch the provider playlist and curate it.
# --------------------------------------------------------------------------- #
def parse_m3u_text(text):
    """The playlist as ordered (extinf-line, url) pairs (header skipped)."""
    lines = text.splitlines()
    i = 1 if lines and lines[0].startswith("#EXTM3U") else 0
    chans = []
    while i < len(lines):
        if lines[i].startswith("#EXTINF"):
            url = lines[i + 1].strip() if i + 1 < len(lines) else ""
            chans.append((lines[i], url))
            i += 2
        else:
            i += 1
    return chans


def _chan_name(extinf):
    """A channel's display name: tvg-name when present, else after the comma."""
    m = _NAME_RE.search(extinf)
    if m and m.group(1):
        return m.group(1)
    return extinf.rsplit(",", 1)[-1].strip() if "," in extinf else ""


def _chan_group(extinf):
    """A channel's source group-title value ('' when absent)."""
    m = _GROUP_RE.search(extinf)
    return m.group(1) if m else ""


def _set_group_title(extinf, group):
    """Return ``extinf`` with its group-title set to ``group`` (added if absent)."""
    if _GROUP_RE.search(extinf):
        return _GROUP_RE.sub(f'group-title="{group}"', extinf)
    return _EXTINF_HEAD_RE.sub(rf'\1 group-title="{group}"', extinf, count=1)


def _resolve_m3u_favorites(spec, chans):
    """``IPTV_<N>_FAVORITES`` -> ordered de-duped channel INDEXES (m3u mode).

    m3u channels have no stream ids, so only the name-substring form applies:
    each entry adds the one best name match, preferring a channel whose source
    group-title does not look like PPV. The xtream-only ``id:``/bare-category
    forms are ignored with a printed note (they cannot mean anything here)."""
    fav, seen = [], set()
    for item in (spec or "").split(";"):
        item = item.strip()
        if not item:
            continue
        if item.lower().startswith("id:") or item.isdigit():
            print(
                f"  note: favorites entry {item!r} is xtream-only — ignored in m3u mode"
            )
            continue
        matches = [
            i
            for i, (extinf, _u) in enumerate(chans)
            if item.lower() in _chan_name(extinf).lower()
        ]
        if not matches:
            print(f"  note: favorites entry {item!r} matched no channel")
            continue
        nonppv = [i for i in matches if "ppv" not in _chan_group(chans[i][0]).lower()]
        pick = (nonppv or matches)[0]
        if pick not in seen:
            seen.add(pick)
            fav.append(pick)
    return fav


def build_m3u_mode(p):
    """Fetch + curate an m3u-mode provider.

    Returns ``(playlist_text, counts, labels)`` — ``labels`` is the ordered
    DISPLAY group list for the customTVGroups file (favorites first); with a
    blank GROUPS spec every channel/group passes through as-is (discovery
    mode)."""
    status, body = http_get(p["m3u"])
    if status != 200 or b"#EXTINF" not in body:
        raise RuntimeError(f"m3u fetch failed: HTTP {status}, {len(body)} bytes")
    chans = parse_m3u_text(body.decode("utf-8", "replace"))
    specs = parse_groups(p.get("groups", ""))
    fav_label = (p.get("favorites_name") or "").strip() or DEFAULT_FAVORITES_NAME
    fav_idx = _resolve_m3u_favorites(p.get("favorites", ""), chans)
    fav_set = set(fav_idx)

    out, counts, labels = ["#EXTM3U"], {}, []
    if fav_idx:
        labels.append(fav_label)
        counts[fav_label] = len(fav_idx)

    if specs:
        buckets = {s["src"]: [] for s in specs}
        for i, (extinf, _url) in enumerate(chans):
            g = _GROUP_RE.search(extinf)
            if g and g.group(1) in buckets:
                buckets[g.group(1)].append(i)
        emitted = set()
        for s in specs:
            idxs = buckets.get(s["src"], [])
            if s["sort"]:
                idxs = sorted(idxs, key=lambda i: _chan_name(chans[i][0]).lower())
            for i in idxs:
                extinf, url = chans[i]
                group = f"{s['label']};{fav_label}" if i in fav_set else s["label"]
                out.append(_set_group_title(extinf, group))
                out.append(url)
                emitted.add(i)
            counts[s["label"]] = len(idxs)
            labels.append(s["label"])
        # favorites whose source group was trimmed away -> favorites-only
        for i in fav_idx:
            if i not in emitted:
                extinf, url = chans[i]
                out.append(_set_group_title(extinf, fav_label))
                out.append(url)
    else:
        # no curation: keep everything as-is (favorites still tagged multi-group)
        for i, (extinf, url) in enumerate(chans):
            g = _GROUP_RE.search(extinf)
            lbl = g.group(1) if g else ""
            if i in fav_set:
                group = f"{lbl};{fav_label}" if lbl else fav_label
                out.append(_set_group_title(extinf, group))
            else:
                out.append(extinf)
            out.append(url)
            key = lbl or "(none)"
            counts[key] = counts.get(key, 0) + 1
            if lbl and lbl not in labels:
                labels.append(lbl)
    return "\n".join(out) + "\n", counts, labels


# --------------------------------------------------------------------------- #
# xtream mode — synthesize the playlist from the Xtream-Codes player_api.
# --------------------------------------------------------------------------- #
def xtream_api(portal, user, pw, action, **params):
    q = {"username": user, "password": pw, "action": action, **params}
    url = portal.rstrip("/") + "/player_api.php?" + urllib.parse.urlencode(q)
    _, body = http_get(url)
    return json.loads(body)


def _resolve_favorites(spec, all_streams, by_cat, cat_name):
    """``IPTV_<N>_FAVORITES`` -> ordered de-duped stream_ids (xtream mode).

    Entries: ``id:<stream_id>`` (exact pin), a bare ``category_id`` (whole
    category), or a channel-name substring (one best match, non-PPV category
    preferred — duplicate PPV copies are often dead ``black.ts`` placeholders)."""
    fav_ids, seen = [], set()
    by_id = {str(s.get("stream_id")): s for s in all_streams}

    def add(s):
        sid = s.get("stream_id")
        if sid not in seen:
            seen.add(sid)
            fav_ids.append(sid)

    for item in (spec or "").split(";"):
        item = item.strip()
        if not item:
            continue
        if item.lower().startswith("id:"):
            s = by_id.get(item[3:].strip())
            if s:
                add(s)
            continue
        if item.isdigit():
            for s in by_cat.get(item, []):
                add(s)
            continue
        matches = [
            s for s in all_streams if item.lower() in (s.get("name") or "").lower()
        ]
        if not matches:
            continue
        nonppv = [
            s
            for s in matches
            if "ppv" not in (cat_name.get(str(s.get("category_id")), "")).lower()
        ]
        add((nonppv or matches)[0])
    return fav_ids


# Decoration tokens dropped when normalizing a channel name to its "core"
# (quality tags + the 24/7 marker split into bare tokens by the regex).
_NAME_NOISE = {"24", "7", "4k", "uhd", "fhd", "hd", "sd", "raw", "60fps"}


def _name_core(name):
    """A channel name reduced to its comparable core.

    Lowercase, country/prefix tag stripped (``US:`` / ``UK|``), every
    non-alphanumeric run (incl. the panels' Unicode superscript decorations)
    collapsed to a space, quality/24-7 noise tokens dropped:
    ``"US: THE SIMPSONS 4K"`` == ``"24/7: THE SIMPSONS"`` -> ``"the simpsons"``."""
    s = (name or "").lower()
    s = re.sub(r"^[a-z]{2,3}\s*[:|]", "", s)
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return " ".join(t for t in s.split() if t not in _NAME_NOISE)


def _icon_alive(url, cache):
    """True iff ``url`` fetches HTTP 200 (memoized in ``cache``; blank/error = dead)."""
    if url not in cache:
        try:
            cache[url] = bool(url) and http_get(url)[0] == 200
        except Exception:  # noqa: BLE001 - any fetch failure just means "dead icon"
            cache[url] = False
    return cache[url]


def _fix_favorite_icons(fav_ids, stream_by_id, all_streams):
    """stream_id -> replacement icon URL for favorites whose own icon is dead.

    The curated favorites are the box's hand-picked shelf — a dead provider
    placeholder there is the ONE place iconless tiles are guaranteed to be
    noticed (live case: the whole "US| CINEMA TV SHOWS" category shared one
    404 picon). For each favorite whose ``stream_icon`` is blank or dead,
    borrow the first LIVE icon from another stream with the same name core
    (providers carry several copies of these channels across categories).
    Only favorites are checked — validating every emitted channel would mean
    hundreds of fetches per build for groups that already render fine."""
    cache, fixes = {}, {}
    for sid in fav_ids:
        s = stream_by_id[sid]
        if _icon_alive(s.get("stream_icon") or "", cache):
            continue
        core = _name_core(s.get("name"))
        donor = None
        if core:
            for t in all_streams:
                cand = t.get("stream_icon") or ""
                if (
                    cand
                    and _name_core(t.get("name")) == core
                    and _icon_alive(cand, cache)
                ):
                    donor = t
                    break
        if donor:
            fixes[sid] = donor.get("stream_icon")
            print(
                f"  note: favorite {s.get('name')!r} icon is dead — "
                f"borrowing the icon of {donor.get('name')!r}"
            )
        else:
            print(
                f"  note: favorite {s.get('name')!r} icon is dead — "
                "no live same-channel alternate found, keeping it"
            )
    return fixes


def build_xtream_mode(p):
    """Synthesize + curate an xtream-mode provider's playlist from the API.

    Returns ``(playlist_text, counts, labels)``. SOURCE side of the groups
    grammar is the ``category_id``; blank GROUPS selects every live category
    (discovery mode). Channel URLs take the standard Xtream live form."""
    portal, user, pw = p["portal"], p["user"], p["pass"]
    cats = xtream_api(portal, user, pw, "get_live_categories")
    cat_name = {str(c["category_id"]): c["category_name"] for c in cats}
    all_streams = xtream_api(portal, user, pw, "get_live_streams")
    by_cat = {}
    for s in all_streams:
        by_cat.setdefault(str(s.get("category_id")), []).append(s)

    specs = parse_groups(p.get("groups", ""))
    if specs:
        selected = [(s["src"], s["label"], s["sort"]) for s in specs]
    else:
        selected = [
            (str(c["category_id"]), cat_name[str(c["category_id"])], False)
            for c in cats
        ]

    fav_label = (p.get("favorites_name") or "").strip() or DEFAULT_FAVORITES_NAME
    fav_ids = _resolve_favorites(p.get("favorites", ""), all_streams, by_cat, cat_name)
    fav_set = set(fav_ids)
    stream_by_id = {s.get("stream_id"): s for s in all_streams}
    # heal dead favorite icons (the hand-picked shelf must render icons)
    icon_fix = _fix_favorite_icons(fav_ids, stream_by_id, all_streams)

    out, counts, labels = ["#EXTM3U"], {}, []
    base = portal.rstrip("/")

    def emit(s, group):
        tvg = s.get("epg_channel_id") or ""
        logo = icon_fix.get(s.get("stream_id")) or s.get("stream_icon") or ""
        out.append(
            f'#EXTINF:-1 tvg-id="{tvg}" tvg-logo="{logo}" '
            f'group-title="{group}",{s.get("name", "")}'
        )
        out.append(f"{base}/live/{user}/{pw}/{s.get('stream_id')}.ts")

    if fav_ids:
        labels.append(fav_label)
        counts[fav_label] = len(fav_ids)

    emitted = set()
    for cid, label, sort in selected:
        streams = by_cat.get(cid, [])
        if sort:
            streams = sorted(streams, key=lambda s: (s.get("name") or "").lower())
        for s in streams:
            sid = s.get("stream_id")
            # a favorite stays in its own group AND joins favorites (multi-group)
            group = f"{label};{fav_label}" if sid in fav_set else label
            emit(s, group)
            emitted.add(sid)
        counts[label] = len(streams)
        labels.append(label)

    # favorites outside every selected group -> emit them favorites-only
    for sid in fav_ids:
        if sid not in emitted and sid in stream_by_id:
            emit(stream_by_id[sid], fav_label)

    return "\n".join(out) + "\n", counts, labels


# --------------------------------------------------------------------------- #
# Artifact emission — playlist + customTVGroups + instance-settings per provider.
# --------------------------------------------------------------------------- #
def _custom_groups_xml(labels):
    out = ["<customChannelGroups>"]
    for g in labels:
        out.append(f"  <channelGroupName>{_xesc(g)}</channelGroupName>")
    out.append("</customChannelGroups>")
    return "\n".join(out) + "\n"


def _instance_xml(p, tok, labels):
    """The staged pvr.iptvsimple ``instance-settings-<N>.xml`` for one provider.

    Identity keys (name + enabled) make the instance real to Kodi's
    multi-instance scanner; the playlist is the staged LOCAL file
    (``m3uPathType=0``, ``m3uPath`` in the portable special:// form the in-Kodi
    consumer rewrites to the translated absolute path); the EPG stays REMOTE
    (``epgPathType=1`` + the env URL). Custom group mode is GATED on the
    curated group list being non-empty (never ``tvGroupMode=2`` at an empty
    groups file — that would load zero channels); ``tvChannelGroupsOnly``
    honors ``IPTV_<N>_GROUPS_ONLY`` (default true) and is forced false when
    favorites exist WITHOUT a groups selection (the favorites group must not
    hide the rest of an uncurated playlist)."""
    n = p["_n"]
    name = (p.get("name") or "").strip() or f"Provider{n}"
    only = (p.get("groups_only", "true") or "true").strip().lower()
    only_val = "true" if only in ("true", "1", "yes", "on") else "false"
    if labels and not parse_groups(p.get("groups", "")):
        only_val = "false"  # favorites-only curation must not hide the rest
    lines = [
        '<settings version="2">',
        f'    <setting id="kodi_addon_instance_name">{_xesc(name)}</setting>',
        '    <setting id="kodi_addon_instance_enabled">true</setting>',
        '    <setting id="m3uPathType">0</setting>',
        f'    <setting id="m3uPath">{_xesc(f"{PLAYLISTS_SPECIAL}/{tok}.m3u")}</setting>',
        '    <setting id="m3uUrl" />',
        '    <setting id="m3uCache">true</setting>',
        '    <setting id="startNum">1</setting>',
        '    <setting id="numberByOrder">false</setting>',
        '    <setting id="m3uRefreshMode">0</setting>',
    ]
    if labels:
        lines += [
            '    <setting id="tvGroupMode">2</setting>',
            '    <setting id="customTvGroupsFile">'
            f"{_xesc(f'{GROUPS_SPECIAL}/customTVGroups-{tok}.xml')}</setting>",
            f'    <setting id="tvChannelGroupsOnly">{only_val}</setting>',
        ]
    else:
        lines += [
            '    <setting id="tvGroupMode">0</setting>',
            '    <setting id="tvChannelGroupsOnly">false</setting>',
        ]
    lines += [
        '    <setting id="radioGroupMode">0</setting>',
        '    <setting id="radioChannelGroupsOnly">false</setting>',
        '    <setting id="epgPathType">1</setting>',
        '    <setting id="epgPath" />',
        f'    <setting id="epgUrl">{_xesc(p.get("epg", ""))}</setting>',
        '    <setting id="epgCache">true</setting>',
        '    <setting id="logoFromEpg">1</setting>',
        '    <setting id="useFFmpegReconnect">true</setting>',
        "</settings>",
    ]
    return "\n".join(lines) + "\n"


def build_provider(p, outdir):
    """Build ONE provider's three artifacts into ``outdir``.

    Raises on a fetch/API failure (the caller reports + continues with the
    other providers). Returns ``(name, mode, counts, labels)``."""
    n = p["_n"]
    mode = p["mode"]
    if mode == "xtream":
        for field in ("portal", "user", "pass"):
            if not (p.get(field) or "").strip():
                raise RuntimeError(
                    f"xtream provider {n} is missing IPTV_{n}_{field.upper()}"
                )
        text, counts, labels = build_xtream_mode(p)
    elif mode == "m3u":
        if not (p.get("m3u") or "").strip():
            raise RuntimeError(f"m3u provider {n} is missing IPTV_{n}_M3U")
        text, counts, labels = build_m3u_mode(p)
    else:
        raise RuntimeError(f"provider {n}: unknown IPTV_{n}_MODE {mode!r}")
    name = (p.get("name") or "").strip() or f"Provider{n}"
    tok = token(p.get("name"), n)
    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    (outdir / f"{tok}.m3u").write_text(text, encoding="utf-8")
    if labels:
        (outdir / f"customTVGroups-{tok}.xml").write_text(
            _custom_groups_xml(labels), encoding="utf-8"
        )
    (outdir / f"instance-settings-{n}.xml").write_text(
        _instance_xml(p, tok, labels), encoding="utf-8"
    )
    return name, mode, counts, labels


def build(env_path, outdir):
    """Build EVERY provider from the env into ``outdir``.

    Per-provider failures are reported and skipped (the others still build).
    Returns the list of failed provider numbers (empty = all built)."""
    env = load_env(env_path)
    provs = providers(env)
    if not provs:
        print(f"no IPTV_<N>_* providers in {env_path} — nothing to build")
        return []
    failed = []
    for p in provs:
        n = p["_n"]
        name = (p.get("name") or "").strip() or f"Provider{n}"
        print(f"=== [{n}] {name} (mode={p['mode']}) ===")
        try:
            _name, _mode, counts, labels = build_provider(p, outdir)
        except Exception as e:  # noqa: BLE001 - one bad provider must not stop the rest
            print(f"  ERROR: {type(e).__name__}: {e}")
            failed.append(n)
            continue
        total = sum(counts.values())
        shown = labels or list(counts)
        print(f"  built {total} channels in {len(shown)} group(s)")
        for lbl in shown[:40]:
            print(f"    - {lbl}: {counts.get(lbl, 0)}")
        if len(shown) > 40:
            print(f"    ... (+{len(shown) - 40} more groups)")
    return failed


def main():
    ap = argparse.ArgumentParser(
        description="Build curated IPTV artifacts from a per-device .env "
        "into a gitignored staging dir."
    )
    ap.add_argument("--env", default=".env.local", help="per-device .env file")
    ap.add_argument("--out", default="iptv-build/local", help="staging output dir")
    args = ap.parse_args()
    print(f"env: {args.env}   out: {args.out}/")
    failed = build(args.env, args.out)
    if failed:
        print(f"FAILED providers: {failed}")
        sys.exit(1)


if __name__ == "__main__":
    main()
