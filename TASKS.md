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

## ▶ VERY NEXT STEP — Phase 5b, step 3: `run_iptv(box_env)` — the standalone IPTV layer

Phase 5b·2 (the host-side IPTV build) is **DONE and clean-Kodi proven** — see the Phase 5b·2 entry
in `docs/plans/modular-setup.md`: `_tools/build_iptv.py` (99%-covered, m3u + xtream modes, full
grammar incl. relabel/`| sort`/favorites) is wired into the provisioner (build → push →
`IPTV_STAGING_DIR`), and `apply_iptv` consumes the staged curated artifacts inside the
PVR-disabled window with per-provider fallback to the 5b·1 direct-env enforce. Acceptance landed
live on a clean Kodi with the REAL `.env.local`: **BOTH providers load** — the m3u provider's
relabelled+sorted groups (**158 / 47 / 24**) AND the xtream provider, synthesized host-side via
player_api (**214 / 100 / 12** + the **5-channel 24/7 Favorites** group) — all surviving a
clean-shutdown restart. NO provider is skipped/unconfigured anymore.

Step 3 (per `docs/plans/modular-setup.md` → "Phase 5b"): **`run_iptv(box_env)`** — make the IPTV
layer independently runnable on top of an existing Foundation (install the pvr backend if missing
— it already fail-louds — + the N-provider/staged config), so a user who stopped at skin-only can
later add IPTV with no redo. Then step 4 (gate + clean-Kodi verify of the standalone runner).
Then 5c (Add-ons layer), 5d (Guided wizard + Model A), 6 (harden + Fire TV).

---

## Build status (modular-setup branch)

- **DONE, gated, committed LOCALLY**: Phases 0–3 + 5a (Foundation, incl. 5a·2/5a·3) + **5b·1**
  (the two `apply_iptv` bugs — clobber window + N-provider env) + **5b·2** (the host-side IPTV
  build integrated — BOTH real providers, xtream included, clean-Kodi channel-load proven with
  the full curation grammar).
- **NOT PUSHED** — milestone-push pending: needs `script.module.tony7bones` + `script.tony7bones.bootstrap`
  version bumps + `--news` (modv2plus is already 1.4.8). Push the branch once 5b lands or at the next
  coherent milestone.
- The deploy gate (`_tools/test_installer_present.py`) is on **`main`**. The `iptv` branch's
  deliverables (build_iptv.py + tests + playbook) are now INTEGRATED on `modular-setup`
  (Phase 5b·2, adapted to the N-provider model) — the branch itself is superseded.

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
