# Design: durable Apple TV restore via post-extract `xbmcvfs` re-write

**Status: SURVIVES ADVERSARIAL REVIEW #2 - WITH REQUIRED CHANGES (2026-07-08). No code
written; not yet shippable.** Supersedes the REJECTED every-boot re-assert
(`atv-every-boot-settings-reassert.md`). Three reviewers (QA + two architects) attacked it.
The core `xbmcvfs` re-write (F1) is **sound and verified in Kodi's tvOS source** and could
not be killed - but it needs the fixes in "REVIEW #2 VERDICT" at the bottom, and the IPTV
"simple path" (I1/I2) is **rejected**: the disable-window (I3) is mandatory, not a fallback.
The proposal below is the ORIGINAL; read the verdict at the end for the corrected spec.

## Root cause (established, source-grounded)

On tvOS Kodi's VFS intercepts `.xml` files under `/userdata`: a write **through `xbmcvfs`**
(`CTVOSFile::Write` → `CTVOSNSUserDefaults::SetKeyData(..., synchronize=true)` →
`[NSUserDefaults synchronize]`) lands the bytes in **NSUserDefaults, the only persistent
store on tvOS, flushed to disk before the call returns** - no clean shutdown required.
Non-`.xml` files and dirs live in the **non-persistent Caches** tree.

**The restore's bug:** `wiz.py` extracts with plain Python `zipfile` (`zin.extract`) = plain
POSIX writes that **bypass the VFS**. So restored `.xml` never enters NSUserDefaults; at boot
Kodi reads settings back *through* the VFS (from the stale NSUserDefaults mirror) and never
sees the POSIX files the restore wrote. The restore is **shadowed, not un-flushed.** The
shipped `apply_guisettings` (live in-memory store, via JSON-RPC) is lost on the unclean
swipe-quit. That is why nothing 06.30.28 → 07.08.1 ever stuck.

## The fix - one-time reconcile at the post-extract point

In `wiz.restore()`, right after the extract completes and before `ask_restart` (the same
place the old design stashed), add ONE step:

### F1 - Re-write every restored `.xml` under `userdata/` THROUGH `xbmcvfs`
Walk the just-extracted `special://home/userdata/` tree; for each `*.xml`, read the POSIX
bytes with **plain Python `open()`** (the source is a file *this add-on* just wrote via
`zipfile`; per `kodi-vfs-cannot-read-foreign-local-files.md` a plain-Python read of a
plain-Python file is the *correct* path - that playbook forbids `xbmcvfs` *read* of a
foreign local file, not a plain read) and **write it back through `xbmcvfs.File(special://…,
"w")`**. On tvOS that write vectors into NSUserDefaults with `synchronize=true` → durable on
the FIRST reopen regardless of how the user quits. On Fire TV / desktop the same call is a
harmless plain file rewrite.

Covers, because all are `.xml` under `/userdata` and satisfy `WantsFile()`:
`guisettings.xml`, `RssFeeds.xml`, `keymaps/*.xml`, `addon_data/<id>/settings.xml`, and
`addon_data/pvr.iptvsimple/instance-settings-*.xml` + `customTVGroups-*.xml`. This is the
user's ENTIRE list: rss, weather, remote/keyboard, skin, **and TV/IPTV**.

### F2 - Keep `apply_guisettings` (unchanged)
Still push core settings into the live store via JSON-RPC, so a *clean* shutdown path also
holds and the running session is correct immediately. F1 is the durable half; F2 is the
in-session/clean-exit half. Both, per the established both-ways lesson.

### Corrections from the rejected design, incorporated
- **One-time, not per-boot.** No marker, no stash, no boot counter, no self-terminate - the
  three mechanisms QA proved unreachable/harmful are gone.
- **No A3 regression.** It runs once at restore; it never re-applies on later boots, so it
  cannot revert a setting the user changes afterward.
- **No boot RPC storm (A4).** Nothing added to `service.py`'s startup path.
- **Writes to the DURABLE layer.** The rejected design wrote its recovery data with plain
  Python into `addon_data` (the purgeable Caches tree); F1 writes through `xbmcvfs` into
  NSUserDefaults - the sanctioned persistent store.
- **The VFS-read bug is not triggered.** We *write* via VFS; Kodi later reads its **own**
  NSUserDefaults-backed data through its own VFS on boot - not a foreign-local-file read.

## IPTV - the simple restart-time placement (owner's approach)

