---
name: ezm-backup-doctor
description: >-
  Diagnose "EZ Maintenance++ backup/restore to a network share is failing" for
  script.ezmaintenanceplusplus in the Tony.7.Bones repo. Load when a backup or
  restore copy over nfs://smb:// reports "size mismatch", VfsCopyError, a
  0-byte copy, or otherwise fails/hangs, especially on tvOS/Apple TV. Covers
  the NFS port-baking browse-dialog bug, the destination-write-settle race,
  the local-file-VFS-read bug (Kodi's VFS silently failing to read a file
  a different, non-VFS writer produced), and the tvOS restore duplicate-userdata
  bug (File Manager listing every userdata file twice after a restore on Apple
  TV). Triggers on EZ Maintenance++ / backup failed / restore failed / size
  mismatch / VfsCopyError / NFS copy debugging / duplicate userdata entries on
  Apple TV in this repo.
---

# EZ Maintenance++ Backup/Restore Doctor

Triage guide for `script.ezmaintenanceplusplus` copy failures on Tony.7.Bones
boxes. The full WHY, the real device logs, and the fix code all live in
`docs/playbooks/kodi-vfs-cannot-read-foreign-local-files.md` - read it before
acting, especially if this is the "size mismatch" failure. This file is the
fast triage path.

## RULE ZERO (read first, every time)

**Get a real device log before touching any code.** Every fix in this add-on's
history that was guessed from static code reading alone either did nothing or
made things worse. The `copied=`/`total=`/`actual=` diagnostic line in
`ui.py`'s `_copy_once` (grep for `chunked copy size mismatch`) is the one fact
that distinguishes the failure classes below - do not skip straight to a code
change without it.

## What is actually failing (4 known modes, in the order to suspect them)

1. **The local-read VFS bug** (the one that took two real-device round-trips
   and two fix attempts to actually nail). Signature: `copied=0 total=<real
size> actual=0` on EVERY attempt, `xbmcvfs.Stat()` on the source has always
   reported the CORRECT size. This is Kodi's VFS silently failing to read a
   local file that a _different, non-VFS writer_ (this add-on's own
   `CreateZip()`, which uses plain `zipfile`/`open()`) produced - confirmed on
   tvOS, not reproducible on macOS's own Kodi. **Fixed** as of
   `script.ezmaintenanceplusplus` 2026.07.04.5: local sources are read with
   plain Python `open()`, never `xbmcvfs`. If you see this signature on a
   version >= 2026.07.04.5, the bug has regressed or moved - full mechanism in
   the playbook above.
