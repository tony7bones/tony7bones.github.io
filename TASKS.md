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

## ▶ VERY NEXT STEP — the MILESTONE PUSH

> **Phase 6 is COMPLETE** — the computer-setup track is hardened and DONE (see the Phase 6
> entry in `docs/plans/modular-setup.md`): the keep-skin race fix (verify-then-re-assert +
> 200 ms poll + skinshortcuts quiescence; BOTH 5b·3/5d variants live-proven, incl. a FORCED
> lost-confirm → re-assert run), the library/bootstrap version guard (`SETUP_API` /
> `REQUIRED_SETUP_API`), `assert_box_complete` + the dependency-closure walk (live-passed
> in-Kodi on the Express-built box), the restart-prompt autoclose (a NEW third dialog-destroy
> window was found live: modv2plus's post-activation patch rebuild — Kodi even segfaulted —
> end state survived; the prompt is now lifetime-bounded), CI gates on this branch, and the
> standing "Express not live-proven since the rewrite" gap CLOSED with a fresh full
> unattended Express run (all 8 groups, counts == builder, POV 11 items, origins, RSS,
> self-uninstall, env consumed, `assert_box_complete` green).
>
> **The milestone push, in order:**
>
> 1. Version-bump `script.module.tony7bones` + `script.tony7bones.bootstrap`
>    (`addons/<id>/addon.xml` + news; MINOR bumps — this is a feature batch), run
>    `python3 _tools/generate_repo.py`, commit the regenerated files.
> 2. Push the `modular-setup` branch (the pre-push hook runs tests/ruff/staleness; the CI
>    workflow now gates this branch too, incl. the named invariant step).
> 3. Delete the superseded `iptv` branch at the push.
> 4. ~~Fire TV wipe-and-run matrix~~ — **DONE on the owner-authorized Bedroom box**
>    (192.168.7.84:5555, both legs: Express one-tap AND the `SETUP_MODE=guided` per-gate
>    manual-reopen walk; full evidence in the **Phase 6 addendum** in
>    `docs/plans/modular-setup.md`). It found + fixed TWO real bugs, both live re-verified
>    on the box: the SLOW-BOX keep-skin race (`activate_skin` now waits out skinshortcuts'
>    first build between re-asserts; suite **768 passed / 1 xfailed**) and the provisioner's
>    too-short 60 s self-close wait (whose fallback reboot killed the skin flush; now ~4 min).
>    The Bedroom box was left COMPLETE and working (MOD V2 patched, both IPTV providers ==
>    builder counts, video apps + origins, weather/RSS; at Home).
> 5. Owner decisions still queued: optionally document `SETUP_MODE` in `.env.device.example`
>    (a protect-hook kept the agent from adding the commented block); the no-computer-setup
>    track (Setup with no provisioner/env) is a SEPARATE follow-on plan doc.

Context: all of Phase 5 + Phase 6 are DONE — 5a (Foundation), 5b·1/2/3 (IPTV), 5c
(`run_addons`), 5d (Guided + Model A), 6 (harden). NOTE: Kodi's `RestartApp` is a NO-OP on
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
