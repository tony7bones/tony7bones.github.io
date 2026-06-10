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

## ▶ VERY NEXT STEP — Phase 6 (harden + Fire TV)

> **Phase 5d is COMPLETE** — the Guided wizard + Model A lifecycle landed and were live-proven
> as a full multi-gate walk on a clean local Kodi (see the 5d phase entry in
> `docs/plans/modular-setup.md`): `run_guided` offers the next undone gate via the new
> installed-state probes (`tony7bones.setup.probes`), the orchestrator PERSISTS across gates
> (self-uninstall only on terminal Finish / confirmed Remove Setup), the env survives every
> gate and is consumed only by the terminal ops, and the shipped `run()` routes
> `SETUP_MODE=guided` (per-device env key — owner-vetoable mechanism, documented in the phase
> log) to the wizard while staying byte-identical Express one-tap otherwise (snapshot +
> `EXPECTED_NET_INSTALLED` unchanged). The no-fork/cadence/end-state-equivalence invariants
> live in `_tools/test_no_fork.py`.
>
> **Phase 6 — harden + Fire TV**, the queue:
>
> 1. **The keep-skin race** (5b·3-recorded, now with the 5d variant: the per-gate restart
>    PROMPT can also be destroyed by skinshortcuts' first buildxml reload) — faster confirm
>    poll / set-and-reconfirm / offline seed in the restart slot.
> 2. **Version-guard shared `script.module.*` across gates**, `assert_box_complete()` +
>    dependency-closure walk, CI gates (no-fork + idempotency + seam-guard as required checks).
> 3. **The wipe-and-run matrix on a real Fire TV Stick** — Express one-tap AND the Guided
>    manual-reopen UX (per-gate notification copy: "box is complete — reopen to continue");
>    Fire TV is where the Android restart shape is real.
> 4. Owner decisions queued: veto window on the `SETUP_MODE` env-key mechanism (alternatives:
>    timeout launch dialog / second launcher entry); optionally document `SETUP_MODE` in
>    `.env.device.example` (a protect-hook kept the agent from adding the commented block).

Context: all of Phase 5 is DONE — 5a (Foundation), 5b·1/2/3 (IPTV: clobber window, host-side
build, `run_iptv`), 5c (`run_addons`), 5d (Guided + Model A). NOTE: Kodi's `RestartApp` is a
NO-OP on macOS — the clean-quit+relaunch IS the real restart on the local box; drive wizard
list dialogs over JSON-RPC with `Input.ButtonEvent` (key-level), not `Input.Select`.

---

## Build status (modular-setup branch)

- **DONE, gated, committed LOCALLY** (suite **733 passed / 1 xfailed**):
  Phases 0–3 + 5a (Foundation, incl. 5a·2/5a·3) + **5b·1** (the two `apply_iptv` bugs — clobber
  window + N-provider env) + **5b·2** (the host-side IPTV build integrated — BOTH real
  providers, xtream included, clean-Kodi channel-load proven with the full curation grammar) +
  the **favorites-icon healing** addendum (dead xtream placeholder icons borrowed from live
  duplicates at build time, live-proven) + **5c** (`run_addons` — the standalone Add-ons layer,
  clean-Kodi proven on a Foundation-only box; MOD V2 untouched, RSS/origins/disable-after all
  live-verified, restart-survival proven) + **5b·3** (`run_iptv` — the standalone IPTV layer,
  clean-FOUNDATION-box proven: pvr backend installed BY the layer, both providers staged-applied,
  counts == builder's 158/47/24 + 214/100/12 + 5 favorites + 560 all, MOD V2 untouched,
  restart-survival; **Phase 5b COMPLETE — all three layers independently runnable**) +
  **5d** (the Guided wizard + Model A lifecycle — `run_guided` + `tony7bones.setup.probes` +
  the `SETUP_MODE=guided` routing in the shipped `run()`; the full multi-gate walk live-proven
  on a clean local Kodi: per-gate restarts each landing on a complete working box, Setup
  persisting across gates, env consumed only at Finish, Finish self-uninstall; the
  no-fork/cadence/end-state-equivalence invariants in `_tools/test_no_fork.py`; Express
  byte-identical — snapshot + `EXPECTED_NET_INSTALLED` unchanged).
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
