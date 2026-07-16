# Implementation & Handoff - EZ Maintenance++ Apple TV restore durability

> **CORRECTION (2026-07-14, from Kodi Omega source).** The claim that Kodi "rewrites the on-disk userdata files from the mirror on boot/launch" is **FALSE**. `MigrateUserdataXMLToNSUserDefaults` (PreflightHandler.mm:81-93) returns early forever once `UserdataMigrated` is set, and nothing ever copies a key back to disk. What actually happens: `CTVOSFile::Exists`/`Open` (TVOSFile.cpp:70-122) check the NSUserDefaults **key FIRST** and only fall back to POSIX - so a key **SHADOWS** the disk file. A file-only restore "reverts" because the stale key wins, not because disk was rewritten. Consequence: **dropping the POSIX copy has ZERO fallback** - nothing re-materializes it. See the `kodi-storage-map` skill.
>
> **CORRECTION (2026-07-14, repo migration).** This document's §9 release steps ("bump `addons/script.ezmaintenanceplusplus/addon.xml`... commit + push `main`") describe a release mechanism that no longer exists: EZ Maintenance++'s source moved to its own repo, `moquette/ezmaintenanceplusplus`, and the old in-tree source/tests here were deleted. A release is now: bump `addon.xml` + hand-write `<news>`/`changelog.txt` in that repo, run its own test suite, then `tools/release.sh` (builds, tags, publishes a GitHub Release asset, verifies it) - THEN, back here, bump the hosted metadata mirror (`addons/hosted/script.ezmaintenanceplusplus/addon.xml`) and ship via `python3 _tools/release.py --proxy`. See `.claude/skills/ezm-backup-doctor/SKILL.md` for the current, accurate procedure.

**Audience:** the engineer (human or agent) who implements the fix. This is the single
authoritative build spec. It assumes you have read nothing else; links point to the
supporting docs for depth. **No code is written yet - this document IS the spec, and the
ship is gated on an on-device check (§8).**

- Add-on: `script.ezmaintenanceplusplus` (served from `main`; `YYYY.MM.DD.N` versioning).
- Branch of record for the investigation: `claude/atv-backup-user-settings-bkujms`.
- Supporting docs (all committed):
  - `docs/plans/atv-restore-vfs-rewrite.md` - the chosen design + Adversarial Review #2 verdict (the corrected spec lives at its bottom).
  - `docs/plans/atv-every-boot-settings-reassert.md` - a REJECTED alternative. **Do not re-propose it.**
  - `docs/playbooks/atv-kodi-xcode-cli-troubleshooting.md` - the on-device verification playbook (§8 depends on it).
  - `docs/playbooks/kodi-settings-clobber.md` - the PVR clobber class (IPTV, §5).
  - `docs/playbooks/kodi-vfs-cannot-read-foreign-local-files.md` - the read-direction rule (§4).

---

## 1. Problem (confirmed)

On **Apple TV (tvOS)**, after an EZ Maintenance++ full-backup restore, user settings do not
stick: RSS, weather, TV/IPTV, remote, keyboard, skin all revert and must be rebuilt by hand.
The backup zip DOES contain the settings; the failure is that the restore cannot make them
take effect. Reported on the owner's two Apple TVs ("ATV1 and 2").

## 2. Root cause (source-grounded - not a theory)

Kodi's tvOS home is under `Library/Caches` (Apple forbids `Documents` writes), which the system
may purge, so Kodi vectors `userdata/*.xml` into the app's **NSUserDefaults** - a different,
non-purged domain. It does **NOT** rewrite the on-disk files from that store: reads simply check
the **key first** and fall back to POSIX, so a key **SHADOWS** the disk file
(`CTVOSFile::Exists`/`Open`, `TVOSFile.cpp:70-122`; Kodi Omega `xbmc@f8815ee4`). The earlier
"rewrites disk from the mirror" wording here came from the Kodi Wiki and is FALSE; it is what
made "vector it, then delete the disk copy" look safe, and it destroyed the owner's menu on
2026-07-14.

- `CFileFactory` routes a local `.xml` write to `CTVOSFile` **only on tvOS**.
- `CTVOSFile::Write` → `CTVOSNSUserDefaults::SetKeyDataFromPath(path, buf, size, /*sync=*/true)`
  → `[NSUserDefaults synchronize]` - **persisted to the durable store before the call returns,
  with no dependency on a clean shutdown.**
- At boot `CTVOSFile::Open` reads the NSUserDefaults key if present, else falls back to the
  POSIX file.

