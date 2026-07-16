# Incident 2026-07-02: EZ Maintenance++ network backups failed intermittently on Kodi's idle-closed NFS/SMB connection

Honest record. A genuine intermittent backup/restore failure over the network, distinct
from the port-baking bug (`docs/incident-2026-07-04-ezmpp-nfs-port-baking.md`) and the
VFS local-read bug (`docs/incident-2026-07-04-ezmpp-backup-size-mismatch-vfs-local-read.md`).

Severity: genuine on-hardware failure (intermittent), not a device brick. A backup or
restore to a healthy network share failed instantly some of the time; nothing was
corrupted or deleted, and re-running usually succeeded.

## Impact

- Backup, restore, and One-Tap restore to an NFS/SMB destination could fail instantly and
  report failure even though the share itself was healthy. Observed on the Office TV box
  and would apply to any box using this add-on's network destinations, per commit
  `895059e`.
- The failure was intermittent, which makes it worse to live with: the same operation
  worked most of the time and failed unpredictably, so the user could not tell whether
  the share, the network, or the add-on was at fault.

## Root cause (the real one)

Kodi's VFS layer can leave a stale connection behind after it auto-closes an idle NFS/SMB
session (an idle-close reaper). The next write reused that stale connection and failed
immediately, even though a fresh connection to the same share would have worked. Verified
with a live network write test, per commit `895059e` ("retry NFS/SMB copy after Kodi's
idle-close reaper"). The failure is timing-dependent: it only bites when a write lands
right after the reaper closed the previous idle session, which is why it was
intermittent.

Fix: `copy_with_progress` now retries a failed copy up to 3 times with a 5 second pause
between attempts, giving Kodi room to open a genuinely fresh connection. Because backup,
restore, and One-Tap restore all share `copy_with_progress`, one change covers all three
paths. Shipped as `2026.07.02.0` in commit `895059e`.

## Contributing factors

1. **Kodi does not expose the connection state.** The add-on cannot see that Kodi reaped
   an idle session, so it cannot pre-empt the stale-connection write; it can only react
   to the failure.
2. **A same-instant single attempt hit the same broken connection.** Without a pause, an
   immediate retry reused the same stale session and failed again, so the operation
   looked permanently broken when it was actually a transient reaper race.

## Resolution

- `2026.07.02.0` / commit `895059e`: up to 3 attempts with a 5 second pause between them
  in `copy_with_progress`, covering backup, restore, and One-Tap restore. The commit
  states the stale-connection behavior was "verified with a live network write test."

Verification status: the root cause was reproduced with a live network write test per the
commit message. The retry fix is a timing-tolerant wrapper; the sources do not record a
sustained device run proving the intermittent failure no longer surfaces, and later
network-copy incidents (the port-baking and VFS local-read bugs) shipped after this,
showing network reliability kept needing work. Treat this specific idle-close race as
addressed by the retry, with the broader network path still exercised by the later fixes.

## Action items

- [ ] Run repeated backups to a network share on a box that idles between runs and confirm
      the retry absorbs the reaper race with no user-visible failure; capture `kodi.log`.
      Fire TV = adb (`_tools/firetv.sh`); Apple TV/tvOS has NO adb, use the Xcode /
      idevice route (`docs/playbooks/atv-kodi-xcode-cli-troubleshooting.md`).
- [x] Retry-with-pause added to the shared `copy_with_progress` so all three network paths
      benefit (commit `895059e`).

## The rule that would have prevented this

**A network write over a connection you do not own is a transient-failure surface; retry
with a pause before reporting failure.** An immediate single attempt will keep hitting the
same reaped connection; a short wait lets the underlying client open a fresh one.

Series context (related EZM incidents):
`docs/incident-2026-07-08-ezmpp-repeated-hardware-burns.md`.
