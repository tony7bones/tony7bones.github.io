# EZ Maintenance++ restore hardening (2026.07.07)

> **CORRECTION (2026-07-14, from Kodi Omega source).** The claim that Kodi "rewrites the on-disk userdata files from the mirror on boot/launch" is **FALSE**. `MigrateUserdataXMLToNSUserDefaults` (PreflightHandler.mm:81-93) returns early forever once `UserdataMigrated` is set, and nothing ever copies a key back to disk. What actually happens: `CTVOSFile::Exists`/`Open` (TVOSFile.cpp:70-122) check the NSUserDefaults **key FIRST** and only fall back to POSIX - so a key **SHADOWS** the disk file. A file-only restore "reverts" because the stale key wins, not because disk was rewritten. Consequence: **dropping the POSIX copy has ZERO fallback** - nothing re-materializes it. See the `kodi-storage-map` skill.

The restore path of `script.ezmaintenanceplusplus` was hardened end to end in the
2026.07.07.x series, driven by a real cross-device clone workflow (one golden
image per device family, restored onto the boxes in that family). Every fix here
was proven on the actual Fire OS 8 stick that exhibited the failure, not inferred
from static reading. Companion triage guide: `.claude/skills/ezm-backup-doctor/SKILL.md`.

## The headline bug: Kodi's text renderer SIGSEGVs on a large restore (Fire OS 8)

**Signature.** Restoring a large backup (a full backup is thousands of files;
the reference image is 6130 files / 133 MB) crashed Kodi partway through the
extract, at a NON-deterministic file count (~5600 one run, ~6300 another), on a
Fire TV Stick 4K Max (AFTKRT, Fire OS 8 / Android 11). Kodi died; the add-on's
`kodi.log` showed NO Python traceback and no `extract to ... ok` summary. The
proof is in Android's crash buffer, not kodi.log:

```
adb -s <ip>:5555 logcat -b crash -d | grep -i libkodi
# native SIGSEGV:
#   CGUIFont::GetTextWidth
#   CGUITextLayout::WrapText
#   CGUITextBox::UpdateInfo
#   CGUIDialogBoxBase::Process   <- the restore progress dialog
#   CApplication::FrameMove -> Run
```

**Root cause.** `wiz.ExtractWithProgress` updated the progress dialog's NOTE with
the current per-file basename (`"[COLOR skyblue][B]%s[/B][/COLOR]" % name`) on
EVERY one of thousands of files. Each update forces Kodi to re-run its native
text-layout/wrap/glyph path (`CGUITextLayout::WrapText` -> `CGUIFont::GetTextWidth`);
hammering it thousands of times per second corrupts and segfaults the renderer on
this device's GPU/OS. It is a KODI native bug, but the add-on's progress behavior
triggered it. The same restore ran fine on the Fire OS 7 smart TVs (different
chip/OS), which is why it looked device-specific.

**Fix (2026.07.07.3).** Stop hammering the renderer: `ExtractWithProgress` no
longer shows the changing per-file name. It updates the note at most every
`_UPDATE_EVERY` (50) files with a STATIC `"Extracting file X of Y"`. The bar still
advances and always reaches 100%. This is the general lesson: **a Kodi progress
dialog updated with rapidly-changing TEXT (a filename, per item, thousands of
times) can crash the native renderer; keep progress text static or count-based
and throttle it.** The same lesson governs the wipe progress bar below.

## Why "movies/TV skin settings don't restore" was the SAME bug

`userdata/` (the ViewModes DB, guisettings, skin `addon_data`) is the LAST ~70
files of the backup zip (6058-6130 of 6130); everything before is `addons/`. So a
crash at ~5600 files dies deep in `addons/` and NEVER reaches `userdata/`. The
box keeps its own pre-restore settings (e.g. the stick's `ViewModes6.db` stayed
dated its provision date, never overwritten by the golden copy). "Views don't
restore" was not a separate defect; it was the crash truncating the restore
before the settings. Fixing the crash fixed both.

**Defense-in-depth (2026.07.07.3): extract `userdata/` before `addons/`.**
`wiz._order_userdata_first()` buckets the infolist so userdata (irreplaceable
settings) is written first and add-ons (re-downloadable) last. An interrupted
restore now costs you at worst some re-downloadable add-ons, never your settings.
Preserves the existing `temp/` `skip_prefix` and the post-wipe uninterruptibility.

## Restore no longer WIPES by default; opt-in clean-clone (2026.07.07.3)

