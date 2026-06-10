# TASKS

Tracking for the Tony.7.Bones repo.

> **The modular "0-1-2" Setup is MERGED to `main` (2026-06-10) — it is the shipped production
> Setup.** Restore point for the pre-merge 3.0 one-shot state: tag `main-pre-modular-2026-06-10`.
> Full design + phase log: **`docs/plans/modular-setup.md`** (historical record).

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

## ▶ VERY NEXT STEP — N2, the on-box config collector (no-computer-setup track)

> **Phase N1.1 is COMMITTED on `no-computer-setup` (2026-06-10, unreleased — no
> version bumps; ships with the next milestone release).** The canonical device
> root is now `/storage/emulated/0/_T7B/kodi/` (layout: `backups/ iptv/ media/
repositories/ rss/ scripts/`); the old `kodi/tony.7.bones/` root is a read-only
> LEGACY fallback (read second, never written). The device-resident MASTER
> `.env.<device>` lives at the canonical root, is read with provisioner-parity
> derivation (`DEVICE_IP` dropped, `IPTV_STAGING_DIR` injected iff staged), and is
> **NEVER deleted** (wipe-and-redo forever); only the derived `tony7bones.env`
> (both roots) + the profile-local collector env are terminal-deletable. With NO
> env anywhere Setup SCAFFOLDS the comment-disabled master template
> `.env.<device-name>` at the canonical root (bundled `resources/env.device.example`,
> drift-pinned) and still opens the wizard. Provisioner push targets (env + IPTV
> staging) moved under `_T7B`; `DEVICE_FILE_COPIES` reads both roots (canonical
> first). Env-source order: derived (canonical → legacy) → masters (canonical →
> legacy, sorted) → profile-local. Gate: 830 passed / 1 xfailed, env.py + iptv.py
> 100% / default.py 98%, 3 keystone mutations killed, deterministic regen. Full
> record: the N1.1 build-log entry in `docs/plans/no-computer-setup.md`.
>
> **Phase N1 is RELEASED to `main` (2026-06-10)** — `script.tony7bones.bootstrap`
> **1.6.0** + `script.module.tony7bones` **1.3.0** (release commit `fbf4b24`, merge
> `38b9237`; proxy untouched at 2.2.1; live-verified: the 1.6.0/1.3.0 zips serve 200
> from raw `main`, the 1.5.0/1.2.0 zips 404). Auto-update impact on completed boxes:
> they will pull library 1.3.0 (an import-only change — benign); the bootstrap is not
> installed on completed boxes (it self-uninstalls). N1 = routing + env-source
> generalization: NO env anywhere →
> `run_guided({})` (the remote-only user lands in the wizard, with the
> "Install everything with defaults" one-tap escape = the exact old no-env Express);
> env present → byte-identical provisioned routing (no `SETUP_MODE` → Express,
> `SETUP_MODE=guided` → wizard); ordered env sources (`BOX_ENV_PATH` wins →
> profile-local second) with terminal deletes covering both; the provisioner now
> ABORTS pre-Setup on a failed env push. **The track's contract: THREE first-class
> delivery modes** (owner directive) — (1) adb provisioner, (2) self-contained
> user-placed env at a device env path (no adb — documented + test-pinned), (3) no
> env → the Guided wizard. Full record: the N1 build-log entry in
> `docs/plans/no-computer-setup.md`. Gate evidence: 797 passed / 1 xfailed, env.py
> 100% / default.py 98%, five keystone mutations killed, clean-Kodi live verify
> (no-env wizard render + Foundation gate walk + MOD V2 boot + hand-placed-env
> Express routing).
>
> **Next: N2 — the on-box collector v1 (prefs + weather + persistence)** per the plan:
> `setup/collect.py` (assembly/validation/persist with `SETUP_MODE=guided`), the
> first-run interview (device name → weather city loop ≤5), `_apply_core_prefs` in
> Foundation, the default RSS list as committed data, the conftest `input` queue.
> N2 needs owner answers to **Q2 (ship the RSS list as public data?)** and **Q3
> (web-server default for no-computer boxes)** — see the plan's open questions.
> Also still queued: a production-path device test (fresh provision + Setup installed
> from the live repo on `main`); optionally document `SETUP_MODE` in
> `.env.device.example` (a protect-hook kept the agent from adding the commented
> block). Pre-N1 context: the modular-setup MERGE to `main` (commit `cedab3d`,
> 1.5.0/1.2.0/1.4.8 shipped, restore tag `main-pre-modular-2026-06-10`) is recorded
> in `docs/plans/modular-setup.md`.

Context: all of Phase 5 + Phase 6 are DONE — 5a (Foundation), 5b·1/2/3 (IPTV), 5c
(`run_addons`), 5d (Guided + Model A), 6 (harden + the Fire TV matrix on the Bedroom box:
both legs, two real bugs found + fixed + re-verified — the slow-box keep-skin race and the
provisioner self-close bound; full evidence in the Phase 6 addendum in
`docs/plans/modular-setup.md`). NOTE: Kodi's `RestartApp` is a NO-OP on
macOS — the clean-quit+relaunch IS the real restart on the local box; drive wizard list
dialogs over JSON-RPC with `Input.ButtonEvent` (key-level), not `Input.Select`.

---

## Build status (modular-setup branch)

- **DONE, gated, committed LOCALLY** (suite **768 passed / 1 xfailed**):
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
  byte-identical — snapshot + `EXPECTED_NET_INSTALLED` unchanged) +
  **6** (harden — the keep-skin verify-then-re-assert fix + quiescence settle, the
  `SETUP_API` version guard, `assert_box_complete` + the closure walk with the bundled
  system-tree fix, the restart-prompt autoclose, CI gates on this branch; live-proven incl.
  a forced lost-confirm re-assert AND the fresh full Express run — the computer-setup track
  is COMPLETE) +
  **the Fire TV matrix** (Phase 6 addendum — BOTH legs on the real owner-authorized Bedroom
  Stick: the Guided per-gate manual-reopen walk incl. an accidental interrupted-run resume
  proof, and the unattended Express one-tap; found + fixed the SLOW-BOX keep-skin race in
  `activate_skin` and the provisioner's too-short self-close wait, both re-verified on the
  box; verbatim Android UX copy recorded; box left complete and working).
- **MERGED to `main` and PUSHED (2026-06-10, merge commit `cedab3d`)** — the modular Setup
  is the shipped production code: `script.module.tony7bones` 1.2.0 +
  `script.tony7bones.bootstrap` 1.5.0 + modv2plus 1.4.8 (proxy untouched at 2.2.1).
  Pre-merge restore point: tag `main-pre-modular-2026-06-10`.
- The deploy gate (`_tools/test_installer_present.py`) is on **`main`**. The superseded
  `iptv` branch (deliverables integrated in Phase 5b·2) was **deleted** — origin and local —
  at the milestone push.

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
