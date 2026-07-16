# Incident 2026-07-08: EZ Maintenance++ repeatedly burned real hardware, and no incident report was filed until now

Honest record. The owner was burned FIVE times on real devices by EZ Maintenance++
(`script.ezmaintenanceplusplus`) backup/restore over a roughly two-week span, and until
this file no dedicated incident report existed for it. That documentation failure is
itself part of the incident. This file exists so the pattern is on the record and the
"fixed in code" claim is never again treated as "fixed on the box."

## Impact

- Real Kodi devices (confirmed classes: tvOS/Apple TV, Fire TV sticks) were left broken or
  data-scrambled by backup/restore runs on multiple separate occasions.
- The owner lost trust after repeated "this release fixes it" claims that did not hold on
  hardware. Each claimed fix that failed on a device counts as a full burn.
- No incident report was filed for any of it while it was happening. The only prior EZM
  incident doc (`docs/incident-2026-06-30-ezmpp-deploy.md`) covers a DIFFERENT problem (the
  add-on being invisible after deploy), not the hardware burns.

## Burn log (reconstructed from git history + the addon.xml `<news>` record)

This chronology is reconstructed from the shipped release notes and commits, NOT from a
contemporaneous incident log (there was none). The owner lived these and should correct any
mis-attribution or add burns this list misses.

1. **Backup 0-byte / "size mismatch" over NFS (tvOS/Apple TV).** The `2026.07.01.0`
   progress-bar rewrite replaced a whole-file copy with a chunked read/write loop. On tvOS
   the chunked reader returned empty on a freshly-built local zip while Kodi still reported
   the correct file size, so every backup failed with `size mismatch (0 != total)` and no
   retry could succeed. Chased across `2026.07.04.2`, `.3`, `.4`, `.5`. Real root cause:
   Kodi's VFS cannot read a local file a different, non-VFS writer produced (see
   `docs/playbooks/kodi-vfs-cannot-read-foreign-local-files.md`). Fixed by reading the local
   source with plain Python I/O, not xbmcvfs.
2. **NFS `:2049` port baked into the path.** Kodi's own NFS browse dialog wrote
   `nfs://host:2049/...`; that form breaks Kodi's NFS write path (VfsCopyError / 0-byte
   copy). Fixed in `2026.07.04.1` by stripping the explicit port.
3. **Native Settings dialog rendered completely blank.** The add-on's settings.xml used
   plain-text labels and shipped no `strings.po`; Kodi resolves settings labels as numeric
   string ids, so every label came back empty. This was first MISDIAGNOSED as a Kodi engine
   bug (`2026.07.05.0`), then correctly fixed in `2026.07.07.0` by giving every label a
   real string id backed by a language file.
4. **Wipe-clean restore crashed Fire TV sticks; restore scattered settings into the home
   folder.** The restore progress screen redrew a changing per-file name thousands of times
   and overran the on-screen text renderer, crashing mid-restore on sticks (`2026.07.07.3`);
   separately a "settings" (kodi_settings) restore landed files in Kodi's home folder
   instead of userdata, so it did not actually restore settings (`2026.07.08.4`).
5. **The IPTV brick.** Restore left behind duplicate `pvr.iptvsimple` instance files, which
   caused a duplicated IPTV load that could crash the box, and boot-time automation
   (auto-enable IPTV + a boot-time home-folder cleanup that deleted files) proved unsafe.
   `2026.07.08.4` addressed the duplicate-instance crash; `2026.07.08.5` (commit `80b6d89`)
   removed ALL IPTV automation and ALL boot-time file deletion of userdata/IPTV.

(Apple TV settings not surviving a backup/restore because tvOS stores them in NSUserDefaults
rather than plain files - `2026.07.08.2` - is a related tvOS-specific burn in the same
series.)

## Root causes (the pattern, not just the individual bugs)

1. **"Fixed in code" was repeatedly reported as "fixed," without hardware verification.**
   Every burn above shipped as a confident fix. Several then failed on the device because
   the fix was validated against unit tests and code reading, not a real box. This is the
   same failure the `2026-06-30` incident named: diagnosing by theory instead of by
   reproduction.
2. **tvOS/Apple TV is a genuinely different runtime** (VFS-can't-read-local-file,
   NSUserDefaults settings store, single-write-replaces-key) and desktop/Fire TV tests do
   not exercise those paths. Repeated burns landed specifically there.
3. **No incident discipline.** With no incident report open, each burn was treated as a
   fresh surprise instead of the next occurrence of a known, recurring class.

## Current status of the IPTV brick fix (`2026.07.08.5` / `80b6d89`) - UNVERIFIED ON HARDWARE

Static code review of the SHIPPED add-on on `main` (done 2026-07-08) - reassuring on the
specific failure modes, but NOT a substitute for a device test:

- Backup: `nsub.py` `_is_iptv()` excludes `addon_data/pvr.iptvsimple/` (top-level and
  per-profile). It is the only pvr.iptvsimple reference left in the add-on.
- Restore: `nsud.py` has zero enable/disable/`SetAddonEnabled`/restart calls; its own header
  states it never manages pvr.iptvsimple.
- The blanket "enable every installed add-on" helpers (`ENABLE_ADDONS` in `wiz.py`,
  `ENABLE_WIZARD` in `default.py`) that could re-enable IPTV as a side effect are **defined
  but never called anywhere** - dead code, not wired into any flow.
- The only boot-time deletion remaining in `service.py` is the original packages / thumbnail
  / cache autocleaner, gated behind a yes/no dialog or the `auto_clean` / `startup.cache`
  settings. It does not touch userdata or IPTV.

**What has NOT been done: no run on a real device.** No Fire TV was reachable over adb at
the time of writing (adb devices was empty), and Apple TV/tvOS is not an adb target at all
(it is verified via the Xcode / idevice route on a dev-signed build). Until a device
confirms a full backup + restore cycle leaves IPTV untouched and does not brick, this fix is
UNVERIFIED and must not be called "fixed."

## Action items

- [ ] **Verify `2026.07.08.5` on real hardware before calling it fixed.** Full backup, then
      restore onto a wiped box, then confirm it boots, IPTV is exactly as left, and nothing
      was deleted; pull `kodi.log` as evidence. Verification is per device class and uses the
      RIGHT tool for each: Fire TV = adb (`_tools/firetv.sh`); Apple TV/tvOS has NO adb -
      it is the Xcode / idevice route on a dev-signed build
      (`docs/playbooks/atv-kodi-xcode-cli-troubleshooting.md`). Only then mark the IPTV brick
      resolved.
- [ ] **Add a hardware-verification gate to the EZM release checklist.** No EZM backup/restore
      release ships as "fixed" without a device run captured in a log. Code + unit tests are
      necessary, not sufficient, for this add-on.
- [x] **File this incident report.** Done (this file). The documentation gap is closed.
- [ ] **Backfill:** if the owner's enumeration of the 5 burns differs from the log above,
      correct this file so it matches what actually happened on the devices.

## The rule that would have prevented this

**For EZ Maintenance++, "fixed" means verified on the affected device class, not verified in
code.** Every burn here passed code review or tests and still broke a real box. When the
subsystem is backup/restore across tvOS and Fire TV, a fix is a hypothesis until a device
run confirms it - and the incident stays open until then.
