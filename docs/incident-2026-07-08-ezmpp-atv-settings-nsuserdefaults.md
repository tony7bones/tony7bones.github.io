# Incident 2026-07-08: EZ Maintenance++ silently omitted Apple TV settings from every backup because tvOS stores them in NSUserDefaults

Honest record. A tvOS-specific hardware burn in the series doc
`docs/incident-2026-07-08-ezmpp-repeated-hardware-burns.md`, filed on its own because it
is a distinct root cause tied to the Apple TV runtime.

## Impact

- On tvOS/Apple TV, a backup silently left out Kodi's settings (guisettings, IPTV
  instances, add-on settings) and a restore could not bring them back. Everything
  reverted the next time Kodi was reopened, so a user who backed up one Apple TV and
  restored onto another got a box with none of its settings.
- The omission was silent: the backup "succeeded" and simply did not contain the
  settings.

## Root cause (the real one)

On tvOS, Kodi stores its userdata XML (guisettings, per-instance IPTV settings, add-on
settings) in the system NSUserDefaults plist, NOT as plain files on disk. The add-on's
backup walked the POSIX filesystem, so it never saw those settings, and a restore that
only wrote files could not put them back where Kodi reads them. This is compounded by
tvOS closing Kodi via a swipe-to-close (not a clean exit), so in-memory settings are not
flushed to any file the walk could have found. Per commit `4ba3cc5` ("preserve Apple TV
settings across backup and restore") and the `2026.07.08.2` news entry.

Fix: on tvOS the backup reads the relevant keys straight from the NSUserDefaults plist
and adds any the filesystem walk missed; a restore re-vectors the restored settings back
into that store through `xbmcvfs` so they stick even when Kodi is closed by swiping it
shut. The add-on's own token-bearing settings (the Dropbox login) are deliberately kept
OUT of the backup. No change on Fire TV or desktop. Shipped as `2026.07.08.2` in commit
`4ba3cc5`.

## Contributing factors

1. **tvOS is a genuinely different runtime.** A filesystem-walk backup is correct on
   desktop and Fire TV and silently incomplete on tvOS; desktop/Fire TV tests never
   exercise the NSUserDefaults path.
2. **Swipe-to-close hides the miss.** Because tvOS does not flush on a clean exit, even a
   settings value the user changed may live only in memory or the plist, never in a file,
   so "back up the files" was never going to capture it.

## Resolution

- `2026.07.08.2` / commit `4ba3cc5`: backup reads settings keys from the NSUserDefaults
  plist and merges any the walk missed; restore writes them back into the store; the
  add-on's Dropbox token stays out of the backup. Unit tests added
  (`test_ezmaintenanceplusplus_nsub.py`, `test_ezmaintenanceplusplus_nsud.py`).

Verification status: UNVERIFIED ON HARDWARE. The fix is covered by unit tests, but the
sources do not record a device run confirming that an Apple TV backup captures the
NSUserDefaults settings and a restore makes them stick across a reopen. Apple TV/tvOS has
NO adb: verification is the Xcode / idevice route on a dev-signed build. Also note the
NSUserDefaults path shares device class with the VFS-local-read backup failure
(`docs/incident-2026-07-04-ezmpp-backup-size-mismatch-vfs-local-read.md`); both are
tvOS-only and both need a tvOS device run.

## Action items

- [ ] Back up one Apple TV, restore onto a second (or a wiped) Apple TV, reopen Kodi via
      swipe-close-and-relaunch, and confirm the settings (weather, RSS, skin, remote,
      TV/IPTV, add-on settings) survived. Apple TV/tvOS has NO adb: use the Xcode /
      idevice route (`docs/playbooks/atv-kodi-xcode-cli-troubleshooting.md`).
- [x] Backup reads NSUserDefaults keys; restore writes them back; Dropbox token excluded
      (commit `4ba3cc5`).
- [ ] Add a tvOS device run to the EZM release checklist so this cannot silently regress.

## The rule that would have prevented this

**Where a value is stored is a per-platform question; do not assume the filesystem is the
store.** On tvOS the settings live in NSUserDefaults, so a filesystem-walk backup was
correct-looking and silently incomplete. A backup tool must know each platform's real
store, and "the backup succeeded" says nothing about what it actually contains.

Series context: `docs/incident-2026-07-08-ezmpp-repeated-hardware-burns.md`.
