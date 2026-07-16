# Plan - Modular "0-1-2" Setup (Foundation / IPTV / Add-ons)

> Status: **MERGED TO `main` - SHIPPED PRODUCTION (2026-06-10, merge commit `cedab3d`,
> owner-decided). Phases 0-6 DONE incl. the Fire TV matrix; all three layers are
> INDEPENDENTLY RUNNABLE (`run_foundation` / `run_iptv` / `run_addons`), the **Guided
> wizard + Model A lifecycle** (`run_guided`, env-keyed `SETUP_MODE=guided` routing in
> the shipped `run()`, Express unchanged) are live-proven. Shipped versions:
> `script.module.tony7bones` 1.2.0, `script.tony7bones.bootstrap` 1.5.0, modv2plus
> 1.4.8; proxy untouched at 2.2.1. The pre-merge 3.0 one-shot `main` is tagged
> `main-pre-modular-2026-06-10` (restore point).
> NEXT = a production-path device test, then the no-computer-setup track (separate plan
> doc; awaiting the six owner answers → N1).** Design was panel-reviewed in parallel by three specialist agents
> (Architecture, QA/testability, Kodi-runtime); this doc is the orchestrated synthesis
> PLUS the running phase log. The design sections below are kept as written (the
> contract); current truth lives in the **Phase log** and the **Phase 5b** section at
> the end.

## Goal

Re-architect the Tony.7.Bones Kodi setup from a **monolithic one-shot** into a **modular,
layered, opt-in installer**. Today `script.tony7bones.bootstrap/default.py` `run()` is a
~55-line procedure that installs everything (repos + apps + curated video + skin + config)
in one unattended shot, restarts once, and self-uninstalls. We want three independent
layers where **each leaves a complete, working box** and the user can stop or continue at
each gate - driven by the same modules whether run as a Guided wizard or an Express one-shot.

## The 0-1-2 model

