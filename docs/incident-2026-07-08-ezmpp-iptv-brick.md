# Incident 2026-07-08: EZ Maintenance++ restore bricked the box via duplicate IPTV instances and unsafe boot-time automation

Honest record. The most recent hardware burn in the series doc
`docs/incident-2026-07-08-ezmpp-repeated-hardware-burns.md`, filed on its own because it
is the one whose fix is NOT yet verified on a device. This incident is OPEN.

## Impact

- A restore left behind duplicate `pvr.iptvsimple` instance files, which caused a
  duplicated IPTV load that could crash the box. Combined with boot-time automation, the
  device could be left unusable ("bricked" from the owner's seat).
- Boot-time automation made it worse: the add-on auto-enabled the IPTV client and ran a
  boot-time home-folder cleanup that deleted files. Both proved unsafe on real hardware.

## Root cause (the real one)

Two compounding faults:

1. **Duplicate instance files.** A restore did not sweep stray
   `addon_data/pvr.iptvsimple/instance-settings-*.xml` files, and a full backup
   re-captured them, so duplicates accumulated and pvr.iptvsimple loaded the same IPTV
   config more than once, which could crash the box. Addressed in `2026.07.08.4` (commit
   `92b212a`), which drops and sweeps duplicate instance files and stops backups from
   re-capturing them. Per the `2026.07.08.4` news entry.
2. **Unsafe boot-time automation.** The add-on shipped logic to auto-enable IPTV after a
   restore (waiting on the playlist share) and a boot-time home-folder cleanup that
   deleted files. On real hardware these behaviors were unsafe: automation that enables a
   PVR client and deletes files at boot is exactly what turns a bad restore into a
   crash/boot-loop. Removed wholesale in `2026.07.08.5`.

Fix of record: `2026.07.08.5` (commit `80b6d89`, "removes all IPTV automation and
boot-time file deletion") removes ALL IPTV automation and ALL boot-time deletion of
userdata/IPTV. Per the `2026.07.08.5` news: backup and restore "no longer capture, touch,
enable, disable, or in any way manage the IPTV (Live TV) add-on," a restore "never turns
IPTV on and never leaves it off," and "nothing runs at startup that deletes files."

## Contributing factors

1. **The add-on tried to manage another add-on's lifecycle.** Enabling/disabling
   pvr.iptvsimple and waiting on a network share put boot success in the hands of a
   backup tool, which is not its job.
2. **Backup and restore both mishandled the same stray files**, so the duplicates were
   self-reinforcing across a backup/restore cycle until the sweep landed.
3. **Boot-time deletion of userdata is unforgiving.** Any deletion that runs before the
   user can intervene converts a recoverable bad state into data loss.

## Current status: OPEN, UNVERIFIED ON HARDWARE

Static code review of the SHIPPED add-on on `main` (done 2026-07-08, recorded in the
series doc) is reassuring on the specific failure modes but is NOT a device test:

- Backup: `nsub.py` `_is_iptv()` excludes `addon_data/pvr.iptvsimple/` (top-level and
  per-profile); it is the only pvr.iptvsimple reference left in the add-on.
- Restore: `nsud.py` has zero enable/disable/`SetAddonEnabled`/restart calls; its header
  states it never manages pvr.iptvsimple.
- The blanket "enable every installed add-on" helpers (`ENABLE_ADDONS` in `wiz.py`,
  `ENABLE_WIZARD` in `default.py`) are defined but never called: dead code, not wired
  into any flow.
- The only boot-time deletion left in `service.py` is the original packages / thumbnail /
  cache autocleaner, gated behind a yes/no dialog or the `auto_clean` / `startup.cache`
  settings; it does not touch userdata or IPTV.

No run on a real device has been done. At the time of writing, no Fire TV was reachable
over adb (`adb devices` was empty), and Apple TV/tvOS is not an adb target at all (it is
verified via the Xcode / idevice route on a dev-signed build). Until a device confirms a
full backup then restore leaves IPTV exactly as left and deletes nothing, this fix is
UNVERIFIED and must not be called "fixed."

## Action items

- [ ] **Verify `2026.07.08.5` / commit `80b6d89` on real hardware before calling it
      fixed.** Full backup, restore onto a wiped box, confirm it boots, IPTV is exactly
      as left, and nothing was deleted; pull `kodi.log` as evidence. Fire TV = adb
      (`_tools/firetv.sh`); Apple TV/tvOS has NO adb, use the Xcode / idevice route
      (`docs/playbooks/atv-kodi-xcode-cli-troubleshooting.md`).
- [x] Duplicate-instance sweep added and backup no longer re-captures strays (commit
      `92b212a`, `2026.07.08.4`).
- [x] All IPTV automation and all boot-time userdata/IPTV deletion removed (commit
      `80b6d89`, `2026.07.08.5`).
- [ ] Keep this incident OPEN until a device run is captured.

## The rule that would have prevented this

**A backup tool must not manage another add-on's lifecycle, and it must never delete
files at boot.** Enabling a PVR client, waiting on a network share, or sweeping the home
folder before the user can intervene are all ways a backup tool bricks a box. And for EZ
Maintenance++, "fixed" means verified on the affected device class, not verified in code:
this incident stays open until a device confirms it.

Series context: `docs/incident-2026-07-08-ezmpp-repeated-hardware-burns.md`.
