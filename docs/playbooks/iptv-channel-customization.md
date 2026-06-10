# Playbook — IPTV channel / list / group customization (`.env`-driven)

> How we turn a raw IPTV subscription into a curated, grouped, favorites-bearing set of
> Kodi `pvr.iptvsimple` channels — driven entirely by a gitignored per-device `.env`,
> built HOST-side by `_tools/build_iptv.py`, applied IN-Kodi by the IPTV layer
> (`tony7bones.setup.iptv`). Captures the two fetch modes (**m3u** vs **xtream**),
> where/why each applies, the group/favorites grammar, the staged-artifact handoff,
> the Kodi multi-instance wiring, and the hard-won gotchas.
>
> Status: shipped (Phase 5b·2 of the modular-setup rewrite; originally developed as a
> POC on the `iptv` branch). Credentials live in `~/.dotfiles/VAULT.md` §22. Nothing in
> this flow writes to the committed repo tree — outputs go to gitignored `iptv-build/`
> and the box/Kodi profile only.

---

## The mental model — "IPTV is two halves"

```
.env.<device>  ──►  _tools/build_iptv.py  ──►  iptv-build/<device>/     (gitignored)
 (gitignored,         per provider:               <Token>.m3u             curated playlist
  source of truth)    fetch → curate → emit       customTVGroups-<Token>  display-label list
                                                  instance-settings-<N>   ready pvr config
                                │
                                ▼  provisioner pushes the dir to the box +
                                   appends IPTV_STAGING_DIR to tony7bones.env
                /storage/emulated/0/kodi/tony.7.bones/iptv/   (device staging)
                                │
                                ▼  in-Kodi: apply_iptv → _apply_staged_provider
                                   (inside the PVR-DISABLED config window)
                userdata/addon_data/pvr.iptvsimple/           ← one INSTANCE per provider
```

**One per-device `.env` is the single source of truth.** Each `IPTV_<N>_*` block becomes
one `pvr.iptvsimple` _instance_ (two providers = `instance-settings-1.xml` +
`instance-settings-2.xml`, each with its own channels/EPG/groups). Everything generated
(playlist, custom-groups file, instance settings) is a build artifact — never
hand-edited, never committed.

- **Host half** (`_tools/build_iptv.py`, run by the provisioner — or by hand): fetches
  each provider, applies the FULL groups grammar (selection, display relabel, `| sort`,
  favorites), and emits the three artifacts per provider into `iptv-build/<device>/`.
  `<Token>` = the provider NAME with non-alphanumerics stripped (`"Network 24"` →
  `Network24` — identical to the in-Kodi derivation, so the legacy
  `customTVGroups-Network24.xml` filename is preserved).
- **In-Kodi half** (`apply_iptv` → `_apply_staged_provider`): when the per-device env
  carries `IPTV_STAGING_DIR` (the provisioner sets it iff staging landed; there is
  deliberately NO default), each provider consumes its staged artifacts — copy the
  playlist + groups file to their `special://` homes, rewrite `m3uPath` to the
  translated absolute path, write the instance file — all inside the PVR-disabled
  config window. Consumption is PARSE-based (it reads what the staged instance file
  references) and validates every side-file exists BEFORE writing anything; on
  no/partial/malformed staging the provider falls back to the direct-env enforce
  (remote `m3uUrl` + SOURCE-name groups — the Phase 5b·1 behaviour). An xtream-mode
  provider has NO fallback (see below) and is skipped with a loud log when unstaged.

```bash
# build by hand (the provisioner runs this for you):
python3 _tools/build_iptv.py --env .env.local --out iptv-build/local
# exit code 1 if ANY provider failed (the others still build — partial staging works)
```

---

## The two fetch modes — `m3u` vs `xtream` (the crux)

IPTV providers are almost all **Xtream-Codes panels**, which expose _two_ ways to get the
channel list. Which one works is per-provider and **must be discovered**, not assumed.

| Mode         | When to use                                      | How it fetches                                                                                                                 | Channel URL                           |
| ------------ | ------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------ | ------------------------------------- |
| **`m3u`**    | Provider's `get.php` playlist endpoint **works** | `GET …/get.php?username=&password=&type=m3u_plus&output=ts` → a real `#EXTM3U` with `group-title=` per channel                 | URLs come straight from the m3u       |
| **`xtream`** | `get.php` is **blocked/disabled**                | Xtream API: `…/player_api.php?…&action=get_live_categories` + `…&action=get_live_streams`; we **synthesize** the m3u ourselves | `…/live/<user>/<pass>/<stream_id>.ts` |

### Why a provider needs `xtream` mode — the Streamvision case

Streamvision's `get.php` returns **`HTTP 884` with an empty body on every mirror host** —
the panel has m3u export disabled account-wide (anti-list-sharing). But `player_api.php`
(auth, categories, streams) and `xmltv.php` (EPG) work fine, and the live stream URLs play.
That's exactly how player apps (TiviMate) consume it — via the Xtream API, not an m3u.

