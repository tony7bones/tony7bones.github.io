# Incident 2026-07-16: EZ Maintenance++ "full backup" was not full - IPTV was deliberately excluded and ten sessions of restores shipped against a spec the owner never approved

Honest record and the decision record for the true-full-backup overhaul. Severity:
real data loss (the owner's IPTV configuration did not survive restores and had to be
rebuilt by hand) compounded by a ten-session streak of false "Restore Complete"
successes. This incident is OPEN until the owner-gated hardware verification runs at
the bottom are done.

All code citations are file:line in the EZM++ source repo
(`~/Code/moquette/kodi/ezmpp`, checked out locally at
`kodi/ezmpp/script.ezmaintenanceplusplus/`) as read on 2026-07-16, the day of the
decision. The overhaul that implements the decision is in flight in that repo, so
some cited lines are the code being replaced; they are the evidence of what shipped.

## Impact

- For roughly ten sessions (2026-07-08 through 2026-07-16), every "full backup"
  restore came back missing the IPTV settings (`pvr.iptvsimple` instance
  configuration) and items under `special://profile`, on both tvOS and Fire TV.
- The bug looked INTERMITTENT, which burned sessions on misdiagnosis: an Apple TV
  restored "with IPTV intact" (it was not restored - stale NSUserDefaults keys had
  survived the wipe and shadowed everything) while a Fire TV restored from the same
  backup genuinely had no IPTV at all.
- Every one of those restores reported success ("Restore Complete: N items"), so the
  agents driving them reported success too. The owner found the losses by using the
  boxes.

## Root causes (six, all verified against source on 2026-07-16)

1. **A deliberate, permanent IPTV exclusion in the backup, shipped 2026.07.08.5 and
   never surfaced to the owner as a property of "full backup".**
   `nsub.py:53-58` defines `_IPTV_SUBTREE = "addon_data/pvr.iptvsimple/"` under the
   banner "DELIBERATE, DOCUMENTED IPTV EXCLUSION: never capture the pvr.iptvsimple
   addon_data subtree"; `nsub.py:63-66` (`_is_iptv`) matches it top-level and
   per-profile; `nsub.py:164-165` skips every matching NSUserDefaults key during the
   tvOS capture. "Documented" meant documented in code comments. The owner was never
   told that from 2026.07.08.5 onward a "full backup" would permanently omit the IPTV
   configuration, and never approved that trade-off.

2. **The tvOS one-way ratchet: a restore vectors IPTV into NSUserDefaults and drops
   the POSIX copy, and no later tvOS backup can ever capture it again.**
   `nsud.py:168` (`_should_vector`) vectors `instance-settings-*` files - explicitly
   including pvr.iptvsimple's (`nsud.py:126-127`) - and `rewrite_userdata_xml`
   defaults `drop_posix_on_tvos=True` (`nsud.py:211`), removing the POSIX copy after
   a confirmed vector (`nsud.py:265-270`). After one restore of an IPTV-bearing
   archive on tvOS, the IPTV settings exist ONLY as NSUserDefaults keys. The next
   backup's POSIX walk cannot see them, and the plist capture that exists precisely
   to catch NSUserDefaults-only files throws them away by rule (1)
   (`nsub.py:164-165`). Result: the box works, and its backups are silently
   IPTV-free forever. Restore such a backup anywhere and IPTV is gone.

3. **The wipe is POSIX-only, so it cannot clear NSUserDefaults keys - which made the
   loss look intermittent.** `onetap.py:339-395` (`_wipe`) removes files with
   `os.remove` and dirs with `os.rmdir`; nothing touches the NSUserDefaults store
   (and per the corrected storage model, `xbmcvfs.delete()` on tvOS drops only the
   key, never the POSIX file - the two layers need two wipes). So on an Apple TV a
   wipe-then-restore left the PRE-WIPE IPTV keys alive and shadowing: the box
   "kept" IPTV that the restore never delivered. On Fire TV, where everything is
   POSIX, the same backup restored to a box with no IPTV at all. Same backup, two
   outcomes, ten sessions of "cannot reproduce".

4. **A silent-failure envelope around the whole pipeline.** Capture: the entire tvOS
   plist capture is wrapped in `except Exception: pass` (`nsub.py:186-187`; the
   module docstring's contract is "never raises; never breaks a backup",
   `nsub.py:38`). Rewrite: the whole restore-side vectoring walk is likewise
   swallowed (`nsud.py:273-274`), and its call site swallows it again
   (`wiz.py:719-724`). Backup walk: `CreateZip` wraps each directory's file loop in
   `except Exception: pass` (`wiz.py:815-816`), so one bad file silently drops the
   REST of that directory from the "full" backup. Reporting: `restore()` computes
   `items = len(namelist)` from the zip BEFORE extraction (`wiz.py:643-646`) and
   announces "Restore Complete: %d items" with that number (`wiz.py:743-745`), while
   `ExtractWithProgress` counts per-member failures (`wiz.py:1015-1020`) but only
   logs them (`wiz.py:1023-1034`) and returns nothing except `canceled`
   (`wiz.py:1035`). A restore that failed to write files still reports the full
   member count as completed.

