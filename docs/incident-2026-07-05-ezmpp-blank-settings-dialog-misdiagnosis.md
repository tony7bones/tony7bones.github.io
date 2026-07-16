# Incident 2026-07-05: EZ Maintenance++ Settings dialog rendered blank, then was misdiagnosed as a Kodi engine bug

Honest record. One of the hardware burns in the series doc
`docs/incident-2026-07-08-ezmpp-repeated-hardware-burns.md`, filed on its own because the
misdiagnosis is itself the lesson: a shipped release blamed the Kodi engine for a defect
that lived in this add-on.

## Impact

- The add-on's native Settings dialog (the Configure gear) rendered every label blank,
  sometimes with no categories or controls and occasionally the wrong add-on name in the
  header. The owner could not read or change settings through the supported dialog.
- A release (`2026.07.05.0`) shipped a workaround built on a WRONG root cause, calling
  the blank dialog "a Kodi engine bug, not something fixable in this add-on's
  settings.xml." That is a false statement of record that had to be retracted two
  releases later.

## Root cause (the real one)

The add-on's `settings.xml` used plain-text labels and shipped no language file. Kodi
resolves settings labels as numeric string ids, so plain text resolves to empty, and
every label came back blank. It was NOT a Kodi engine bug: a control add-on's Settings
dialog renders fine on the same box (the check called out in MEMORY.md,
"ezm-blank-settings-was-mislabeled-not-engine-bug"). Per commit `4e8f112` and the
`2026.07.07.0` news entry.

Fix: add `resources/language/resource.language.en_gb/strings.po` and give every
`settings.xml` label, heading, and option a real numeric string id backed by that file,
which is the standard, supported way. The custom in-app settings screen that had been
built to work around the misdiagnosis was retired, and the SETTINGS item plus the
backup/restore empty-path fallbacks were routed back to the now-working native dialog.
Shipped as `2026.07.07.0` in commit `4e8f112`.

## Contributing factors (why the wrong diagnosis shipped)

1. **"It reproduces on a fresh install, so it must be the engine."** The `2026.07.05.0`
   news claims the blank dialog was "live-confirmed as a Kodi engine bug ... reproducing
   even on a fresh install and on unrelated Kodi-team add-ons." Reproducing on a fresh
   install only rules out stale state; it does not rule out a defect shared by the
   add-on's own `settings.xml` authoring. The disproof (a healthy control add-on's
   dialog on the same box) was the test that mattered and it came later.
2. **A real, separate defect masked the first.** The `settings.xml` schema was also on
   Kodi's old format and needed migration to the modern versioned schema (commit
   `7ee19fa`, shipped in the `2026.07.05.0` line). Two defects in the same file made the
   "engine is broken" story feel plausible.
3. **The workaround worked, which entrenched the wrong theory.** `2026.07.05.0` (commit
   `7f0a451`) shipped a custom in-app settings screen that read and wrote the same
   storage, so settings became usable and the misdiagnosis looked validated instead of
   challenged.

## Resolution

- `2026.07.05.0` / commits `7ee19fa` (schema migration) and `7f0a451` (custom in-app
  screen workaround): made settings usable but on a wrong root cause.
- `2026.07.07.0` / commit `4e8f112`: real fix. Every label given a numeric id backed by
  `strings.po`; the workaround screen (`settings_menu.py`) retired; a regression test
  (`test_ezmaintenanceplusplus_settings_xml.py`) added to assert every label is a numeric
  id present in `strings.po`.

Verification status: the disproof observation (a control add-on renders fine on the same
box) is a device observation. The sources do not record an explicit device run of
`2026.07.07.0` confirming the native dialog now renders all labels; the fix is the
standard supported mechanism and is regression-tested, but a device confirmation is not
in the record.

## Action items

- [x] `strings.po` added and every `settings.xml` label given a numeric id (commit
      `4e8f112`).
- [x] Regression test guards that every label is a numeric id present in `strings.po`
      (`test_ezmaintenanceplusplus_settings_xml.py`).
- [x] The mislabel-vs-engine-bug lesson recorded in MEMORY.md.
- [ ] Confirm on a real box that the native Settings dialog now renders every category,
      control, and label.

## The rule that would have prevented this

**Before blaming the platform, run the platform's own healthy example.** One look at a
control add-on's Settings dialog on the same box showed the engine was fine, which means
the defect was ours. Reproducing on a fresh install proves the state is clean, not that
the engine is broken.

Series context: `docs/incident-2026-07-08-ezmpp-repeated-hardware-burns.md`.