| Layer | Name                 | Contents                                                                                                                                                              | Stop here =                                 |
| ----- | -------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------- |
| **0** | **Foundation**       | Kodi + Estuary MOD V2 skin + modv2plus patch (+ the skin's required dep closure: `script.module.pvr.artwork`, skinshortcuts, image.resource.select, Outline-HD icons) | A pristine, branded Kodi - **zero content** |
| **1** | **IPTV** (opt-in)    | `pvr.iptvsimple` + inputstream clients + `.env`-driven instances                                                                                                      | Branded Kodi + _your_ live TV               |
| **2** | **Add-ons** (opt-in) | curated repos + base apps + video add-ons (POV, Loop, Sports HD, YouTube) + weather/RSS                                                                               | The full box                                |

Each layer is its own complete box; the next is purely additive.

## Core principles

- **Modules are the single source of truth.** Three re-entrant functions live in the shared
  library `script.module.tony7bones`: `apply_foundation`, `apply_iptv`, `apply_addons`.
  **Both** the Guided wizard and the Express one-shot call the _same_ functions - no forked
  install logic, ever.
- **Restart-as-seam - and it's actually "activate-skin-then-restart" as one
  orchestrator-owned terminal operation.** Modules do work but never restart and never
  activate the skin. The orchestrator owns cadence: **Guided** restarts after each gate;
  **Express** defers, sets `lookandfeel.skin` **last**, and restarts **once** at the end.
  (Activation is part of the seam because setting the skin too long before the restart
  re-triggers Kodi's "Keep this skin?" revert to stock.)
- **Re-entrancy via installed-state, not marker files.** Each module detects what's already
  done and no-ops it; the box's actual state _is_ the resume state. Lean on the existing
  idempotency (`is_installed` short-circuits, `_add_file_sources` dedupes,
  `_ensure_iptv_custom_tv_groups` writes-only-if-changed).

## Module contract

A small shared result type lets modules **request** terminal operations the orchestrator
**decides**:

```python
class LayerResult:
    layer            # "foundation" | "iptv" | "addons"
    ok               # reached a complete state? (success/degraded - orchestrator checks BEFORE restarting)
    already_done     # re-entry no-op'd everything
    installed        # {addon_id: state}
    failed           # {addon_id: reason}
    needs_skin_activation  # foundation sets this - a REQUEST
    needs_restart          # a REQUEST; orchestrator owns the actual restart
```

```python
def apply_foundation(env, *, dialog=None, log) -> LayerResult   # skin closure + modv2plus + file-sources + home-trim; NO content, NO PVR; sets needs_skin_activation
def apply_iptv(env, *, dialog=None, log) -> LayerResult         # install pvr.iptvsimple closure + write/enforce instance-settings-N.xml (N providers)
def apply_addons(env, *, dialog=None, log) -> LayerResult       # curated repos/apps/video + origin stamp + install-then-disable + weather/RSS
```

- **`env` is passed in, never read inside a module.** The orchestrator reads the per-device
  env once, passes the dict down, and owns the **read-then-delete** - deleting only after
  the _last_ layer of the session (today `_configure_box` deletes it mid-run, which would
  starve a later gate in a multi-session Guided flow).
- **Idempotency detection** per layer (all primitives already exist):
  - Foundation: `is_installed(SKIN_ID)` + `is_installed(MODV2PLUS_ID)` + skin enabled; _activated_ = `getSkinDir()==SKIN_ID`.
  - IPTV: `is_installed("pvr.iptvsimple")` + instance-settings keys already correct (file check - **not** a populated channel list, which is async).
  - Add-ons: per-id `is_installed(aid)` + non-blank origin.

## Panel-resolved decisions

These were independently surfaced and converged on by ≥2 of the three lenses:

1. **Self-uninstall lifecycle - the keystone (all three flagged as #1 blocker).** A
   self-deleting one-shot cannot support multi-gate/resume - delete after Gate 0 and there's
   no body to run Gate 1. **Resolution (Model A for v1):** the orchestrator add-on _persists_
   across gates (its home tile _is_ the "continue setup" affordance) and self-uninstalls
   **only** on terminal Finish / completing the last layer. **Express** keeps today's clean
   end-of-run self-uninstall; **Guided** keeps the add-on and offers an explicit "Remove
   Setup." The shared library (`xbmc.python.module`, invisible) is **always** left installed.
   _v2 polish:_ Model C - a tiny permanent boot service surfaces a "Continue setup"
   notification after reopen (reuses the proven modv2plus service pattern), letting the
   heavy orchestrator stay transient.
2. **`pvr.iptvsimple` moves from Foundation (Layer 0) into `apply_iptv` (Gate 1).** Today
   it's in the base `ADDONS` - so Layer 0 isn't actually content-free until it moves. This
   creates a deliberate cross-gate dependency: `apply_iptv` must install its own PVR backend
   (or fail loudly), never silently write instance-settings for a missing add-on.
3. **IPTV is two halves.** The host-side **build** (`build_iptv.py` on the `iptv` branch:
   fetch from provider portals, curate groups/favorites, m3u vs xtream modes) belongs in the
   **provisioner**, upstream of Setup - it needs provider creds and runs on the Mac. The
   in-Kodi **apply** (`apply_iptv`) is the thin consumer: install the PVR backend + write/
   enforce the staged `instance-settings-N.xml` + `customTVGroups-*.xml`. Generalize the
   apply side to **N providers** (today it's hard-wired to instance-1/Network24).
4. **Express is the Fire TV default; Guided is the advanced/power path.** Kodi can't
   self-restart on Android - every gate restart is a manual close+reopen. Express = **one**
   reopen; Guided = up to **three**. Each gate's reopen must land on a _complete, working
   box_ so it never reads as "did it freeze?"
5. **Per-gate install ritual stays intact, not collapsed.** Each add-on-installing gate does
   its own direct-extract (proxy/GitHub-only deps first) → `UpdateLocalAddons` → 3s settle →
   enable → enable source repos → stamp origins → restart. Plus a **version-guard**: skip
   extracting a shared `script.module.*` when the installed version ≥ the resolved version,
   so a later gate can't clobber Foundation's working module with an older shadow.

## Build approach - Hybrid (adversarial-review verdict)

A second, **adversarial** architecture pass was run specifically to steelman a from-scratch
"white canvas" rebuild and find what the current base genuinely costs. Verdict: **hybrid -
fresh orchestrator + fresh module boundaries, reusing the proven engine verbatim.** Not full
greenfield (it re-pays hardware-proven debts for no engine-layer gain); not pure
decompose-in-place (it would graft a resumable wizard onto a self-deleting host).

**The exact line - what we keep, refactor, and write fresh:**

| Code                                                                                        | Disposition                                                                               | Why                                                                                                                                             |
| ------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------- |
| `net.py`, `index.py`, `install.py`, `repos.py`, `system.py`                                 | **Reuse as-is**                                                                           | Hardware-earned engine. `install_selection` is _already_ the module contract. `activate_skin`/`restart_kodi` encode blood-bought Fire TV fixes. |
| install/config bodies (`_install_*`, `_configure_box` writers, `parse_env`/`read_box_env`)  | **Reuse-but-refactor** → move into `apply_foundation/iptv/addons` returning `LayerResult` | Correct + idempotent already; only their home and the env-ownership are wrong.                                                                  |
| `run()` tail (summary, self-uninstall placement, activate+restart ordering, single cadence) | **Write fresh** as the orchestrator seam + state machine                                  | The only genuinely wrong-shaped code (~55 lines).                                                                                               |
| orchestrator add-on, `LayerResult`, done-probes, cadence/lifecycle/resume                   | **Write fresh**                                                                           | Net-new; no legacy to preserve.                                                                                                                 |
| fake-Kodi `boot` fixture                                                                    | **Reuse-but-relocate** → `conftest.py`                                                    | Keystone test asset; extract, don't rebuild.                                                                                                    |

**Steal greenfield's one real win - a `KodiHost` port** (an interface wrapping the `xbmc*`
calls) **for the NEW code only**: the orchestrator + layer modules get plain
constructor-injected fakes (retiring the fragile `sys.modules` monkeypatch for new code),
while the proven engine keeps its existing, already-tested harness. One real upgrade, zero
churn to proven code.

**Discipline:** rebuild the lifecycle (Model A persistence + env-ownership) **before** Guided
ships - never graft a resumable wizard onto a self-deleting host. Target sublibrary layout:
`script.module.tony7bones/lib/tony7bones/setup/` (`result.py`, `foundation.py`, `iptv.py`,
`addons.py`, `probes.py`, `env.py`, `host.py`) + a fresh `script.tony7bones.bootstrap`
orchestrator (`default.py` state machine + `service.py` resume nudge). The migration sequence
below is sequenced so every step stays green and the lifecycle is rebuilt before any Guided
release.

## Key risks & mitigations

| Risk                                          | Lens           | Mitigation                                                                                                              |
| --------------------------------------------- | -------------- | ----------------------------------------------------------------------------------------------------------------------- |
| Self-delete kills resume                      | all            | Model A: persist orchestrator until terminal Finish                                                                     |
| Skin reverts (timeout) if activated too early | Arch, QA, Kodi | Orchestrator sets `lookandfeel.skin` LAST before restart, both cadences; assert no step runs between activate + restart |
| env deleted mid-run starves later gates       | Arch, QA       | Orchestrator owns read-then-delete; delete only after last layer of session                                             |
| Partial state (extracted-but-not-enabled)     | QA, Kodi       | Test half-state recovery; real-box verify; forward-only "rollback = run again"                                          |
| IPTV async channel sync read as failure       | Kodi           | Done-marker = instance-settings written+enabled; channel count is informational only                                    |
| Swallowed `except` → restart into broken box  | QA             | Each module returns success/degraded; orchestrator checks `ok` BEFORE restarting a gate                                 |
| Cross-gate shared-module clobber              | Kodi           | Version-guard on shared `script.module.*`                                                                               |
| Proxy-invisible deps (pvr.artwork)            | Kodi           | `apply_foundation` direct-extracts before closure resolve (as today)                                                    |
| "Complete box" is a slogan not a check        | QA             | `assert_box_complete()` + dependency-closure-completeness walk per layer                                                |

## Test strategy (QA lens)

- **`conftest.py` shared harness** - extract the `boot` fake-Kodi fixture from
  `test_bootstrap.py` into a reusable fixture (keystone for all modular tests).
- **Characterization golden snapshot** of the current `run()` before any refactor, as the
  "Express must reproduce the monolith" oracle.
- **Idempotency tests per module** - run twice; assert written files are **byte-identical**
  and zero new `.zip` fetches on the second run (current tests check counts, not bytes).
- **`test_no_fork.py`** - inject module spies; assert Guided and Express drive the _identical_
  `(module, args)` sequence; assert Guided = per-gate restart, Express = exactly one.
- **Seam-guard test** - grep each module for `RestartApp`/`Quit`/`restart_kodi` → assert
  absent (restart lives only in the orchestrator).
- **`assert_box_complete(state, layer)`** post-conditions, incl. a dependency-closure walk
  (no dangling required import after any layer).
- **Partial-state recovery tests** - pre-seed extracted-but-not-installed / installed-subset.
- **Wipe-and-run matrix on real hardware** (mocks can't see skin-revert, async PVR sync,
  proxy-invisible deps, GL-wedge from rapid restarts): Foundation-only, +IPTV, +Add-ons,
  Express all-in-one, re-entrancy (run a layer twice), resume-after-interrupt; verify
  "Express end-state == cumulative Guided end-state" by diffing `Addons33.db`.

## Refactor sequence (keep the suite green at every step)

1. **Pin** current behavior with the characterization snapshot test.
2. **Extract** `_install_base`/`_install_skin`/`_install_video`/`_configure_box` bodies into
   library modules with **zero logic change** (re-export shims keep current tests green).
3. **Introduce** the orchestrator + `LayerResult`; `run()` becomes `run_express()`; assert
   the golden snapshot still matches.
4. **Add** `run_guided()` (wizard probes installed-state, offers next undone gate); write the
   no-fork + per-gate-restart tests.
5. **Only then** make behavior changes (opt-in gating, move `pvr.iptvsimple` to Gate 1, env
   ownership move, N-provider IPTV) - each behind its own failing-then-passing test.

## Action backlog

**P0 - confirm/unblock before any module split**

- [ ] **Confirm Model A** self-uninstall lifecycle (orchestrator persists; uninstall only on Finish). _(Arch, Kodi)_
- [ ] Move env **read-then-delete** out of `_configure_box` into the orchestrator. _(Arch, QA)_
- [ ] Move `pvr.iptvsimple` + inputstream closure from Foundation `ADDONS` into `apply_iptv`. _(Arch, QA, Kodi)_
- [ ] Encode the **activate-skin-is-last-before-restart** invariant (both cadences) + a test. _(Arch, Kodi)_
- [ ] `conftest.py` shared fake-Kodi harness + characterization golden snapshot of `run()`. _(QA)_

**P1 - the decomposition**

- [ ] Add `LayerResult` + `apply_foundation`/`apply_iptv`/`apply_addons` to the library (behavior-preserving extraction). _(Arch)_
- [ ] Refactor `run()` → `_orchestrate(layers, env, cadence)`; Express = the existing tail generalized. _(Arch)_
- [ ] Add the Guided entry point (installed-state resume probe + next-undone-gate wizard). _(Arch, Kodi)_
- [ ] `test_no_fork.py` + per-gate-restart placement test; seam-guard grep test. _(QA)_
- [ ] Per-module idempotency byte-equality tests; `assert_box_complete` + closure walk. _(QA)_
- [ ] Done-state probe library fns - `foundation_done()/iptv_applied()/addons_done()` sharing modv2plus's `_is_applied/_menu_is_ours/_settings_applied`; tolerate "applied but async-in-progress." _(Kodi)_

**P2 - IPTV gate composition (depends on the `iptv` branch)**

- [ ] Land `build_iptv.py` into the **provisioner** (host-side build), not the add-on; port `test_build_iptv.py` to main. _(Arch, QA)_
- [ ] Generalize `apply_iptv` / `_ensure_iptv_custom_tv_groups` to **N instances** (loop providers). _(Arch, Kodi)_
- [ ] Cross-gate dependency test: `apply_iptv` with no `pvr.iptvsimple` → self-install or loud fail, never silent. _(QA, Kodi)_
- [ ] IPTV done-detection = instance-settings written+enabled (not channel count). _(Kodi)_

**P3 - guardrails & hardware**

- [ ] Version-guard shared `script.module.*` across gates (skip if installed ≥ resolved). _(Kodi)_
- [ ] Per-gate notification copy: "box is complete - reopen to continue." _(Kodi)_
- [ ] CI gate: no-fork + per-module idempotency + seam-guard as required checks. _(QA)_
- [ ] Wipe-and-run matrix doc (extend `local-kodi-verification.md`); mandatory before any modular release. _(QA, Kodi)_
- [ ] Evaluate **Model C** resume-service for v2. _(Kodi)_

## Open decisions for the owner

1. **Model A confirmed for v1?** (orchestrator persists, self-uninstall only on Finish; Model C as v2 polish) - panel strongly recommends yes.
2. **Express as Fire TV default, Guided as advanced?** - panel recommends yes.
3. **Sequencing:** merge the `iptv` branch (`build_iptv.py`) to `main` _before_ the IPTV gate work, or keep it parallel and integrate at P2? (P0/P1 don't need it; P2 does.)

## Dependencies

- The IPTV gate (P2) consumes the `iptv` branch's `build_iptv.py` + `test_build_iptv.py` and
  the customization playbook. P0/P1 are independent of it.
- The orchestrator-owned terminal seam relies on the proven `system.py` primitives
  (`activate_skin` w/ the 10100/control-11 accept, `restart_kodi`, `self_uninstall`).

## Execution plan & phase gate

Build proceeds in **sequential, gated phases** - each phase builds on the prior phase's
committed result, so phases do NOT run in parallel (that's what keeps the suite green at
every step). Parallelism happens **within** a phase: the orchestrator fans out agents
(implementer + test-author + an adversarial QA test-completeness reviewer) on independent
pieces, integrates them, runs the gate, and commits. (These execution **phases** are the
delivery order; the P0-P3 tags in the Action backlog are priority/owner labels scheduled
into them.)

### Phase Gate - Definition of Done (every phase)

1. **Documented** - this plan / a phase-log updated: what changed, why, what's now true.
2. **Thoroughly tested** - unit tests for all new/changed code; idempotency tests where
   re-entrant; invariant tests (no-fork, seam-guard) where applicable; pure refactors pinned
   against the characterization golden snapshot.
3. **Coverage** - new modules ≥ 90% line coverage (the bar `build_iptv.py` hit), with a
   `--cov term-missing` report and every uncovered line justified.
4. **Green everywhere** - full `pytest _tools/ -q` + `ruff` + generated-files staleness +
   the pre-push gate all pass.
5. **Real-device check** - phases that change runtime behavior are wipe-and-run verified on
   the **local Kodi 21.3 Omega** (JSON-RPC `127.0.0.1:8080`). The Mac Kodi faithfully covers
   skin install/activation + "Keep this skin?" revert, dependency-closure installs, origin
   stamping, instance sync, and idempotency. It does **not** cover Fire-OS-only behavior
   (desktop Kodi _can_ self-restart; Android can't) - the manual-reopen UX and scoped-storage
   paths get a final **real Fire TV** pass before any release.
6. **Checked in** - committed + pushed with a phase-tagged message before the next phase opens.
7. **QA completeness review** - an adversarial QA agent reviews each gate for what the tests
   _miss_ before the phase is accepted.

### Phases

| Phase           | Deliverable                                                                                 | Runtime change? → device gate               |
| --------------- | ------------------------------------------------------------------------------------------- | ------------------------------------------- |
| **0**           | Extract `boot` fixture → `conftest.py`; characterization golden-snapshot of current `run()` | none - snapshot + unit only                 |
| **1**           | Lift `env` read-then-delete into orchestrator ownership                                     | none                                        |
| **2**           | `apply_foundation/iptv/addons` + `LayerResult` + `KodiHost` port (behavior-preserving)      | none                                        |
| **3**           | Move `pvr.iptvsimple` → Gate 1 (first intentional behavior change)                          | yes → local Kodi                            |
| **4**           | Fresh orchestrator + Express path (releasable end-state == monolith)                        | yes → local Kodi                            |
| **5**           | Model A lifecycle + Guided + invariants (no-fork, seam-guard, idempotency)                  | yes → local Kodi (+ Fire TV for restart UX) |
| **6**           | Harden: version-guard, `assert_box_complete`, CI gates, wipe-and-run matrix                 | yes → local Kodi + Fire TV                  |
| _(7, deferred)_ | IPTV gate composition (provisioner build + N-provider apply)                                | needs `iptv` merge first                    |

### ⛔ THE WORKING AGREEMENT (non-negotiable - read before touching code)

**The strict per-phase order - never skip, never reorder:**

> **implement → TEST → COVERAGE → GATE (full suite + ruff + secrets green) → QA completeness
> review → real-device verify (if runtime) → DOCUMENT → only THEN commit → only THEN start the
> next phase.**

Two hard rules that have held for every phase 0-5a and MUST continue:

1. **NO COMMIT until ALL gate items pass.** Tested + coverage (≥90% new code, justified) + green
   everywhere + QA review accepted + (runtime →) clean-Kodi verified + documented. A red suite, a
   missing test, an unreviewed change, or an undocumented phase = **do not commit.**
2. **NO next phase until the current phase is committed green.** Phases are sequential-gated; the
   next phase builds on the prior phase's committed result. Never start N+1 with N uncommitted or red.

Every phase also gets an **adversarial QA completeness review** (a separate agent hunting what the
tests _miss_) - its findings are closed _before_ the commit, not deferred. This is how phase 0's
silent-rebaseline footgun, phase 2b's tech-debt seam, phase 3's equivalence proof, and phase 5a's
zero-content guarantee were all caught pre-commit.

Per-phase loop: **brief parallel agents → integrate → run the gate → QA completeness review → close
gaps → commit → next phase.**

## Phase log

Every phase records all four gate facts here when accepted: **tested · gated · coverage ·
documented**.

### Phase 0 - DONE (`test(modular-setup): Phase 0 …`)

- **Landed:** `_tools/conftest.py` (the fake-Kodi `boot` fixture extracted from
  `test_bootstrap.py` - verified byte-equivalent, now reusable by all modular tests);
  `_tools/test_modular_setup.py` + `modular_setup_snapshot.json` - the characterization
  oracle (`bare` + `full` snapshots) pinning the current `run()`'s install/enable order,
  the activate-skin-**last** cadence, and - at **runtime**, not source-grep - the restart,
  self-uninstall, and cancel-path wiring.
- **What's now true:** there is a behavior oracle that every later phase is checked against
  ("Express must reproduce the monolith"). It is hardened against silent self-rebaseline
  (writes only under `UPDATE_SNAPSHOT=1`; refused when `CI` is set; a missing key fails loud).
- **Tested:** 7 oracle tests incl. runtime restart/self-uninstall/cancel/skin-last
  invariants, all **mutation-verified** (removing a call from `run()` fails the matching test).
- **Gated:** full suite **383 passed / 1 xfailed**, `ruff` clean, zero `addons/**` change,
  pre-push gate green, pushed.
- **Coverage:** new-production-module ≥90% criterion **N/A** (Phase 0 added no production
  module - test infra + oracle only). Recorded oracle reach instead: the characterization
  test alone exercises **58%** of `bootstrap/default.py`; the full bootstrap suite reaches
  **89%**. Unpinned lines = the env-driven IPTV/RSS + device-copy branches that are guarded
  no-ops on a desktop no-env run - exercised in the later phases that touch them.
- **Adversarial QA review:** caught + closed GAP 1 (silent-rebaseline footgun), GAP 2
  (restart/self-uninstall wiring invisible to the oracle), GAP 4 (cancel path), GAP 3
  (docstring overclaim). All fixes mutation-verified.
- **Deferred/noted:** pre-existing `repository.diggz` vs `repository.diggz.zip` double-enable
  quirk (faithfully pinned, do not "fix" without updating the snapshot); env-driven branch
  coverage rises as Phases 1-3 touch those paths.

### Phase 1 - DONE (local commit; behavior-preserving)

- **Landed:** the per-device `.env` read-then-delete lifted OUT of `_configure_box` INTO the
  orchestrator `run()`. `_configure_box(box_env=None)` is now a pure consumer - it never reads
  or deletes the env file; `run()` reads once, passes the dict in, deletes after configure.
- **What's now true:** a single coordinator owns env lifecycle - the prerequisite that lets a
  future multi-session Guided flow run a later gate without an earlier gate having deleted the
  env it needs.
- **Tested:** 5 new/changed tests; **mutation-verified** - 3 mutations killed incl. the subtle
  "delete-before-configure" (runtime ordering assertion) and "delete-removed"; remove-spies
  path-scoped to `BOX_ENV_PATH` so they don't false-trip on `run()`'s other `os.remove` calls.
- **Gated:** Phase 0 characterization snapshot passes **UNCHANGED** (behavior-preserving);
  387 passed / 1 xfailed; `ruff` clean.
- **Coverage:** `bootstrap/default.py` 89% → **92%**; env-ownership logic covered; only
  uncovered new line is a pre-existing defensive `except OSError: pass`.
- **QA completeness review:** ACCEPTABLE - no blocking gaps (2 optional nits noted).
- **Push/version:** committed locally; generated zip/`addons.xml` not regenerated and version
  not bumped - deferred to a milestone push (see Execution notes) to avoid advertising an
  unfinished feature in the user-visible version.

### Phase 2a - DONE (local commit; scaffolding, behavior-preserving)

- **Landed:** the `tony7bones/setup/` sublibrary - `result.py` (`LayerResult`), `host.py`
  (`KodiHost` port + `RealKodiHost`, lazy method-level delegation), `env.py` (env parsing
  relocated VERBATIM out of `default.py`). `default.py` now imports the env funcs from there
  (re-export, identity-verified). **`tony7bones/__init__.py` made lazy** (PEP 562
  `__getattr__`) so the engine is no longer eagerly imported.
- **What's now true:** the module-contract primitives exist, and the engine is
  **import-decoupled** - `import tony7bones.setup.host/env/result` works with **no xbmc**
  (proven by blocking `xbmc` at the import meta-path), while the engine still lazily requires
  Kodi on use. So the `apply_*` layers (2b/c/d) can be unit-tested via plain fake-`KodiHost`
  injection - no `sys.modules` xbmc monkeypatching.
- **Tested:** `_tools/test_setup_lib.py` (incl. off-box-import + commented-out-`KEY=value`
  guard tests); mutation-verified. **Gated:** snapshot UNCHANGED; 424 passed / 1 xfailed;
  ruff clean. **Coverage:** `setup/` **100%**.
- **QA completeness review:** ACCEPT; closed - commented-out-key guard test, real off-box
  decoupling (lazy `__init__`), port-growth note, tautology fix.
- **2b input:** the `KodiHost` port grows **test-driven** in 2b (it'll gain
  `dialog`/`progress`/`getAddonInfo`(version)/settings accessors as the layers need them).

### Phase 2b - DONE (local commit; Foundation extraction, behavior-preserving)

- **Landed:** `setup/foundation.py` with `apply_foundation(env, *, dialog=None, log) -> LayerResult` -
  the bodies of `_install_skin` (skin closure + pvr.artwork/modv2plus direct-extract-before-resolve;
  does NOT set `lookandfeel.skin`), `_add_file_sources`, `_trim_home_menu` (Skin.SetBool + settings.xml
  belt-and-suspenders) MOVED verbatim. `default.py` keeps thin shims; `run()` calls `apply_foundation`
  in the same slot and uses `foundation.ok` exactly as it used `_install_skin`'s bool (skin still
  activated LAST).
- **Tested:** `_tools/test_setup_foundation.py` (12 tests), mutation-verified (move modv2plus
  extract after closure → caught; drop file-sources → caught; flip needs_skin_activation → caught).
  Deleted the now-misplaced `test_install_skin_imports_is_installed` grep guard (it guarded
  `default.py` but the footgun moved to `foundation.py`, where the behavioral tests cover it).
- **Gated:** snapshot UNCHANGED; full suite green; ruff clean. **Coverage:** `foundation.py` **95%**
  (uncovered = pre-existing defensive branches lifted verbatim + one unreachable guard).
- **QA review:** ACCEPT (one fix-first = the grep test, done).

#### Tech-debt ledger (opened in 2b - settle before/at the Phase 4 orchestrator)

- **`deps`-injection seam** (`_SkinDeps`/`_BootSkinDeps` + `install_skin=/add_file_sources=/trim_home_menu=`
  params): a TRANSITIONAL test-compat mechanism so `run()`-driven tests that patch `boot.mod.*`
  primitives still take effect through the moved bodies. **Do NOT proliferate it to 2c/2d** -
  prefer repointing the few legacy `boot.mod.*` unit-test patches at the new module. The Phase 4
  orchestrator calls the **bare 3-arg** form (`apply_foundation({}, dialog, log)`, default `_SkinDeps`,
  no injection). **Kill the seam** once `run()` is fully decomposed.
- **`log` param dormant** - `apply_foundation` ignores it (logs via its module logger); wire layer
  logging when the orchestrator is built.
- **`already_done` not populated** by foundation (always implies fresh); populate when the
  orchestrator reads it for re-entry. 2c/2d must not cargo-cult always-False `already_done`.

### Phase 2c - DONE (local commit; Add-ons extraction, behavior-preserving)

- **Landed:** `setup/addons.py` - `_install_base`, `_install_video` (incl. dailymotion
  install-then-disable), and the WEATHER + RSS env-writers from `_configure_box`, MOVED
  verbatim, plus a composed `apply_addons(env) -> LayerResult` (built + self-tested but NOT
  yet called by `run()` - reserved for the Phase-4 orchestrator). IPTV parts of
  `_configure_box` (`_ensure_iptv_custom_tv_groups`, `_copy_device_files`) left in
  `default.py` for Phase 2d.
- **Interleaving preserved exactly:** `run()` still calls base/video install EARLY and
  weather/RSS LATE (in `_configure_box`); the weather→copy→iptv→rss order is byte-identical.
- **No deps-seam** (ledger honored): repointed the run()-driven test patches from `boot.mod.*`
  to `boot.mod._addons.*`. **Oracle integrity proven** - Mutation D (removing the new patches)
  breaks the snapshot, confirming `run()` genuinely routes install through the moved bodies;
  A/B/C (drop a repo / app / disable-after) all trip the golden snapshot.
- **Tested:** `_tools/test_setup_addons.py` (27 tests), mutation-verified. **Gated:** snapshot
  UNCHANGED; 462 passed; ruff clean. **Coverage:** `addons.py` **99%** (3 uncovered =
  defensive branches lifted verbatim from the monolith). **QA review:** ACCEPT.

#### Ledger update (already_done semantics - settled the 2b open item)

- `LayerResult.already_done` as a layer can compute it = **"no work was CONFIGURED"** (empty
  install lists), **NOT "the box is already provisioned"** - install primitives can't tell
  already-present from freshly-installed, so on a real re-entry `installed` is full and
  already_done is False. **Real re-entry detection is the Phase-4 orchestrator's
  installed-state probes** (`is_installed`/instance-settings/origin checks), NOT this field.
  Docstring + test reworded honestly; do not build idempotence on `already_done`.

### Phase 2d - DONE (local commit; IPTV-config extraction → Phase 2 decomposition COMPLETE)

- **Landed:** `setup/iptv.py` - `_ensure_iptv_custom_tv_groups` (+ `_set_instance_setting` +
  instance-settings constants) and `_copy_device_files`/`_copy_one_device_file`/`DEVICE_FILE_COPIES`
  MOVED verbatim, plus composed `apply_iptv(env) -> LayerResult` (not called by `run()` - Phase-4).
  `pvr.iptvsimple` INSTALL deliberately stays in base `ADDONS` (its move to the IPTV gate is the
  **Phase 3** behavior change). `_configure_box` keeps the exact weather→copy→iptv→rss order.
- **No deps-seam** (ledger honored); repointed 2 list-binding patches to `iptv.*`.
- **Highest-stakes checks PASS (mutation-proven):** the `tvGroupMode=2`-only-with-groups-file gate
  (the "empty channel list" regression) is intact; **secret safety** - m3u/epg creds are never
  logged (only `bool(...)`), no real creds in module/tests (fakes only), instance XML lands only in
  userdata.
- **Review-fix:** `apply_iptv`'s change-detection was a false-negative on a device-copied box
  (`existed_before` inference); fixed so `_ensure_iptv_custom_tv_groups` returns a truthful "wrote?"
  signal that `apply_iptv` consumes - fixed BEFORE Phase-4 wiring, mutation-verified.
- **Tested:** `_tools/test_setup_iptv.py` (33 tests). **Gated:** snapshot UNCHANGED; 495 passed;
  ruff clean; secrets clean. **Coverage:** `iptv.py` **100%**. **QA review:** ACCEPT.

---

## Phase 2 COMPLETE - the decomposition

`run()`'s install/config logic is now extracted into the `tony7bones/setup/` sublibrary:
`foundation.py` (95%), `addons.py` (99%), `iptv.py` (100%), on `result.py`/`host.py`/`env.py`
(100%). Each layer has a composed `apply_*(env) -> LayerResult` (built + self-tested, NOT yet
called by `run()`). `default.py` is now thin shims; behavior is **byte-identical** (the
characterization snapshot never moved across 2a-2d). 495 tests green. **Next: Phase 3** - the first
deliberate behavior change (move `pvr.iptvsimple` install Foundation→IPTV gate).

### Phase 3 - DONE (local commit; Express orchestrator + first deliberate behavior change)

- **Landed:** `run()` → **`run_express(box_env)`** composing `apply_addons → apply_foundation →
apply_iptv` as units (the Express orchestrator). `pvr.iptvsimple` INSTALL moved from base
  `ADDONS` into `apply_iptv` (`_install_pvr_backend`, **install-or-fail-loud** - never configure a
  missing backend). `apply_addons` now owns the weather/RSS core settings.
- **First DELIBERATE snapshot change - justified by a net-installed-SET equivalence proof:** the
  full run installs the byte-identical SET of add-ons as the old monolith (pvr.iptvsimple +
  inputstream still installed, via `apply_iptv` now); ONLY the operation ORDER (interleaved→layered)
  and the summary text (`Apps 4/4→3/3` + `IPTV: installed`) changed. `lookandfeel.skin` still LAST,
  all home-trim bools present. Pinned by a permanent FROZEN-constant invariant
  `MONOLITH_NET_INSTALLED` (mutation-proven, derived from the OLD committed snapshot - NOT circular),
  independent of the regen-able snapshot.
- **L1 resolved (reviewer flag):** IPTV is **deliberately non-blocking** - a pvr-backend install
  failure does NOT abort the end-of-setup restart (matches the monolith: install failures were
  always non-fatal). The fail-loud contract is at the LAYER (no half-config written); the box still
  completes setup.
- **Tested:** 515 passed; new fail-loud, net-set-equivalence, and `run_express` orchestration tests
  (skin-last, self-uninstall-after-summary, env read-once-delete-after) - all mutation-verified; the
  source-grep flow tests converted to RUNTIME spies. **Coverage:** iptv 100%, addons 99%, foundation
  93%, default.py 95%. **QA review:** ACCEPT (equivalence real, snapshot hid nothing - both
  mutation-proven).
- **Tech-debt:** the `_BootSkinDeps` seam is now OFF the `run_express` path → kill when `run()` is
  fully decomposed; `_configure_box` is now unused by the orchestrator (removal candidate in cleanup).
- **NEXT: Phase 3b - local-Kodi wipe-and-run** = the first VIEWABLE deliverable (run Express on the
  box → MOD V2 skin appears).

### Phase 5a - DONE (local commit; standalone Foundation = the skin-only deliverable)

- **Landed:** `install_repos(dialog)` extracted from `_install_base` (behavior-preserving incl.
  the exact per-iteration cancel semantics), and `run_foundation(box_env)` in `default.py`:
  `install_repos()` → `apply_foundation()` (skin closure + modv2plus + pvr.artwork direct-extract
  - Outline-HD + file-sources + home-trim) → set `lookandfeel.skin` LAST → restart →
    `self_uninstall`. Calls **neither** `apply_addons` content **nor** `apply_iptv`.
- **The deliverable:** Foundation installs **ALL our repositories** (the 12 `REPO_ZIPS` as
  sources/plumbing) + establishes `repository.tony7bones` (host proxy present + `.tony.7.bones`
  file source) + the skin + patch + skin-infra closure - and **ZERO content add-ons** (no base
  apps, no video, no pvr.iptvsimple, no IPTV). A clean branded Kodi; Setup self-removes.
- **Express unchanged:** `run_express` still installs the identical net set (repo install is
  idempotent); the characterization snapshot and `MONOLITH_NET_INSTALLED` invariant pass UNCHANGED.
- **Tested:** `_tools/test_run_foundation.py` (13 tests) + 3 extraction tests - mutation-verified
  (all 12 repos land; ZERO content at BOTH the stubbed AND the **real-engine resolve** level - a
  content leak fails; `install_repos` extraction byte-identical incl. cancel; skin-last;
  self-uninstall-after-summary). **Coverage:** addons.py 99%, `run_foundation` ~98% (uncovered =
  defensive guards). **QA review:** ACCEPT (closed the real-engine zero-content assertion).
- **NEXT: 5a device verification - a CLEAN Kodi install running `run_foundation`** → skin-only box
  (MOD V2 active, all repos present, ZERO content add-ons).

### Phase 5a·2 - DONE (local; Foundation realignment: menu-reliability fix + weather-into-Foundation)

> _(Numbering note: this and 5a·3 are CONTINUATIONS of the Foundation layer (Phase 5a), not new
> phases. The real Phase 5b is the IPTV layer - see "Phase 5b - NEXT" at the end of this doc.)_

Two coordinated changes, both **live-verified on a clean local Kodi 21.3 Omega** running
`run_foundation`.

- **Part A - menu reliability (`script.tony7bones.modv2plus` 1.4.7 → 1.4.8).** The skinshortcuts
  caching race (`service.py:_menu_is_ours`): Setup's live skin-switch can race
  script.skinshortcuts into building the STOCK Estuary menu and writing its `<skin>.hash` BEFORE
  our menu deploys; the matching hash then makes skinshortcuts SKIP rebuilding from ours on the
  next boot. **Fix:** the (re)deploy path (`_deploy_skinshortcuts_menu`, called from
  `apply_home_menu`) now DEFEATS the race in one atomic step - it (1) CLEARS the built
  skinshortcuts cache for `skin.estuary.modv2` (via `_clear_skinshortcuts_cache`), (2) deploys our
  exact menu DATA + widget `.properties`, then (3) DROPS the built `<skin>.hash` (new
  `_drop_skinshortcuts_hash`) so skinshortcuts regenerates from OUR menu on the next build/boot.
  `_menu_is_ours()`'s POV-based marker and the menu CONTENT (Live TV, Movies→POV, TV shows→POV,
  Add-ons, Favorites, Weather) are UNCHANGED. Bumped version + news, regenerated
  addons.xml/checksums/zip (old 1.4.7.zip pruned).
- **Part B - weather into Foundation.** `weather.multi` is part of the BRANDED LOOK (the MOD V2
  skin renders a weather readout + a Weather home-menu item), not content - so its INSTALL +
  CONFIG moved OUT of the Add-ons base `ADDONS` INTO Foundation (same pattern as the pvr→IPTV move
  in Phase 3). `apply_foundation` now installs `weather.multi` (via `install_with_deps`), sets the
  core `weather.addon` provider, and writes the env-driven (or keyless Sacramento default)
  locations (`_apply_weather_from_env` + helpers lifted from `addons.py` → `foundation.py`). The
  Outline-HD weather icons are already in the skin closure Foundation installs, and modv2plus's
  apply points `WeatherIcons` at them. The Add-ons layer now owns only RSS config. `ADDONS` is now
  `[script.ezmaintenanceplus, script.realdebrid]`.
- **Express equivalence:** the `MONOLITH_NET_INSTALLED` net-set invariant PASSES UNCHANGED -
  `weather.multi` (+ its python closure) is still installed by a full run, now via `apply_foundation`
  instead of the base loop. The characterization snapshot was regenerated (justified): `Apps 3/3→2/2`,
  the `weather.addon` setting + the weather.multi enable-order shift later (Foundation runs after
  add-ons in `run_express`). Net installed SET byte-identical - proven BEFORE the regen.
- **Tested:** `test_modv2plus.py` (+5 Part-A cache-clear/hash-drop tests, mutation-verified - hash-drop
  and cache-clear each independently killed); `test_run_foundation.py` / `test_setup_foundation.py`
  (Foundation installs+configures weather; weather unit tests moved here; mutation: weather-not-configured
  → net-set invariant + Foundation tests fail); `test_setup_addons.py` (weather out of ADDONS, RSS-only
  config; mutation: weather back in ADDONS → fail); `test_bootstrap.py` repointed. **541 passed / 1 xfailed**,
  `ruff` clean, secrets clean. **Coverage:** foundation.py 95%, addons.py 99%.
- **LIVE (clean Kodi, `run_foundation`):** MOD V2 active; the home menu is modv2plus's TRIMMED menu
  (Movies/TV shows/Add-ons/Favorites/Weather/Live TV - NO Music/Pictures/Games clutter), boot service
  logged `nothing to do (menu=True)` proving `_menu_is_ours`; clicking Movies (no POV) → Kodi's
  "Add-on required: POV" prompt; WEATHER WORKS - `weather.addon=weather.multi`, location Sacramento,
  Outline-HD icons, the skin's Weather panel populated ("Sacramento, California - 82°F · Sunny" + full
  forecast). ZERO content add-ons; all 12 repos installed. Screenshots captured.

### Phase 5a·3 - DONE (local; Foundation finishers: our repo + autocomplete + env-gated IPTV auto-chain)

Three additive Foundation changes, all unit-/mutation-verified (no live-Kodi pass yet -
the owner runs the clean-Kodi verify).

- **Foundation now installs our OWN proxy repo (`repository.tony7bones`).** Previously
  Foundation installed the 12 third-party `REPO_ZIPS` but NOT our own repo. `install_repos`
  (addons.py) now also direct-extracts the proxy installer zip - resolved LIVE from the
  served `addon.xml` via `_latest_zip_url` (the SAME mechanism modv2plus uses) - then
  registers + enables it (new `PROXY_REPO_ID`). Idempotent (`is_installed` short-circuit) and
  non-fatal (a resolve/extract failure leaves the box working; `apply_foundation`'s
  `.tony.7.bones` File-Manager source still lets the user reinstall). The box ends up with our
  repo as an INSTALLED, ENABLED add-on - the lifeline (updates / the proxy / future opt-ins) -
  not merely the source entry. Counted into `fp_ok` (first-party plumbing). Both Express
  (`run_express` via `_install_base`) and Foundation get it.
- **Foundation installs `script.module.autocompletion`** (official Kodi repo, current 2.1.1) -
  the on-screen-keyboard autocomplete QoL UTILITY (helps search / IPTV portal+login typing),
  NOT content. New `AUTOCOMPLETE_ID` + `_install_autocomplete` in foundation.py; installed via
  `install_with_deps(..., OFFICIAL_BASE, ...)`. Non-fatal; recorded in the Foundation
  `LayerResult` (`installed`/`failed`).
- **Env-gated IPTV auto-chain.** New `run_foundation_setup(box_env)` composes the shared
  Foundation install seam (`_foundation_core` - repos incl. our proxy + the skin/weather/menu/
  autocomplete layer) and THEN, **iff the env carries an IPTV provider** (`_env_has_iptv` -
  true when any `IPTV_<N>_M3U` / `IPTV_<N>_PORTAL` or the single-instance
  `IPTV_M3U`/`IPTV_PORTAL`/`IPTV_EPG` is present with a non-empty value; `IPTV_GROUPS` alone does
  NOT count), chains `apply_iptv` (installs pvr.iptvsimple + writes instance-settings). With no
  IPTV env it stops at the skin-only box - identical to `run_foundation` (no pvr, no IPTV).
  `run_foundation` stayed PURE skin-only (never touches IPTV); both runners share
  `_foundation_core` so they can't drift. Terminal seam (set `lookandfeel.skin` LAST → restart
  ONCE → self-uninstall) stays orchestrator-owned. NOT wired into the shipped `run()` (still
  `run_express`) - a new entry point for later.
- **Net-set invariant updated.** `MONOLITH_NET_INSTALLED` renamed → `EXPECTED_NET_INSTALLED`
  (old name kept as an alias) and now includes the two new ids with a justification comment
  (intentional feature growth, NOT a regression). The PROVEN delta before regenerating the
  golden snapshot was EXACTLY `{repository.tony7bones, script.module.autocompletion}` added,
  nothing else (asserted by `test_full_run_net_installed_set_equals_expected` +
  `test_foundation_additions_are_exactly_two`, mutation-proven). The characterization snapshot
  was regenerated - the diff is ONLY the two additions + their enable/rescan entries (no
  removals, no value changes; `Apps`/`Video` summary counts unchanged). `conftest.py`'s fake
  index gained `script.module.autocompletion` so the bare full run genuinely installs it (the
  growth is real, not asserted-only).
- **Tested / mutation-proven:** +13 net new tests across `test_setup_addons.py` (proxy install
  - idempotence), `test_setup_foundation.py` (autocomplete install / official-base / non-fatal),
    `test_run_foundation.py` (proxy + autocomplete land; `_env_has_iptv` true/false; the
    `run_foundation_setup` with-iptv → pvr+instance-settings, without-iptv → skin-only/no pvr/no
    apply_iptv call; skin-last; self-uninstall ordering; shared-seam), `test_modular_setup.py`
    (net-set + additions-are-exactly-two). Mutations killed: drop proxy install (3 tests), drop
    autocomplete (3 tests), force IPTV chain skip (1 test). **557 passed / 1 xfailed**, `ruff`
    clean (`_tools/` + first-party add-ons), secret-leak test green (IPTV env uses fakes).
- **Coverage:** addons.py 99%, foundation.py 95%, iptv.py 100%, bootstrap default.py 96% - all
  new code covered (uncovered lines are pre-existing defensive guards / `__main__`).
- **Generated files** regenerated (deterministic - second regen byte-identical); installer zip
  present in served `repositories/`; consistency gate green. modv2plus stays 1.4.8; no other
  version bumps (deferred to the milestone push).
- **QA review gaps closed:** (GAP-1) added `test_run_foundation_ignores_iptv_env` - proves the
  PURE `run_foundation` never chains IPTV even when handed an IPTV-bearing env (purity was
  structural; now mutation-guarded). (GAP-2 decision) **`IPTV_EPG` alone no longer trips the
  gate** - an EPG with no playlist is a channel-less PVR, not a usable source; the gate is now
  M3U/PORTAL only (`apply_iptv` still consumes `IPTV_EPG` when a real provider is present).
  **558 passed.**
- **LIVE-VERIFIED (clean Kodi, `run_foundation_setup` with an IPTV-bearing env from `.env.local`):**
  `repository.tony7bones` v2.2.1 **installed + enabled** (proxy service running) - the previously-
  missing lifeline; `script.module.autocompletion` 2.1.1 **installed + enabled**; the **env-gated
  chain FIRED** (`has_iptv=True` → pvr.iptvsimple installed); MOD V2 active, trimmed menu, weather
  populated, Setup self-uninstalled.

#### ⚠️ Two IPTV-LAYER bugs the live run surfaced → first action items for Phase 5b

These are in `apply_iptv` (the IPTV layer), NOT Foundation - the chain WIRING is correct (gate
fires, backend installs). They are exactly the IPTV-layer hardening Phase 5b owns.

1. **Instance-settings clobber (the live box ends up with an UNCONFIGURED pvr).** `apply_iptv`
   ENABLES pvr.iptvsimple (which instantiates the live PVR client with stock in-memory defaults)
   BEFORE `_ensure_iptv_custom_tv_groups` WRITES the file - so the running client flushes its stale
   defaults back over the enforce's write (the same "Kodi clobbers a direct file write" class the
   project documents for `Skin.SetBool`). FIX (5b): write/enforce instance-settings BEFORE enabling
   the backend (or disable around the write, or force a reload after). The Express `_configure_box`
   path likely has the same latent race.
