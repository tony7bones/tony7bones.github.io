# Plan — Center the KODI wordmark over the Settings gear (MOD V2+ home)

> Status: **PROPOSED — feasibility done, not executed.** No repo changes yet.
> Scope: cosmetic position change to the home-screen branding in
> `script.tony7bones.modv2plus`. One file (`Home.xml`), no Python, no new art.
> Ships via the `script.*` path (`generate_repo.py` + push), **not** `deploy.py`.

## Goal

In the **full-menu home view** (3 system buttons showing: power · settings · search),
move the white **KODI wordmark** so it is **horizontally centered above the Settings
(gear) icon**. Idle/3-button state is the target — it's what the home screen shows at rest.

## What we found (feasibility)

Two top-left images, both **static image controls** in a group anchored at `left=20, top=20`:

- diamond **mark** — `icons/logo.png`, 56×56
- **KODI wordmark** — `extras/logo-text-hires.png` (the file our patch ships)

The wordmark exists in **two** branding groups (MOD V2 swaps between them):

| Group    | Where used            | Wordmark control  | `left` | box width |
| -------- | --------------------- | ----------------- | ------ | --------- |
| main     | full menu (the photo) | `Home.xml` ~L2476 | 55     | 202       |
| fallback | widgets / minimized   | `Home.xml` ~L2401 | 40     | 192       |

Both have a **hardcoded `<left>`** — trivial to move.

The Settings gear (`id=802`, `Home.xml` ~L2052) is **not** at a fixed X. It's one item
in a horizontal **`grouplist id=700`** (`Home.xml` ~L1989): `width=480`, `align=justify`,
items power → settings → search, each 80px wide. With justify + 3 buttons the gear lands
**dead-center of the 480px row**.

## Constraints / wrinkles (the honest part)

1. **The gear moves.** A 4th button, **Fullscreen** (`id=803`), appears whenever
   `Player.HasMedia`. The row re-justifies to 4 items and the gear shifts ~65px left.
   A single fixed wordmark `<left>` can be _perfectly_ centered in only **one** state.
   → Center for the **idle/3-button** state (the photo); accept a small drift while media plays.

2. **`aspectratio=keep`** left-justifies the glyph inside its 202px box, so the visible
   "KODI" is narrower than the box. "Centered" must be computed from the **rendered glyph
   width**, or done by giving the control `<align>center</align>` over a box whose center
   equals the gear's center — not by eyeballing `<left>`.

3. **Two coordinate origins.** The branding group and the menu group that holds the button
   row have different offsets, so the exact pixel needs **one on-device measurement**, not
   pure arithmetic.

4. **Two copies.** Both wordmark controls (main + fallback) should move together so the
   branding stays consistent across states.

5. **Design consequence.** Today "KODI" hugs the diamond (reads as one lockup: ◆ KODI).
   Centering over the gear **pulls the wordmark away from the diamond** — they stop being a
   tight pair. Aesthetic call, not a technical blocker.

## Open decisions (confirm before executing)

- [ ] **Center for which state?** Idle/3-button (recommended — matches the at-rest photo).
- [ ] **OK to decouple "KODI" from the diamond mark?** Required to sit it over the gear.
- [ ] **Both groups, or main only?** Recommended: both, for consistency.

## Plan (small phases, QA gate each)

### Phase 1 — Measure on device

- Screencap the real Office Fire TV home (idle) via `_tools/firetv.sh`.
- Measure the gear's center X and the rendered wordmark glyph width/position.
- Derive the target `<left>` (and decide `<align>center</align>` vs. raw `<left>`).
- **Gate:** numbers written down; target X agreed.

### Phase 2 — Edit `Home.xml`

- Update the **main-group** wordmark control (~L2476): new `<left>` (± `<align>center</align>`).
- Update the **fallback-group** wordmark control (~L2401) to match the same visual intent.
- No other files touched.
- **Gate:** `python3 -m pytest _tools/ -q` + `ruff check _tools/` green (no behavior change, but keep the gate honest).

### Phase 3 — Build + verify on device

- `python3 _tools/generate_repo.py` (rebuilds the zip + addons.xml).
- Bump `script.tony7bones.modv2plus` version in its `addon.xml` (+ news line).
- Push to the Fire TV, Apply, screencap idle state → confirm centered over the gear.
- Also screencap a media-playing state to document the expected drift.
- **Gate:** side-by-side before/after screencaps; centering confirmed in idle state.

### Phase 4 — Ship

- Commit regenerated files + `addon.xml` bump.
- `git push` (pre-push hook runs tests / ruff / staleness / version-bump gate).
- **Gate:** hook passes; live home view verified once more after Kodi auto-updates the add-on.

## Effort

Small. One XML file, no new code or art. Real time is the device measure + verify loop —
roughly an hour or two end to end.

## Out of scope

- Making the wordmark track the gear across the 3↔4 button change (would need a variable /
  conditional position, not a static `<left>`). Revisit only if the media-playing drift is
  judged unacceptable.
- Any change to the diamond mark, the button row, or other home elements.
