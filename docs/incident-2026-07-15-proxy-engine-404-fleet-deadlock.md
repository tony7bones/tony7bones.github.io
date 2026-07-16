# Incident: one dead manifest URL deadlocked the whole fleet's update path (2026-07-15)

## Symptom

Both live boxes (office Fire TV, atv2) sat on repository.tony7bones 2.4.5 while
2.4.6, 2.4.7 and 2.4.8 were released green. "Check for updates" did nothing,
a Kodi force-quit/relaunch did nothing, and every release gate (release.py's
atomic push + Pages verify, check_hosted_release_sync, check_consistency)
passed. Discovered while chasing why Estuary 7 1.0.39 "showed up" for hand
installs but the repo addon never advanced.

## Root cause (two layered defects in the on-box engine)

1. **No per-entry fault isolation.** `lib/repository.py::_get_addon_xml` had
   `raise_for_status()` OUTSIDE its try block; only the XML parse was guarded.
   One upstream 404 propagated through the futures map in `_get_addons_xml`
   and aborted the entire addons.xml build, so the engine answered HTTP 500
   for both `/addons.xml` and `/addons.xml.md5` - Kodi logged
   `CRepository: failed read` on every check, for every addon.
2. **The 404 itself.** The deployed 2.4.5 engines bundle their own
   repository.json, which still resolved `script.ezmaintenanceplusplus` to its
   pre-migration path `addons/script.ezmaintenanceplusplus/addon.xml`. The
   EZM++ repo split (commit 6d8d522, Jul 14 17:04) deleted that directory
   minutes after 2.4.6 was cut. From that moment every deployed engine 500'd:
   a self-update deadlock, because the release carrying the corrected manifest
   could only be delivered by the engine the stale manifest had just killed.

Secondary finding while diagnosing: even a healthy engine served its checksum
from a 1-hour `LoadingCache` snapshot with no upstream revalidation, so a
manual "Check for updates" inside the TTL was a structural no-op and
propagation also needed Kodi's own boot/~24h recheck cadence to line up.

## Why every gate missed it

All gates verify the PUBLISH side (Pages artifacts, zips, shas, versions).
The fleet consumes through the on-box engine, and nothing exercised that
consumption path. Three releases in a row were "verified LIVE" while no box
could read the repository at all. Released is not deployed.

## Diagnosis trail (what finally found it)

adb tunnel to the office box's engine port (`adb forward tcp:61234
tcp:61234`) showed `/addons.xml` returning HTTP 500 with 0 bytes; the box's
kodi.log held the full traceback naming the 404; probing all 31 entries of
the v2.4.5 bundled manifest found exactly one dead URL.

## Fix (in release order)

1. **Shim (immediate, commit 9c37471):** restored a copy of the current EZM++
   addon.xml at the deleted path. Every deployed 2.4.5 engine healed on its
   next request; both boxes self-updated to 2.4.8 within seconds of a check.
   KEEP the shim until the whole fleet is confirmed past 2.4.5.
2. **Engine hardening (2.4.9):**
   - per-entry fault isolation: a failing entry is logged and skipped; a dead
     entry now costs one missing listing, never the repository;
   - all-entries-failed raises `UpstreamUnavailable` instead of serving an
     empty `<addons/>` (which would wipe Kodi's knowledge of the repo);
   - `LoadingCache` serves the last good snapshot when a refresh fails after
     expiry (offline boxes keep working);
   - upstream revalidation: the engine polls a 32-byte change token
     (`addons/addons.xml.md5` on raw, conditional GET, at most once per 60s)
     and drops its caches when the token moves, so a Kodi update check sees a
     new release within seconds instead of TTL + recheck-cadence.
3. **Regression gates:** `_tools/test_update_propagation.py` (propagation
   contract: checksum integrity, bounded staleness, prompt revalidation) and
   outage-shaped tests in `_tools/test_proxy.py` (one 404 among N entries
   still yields N-1 listings and a live checksum).

## Lessons

- A distribution pipeline's gates must include one assertion made from the
  CONSUMER's seat. Publish-side green means nothing if no test fetches
  through the same component the fleet fetches through.
- Deployed engines pin their own bundled manifest. Any repo-layout change
  (file moves, dir deletions) must keep every URL referenced by the OLDEST
  deployed engine's bundle alive until that engine version is extinct - or
  the fleet must be confirmed upgraded first.
- Fan-out builds need per-item fault isolation as a default posture. One
  item's failure mode should be that item's absence, not the batch's.
