---
name: iptv-stream-doctor
description: >-
  Diagnose "an IPTV channel is not working on the TV" for the Tony.7.Bones
  Xtream-Codes providers (Streamvision, Network 24). Load when a channel shows a
  Cloudflare ToS / "video on basic service restricted" page, a black screen, or
  channels that flap (work, then stop, then work). Covers the max_connections=1
  trap, Cloudflare per-zone blocks, dead black.ts placeholders, ADB + kodi.log
  ground-truth checks, and Kodi JSON-RPC remote playback. Triggers on IPTV /
  Streamvision / pvr.iptvsimple / "channel not working" / Cloudflare restriction
  / stream debugging in this repo.
---

# IPTV Stream Doctor

Triage guide for IPTV playback failures on the Tony.7.Bones boxes. The full WHY,
the probe scripts, and the case study live in
`docs/playbooks/iptv-stream-troubleshooting.md` - read it before acting. This
file is the fast path and the non-negotiable rules.

## RULE ZERO (read first, every time)

The Streamvision account is `max_connections=1` (VAULT section 22). Every `curl`
to `player_api.php` or a `.ts` URL uses the ONE connection slot. If the TV is
streaming while you probe, both fail and channels appear to "break."

- Never probe a provider while the TV is on it.
- Test channels SEQUENTIALLY, one request at a time, `sleep` between them.
- If channels start flapping, STOP everything for 1 to 2 minutes and let the
  slot reset. Do not channel-surf during the reset.
- Most "all channels broke at once" reports are self-inflicted contention, not a
  real fault. Suspect this first.

## What is actually failing (4 modes)

1. **Connection contention** (`max_connections=1`) - flapping channels. Most common.
2. **Cloudflare per-zone block** - the `cf.*` mirror serves the ToS restriction
   page instead of a 302. Intermittent, per-mirror. Provider-side.
3. **Dead channel** - origin 302s to `.../black.ts`. Stale stream id in the playlist.
4. **Decode issue** - pulls bytes on a laptop but kodi.log shows a codec error. Rare.

## Triage order

1. **Rule out contention.** Is the TV (or another device) live right now? If yes,
   stop, wait, retest. Do not proceed until you own the single slot.
2. **Classify from the workstation, sequentially** (creds: VAULT section 22):
   redirect to `185.245.1.x` = live; to `black.ts` = dead id; to
   `cloudflare-terms-of-service-abuse.com` = flagged mirror; empty = blocked or
   slot in use. Over 50 KB pulled = real video.
3. **Check mirror health** if you see the abuse host - probe the ~10 `cf.*`
   mirrors and switch `IPTV_<N>_PORTAL` to a healthy one.
4. **Verify on the TV** over ADB (`adb connect <DEVICE_IP>:5555`): TCP/80 reach to
   both Cloudflare and origin via `toybox nc` (ICMP ping to origin is filtered -
   that is normal; toybox has no wget/curl). Then read `kodi.log`:
   `CDropControl` = decoding (works); `Creating InputStream` then silence =
   stalled (contention/origin). 403s against sherdog/feeds.kodi.tv are the RSS
   ticker, not IPTV.
5. **Drive playback** via Kodi JSON-RPC (`:8080`, `kodi`/`kodi`) to confirm a fix
   on-screen. `Player.GetActivePlayers` is local/safe; `Player.Open` uses the
   slot; always `Player.Stop` when done.

## Fix placement (do NOT hot-patch the TV)

- **Dead id** -> find the live id (`get_live_streams`), update the favorite/id in
  `.env.<device>`, rebuild with `_tools/build_iptv.py`, redeploy. The `.env` is the
  source of truth; editing the deployed playlist is overwritten on next build.
- **Flagged mirror** -> change `IPTV_<N>_PORTAL` to a healthy mirror, rebuild,
  redeploy.
- **Contention / intermittent block** -> nothing to fix client-side; the channel
  recovers on its own. Optional durable improvement: mirror failover in
  `build_iptv.py` (not yet implemented).

## Gotchas that cost us time

- M3U stream URL is on the line AFTER its `#EXTINF` label. Off-by-one reads make
  a live channel look stale - verify the id under the right label.
- "It opened a stream" is not proof of playback. Require `CDropControl` in the log.
- `VideoView creation failed!!` after a headless JSON-RPC `Player.Open` is benign
  (software-decode fallback), not a failure.
- The Cloudflare restriction page is the provider's free-plan violation, not your
  network. DNS, eero, and the TV are irrelevant to it.
