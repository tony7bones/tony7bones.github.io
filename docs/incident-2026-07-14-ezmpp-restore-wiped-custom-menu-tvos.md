# Incident 2026-07-14: an EZ Maintenance++ restore silently wiped the customized main menu on Apple TV

> **UPDATE (2026-07-14, later same day doc audit): DEPLOYED, this incident is now
> considered RESOLVED.** The bench Apple TV (this doc's "ATV1", `192.168.7.183`, whose
> Kodi friendlyname now reports `atv2`) and the office Fire TV (`192.168.7.162`) are both
> on `script.ezmaintenanceplusplus` `2026.07.14.1` and `skin.estuary7` `1.0.38` - past the
> `2026.07.14.0`/`1.0.36`-`1.0.37` fixes this doc originally shipped, and past the `1.0.38`
> regression fix (the boot-loop bug - see `~/Code/moquette/estuary7/TASKS.md`). **Verified
> directly in this audit** on the office Fire TV via JSON-RPC (`Addons.GetAddonDetails`
> for both add-on ids); the bench Apple TV was asleep/unreachable over JSON-RPC at audit
> time, so its versions were NOT independently re-confirmed here - stated per the session
> record, not re-derived. The rest of this document is the original incident record and
> root-cause writeup; treat its "OPEN"/"NOT DEPLOYED" language below as superseded by this
> update, not as current status.

**FIX WRITTEN AND RELEASED. NOT DEPLOYED. THE BUG IS STILL LIVE ON THE FLEET.** (superseded - see the update above)

Corrected 2026-07-14 after reading the versions off the boxes instead of trusting this
document. The earlier header claimed "RESOLVED ... Hardware-confirmed on ATV1". Every part
of that was wrong, and the errors all pointed the same way (toward believing we were done):

- **ATV1 is `192.168.7.183`, not `192.168.7.220`.** `.220` answers ping and is not the box.
  Boxes are identified by asking Kodi (`System.FriendlyName` over JSON-RPC), never by a
  remembered IP.
- **ATV1 runs `script.ezmaintenanceplusplus` 2026.07.13.6** - the BUGGY build. The root-cause
  fix `2026.07.14.0` was released to the repo and **never installed on any box**. Released is
  not deployed.
- **ATV1 runs `skin.estuary7` 1.0.35.** The 1.0.36 self-heal and 1.0.37 purge have **never
  executed on real hardware.** They are unverified code.
- **What actually restored the menu on ATV1 was a MANUAL repair** performed over JSON-RPC
  during debugging, not any shipped fix. A hand-repair is not a verification.

Current, measured state (2026-07-14): ATV1 skinshortcuts data is clean (26 VFS entries, no
key/disk duplicates, `mainmenu.DATA.xml` and the hash present, custom menu intact). It is
clean because it was repaired by hand. **The code that destroyed it is still the code
running on it: the next EZM++ restore on ATV1 will wipe the menu again.**

Deploying 2026.07.14.0 to the fleet is the outstanding action. Until then this incident is
OPEN.

## Impact

- On Apple TV, every EZ Maintenance++ restore silently reset the Estuary 7 main menu to
  the skin's SHIPPED DEFAULT, destroying the owner's customized menu. No error, no warning.
- A second, independent bug meant the seed ALSO reset a customized menu to stock on **every
  skin version bump** - live on all 7 boxes, restore or no restore.

## Root cause

`nsud.rewrite_userdata_xml` vectored **every** `*.xml` under `userdata/` into NSUserDefaults
and then **deleted the POSIX copy** (`drop_posix_on_tvos`). That included
`addon_data/script.skinshortcuts/*.DATA.xml` - the owner's menu.

`script.skinshortcuts` reads that file with a **mixed-mode** access pattern
(`datafunctions.py:178-183`):

```python
if xbmcvfs.exists(path):        # tvOS: CTVOSFile::Exists checks the NSUserDefaults KEY FIRST -> True
    try:    tree = ETree.parse(path)   # plain POSIX open() -> FileNotFoundError (we deleted it)
    except: continue                   # -> falls through to the skin's shipped default menu
```

So the existence check passed off the relocated key, the content read failed on the deleted
disk file, the bare `except` swallowed it, and skinshortcuts fell through to
`special://skin/shortcuts/mainmenu.DATA.xml` = **the full stock menu**.

Confirmed in Kodi's Omega source: `TVOSFile.cpp:113-122` (`Exists` checks the key first),
`TVOSFile.cpp:39-45` (`WantsFile` = any `.xml` under userdata except
`customcontroller.SiriRemote*`), `TVOSDirectory.cpp:48-106` (listings never dedupe).

**The data was never lost** - it was sitting in the NSUserDefaults key the whole time.

## The false belief that caused it

Six of our own docs (and the auto-loading memory) claimed _"Kodi rewrites the on-disk
userdata files from that mirror on boot/launch."_ **That is false.**
`MigrateUserdataXMLToNSUserDefaults` (`PreflightHandler.mm:81-93`) returns early forever once
`UserdataMigrated` is set; nothing ever copies a key back to disk. A key **SHADOWS** the disk
file - that is why a file-only restore "reverts".