The normal restore (`wiz.restoreFolder` -> `wiz.restore(..., post_wipe=False)`)
was and is an OVERLAY: it extracts over `special://home` and leaves anything not
in the backup in place. That produced a chaotic merged box on a clone (e.g. 72
add-on dirs where the backup had ~69). Only ONE-TAP RESTORE wiped first.

`restoreFolder()` now prompts **"Wipe this device clean before restoring?"** and
passes `wipe=` into `restore()`. The clean-clone path reuses the PROVEN One-Tap
wipe (`onetap._wipe` / `_wipe_excludes`, which preserve EZM++, its deps, and the
staged zip in `special://temp`). SAFETY INVARIANTS (do not weaken):

- The chosen zip is staged AND validated (`size>0` + `zipfile.is_zipfile`) BEFORE
  any wipe. A missing/short/corrupt backup NEVER wipes the box.
- A local source zip is copied into `special://temp` (which the wipe preserves)
  before the wipe, so the restore source survives.
- After the wipe it flips to `post_wipe=True`: the extract is uninterruptible and
  ALWAYS reaches the restart prompt (a cancel/hiccup never strands a wiped box).

## The wipe shows a progress bar, not a dead screen (2026.07.07.4)

The wipe deletes thousands of files silently. On a FUSE-backed Fire OS stick that
is a ~90s blank gap between the download finishing and the restore window, which
reads as "hung/failed". `onetap._wipe` now takes an optional `progress(removed,
total)` callback (pre-counts, then throttled every 100 files, COUNTS ONLY - never
a per-file name, per the crash lesson above), and `restore()` drives it through
the same `ui.Progress` bar the extract uses, headed "Wiping the device clean...".
Not cancelable (a mid-wipe cancel would strand a half-wiped box).

## Honest restart prompt per platform (2026.07.07.5)

On Fire TV / Android, Kodi CANNOT restart itself: `RestartApp` is desktop-only, so
`ui.restart()` can only `Quit`. The old "Restart now?" prompt overpromised (it just
closes). `ui.ask_restart(status="")` is now platform-aware via
`xbmc.getCondVisibility("System.Platform.Android")`: on Android it says "Kodi needs
to close to finish. Close Kodi now, then reopen it" with a "Close now" button; on
desktop it still says "Restart". The one caller passes only the status line and
`ask_restart` builds the platform-correct sentence.

## Post-restore per-device tune-up: device name + video-cache buffer (2026.07.08.1)

A restore clones the SOURCE box's `guisettings.xml`, so this box comes up with the
wrong per-device identity/performance settings: the wrong **device name**
(`services.devicename`) and a **video cache buffer** (`filecache.memorysize`) sized
for the wrong RAM. Both are things the user fixes by hand after cloning a "base"
backup. One combined one-shot prompt closes both gaps and completes the
clone-a-golden-image workflow:

- `wiz.restore()` drops a single one-shot marker via
  `tools.mark_buffer_prompt_pending()` AFTER the extract (so the pre-extract wipe
  and the extract itself cannot remove it) and before `ask_restart`. The marker
  lives in EZM's own `addon_data` (`.ezm_buffer_prompt` - kept that historical name
  even though it now gates the whole combined flow), which `_wipe_excludes()`
  preserves, so it survives a wipe restore and the restart. Reached by normal,
  wipe, and One-Tap restores.
- The boot service (`service.py`, `xbmc.service`, already runs at startup) calls
  `_maybe_prompt_after_restore()`: the marker check is BEFORE `_wait_kodi_ready`, so
  a normal boot (no marker) returns immediately and never delays the maintenance
  loop; only a genuinely pending restore waits for `Window.IsVisible(home)`
  (interruptible, bounded) then calls `tools.prompt_after_restore()`.