2. **Multi-provider → single-instance env gap.** `_ensure_iptv_custom_tv_groups` reads single-instance
   `IPTV_M3U`/`IPTV_EPG`/`IPTV_GROUPS`, but the per-device `.env` uses the multi-provider `IPTV_<N>_*`
   shape - there is no `IPTV_<N>_*` → instance derivation yet, so a real provisioner env writes
   nothing. FIX (5b): generalize `apply_iptv` to N providers (the deferred P2 work - host-side
   `build_iptv.py` from the `iptv` branch + N `instance-settings-<N>.xml`).

---

### Phase 5b·1 - DONE (local; both `apply_iptv` live-box bugs fixed: the PVR-disabled config window + N-provider env)

The two bugs above, fixed and clean-Kodi proven (channels actually load - the acceptance the
5a·3 verify could not reach).

- **Bug #1 - instance-settings clobber → the PVR-DISABLED config window.** `apply_iptv` now wraps
  BOTH file-writing halves (the device-copy AND the instance-settings enforce) in
  `_pause_pvr_for_config()` / `_resume_pvr_after_config()` (iptv.py): disable pvr.iptvsimple →
  1s settle (the client teardown flushes ITS settings BEFORE our writes) → copy + enforce →
  re-enable in a `finally` (never leave the backend disabled). The re-enable makes Kodi's
  multi-instance scanner re-read every `instance-settings-<N>.xml` just written, so the fresh
  client(s) start with OUR values in memory - every later flush (incl. the end-of-setup clean
  shutdown that corrupted the 5a·3 box) now PRESERVES the config instead of clobbering it.
  **Mechanism choice:** the shared `install_with_deps` (whose final enable is correct for every
  other add-on) stays untouched - the bounce uses the library's own `enable`/`disable` primitives
  and uniformly covers both the fresh-install path (just enabled by the installer) and re-entry on
  an already-enabled box. **Express verdict:** the shipped Express path goes through `apply_iptv`
  (fixed); the legacy `_configure_box` helper (no shipped runner calls it, but its body carried the
  same race - pvr enabled EARLY by the monolith's base step, config written LATE) got the SAME
  guarded window (no-op on a pvr-less box, so its existing tests/behaviour are unchanged).
- **Bug #2 - multi-provider env.** New `_iptv_providers(box_env)` parses the real per-device shape:
  each `IPTV_<N>_NAME/MODE/M3U/EPG/GROUPS/GROUPS_ONLY` block becomes ONE pvr.iptvsimple instance -
  `instance-settings-<N>.xml` (the env N is the instance id; gaps preserved) + its own
  `channelGroups/customTVGroups-<Name>.xml` (provider NAME, non-alnum stripped - "Network 24" →
  `Network24`, deliberately identical to the legacy constant) + the multi-instance identity keys
  (`kodi_addon_instance_name`/`_enabled`) that make a CREATED instance file real to Kodi's scanner.
  The legacy single-instance keys map to a `legacy=True` provider 1 that keeps the monolith's exact
  paths and writes NO identity keys - byte-compatible with every shipped box, so all existing
  tests/envs pass unchanged. Per-provider failures are logged and skipped (the others still apply).
- **Groups grammar (the in-Kodi half).** `_group_source` extracts the SOURCE side of
  `SOURCE > Display Label | sort` - pvr.iptvsimple matches `<channelGroupName>` against the
  playlist's group-title values (the provider's ORIGINAL names); pointing it at the display label
  would load zero channels. Display relabel + the `| sort` directive + `IPTV_<N>_FAVORITES` are
  host-side curation → deferred to step 2 (`build_iptv.py`).
