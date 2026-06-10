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

## ▶ VERY NEXT STEP — the remaining queue: Phase 5b·3 (`run_iptv`), then 5d

> **Phase 5c (`run_addons`) is DONE** — taken deliberately BEFORE 5b·3 (no dependency on it);
> see the Phase 5c entry in `docs/plans/modular-setup.md`. The queue is now:
>
> 1. **Phase 5b·3 — `run_iptv(box_env)`** (next, below)
> 2. **Phase 5d — Guided wizard + Model A lifecycle** (then wire a default into the shipped `run()`)
> 3. **Phase 6 — harden + Fire TV**

**Start from the prep section: `docs/plans/modular-setup.md` → "Phase 5b·3 — PREP".** It has the
full design (mirror `run_foundation`'s shape; apply_iptv → summary → self-uninstall → ONE
restart; NO skin touch, NO install_repos; env read-once/delete-after; re-entry safe by
construction) — everything `run_iptv` needs already exists (`apply_iptv` owns its backend
install-or-fail-loud, staged-first config inside the PVR-disabled window). `run_addons` (Phase
5c) is the freshest template for the runner shape + its test file (`_tools/test_run_addons.py`).

**Acceptance bar (the standing four-part bar):** (1) unit tests incl. the no-skin-touch +
no-install_repos invariants, backend-failure summary honesty, re-entry; ≥90% new-code coverage —
(2) gate green (`pytest _tools/ -q` + `ruff` + secrets + deterministic regen) — (3) adversarial
QA review — (4) clean-**Foundation**-box live verify: fresh Kodi → `run_foundation` (skin-only,
no pvr) → stage (build_iptv + env re-push) → `run_iptv` with the real `.env.local` → backend
installed BY THIS LAYER, both providers' JSON-RPC counts match the builder's, MOD V2 still
active, survives a clean-shutdown restart (recipe: `local-kodi-verification.md` → "Verifying
PVR / IPTV state"). NOTE from the 5c live run: Kodi's `RestartApp` is a NO-OP on macOS — the
clean-quit+relaunch IS the real restart on the local box.

Context: Phase 5b·1 (clobber window + N-provider env), 5b·2 (host-side `build_iptv.py` build →
staging → staged apply; both real providers load, xtream included), the favorites-icon healing
addendum, and **Phase 5c (`run_addons` — the standalone Add-ons layer, clean-Kodi proven on a
Foundation-only box)** are all **DONE** — see the phase log. After 5b·3: 5d (Guided wizard +
Model A), 6 (harden + Fire TV).

---

## Build status (modular-setup branch)

- **DONE, gated, committed LOCALLY** (suite **677 passed / 1 xfailed**):
  Phases 0–3 + 5a (Foundation, incl. 5a·2/5a·3) + **5b·1** (the two `apply_iptv` bugs — clobber
  window + N-provider env) + **5b·2** (the host-side IPTV build integrated — BOTH real
  providers, xtream included, clean-Kodi channel-load proven with the full curation grammar) +
  the **favorites-icon healing** addendum (dead xtream placeholder icons borrowed from live
  duplicates at build time, live-proven) + **5c** (`run_addons` — the standalone Add-ons layer,
  clean-Kodi proven on a Foundation-only box; MOD V2 untouched, RSS/origins/disable-after all
  live-verified, restart-survival proven).
- **NOT PUSHED** — milestone-push pending: needs `script.module.tony7bones` + `script.tony7bones.bootstrap`
  version bumps + `--news` (modv2plus is already 1.4.8). Push the branch once 5b lands or at the next
  coherent milestone.
- The deploy gate (`_tools/test_installer_present.py`) is on **`main`**. The `iptv` branch is
  **SUPERSEDED** — its deliverables (build_iptv.py + tests + playbook) are integrated on
  `modular-setup` (Phase 5b·2, adapted to the N-provider model); **delete the branch at the
  milestone push**.

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