**Why the restore fails:** `wiz.py` extracts with plain Python `zipfile` (`zin.extract`), a
plain POSIX write that **bypasses `CTVOSFile`**. So the restored `.xml` never enters
NSUserDefaults; at boot Kodi reads settings from the **stale** NSUserDefaults mirror and never
sees the POSIX files the restore wrote. The restore is **shadowed, not un-flushed.** The
already-shipped `apply_guisettings` (JSON-RPC → live in-memory store, since 2026.06.30.28) is
lost on the unclean swipe-quit. That is why nothing 06.30.28 → 07.08.1 stuck.

## 3. Chosen fix (one paragraph)

At the end of a restore, **re-write each restored `userdata/*.xml` through `xbmcvfs`** so tvOS
vectors it into NSUserDefaults (durable on the first reopen regardless of how the user quits),
keep `apply_guisettings` for the clean-exit/live-session path, and handle `pvr.iptvsimple`
instance settings through the proven **disable→settle→write→enable** window (never under a
live client). Verified sound in Kodi source; ships only with the guards in §4-§6.

---

## 4. Component A - the userdata `.xml` re-write (F1)

### 4.1 New module: `resources/lib/modules/nsud.py` (or add to `_kodisettings.py`)

Keep it separate for testability; `_kodisettings.py` is also fine. Public surface:

```python
def rewrite_userdata_xml(userdata_dir, exclude_rel=(), log=None):
    """Re-write every *.xml under userdata_dir THROUGH xbmcvfs so tvOS vectors it into
    NSUserDefaults (durable). On Fire TV/desktop it is a harmless plain rewrite. Returns
    (written, skipped, failed). Fully guarded - never raises."""
```

Behavior, EXACTLY:

1. `os.walk(userdata_dir)`; for each file ending `.xml` (case-insensitive):
   - Compute its path **relative to** `userdata_dir` (normalized, forward slashes).
   - **Skip** if the rel-path is in `exclude_rel` (see 4.3) or matches an exclude prefix.
   - Translate to a `special://` path: `special://home/userdata/<rel>` (must be under
     `special://home/userdata` so tvOS `WantsFile`'s `/userdata` key match fires).
2. Re-write via the **single-write** helper (4.2). Count results; log one summary line
   (`xbmc.log`, no per-file GUI - the SIGSEGV lesson).

### 4.2 The single-write helper - THE critical correctness rule

```python
def _vfs_rewrite_once(posix_src, special_dst):
    """Read the whole file with PLAIN python, write it in EXACTLY ONE xbmcvfs write.
    Returns True on confirmed write, False otherwise (POSIX source left untouched)."""
    # READ: plain open() - never xbmcvfs. The source is a file THIS add-on just wrote via
    # zipfile; kodi-vfs-cannot-read-foreign-local-files.md forbids xbmcvfs *read* of it.
    with open(posix_src, "rb") as fh:
        data = fh.read()
    # WRITE: exactly one xbmcvfs write. CTVOSFile::Write is REPLACE-per-call, so a chunked
    # loop would leave only the LAST chunk in NSUserDefaults -> a truncated XML fragment ->
    # settings reset to defaults, unrecoverable. NEVER chunk. NEVER reuse ui.py's
    # _stream_copy/_LocalReader here.
    f = xbmcvfs.File(special_dst, "w")
    try:
        ok = f.write(bytearray(data))   # single call; check the boolean return
    finally:
        f.close()
    return bool(ok)
```

- **MUST** be one `write()` call with the full byte payload. Do not chunk. Do not stream.
- **MUST** check the return; on `False` (a `SetKeyData`/synchronize failure, incl. a 500 KB
  overflow) log and count as `failed` - do **not** delete or truncate the POSIX source (it
  remains as the shadow, i.e. no worse than today).
- A tvOS `.xml` write ≤ a few hundred KB is fine as a single write (biggest realistic file is
  a skin `settings.xml`, ~100-200 KB).

### 4.3 Exclusion list (mandatory - prevents self-clobber, a SECRET LEAK, and a boot crash)

`exclude_rel` MUST include at least:

- `addon_data/script.ezmaintenanceplusplus/settings.xml` - carries the SOURCE box's
  `download.path`/`restore.path` **and its `dropbox_refresh_token` (a secret)**; and
  `service.py` reads several EZM settings at IMPORT time with `int(...)` (lines ~27-31), so a
  blank/foreign value would **crash the boot service** (killing the post-restore tune-up).
- `addon_data/pvr.iptvsimple/instance-settings-*.xml` and its `customTVGroups-*.xml` - handled
  by Component B (the disable-window), NOT the blind walk.
- **Evaluate also excluding** (decide during implementation, note the decision):
  `profiles.xml`, `sources.xml`, `mediasources.xml`, `favourites.xml` - machine/box-specific
  or already-safe-as-files; re-vectoring them is at best pointless, at worst cross-box.
- Known non-fix (document, do not try to force): `keymaps/customcontroller.SiriRemote.xml` is
  carved out of Kodi's tvOS `WantsFile()` → the write silently no-ops. The Siri-Remote
  customization stays a manual step. (Ordinary `keyboard.xml`/`remote.xml` vector fine.)

## 5. Component B - IPTV instance settings via the disable-window

The general walk (§4) does **not** touch `pvr.iptvsimple`. Instead, once, at the same restore
point, run a local reimplementation of `script.module.tony7bones`'s proven pattern
(EZM does not depend on that library - reimplement locally; reference
`addons/script.module.tony7bones/lib/tony7bones/setup/iptv.py:733-777`):

```python
def reassert_iptv_instances(log=None):
    """Force pvr.iptvsimple to adopt the restored instance settings. Enumerate the restore's
    ACTUAL instance-settings-*.xml (do NOT assume a fixed count), disable the client so its
    teardown flush lands first, re-write each instance-settings-N.xml + its customTVGroups
    via the single-write helper, then RE-ENABLE in a finally (forces Kodi's multi-instance
    scanner to re-read our files). Guarded; never raises; no-op if pvr.iptvsimple absent."""
```

Sequence (do not reorder):

1. Enumerate `addon_data/pvr.iptvsimple/instance-settings-*.xml` actually present after the
   extract → the real provider set (1, 2, … N). If none, return.
2. `Addons.SetAddonEnabled(pvr.iptvsimple, false)` via JSON-RPC (local helper).
3. Settle: `xbmc.sleep(1000)` - lets the client's teardown flush land BEFORE our write.
4. For each instance file (and its referenced `customTVGroups-*.xml`), `_vfs_rewrite_once`
   (same single-write rule as §4.2 - these are `.xml` under `/userdata`, they vector too).
5. In a `finally`: `Addons.SetAddonEnabled(pvr.iptvsimple, true)` - forces the re-read so the
   live client's in-memory state == our files; the later restart shutdown flush is then benign.

**Dropped ideas (do NOT implement):** pre-establishing bare instances 1+2 (the clean-clone
wipe removes pvr.iptvsimple anyway; the restore overwrites the identity keys; a fixed 1+2 count
leaves a phantom instance on a 1-provider box). **Still manual:** the hidden "All channels"
group (`channelgroups.bIsHidden` in `Database/TV<N>.db`, non-`.xml`, row exists only after a
post-restart sync) - leave the CLAUDE.md manual step.

## 6. Wiring in `wiz.restore()` - ORDER IS LOAD-BEARING

Current tail of `restore()` (~L718-L753): `apply_guisettings(...)` → `UpdateLocalAddons` →
`mark_buffer_prompt_pending()` → `ask_restart(...)`. Insert F1 + B **after**
`UpdateLocalAddons` and **before** `mark_buffer_prompt_pending`, in this order:

```python
# ... existing apply_guisettings(...) ...
# ... existing xbmc.executebuiltin("UpdateLocalAddons") ...
try:
    from resources.lib.modules import nsud
    nsud.rewrite_userdata_xml(control.USERDATA, exclude_rel=nsud.DEFAULT_EXCLUDES, log=...)
    nsud.reassert_iptv_instances(log=...)
except Exception:
    pass          # never break the restore
# ... existing tools.mark_buffer_prompt_pending() ...
# ... existing ui.ask_restart(...) ...
```

Rationale: F1 must run **after** `apply_guisettings`/`UpdateLocalAddons` so no in-session
add-on re-init re-saves its defaults over F1's NSUserDefaults keys (the last-mutation-wins
rule). It must run **before** the restart prompt so it is done while the values are on disk.
`service.py` needs **no change** (this is a one-time restore-time fix, not a boot step - that
is the whole reason it avoids the rejected design's A3/A4 problems).

## 7. Tests (`_tools/`, the only pre-hardware confidence - mandatory)

Add `_tools/test_ezmaintenanceplusplus_nsud.py` (model the fake-`xbmc*` style of
`test_ezmaintenanceplusplus_wiz.py` / `conftest.py`). Cover, each as a distinct test:

1. **Single-write invariant (THE regression guard):** fake `xbmcvfs.File` whose `write()` is
   RECORD-and-REPLACE (mimics `CTVOSFile::Write`). Feed a multi-KB `.xml`; assert `write` was
   called **exactly once** and the stored value is the WHOLE file, never a tail fragment.
   Self-verify: make the helper chunk → the test must go red with a truncated value.
2. **Exclusion:** a tree containing `addon_data/script.ezmaintenanceplusplus/settings.xml`
   (with a fake `dropbox_refresh_token`) → assert it is NOT written/vectored; assert the
   `pvr.iptvsimple/instance-settings-1.xml` is excluded from the general walk.
3. **Non-`.xml` skipped:** `.db`, `.png`, `Thumbnails/` present → untouched.
4. **Write-failure guard:** fake `write()` returns `False` → counted `failed`, POSIX source
   still intact, no exception, restore continues.
5. **IPTV disable-window ordering:** assert the exact sequence
   `SetAddonEnabled(false) → sleep → write(instance files) → SetAddonEnabled(true)`, that
   re-enable runs in `finally` even if a write raises, and that a 1-provider tree touches only
   `instance-settings-1.xml` (dynamic count, no phantom instance 2).
6. **Restore ordering:** F1 + B run AFTER `apply_guisettings` and `UpdateLocalAddons` (patch
   those to record call order), BEFORE `ask_restart`.
   Run the full suite + `ruff check _tools/` before any commit.

## 8. On-device verification gate (SHIP BLOCKER - do not release without it)

Local Kodi/Mac proves nothing about this tvOS-specific behavior (see the VFS playbook). Use
the Xcode CLI (`docs/playbooks/atv-kodi-xcode-cli-troubleshooting.md`) on a real Apple TV:

1. Restore a backup → **swipe-quit** → reopen.
2. Pull the container plist:
   `xcrun devicectl device copy from --device <UDID> --domain-type appDataContainer
--domain-identifier <bundle-id> --source Library/Preferences/<bundle-id>.plist
--destination ./post.plist`
3. Decode the key (the DECISIVE check):
   `/usr/libexec/PlistBuddy -c 'Print :"/userdata/guisettings.xml"' post.plist | xxd -r -p | gunzip | head`
   - **Full, well-formed `<settings>…` = the fix works (B1).**
   - **A tail fragment (starts mid-element, no root) = the chunking bug (§4.2) - FIX BEFORE SHIP.**
   - **Key absent = 500 KB overflow (§4.2 return now catches it loudly) - investigate size.**
4. Repeat the decode for an `/userdata/.../instance-settings-1.xml` key to confirm IPTV vectored.
5. Confirm the restored values are actually live in the UI after the reopen (weather locations,
   RSS, TV groups).
   Only after 3/4/5 pass do you release.

## 9. Release / rollout

Per this add-on's convention (NOT `release.py`'s automation - see the `ezm-backup-doctor`
skill's news-format warning):

1. Bump `addons/script.ezmaintenanceplusplus/addon.xml` `version` to the next `YYYY.MM.DD.N`
   (current `2026.07.08.1`).
2. **Hand-write** the `<news>` block entry (top) and the `changelog.txt` entry in the add-on's
   multi-line voice. Suggested user-facing summary: "Fix: on Apple TV, a restore now actually
   sticks - your weather, RSS, remote/keyboard, skin, and TV settings survive the reopen
   instead of reverting. (Kodi on Apple TV keeps settings in a special store; the restore now
   writes your restored settings into it directly.)"
3. `python3 _tools/generate_repo.py` (rebuilds the zip + `addons.xml`/checksums - do not
   hand-edit those).
4. Full suite + `ruff check _tools/`.
5. Commit + push to `main` (this add-on is served straight from `main`).

## 10. Risks & open questions (carry these to the PR)

- **B2 500 KB budget:** not Kodi-enforced (no cap in source); a very large restored
  `addon_data` could overflow Apple's plist limit → the single-write return now fails LOUDLY
  per file (counted `failed`) instead of corrupting. Measure `ls -l post.plist` on device.
- **Siri Remote keymap** stays manual (WantsFile carve-out).
- **Hidden channel-group DB flag** stays manual (non-`.xml`).
- **Confirmation is device-only** - the whole gate in §8 needs a real Apple TV + (for IPTV) a
  real provider/stream.

## 11. Rollback

If a release regresses a box, roll the add-on back to the prior `YYYY.MM.DD.N` (the version
lives only in `addon.xml`; Kodi upgrades by version number). The repo's tagged restore points
are listed in `CLAUDE.md` ("Restore points").