- **Xtream decision (scope boundary honored).** pvr.iptvsimple Omega (21.11.0) has NO native
  Xtream-Codes connection mode - verified against the REAL installed instance-settings schema (its
  only XTREAM reference is the `allChannelsCatchupMode` CATCHUP enum, no portal/user/pass source
  settings) - and this provider's get.php m3u export is server-blocked, so URL derivation can't work
  either. An xtream-mode provider is therefore SKIPPED in-Kodi with an honest log (no creds logged,
  no instance file written); host-side xtream→m3u derivation lands in step 2.
- **Snapshot delta (reviewed):** the `bare` characterization snapshot's `enable_sequence` gains
  EXACTLY the pvr.iptvsimple disable→enable bounce after its install-enable (installed/disabled
  sets, settings, builtins, files all unchanged); the `full` snapshot is byte-identical (its iptv
  install is a no-state stub, so the guarded pause no-ops).
- **Tested / mutation-proven:** +17 net new tests - `test_setup_iptv.py` (+14: the disabled-window
  ordering probe [copy AND enforce observed running with pvr disabled, exact
  install-enable→disable→enable sequence], finally-re-enable on a raising enforce, pause no-op
  without the backend, pause/resume failure swallows, `_group_source` grammar, `_iptv_providers`
  parsing + mode inference + legacy fallback, one-instance-per-provider with identity keys +
  per-provider groups files + N-gap honored, xtream skip with zero secret leak, legacy-shape
  back-compat incl. IPTV_NAME, one-bad-provider isolation, numbered-shape secrets-never-logged,
  multi-provider `apply_iptv` reports "configured", outer parse-failure swallow),
  `test_run_foundation.py` (+1: the REAL env shape through `run_foundation_setup` - m3u provider 1
  configured + named, xtream provider 2 skipped, backend ends ENABLED), `test_bootstrap.py` (+2:
  `_configure_box` writes inside the window with pvr installed / no toggles at all without pvr).
  **575 passed / 1 xfailed** (was 558), `ruff` clean (`_tools/` + both add-ons), secret-leak green.
- **Coverage:** iptv.py **100%**, bootstrap default.py 96% (every uncovered line is a pre-existing
  defensive guard / `__main__` - all NEW code covered). Generated files regenerated (second regen
  byte-identical); no version bumps (deferred to the milestone push).
- **LIVE-VERIFIED (clean Kodi, fresh profile, `run_foundation_setup` with the FULL `.env.local`
  multi-provider env - 28 keys, `has_iptv=True`):** the enforce logged
  `instance 1: generated 3 custom group(s)` + `groups=True only=true m3u=True epg=True` and
  `provider 2 is xtream-mode - skipped in-Kodi`; pvr.iptvsimple pulled the real playlist (2.3 MB
  m3u cache + 19 MB EPG cache) from the written settings DURING the run; after the clean-shutdown
  restart (the exact flush that clobbered the 5a·3 box) `instance-settings-1.xml` still carried
  `kodi_addon_instance_name=Network 24`, `tvGroupMode=2`, `tvChannelGroupsOnly=true`, m3u/epg -
  and JSON-RPC proved the acceptance: `PVR.GetChannelGroups` = **USA ENTERTAINMENT / USA
  NEWS/WEATHER / PPV EVENTS** (+ the stock "All channels"), `PVR.GetChannels` totals **158 / 47 /
  24** real channels per group. `skin.estuary.modv2` active, pvr.iptvsimple 21.11.0 enabled, no
  `instance-settings-2.xml`, Setup self-uninstalled, staged env deleted.

### Phase 5b·2 - DONE (local; the host-side IPTV build integrated - EVERY provider, xtream included, loads channels)

The deferred P2 work landed: `_tools/build_iptv.py` (+ its suite + the customization
playbook) came over from the `iptv` branch, ADAPTED to the 5b·1 N-provider model, and
`apply_iptv` now consumes its staged artifacts - the panel's "IPTV is two halves"
decision realised. The owner's directive "everything must be fixed" holds: on the
acceptance run NO provider ends unconfigured (the 5b·1 xtream skip fires only on a
box with no staging).

- **The host half (`_tools/build_iptv.py`).** Per `IPTV_<N>_*` block it fetches (m3u
  mode) or SYNTHESIZES via the Xtream player_api (xtream mode - `get_live_categories`
  - `get_live_streams` → `…/live/<user>/<pass>/<id>.ts` URLs) a CURATED local playlist
    applying the FULL groups grammar: selection, `> Display Label` relabel, `| sort`, and
    `IPTV_<N>_FAVORITES` (name-substring both modes; `id:`/category pins xtream-only;
    favorites group emitted FIRST; multi-group `group-title="Label;24/7 Favorites"` for a
    favorite inside a selected group, favorites-only emission for one outside). It emits
    three artifacts per provider into gitignored `iptv-build/<device>/`: `<Token>.m3u`,
    `customTVGroups-<Token>.xml` (DISPLAY labels), `instance-settings-<N>.xml` (identity
    keys + `m3uPathType=0` with a PORTABLE `special://…/playlists/<Token>.m3u` path +
    remote EPG + custom group mode GATED on a non-empty group list + env
    `GROUPS_ONLY`, forced off for blank-GROUPS curation so favorites never hide an
    uncurated playlist). `<Token>` = the in-Kodi `_groups_file_special` derivation
    ("Network 24" → `Network24` - the legacy filename preserved). Per-provider failures
    are reported and skipped; exit 1 if any failed. The POC's direct-to-Kodi `provision`
    mode is GONE - applying is the in-Kodi half's job.
