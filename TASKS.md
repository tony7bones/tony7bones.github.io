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

## ▶ VERY NEXT STEP — Phase 5b, step 2: integrate the host-side IPTV build (`build_iptv.py`)

Phase 5b·1 (both `apply_iptv` bugs) is **DONE and clean-Kodi proven** — see the Phase 5b·1 entry in
`docs/plans/modular-setup.md`: the PVR-disabled config window kills the instance-settings clobber,
`IPTV_<N>_*` envs now drive N pvr.iptvsimple instances, and the acceptance landed live (the three
custom groups loaded **158 / 47 / 24 real channels** from `.env.local`'s m3u provider; settings
survive the shutdown flush; the xtream provider is skipped in-Kodi with an honest log).

Step 2 — the deferred P2 work (per `docs/plans/modular-setup.md` → "Phase 5b"):

1. Bring `_tools/build_iptv.py` + `_tools/test_build_iptv.py` + the customization playbook over
   from the **`iptv` branch** (98%-covered, m3u + xtream modes) into the provisioner.
2. Have `apply_iptv` consume its staged curated `instance-settings-<N>.xml` /
   `customTVGroups-*.xml` (the panel's "IPTV is two halves" decision — host build + in-Kodi apply).
   This is where the xtream→m3u derivation (provider 2), the groups grammar's display
   relabel + `| sort` directives, and `IPTV_<N>_FAVORITES` land (all deferred from 5b·1).

Then Phase 5b step 3 (`run_iptv(box_env)` — IPTV independently runnable on an existing Foundation)
and step 4 (gate + clean-Kodi verify). Then 5c (Add-ons layer), 5d (Guided wizard + Model A),
6 (harden + Fire TV).

---

## Build status (modular-setup branch)

- **DONE, gated, committed LOCALLY**: Phases 0–3 + 5a (Foundation, incl. 5a·2/5a·3) + **5b·1**
  (the two `apply_iptv` bugs — clobber window + N-provider env — clean-Kodi channel-load proven).
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
