# Incident 2026-07-08: EZ Maintenance++ settings restore scattered files into Kodi's home root instead of userdata

Honest record. One of the hardware burns in the series doc
`docs/incident-2026-07-08-ezmpp-repeated-hardware-burns.md`, filed on its own because it
is a distinct restore-correctness bug with its own root cause and fix.

## Impact

- A "settings" (`kodi_settings`) restore extracted its files into Kodi's home root
  instead of under `userdata/`, so it did not actually restore the user's settings and
  it polluted the home folder with stray files. The user got a restore that silently did
  not restore what they asked for.

## Root cause (the real one)

A settings-only backup zip is anchored differently from a full backup, and the restore
extract did not detect the anchor: it extracted a `userdata`-anchored zip at the HOME
root, scattering `guisettings.xml` and friends into the home directory rather than into
`userdata/`. Per commit `92b212a` ("anchor-aware restore and IPTV no-brick"), whose body
states "A settings-only backup now extracts under userdata instead of scattering into
Kodi's home root," and whose tests name the regression directly
(`test_restore_userdata_zip_lands_under_userdata_not_home`, commented "THE regression
guard ... the bug that bricked the box").

Fix: an `_archive_anchor()` helper inspects the zip's entries and decides whether the
archive is `home`-anchored (contains `userdata/...` and `addons/...` paths) or
`userdata`-anchored (its entries ARE the userdata content, e.g. `addon_data/`,
`guisettings.xml`), and an `_extract_skip()` filter keeps each anchor's real content
while dropping stray HOME-root pollution and temp self-references. A `userdata`-anchored
`kodi_settings` zip now extracts under `userdata/`. Shipped as `2026.07.08.4` in commit
`92b212a`.

## Contributing factors

1. **One restore path served two differently anchored archive shapes.** A full backup
   and a settings-only backup do not share a root, but the extractor assumed one layout.
2. **The bug is silent by nature.** Files landed somewhere, the extract "succeeded," and
   nothing errored; the settings simply were not where Kodi reads them, so the failure
   only shows up as "my settings did not come back."
3. **This shipped as a regression in the same window as other 07.08.x churn.** The commit
   body notes it "resolves the 2026.07.08.2/.3 restore regression that scattered files."

## Resolution

- `2026.07.08.4` / commit `92b212a`: `_archive_anchor()` + `_extract_skip()` route a
  settings-only zip under `userdata/` and drop HOME-root strays. Regression tests added
  (`test_archive_anchor_home_vs_userdata`,
  `test_restore_userdata_zip_lands_under_userdata_not_home`).

Verification status: UNVERIFIED ON HARDWARE. The fix is covered by unit tests that
extract representative zips into temp dirs and assert placement, but the sources do not
record a device restore confirming a `kodi_settings` backup lands under `userdata/` on a
real box. The whole `2026.07.08.x` restore work is treated as unverified in the series
doc.

## Action items

- [ ] Restore a settings-only (`kodi_settings`) backup on a real box and confirm the
      files land under `userdata/` and Kodi reads the restored settings. Verify per
      device class: Fire TV = adb (`_tools/firetv.sh`); Apple TV/tvOS has NO adb, use the
      Xcode / idevice route (`docs/playbooks/atv-kodi-xcode-cli-troubleshooting.md`).
- [x] Anchor detection + extract filter added with regression tests (commit `92b212a`).
- [x] Restore-hardening lessons captured in `docs/playbooks/ezm-restore-hardening.md`.

## The rule that would have prevented this

**A restore must detect an archive's anchor, never assume it.** When one extract path
handles more than one archive shape, "it extracted without error" is not "it extracted to
the right place"; assert placement, not just success.

Series context: `docs/incident-2026-07-08-ezmpp-repeated-hardware-burns.md`.