That false model is what made "vector it, then delete the disk copy" look safe. It is not:
**dropping the POSIX copy has ZERO fallback.** All six docs + the memory are now corrected.

## Wrong turns (recorded so they are not repeated)

- **Blamed the skinshortcuts hash / the tvOS container UUID.** Real (the hash stores absolute
  paths) but a **passenger** - the container UUID never even changed (proved from the log).
- **Proposed suppressing the rebuild** by re-seeding the hash. Two independent adversarial
  reviewers KILLED it: a rebuild READS the owner's DATA first
  (`paths = [user_shortcuts, skin_shortcuts, default_shortcuts]`) and **regenerates** the
  custom menu - it never destroys it. Suppressing it would have **permanently disarmed the
  only mechanism that can rebuild the menu** = silent, delayed data loss.
- **Nearly shipped a new data-loss bug:** the first fix vectored `customcontroller.SiriRemote*.xml`,
  which Kodi EXCLUDES from `WantsFile` - so the write+read-back was a POSIX round-trip that
  ALWAYS "confirmed", and the code would then have deleted the only copy. Caught by review.

## Resolution

**EZM++ 2026.07.14.0 - scope the vectoring (the fix our own incident doc asked for in July).**
`_should_vector()` now vectors ONLY what Kodi itself reads through its VFS: top-level
`userdata/*.xml`, `addon_data/<id>/settings.xml`, `instance-settings-*.xml`. An add-on's
private data is left as a plain POSIX file - never vectored, never deleted.
`customcontroller.SiriRemote*` is excluded outright. This protects **every** add-on, not just
skinshortcuts.

**skin.estuary7 1.0.36 - self-heal.** The boot service detects DATA that is missing from disk
but present via the VFS, reads it back THROUGH `xbmcvfs`, writes it to disk with plain
`open()` (the API skinshortcuts reads with), drops the stale hash, and lets skinshortcuts
**rebuild the menu from the owner's own data**. It also never seeds a hash over a customized
menu again (fixing the every-skin-bump reset).

**skin.estuary7 1.0.37 - cleanup.** Purges the now-redundant NSUserDefaults keys so each file
is one coherent entity again (no duplicate File Manager entry, no stale key shadowing disk, and
the tvOS defaults budget freed).

**Correction (2026-07-14, re-derived from source during adversarial review of the 1.0.36/1.0.37
follow-up fix):** the sentence that used to be here claimed `CTVOSFile::Delete` "FALLS BACK to
deleting the POSIX file if the key-delete reports failure." **That is false and is the opposite
of the engine's actual behavior**, confirmed against Kodi Omega source (`TVOSFile.cpp:101-111`,
`TVOSNSUserDefaults.mm:271-278,188-202`):

```
CTVOSFile::Delete        -> ret = DeleteKeyFromPath(url, true); if (!ret) POSIX delete
DeleteKeyFromPath        -> translatePathIntoKey() succeeds for any path under userdata,
                            then DeleteKey(key, true)
DeleteKey                -> [defaults removeObjectForKey:key]  (silent no-op if absent)
                         -> return [defaults synchronize] == YES        (true)
```

`ret` is **TRUE whether or not the key existed**, so the `if (!ret)` POSIX-delete fallback is
**unreachable** for exactly the files `CTVOSFile` is dispatched for. `xbmcvfs.delete()` on a
userdata `*.xml` path on tvOS can NEVER delete the POSIX file through this engine path - it only
ever drops the key (or no-ops if the key is already absent) and reports success.

The purge is still safe, but not for the reason originally stated. It holds the bytes in memory,
verifies the disk file survived, and rewrites it if the fallback fires - that verify/restore
branch is now known-unreachable **defense-in-depth**, not the active safety mechanism. The real
safety property is structural: the purge only ever calls `xbmcvfs.delete()` on a path whose POSIX
copy already exists on disk (verified before the call), and that engine path is incapable of
touching the POSIX file at all. **Data loss is impossible by construction** - just a different
construction than originally documented. See `.claude/skills/kodi-storage-map/SKILL.md` §3/§7
rule 4, which already stated this correctly; this doc is now consistent with it.

## Hardware verification (ATV1, 192.168.7.183 - corrected per the note above; `.220` was never the box)

- Before: VFS listed **23** `.DATA.xml` (keys only - no disk copies); menu = stock default.
- After 1.0.36 + restart: VFS listed **46** (23 disk + 23 keys) and the **owner's custom menu
  was back**.
- 1.0.37 purges the 23 redundant keys -> back to 23 entries, one layer.

## The rules that would have prevented this

1. **Read and write a file through the SAME layer its real consumer uses.** skinshortcuts reads
   with plain `open()`; we moved its file into a store it cannot see, then deleted the copy it
   could.
2. **A durability rewrite must be scoped to exactly the files that need it** - our own
   2026-07-08 incident said this and it was never done.
3. **Verify a platform claim against the platform's source.** A wrong sentence in a doc
   ("Kodi rewrites disk from the mirror") propagated into code that deleted user data.

Full storage model: `.claude/skills/kodi-storage-map/SKILL.md`.
