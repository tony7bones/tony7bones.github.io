# Plan — Modular "0-1-2" Setup (Foundation / IPTV / Add-ons)

> Status: **DESIGN — panel-reviewed, nothing built.** Reviewed in parallel by three
> specialist agents (Architecture, QA/testability, Kodi-runtime). This doc is the
> orchestrated synthesis: the architecture, the panel-resolved decisions, the risks, and
> the prioritized action backlog. No code until the P0 decisions are confirmed.

## Goal

Re-architect the Tony.7.Bones Kodi setup from a **monolithic one-shot** into a **modular,
layered, opt-in installer**. Today `script.tony7bones.bootstrap/default.py` `run()` is a
~55-line procedure that installs everything (repos + apps + curated video + skin + config)
in one unattended shot, restarts once, and self-uninstalls. We want three independent
layers where **each leaves a complete, working box** and the user can stop or continue at
each gate — driven by the same modules whether run as a Guided wizard or an Express one-shot.

## The 0-1-2 model

| Layer | Name                 | Contents                                                                                                                                                              | Stop here =                                 |
| ----- | -------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------- |
| **0** | **Foundation**       | Kodi + Estuary MOD V2 skin + modv2plus patch (+ the skin's required dep closure: `script.module.pvr.artwork`, skinshortcuts, image.resource.select, Outline-HD icons) | A pristine, branded Kodi — **zero content** |
| **1** | **IPTV** (opt-in)    | `pvr.iptvsimple` + inputstream clients + `.env`-driven instances                                                                                                      | Branded Kodi + _your_ live TV               |
| **2** | **Add-ons** (opt-in) | curated repos + base apps + video add-ons (POV, Loop, Sports HD, YouTube) + weather/RSS                                                                               | The full box                                |

Each layer is its own complete box; the next is purely additive.

## Core principles

- **Modules are the single source of truth.** Three re-entrant functions live in the shared
  library `script.module.tony7bones`: `apply_foundation`, `apply_iptv`, `apply_addons`.
  **Both** the Guided wizard and the Express one-shot call the _same_ functions — no forked
  install logic, ever.
- **Restart-as-seam — and it's actually "activate-skin-then-restart" as one
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
    ok               # reached a complete state? (success/degraded — orchestrator checks BEFORE restarting)
    already_done     # re-entry no-op'd everything
    installed        # {addon_id: state}
    failed           # {addon_id: reason}
    needs_skin_activation  # foundation sets this — a REQUEST
    needs_restart          # a REQUEST; orchestrator owns the actual restart
```

```python
def apply_foundation(env, *, dialog=None, log) -> LayerResult   # skin closure + modv2plus + file-sources + home-trim; NO content, NO PVR; sets needs_skin_activation
def apply_iptv(env, *, dialog=None, log) -> LayerResult         # install pvr.iptvsimple closure + write/enforce instance-settings-N.xml (N providers)
def apply_addons(env, *, dialog=None, log) -> LayerResult       # curated repos/apps/video + origin stamp + install-then-disable + weather/RSS
```

- **`env` is passed in, never read inside a module.** The orchestrator reads the per-device
  env once, passes the dict down, and owns the **read-then-delete** — deleting only after
  the _last_ layer of the session (today `_configure_box` deletes it mid-run, which would
  starve a later gate in a multi-session Guided flow).
- **Idempotency detection** per layer (all primitives already exist):
  - Foundation: `is_installed(SKIN_ID)` + `is_installed(MODV2PLUS_ID)` + skin enabled; _activated_ = `getSkinDir()==SKIN_ID`.
  - IPTV: `is_installed("pvr.iptvsimple")` + instance-settings keys already correct (file check — **not** a populated channel list, which is async).
  - Add-ons: per-id `is_installed(aid)` + non-blank origin.

## Panel-resolved decisions

These were independently surfaced and converged on by ≥2 of the three lenses:

1. **Self-uninstall lifecycle — the keystone (all three flagged as #1 blocker).** A
   self-deleting one-shot cannot support multi-gate/resume — delete after Gate 0 and there's
   no body to run Gate 1. **Resolution (Model A for v1):** the orchestrator add-on _persists_
   across gates (its home tile _is_ the "continue setup" affordance) and self-uninstalls
   **only** on terminal Finish / completing the last layer. **Express** keeps today's clean
   end-of-run self-uninstall; **Guided** keeps the add-on and offers an explicit "Remove
   Setup." The shared library (`xbmc.python.module`, invisible) is **always** left installed.
   _v2 polish:_ Model C — a tiny permanent boot service surfaces a "Continue setup"
   notification after reopen (reuses the proven modv2plus service pattern), letting the
   heavy orchestrator stay transient.
2. **`pvr.iptvsimple` moves from Foundation (Layer 0) into `apply_iptv` (Gate 1).** Today
   it's in the base `ADDONS` — so Layer 0 isn't actually content-free until it moves. This
   creates a deliberate cross-gate dependency: `apply_iptv` must install its own PVR backend
   (or fail loudly), never silently write instance-settings for a missing add-on.
3. **IPTV is two halves.** The host-side **build** (`build_iptv.py` on the `iptv` branch:
   fetch from provider portals, curate groups/favorites, m3u vs xtream modes) belongs in the
   **provisioner**, upstream of Setup — it needs provider creds and runs on the Mac. The
   in-Kodi **apply** (`apply_iptv`) is the thin consumer: install the PVR backend + write/
   enforce the staged `instance-settings-N.xml` + `customTVGroups-*.xml`. Generalize the
   apply side to **N providers** (today it's hard-wired to instance-1/Network24).
4. **Express is the Fire TV default; Guided is the advanced/power path.** Kodi can't
   self-restart on Android — every gate restart is a manual close+reopen. Express = **one**
   reopen; Guided = up to **three**. Each gate's reopen must land on a _complete, working
   box_ so it never reads as "did it freeze?"
5. **Per-gate install ritual stays intact, not collapsed.** Each add-on-installing gate does
   its own direct-extract (proxy/GitHub-only deps first) → `UpdateLocalAddons` → 3s settle →
   enable → enable source repos → stamp origins → restart. Plus a **version-guard**: skip
   extracting a shared `script.module.*` when the installed version ≥ the resolved version,
   so a later gate can't clobber Foundation's working module with an older shadow.

## Build approach — Hybrid (adversarial-review verdict)

A second, **adversarial** architecture pass was run specifically to steelman a from-scratch
"white canvas" rebuild and find what the current base genuinely costs. Verdict: **hybrid —
fresh orchestrator + fresh module boundaries, reusing the proven engine verbatim.** Not full
greenfield (it re-pays hardware-proven debts for no engine-layer gain); not pure
decompose-in-place (it would graft a resumable wizard onto a self-deleting host).

**The exact line — what we keep, refactor, and write fresh:**

| Code                                                                                        | Disposition                                                                               | Why                                                                                                                                             |
| ------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------- |
| `net.py`, `index.py`, `install.py`, `repos.py`, `system.py`                                 | **Reuse as-is**                                                                           | Hardware-earned engine. `install_selection` is _already_ the module contract. `activate_skin`/`restart_kodi` encode blood-bought Fire TV fixes. |
| install/config bodies (`_install_*`, `_configure_box` writers, `parse_env`/`read_box_env`)  | **Reuse-but-refactor** → move into `apply_foundation/iptv/addons` returning `LayerResult` | Correct + idempotent already; only their home and the env-ownership are wrong.                                                                  |
| `run()` tail (summary, self-uninstall placement, activate+restart ordering, single cadence) | **Write fresh** as the orchestrator seam + state machine                                  | The only genuinely wrong-shaped code (~55 lines).                                                                                               |
| orchestrator add-on, `LayerResult`, done-probes, cadence/lifecycle/resume                   | **Write fresh**                                                                           | Net-new; no legacy to preserve.                                                                                                                 |
| fake-Kodi `boot` fixture                                                                    | **Reuse-but-relocate** → `conftest.py`                                                    | Keystone test asset; extract, don't rebuild.                                                                                                    |

**Steal greenfield's one real win — a `KodiHost` port** (an interface wrapping the `xbmc*`
calls) **for the NEW code only**: the orchestrator + layer modules get plain
constructor-injected fakes (retiring the fragile `sys.modules` monkeypatch for new code),
while the proven engine keeps its existing, already-tested harness. One real upgrade, zero
churn to proven code.

**Discipline:** rebuild the lifecycle (Model A persistence + env-ownership) **before** Guided
ships — never graft a resumable wizard onto a self-deleting host. Target sublibrary layout:
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

- **`conftest.py` shared harness** — extract the `boot` fake-Kodi fixture from
  `test_bootstrap.py` into a reusable fixture (keystone for all modular tests).
- **Characterization golden snapshot** of the current `run()` before any refactor, as the
  "Express must reproduce the monolith" oracle.
- **Idempotency tests per module** — run twice; assert written files are **byte-identical**
  and zero new `.zip` fetches on the second run (current tests check counts, not bytes).
- **`test_no_fork.py`** — inject module spies; assert Guided and Express drive the _identical_
  `(module, args)` sequence; assert Guided = per-gate restart, Express = exactly one.
- **Seam-guard test** — grep each module for `RestartApp`/`Quit`/`restart_kodi` → assert
  absent (restart lives only in the orchestrator).
- **`assert_box_complete(state, layer)`** post-conditions, incl. a dependency-closure walk
  (no dangling required import after any layer).
- **Partial-state recovery tests** — pre-seed extracted-but-not-installed / installed-subset.
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
   ownership move, N-provider IPTV) — each behind its own failing-then-passing test.

## Action backlog

**P0 — confirm/unblock before any module split**

- [ ] **Confirm Model A** self-uninstall lifecycle (orchestrator persists; uninstall only on Finish). _(Arch, Kodi)_
- [ ] Move env **read-then-delete** out of `_configure_box` into the orchestrator. _(Arch, QA)_
- [ ] Move `pvr.iptvsimple` + inputstream closure from Foundation `ADDONS` into `apply_iptv`. _(Arch, QA, Kodi)_
- [ ] Encode the **activate-skin-is-last-before-restart** invariant (both cadences) + a test. _(Arch, Kodi)_
- [ ] `conftest.py` shared fake-Kodi harness + characterization golden snapshot of `run()`. _(QA)_

**P1 — the decomposition**

- [ ] Add `LayerResult` + `apply_foundation`/`apply_iptv`/`apply_addons` to the library (behavior-preserving extraction). _(Arch)_
- [ ] Refactor `run()` → `_orchestrate(layers, env, cadence)`; Express = the existing tail generalized. _(Arch)_
- [ ] Add the Guided entry point (installed-state resume probe + next-undone-gate wizard). _(Arch, Kodi)_
- [ ] `test_no_fork.py` + per-gate-restart placement test; seam-guard grep test. _(QA)_
- [ ] Per-module idempotency byte-equality tests; `assert_box_complete` + closure walk. _(QA)_
- [ ] Done-state probe library fns — `foundation_done()/iptv_applied()/addons_done()` sharing modv2plus's `_is_applied/_menu_is_ours/_settings_applied`; tolerate "applied but async-in-progress." _(Kodi)_

**P2 — IPTV gate composition (depends on the `iptv` branch)**

- [ ] Land `build_iptv.py` into the **provisioner** (host-side build), not the add-on; port `test_build_iptv.py` to main. _(Arch, QA)_
- [ ] Generalize `apply_iptv` / `_ensure_iptv_custom_tv_groups` to **N instances** (loop providers). _(Arch, Kodi)_
- [ ] Cross-gate dependency test: `apply_iptv` with no `pvr.iptvsimple` → self-install or loud fail, never silent. _(QA, Kodi)_
- [ ] IPTV done-detection = instance-settings written+enabled (not channel count). _(Kodi)_

**P3 — guardrails & hardware**

- [ ] Version-guard shared `script.module.*` across gates (skip if installed ≥ resolved). _(Kodi)_
- [ ] Per-gate notification copy: "box is complete — reopen to continue." _(Kodi)_
- [ ] CI gate: no-fork + per-module idempotency + seam-guard as required checks. _(QA)_
- [ ] Wipe-and-run matrix doc (extend `local-kodi-verification.md`); mandatory before any modular release. _(QA, Kodi)_
- [ ] Evaluate **Model C** resume-service for v2. _(Kodi)_

## Open decisions for the owner

1. **Model A confirmed for v1?** (orchestrator persists, self-uninstall only on Finish; Model C as v2 polish) — panel strongly recommends yes.
2. **Express as Fire TV default, Guided as advanced?** — panel recommends yes.
3. **Sequencing:** merge the `iptv` branch (`build_iptv.py`) to `main` _before_ the IPTV gate work, or keep it parallel and integrate at P2? (P0/P1 don't need it; P2 does.)

## Dependencies

- The IPTV gate (P2) consumes the `iptv` branch's `build_iptv.py` + `test_build_iptv.py` and
  the customization playbook. P0/P1 are independent of it.
- The orchestrator-owned terminal seam relies on the proven `system.py` primitives
  (`activate_skin` w/ the 10100/control-11 accept, `restart_kodi`, `self_uninstall`).

## Execution plan & phase gate

Build proceeds in **sequential, gated phases** — each phase builds on the prior phase's
committed result, so phases do NOT run in parallel (that's what keeps the suite green at
every step). Parallelism happens **within** a phase: the orchestrator fans out agents
(implementer + test-author + an adversarial QA test-completeness reviewer) on independent
pieces, integrates them, runs the gate, and commits. (These execution **phases** are the
delivery order; the P0–P3 tags in the Action backlog are priority/owner labels scheduled
into them.)

### Phase Gate — Definition of Done (every phase)

1. **Documented** — this plan / a phase-log updated: what changed, why, what's now true.
2. **Thoroughly tested** — unit tests for all new/changed code; idempotency tests where
   re-entrant; invariant tests (no-fork, seam-guard) where applicable; pure refactors pinned
   against the characterization golden snapshot.
3. **Coverage** — new modules ≥ 90% line coverage (the bar `build_iptv.py` hit), with a
   `--cov term-missing` report and every uncovered line justified.
4. **Green everywhere** — full `pytest _tools/ -q` + `ruff` + generated-files staleness +
   the pre-push gate all pass.
5. **Real-device check** — phases that change runtime behavior are wipe-and-run verified on
   the **local Kodi 21.3 Omega** (JSON-RPC `127.0.0.1:8080`). The Mac Kodi faithfully covers
   skin install/activation + "Keep this skin?" revert, dependency-closure installs, origin
   stamping, instance sync, and idempotency. It does **not** cover Fire-OS-only behavior
   (desktop Kodi _can_ self-restart; Android can't) — the manual-reopen UX and scoped-storage
   paths get a final **real Fire TV** pass before any release.
6. **Checked in** — committed + pushed with a phase-tagged message before the next phase opens.
7. **QA completeness review** — an adversarial QA agent reviews each gate for what the tests
   _miss_ before the phase is accepted.

### Phases

| Phase           | Deliverable                                                                                 | Runtime change? → device gate               |
| --------------- | ------------------------------------------------------------------------------------------- | ------------------------------------------- |
| **0**           | Extract `boot` fixture → `conftest.py`; characterization golden-snapshot of current `run()` | none — snapshot + unit only                 |
| **1**           | Lift `env` read-then-delete into orchestrator ownership                                     | none                                        |
| **2**           | `apply_foundation/iptv/addons` + `LayerResult` + `KodiHost` port (behavior-preserving)      | none                                        |
| **3**           | Move `pvr.iptvsimple` → Gate 1 (first intentional behavior change)                          | yes → local Kodi                            |
| **4**           | Fresh orchestrator + Express path (releasable end-state == monolith)                        | yes → local Kodi                            |
| **5**           | Model A lifecycle + Guided + invariants (no-fork, seam-guard, idempotency)                  | yes → local Kodi (+ Fire TV for restart UX) |
| **6**           | Harden: version-guard, `assert_box_complete`, CI gates, wipe-and-run matrix                 | yes → local Kodi + Fire TV                  |
| _(7, deferred)_ | IPTV gate composition (provisioner build + N-provider apply)                                | needs `iptv` merge first                    |

Per-phase loop: **brief parallel agents → integrate → run the gate → QA completeness review →
commit/push → next phase.**

## Phase log

Every phase records all four gate facts here when accepted: **tested · gated · coverage ·
documented**.

### Phase 0 — DONE (`test(modular-setup): Phase 0 …`)

- **Landed:** `_tools/conftest.py` (the fake-Kodi `boot` fixture extracted from
  `test_bootstrap.py` — verified byte-equivalent, now reusable by all modular tests);
  `_tools/test_modular_setup.py` + `modular_setup_snapshot.json` — the characterization
  oracle (`bare` + `full` snapshots) pinning the current `run()`'s install/enable order,
  the activate-skin-**last** cadence, and — at **runtime**, not source-grep — the restart,
  self-uninstall, and cancel-path wiring.
- **What's now true:** there is a behavior oracle that every later phase is checked against
  ("Express must reproduce the monolith"). It is hardened against silent self-rebaseline
  (writes only under `UPDATE_SNAPSHOT=1`; refused when `CI` is set; a missing key fails loud).
- **Tested:** 7 oracle tests incl. runtime restart/self-uninstall/cancel/skin-last
  invariants, all **mutation-verified** (removing a call from `run()` fails the matching test).
- **Gated:** full suite **383 passed / 1 xfailed**, `ruff` clean, zero `addons/**` change,
  pre-push gate green, pushed.
- **Coverage:** new-production-module ≥90% criterion **N/A** (Phase 0 added no production
  module — test infra + oracle only). Recorded oracle reach instead: the characterization
  test alone exercises **58%** of `bootstrap/default.py`; the full bootstrap suite reaches
  **89%**. Unpinned lines = the env-driven IPTV/RSS + device-copy branches that are guarded
  no-ops on a desktop no-env run — exercised in the later phases that touch them.
- **Adversarial QA review:** caught + closed GAP 1 (silent-rebaseline footgun), GAP 2
  (restart/self-uninstall wiring invisible to the oracle), GAP 4 (cancel path), GAP 3
  (docstring overclaim). All fixes mutation-verified.
- **Deferred/noted:** pre-existing `repository.diggz` vs `repository.diggz.zip` double-enable
  quirk (faithfully pinned, do not "fix" without updating the snapshot); env-driven branch
  coverage rises as Phases 1–3 touch those paths.

### Phase 1 — DONE (local commit; behavior-preserving)

- **Landed:** the per-device `.env` read-then-delete lifted OUT of `_configure_box` INTO the
  orchestrator `run()`. `_configure_box(box_env=None)` is now a pure consumer — it never reads
  or deletes the env file; `run()` reads once, passes the dict in, deletes after configure.
- **What's now true:** a single coordinator owns env lifecycle — the prerequisite that lets a
  future multi-session Guided flow run a later gate without an earlier gate having deleted the
  env it needs.
- **Tested:** 5 new/changed tests; **mutation-verified** — 3 mutations killed incl. the subtle
  "delete-before-configure" (runtime ordering assertion) and "delete-removed"; remove-spies
  path-scoped to `BOX_ENV_PATH` so they don't false-trip on `run()`'s other `os.remove` calls.
- **Gated:** Phase 0 characterization snapshot passes **UNCHANGED** (behavior-preserving);
  387 passed / 1 xfailed; `ruff` clean.
- **Coverage:** `bootstrap/default.py` 89% → **92%**; env-ownership logic covered; only
  uncovered new line is a pre-existing defensive `except OSError: pass`.
- **QA completeness review:** ACCEPTABLE — no blocking gaps (2 optional nits noted).
- **Push/version:** committed locally; generated zip/`addons.xml` not regenerated and version
  not bumped — deferred to a milestone push (see Execution notes) to avoid advertising an
  unfinished feature in the user-visible version.

### Phase 2a — DONE (local commit; scaffolding, behavior-preserving)

- **Landed:** the `tony7bones/setup/` sublibrary — `result.py` (`LayerResult`), `host.py`
  (`KodiHost` port + `RealKodiHost`, lazy method-level delegation), `env.py` (env parsing
  relocated VERBATIM out of `default.py`). `default.py` now imports the env funcs from there
  (re-export, identity-verified). **`tony7bones/__init__.py` made lazy** (PEP 562
  `__getattr__`) so the engine is no longer eagerly imported.
- **What's now true:** the module-contract primitives exist, and the engine is
  **import-decoupled** — `import tony7bones.setup.host/env/result` works with **no xbmc**
  (proven by blocking `xbmc` at the import meta-path), while the engine still lazily requires
  Kodi on use. So the `apply_*` layers (2b/c/d) can be unit-tested via plain fake-`KodiHost`
  injection — no `sys.modules` xbmc monkeypatching.
- **Tested:** `_tools/test_setup_lib.py` (incl. off-box-import + commented-out-`KEY=value`
  guard tests); mutation-verified. **Gated:** snapshot UNCHANGED; 424 passed / 1 xfailed;
  ruff clean. **Coverage:** `setup/` **100%**.
- **QA completeness review:** ACCEPT; closed — commented-out-key guard test, real off-box
  decoupling (lazy `__init__`), port-growth note, tautology fix.
- **2b input:** the `KodiHost` port grows **test-driven** in 2b (it'll gain
  `dialog`/`progress`/`getAddonInfo`(version)/settings accessors as the layers need them).