And `pvr.iptvsimple` (Omega 21.x) has **no native Xtream-Codes connection mode** (its only
XTREAM schema reference is a catchup enum) — so the host-side synthesis is the ONLY way an
xtream-mode provider can load in Kodi. This is why the staged-artifact path exists.

> **Diagnosis recipe** when an m3u URL fails: test the same creds against
> `player_api.php?…` (no action) — if it returns `{"user_info":{"auth":1,…}}`, the account
> is alive and you should switch that provider to `xtream` mode. A non-standard HTTP code
> (884, etc.) with an empty body on `get.php` = m3u export deliberately disabled.

Network 24, by contrast, serves a normal `get.php` m3u (~7,500 channels) → `m3u` mode.

### Why m3u mode ALSO becomes a staged local playlist

Display relabel (`> Label`) and `| sort` **mutate** `group-title` values and channel
order — impossible against a remote URL. A curated m3u provider is therefore fetched,
rewritten, and staged as a local file (`m3uPathType=0`). The snapshot is refreshed on
every provisioner run; the direct-env fallback (remote `m3uUrl`, SOURCE-name groups, no
relabel/sort/favorites) still works when staging is absent.

### `.env` shape for each mode

```ini
# m3u mode — provider serves a playlist
IPTV_1_NAME="Network 24"
IPTV_1_MODE="m3u"
IPTV_1_M3U="http://iptv-a.example:8080/get.php?username=…&password=…&type=m3u_plus&output=ts"
IPTV_1_EPG="http://iptv-a.example:8080/xmltv.php?username=…&password=…"
IPTV_1_GROUPS="USA ENTERTAINMENT > US Entertainment | sort; USA NEWS/WEATHER > US News/Weather | sort; PPV EVENTS > PPV Events"
IPTV_1_GROUPS_ONLY="true"

# xtream mode — m3u blocked, build from the Xtream API
IPTV_2_NAME="Streamvision"
IPTV_2_MODE="xtream"
IPTV_2_PORTAL="http://iptv-b.example"
IPTV_2_USER="<username>"
IPTV_2_PASS="<password>"
IPTV_2_EPG="http://iptv-b.example/xmltv.php?username=…&password=…"
IPTV_2_GROUPS="58 > US Entertainment | sort; 491 > US News | sort; 1139 > UFC PPV"
IPTV_2_FAVORITES="Rick and Morty; South Park; Family Guy; id:<simpsons_stream_id>; id:<archer_stream_id>"
IPTV_2_GROUPS_ONLY="true"
```

(`IPTV_<N>_MODE` may be omitted: a block with a PORTAL and no M3U defaults to `xtream`,
else `m3u` — both halves apply the same rule.)

---

## The `IPTV_<N>_GROUPS` grammar (selection + relabel + sort + order)

`IPTV_<N>_GROUPS` is a `;`-separated list. Each entry: **`SOURCE > Display Label | sort`**

- **`SOURCE`** — in `m3u` mode it's the source group's `group-title` name (e.g.
  `USA ENTERTAINMENT`); in `xtream` mode it's the **`category_id`** (e.g. `58`).
  _Use `category_id`, not the name, for xtream_ — panel category names are decoration-heavy
  Unicode (`US| ENTERTAINMENT ᴴᴰ/ᴿᴬᵂ ⁶⁰ᶠᵖˢ`) and brutal to match by hand.
- **`> Display Label`** _(optional)_ — the clean group name shown in Kodi. Omit to keep the
  source name. This label is what lands in the generated `customTVGroups-*.xml` AND in the
  curated playlist's rewritten `group-title`.
- **`| sort`** _(optional)_ — alpha-sort the channels within that group.
- **Order** — groups appear in Kodi in the order listed.
- **Blank `IPTV_<N>_GROUPS`** — no curation; load every group as-is (use this once to
  _discover_ what a provider offers, then trim). In this mode `tvChannelGroupsOnly` is
  forced off so group-less channels stay visible.

To find xtream `category_id`s: run the builder with blank groups once, or query
`player_api.php?…&action=get_live_categories` and read the `category_id`/`category_name`
pairs.

### Curate vs. hide a group

There is no separate "hide" — **a group exists iff it's listed in `IPTV_<N>_GROUPS`.** To
hide groups, delete their lines and rebuild. Because we run in **groups-only** mode
(`tvChannelGroupsOnly=true`), removing a group also removes its channels from "All
channels". (Kodi's native per-group hide lives in the PVR DB, isn't automatable, and is
lost on every rebuild — don't use it.)

---

## Favorites — a hand-picked group across categories (`IPTV_<N>_FAVORITES`)

