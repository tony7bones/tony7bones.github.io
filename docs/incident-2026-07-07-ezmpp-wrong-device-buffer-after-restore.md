# Incident 2026-07-07: EZ Maintenance++ restore left the video cache buffer sized for the source box, not this device

Honest record. A correctness defect in restore-onto-another-box, NOT a hardware burn:
nothing was corrupted, deleted, or bricked. A mis-sized video cache buffer degrades
playback and can waste or overcommit RAM, but the box works.

Severity: correctness. Wrong setting value carried across devices; no data loss.

## Impact

- A restore clones another box's `guisettings`, so `filecache.memorysize` (the video cache
  buffer) came across sized for the SOURCE device rather than THIS device. The buffer
  should track the local device's RAM; after restoring a "base" backup onto a box with
  different RAM, the buffer could be too large (overcommitting memory on a small stick) or
  too small (under-buffering on a box with more RAM). Per commit `e068047`.

## Root cause (the real one)

`filecache.memorysize` is a device-specific tuning value stored in `guisettings`, and a
restore is a plain clone of another box's `guisettings`, so the value was carried verbatim
instead of being retuned for the target device. The restore had no step to re-derive a
RAM-appropriate buffer for the box it landed on. Per commit `e068047` ("retunes the video
cache buffer after a restore").

Fix: after a restore, `wiz.restore` drops a one-shot marker written after the extract into
EZM's own `addon_data` (so the wipe and extract cannot remove it). On the next boot the
service sees the marker, waits for Kodi to be ready, and offers a "Restore Complete"
prompt to set the buffer to the size recommended for this device
(`tools._recommended_mb`: 10% of total RAM clamped to 50-200 MB) via the existing
`filecache.memorysize` setter, or open the Buffer Size screen, or keep the current value.
It asks exactly once and never blocks boot. Shipped as `2026.07.07.6` in commit `e068047`.

## Contributing factors

1. **Restore is a whole-settings clone.** The same property that makes a "base" backup
   useful (it brings every setting) also carries device-specific tuning that should not
   transfer, and the buffer size is one of those.
2. **The correct value depends on hardware the backup cannot know.** The right buffer is a
   function of the target box's RAM, so it can only be computed on the device after the
   restore, not baked into the backup.

## Resolution

- `2026.07.07.6` / commit `e068047`: post-restore marker plus a one-shot boot prompt to set
  the device-appropriate buffer (`_recommended_mb`, 10% of RAM clamped 50-200 MB), keep,
  or open the Buffer Size screen.

Verification status: the marker-plus-boot-prompt mechanism is code-and-test level. The
sources do not record a device run confirming the prompt appears once after a real restore
and applies the recommended size, and the marker relies on surviving the wipe/extract
(it is written to EZM's own `addon_data` for that reason). Treat as evidence-backed; a
device run would confirm the marker survives and the prompt fires exactly once.

## Action items

- [x] Post-restore one-shot buffer prompt added, sized to this device's RAM (commit
      `e068047`).
- [ ] After a real restore onto a box with different RAM than the source, confirm the
      prompt appears exactly once and sets a device-appropriate buffer. Fire TV = adb
      (`_tools/firetv.sh`); Apple TV/tvOS has NO adb, use the Xcode / idevice route
      (`docs/playbooks/atv-kodi-xcode-cli-troubleshooting.md`).

## The rule that would have prevented this

**A restore that clones another box must retune device-specific settings for the target.**
Values that depend on the local hardware (video cache buffer, and anything else keyed to
RAM or the specific device) cannot be cloned verbatim; re-derive them on the box that
received the restore.

Series context (related EZM incidents):
`docs/incident-2026-07-08-ezmpp-repeated-hardware-burns.md`.
