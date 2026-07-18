# Incident 2026-07-08: EZ Maintenance++ restore leaves duplicate userdata entries in File Manager on Apple TV


> **CORRECTION (2026-07-14, from Kodi Omega source).** The claim that Kodi "rewrites the on-disk userdata files from the mirror on boot/launch" is **FALSE**. `MigrateUserdataXMLToNSUserDefaults` (PreflightHandler.mm:81-93) returns early forever once `UserdataMigrated` is set, and nothing ever copies a key back to disk. What actually happens: `CTVOSFile::Exists`/`Open` (TVOSFile.cpp:70-122) check the NSUserDefaults **key FIRST** and only fall back to POSIX - so a key **SHADOWS** the disk file. A file-only restore "reverts" because the stale key wins, not because disk was rewritten. Consequence: **dropping the POSIX copy has ZERO fallback** - nothing re-materializes it. See the `kodi-storage-map` skill.

Honest record. On Apple TV (tvOS), after an EZ Maintenance++ restore, Kodi's File Manager
shows **every file in `special://profile` (userdata) twice**. Confirmed by the owner
empirically (a fresh clean Kodi install was clean; the duplicates appeared only after an
EZM restore) and corroborated in code. This is a side effect of the tvOS settings-durability
rewrite added in 2026.07.08.2, and it is **not yet fixed**.

## Impact

- Every userdata file (`sources.xml`, `guisettings.xml`, `profiles.xml`, `RssFeeds.xml`,
  `peripheral_data/*`, every `addon_data/*/settings.xml`) appears twice when browsing
  `special://profile` in File Manager on Apple TV.
- Confusing and alarming to the owner (looks like corruption), especially on top of the
  earlier EZM restore burns. Functionally the settings still work, but the box looks broken.
- Reproduced on ATV1 (`192.168.7.220`, tvOS 26.6, Kodi 21.3 koditvbox build
  `ca.koditvbox.kodi.tvos.21`).

## Root cause

`resources/lib/modules/wiz.py` `restore()` (line ~786) calls:

```python
from resources.lib.modules import nsud
nsud.rewrite_userdata_xml(control.USERDATA, log=_rlog)
```

`nsud.rewrite_userdata_xml` (`resources/lib/modules/nsud.py`) **walks every `*.xml` under
`userdata/` and rewrites each one through `xbmcvfs`**, which on tvOS dispatches to
`CTVOSFile::Write` and vectors the file into **NSUserDefaults** (Kodi's persistent store on
tvOS, per the Kodi Wiki: tvOS gives an app ~500 KB of normal storage, so Kodi mirrors
`userdata/*.xml` into NSUserDefaults and rewrites the disk files from it on boot).

The restore first extracts the backup to **disk** with plain `zipfile` (POSIX, bypassing
`CTVOSFile`), then vectors every one of those `*.xml` into **NSUserDefaults**. The file now
exists in **both** layers, and this build's tvOS File Manager enumerates both the POSIX disk
entry and the NSUserDefaults key as separate items -> each file is listed twice.

The rewrite was introduced (2026.07.08.2) for a real reason: a file-only restore reverts on
the next unclean relaunch on tvOS because the restored files never entered NSUserDefaults.
The defect is that the rewrite **over-applies to every `*.xml`** rather than only the files
that genuinely need durability, dual-layering the entire folder.

## Evidence (from the live ATV1, 2026-07-08)

- **Owner A/B:** fresh clean Kodi install was clean; duplicates appeared only after an EZM
  restore. (Owner initially said "backup", then corrected to "after restore" - the restore
  path is the one that calls the rewrite.)
- **Disk vs NSUserDefaults:** `devicectl` container listing of
  `Library/Caches/Kodi/userdata` shows single copies on disk (9 `*.xml`); the NSUserDefaults
  plist (`Library/Preferences/ca.koditvbox.kodi.tvos.21.plist`) holds `/userdata/*` keys for
  the same files plus add-on settings (12 keys) - the mirror the rewrite populates.
- **Boot log** (`Library/Caches/kodi.log`): `special://profile/ is mapped to
  special://masterprofile/`; `found key /userdata/guisettings.xml` /
  `NSUSerDefaults: compressed /userdata/profiles.xml ...` confirm the NSUserDefaults mirror
  is live.

## Resolution

**RESOLVED - fixed, hardware-verified on both platforms, released as 2026.07.08.6.**

Fix (`nsud.py`, commit 4ccee62): after a restore vectors a userdata `*.xml` into
NSUserDefaults, and ONLY after a READ-BACK confirms the store holds the identical bytes,
drop the redundant POSIX copy so only one coherent entity remains. Hard tvOS gate
(`_is_tvos()` = `getCondVisibility("System.Platform.TVOS")`): a strict no-op on Fire TV /
Android / desktop, where the same `special://` path IS the POSIX file. The read-back before
delete guards the tvOS storage budget silently truncating a key.

Hardware verification (not code-only):

- **ATV1 (Apple TV 4K, tvOS 26.6, Kodi 21.3):** a real restore logged
  `9 written, 0 failed, 9 posix-dropped (tvOS)`; NSUserDefaults held every file byte-exact
  (`guisettings.xml` 36,617 B); after a restart File Manager listed each userdata file ONCE.
- **Bedroom (Amazon AFTHA001, Android 9, Kodi 21.3):** the actual fixed
  `rewrite_userdata_xml` run in-Kodi logged `T7BTEST SAFE platform_tvos=False is_tvos=False
  rewrite=(1,0,0) posix_survived=True` - the delete path never fires on Android.

Released 2026.07.08.6 (commit 1a054cf), live on `main`/raw and fetchable by the boxes.

## Action items

- [x] File this incident.
- [x] Implement the fix (read-back-gated POSIX drop, tvOS-only). Commit 4ccee62.
- [x] Verify on ATV1: restore -> single entries + settings survive reopen. Done (log + plist).
- [x] Clean the existing duplicates on ATV1: a restore with the fixed code collapses them
      (proven - File Manager lists once after restart).
- [x] Verify the tvOS gate is a no-op on Fire TV. Done on Bedroom (`T7BTEST SAFE`).
- [x] Release + verify the fix reaches the box. Released 2026.07.08.6; raw addon.xml + zip live.
- [ ] Follow-up: atv-1 currently runs the hand-assembled TEST build (no proxy installed), so it
      will not auto-update. Reinstall EZM cleanly there (or install the proxy) so it tracks
      releases going forward.

## The rule that would have prevented this

A tvOS durability rewrite that vectors files into NSUserDefaults must be **scoped to exactly
the files that need it**, and any restore change on tvOS must be **verified on a real Apple
TV** (File Manager listing + settings-survive-reopen), not only in unit tests. This is the
same "verified in code is not verified on hardware" rule as the other EZM burns.
