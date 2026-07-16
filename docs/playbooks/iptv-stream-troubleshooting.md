# Playbook - IPTV stream troubleshooting (Streamvision / Cloudflare / connection limits)

> How to diagnose "a channel is not working on the TV" for the Xtream-Codes providers
> (Streamvision, Network 24) without guessing and without making it worse. Captures the
> real failure modes we hit on the **Office TV** (Cloudflare ToS restriction page, dead
> `black.ts` placeholders, the `max_connections=1` trap), the exact probes to run, and the
> hard rule that pulled the whole investigation sideways: **never test a live stream while
> the TV is using it.**
>
> Credentials live in `~/.dotfiles/VAULT.md` section 22. Provider creds and mirror lists are
> referenced, not duplicated. Read the companion playbook `iptv-channel-customization.md`
> for how playlists are built in the first place.

---

## The mental model - where a stream can die

A Streamvision channel request travels through three hops, and each hop fails differently:

```
  Kodi (pvr.iptvsimple)
      |  GET http://cf.<mirror>/live/<user>/<pass>/<stream_id>.ts
      v
  Cloudflare edge  (every cf.* mirror is a separate FREE-plan zone)
      |  normally: 302 redirect to the raw origin
      |  when flagged: serves the Cloudflare "video on basic service" ToS page
      v
  Raw origin  185.245.1.x:80  (Apache, real video - NOT behind Cloudflare)
      |  live channel: streams MPEG-TS
      |  retired channel: 302 to video1.c2.wdcdn8s.com/video/black.ts  (black placeholder)
      v
  Back to Kodi -> ffmpeg demux -> hardware/software decode
```

The four things that actually go wrong, in order of how often we saw them:

1. **`max_connections=1` contention** - the account allows exactly ONE concurrent stream.
   A second consumer (another TV, OR your `curl` probes) gets refused. Symptom: channels
   "flap" - one works, switch away, now a different one works, the first is dead. **This is
   almost always self-inflicted during testing.**
2. **Cloudflare per-zone ToS block** - Cloudflare flags a specific `cf.*` mirror zone for
   delivering video on a free plan and replaces the redirect with its restriction page.
   Intermittent, per-zone, comes and goes with no change on your end.
3. **Dead provider channel** - the origin 302s to `.../black.ts`. The channel is retired
   upstream; the stream id in your playlist is stale. Nothing client-side fixes it; the
   provider has usually moved it to a new id.
4. **Genuine playback/decode issue** - rare. The stream pulls bytes fine from a laptop but
   Kodi can't decode it (codec/encode quirk on one channel).

---

## Known endpoints and mirrors

> Credentials are NEVER written here. This repo is public; the real `username` /
> `password` live in `~/.dotfiles/VAULT.md` section 22 and in the gitignored
> `.env.<device>`. Below are hostnames and URL shapes only - substitute creds at
> runtime.

**Streamvision** (Xtream-Codes panel "World 8K", `max_connections=1`):

| Field   | Value                                                                      |
| ------- | -------------------------------------------------------------------------- |
| Mode    | `xtream` (m3u export is blocked panel-wide, HTTP 884 - build from the API) |
| Portal  | `http://cf.<mirror>` (see mirror list below)                               |
| API     | `http://cf.<mirror>/player_api.php?username=<user>&password=<pass>`        |
| Streams | `http://cf.<mirror>/live/<user>/<pass>/<stream_id>.ts`                     |
| EPG     | `http://cf.<mirror>/xmltv.php?username=<user>&password=<pass>`             |
| Origin  | redirects to `185.245.1.x:80` (raw Apache, not behind Cloudflare)          |

Streamvision `cf.*` mirrors (same creds; all share one backend; rotate if one is
flagged). m3u stays blocked on all, the Xtream API works on all.

**Primary rotation (the 8 `.online` mirrors - use these for `IPTV_<N>_PORTAL`):**

