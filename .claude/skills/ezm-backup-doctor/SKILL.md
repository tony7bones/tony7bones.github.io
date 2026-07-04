---
name: ezm-backup-doctor
description: >-
  Diagnose "EZ Maintenance++ backup/restore to a network share is failing" for
  script.ezmaintenanceplusplus in the Tony.7.Bones repo. Load when a backup or
  restore copy over nfs://smb:// reports "size mismatch", VfsCopyError, a
  0-byte copy, or otherwise fails/hangs, especially on tvOS/Apple TV. Covers
  the NFS port-baking browse-dialog bug, the destination-write-settle race,
  and the local-file-VFS-read bug (Kodi's VFS silently failing to read a file
  a different, non-VFS writer produced). Triggers on EZ Maintenance++ / backup
  failed / restore failed / size mismatch / VfsCopyError / NFS copy debugging
  in this repo.
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

## What is actually failing (3 known modes, in the order to suspect them)

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

- All three known fixes live in
  `addons/script.ezmaintenanceplusplus/resources/lib/modules/{ui.py,wiz.py}`.
  Regenerate (`python3 _tools/generate_repo.py`), bump the version by hand in
  `addon.xml` (this add-on's `YYYY.MM.DD.N` scheme, NOT the repo's own
  single-digit `X.Y.Z` - `release.py`'s automation is NOT used for this
  add-on's news block, see the news-format note in the repo's `CLAUDE.md`),
  write the changelog entry BY HAND in the add-on's own established multi-line
  format, run the full suite + `ruff check _tools/`, then commit and push to
  `main` (this add-on is served straight from `main` like every other
  first-party add-on here - see `docs/playbooks/release-and-deploy.md`).
- Every fix to `ui.py`'s copy/fallback logic must come with a test in
  `_tools/test_ezmaintenanceplusplus_ui.py` that reproduces the EXACT failure
  shape from the real log (not a generic approximation), and should be
  self-verified by reverting just the fix and confirming the new test fails
  with the same error the device showed, then restoring it. This is the
  standard this add-on's test suite has been held to since the 2026.07.04
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