`IPTV_<N>_FAVORITES` is a `;`-separated list that builds a **"24/7 Favorites"** group
(name overridable via `IPTV_<N>_FAVORITES_NAME`, emitted first). Each entry is one of:

| Entry form       | Meaning                                                                           |
| ---------------- | --------------------------------------------------------------------------------- |
| `Rick and Morty` | **name substring** — adds the one best match (a non-PPV category/group preferred) |
| `id:<stream_id>` | **exact `stream_id`** (xtream only) — pins one specific, verified feed            |
| `2063`           | **whole `category_id`** (xtream only) — folds that entire category into Favorites |

In `m3u` mode only the name-substring form applies (m3u channels have no stream/category
ids); `id:`/numeric entries are ignored with a printed note.

**Why `id:` matters:** name matching can land a duplicate or a dead copy (the same show
often exists in a 24/7 group _and_ a `…PPV` group, and the PPV copy may be a `black.ts`
placeholder). Stream-verify a channel first, then pin it by `id:<stream_id>`.

**Multi-group, not duplication:** a favorite that's also in a selected group is tagged with
a semicolon group-title (`group-title="24/7 Cartoon;24/7 Favorites"`) so it appears in both
— one channel, two groups. A favorite whose source group is _not_ selected is emitted
**favorites-only**, so Favorites survives even after you trim away its origin group.
Favorites WITHOUT a groups selection force `tvChannelGroupsOnly=false` (the favorites
group must never hide the rest of an uncurated playlist).

**Favorite icons are healed at build time (xtream mode).** Some panels stamp a whole
category with ONE placeholder `stream_icon` that 404s — live case: every stream in
Streamvision's "US| CINEMA TV SHOWS" category (the source of all five favorites) pointed
at the same dead picon, so the 24/7 Favorites group rendered **iconless** in Kodi while
every other group's icons worked. The builder now HTTP-checks each favorite's icon
(memoized; blank = dead) and, when dead, borrows the first **live** icon from another copy
of the same channel elsewhere in the stream list (same normalized name core —
`"US: THE SIMPSONS 4K"` ≡ `"24/7: THE SIMPSONS"`; country prefix, `24/7` markers, quality
tags, and Unicode decorations are ignored). No donor → the original is kept and a note is
printed. Only favorites are checked — validating every emitted channel would cost hundreds
of fetches for groups that already render fine. `m3u` mode reuses the provider's EXTINF
verbatim and is deliberately not healed (the observed failure is xtream's category-wide
placeholder).

---

## Honest verification — an HTTP 200 is NOT proof it plays

Dead IPTV feeds frequently return **`HTTP 200` and even push bytes**, but redirect to a
`…/video/black.ts` (or similar) **black-screen placeholder**. To confirm a channel is
genuinely streaming:

1. Follow redirects (`curl -L`) — the panel 302s to an edge node.
2. Sample a few seconds of the `.ts`.
3. Check it's a valid **MPEG-TS** (sync byte `0x47` at every 188-byte boundary) at a real
   bitrate, and that the edge URL is **not** `black.ts`.

```bash
# verify one stream really plays (no ffprobe needed)
URL="http://<portal>/live/<user>/<pass>/<stream_id>.ts"
curl -sS -L -m 6 -A "VLC/3.0.20 LibVLC/3.0.20" -o /tmp/s.ts "$URL"
python3 - <<'PY'
d=open('/tmp/s.ts','rb').read(); pk=min(len(d)//188,200)
sync=sum(1 for i in range(pk) if d[i*188]==0x47)
print(f"{len(d)/1024:.0f} KB, TS-sync {sync}/{pk}", "STREAMING" if sync>pk*0.9 and len(d)>50000 else "DUD")
PY
# also check the edge URL it redirects to:
curl -sS -m 6 -A "VLC/3.0.20 LibVLC/3.0.20" -D - -o /dev/null "$URL" | grep -i location   # 'black.ts' => dead
```

> A player **User-Agent** (`VLC/…`) is sometimes required; default curl can be rejected.

---

## Kodi side — `pvr.iptvsimple` multi-instance wiring

`pvr.iptvsimple` (Omega) registers **one instance per `instance-settings-<N>.xml`** in
`userdata/addon_data/pvr.iptvsimple/`. Two keys make Kodi enumerate + enable an instance:

```xml
<setting id="kodi_addon_instance_name">Streamvision</setting>
<setting id="kodi_addon_instance_enabled">true</setting>
```

Per-instance settings the staged artifact carries:

| Setting                   | Value                                                  | Why                                                                                                                                                          |
| ------------------------- | ------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `m3uPathType` / `m3uPath` | `0` (Local) + the staged curated `.m3u`                | local file; staged as portable `special://…/playlists/<Token>.m3u`, REWRITTEN to the translated absolute path by the in-Kodi consumer (the live-proven form) |
| `epgPathType` / `epgUrl`  | `1` (Remote) + the provider `xmltv.php` URL            | EPG fetched live                                                                                                                                             |
| `tvGroupMode`             | `2` (custom) — GATED on a non-empty curated group list | use our custom-groups file (never `2` at an empty list — zero channels)                                                                                      |
| `customTvGroupsFile`      | `special://…/channelGroups/customTVGroups-<Token>.xml` | the display-label group list (special:// form is live-proven)                                                                                                |
| `tvChannelGroupsOnly`     | `IPTV_<N>_GROUPS_ONLY` (default `true`)                | only load channels that are in a listed group                                                                                                                |

> **Instance settings are NOT reachable via JSON-RPC.** `Settings.SetSettingValue` only
> touches _core_ Kodi settings — `pvr.iptvsimple` instance settings live _only_ in that XML.
> Write the file; Kodi reads it **at startup** (so changes need a restart). And write it
> inside the **PVR-disabled config window** (`_pause_pvr_for_config`) or the live client
> flushes its stale in-memory defaults back over your write (the Phase 5b·1 clobber —
> one instance of a general Kodi pattern; see `kodi-settings-clobber.md` for the class
> and the two fix mechanisms).

> **EPG binds by `tvg-id`.** Channels whose source playlist has an empty `tvg-id` show no
> programme data — a source-data limitation, not a config bug. (Most Streamvision 24/7
> channels lack `tvg-id`; broadcast feeds have them.)

---

## Applying changes (rebuild → re-provision → restart → verify)

Instance settings only load at startup, and **the PVR database keeps a group around even
after you drop it from the file** (it lingers as an empty group). So after a change that
_removes_ groups, reset the PVR DB for a clean list:

```bash
# 1) edit .env.<device>, then re-run the provisioner (it rebuilds + re-stages):
_tools/provision-kodi.sh <device>

# …or for the LOCAL Kodi: rebuild + let apply_iptv consume the staging
python3 _tools/build_iptv.py --env .env.local --out iptv-build/local

# 2) quit Kodi cleanly (JSON-RPC), reset PVR DB, relaunch
#    Application.Quit  →  rm userdata/Database/TV*.db  →  relaunch

# 3) verify over JSON-RPC (PVR.GetChannelGroups + PVR.GetChannels per group)
```

Verify by **real counts from JSON-RPC**, not assumptions: each group count should match
the builder's printed counts, and the DISPLAY labels (not the SOURCE names) must appear.
Add `"properties":["icon"]` to `PVR.GetChannels` to audit per-channel icons (how the
dead-favorites-icon placeholder was caught), and always prove **restart-survival** —
a clean-shutdown quit + relaunch, then re-check the instance files AND the counts
(the clobber class only shows up across that flush). The full honest-PVR recipe
(JSON-RPC payloads, PVR-DB cross-check, screenshot proof) lives in
`local-kodi-verification.md` → "Verifying PVR / IPTV state".

> **Gotcha:** don't double-background. Running `python … &` _inside_ a backgrounded shell
> detaches stdout and you lose the verification output. Run the verify script in the
> foreground of one backgrounded task.

---

## Gotchas / lessons (don't relearn these)

- **m3u blocked ≠ account dead.** `get.php` 884/empty on a live account = m3u export off →
  use `xtream` mode. Confirm with `player_api.php` (`auth:1`).
- **HTTP 200 ≠ streaming.** Dead feeds serve `black.ts`. Always sample-and-verify before
  trusting (or favoriting) a channel.
- **Pin favorites by `id:`** once verified — names drift across duplicate/PPV copies.
- **xtream groups by `category_id`**, not the decorated Unicode name.
- **Instance settings are XML-only** (no JSON-RPC); read at startup → restart to apply;
  write them inside the PVR-disabled window or the live client clobbers them.
- **Removed groups linger** as empties in the PVR DB → reset `TV*.db` after a trim. The
  same applies to a REDUCED provider count: stale `instance-settings-<N>.xml` files from
  a previous run are not auto-deleted (drop them by hand + reset the DB).
- **Same display label across providers merges in Kodi's group list** (e.g. both
  providers labelling a group "US Entertainment") — give providers distinct labels if you
  want separate rows.
- **`pvr.iptvsimple` is live-TV only.** VOD (movies/series via `get_vod_*` /
  `get_series_*`) cannot go through it; that's a separate STRM-library feature,
  intentionally out of scope here.
- **macOS FS is case-insensitive** — keep token-cased filenames consistent (the builder
  derives them deterministically, so this only bites hand-made files).
- **Staged artifacts carry creds** (every channel URL embeds user/pass). They live ONLY
  in gitignored `iptv-build/` and on the box; `test_secret_leak.py` forbids any tracked
  `*.m3u` / `iptv-build/` path and scans every `IPTV_<N>_*` credential value.