```
http://cf.svstartwatch.online
http://cf.svfmed.online
http://cf.svclubtvlite.online
http://cf.svclubmedia.online
http://cf.streamvisiontv44.online
http://cf.streamvisiontv55.online     <- Office TV portal (.env.office)
http://cf.streamvision22.online
http://cf.streamvisiontv2.online
```

**Flagged / avoid (the `.me` domains - Cloudflare-burned, served the ToS page on
2026-06-11):**

```
http://cf.mar-cdn.me
http://cf.mls-cdn.me
```

**Network 24** (the Cloudflare-free provider):

| Field  | Value                                                                                       |
| ------ | ------------------------------------------------------------------------------------------- |
| Mode   | `m3u` (`get.php` works, no Cloudflare in front, cannot show the ToS page)                   |
| Portal | `http://op.web24.live:8080` (direct IP `185.134.22.150`)                                    |
| M3U    | `http://op.web24.live:8080/get.php?username=<user>&password=<pass>&type=m3u_plus&output=ts` |
| EPG    | `http://op.web24.live:8080/xmltv.php?username=<user>&password=<pass>`                       |

> When a Streamvision channel is stuck behind a flagged mirror or a dead id,
> Network 24 is the fallback that is structurally immune to the Cloudflare block.

---

## RULE ZERO - do not probe a stream the TV is on

The account is `max_connections=1` (VAULT section 22, "World 8K" panel). Every `curl` you
run against `player_api.php` or a `.ts` URL **consumes the single connection slot**. If the
TV is streaming at the same time, your probe and the TV fight over one slot and BOTH fail.

This is exactly how we "broke all the channels at once" mid-investigation: back-to-back test
pulls plus JSON-RPC play/stop while the TV was live tripped the limit, and everything went
dark for the cooldown window (about 1 to 2 minutes).

**Before any provider probe:**

- Confirm the TV is idle, OR accept that you're using the one slot and the TV will fail
  while you test.
- Test channels **sequentially**, one request at a time, with a `sleep` between them.
- If things start flapping, **stop everything** for 1 to 2 minutes and let the slot reset.
  Do not channel-surf during the reset - each switch re-grabs the slot.

---

## Step 1 - Reproduce from the workstation (one slot, sequentially)

Pull a few seconds of each channel and classify it. `black.ts` = dead, small/zero bytes =
blocked or refused, over 50 KB = real video.

```bash
U=<user>; P=<pass>; H=cf.streamvisiontv55.online   # creds: VAULT section 22
for id in 696090 696076 696197 696045 696296; do   # R&M, South Park, Family Guy, Simpsons, Archer
  loc=$(curl -s -D - -o /dev/null --max-time 8 "http://$H/live/$U/$P/$id.ts" -r 0-1 \
        | awk '/^[Ll]ocation/{print $2}' | tr -d '\r')
  case "$loc" in
    *black.ts*) echo "$id DEAD (placeholder)";;
    "")         echo "$id NO REDIRECT (blocked or connection limit)";;
    *) b=$(curl -sS -L --max-time 14 "http://$H/live/$U/$P/$id.ts" -r 0-131071 | wc -c)
       [ "$b" -gt 50000 ] && echo "$id WORKS ($((b/1024)) KB)" || echo "$id NO VIDEO";;
  esac
  sleep 2          # RULE ZERO: one slot, never concurrent
done
```

Interpreting the `origin` host from the redirect:

- `185.245.1.x:80` is the real origin, channel is live.
- `video1.c2.wdcdn8s.com/video/black.ts` is a dead/retired channel (stale id).
- `www.cloudflare-terms-of-service-abuse.com` means that mirror zone is Cloudflare-flagged.

## Step 2 - Check mirror health (Cloudflare block is per-zone)

If a channel returns the abuse host, the **mirror** is flagged, not the channel. Streamvision
publishes about 10 `cf.*` mirrors (VAULT section 22) that share one backend. Probe them and
switch the provider's portal to a healthy one:

