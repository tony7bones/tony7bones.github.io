# Incident 2026-07-04: EZ Maintenance++ backups failed with "size mismatch (0 != total)" on Apple TV, chased across four releases

Honest record. One of the five hardware burns in the series doc
`docs/incident-2026-07-08-ezmpp-repeated-hardware-burns.md`; this file breaks that
burn out on its own because it cost four releases and multiple wrong theories before
the real root cause was found.

## Impact

- On tvOS/Apple TV, every backup (and any restore that copied the staged zip) failed
  with `size mismatch (0 != total)` and could not be made to succeed by retrying. The
  owner could not take a working backup at all on that device class.
- Trust damage from a chain of confident "reliability fix" releases (`2026.07.04.2`,
  `.3`, `.4`) that each shipped as a fix and each still failed on the real box.

## Root cause (the real one)

The `2026.07.01.0` progress-bar rewrite (commit `330ce5f`, "unify all backup/restore
feedback on ui.py") replaced a plain whole-file copy with a chunked read/write loop so
it could draw a gauge and support cancel. On tvOS that chunked reader returned an empty
read on a freshly built LOCAL zip even though Kodi still reported the file's size
correctly, so the copy shipped 0 bytes and the size check failed every time. No amount
of retrying the same chunked path could ever succeed.

The underlying cause is a Kodi VFS property, not a bug in the copy math: Kodi's VFS can
silently return empty reads (never an exception) for a local file a different, non-VFS
writer produced, while `xbmcvfs.Stat()` on that same file reports the correct size the
whole time. Confirmed on tvOS against the add-on's own freshly built backup zip. See
`docs/playbooks/kodi-vfs-cannot-read-foreign-local-files.md`.

The fix that actually worked: read the LOCAL source with plain Python file I/O instead
of `xbmcvfs`, for both the copy and its retry, matching how the add-on already builds
and validates that same file elsewhere. Shipped as `2026.07.04.5` in commit `bf7584f`
("reads a local backup source via Python I/O, not Kodi VFS"). A remote source
(`nfs://`, `smb://`) still goes through the VFS and was unaffected.

## Contributing factors (why it took four releases)

1. **Diagnosis by theory instead of by the device log.** `2026.07.04.2` (commit
   `45354f3`) theorized the failure was a large NFS write needing a moment to commit
   server-side and added a settle wait before the size check. The failure persisted on
   a real box, disproving the theory. Per the `2026.07.04.2` and `2026.07.04.3` news
   entries.
2. **The right move only came after adding instrumentation.** `2026.07.04.3` (commit
   `91e9d79`) shipped a diagnostic-only change that logged how many bytes were actually
   read vs written on a failed attempt, explicitly stating the prior fix's theory "did
   not fully explain a real failure still seen after that fix shipped." That byte count
   is what localized the fault to the read side.
3. **The first real fix was incomplete.** `2026.07.04.4` (commit `c312cf5`) made the
   chunked copy fall back to the original whole-file VFS copy. A second real device log
   then showed the fallback VFS copy ALSO returned empty on the same local file, proving
   the VFS layer itself could not read it through any entry point. That is what forced
   the plain-Python-I/O fix in `2026.07.04.5`. Per the `2026.07.04.4` and `2026.07.04.5`
   news entries.

## Resolution

- `2026.07.04.5` / commit `bf7584f`: local backup source is read with plain Python file
  I/O for both the copy and its retry. This is the fix of record.

Verification status: the diagnosis at every step was driven by real tvOS/Apple TV device
logs (the news entries cite "a real device log" and "a second real device log"). The
sources do NOT contain an explicit confirmation that the final `2026.07.04.5` build was
re-run end to end on the device and observed to produce a non-empty backup. Treat the
root cause as device-proven and the final fix as strongly evidence-backed but not
independently re-confirmed on hardware in the record.

## Action items

- [ ] Re-run a full backup on Apple TV/tvOS on `2026.07.04.5` or later and capture the
      byte count from `kodi.log` as positive proof the local read is now non-empty.
      Apple TV/tvOS has NO adb: verify via the Xcode / idevice route on a dev-signed
      build (`docs/playbooks/atv-kodi-xcode-cli-troubleshooting.md`).
- [x] Root cause documented as a reusable class in
      `docs/playbooks/kodi-vfs-cannot-read-foreign-local-files.md`.
- [x] Triage guide captured in `.claude/skills/ezm-backup-doctor/SKILL.md`.

## The rule that would have prevented this

**When a copy reports 0 bytes, measure which side actually moved bytes before theorizing
about the network.** The byte-count log in `2026.07.04.3` found the truth in one run;
the two releases before it guessed. And for a LOCAL file another writer produced, do not
assume Kodi's VFS can read it back just because `Stat()` reports the right size.

Series context: `docs/incident-2026-07-08-ezmpp-repeated-hardware-burns.md`.