The general `.xml` re-write (F1) already writes `instance-settings-*.xml` +
`customTVGroups-*.xml` into NSUserDefaults. The remaining hazard is the **live-PVR clobber**
(`kodi-settings-clobber.md` #3): a running `pvr.iptvsimple` flushes its stale in-memory
instance settings over the file on shutdown. The owner's fix avoids fighting a live client:

### I1 - Pre-establish bare instances (no real content)
The base box ships `pvr.iptvsimple` installed + enabled with instances **1 and 2 already
registered** (empty/placeholder playlists) - so the instance framework and the identity keys
(`kodi_addon_instance_name` / `kodi_addon_instance_enabled`) for instances 1 and 2 exist
before any restore. A restored `instance-settings-1.xml` / `instance-settings-2.xml` then maps
onto instances Kodi already knows about, instead of being written for an instance the client
never enumerates.

### I2 - Place the restored instance settings on RESTART, not under a live client
The clobber happens on the SHUTDOWN of a live client. So the restored
`instance-settings-1/2.xml` + `customTVGroups-*.xml` are put in place **at the start of the
post-restart boot** (written through `xbmcvfs` → NSUserDefaults), *after* the clobbering
shutdown has already happened, *before* `pvr.iptvsimple` initializes for the new session.
Because the instances are pre-established (I1) and the mappings already correct, iptv reads
the restored settings on startup and comes up configured - "copy on restart, and it starts
up with the right mappings." No live-session disable-window needed in the simple path.

### I3 - Fallback if the boot read races the client
If iptv initializes before the placement wins the race, fall back to the proven
disable→settle→write→enable window (`_pause_pvr_for_config`/`_resume_pvr_after_config`,
reimplemented locally since EZM doesn't depend on `script.module.tony7bones`) applied once at
that boot - forcing a re-read. Kept as a safety net, not the primary path.

## What this does NOT cover (honest limits)
- **Non-`.xml` userdata** does not vector into NSUserDefaults: `Database/*.db`
  (incl. the PVR `TV<N>.db` **hidden-channel-group** flag), `Thumbnails/`, view DBs. The
  hidden "All channels" group stays a one-time manual step (already documented in CLAUDE.md).
- **500 KB NSUserDefaults budget.** A large restored `addon_data`/`guisettings` written into
  NSUserDefaults could exceed tvOS's cap (`NSUserDefaultsSize`/`NSUserDefaultsPurge`), where
  writes silently fail. Kodi already stores this class of data there in normal use, but a
  restore's userdata can be larger - MUST be measured on-device.

## Assumptions to attack (B-series)
- **B1** - Writing a restored `.xml` through `xbmcvfs` on tvOS actually vectors it into
  NSUserDefaults and is read back correctly on the next boot (the write side of the VFS,
  proven in *source* but not on *hardware*).
- **B2** - The re-written NSUserDefaults content does not blow the 500 KB budget for a real
  backup's userdata.
- **B3** - The IPTV restart-time placement (I2) actually beats the `pvr.iptvsimple` init on
  the fresh boot, OR the I3 fallback reliably forces a re-read; and pre-established bare
  instances (I1) don't themselves get clobbered/merged wrongly.
- **B4** - Re-writing hundreds of `.xml` files through `xbmcvfs` at restore time is not
  itself slow/among the SIGSEGV-class GUI hazards, and doesn't double-trigger add-on
  `onSettingsChanged` side effects destructively.
- **B5** - No new data-loss path: F1 never corrupts/truncates a restored file (a failed
  `xbmcvfs` write must leave the good POSIX file in place, not a half-written one).

## Verification gate (before any ship)
1. Unit tests: F1 walks the tree and re-writes each `.xml` via a faked `xbmcvfs`; a failed
   write is guarded; non-`.xml` skipped; the IPTV placement ordering (I1→I2, I3 fallback).
2. **Xcode CLI plist diff** (`atv-kodi-xcode-cli-troubleshooting.md`): after a restore, dump
   `Library/Preferences/<bundle>.plist` and confirm the restored `guisettings`/`RssFeeds`/
   add-on/`instance-settings` values are IN it (B1), the plist size is under budget (B2), and
   they survive a swipe-quit reopen with iptv configured (B3).
3. Only then ship, version/news hand-edited per this add-on's `YYYY.MM.DD.N` convention.

---

# ADVERSARIAL REVIEW #2 VERDICT (2026-07-08): SURVIVES WITH REQUIRED CHANGES

Three reviewers attacked it. Consolidated result: the general `.xml` re-write is a sound,
source-verified fix; it ships only with the changes below. The IPTV "simple path" is dead.

## What was VERIFIED (in Kodi's actual tvOS source)
- **B1 holds.** `CFileFactory` routes a tvOS local `.xml` write to `CTVOSFile`;
  `CTVOSFile::Write` → `CTVOSNSUserDefaults::SetKeyDataFromPath(..., synchronize=true)` →
  `[NSUserDefaults synchronize]` - persisted before the call returns, no clean shutdown
  needed. `WantsFile()` matches `guisettings.xml`, `RssFeeds.xml`, `keymaps/*.xml` (except
  the carve-out below), nested `addon_data/<id>/settings.xml`, `instance-settings-*.xml`,
  `customTVGroups-*.xml` - no depth limit. Read-back is safe: the one-time
  `MigrateUserdataXMLToNSUserDefaults` is gated on `UserdataMigrated`, so it never re-runs
  and never fights F1; at boot Kodi reads F1's NSUserDefaults key and the shadow dissolves.
- **B2 (500 KB) is NOT Kodi-enforced** - there is no cap constant/overflow branch in Kodi's
  tvOS source; any ceiling is Apple's platform plist limit. F1 writes the same data class
  Kodi already stores there normally, so it is not materially worse. Measure on device;
  don't block on it.

## REQUIRED CHANGES before shippable (these are mandatory, not optional)
1. **Single write per file - NEVER chunk (critical, prevents NEW data loss).** `CTVOSFile::Write`
   is REPLACE-per-call, not append: each `Write()` overwrites the whole NSUserDefaults key
   with just that chunk. If F1 reuses the repo's chunked copy idiom (`ui.py`
   `_stream_copy`/`_LocalReader`), only the LAST chunk survives → a truncated XML fragment →
   `CSettings` parse fails → settings reset to defaults, with the valid POSIX file shadowed and
   unrecoverable - WORSE than the shadow bug. F1 must read the whole file with plain `open()`
   and write it in exactly ONE `xbmcvfs.File.write(data)` call. Check the boolean return;
   on failure log and leave the POSIX file untouched (do not delete/alter it).
2. **Exclusion list (prevents self-clobber, a SECRET LEAK, and boot-service death).** F1's walk
   must NOT re-write `addon_data/script.ezmaintenanceplusplus/settings.xml` - it carries the
   SOURCE box's `download.path`/`restore.path` AND its `dropbox_refresh_token` (a secret), and
   `service.py` reads several of these at IMPORT time with `int(...)`, so a blank/foreign value
   crashes the boot service (which then never runs the tune-up prompt). Also evaluate excluding
   `profiles.xml`, `sources.xml`/`mediasources.xml`, `favourites.xml`.
3. **IPTV out of the blind walk; disable-window is PRIMARY (I3), not a fallback.** Writing
   `instance-settings-*.xml` via F1 under a LIVE `pvr.iptvsimple` is the documented clobber
   (`kodi-settings-clobber.md` #3): the client flushes its stale in-memory defaults over
   F1's key on the restart shutdown (last-writer-wins). Kodi reads instance-settings ONCE at
   client instantiation and never watches the file, so "place early on boot and hope" has no
   re-read trigger and loses the race against the async PVR manager. The ONLY in-Kodi fix is
   the proven `disable → settle → write → enable` window (`_pause_pvr_for_config`/
   `_resume_pvr_after_config`, reimplemented locally). **Drop I1 (pre-established bare
   instances):** the clean-clone wipe removes `pvr.iptvsimple` anyway, the restore overwrites
   the identity keys, and a fixed 1+2 count leaves a phantom instance on a 1-provider box.
   Instead, enumerate the restore's ACTUAL `instance-settings-N.xml` set and force a re-read
   of exactly those.
4. **Order F1 LAST** - after `apply_guisettings` and `UpdateLocalAddons`, immediately before
   `mark_buffer_prompt_pending`/`ask_restart` - so no in-session add-on re-init re-saves its
   defaults over F1's keys.
5. **Correct the "remote fully covered" claim.** `keymaps/customcontroller.SiriRemote.xml` (the
   Siri Remote customization) is explicitly carved out of `WantsFile()` → it will NOT vector,
   and F1's write of it fails silently. Document it as a manual step alongside the hidden
   channel-group DB flag. (Ordinary `keyboard.xml`/`remote.xml` still vector.)

## Still-open / unchanged limits
- **Non-`.xml` userdata** never vectors: `Database/*.db` (incl. the PVR `TV<N>.db`
  hidden-channel-group flag), `Thumbnails/`, view DBs - the hidden "All channels" group stays
  a documented manual step.
- **On-device gate is mandatory.** The decisive check (per `atv-kodi-xcode-cli-troubleshooting.md`):
  after restore → swipe-quit → reopen, `devicectl copy from` the plist and
  `PlistBuddy -c 'Print :"/userdata/guisettings.xml"' post.plist | xxd -r -p | gunzip` -
  **full well-formed `<settings>` = fix works; a tail fragment = change #1 (chunking) fired;
  key absent = B2 overflow.** Also decode an `instance-settings` key to confirm IPTV vectored.

## Bottom line
Adopt F1 (single-write, excluded, ordered-last) for the non-PVR `.xml` + keep `apply_guisettings`;
handle IPTV via the mandatory disable-window over the restore's actual instances; ship only
after the on-device plist decode confirms B1 and rules out the chunking/overflow failures.

Sources: Kodi tvOS source `FileFactory.cpp`, `TVOSFile.cpp`, `TVOSDirectory.cpp`,
`TVOSNSUserDefaults.mm`, `PreflightHandler.mm`; repo `kodi-settings-clobber.md`,
`kodi-vfs-cannot-read-foreign-local-files.md`, `iptv.py`, `wiz.py`, `service.py`.
