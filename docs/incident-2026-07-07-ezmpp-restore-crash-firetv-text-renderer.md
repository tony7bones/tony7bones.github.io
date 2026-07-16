# Incident 2026-07-07: EZ Maintenance++ restore crashed Fire TV sticks by overrunning Kodi's text renderer

Honest record. One of the hardware burns in the series doc
`docs/incident-2026-07-08-ezmpp-repeated-hardware-burns.md`, filed on its own because it
is a distinct crash with a distinct root cause and fix.

## Impact

- Restoring a large backup segfaulted Kodi partway through on Fire OS 8 Fire TV sticks,
  leaving the box crashed mid-restore. On a device with a lot of files the restore could
  not complete.
- A related UX defect made it worse: the wipe-clean step showed a blank, hung-looking
  screen for up to roughly 90 seconds, so a user could not tell a crash from normal
  progress.

## Root cause (the real one)

The restore progress dialog redrew a changing per-file filename thousands of times as it
extracted. On Fire OS 8 sticks that volume of text redraws overran Kodi's on-screen text
renderer and segfaulted the app. Per commit `89a4778` ("wipe-clean restore option +
crash fix + wipe progress") and the `2026.07.07.3` news entry, which describes the
progress screen redrawing "a changing filename thousands of times."

Fix: stop showing the per-file name. The extract progress now shows "Extracting file X
of Y", count-based and throttled so it updates far less often; the bar still advances and
the restore completes. The wipe step got its own throttled, count-based progress bar for
the same reason so it cannot re-trigger the renderer crash. Shipped as `2026.07.07.3`
(the crash fix and wipe option) and `2026.07.07.4` (the wipe progress bar), both in
commit `89a4778`; the addon.xml at that commit reads `2026.07.07.4`.

## Contributing factors

1. **Progress feedback was tied to per-item strings.** Drawing the filename of every one
   of thousands of files put the UI on a hot path with no throttle, which is exactly the
   load the stick renderer could not take.
2. **A long silent gap looked like a hang.** Before the wipe progress bar, the roughly
   90-second gap between the download finishing and the restore window appearing gave no
   signal, so the genuine crash and normal slowness were indistinguishable to the user.

## Resolution

- `2026.07.07.3` / commit `89a4778`: progress no longer shows the changing filename;
  shows a throttled "Extracting file X of Y". Restore also extracts `userdata/` before
  `addons/` so an interrupted restore preserves the irreplaceable settings and only
  re-downloadable add-ons would be missing. The wipe is SAFE-ordered: the chosen backup
  is staged and validated (size + `is_zipfile`) BEFORE any wipe, so a missing or corrupt
  backup never wipes anything.
- `2026.07.07.4` / commit `89a4778`: the wipe step shows a count-based, throttled
  progress bar instead of the blank gap, itself designed not to re-trigger the renderer
  crash.

Verification status: the crash was observed live on Fire OS 8 sticks (the news and commit
describe the real failure). The fix throttles the redraw path; the sources do not record
a post-fix live restore of a large backup on a stick confirming no crash. Fire TV is an
adb target: verify with `_tools/firetv.sh`. Until that run exists, treat the fix as
strongly evidence-backed but not device-re-confirmed.

## Action items

- [ ] Restore a large (many-file) backup on a Fire OS 8 stick on `2026.07.07.4` or later
      and confirm it completes without a segfault; capture `kodi.log`. Fire TV = adb
      (`_tools/firetv.sh`).
- [x] Progress feedback decoupled from per-file strings and throttled (commit `89a4778`).
- [x] Wipe ordering made safe: validate the staged zip before wiping (commit `89a4778`).

## The rule that would have prevented this

**Do not put a per-item string on the UI hot path for an operation that touches thousands
of items.** A progress display should be count-based and throttled; the low-powered
device is the one that will segfault, and it is the one the owner actually runs.

Series context: `docs/incident-2026-07-08-ezmpp-repeated-hardware-burns.md`.
