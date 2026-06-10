# TASKS

Tracking for the Tony.7.Bones repo.

> **CURRENT FOCUS: the modular "0-1-2" Setup rewrite** — branch **`modular-setup`**.
> Full design + phase log + forward plan: **`docs/plans/modular-setup.md`** (read it first).

---

## ⛔ WORKFLOW — non-negotiable, every phase (do NOT skip or reorder)

> **implement → TEST → COVERAGE (≥90% new code) → GATE (`pytest _tools/ -q` + `ruff` + secrets all
> green) → adversarial QA completeness review → real-device verify on local Kodi (if runtime) →
> DOCUMENT (phase log) → only THEN commit → only THEN start the next phase.**

1. **NO COMMIT until ALL of the above pass.** Red suite / missing test / unreviewed change /
   undocumented phase = do not commit.
2. **NO next phase until the current phase is committed green.** Phases are sequential-gated.

This discipline caught real bugs pre-commit in every phase (the snapshot rebaseline footgun, a
tech-debt seam, the apply_iptv reporting bug, the zero-content guarantee). Keep it.

---

## ▶ VERY NEXT STEP — Phase 5b, step 1: fix the two `apply_iptv` bugs

The Phase 5a·3 clean-Kodi run installed pvr.iptvsimple but left it **unconfigured** (no channels).
Two IPTV-LAYER bugs (in `apply_iptv` / `_ensure_iptv_custom_tv_groups` — NOT Foundation) must be
fixed FIRST in Phase 5b:

1. **Instance-settings clobber** — `apply_iptv` ENABLES pvr.iptvsimple (which instantiates the live
   PVR client with stock in-memory defaults) BEFORE it WRITES `instance-settings-*.xml`, so the
   running client flushes its stale defaults back over the write (same class as the `Skin.SetBool`
   clobber). **Fix:** write/enforce instance-settings BEFORE enabling the backend (or disable around
   the write / force a reload after). Check the Express `_configure_box` path for the same race.
2. **Multi-provider env gap** — the enforce reads single-instance `IPTV_M3U`/`IPTV_EPG`/`IPTV_GROUPS`,
   but the per-device `.env` uses multi-provider `IPTV_<N>_*`. **Fix:** generalize `apply_iptv` to N
   providers → N `instance-settings-<N>.xml` + N `customTVGroups-*.xml`.

**Acceptance for these:** clean-Kodi run of `run_foundation_setup` with `.env.local` (real IPTV) →
channels ACTUALLY load (the 5a·3 verify could not confirm this because of bug #1).

Then continue Phase 5b per `docs/plans/modular-setup.md` → "Phase 5b — NEXT": host-side build
(`build_iptv.py` from the `iptv` branch), `run_iptv()`, gate. Then 5c (Add-ons layer), 5d (Guided
wizard + Model A), 6 (harden + Fire TV).

---

## Build status (modular-setup branch)

- **DONE, gated, committed LOCALLY** (HEAD `1d68284`): Phases 0–3 + 5a (Foundation, incl. 5a·2/5a·3).
- **NOT PUSHED** — milestone-push pending: needs `script.module.tony7bones` + `script.tony7bones.bootstrap`
  version bumps + `--news` (modv2plus is already 1.4.8). Push the branch once 5b lands or at the next
  coherent milestone.
- The deploy gate (`_tools/test_installer_present.py`) is on **`main`**; the `iptv` branch (build_iptv.py
  - playbook + tests) is pushed and awaits the Phase 5b integration.

---

## Backlog — Estuary MOD V2+ (`script.tony7bones.modv2plus`), lower priority

- [ ] **Settings menu order toggle** — "Skin Settings first", default ON; off = stock order. _Harder_ (list item order isn't cleanly conditional).
- [ ] **Re-skin the MOD V2+ add-on icon** to reflect the "+" branding (currently reuses the old patch icon).
- [ ] **Localized `strings.po`** for our category labels/help (currently literal text).
- [ ] **`drop/` staging folder** at the repo root — a staging area for incoming files/assets. _Purpose/usage to confirm before building._

> Conventions: batch work into versioned deliverables; build bundled skin files FRESH from current
> omega source (b-jesch Omega / Kodinerds omega.4); verify on real local Kodi before shipping; no AI
> attribution anywhere. `script.*` changes ship via `generate_repo.py` + push (no proxy/deploy.py).
> Shipped/done history is not tracked here — live state lives in `addons/*/addon.xml` versions, git
> tags, and CLAUDE.md.
