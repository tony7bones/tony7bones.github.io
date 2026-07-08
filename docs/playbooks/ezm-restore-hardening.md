# EZ Maintenance++ restore hardening (2026.07.07)

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

## Post-restore per-device video-cache-buffer retune (2026.07.07.6)

A restore clones the SOURCE box's `guisettings.xml`, so `filecache.memorysize`
(the video cache buffer) is now sized for the wrong device. The buffer is the one
performance-critical setting that MUST differ per device (by its RAM). The retune
prompt closes that gap and completes the clone-a-golden-image workflow:

- `wiz.restore()` drops a one-shot marker via `tools.mark_buffer_prompt_pending()`
  AFTER the extract (so the pre-extract wipe and the extract itself cannot remove
  it) and before `ask_restart`. The marker lives in EZM's own `addon_data`
  (`.ezm_buffer_prompt`), which `_wipe_excludes()` preserves, so it survives a
  wipe restore and the restart. Reached by normal, wipe, and One-Tap restores.
- The boot service (`service.py`, `xbmc.service`, already runs at startup) calls
  `_maybe_prompt_buffer_after_restore()`: returns immediately on a normal boot (no
  marker, no wait); when a marker is pending it waits for `Window.IsVisible(home)`
  (interruptible, bounded) then shows a "Restore Complete" dialog offering **Set
  to X MB** (X = `tools._recommended_mb()`), **Let me choose** (opens the Buffer
  Size screen), or **Keep current**. Deletes the marker in a `finally` so it asks
  exactly once, and is fully guarded so it can never block boot.
- The recommendation already existed: `tools._recommended_mb()` = `max(50,
min(200, int(System.Memory(total) * 0.10)))` - device-aware (this box's total
  RAM, a stable constant, deliberately not the drifting FreeMemory), clamped
  50-200 MB. `tools._set_cache_mb()` applies it live via JSON-RPC (no restart
  needed). Verified on-device: a 1669 MB stick recommends 166 MB.

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