```bash
for h in cf.streamvisiontv55.online cf.streamvision22.online cf.streamvisiontv44.online \
         cf.streamvisiontv2.online cf.svclubtvlite.online cf.svclubmedia.online \
         cf.svstartwatch.online cf.svfmed.online cf.mar-cdn.me cf.mls-cdn.me; do
  loc=$(curl -s -D - -o /dev/null --max-time 8 "http://$h/live/$U/$P/696090.ts" -r 0-1 \
        | awk '/^[Ll]ocation/{print $2}' | cut -d/ -f3)
  echo "$h -> ${loc:-NO REDIRECT}"
  sleep 1
done
```

> Observed 2026-06-11: `cf.mar-cdn.me` and `cf.mls-cdn.me` were flagged (redirecting to
> `cloudflare-terms-of-service-abuse.com`); the other 8 were healthy. tv55 (the Office TV's
> portal) was healthy. Enforcement is intermittent - re-probe before acting.

## Step 3 - Verify from the TV itself (ground truth)

The workstation and the TV are different network paths. Confirm what the TV actually
experiences over ADB.

```bash
adb connect 192.168.7.162:5555          # Office TV (DEVICE_IP in .env.office)

# Reachability: TV must reach BOTH the cf mirror AND the raw origin on tcp/80.
# ICMP ping to the origin is filtered (100% loss) - that is NORMAL, use nc for TCP.
adb shell 'echo "" | toybox nc -w 5 104.21.31.35 80   && echo cf-ok'      # Cloudflare
adb shell 'echo "" | toybox nc -w 5 185.245.1.188 80  && echo origin-ok'  # origin
# (toybox on these boxes has nc but NO wget/curl; /dev/tcp is unsupported in Android sh)

# What URL did Kodi tune, and did it decode? This is the real answer.
D=/sdcard/Android/data/org.xbmc.kodi/files/.kodi
adb shell "cat $D/temp/kodi.log" | grep -iE \
  'Live Stream URL|Creating Demuxer|Using codec|VideoView|FillBuffer.*code|Failed'
```

A **healthy** playback in `kodi.log` looks like:

```
GetChannelStreamProperties - Live Stream URL: http://cf.streamvisiontv55.online/.../696090.ts
Creating InputStream -> Creating Demuxer
CDVDVideoCodecFFmpeg::Open() Using codec: H.264 / AVC / MPEG-4 AVC
CDVDVideoCodecFFmpeg::CDropControl   (actively decoding frames = it is PLAYING)
```

- `CDropControl` / frame timing lines mean video is decoding. The channel works.
- `VideoView creation failed!!` followed by an FFmpeg fallback is **benign** when you
  launched playback headlessly over JSON-RPC (no focused video surface) - it falls back to
  software decode and still plays.
- `HTTP returned code 403` / `FillBuffer Failed` is a real fetch failure (note: 403s against
  `sherdog.com` / `feeds.kodi.tv` in the log are the **RSS ticker**, not IPTV - ignore them).
- `Creating InputStream` then nothing for minutes means the stream opened but no data, which
  is a connection limit or origin stall, NOT a stale id.

## Step 4 - Drive playback remotely (to confirm a fix on-screen)

Kodi remote control is enabled on the boxes (`KODI_WEB_PORT=8080`, user/pass `kodi`/`kodi`,
`KODI_REMOTE_CONTROL=true`). `Player.GetActivePlayers` is a **local** call (no provider
connection); `Player.Open` **does** open a stream (uses the slot).

```bash
TV=192.168.7.162:8080; A='kodi:kodi'
rpc(){ curl -s -m 10 -u "$A" -H 'Content-Type: application/json' -d "$1" "http://$TV/jsonrpc"; }

rpc '{"jsonrpc":"2.0","method":"PVR.GetChannels","params":{"channelgroupid":"alltv","properties":["channelnumber"]},"id":1}'
rpc '{"jsonrpc":"2.0","method":"Player.Open","params":{"item":{"channelid":366}},"id":2}'   # play
rpc '{"jsonrpc":"2.0","method":"Player.GetActivePlayers","id":3}'                            # local, safe
rpc '{"jsonrpc":"2.0","method":"Player.Stop","params":{"playerid":1},"id":4}'               # free the slot
```