- **The in-Kodi half (`_apply_staged_provider`, iptv.py).** When the env carries
  `IPTV_STAGING_DIR` (NO default - the key exists iff the host actually staged, so
  legacy boxes can never drift into the staged path), each provider FIRST consumes its
  staged artifacts inside the 5b·1 PVR-disabled window: PARSE-based (reads what the
  staged instance file references - no naming-convention coupling), validates every
  side-file exists BEFORE writing anything (partial staging must never point pvr at
  missing files), copies playlist + groups to their `special://` homes, REWRITES
  `m3uPath` to the translated absolute path (the POC-proven form; `customTvGroupsFile`
  keeps its live-proven special:// form), then writes `instance-settings-<N>.xml`.
  Any no/partial/malformed staging or copy failure → logged, per-provider fallback to
  the 5b·1 direct-env enforce (whose xtream skip log now says "no staged host-built
  config - run the host build"). Staged consumption is deliberately always-apply
  (host artifacts are authoritative; re-copying identical bytes on re-entry is
  harmless inside the window).
- **Provisioner wiring (`provision-kodi.sh` step 4b).** Builds into
  `iptv-build/<device>` (rm -rf'd first - never push STALE artifacts), pushes the dir
  to the device-convention `/storage/emulated/0/kodi/tony.7.bones/iptv/`, and appends
  `IPTV_STAGING_DIR` to the derived `tony7bones.env` iff the push landed. A PARTIAL
  build (one provider failed) is still staged - apply_iptv falls back per-provider, so
  the built providers keep their curation (QA finding: the first cut discarded the
  good providers' artifacts on any failure).
- **Decisions documented:** (1) staging location = gitignored `iptv-build/<device>/`
  host-side, the existing device-convention `iptv/` dir on the box (generated
  artifacts land exactly where hand-placed files always lived), `IPTV_STAGING_DIR`
  env key as the ONLY pointer; (2) the xtream playlist is a staged LOCAL file, not a
  derived URL (get.php is server-blocked - HTTP 884 - and pvr.iptvsimple Omega has no
  Xtream mode; m3u-mode curation is ALSO a local snapshot because relabel/sort mutate
  group-title/order, impossible against a remote URL; refreshed every provisioner
  run); (3) favorites become a customTVGroups group via multi-group group-title
  tagging in the synthesized playlist, label listed FIRST.
- **Secret hygiene:** `test_secret_leak.py` extended - the value-scan now covers every
  numbered `IPTV_<N>_M3U/EPG/PORTAL` URL plus raw `IPTV_<N>_USER`/`_PASS` (previously
  ONLY the legacy keys - a real gap), and ANY tracked `*.m3u` is structurally
  forbidden (host-built playlists embed creds in every channel URL). `iptv-build/`
  was already gitignored + tracked-forbidden. The builder prints names/labels/counts
  only; the in-Kodi staged path logs booleans only - both pinned by tests.
- **Tested:** +73 net new tests - `test_build_iptv.py` (58: env/provider/grammar
  parsing, token↔in-Kodi-derivation lock, m3u curation incl. favorites multi-group/
  non-PPV preference/xtream-form rejection, xtream synthesis incl. favorites pin/
  category folds, instance-xml gating, build/main failure + exit-code contract, no
  creds in stdout) and `test_setup_iptv.py` (+15: staged apply with m3uPath rewrite,
  xtream-finally-configures with zero secret leak, fallbacks for missing instance /
  missing playlist / missing groups / malformed / wrong root / copy-failure, no-key
  means no staged path, legacy consumption, stale extra instances ignored,
  no-side-file instance verbatim, idempotent re-entry, apply_iptv end-to-end with the
  REAL two-provider shape proving the PVR window still wraps everything).
  **647 passed / 1 xfailed** (was 575), `ruff` clean, secret-leak green.
- **Coverage:** build_iptv.py **99%** (missing: the real-network `http_get` body +
  `__main__`), iptv.py **100%**.
- **QA findings closed pre-commit:** the provisioner's discard-partial-build flaw and
  the stale-staging-dir reuse (both fixed above); stale `instance-settings-<N>.xml`
  on a REDUCED provider count is documented in the playbook as the same manual-clean
  class as the lingering PVR-DB groups (the env-driven loop never applies them).
- **LIVE-VERIFIED (clean Kodi, fresh profile, real `.env.local`, full flow: host
  build → staged artifacts → `run_foundation_setup`):** the build fetched BOTH real
  providers (Network 24 m3u: 229 ch; Streamvision xtream: 331 ch - player_api
  synthesis worked where 5b·1 had to skip); in-Kodi `_apply_staged_provider` logged
  `instance 1/2: applied HOST-BUILT staged config (playlist=True groups=True)`; BOTH
  EPGs cached (19 MB + 74 MB) during the run; after the end-of-setup restart AND a
  further clean-shutdown quit+relaunch, `instance-settings-1.xml` + `-2.xml` both
  survive with identity/m3uPathType=0/tvGroupMode=2/groups-only intact, and JSON-RPC
  proves the acceptance: **8 groups** - provider 1 `US Entertainment 158 /
US News/Weather 47 / PPV Events 24` (DISPLAY labels, alpha-sorted: A&E → ABC →
  ADULT SWIM → AMC…), provider 2 `US Entertainment 214 / US News 100 / UFC PPV 12 /
24/7 Favorites 5` (the favorites are exactly the five curated channels, incl. the
  two `id:`-pinned 4K feeds), `All channels` = **560 = 229+331**. MOD V2 active,
  Setup self-uninstalled, staged env read-then-removed. (Driver note: the run was
  triggered by patching the INSTALLED bootstrap copy's `run()` to call
  `run_foundation_setup` with a local env path - the repo source is untouched; the
  shipped `run()` still calls `run_express`.)

- **Addendum - live-box bug: the 24/7 Favorites group rendered ICONLESS.** Root
  cause (diagnosed on the real data, not the code): all five favorites resolve to
  Streamvision's "US| CINEMA TV SHOWS" category - the verified 4K feeds - and the
  panel stamps EVERY stream in that category with the same placeholder
  `stream_icon` (`picons.cmshulk.com/.../cinemania.jpg`), which is **HTTP 404**;
  the other groups' `photo-tmdb.com` icons fetch fine. The synthesized playlist
  faithfully carried the dead URL, Kodi fetched nothing, and `tvg-id=""` meant no
  EPG fallback. Fix (`build_xtream_mode`): favorite icons are now validated at
  build time (`_icon_alive` - memoized HTTP check, blank = dead) and a dead one
  borrows the first LIVE icon from another copy of the same channel in the stream
  list (`_name_core` match: country prefix / `24/7` markers / quality tags /
  Unicode decorations ignored, so `"US: THE SIMPSONS 4K"` ≡ `"24/7: THE
SIMPSONS"`); no donor → original kept + a printed note. Only favorites are
  checked (the hand-picked shelf; validating every channel = hundreds of fetches);
  m3u mode is untouched (verbatim provider EXTINF - the failure is xtream's
  category-wide placeholder). +16 tests (suite 663 passed / 1 xfailed;
  build_iptv.py still 99%). Live-proven: rebuild from the real `.env.local` healed
  5/5 (`borrowing the icon of …` notes), re-applied to the live box, and after a
  clean-shutdown restart JSON-RPC `PVR.GetChannels` group 9 + the PVR DB
  (`TV46.db` `sIconPath`) + a rendered-screen screenshot all show the five
  favorites carrying the live `photo-tmdb.com/.../14330.png` icon exactly like
  the working groups. Playbook updated (favorites-icon healing section).

## Phase 5b - COMPLETE (steps 1-3 DONE incl. the icon addendum; `run_iptv` landed in 5b·3)

> **Status of the build (HEAD `954f9f3`, suite 663 passed / 1 xfailed):** Phases 0-3 + **5a
> (Foundation, incl. 5a·2/5a·3)** + **5b·1 (both `apply_iptv` bugs fixed + clean-Kodi
> channel-load proof)** + **5b·2 (host-side IPTV build integrated - BOTH real providers,
> xtream included, live-proven loading channels)** + the **favorites-icon healing addendum**
> (dead xtream placeholder icons borrowed from live duplicates at build time, live-proven)
> are DONE, gated, and committed LOCALLY on `modular-setup` - **not pushed** (milestone-push
> pending: it needs the `script.module.tony7bones` + `script.tony7bones.bootstrap` version
> bumps + a `--news`; the `iptv` branch is superseded and can be deleted then). The
> Foundation deliverable is complete and clean-Kodi verified, and the env-gated IPTV chain
> now PROVABLY loads EVERY env provider's channels with the full curation grammar.
> `run_express` (Express) and `run_foundation`/`run_foundation_setup` (skin-only + env-gated
> IPTV chain) exist; the shipped `run()` still calls `run_express`.

**5b makes the IPTV layer independently runnable AND correct.** In order:

1. ~~**FIX the two `apply_iptv` live-box bugs**~~ - **DONE (Phase 5b·1, see the phase log above):**
   the PVR-disabled config window (clobber fix, incl. the legacy `_configure_box` slot) + the
   N-provider `IPTV_<N>_*` → N `instance-settings-<N>.xml` + N `customTVGroups-*.xml`
   generalization (legacy single-instance keys = provider 1, byte-compatible). Clean-Kodi proof:
   158/47/24 channels in the three custom groups, settings survive the shutdown flush.
2. ~~**Integrate the host-side IPTV build**~~ - **DONE (Phase 5b·2, see the phase log above):**
   `_tools/build_iptv.py` + its suite + the customization playbook brought over from the `iptv`
   branch (adapted to the 5b·1 N-provider model), wired into the provisioner (build → push →
   `IPTV_STAGING_DIR`), with `apply_iptv` consuming the staged curated artifacts (parse-based,
   inside the PVR-disabled window, per-provider fallback to direct-env). Clean-Kodi proof: BOTH
   real providers load - 158/47/24 (m3u, relabelled + sorted) and 214/100/12 + the 5-channel
   favorites group (xtream, synthesized via player_api) - surviving a clean-shutdown restart.
   Plus the **icon addendum** (dead favorite icons healed at build time, live-proven).
3. ~~**`run_iptv(box_env)`**~~ - **DONE (Phase 5b·3, see the phase entry after 5c below):** the
   IPTV layer is independently runnable on top of an existing Foundation - a user who stopped
   skin-only later adds live TV with no redo. (The prep below is kept as the design record.)
4. ~~**Gate it**~~ - **DONE:** the standing four-part bar + the clean-**Foundation**-box live
   verify all passed (see the 5b·3 entry).

### Phase 5b·3 - PREP (the design record; DELIVERED - see the 5b·3 phase entry after 5c): `run_iptv(box_env)` - the standalone IPTV runner

**Goal.** A new bootstrap entry point `run_iptv(box_env)` that applies ONLY Layer 1 on top of
an EXISTING Foundation box (MOD V2 active, repos installed, zero content): the 0-1-2 model's
"stopped at skin-only, later adds live TV" story. Everything it needs already exists -
`apply_iptv` owns its backend (install-or-fail-loud, Phase 3a), consumes staging
(`IPTV_STAGING_DIR`) with per-provider direct-env fallback, and writes inside the PVR-disabled
window. 5b·3 is the thin orchestrator + its gate.

**Design (mirror `run_foundation`'s shape - `addons/script.tony7bones.bootstrap/default.py`):**

- **Body:** progress dialog → `apply_iptv(box_env, dialog=dialog, log=_log)` → summary dialog
  (installed/configured/FAILED per the LayerResult; honest about a skipped/unstaged provider) →
  `self_uninstall(MY_ID, _log)` → ONE `restart_kodi(...)` (pvr.iptvsimple reads instance
  settings at startup - honor the layer's `needs_restart` request).
- **It must NOT touch the skin.** No `activate_skin`, no `lookandfeel.skin` - Foundation
  already owns the active skin; re-setting it would re-arm the "Keep this skin?" revert
  timeout for no reason. It also does NOT call `install_repos` (Foundation installed them; the
  backend install resolves from the already-installed repos - if a repo is somehow missing,
  `apply_iptv`'s fail-loud path reports it rather than silently reinstalling plumbing).
- **Env lifecycle:** same coordinator pattern as `run()` - the driver reads the per-device env
  ONCE (`read_box_env(BOX_ENV_PATH)`), passes the dict in, and deletes the env file only after
  a successful (non-cancelled) run. Precondition for the later-opt-in story: the provisioner
  (or a lighter re-stage) must have re-pushed `tony7bones.env` + the staged `iptv/` artifacts
  to the box - Foundation's earlier run consumed and deleted the original env. Document this
  in the runner's docstring.
- **Failure semantics:** `apply_iptv` `ok=False` (backend didn't install) → summary says
  FAILED, NO restart-into-broken-state surprises (still restart once - the box is unchanged
  except possibly extracted-but-disabled bits - but the summary must not claim success), env
  left intact for a re-run. Per-provider config failures stay defensive (logged, reported via
  `installed`/`failed`).
- **Re-entry:** running it twice is safe by construction - backend `is_installed`
  short-circuits, staged consumption is always-apply (identical bytes, inside the window),
  direct-env enforce is write-only-if-changed. Pin this with a test (second run →
  `already_done` semantics honest, no duplicate instances).

**Acceptance bar (the standing four-part bar, applied to 5b·3):**

1. **Tests + coverage:** unit tests for the runner (mocked xbmc\*) - happy path order
   (apply → summary → self-uninstall → restart LAST), no-skin-touch invariant (never calls
   activate_skin / sets lookandfeel.skin), no-install_repos invariant, backend-failure
   summary honesty, env-driven N-provider passthrough, re-entry. ≥90% new-code coverage.
2. **Gate:** `pytest _tools/ -q` green + `ruff` + secret-leak + deterministic regen.
3. **Adversarial QA completeness review** before commit.
4. **Clean-FOUNDATION-box live verify:** fresh local Kodi → run `run_foundation` (skin-only,
   NO pvr) → restart → confirm zero content. Then stage (build_iptv + env re-push, the
   provisioner-equivalent for the local box) and trigger `run_iptv` with the real `.env.local`
   (same driver trick as 5b·2: patch the INSTALLED bootstrap copy's `run()` - repo source
   untouched). Prove: pvr.iptvsimple installed BY THIS LAYER, both providers configured from
   staging, JSON-RPC group/channel counts match the builder's, MOD V2 STILL the active skin,
   Setup self-uninstalled, and everything survives a further clean-shutdown restart
   (the honest-PVR recipe: `docs/playbooks/local-kodi-verification.md` → "Verifying PVR /
   IPTV state").

**Out of scope for 5b·3:** wiring `run_iptv` into any shipped entry point (the shipped `run()`
stays `run_express` until 5d), Guided-wizard UI, and the Add-ons layer (5c).

**Then:**

- ~~**Phase 5c - the Add-ons layer independent** (`run_addons`)~~ - **DONE (taken deliberately
  BEFORE 5b·3 - no dependency on it; see the phase entry below).**
- **Phase 5d - the Guided wizard + Model A lifecycle** (the panel's keystone): the orchestrator
  persists across gates (self-uninstall only on terminal Finish); the wizard offers the next undone
  gate using installed-state probes; the **no-fork** invariant (Guided and Express drive the same
  `apply_*`). Wire a chosen default into the shipped `run()` (today still `run_express`).
- **Phase 6 - harden + Fire TV** (version-guard shared modules, `assert_box_complete`, CI gates, the
  wipe-and-run matrix on a real Stick for the Android manual-restart UX).

### Phase 5c - DONE (local; the standalone Add-ons layer: `run_addons`)

> _(Ordering note: 5c was deliberately done BEFORE 5b·3 (`run_iptv`) - it has no dependency on
> it. 5b·3 stays queued as the next step; its full prep section above is unchanged.)_

- **Landed:** `run_addons(box_env)` in `default.py` - a thin standalone orchestrator mirroring
  `run_foundation`'s proven seam: progress dialog → `apply_addons(box_env)` (the SAME layer
  function Express drives - base source repos + base apps + curated video POV/Loop/Sports HD/
  YouTube with closures + origin stamps + the dailymotion install-then-disable + the RSS core
  toggle + env-driven RSS feeds) → honest summary (per-stage counts straight from the
  LayerResult: `Repos x/12, Apps x/2, Video x/4`) → `self_uninstall` → ONE platform-aware
  `restart_kodi`. ZERO library changes - the orchestrator is the entire diff, so the no-fork
  invariant is structural (one `apply_addons`, two callers).
- **Layer invariants (decided + pinned):** NO skin touch - no `activate_skin`, no
  `lookandfeel.skin`, no `Skin.SetBool` (re-setting the skin re-arms the "Keep this skin?"
  revert timeout; the top-bar weather bool belongs to Foundation/modv2plus). NO
  orchestrator-level `install_repos` call (Foundation owns plumbing) - the LAYER's own
  `_install_base` keeps its historical idempotent repo loop internally, shared verbatim with
  Express (on a Foundation box every repo extract short-circuits). NO
  `apply_foundation`/`apply_iptv`.
- **Foundation-missing semantics (decided, not probed):** tolerant fallback - on a box WITHOUT
  Foundation the curated content still lands and works (`apply_addons`' base step installs the
  source repos itself, so the video closures resolve); the box just isn't branded (stock
  Estuary). No probe-and-abort: the layer is additive/re-entrant and a later `run_foundation`
  completes the branding with no redo.
- **Env lifecycle:** dict passed in; the DRIVER owns read-once (`read_box_env`) +
  delete-only-after-success (a cancel leaves the env for a re-run) - same coordinator pattern
  as `run()`/the 5b·3 prep. Precondition for the later-opt-in story (documented in the
  docstring): the env must be re-pushed - Foundation's earlier run consumed the original.
- **Failure semantics:** cancel (`ok=False`, the only not-ok path) → clean abort, NO
  summary/uninstall/restart (the monolith's early-return contract). Per-add-on failures are
  non-fatal: honest counts (e.g. `Video add-ons: 2/4`), box still completes with one restart.
- **NOTE - weather is NOT this layer's job** (5a·2 moved it to Foundation; the original Phase-5c
  bullet predates that). `run_addons` applies only RSS; the acceptance's weather evidence comes
  from Foundation's env-driven config, proven intact on the same live box.
- **Tested / mutation-proven:** new `_tools/test_run_addons.py` (14 tests, same fake-Kodi `boot`
  patterns): curated set + disable-after, Foundation-less repos fallback, no-skin-touch (spy +
  settings + builtins), real-engine no-Foundation/no-IPTV leak (installed-set + instance-file +
  weather.addon), STRUCTURAL body test (apply_addons stubbed → no
  install_repos/apply_foundation/apply_iptv/activate_skin), terminal ordering
  (summary→self-uninstall→restart, restart LAST, exactly once), honest partial-failure summary,
  real dialog-cancel abort, env passthrough verbatim + None→{}, env-driven RSS write, re-entry
  (second run state-identical; `already_done=False` semantics pinned honestly). Mutations
  killed: skin-activation added (2 tests), `install_repos` added to the body, `self_uninstall`
  dropped (2), lying video count. **677 passed / 1 xfailed** (was 663), `ruff` clean, secrets
  green; snapshot + `EXPECTED_NET_INSTALLED` pass UNCHANGED (`run_express` untouched).
- **Coverage:** the new `run_addons` body 100% (default.py 96% - every uncovered line is a
  pre-existing defensive guard / `__main__`). Generated files regenerated (second regen
  byte-identical); no version bumps (deferred to the milestone push).
- **LIVE-VERIFIED (clean Kodi 21.3, fresh profile, two-leg run with the real `.env.local`):**
  leg 1 `run_foundation` → a proven Foundation-ONLY box (all 8 content ids NOT installed; skin
  21.4+omega.4 + modv2plus + pvr.artwork + weather.multi + autocomplete + all repos + our proxy
  repo installed/enabled; weather env-applied: `5 location(s) written; weatherbit=True
owm=True`). Leg 2 `run_addons` (driver: patched INSTALLED copy's `run()`, repo source
  untouched) → log `stamped origin on 21 add-on(s)`, `disabled after install:
plugin.video.dailymotion_com`, `_apply_rss: wrote 7 RSS feed(s) (interval 30)`; JSON-RPC:
  POV 6.06.06 / Loop 7.9 / Sports HD 0.1.85.1 / YouTube 7.4.3 installed+ENABLED, dailymotion
  2.4.4 installed+DISABLED, both base apps enabled; origins stamped (kodifitzwell/loop/
  bugatsinho/xbmc.org×2; the two peno64 base apps blank - PRE-EXISTING `install_with_deps`
  by-design "No origins", identical under Express); RssFeeds.xml == the parsed env exactly
  (7 feeds, interval 30) + `lookandfeel.enablerssfeeds=true`; `IPTV` instance file absent,
  pvr.iptvsimple NOT installed; Setup self-uninstalled; staged env consumed. **MOD V2 STILL
  the active skin after the run** (no `activate_skin` log line in leg 2 - the no-skin-touch
  invariant live-proven). **Clean-shutdown restart-survival:** after quit+relaunch the skin,
  RSS setting + 7 feeds, weather (5 locations + keys + provider) and all add-on states
  survived; the modv2plus service auto-applied the patch on the real boot
  (`show_system_info_overlay` marker present, `show_weatherinfo=true`); POV `GetDirectory`
  **11 items** + a browsable Movies submenu (**14 items**: Trending/Popular/Premieres…);
  rendered-home screenshot shows the patched MOD V2 trimmed menu, top-bar weather (70°F) and
  the live RSS ticker. **Platform finding (documented):** Kodi's `RestartApp` is a NO-OP on
  macOS (one PID across the whole run; the skin went live via `activate_skin`'s live switch) -
  the playbook's clean-quit+relaunch IS the real restart on this box; on Fire TV the prompt-free
  Quit() path is unaffected. The local box was RESTORED to its pre-verify state (the 5b·2 full
  IPTV box - all 8 channel groups re-confirmed); the 5c end-state archived as
  `Kodi.archive-5c-verified-*`.

### Phase 5b·3 - DONE (local; the standalone IPTV runner `run_iptv` - Phase 5b COMPLETE, all three layers independently runnable)

- **Landed:** `run_iptv(box_env)` in `default.py` - a thin standalone orchestrator mirroring
  `run_foundation`/`run_addons`' proven seam: progress dialog → `apply_iptv(box_env)` (the SAME
  layer function Express drives - backend install-or-fail-loud, the PVR-disabled config window,
  staged-first consumption with per-provider direct-env fallback, the N-provider enforce) →
  honest summary straight from the LayerResult → `self_uninstall` → ONE platform-aware
  `restart_kodi`. ZERO library changes - the orchestrator (+ a `PVR_BACKEND_ID` re-export) is
  the entire runtime diff, so the no-fork invariant is structural (one `apply_iptv`, three
  callers: Express, `run_foundation_setup`, `run_iptv`).
- **Layer invariants (decided + pinned):** NO skin touch - no `activate_skin`, no
  `lookandfeel.skin`, no `Skin.SetBool` (Foundation owns the active skin; re-setting it would
  re-arm the "Keep this skin?" revert timeout). NO `install_repos` - Foundation owns plumbing,
  and `apply_iptv` resolves its backend's platform closure straight from the OFFICIAL repo, so
  **Foundation-missing is tolerant** (backend + config still land on an unbranded box; no
  probe-and-abort - same decided semantics as `run_addons`). NO `apply_foundation` /
  `apply_addons` - one layer per runner.
- **Failure semantics (decided per the prep):** `apply_iptv` `ok=False` = the backend did not
  install - the ONLY not-ok path; this layer has **NO user-cancel path by construction**
  (`install_with_deps` never polls the dialog's cancel button, unlike the Add-ons layer's
  per-repo loop - PINNED by a cancel-button-inert test so a future cancel-poll surfaces
  deliberately). On failure the summary says FAILED + "No instance settings were written"
  (fail-loud = no half-config), then the runner STILL self-uninstalls and restarts ONCE - the
  box is unchanged, so the restart lands on the same working Foundation box, never a broken
  one; the DRIVER keeps the env (delete-only-on-ok), and Foundation guarantees our proxy repo,
  so the retry is a one-tap Setup reinstall + re-run.
- **Env lifecycle:** dict passed in; the DRIVER owns read-once (`read_box_env`) +
  delete-only-after-ok - the coordinator pattern shared with `run()`/`run_addons`. Documented
  PRECONDITION for the later-opt-in story: the provisioner (or a lighter re-stage) must have
  re-pushed `tony7bones.env` AND the staged `iptv/` artifacts (step 4b's existing transport -
  nothing new invented; Foundation's earlier run consumed the original env).
- **Tested / mutation-proven:** new `_tools/test_run_iptv.py` (16 tests, the fake-Kodi `boot`
  patterns): backend + inputstream closure installed BY THE LAYER through the REAL engine and
  ends ENABLED (the clobber window re-enables); legacy + numbered multi-provider envs (identity
  keys, the groups grammar's SOURCE side, an unstaged portal-mode provider skipped honestly with
  no instance file); the staged-first path END-TO-END through the runner (m3uPath rewritten to
  the translated absolute path, staged config authoritative over the env's remote URL);
  no-skin-touch (spy + settings + builtins); real-engine no-Foundation/no-Add-ons/no-repos leak;
  STRUCTURAL body test (apply_iptv stubbed → no install_repos/apply_foundation/apply_addons/
  activate_skin); terminal ordering (summary → self-uninstall → restart LAST, exactly once);
  honest summaries ("written" / "unchanged…" / FAILED - never a false success); the
  cancel-inert pin; env passthrough verbatim + None→{}; re-entry (installed set + instance file
  BYTE-identical, `already_done=True` honest, backend still enabled). Mutations killed:
  skin-activation added (2 tests), `install_repos` added to the body (2), `self_uninstall`
  dropped (2), lying failure summary (1), restart dropped (3). **693 passed / 1 xfailed** (was
  677), `ruff` clean, secrets green; snapshot + `EXPECTED_NET_INSTALLED` pass UNCHANGED
  (`run_express` untouched). One guard adaptation: `test_no_iptv_secret_embedded` bans the
  "xtream" token from the shipped `default.py`, so the docstring says "portal-API provider".
- **Coverage:** the new `run_iptv` body 100% (default.py 96% - every uncovered line is a
  pre-existing defensive guard / `__main__`). Generated files regenerated (second regen
  byte-identical); no version bumps (deferred to the milestone push).
- **LIVE-VERIFIED (clean Kodi 21.3, fresh profile, the two-leg run with the real `.env.local`):**
  leg 1 `run_foundation` → a PROVEN Foundation-ONLY box (`pvr.iptvsimple` ABSENT - JSON-RPC
  unknown-addon error AND no `addon_data/pvr.iptvsimple/` dir; zero content ids; skin closure +
  modv2plus + pvr.artwork + Outline-HD + weather.multi + autocomplete + all 12 repos + our proxy
  repo 2.2.1 installed/enabled; Setup self-uninstalled; the modv2plus boot service applied the
  patch on the next boot - `show_system_info_overlay` marker present). Host-stage:
  `build_iptv.py` from `.env.local` → Network 24 (m3u) **229 ch = 158/47/24** + Streamvision
  (portal-API) **331 ch = 214/100/12 + the 5-channel favorites** (5/5 dead icons healed);
  derived env (16 IPTV keys + `IPTV_STAGING_DIR`) staged for the driver. Leg 2 `run_iptv`
  (driver: patched the INSTALLED bootstrap copy - repo source untouched; the driver mirrors
  `run()`'s read-once/delete-only-on-ok contract) → log: the backend installed BY THIS LAYER,
  `instance 1/2: applied HOST-BUILT staged config (playlist=True groups=True)`, BOTH EPGs
  cached DURING the run (19 + 78 MB - the re-enabled clients started from OUR files), the live
  summary dialog read exactly "pvr.iptvsimple: installed / Instance settings: written", Setup
  self-uninstalled, env consumed. After the restart AND a further clean-shutdown
  quit+relaunch, JSON-RPC matches the builder EXACTLY: **158 / 47 / 24** (provider 1, display
  labels) + **214 / 100 / 12 + 24/7 Favorites = the 5 curated channels carrying live
  photo-tmdb icons** (provider 2) + **All channels 560 = 229+331**; both instance files intact
  (identity keys / `m3uPathType=0` / `tvGroupMode=2` / groups-only); **MOD V2 STILL the active
  skin** (no skin op anywhere in leg 2 - the no-skin-touch invariant live-proven); rendered
  screenshots show the patched trimmed home (top-bar weather) and a populated channel list with
  EPG data. The 5b·3 end state archived as `Kodi.archive-5b3-verified-*`; the live profile
  **RESTORED** to its pre-verify 5b·2 state (8 groups re-confirmed over JSON-RPC).
- **Leg-1 finding (a Foundation/5a race, NOT a 5b·3 regression - recorded for Phase 6
  hardening):** on a fresh box the "Keep this skin?" confirm can be DESTROYED ~270 ms after the
  live switch by script.skinshortcuts' first `buildxml` → skin-reload (its includes file does
  not exist yet), losing the race against `activate_skin`'s 500 ms poll → silent revert to
  stock Estuary (log-proven: confirm Init 22.530 → Deinit 22.799 → stock skin load 22.893).
  The 5a·2/5c live runs won this same race. Recovery used = the documented no-race mechanism
  (playbook §13: write `lookandfeel.skin` into `guisettings.xml` while Kodi is fully DOWN).
  Hardening candidates: a faster confirm poll, a set-and-reconfirm after the skinshortcuts
  settle, or an offline seed in the restart slot.

### Phase 5d - DONE (local; the Guided wizard + Model A lifecycle - the panel's keystone)

- **Landed:** `run_guided(box_env)` in `default.py` - the multi-gate, resumable wizard - plus the
  Model A lifecycle it rides on, and the shipped `run()` routing. The pieces:
  - **`tony7bones/setup/probes.py` (new library module, 100% covered)** - the installed-state
    done-probes the wizard resumes by (NEVER marker files): `foundation_done` (skin installed AND
    `getSkinDir()==SKIN_ID` - activation is part of done-ness so a keep-skin revert self-heals by
    re-offer), `iptv_done` (backend installed + at least ONE env provider's
    `instance-settings-<N>.xml` exists - a FILE check, never the async channel list; "at least
    one" because an unstaged portal-API provider can never land in-Kodi and "all" would re-offer
    forever), `addons_done` (per-id `is_installed` over base apps + curated video; origin
    deliberately NOT probed - the two peno64 apps ship blank origins by design, 5c-proven). All
    defensive: a raising primitive reads "not done" (worst case = re-offering an idempotent gate).
  - **The Model A gates** (`_guided_gate_foundation/_iptv/_addons`): each drives the SAME layer
    seam the proven runners drive - Foundation = `_foundation_core` (repos incl. our proxy + the
    skin/weather/menu/autocomplete layer; gate order puts Foundation FIRST so it must own the
    repos install, exactly like `run_foundation`), IPTV/Add-ons = bare `apply_iptv`/`apply_addons`
    - then summary → **restart ONLY on `ok`** (never restart into a failed gate; the menu returns
    for retry/exit) and **NEVER self-uninstall**. The Foundation gate's terminal op is
    activate-skin-IMMEDIATELY-then-restart (the keep-skin invariant, both cadences). The Add-ons
    cancel keeps the monolith's early-return contract (no summary/restart).
  - **The terminal ops** (`_guided_finish`): Finish (offered when all gates probe done) and the
    explicit, CONFIRMED "Remove Setup" menu entry both run: delete the per-device env →
    `self_uninstall` → ONE restart (the standard removal finaliser). These are the ONLY Guided
    self-uninstalls; Express keeps its end-of-run self-uninstall untouched.
  - **Env ownership (the panel rule realised):** the env SURVIVES every gate - gates never delete
    it - and is consumed only by Finish/Remove, BEFORE their restart. Each reopen's `run()`
    re-reads the surviving env, which is also what makes the wizard self-resume. The standalone
    runners' driver contracts (read-once + delete-only-on-ok) are UNCHANGED.
  - **`run()` routing - the Guided-reachability mechanism (⚠ OWNER-VETOABLE):** `SETUP_MODE=guided`
    (case-insensitive) in the per-device env → `run_guided`; the key absent or any other value →
    the byte-identical pre-5d Express one-tap. WHY env-key and not a launch dialog: a chooser
    (even timeout-to-Express) would break the proven unattended one-tap and reshape the
    characterization snapshot; the mode is a per-device PROVISIONING decision like everything else
    the env drives, and the provisioner already passes `.env.<device>` through verbatim - no
    provisioner change needed. Alternatives if vetoed: a timeout launch dialog, or a second
    launcher entry. (Suggested doc add the protect-hook kept me from making: a commented
    `# SETUP_MODE="guided"` block in `.env.device.example`.)
  - **Documented degradation (accepted):** env LOST mid-Guided-flow → the next launch reads no
    `SETUP_MODE` and runs EXPRESS, which idempotently completes every remaining layer and
    self-uninstalls (the proven end-state equivalence); only env-driven config is skipped until a
    re-push. Also: a DECLINED desktop per-gate restart lets the next launch offer the next gate
    without the restart between - accepted (the user explicitly declined; modules are re-entrant).
- **Conftest growth (additive only):** the fake `Dialog` gained `select` (recorded; scripted via
  `state["select_queue"]`, default -1 so an unscripted test can never run a gate) and `yesno`
  gained an optional `state["yesno_queue"]` consumed before the legacy behaviour - zero change to
  existing tests (full suite proves it).
- **Tested / mutation-proven:** +40 net new tests - `test_setup_probes.py` (14: each probe's
  done/not-done/half-state/never-raises shapes incl. the reverted-skin self-heal and the
  at-least-one-provider-file semantics), `test_run_guided.py` (23: offer order + env-gated IPTV
  skip + resume-after-crash re-offers; each gate's install + Model A no-self-uninstall + env
  survival + restart-only-on-ok; the Add-ons cancel contract; Finish's env→uninstall→restart
  ORDER + guarded missing-env Finish; confirmed/declined Remove Setup; decline-everything;
  `run()` routing incl. case-insensitivity and unknown-value→Express), `test_no_fork.py` (3 -
  the plan's keystone invariants: the spy test proving Guided and Express drive the IDENTICAL
  three `apply_*` exactly once with the SAME env object, Express = uninstall→activate→restart
  exactly once vs Guided = activate→restart at gate 1 + one restart per gate + uninstall ONLY at
  Finish; the REAL-ENGINE cumulative-Guided net-set == `EXPECTED_NET_INSTALLED` (the same frozen
  constant Express is pinned to - equivalence by transitivity, rebaseline-proof); and the
  head-to-head FULL-SUCCESS world diff - Express run vs Guided walk reduced to
  installed/disabled/settings/Skin-builtins/every-profile-file and compared EQUAL).
  **Six mutations run and killed:** self-uninstall re-added to a gate, a per-gate restart dropped,
  a forked layer call (different body/args), a gate consuming the env, the `run()` routing
  dropped, a step slid between activate_skin and its restart. **733 passed / 1 xfailed** (was
  693), `ruff` clean, secret-leak green; the characterization snapshot + `EXPECTED_NET_INSTALLED`
  pass **UNCHANGED** (Express byte-identical).
- **Coverage:** probes.py **100%**, bootstrap default.py **97%** (every uncovered line is a
  pre-existing defensive guard / `__main__`; ALL new Guided code covered). Generated files
  regenerated (second regen byte-identical); no version bumps (milestone push pending).
- **LIVE-VERIFIED (clean Kodi 21.3, fresh profile, real `.env.local` + host-staged IPTV build +
  `SETUP_MODE=guided`; driver = the installed copy's `BOX_ENV_PATH` pointed at a local env, repo
  source untouched):** the full multi-gate walk, every step over JSON-RPC with rendered-dialog
  screenshots -
  1. Launch → wizard rendered "Tony.7.Bones Setup - Guided" offering **Install Foundation** (+
     Remove Setup / Exit). Gate ran: repos + proxy repo extracted, origins stamped, sources,
     home-trim, env weather (5 locations, both keys); summary verbatim "Estuary MOD V2: installed
     … reopen Setup to continue"; `activate_skin` accepted keep-skin (no race this run); skin
     LIVE = `skin.estuary.modv2`. **Setup STILL installed + env intact after the gate (Model A
     proven)**; zero content (pov/pvr/apps all unknown to JSON-RPC).
  2. Clean quit + relaunch (macOS `RestartApp` no-op - the documented real restart) → skin
     SURVIVED, modv2plus boot service applied the patch (trimmed menu + marker), Setup still
     installed; relaunched wizard PROBED the box and offered **Install IPTV (live TV)** -
     screenshot shows the offer rendering ON the patched MOD V2 home. Gate ran: backend installed
     BY the layer, `instance 1/2: applied HOST-BUILT staged config`, summary "pvr.iptvsimple:
     installed / Instance settings: written". After the restart seam: **all 8 groups, counts ==
     the builder exactly - 158/47/24 + 214/100/12 + 5 favorites, All channels 560** -
     restart-survival of the clobber class re-proven; env still intact.
  3. Relaunch → wizard offered **Install Add-ons**. Gate ran: `stamped origin on 20 add-on(s)`,
     dailymotion install-then-DISABLED, `7 RSS feed(s)` written; summary honest "Repos: 12/12 /
     Apps: 2/2 / Video add-ons: 4/4". After the restart: POV 6.06.06 / The Loop 7.9 / Sports HD
     0.1.85.1 / YouTube 7.4.3 installed+enabled with origins (kodifitzwell / loop / bugatsinho /
     xbmc.org×2), dailymotion 2.4.4 disabled, POV `GetDirectory` = 11 real items, rendered home =
     patched trimmed menu + top-bar weather (64°F) + live RSS ticker. **Each gate landed on a
     complete working box.**
  4. Relaunch → wizard offered **Finish - setup is complete, remove Setup** → Finish CONSUMED the
     env, removed the add-on dir (`self-uninstall: removed …`), and after the finaliser restart
     Setup is fully de-registered (JSON-RPC unknown; 0 rows in Addons33.db) while the box stays
     the complete build (MOD V2 + 560 channels + content). The decline path was also live-hit
     (an escaped wizard exits cleanly, nothing changed, Setup + env intact).
  - **Express regression - equivalence argued, stated honestly:** no fresh full Express live run
    was made. The argument: the `run()` diff is EXACTLY a 3-line branch guarded on a key absent
    from every shipped env; the runtime characterization snapshot (which drives `run()` whole) and
    `EXPECTED_NET_INSTALLED` pass UNCHANGED; the routing unit tests pin no-key/unknown-value →
    `run_express`; and the no-fork world-diff proves the shared bodies. The pre-5d Express path
    itself is the hardware-proven 5b·2/5c state.
  - **Live-verify environment notes (recorded):** (a) Kodi's screenshot action on a fresh profile
    pops a File-Browser picker (no `debug.screenshotpath`) - seed the setting first; a modal
    stacked that way can leave the underlying select dialog focus-wedged (keys arrive,
    "action is Select", nothing fires) - escape + relaunch recovers; drive list dialogs with
    `Input.ButtonEvent` (key-level), not `Input.Select`. (b) The desktop per-gate restart PROMPT
    after the Foundation gate's live skin switch can be destroyed by the skinshortcuts reload
    (same dialog-destroy class as the 5b·3 keep-skin race) - harmless here (= "Later"; macOS's
    real restart is the quit+relaunch anyway), but it feeds the same Phase 6 hardening item.
    (c) The redwizard repo index 404'd server-side mid-run (`index load failed … redwizardrepo`)
    with zero impact (12/12 repos still landed from the served zips; closures resolved from the
    others) - the defensive multi-index design absorbing a real outage.
  - End state archived as `Kodi.archive-5d-verified-20260610-010656`; the live profile **RESTORED**
    to the pre-verify 5b·2 box (8 groups + MOD V2 re-confirmed over JSON-RPC).
- **Deferred to Phase 6:** the keep-skin race hardening (now with the restart-prompt variant
  above); per-gate Android notification copy ("box is complete - reopen to continue") and the
  real-Stick wipe-and-run matrix incl. the Guided manual-reopen UX; version-guard +
  `assert_box_complete`; optionally surfacing Guided without an env (a second launcher entry)
  if the owner wants a no-provisioner path; Model C (resume-notification service) stays v2.

### Phase 6 - DONE (local; harden the computer-setup track: the keep-skin race fix, version guard, `assert_box_complete`, CI gates)

> _(Provenance note: most of this phase's implementation was inherited from a session that was
> killed mid-live-verify - the hardened `activate_skin` + `_wait_skin_quiescent`, the
> `SETUP_API`/`REQUIRED_SETUP_API` version guard, `env_has_iptv`'s move to `setup/env.py`,
> `box_state`/`_addons_missing`/`missing_required_imports`/`assert_box_complete`, the
> `_guided_finish` wiring, the state-aware conftest skin fake, and the new
> `test_version_guard.py` + probe/module tests. The resuming session adversarially QA'd that
> work (one real bug found + fixed, below), added the system-tree/registry closure-walk fix,
> the restart-prompt autoclose bound, the CI gates, and ran ALL the live verification.)_

- **The keep-skin race fix (`tony7bones/system.py: activate_skin`)** - the 5b·3-recorded race
  (the "Keep this skin?" confirm DESTROYED ~270 ms post-switch by script.skinshortcuts' first
  `buildxml` ReloadSkin → silent revert to stock) and the 5d-recorded variant (the per-gate
  restart PROMPT destroyed by the same reload) are both closed, by mechanism, not luck:
  - **200 ms confirm poll** (the old 500 ms poll lost the ~270 ms destroy outright), tracking
    skin live-ness EVERY iteration - including while the confirm is visible (Kodi switches
    live, THEN shows the confirm; recording live-ness only in the no-dialog branch misread a
    destroyed-while-visible confirm as "never went live" - caught on the live box).
  - **Early revert detection** - the poll exits as soon as the skin was-live-then-flipped-back
    (the confirm is gone; stop waiting for it).
  - **The fundamental fix: verify-then-re-assert** - after the settle the END STATE is checked
    via `getSkinDir()`; a non-stuck switch is re-asserted (bounded, 3 attempts). The re-assert
    runs after the destructive first build (its includes file now exists), so the second
    confirm survives and commits. A set that never goes live at all is a REJECTED set (skin not
    registered/enabled) - bail after one attempt, loud. `activate_skin` now returns True/False.
  - **`_wait_skin_quiescent`** - inside the activation seam, a bounded (~15 s) wait for the
    skin's `script-skinshortcuts-includes.xml` (+1 s grace for the build's ReloadSkin), so the
    caller's NEXT dialog (the restart prompt) renders AFTER the blast radius. Skipped instantly
    when skinshortcuts is not installed; never raises; never blocks activation.
- **The version guard (`tony7bones.setup.SETUP_API` = 1 / bootstrap `REQUIRED_SETUP_API` = 1 +
  `_require_setup_library()`)** - a too-old library paired with a too-new bootstrap (cross-gate
  update skew, or a sideload bypassing `<requires>` - our own direct-extract path does exactly
  that) now fails LOUD at launch: one honest "update the library from the repository" dialog +
  ERROR log + RuntimeError, BEFORE the real library imports (pinned structurally by test).
  Bump both when the bootstrap starts needing a new library capability.
- **`assert_box_complete` (`tony7bones.setup.probes`)** - the plan's verification primitive:
  `box_state()` (foundation/iptv/addons done-ness; iptv `None` when the env expects none),
  `_addons_missing()` (names the gaps), `missing_required_imports()` (the dependency-closure
  walk over user add-ons), and `assert_box_complete(box_env, layers=…)` which raises NAMING
  exactly what is missing or returns the verified state. Wired into `_guided_finish` -
  INFORM, never block (an explicit Remove Setup on a half-built box stays legal).
  - **QA find (real bug, fixed in the resume):** the inherited closure walk checked only
    `special://home/addons/` and falsely "dangled" SEVEN imports on the owner's real complete
    box (`metadata.common.allmusic.com/musicbrainz.org/theaudiodb.com` ×2 consumers +
    `script.module.pil`) - all bundled INSIDE Kodi at `special://xbmc/addons/`, which never
    appear in the user tree. Fixed: presence = user tree ∪ bundled system tree, with an
    `is_installed` registry fallback (this probe informs, so a false alarm is worse than a
    miss); system add-ons' own imports are not walked. Offline-validated against the real
    box's archived profile (registry stubbed closed → dangling `[]`) and live in-Kodi.
- **The restart-prompt autoclose (resume addition, live-forced):** the desktop restart prompt
  now carries `autoclose=20000`. Live finding behind it - a THIRD dialog-destroy window, new
  in the hardened flow: with the skin committed and live BEFORE the restart, the modv2plus
  boot service auto-applies its patch ~45 s in, ending in a skinshortcuts rebuild + ReloadSkin
  that DESTROYED the still-open restart prompt on the live Guided run - and Kodi SEGFAULTED
  tearing the modal down mid-reload (`.ips` captured 02:41:01.07, the exact destroy moment).
  The end state survived regardless (lookandfeel.skin already persisted; the relaunched
  instance booted MOD V2, "[mod v2+ service] nothing to do", probes self-heal by design), but
  an unbounded modal in a reload-prone window is now structurally disallowed. Observed live:
  the autoclose answer is True → the restart proceeds (the one-tap completes itself
  unattended); a False would be the documented "Later" self-heal. Both safe.
- **CI gates (`.github/workflows/generate_repo.yml`)** - the workflow now also runs on
  `modular-setup` pushes; the version-consistency step is conditioned to main only (a feature
  branch legitimately carries unbumped versions until its milestone push); and a NAMED
  "Setup invariant gates" step re-runs `test_no_fork.py` + `test_version_guard.py` +
  `test_setup_probes.py` so a broken keystone invariant fails as its own loud check.
- **Tested / mutation-proven:** suite **767 passed / 1 xfailed** (was 733), `ruff` clean,
  secret-leak green, generator deterministic. New/inherited tests: the activate_skin race
  shapes (verified-happy-path single set; destroyed-confirm revert → re-assert; the
  destroyed-WHILE-VISIBLE live scenario; honest False when nothing sticks; fast-bail on a
  rejected set; the 200 ms poll pin; the quiescence helper's skip/bounded/never-raises/seam
  shapes), the version guard (compatible pairing pin, too-old API, missing modules, order pin,
  dialog-failure-doesn't-mask), box_state/closure-walk/assert_box_complete (incl. the bundled
  system tree, system-addons-not-walked, registry fallback), the autoclose bound pin.
  **Eight mutations run, all killed** (500 ms poll revert; attempts=1; verify dropped;
  quiescence call dropped; guard comparison dropped; guard raise dropped; system-tree union
  dropped; registry fallback dropped; autoclose dropped). One attempted mutant proved
  functionally equivalent (saw_live tracking moved but still recorded + the `accepted` flag
  guards the bail) - not a gap; the historical bug shape is killed by the
  destroyed-while-visible test. Coverage: all new code covered (probes 94% file-wide, the
  misses are pre-existing defensive `except` arms; system/env new lines 100%; the guard fully
  covered by `test_version_guard.py`).
- **LIVE-VERIFIED (clean Kodi 21.3, fresh profiles, real `.env.local`):**
  1. **The race, natural run (Guided Foundation gate on a fresh box):** includes file absent →
     skin switch 02:40:12.497 → skinshortcuts first build started 12.551 → **keep-skin
     accepted 12.553** (the 200 ms poll WON the exact race the 500 ms poll lost in 5b·3) →
     build done 12.829 → verify + quiescence → "**active and committed (attempt 1)**" 15.561 →
     the restart prompt rendered AFTER the blast radius (the 5d victim, protected). Then the
     third-window finding above (segfault AFTER completion; end state intact + persisted -
     guisettings already carried modv2; relaunch booted MOD V2 patched).
  2. **The race, FORCED lost-confirm (the re-assert proof):** a local-only driver add-on
     recreated the fresh-box precondition (includes deleted, hashes cleared) and SUPPRESSED
     activate_skin's first SendClick so the real skinshortcuts reload destroyed the unaccepted
     confirm. Log-stamped: attempt 1 "accepted" (the suppressed click - the code believes the
     dance) → skin REVERTED → "**did not stick (attempt 1/3) - re-asserting**" → attempt 2
     confirm survived (includes now built) → accepted → "**active and committed (attempt 2)**"
     → returned True, final skin `skin.estuary.modv2`. The verify caught a revert the dialog
     dance missed - the fundamental fix, live.
  3. **The fresh full Express proof (closing the standing "Express not live-proven since the
     rewrite" gap):** wipe → stage host-built IPTV artifacts (`build_iptv.py` from
     `.env.local`: 229 ch/3 groups + 331 ch/4 groups incl. 5 healed favorites) + derived env
     (no `SETUP_MODE`) → ONE unattended `run()`: repos + apps + curated video installed +
     origins stamped (26+5), BOTH providers' staged config applied in-run, summary,
     self-uninstall, keep-skin accepted + committed (attempt 1), restart prompt **autoclosed
     at ~17 s answering True** (`restart: RestartApp()` - a no-op on macOS) - and the
     modv2plus destroyer reload arrived AFTER, finding no modal: NO crash. After the real
     restart (clean quit + relaunch): MOD V2 active on Home, **all 8 groups, counts == the
     builder exactly (158/47/24 + 214/100/12 + 5 favorites, All channels 560)**, POV
     `GetDirectory` = 11 real items, all four video apps enabled with origins
     (kodifitzwell/loop/bugatsinho/xbmc.org), dailymotion installed-then-DISABLED, 7 RSS
     feeds, bootstrap fully de-registered, env consumed. **`assert_box_complete` run IN-KODI
     on this box: PASSED `{foundation: True, iptv: True, addons: True}`, dangling `[]`.**
     Rendered-home screenshot captured (patched trimmed menu + top-bar weather + thin clock).
  - The Express end state archived as `Kodi.phase6-*` profiles; the owner's box restored from
    `Kodi.backup-6-pre-20260610-020420` (see TASKS).
- **Fire TV (queue item 3) - reachability CHECKED, matrix DEFERRED pending owner go-ahead:**
  a real Fire TV smart TV IS adb-reachable right now (192.168.7.84:5555, AFTHA001 "hailey" -
  a 4K UHD Fire TV smart TV, NOT a stick - device name "Bedroom TV") - but it is a provisioned
  LIVING-ROOM box, and the wipe-and-run matrix
  (`_tools/provision-kodi.sh <device>` wipe → Express one-tap; then wipe → `SETUP_MODE=guided`
  → the manual-reopen UX per gate) is destructive. Commands are ready in the provisioner +
  `firetv.sh`; run it on an owner-designated stick (travelstick) at the milestone.
- **Owner decisions recorded:** the computer-setup (provisioner-driven) track is COMPLETE as
  of this phase; `SETUP_MODE=guided` (the env-key mechanism) STAYS as shipped in 5d; the
  no-computer-setup track (running Setup with no provisioner/env at all) is a separate
  follow-on plan doc - referenced here as a placeholder only, lands on its own.

### Phase 6 addendum - the Fire TV wipe-and-run matrix (DONE; Bedroom box, owner-authorized) + the SLOW-BOX keep-skin race found & fixed

> _(Provenance: this matrix run was itself interrupted once - the driving agent died mid-Leg-B
> Foundation gate. The interruption became data: the in-flight gate ran to COMPLETION
> unattended on the box (the run does not depend on its driver) and parked on its summary
> dialog, where the resuming agent found it minutes later. Model A's installed-state probes
> then re-offered exactly the one gate the interrupted run had genuinely lost (the reverted
> skin, below) - no marker files, no stale state: the self-heal exactly as designed, proven on
> real Android by accident.)_

Device: the owner-authorized Bedroom Fire TV (AFTHA001, `192.168.7.84:5555`, Fire OS; Kodi
21.3 ARM 32-bit, data in the `Android/data` sandbox - no relocation needed). Both legs ran
with `USE_LOCAL=1`: the live site serves main's OLD monolith bootstrap, so an unpushed branch
CANNOT be installed the production way (file-manager → repo zip) - the provisioner's
working-tree push is the documented branch-verify mode. The only adb-driven "user" shortcuts:
`input keyevent 23` (the remote's select/OK press) and `Addons.ExecuteAddon` (= clicking the
Setup tile); everything else was the shipped flow.

- **THE REAL ANDROID BUG (Leg B's first Foundation gate, log-stamped): the slow-box keep-skin
  race.** On this stick script.skinshortcuts' FIRST menu build for MOD V2 runs >14 s cold -
  longer than one whole `activate_skin` attempt - so the Phase 6 premise ("a re-assert runs
  after the destructive first build is over") never came true: each re-assert fired straight
  back INTO the still-running build (whose skin reload it re-kicks), each confirm was
  destroyed unaccepted ~200 ms AFTER our SendClick had already logged "accepted"
  (destroyed-unaccepted = "No" = revert), and all 3 attempts burned inside ONE build window:
  `accepted keep-skin` → `did not stick` ×3 → `FAILED to keep skin.estuary.modv2 after 3
attempts` → the gate restarted onto STOCK Estuary. **Fix (`tony7bones/system.py`):** between
  attempts `activate_skin` now WAITS for skinshortcuts quiescence (`_wait_skin_quiescent`;
  bound raised 15 s → 30 s) BEFORE re-asserting, so the next confirm renders after the
  destroyer finishes. Mutation-proven test (the slow-build timeline: without the wait all 3
  attempts land in-window → False; with it attempt 2 sticks at exactly 2 sets) + the bound pin
  updated - suite **768 passed / 1 xfailed**, ruff + secrets green. **Live re-verify:** fixed
  module pushed to the box, includes file deleted (recreating the fresh-box condition), the
  wizard re-offered Foundation (the self-heal) and the re-run committed - `active and
committed (attempt 1)` (the warm rebuild won naturally) and `lookandfeel.skin =
skin.estuary.modv2` PERSISTED in guisettings across the clean Quit.
- **Leg B - Guided manual-reopen UX: COMPLETE (all four offers walked as a remote user).**
  `SETUP_MODE=guided` was injected into the DERIVED env only - a key-level diff proved the
  pushed env == `.env.bedroom` modulo exactly {DEVICE_IP dropped, DEVICE_NAME rewritten,
  IPTV_STAGING_DIR appended, SETUP_MODE appended}; **`.env.bedroom` itself was never
  modified**. Verbatim Android copy - wizard title `Tony.7.Bones Setup - Guided`; offers
  `Install Foundation (Estuary MOD V2 skin + repositories)` / `Install IPTV (live TV)` /
  `Install Add-ons (curated content)` / `Finish - setup is complete, remove Setup`, each above
  `Remove Setup` and `Exit (keep Setup)`. Gate summaries: Foundation `Estuary MOD V2:
installed / Repositories + sources installed. / Kodi will restart - reopen Setup to
continue.`; IPTV `pvr.iptvsimple: installed / Instance settings: written / …`; Add-ons
  `Repos: 12/12 / Apps: 2/2 / Video add-ons: 4/4` - that dialog's 5th line (the restart
  notice) is CLIPPED off the dialog under MOD V2 at 1080p (UX observation, document-only).
  The Android restart seam is the Phase 6 autoclose, live-confirmed: notification `Setup
complete - closing Kodi. Reopen it to finish.` + clean `Quit()`, prompt-free, ~4 s end to
  end. Each manual reopen landed on a complete working box (skin-only → +live TV → full);
  IPTV verified mid-walk (all 8 groups, counts == builder: 158/47/24 + 214/100/12 + 5
  favorites with 5/5 icons, All channels 560). Finish: `finish: box verified complete
{'foundation': True, 'iptv': True, 'addons': True}` - `assert_box_complete` IN-KODI on the
  real box - then env consumed, self-uninstall, clean Quit.
- **Leg A - Express one-tap: COMPLETE (second run; the first run caught a PROVISIONER bug).**
  The provisioner's "waiting for Kodi to close itself" bound was 60 s, but the real-Fire-TV
  terminal seam (summary OK → cold first MOD V2 load + first skinshortcuts build + the
  keep-skin dance - now deliberately build-waiting - + close notice + clean Quit) runs longer:
  the bound expired MID-DANCE and the fallback DEVICE REBOOT killed Kodi before the clean
  shutdown flushed `lookandfeel.skin` - box back on stock (everything else installed, Setup
  already self-uninstalled; the no-clean-shutdown settings-loss class, again). Fixed in
  `_tools/provision-kodi.sh`: the bound is now ~4 min with the failure mode documented inline.
  The clean re-run: wipe → seed → host IPTV build/stage → ONE unattended Express → `Kodi
closed cleanly - no force-kill needed` + `Skin persisted as MOD V2` + patch/menu built; the
  box then verified end-to-end over JSON-RPC after a FULL DEVICE REBOOT (the restart-survival
  proof): MOD V2 active on Home, weather `Sacramento, California` 63°F, RSS on + ticker live,
  POV 6.06.06 / The Loop 7.9 / Sports HD 0.1.85.1 / YouTube 7.4.3 all enabled, dailymotion
  2.4.4 installed-DISABLED, origins kodifitzwell / loop / bugatsinho / xbmc.org×2, IPTV
  counts == builder again, bootstrap de-registered, env consumed, rendered patched home
  captured. The box was left ON, at Home, fully working (the owner's hard requirement).
- **Android observations (document-only):** (1) ONE post-Foundation clean Quit was followed by
  an AUTOMATIC Kodi relaunch ~20 s later - observed once, never reproduced; don't design
  against it. (2) The first boot after the Add-ons gate wedged the Python invoker pool (Kodi
  force-killed a hung plugin.video.youtube service; later `ExecuteAddon` calls returned OK but
  never spawned an invoker) - a user-style close-and-reopen cleared it. (3) After the Leg A
  provision finished, Kodi exited and CRASH-LOOPED during GL init on relaunch (the
  provisioner's documented GPU-wedge class); a device reboot recovered it, end state fully
  intact. (4) `GUI.ExecuteBuiltin` is NOT exposed over JSON-RPC on this build -
  `firetv.sh`'s `_builtin` helper cannot work; drive the GUI with key events /
  `Addons.ExecuteAddon`. (5) The one-time manual steps remain by design (PVR DB flags):
  hide "All channels", TV sort-by-name.
