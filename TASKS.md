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

## ▶ VERY NEXT STEP — Phase 5d (Guided wizard + Model A lifecycle), then 6

> **Phase 5b is COMPLETE** — 5b·3 (`run_iptv`) landed; see its phase entry in
> `docs/plans/modular-setup.md`. **All three layers are now INDEPENDENTLY RUNNABLE**
> (`run_foundation` / `run_iptv` / `run_addons` — the 5d precondition is met). The queue:
>
> 1. **Phase 5d — Guided wizard + Model A lifecycle** (the panel's keystone: the orchestrator
>    persists across gates, self-uninstall only on terminal Finish; the wizard offers the next
>    undone gate via installed-state probes; the no-fork invariant — Guided and Express drive
>    the same `apply_*`; then wire a chosen default into the shipped `run()`, today still
>    `run_express`)
> 2. **Phase 6 — harden + Fire TV** (version-guard shared modules, `assert_box_complete`, CI
>    gates, the wipe-and-run matrix on a real Stick; plus the 5b·3-recorded keep-skin race —
>    skinshortcuts' first buildxml reload can destroy the confirm and revert the skin)

Design context for 5d: `docs/plans/modular-setup.md` → "Panel-resolved decisions" #1 (Model A),
the Phase 5 row in the phase table, and the three standalone runners as the wizard's gates.
`run_addons`/`run_iptv` (Phases 5c/5b·3) are the freshest runner + test templates
(`_tools/test_run_addons.py`, `_tools/test_run_iptv.py`).

Context: Phase 5b·1 (clobber window + N-provider env), 5b·2 (host-side `build_iptv.py` build →
staging → staged apply; both real providers load, xtream included), the favorites-icon healing
addendum, **5c (`run_addons`)** and **5b·3 (`run_iptv` — clean-Foundation-box live-proven:
backend installed by the layer, both providers' JSON-RPC counts match the builder's, MOD V2
untouched, restart-survival)** are all **DONE** — see the phase log. NOTE: Kodi's `RestartApp`
is a NO-OP on macOS — the clean-quit+relaunch IS the real restart on the local box.

---

## Build status (modular-setup branch)

- **DONE, gated, committed LOCALLY** (suite **693 passed / 1 xfailed**):
  Phases 0–3 + 5a (Foundation, incl. 5a·2/5a·3) + **5b·1** (the two `apply_iptv` bugs — clobber
  window + N-provider env) + **5b·2** (the host-side IPTV build integrated — BOTH real
  providers, xtream included, clean-Kodi channel-load proven with the full curation grammar) +
  the **favorites-icon healing** addendum (dead xtream placeholder icons borrowed from live
  duplicates at build time, live-proven) + **5c** (`run_addons` — the standalone Add-ons layer,
  clean-Kodi proven on a Foundation-only box; MOD V2 untouched, RSS/origins/disable-after all
  live-verified, restart-survival proven) + **5b·3** (`run_iptv` — the standalone IPTV layer,
  clean-FOUNDATION-box proven: pvr backend installed BY the layer, both providers staged-applied,
  counts == builder's 158/47/24 + 214/100/12 + 5 favorites + 560 all, MOD V2 untouched,
  restart-survival; **Phase 5b COMPLETE — all three layers independently runnable**).
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