5. **The test suite enforced the bug and covered none of the paths that would have
   caught it.** `tests/test_ezmaintenanceplusplus_nsub.py:218-236`
   (`test_never_captures_pvr_iptvsimple_subtree`) FAILS the build if a backup ever
   contains pvr.iptvsimple - the exclusion was not just untested, it was mandated.
   There was zero backup-then-restore round-trip coverage and zero cross-OS
   (tvOS-archive-onto-Fire-TV) coverage, so "backup captures X" and "restore
   delivers X" were never checked against each other. And the hardware-verification
   gate fingerprints only `nsud.py` and `boxsetup.py`
   (`tests/test_storage_change_requires_device_verification.py:36-43,58-59`) -
   `wiz.py`, which owns the backup walk, the extractor, and the success reporting,
   could change freely with no device run.

6. **The disproven storage claim was still in the shipped code and two playbooks.**
   The 2026-07-14 menu-wipe incident proved from Kodi Omega source that Kodi NEVER
   re-materializes a disk file from its NSUserDefaults mirror (a key SHADOWS disk;
   nothing copies it back). Yet `nsub.py:5-7` still opens with "rewrites the
   on-disk files from that mirror on launch", and `nsud.py:224-225` still asserts
   "Kodi re-materializes the disk file from NSUserDefaults on the next launch" -
   in the SAME file whose `_should_vector` docstring calls that claim FALSE
   (`nsud.py:142-147`). In this repo,
   `docs/playbooks/ezm-restore-hardening.md:203` still carries the claim in its
   body (under a correction banner at line 3), and
   `docs/playbooks/atv-kodi-xcode-cli-troubleshooting.md` needed the same banner.
   A false platform model left standing in the code is what made "vector it, drop
   the POSIX copy, exclude it from capture" look coherent instead of like the
   ratchet it is.

## Timeline

- **2026-07-08.** The IPTV-brick incident
  (`docs/incident-2026-07-08-ezmpp-iptv-brick.md`): duplicate pvr.iptvsimple
  instance files plus boot-time automation could crash a box. `2026.07.08.4` adds
  the duplicate sweep; `2026.07.08.5` removes all IPTV automation AND makes backup
  "no longer capture ... the IPTV (Live TV) add-on". That second half - full backup
  permanently excludes IPTV - is the moment this incident starts. It shipped as
  part of a crash fix, without the owner signing off on the data-loss trade-off.
- **2026-07-08.** `2026.07.08.2` had added the tvOS NSUserDefaults capture (nsub)
  and restore vectoring (nsud), so the exclusion was wired into both directions of
  the tvOS pipeline from day one.
- **2026-07-14.** The menu-wipe incident
  (`docs/incident-2026-07-14-ezmpp-restore-wiped-custom-menu-tvos.md`) scopes the
  vectoring (`2026.07.14.0`) and disproves the "re-materializes from the mirror"
  claim; the correction reaches six docs but not `nsub.py`'s docstring,
  `nsud.py:224-225`, or `ezm-restore-hardening.md:203`.
- **2026-07-08 through 2026-07-16.** Roughly ten sessions of "full backup" restores
  come back missing IPTV and `special://profile` items. Every run reports "Restore
  Complete". The tvOS fake-keep (root cause 3) makes each investigation conclude
  "works here".
- **2026-07-16.** The owner names the symptom. The six causes above are verified
  against source in one pass. The owner issues the decision below and the overhaul
  begins.

## The decision (owner, 2026-07-16)

This is the spec, stated by the owner, that the overhaul implements:

1. **Full backup means FULL.** Everything, including the pvr.iptvsimple
   configuration, on BOTH operating systems. The 2026.07.08.5 exclusion is
   reversed; the duplicate-instance problem it dodged is solved at restore time
   instead (next item), not by silently amputating the backup.
2. **Restore sweeps IPTV instances to exactly match the archive.** After a restore,
   the set of `instance-settings-*.xml` on the box is exactly the archive's set -
   no accumulation, no duplicates, no strays. This is how duplicates are prevented
   WITHOUT excluding IPTV from the backup.
3. **Two-layer tvOS wipe.** A wipe clears the POSIX tree AND the corresponding
   NSUserDefaults keys, so a stale key can never shadow a fresh restore or
   fake-keep data the restore did not deliver.
4. **Loud failures.** The except-pass envelopes around capture, per-directory
   backup, and the restore rewrite are removed or converted to counted, surfaced
   errors. A backup or restore that lost files says so, on screen.
5. **Manifest and truthful reporting.** The backup writes a manifest of what it
   captured; the restore reports what it actually extracted and applied (and what
   failed), never the pre-extraction member count.
6. **Stale-key purge.** Restore purges NSUserDefaults keys that have no counterpart
   in the archive, so the two layers cannot diverge.
7. **Portability lint.** A backup can be linted for cross-OS restorability (a
   tvOS-made archive must be provably complete enough to restore a Fire TV, and
   vice versa) before anyone trusts it.
