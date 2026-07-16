# Incident 2026-07-04: EZ Maintenance++ backups failed because Kodi baked :2049 into the NFS path

Honest record. One of the network-copy hardware burns in the series doc
`docs/incident-2026-07-08-ezmpp-repeated-hardware-burns.md`, filed on its own because it
is a distinct root cause with its own release.

## Impact

- Backups and restores to an NFS destination failed every time with a `VfsCopyError` or
  a 0-byte copy on affected boxes. Confirmed live on two different boxes.
- The failure was not user-correctable: the destination setting can only be set through
  Kodi's own network-browse dialog, so a user could not type a good path even if they
  knew the fix.

## Root cause (the real one)

`download.path` and `restore.path` are Kodi `type=folder` settings: browse-only, with no
manual text entry. Kodi's own network-browse dialog hands back an NFS URL with an
explicit port baked in (`nfs://host:2049/export/path`), and that explicit-port form
breaks Kodi's own NFS client write path, producing a `VfsCopyError` or 0-byte copy every
time, while the port-free form (`nfs://host/export/path`) writes fine. Because the
setting can only ever be set via that same dialog, this can recur on any future box.
Per commit `5440beb` ("backup destination survives Kodi's port-baking NFS browse
dialog"), which states this was "live-proven, independently, on two different boxes."

Fix: a `_strip_nfs_port()` helper defangs the URL at both read sites (the `download.path`
read in `backup()` and the `restore.path` read in `restoreFolder()`), stripping an
explicit `:2049` port before the path is handed to the copy. Shipped as `2026.07.04.1`.

## Contributing factors

1. **The setting is browse-only.** There is no code path for the user to enter a
   port-free URL by hand, so the bad value is unavoidable through normal use.
2. **Kodi supplies the broken value AND rejects it.** The same client that writes the
   port into the path then fails to write through it, so the fault is invisible from the
   add-on's point of view without knowing this quirk.

## Resolution

- `2026.07.04.1` / commit `5440beb`: `_strip_nfs_port()` strips an explicit port at both
  read sites. The commit adds unit tests that fail on the pre-fix code and pass on the
  post-fix code, including an end-to-end `backup()` test that asserts the STRIPPED path
  reaches `CreateZip`.

Verification status: the root cause (port form breaks, port-free form works) was
live-proven on two boxes per the commit message. The fix itself is covered by unit tests
that exercise both read sites; the sources do not record a post-fix live NFS backup run,
but the mechanism is a deterministic string transform and the failing/passing device
behavior was directly observed.

## Action items

- [x] `_strip_nfs_port()` applied at both `download.path` and `restore.path` read sites
      with regression tests (commit `5440beb`).
- [ ] If Kodi ever changes the browse dialog to allow a manual entry, drop the strip only
      after confirming the port form still breaks writes on current Kodi.

## The rule that would have prevented this

**Treat any path Kodi's own browse dialog returns as untrusted input.** A file manager
that both produces and rejects the same URL form will burn you; normalize network paths
at the read site, not at the point of entry you do not control.

Series context: `docs/incident-2026-07-08-ezmpp-repeated-hardware-burns.md`.