> Always `Player.Stop` when done so the single connection is released for the TV.

---

## Decision tree

```
Channel not working on the TV?
|- Are you (or another device) also hitting the provider right now?
|     -> YES: it's max_connections=1 contention. Stop, wait 1-2 min, retest. (most common)
|- Step 1 says origin = .../black.ts
|     -> dead/retired channel. Find the live id on the panel (get_live_streams),
|        update the favorite/id in .env.<device>, rebuild + redeploy. Do NOT patch the TV.
|- Step 1/2 says origin = cloudflare-terms-of-service-abuse.com
|     -> that mirror zone is flagged. Switch IPTV_<N>_PORTAL to a healthy cf.* mirror,
|        rebuild + redeploy. Provider-side, intermittent - not fixable on the TV.
|- Workstation pulls video but the TV does not, and kodi.log shows a decode error
|     -> genuine playback issue on that one channel (codec/encode). Rare; investigate it.
\- Everything pulls video sequentially and kodi.log shows CDropControl
      -> nothing is broken. The earlier failure was (1) or (2) and has cleared.
```

---

## Office TV case study (2026-06-11)

**Reported:** the Cloudflare "video on basic service is a ToS violation and has been
restricted" page on the Office TV; later "all 24/7 channels work except Simpsons."

**Found:**

- All five `24/7 Favorites` (Rick and Morty `696090`, South Park `696076`, Family Guy
  `696197`, Simpsons `696045`, Archer `696296`) are **live** - each pulled 12 to 19 MB of
  real video when tested **one at a time**.
- The deployed playlist ids were **correct**, not stale. (The `716546` black-placeholder id
  initially suspected for R&M is actually the `UFC 10:` PPV channel - an M3U off-by-one
  misread: the URL is on the line AFTER its `#EXTINF` label.)
- The TV reached both Cloudflare and the origin on tcp/80; `kodi.log` showed R&M opening the
  demuxer and decoding H.264, i.e. it **played**.
- The Cloudflare restriction page was the provider's intermittent per-zone block: confirmed
  live on 2 of 10 mirrors (`mar-cdn`, `mls-cdn`), but NOT on tv55, the TV's portal.
- The "everything broke at once" mid-investigation was **self-inflicted**: concurrent test
  pulls plus play/stop against a `max_connections=1` account starved the TV. It recovered on
  its own once probing stopped.

**Outcome:** no change made - the ids were correct and the streams decode. The fix was to
**stop testing against the live slot**. Simpsons resolved on its own once contention
cleared, consistent with connection starvation rather than a dead channel.

**Lessons (the reusable part):**

1. `max_connections=1` is the dominant failure mode. Treat the provider as a single-user
   resource: never probe while the TV is live, always test sequentially, and when in doubt
   that flapping is real, stop and let it cool down.
2. The Cloudflare ToS page is the **provider's** problem (free-plan video on a flagged
   zone), not the network's. DNS, eero, and the TV are irrelevant to it. Mitigation is mirror
   rotation, not a TV-side change.
3. `kodi.log` is ground truth. "It opened a stream" is not proof - look for `CDropControl`
   (decoding) vs `Creating InputStream` then silence (stalled).
4. Read M3U carefully: the stream URL follows its `#EXTINF` label. An off-by-one read makes
   a live channel look stale and sends you fixing the wrong thing.
5. A durable improvement, if wanted: automatic mirror failover in `_tools/build_iptv.py` so a
   flagged `cf.*` zone rotates to a healthy mirror instead of surfacing the block. Not yet
   implemented.