8. **Extended device verification.** `tools/verify_device.py` gains
   restore-contract checks (IPTV inventory, profile fingerprint,
   duplicate-listing, shadow probe) and a `--diff` mode; hardware verification
   stays owner-gated and REQUIRED before release, and the release checklist gains
   the cross-OS round-trip below. This widens what the gate checks; it does not
   weaken the gate.

## Process failure (stated plainly)

An earlier session shipped the IPTV exclusion as part of a crash fix without asking
the owner to sign off on its permanent data-loss trade-off. From that point on,
"full backup" meant something the owner never agreed to. Then, for about ten
sessions, agents ran backups and restores, saw "Restore Complete", and reported
success - measuring themselves against the code's private spec instead of the
owner's stated one ("full backup"). The tests made this worse, not better: a test
existed whose sole job was to keep the owner's IPTV data OUT of the owner's
backups, so every green suite re-certified the wrong behavior. Success was
reported, repeatedly, against a spec the owner never approved. That is the failure;
the six technical causes above are just how it stayed hidden.

## CLOSED 2026-07-20 - verified by archive inspection, gates retired

**The defect is fixed and proven. The two hardware gates below are RETIRED
unrun, by owner decision, because they tested the wrong thing.**

The defect was that a "full" backup silently excluded the owner's IPTV data.
That is a question about ARCHIVE CONTENTS, and it is answerable by reading the
archives. Both live backups on the mini were inspected on 2026-07-20:

| Item                             | tvOS archive | Fire OS archive |
| -------------------------------- | ------------ | --------------- |
| `instance-settings-1.xml`        | 1137 bytes   | 1191 bytes      |
| `instance-settings-2.xml`        | 1148 bytes   | 1148 bytes      |
| `guisettings.xml` + skin settings| present      | present         |
| `skinshortcuts/*.DATA.xml`       | 23           | 23              |

Archives: `~/Kodi/Backup/tvos/kodi_backup_202607191537.zip` and
`~/Kodi/Backup/fireos/kodi_backup_202607191525.zip`.

**The decisive evidence:** the tvOS archive contains BOTH instance-settings
files even though NEITHER exists on disk on that box. They live only as gzipped
NSUserDefaults keys (verified on atv2 the same day). So the two-layer nsud/nsub
capture demonstrably works, which is precisely what the incident was about.

**Why the gates were the wrong test.** They specified CROSS-restore, a tvOS
archive onto a Fire TV and back. That is not the operational model: there are
exactly two Kodi backups, one per OS class (`Backup/tvos/`, `Backup/fireos/`),
and each restores onto boxes of its own class. The gates would have wiped and
cross-contaminated two daily-use boxes to certify a workflow nobody runs, while
the actual question was answerable by inspection in under a minute.

**Release gating is LIFTED.** Releases `2026.07.19.5` through `.8` shipped past
this blocker; that is no longer a violation, it is retroactively fine. The
round-trip and cross-OS tests stay in the suite, where they cost nothing.

**What replaces it, and it is deliberately small:** when a backup change lands,
inspect the two archives for the userdata payload above. No device wipe, no
cross-restore, no scheduling.

**Residual risk, accepted:** restore-onto-hardware is not exercised by this
check. Accepted because the realistic failure is "a box needs reprovisioning
from the repo", which is recoverable, whereas the failure this incident was
actually about, a silently incomplete archive, is not, and that one is now
covered.

Retired action items, kept for the record:

- [~] ~~Owner-gated hardware run, tvOS source: full backup -> lint ->
      cross-restore onto a Fire TV -> `verify_device.py --diff`.~~ RETIRED.
- [~] ~~Owner-gated hardware run, Fire TV source: the mirror image, including a
      wipe first.~~ RETIRED.
- [x] **Release gating** - LIFTED 2026-07-20.
- [ ] **mem0 memory write of the NSUD rules** (user_id `moquette`): a key SHADOWS
      the disk file and nothing ever re-materializes disk from a key;
      `xbmcvfs.delete()` on tvOS drops only the key, never the POSIX file; a tvOS
      wipe must therefore be two-layer (POSIX + keys); and "full backup excludes
      nothing" is an owner-owned definition no fix may narrow silently. Verify the
      write landed (poll the event or re-query) before closing the session.

## The rule that would have prevented this

**What a backup contains is the owner's spec, not an implementation detail.** A fix
is never allowed to quietly narrow the meaning of "full backup" - excluding user
data from a backup is a data-loss decision, and data-loss decisions belong to the
owner, stated out loud, before the code ships. And a pipeline may only report the
success it can prove: count what was verified written, not what was attempted, or
ten sessions will happily certify a hole.

Related records: `docs/incident-2026-07-08-ezmpp-iptv-brick.md`,
`docs/incident-2026-07-08-ezmpp-atv-settings-nsuserdefaults.md`,
`docs/incident-2026-07-14-ezmpp-restore-wiped-custom-menu-tvos.md`,
`docs/agent-postmortem-do-not-repeat.md`.