- `prompt_after_restore()` runs the **device-name step first, then the buffer
  step**, under one "Restore Complete" banner. ONLY the buffer step clears the
  marker (in its `finally`), and it always runs after the wrapped device-name step,
  so the flow is exactly-once even if the device-name step raises. Fully guarded so
  it can never block boot.
  - **Device name** (`prompt_devicename_after_restore`): text-entry, since there is
    no derivable "right" value (unlike the buffer's RAM-based recommendation). The
    keyboard is prefilled with the current (inherited) name to edit; Keep / cancel /
    empty / whitespace / unchanged all no-op. A rejected name surfaces `ui.error`
    (no silent no-op) and logs to kodi.log.
  - **Buffer** (`prompt_buffer_after_restore`, unchanged): **Set to X MB** (X =
    `tools._recommended_mb()` = `max(50, min(200, int(System.Memory(total) *
    0.10)))`, device-aware off total RAM, clamped 50-200 MB; a 1669 MB stick
    recommends 166 MB), **Let me choose** (Buffer Size screen), or **Keep current**.
    `tools._set_cache_mb()` applies it live via JSON-RPC (no restart needed).

### Both-ways persistence (the split-brain settings lesson)

`_set_devicename()` writes the name TWO ways on purpose, because the two platforms
persist settings oppositely (this is `kodi-settings-clobber.md`'s hazard, both
directions at once):

- `Settings.SetSettingValue` updates Kodi's LIVE store. On **tvOS** that is the
  durable path - the settings flush goes through `CTVOSFile` into the NSUserDefaults
  key, and reads check that key FIRST, so a file-only write is shadowed by the stale
  key and appears to revert (the same reason `_kodisettings.apply_guisettings` exists
  for restore).
- `_kodisettings.write_guisetting()` writes `services.devicename` straight into
  guisettings.xml, which is what survives a **Fire TV / Android UNCLEAN shutdown**
  (there the live store only flushes to the file on a clean exit; a power-pull loses
  an in-memory-only set). On tvOS this is harmless same-value reinforcement.

Doing BOTH covers every platform. An identity setting that silently reverts (and
would not re-prompt, since the marker is already cleared) is worse than the buffer's
exposure, which self-heals on the next retune - so the buffer alone kept the simpler
in-memory-only set, but the device name is hardened. `write_guisetting` also clears
the `default="true"` marker so Kodi treats the value as user-set.

**Verified on hardware (Bedroom Fire TV `192.168.7.84`, 2026-07-08, which was itself
running a "base" backup named `base`):** `services.devicename` IS settable via
`Settings.SetSettingValue` at the box's level (`result:true`, read-back confirmed).
An in-memory-only set (SetSettingValue with NO file write) reverted to the on-disk
value after an `am force-stop` unclean kill + relaunch - proving the hazard. The
both-ways write (SetSettingValue + the value in guisettings.xml) SURVIVED the same
unclean kill + relaunch. So the fix is confirmed, not just reasoned.

## tvOS restore durability: vector userdata into NSUserDefaults, then drop the POSIX shadow (2026.07.08.2, .6)

Apple TV is the one platform where a file-only restore silently reverts. Kodi's tvOS home
lives under `Library/Caches` (Apple forbids `Documents` writes), which the system may purge,
so Kodi vectors `userdata/*.xml` into the app's **NSUserDefaults** - a separate, non-purged
domain. It does **NOT** rewrite the on-disk files from that store: reads check the **key
first** and only fall back to POSIX, so a key **SHADOWS** the disk file
(`CTVOSFile::Exists`/`Open`, `TVOSFile.cpp:70-122`; Kodi Omega `xbmc@f8815ee4`). The Kodi
Wiki's "rewrites from the mirror on launch" wording is FALSE and is what made deleting a
disk copy look safe on 2026-07-14.
The restore extracts with plain `zipfile` (a POSIX write that BYPASSES `CTVOSFile`),
so the restored files never enter NSUserDefaults and are shadowed by the stale mirror
on the next (often unclean, swipe-to-quit) relaunch.

**The rewrite (2026.07.08.2, `resources/lib/modules/nsud.py`).** After the extract,
`restore()` calls `nsud.rewrite_userdata_xml()`, which walks every `*.xml` under
`userdata/` and re-writes each one THROUGH `xbmcvfs`. On tvOS that dispatches to
`CTVOSFile::Write` -> `CTVOSNSUserDefaults::SetKeyDataFromPath(..., synchronize=true)`,
persisting the file to NSUserDefaults BEFORE the call returns, with no dependency on a
clean shutdown. On Fire TV / desktop it is a harmless rewrite of identical bytes.
Two hard rules encoded in that module: (1) **one `xbmcvfs.File.write` call per file,
never chunked** - `CTVOSFile::Write` REPLACES the whole NSUserDefaults key each call, so
a chunked loop would leave only the last chunk = a truncated XML fragment = settings
reset to defaults; the whole file is read with plain `open()` (per
`kodi-vfs-cannot-read-foreign-local-files.md` the read must be plain, never `xbmcvfs`)
and written in one call. (2) **EXCLUDE this add-on's own `settings.xml`** - it carries
the SOURCE box's paths + the Dropbox token, and `service.py` `int()`-parses several at
import, so vectoring a foreign value would crash the boot service.

**The duplicate-entry bug the rewrite introduced, and its fix (2026.07.08.6).** On tvOS
the POSIX file the restore extracted and the NSUserDefaults key the rewrite creates are
TWO separate entities, so File Manager listed **every userdata file twice** under
`special://profile` after a restore. Fix (`nsud.py`, commit `4ccee62`): after a
CONFIRMED vector, and ONLY after a **read-back** (`_vector_confirmed`) proves
NSUserDefaults holds the identical bytes, drop the redundant POSIX copy so only the
coherent CTVOSFile/NSUserDefaults entity remains. The key is then the ONLY copy -
nothing ever re-materializes the disk file from it, so this trades a cosmetic
duplicate listing for a zero-fallback state (see the `kodi-storage-map` skill, §5).
This is ordered write-then-delete - never delete a
file whose content is not already durably in the store - and the read-back guards the
tiny NSUserDefaults budget silently truncating a large key. Hard tvOS gate
(`_is_tvos()` = `xbmc.getCondVisibility("System.Platform.TVOS")`, defaulting False on any
error): a strict no-op on Fire TV / Android / desktop, where the same `special://` path
IS the POSIX file so deleting it would delete the file just written. New param
`drop_posix_on_tvos` (default True) is the escape hatch and drives the pre-fix behaviour
in tests (`_tools/test_ezmaintenanceplusplus_nsud.py`).

**Hardware-verified both platforms (2026-07-08).** ATV1 (Apple TV 4K, tvOS 26.6,
Kodi 21.3): a real restore logged `9 written, 0 failed, 9 posix-dropped (tvOS)`,
NSUserDefaults held every file byte-exact, and File Manager listed each userdata file
ONCE after a restart. Bedroom (AFTHA001, Android 9): the actual fixed
`rewrite_userdata_xml` ran in-Kodi and logged `is_tvos=False` / `posix_survived=True` -
the delete path never fires off tvOS. Full incident record (root cause, evidence, the
ATV1 `devicectl` container listing):
`docs/incident-2026-07-08-ezmpp-tvos-restore-duplicate-userdata.md`. tvOS
capture/verify workflow: `docs/playbooks/atv-kodi-xcode-cli-troubleshooting.md`.

## Fleet facts (measured 2026-07-07, relevant to restore portability)

- The always-on Kodi devices are Fire TV Edition SMART TVs, not sticks: Office =
  `AFTHA004`/hazel (Toshiba 4K UHD Fire TV), Bedroom = `AFTHA001`/hailey. The travel
  sticks are the actual Fire TV Stick 4K Max (`AFTKRT`, 2nd gen). ALL are
  `armeabi-v7a` (32-bit) on Kodi 21.3 (the 64-bit-capable AFTKRT still runs a 32-bit
  Fire OS userspace, so the arm64 Kodi APK will not even install). Because they share
  one ABI + Kodi major, EZM++ FULL backups (including compiled binary add-ons) are
  interchangeable across the whole in-use fleet. The Shield (retired/unused, likely
  arm64) is the only exception. Confirm any unit with
  `adb shell pm dump org.xbmc.kodi | grep primaryCpuAbi`.
- Backup folders on the mini's NFS share are per-device (`bedroom`, `office`,
  `ts-1`, `fs-1`, `fs-2`, ...). The 2026.07.07.2 release REMOVED the box-local path
  re-stamp: a restore now restores the backup verbatim (including the source box's
  `download.path`/`restore.path`/`destination`), and the user sets each box's own
  path afterward (the native Settings dialog works). The mini auto-advertises NFS
  over Bonjour (`_nfs._tcp`) whenever `nfsd` runs with exports, so Zeroconf discovery
  is on and persistent with no launchd job needed.

## Related

- Blank native Settings dialog (2026.07.07.0): was NOT a Kodi engine bug (a prior
  release misdiagnosed it). Cause: `settings.xml` used plain-text labels and shipped
  no language file; Kodi resolves settings labels as numeric string ids, so plain
  text renders blank. Fixed with numeric ids + `resources/language/.../strings.po`;
  the custom in-app settings screen workaround was retired. See the memory note
  `ezm-blank-settings-was-mislabeled-not-engine-bug`.
- `docs/playbooks/kodi-vfs-cannot-read-foreign-local-files.md` and the
  `ezm-backup-doctor` skill cover the earlier NFS/VFS copy-failure classes.
