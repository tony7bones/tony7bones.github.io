# Handoff to the LOCAL Claude Code agent — verify + release the Apple TV restore fix

**You are the Claude Code agent running on the owner's Mac** (the cloud agent that wrote the
fix cannot reach the LAN; you can). You have Xcode CLI tools, `pymobiledevice3`, `plutil`,
and LAN access to **atv-1 = `192.168.7.220`**. This repo is checked out on branch
`claude/atv-backup-user-settings-bkujms`. Your job: **prove the fix works on atv-1, then
release it** — and if it does not work, report exactly why with the on-device evidence.

**Do the whole thing yourself.** Do not ask the owner to run commands you can run. Only
involve them for the physical Apple-TV actions you truly cannot do remotely (triggering a
restore inside Kodi's UI, and the swipe-up force-quit) — and even then, drive right up to
that line and tell them the single action, then continue.

## The fix you are verifying (already implemented on this branch)

Root cause: on tvOS Kodi stores `userdata/*.xml` in **NSUserDefaults** and rewrites the disk
files from it on boot. The restore extracts with plain `zipfile` (POSIX), which bypasses
Kodi's `CTVOSFile` VFS, so restored settings never enter NSUserDefaults and are shadowed by
the stale mirror at boot → the restore "doesn't stick." The fix (`resources/lib/modules/nsud.py`,
wired into `wiz.restore()`): after extract, re-write each restored `userdata/*.xml` **through
`xbmcvfs`** (vectors into NSUserDefaults, `synchronize=true`), with a single-write-per-file
rule, an exclusion list, and a PVR-disable-window for `pvr.iptvsimple` instance settings.
Full context: `docs/plans/atv-restore-vfs-rewrite.md`, `docs/plans/atv-restore-implementation-handoff.md`.
CLI reference: `docs/playbooks/atv-kodi-xcode-cli-troubleshooting.md`.

## Success criteria (the gate — do not release without it)

On atv-1, after a restore → swipe-quit → reopen, the restored settings are LIVE, and the
decisive proof is that they are present as **full, well-formed XML** in the NSUserDefaults
plist key. The one-command test:
```bash
/usr/libexec/PlistBuddy -c 'Print :"/userdata/guisettings.xml"' post.plist | xxd -r -p | gunzip | head
```
- **Full `<settings>…</settings>` = PASS.** 
- **A tail fragment (starts mid-element, no root) = the chunking bug** — stop, report, do not ship.
- **Key absent = a 500 KB overflow or a non-vector** — stop, report.

## Phase 0 — connect to atv-1 (do this yourself)
```bash
xcode-select -p
xcrun devicectl list devices
# If atv-1 isn't listed: pair it. Prefer devicectl; fall back to pymobiledevice3 with the IP.
xcrun devicectl manage pair --device <UDID>        # or:
python3 -m pymobiledevice3 remote pair
sudo python3 -m pymobiledevice3 remote tunneld &   # tvOS17+ needs the tunnel for pmd3
```
Capture: atv-1's **UDID** and Kodi's **bundle id** (`xcrun devicectl device info apps --device <UDID> | grep -i kodi` — may be `org.xbmc.kodi` or a re-signed id). Set them as shell vars for the rest. Resolve Kodi's in-container userdata path by enumerating the container (`xcrun devicectl device info files --device <UDID> --domain-type appDataContainer --domain-identifier <bundle>` or the GUI-download `find`), per the CLI playbook §2/§3.

## Phase 1 — prove the ROOT CAUSE first (no code deploy needed; cheap, high-value)
Establishes the baseline so a later PASS is meaningful.
1. Pull `Library/Preferences/<bundle>.plist` (`devicectl device copy from … --domain-type appDataContainer --domain-identifier <bundle> --source Library/Preferences/<bundle>.plist`). Confirm a `"/userdata/guisettings.xml"` key EXISTS and decodes to the box's current settings → proves the NSUserDefaults mirror is real.
2. Have the owner run a normal restore of a backup whose settings differ (this is the one physical action). Pull the container again: the on-disk `userdata/guisettings.xml` shows restored values, but the plist key still holds OLD values → **the shadow, proven on hardware.** Owner swipe-quits + reopens → settings reverted. Record this as the "before fix" evidence.

## Phase 2 — get the FIXED add-on onto atv-1
The fix is on this branch but not in a released zip. Choose the lowest-risk deploy you can
verify on the actual device (you can SEE the container; decide from what's real):
- **Option A (preferred if the add-on dir is writable in the container):** build the add-on
  zip from this branch and install/replace it so `resources/lib/modules/nsud.py` and the
  patched `wiz.py` are present on atv-1. You can build the tree with the repo tooling
  (`python3 _tools/generate_repo.py` produces the per-add-on zip) and push the two changed
  files into the installed add-on dir in the container via `devicectl device copy to`
  (`--domain-type appDataContainer`), then rescan/enable. Verify the files landed by pulling
  them back.
- **Option B (a controlled release):** only if a container-side install isn't viable. Bump
  `addon.xml` to the next `YYYY.MM.DD.N`, hand-edit `<news>`/`changelog.txt`, `generate_repo`,
  push `main`, let Kodi update atv-1, then verify. (This ships to ALL boxes — prefer A for a
  pre-proof test; if you must use B, treat this run's version as the candidate and be ready to
  bump again on failure.)
Whichever you pick, confirm on-device that the new `nsud.py` is actually in Kodi's add-on
before testing (pull it back and diff against this branch's copy).

## Phase 3 — run the proof
1. Owner triggers a restore in Kodi (the physical action), then **swipe-quit + reopen**.
2. Pull the plist → `post.plist`, run the PlistBuddy→gunzip decode above on the
   `guisettings.xml` key AND on an `instance-settings-1.xml` key (for IPTV). Also `ls -l
   post.plist` to check it's well under the platform plist ceiling.
3. Confirm in the Kodi UI (JSON-RPC over the web server, or ask the owner to glance) that
   weather/RSS/skin/TV actually came back.
4. Interpret per the gate. Save `post.plist` + the decodes as evidence in the PR.

## Phase 4 — release (ONLY on a PASS)
Per this add-on's convention (NOT `release.py`'s news automation — see the `ezm-backup-doctor`
skill):
1. Bump `addons/script.ezmaintenanceplusplus/addon.xml` to the next `YYYY.MM.DD.N`.
2. Hand-write the `<news>` block + `changelog.txt` entry in the add-on's multi-line voice
   (see the suggested wording in `atv-restore-implementation-handoff.md` §9).
3. `python3 _tools/generate_repo.py`; run `python3 -m pytest _tools/ -q` + `ruff check _tools/`.
4. Commit + push `main` (this add-on is served straight from `main`). Verify atv-1 (and, when
   convenient, atv-2) picks up the update and a fresh restore now sticks.
5. Update PR #4 (or open the release PR) with the on-device evidence and mark the design docs
   shipped.

## If it FAILS
Report the exact failure mode from Phase 3 (fragment / absent key / values still stale),
attach the plist decode, and map it to the handoff doc's known modes (chunking → §4.2 rule
regressed; absent → 500 KB overflow or a `WantsFile` non-match; stale on-disk but present
in plist → a read-order issue). Do NOT release. Loop the diagnosis back (the cloud agent can
pick it up from the evidence you commit).

## Guardrails
- Never `--remove-existing-content true` on `devicectl copy to` (wipes the whole container).
- Keep secrets out of anything you commit (the plist may contain tokens — redact before PR).
- The fix is guarded to never break a restore; if anything on-device looks like data loss,
  stop and report rather than pressing on.
