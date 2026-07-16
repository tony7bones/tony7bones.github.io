# Incident 2026-07-04: the release tool truncated and mangled EZ Maintenance++'s changelog

Honest record. This is a RELEASE-HYGIENE defect in this repo's own tooling, NOT a device
backup/restore burn. Nothing on any Kodi box was corrupted, deleted, or bricked. The only
user-visible symptom is that the add-on's in-app "What's New" / About text displayed
mangled, truncated release notes.

Severity: release-hygiene / tooling. No hardware impact; cosmetic-to-informational
(garbled release notes and lost history in the shipped `<news>`).

## Impact

- Running `release.py` on EZ Maintenance++ ran its `<news>` through this repo's
  rolling-cap prepend logic, which truncated roughly 190 lines of real, multi-paragraph
  release history (going back to 2020) down to a few mangled lines with extra indentation
  added throughout. Per commit `e0fd551`.
- The commit notes this is "very likely what the add-on's Settings/About screen showed as
  broken," which ties it to the in-app changelog display users saw, but no
  backup/restore behavior was affected.

## Root cause (the real one)

`release.py`'s default news-writing path (`prepend_addon_news`) assumes every first-party
add-on uses this repo's own short, one-line-per-version convention. EZ Maintenance++ is a
mirrored third-party fork that has always used its own multi-line, multi-paragraph
changelog format going back to 2020. Running that format through the rolling-cap prepend
logic truncated and re-indented it. Per commit `e0fd551` ("changelog corruption from the
previous release").

Fix: the commit restores the full historical `<news>` content from before the previous
release and prepends the new entry in the add-on's own established multi-paragraph format
instead. It was shipped as `2026.07.04.1` rather than by editing `2026.07.04.0` in place,
because Kodi will not re-serve a version it already fetched.

## Contributing factors

1. **A generic tool was applied to a non-generic add-on.** `release.py`'s rolling-cap
   writer owns this repo's own short changelog convention, but EZ Maintenance++ does not
   use that convention, so the writer mangled a format it does not own.
2. **The version-math scoping was fixed but the news-content scoping was not.**
   `release.py` / `release_lib.py`'s version math and consistency gates were already
   correctly scoped to this add-on's real legacy date-version scheme (fixed earlier in the
   same session per the commit body), but the news CONTENT convention remained a separate,
   still-open gap: the tool still used the generic rolling-cap writer for an add-on whose
   changelog format it does not own.

## Resolution

- `2026.07.04.1` / commit `e0fd551`: full historical `<news>` restored; the new entry
  prepended in the add-on's own format. This fixed the corrupted content for that release.
- The underlying tooling gap was explicitly NOT fixed in that commit. The commit body
  states a proper fix "would need a per-addon opt-out" so `release.py` does not run the
  generic rolling-cap writer against an add-on whose changelog format it does not own, and
  flags it "before the next EZ Maintenance++ release repeats this." That means the defect
  can recur on the next release unless the tooling is changed.

Verification status: the corrupted content was restored in the shipped `2026.07.04.1`
`<news>`, verifiable in the addon.xml history. The root-cause tooling gap remains OPEN.

## Action items

- [x] Restore the full historical `<news>` and reship as `2026.07.04.1` (commit `e0fd551`).
- [ ] Add a per-addon opt-out so `release.py` / `prepend_addon_news` does not apply this
      repo's rolling-cap one-line convention to EZ Maintenance++ (a mirrored fork with its
      own multi-paragraph changelog format). Until then, hand-check the `<news>` on every
      EZM release. OPEN.
- [ ] Consider a release-tool test asserting an EZM release preserves its historical
      `<news>` rather than truncating it.

## The rule that would have prevented this

**Do not run a format-owning tool against content whose format it does not own.** The
rolling-cap news writer is correct for this repo's own short changelogs and wrong for a
mirrored fork's multi-paragraph history; a per-addon opt-out (or format detection) is
required before a generic writer touches a foreign changelog.

Series context (related EZM incidents):
`docs/incident-2026-07-08-ezmpp-repeated-hardware-burns.md`.