2. **The destination-write-settle race** (the FIRST theory tried, shipped in
   2026.07.04.2, and it was WRONG for the failure actually seen live - kept
   here because it's still a real, distinct possible cause). Signature: same
   `size mismatch`, but `copied` equals the real total (the read succeeded in
   full) and only `actual` (the destination stat) is short or zero. A large
   NFS write can complete before the server commits it; `ui.py`'s
   `SIZE_SETTLE_ATTEMPTS` poll-and-retry already handles this - if you see
   `copied==total` with a settling `actual`, this mechanism is already in
   place and working as designed, not a new bug.
3. **The NFS `:2049` port-baking bug** (fixed in 2026.07.04.1, `wiz.py`'s
   `_strip_nfs_port()`). Signature: the backup/restore destination _setting_
   itself (visible in the add-on's own settings screen) contains an explicit
   `:2049` in the `nfs://` URL. Kodi's own browse-dialog UI bakes this in the
   moment the user drills into a folder inside a zeroconf-discovered share
   (there is no manual path-entry option for this setting - it's browse-only).
   An explicit port breaks Kodi's own NFS write path. If you see this in a
   _current_ install, either the strip isn't firing (check `wiz.py`) or the
   user re-browsed and picked a folder again after the port was already
   stripped once (it will always come back baked-in from Kodi's UI - the fix
   must re-strip it every read of the setting, not just once).
4. **The restore-crash / text-renderer SIGSEGV** (fixed 2026.07.07.3). Signature:
   a RESTORE of a large backup crashes Kodi partway through the extract at a
   NON-deterministic file count, Kodi dies, and `kodi.log` has NO Python traceback
   and no `extract to ... ok` summary. The proof is in Android's crash buffer, not
   kodi.log: `adb logcat -b crash -d | grep libkodi` shows a native SIGSEGV in
   `CGUIFont::GetTextWidth` <- `CGUITextLayout::WrapText` <- `CGUITextBox::UpdateInfo`
   <- `CGUIDialogBoxBase::Process`. Cause: the progress dialog was updated with the
   changing per-file NAME on every one of thousands of files, hammering Kodi's native
   text renderer until it corrupts (seen on Fire OS 8 sticks; not on Fire OS 7 TVs).
   Fixed by throttling to a STATIC "Extracting file X of Y". Related symptom to watch:
   because `userdata/` is the LAST ~70 files of the zip, this crash also presents as
   "views/skin settings did not restore" (the extract died before reaching them).
   Full mechanism + all the restore-flow features (opt-in clean wipe, wipe progress
   bar, userdata-first extract, honest restart prompt, post-restore tune-up = the
   combined device-name rename + video-cache buffer retune, one exactly-once
   "Restore Complete" prompt): `docs/playbooks/ezm-restore-hardening.md`.
5. **The tvOS restore duplicate-userdata bug** (fixed 2026.07.08.6). Signature: on
   Apple TV ONLY, after a RESTORE, File Manager lists **every file under
   `special://profile` (userdata) twice** (`sources.xml`, `guisettings.xml`,
   `profiles.xml`, every `addon_data/*/settings.xml`, ...); a fresh clean Kodi install
   is clean, so the dupes appear only post-restore. Cause: the tvOS settings-durability
   rewrite (2026.07.08.2, `nsud.rewrite_userdata_xml`) vectors every userdata `*.xml`
   into NSUserDefaults via `xbmcvfs`, but the zip-extracted POSIX copy stayed on disk,
   so this build's tvOS File Manager enumerates BOTH layers = two entries per file.
   Fixed by dropping the redundant POSIX copy after a read-back confirms NSUserDefaults
   holds the identical bytes, hard-gated to tvOS (`getCondVisibility
System.Platform.TVOS`) so it is a strict no-op on Fire TV / Android / desktop. If you
   see this on a version >= 2026.07.08.6, the drop is not firing (check `nsud.py`'s
   `_is_tvos()` gate and the `_vector_confirmed` read-back). Full mechanism + the
   NSUserDefaults storage model + hardware proof:
   `docs/playbooks/ezm-restore-hardening.md` and
   `docs/incident-2026-07-08-ezmpp-tvos-restore-duplicate-userdata.md`.

## Triage order

1. **Get the log.** Ask for (or pull) the real device's `kodi.log` around the
   failure. Do not proceed on a hunch.
2. **Check the installed version first**
   (`CAddonMgr::FindAddon(s): script.ezmaintenanceplusplus vX installed` in the
   log). If it's below 2026.07.04.5, the fix may simply not be on the device
   yet - that's the first thing to rule out, not a new bug.
3. **Grep for the diagnostic line**: `chunked copy size mismatch (copied=...
total=... actual=...)`. `copied=0` → mode 1 (local-read VFS bug, above).
   `copied==total` with `actual` short → mode 2 (settle race - should already
   recover on its own via the settle-poll and, failing that, the fallback).
4. **Grep for the raw destination setting** (`download.path`/`restore.path` in
   `control.setting`) if the failure looks port-related - an explicit `:2049`
   is mode 3.
5. **If none of the three known signatures match**: this is a genuinely new
   failure mode. Follow RULE ZERO - add/extend the diagnostic logging in
   `_copy_once`/`_fallback_copy` (`ui.py`) BEFORE guessing a fix, ship a
   diagnostic-only release if needed, and wait for a real retry log.

## Fix placement (do NOT hot-patch the device)

**EZ Maintenance++ moved to its own repo, `moquette/ezmaintenanceplusplus`, on
2026-07-14 - it is no longer edited here.** This repo previously held BOTH the
add-on source AND its only test suite (the standalone repo had a stale, partly-
broken second copy that had drifted for weeks), which is exactly the kind of
duplication that let fixes ship without their tests traveling with them. Do the
work in the other repo now:

- The copy/NFS fixes (modes 1-3) live in
  `~/Code/moquette/ezmaintenanceplusplus/script.ezmaintenanceplusplus/resources/lib/modules/{ui.py,wiz.py}`;
  the restore-flow fixes live in `wiz.py` (the crash/extract-order/wipe
  features, mode 4) and `nsud.py` (the tvOS NSUserDefaults rewrite + the
  duplicate-userdata drop, mode 5).
- Bump the version by hand in `addon.xml` (this add-on's `YYYY.MM.DD.N` scheme),
  write the changelog entry BY HAND in the add-on's own established multi-line
  format, run the full suite (`/opt/homebrew/bin/python3 -m pytest tests/ -q` -
  system `python3` here is 3.9, too old) + `ruff check tests/ tools/`, commit,
  then `./tools/release.sh` to build the deterministic zip, tag it, publish it
  as a GitHub Release asset on `moquette/ezmaintenanceplusplus`, and verify the
  asset is anonymously downloadable and sha256-matches the build.
- Only THEN, back in this repo: bump the version in
  `addons/hosted/script.ezmaintenanceplusplus/addon.xml` to match (hand-synced
  metadata mirror, same pattern as `addons/hosted/skin.estuary7/`) and ship it
  via `python3 _tools/release.py --proxy` - `repository.json` (which points at
  the release asset) is bundled inside `repository.tony7bones`'s own zip, so a
  proxy release is what actually gets the new version onto a box.
- A change to `nsud.py`/`boxsetup.py` specifically also needs a fresh
  hardware-verification artifact before it ships - see
  `moquette/ezmaintenanceplusplus`'s `tests/test_storage_change_requires_device_verification.py`
  and `tools/verify_device.py`.
- Every fix to `ui.py`'s copy/fallback logic must come with a test in
  `tests/test_ezmaintenanceplusplus_ui.py` (in the new repo) that reproduces
  the EXACT failure shape from the real log (not a generic approximation), and
  should be self-verified by reverting just the fix and confirming the new
  test fails with the same error the device showed, then restoring it. This is
  the standard this add-on's test suite has been held to since the 2026.07.04
  saga - keep holding it there.

## Gotchas that cost real time on this saga

- `xbmcvfs.Stat()` can be completely correct while `xbmcvfs.File(...).readBytes()`
  (or even the native `xbmcvfs.copy()`) is completely broken for the SAME
  path. A correct stat is NOT proof the read side works - this is the trap
  that made the first fix attempt (falling back to `xbmcvfs.copy()`) fail
  identically to the bug it was meant to fix.
- A local Mac Kodi test proved nothing about a tvOS-specific bug like this one
  - two clean local tests (63MB and ~141MB) gave false confidence that the
    settle-race theory was right, when the real failure only reproduces on the
    actual sandboxed device. Local testing is useful for ruling OUT a hypothesis
    cheaply, never for confirming a device-specific one.
- This add-on's changelog format is NOT this repo's own one-liner convention -
  running `release.py`'s `prepend_addon_news` against it once corrupted ~190
  lines of real history down to a few mangled lines. Always hand-edit this
  add-on's `<news>` block, never run the automated news-prepend against it.
