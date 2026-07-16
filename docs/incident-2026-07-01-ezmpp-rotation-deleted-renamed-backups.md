# Incident 2026-07-01: EZ Maintenance++ backup rotation auto-deleted the backups a user renamed to keep

Honest record. A data-loss incident distinct from the hardware-burn series
(`docs/incident-2026-07-08-ezmpp-repeated-hardware-burns.md`) and from the deploy
incident (`docs/incident-2026-06-30-ezmpp-deploy.md`). It is filed here because neither
of those covers it and it is a genuine data-loss bug.

## Impact

- The "keep how many backups" rotation deleted a backup the user had RENAMED, and a
  renamed backup was made the FIRST one deleted. Renaming is exactly what a user does to
  mark a backup as one to keep, so the feature deleted the backups most likely to be
  irreplaceable. Applied to both Dropbox and Network/Local destinations.

## Root cause (the real one)

Rotation pruned by treating the whole backup set as its own rolling pool, so any file
that did not sort as a recent auto-backup was eligible for deletion first. A renamed
backup no longer ended in the tool's automatic date stamp, so instead of being excluded
from rotation it fell to the front of the delete order. Per commit `cd4784f` and the
`2026.07.01.1` news entry ("Renaming a backup used to make it the FIRST one deleted; now
it is the safest").

Fix: rotation now prunes ONLY the tool's own automatic backups, identified by their
trailing date stamp. Any backup the user renamed, or one with "keep" in the name, is
protected and never auto-deleted. Shipped as `2026.07.01.1` in commit `cd4784f`, for both
Dropbox and Network/Local.

## Contributing factors

1. **"Renamed" was not modeled as "protected."** The rotation logic had no concept of a
   user-marked keeper; it only knew "auto-stamped" vs "everything else," and "everything
   else" was treated as deletable rather than off-limits.
2. **The delete order made it worst-case.** A renamed file was not merely eligible for
   deletion, it sorted to the front, so the most deliberately preserved backup was the
   first casualty.

## Resolution

- `2026.07.01.1` / commit `cd4784f`: rotation prunes only date-stamped automatic backups;
  renamed or "keep"-named backups are protected on both Dropbox and Network/Local.

Verification status: the fix is a change to which files rotation is allowed to delete.
The sources (news + commit) describe the bug and the fix but do not record a device run
confirming a renamed backup survives a rotation cycle on a real box. Treat the fix as
evidence-backed by the release record; a live rotation test with a renamed backup present
would close it definitively.

## Action items

- [ ] Run a rotation cycle (exceed the keep-N count) with a renamed backup and a
      "keep"-named backup present, on both Dropbox and Network/Local, and confirm both
      survive while stamped auto-backups prune. Capture the before/after listing.
- [x] Rotation restricted to date-stamped automatic backups; renamed and "keep"-named
      backups protected (commit `cd4784f`).

## The rule that would have prevented this

**A destructive cleanup must delete only what it created, and must default to protecting
anything it does not recognize.** Rotation should have treated an unrecognized (renamed)
backup as off-limits, not as first-to-go. When in doubt, a pruner keeps.

Series context (related EZM incidents):
`docs/incident-2026-07-08-ezmpp-repeated-hardware-burns.md`.
