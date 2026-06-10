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

### Phase 2b — DONE (local commit; Foundation extraction, behavior-preserving)

- **Landed:** `setup/foundation.py` with `apply_foundation(env, *, dialog=None, log) -> LayerResult` —
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

#### Tech-debt ledger (opened in 2b — settle before/at the Phase 4 orchestrator)

- **`deps`-injection seam** (`_SkinDeps`/`_BootSkinDeps` + `install_skin=/add_file_sources=/trim_home_menu=`
  params): a TRANSITIONAL test-compat mechanism so `run()`-driven tests that patch `boot.mod.*`
  primitives still take effect through the moved bodies. **Do NOT proliferate it to 2c/2d** —
  prefer repointing the few legacy `boot.mod.*` unit-test patches at the new module. The Phase 4
  orchestrator calls the **bare 3-arg** form (`apply_foundation({}, dialog, log)`, default `_SkinDeps`,
  no injection). **Kill the seam** once `run()` is fully decomposed.
- **`log` param dormant** — `apply_foundation` ignores it (logs via its module logger); wire layer
  logging when the orchestrator is built.
- **`already_done` not populated** by foundation (always implies fresh); populate when the
  orchestrator reads it for re-entry. 2c/2d must not cargo-cult always-False `already_done`.

### Phase 2c — DONE (local commit; Add-ons extraction, behavior-preserving)

- **Landed:** `setup/addons.py` — `_install_base`, `_install_video` (incl. dailymotion
  install-then-disable), and the WEATHER + RSS env-writers from `_configure_box`, MOVED
  verbatim, plus a composed `apply_addons(env) -> LayerResult` (built + self-tested but NOT
  yet called by `run()` — reserved for the Phase-4 orchestrator). IPTV parts of
  `_configure_box` (`_ensure_iptv_custom_tv_groups`, `_copy_device_files`) left in
  `default.py` for Phase 2d.
- **Interleaving preserved exactly:** `run()` still calls base/video install EARLY and
  weather/RSS LATE (in `_configure_box`); the weather→copy→iptv→rss order is byte-identical.
- **No deps-seam** (ledger honored): repointed the run()-driven test patches from `boot.mod.*`
  to `boot.mod._addons.*`. **Oracle integrity proven** — Mutation D (removing the new patches)
  breaks the snapshot, confirming `run()` genuinely routes install through the moved bodies;
  A/B/C (drop a repo / app / disable-after) all trip the golden snapshot.
- **Tested:** `_tools/test_setup_addons.py` (27 tests), mutation-verified. **Gated:** snapshot
  UNCHANGED; 462 passed; ruff clean. **Coverage:** `addons.py` **99%** (3 uncovered =
  defensive branches lifted verbatim from the monolith). **QA review:** ACCEPT.

#### Ledger update (already_done semantics — settled the 2b open item)

- `LayerResult.already_done` as a layer can compute it = **"no work was CONFIGURED"** (empty
  install lists), **NOT "the box is already provisioned"** — install primitives can't tell
  already-present from freshly-installed, so on a real re-entry `installed` is full and
  already_done is False. **Real re-entry detection is the Phase-4 orchestrator's
  installed-state probes** (`is_installed`/instance-settings/origin checks), NOT this field.
  Docstring + test reworded honestly; do not build idempotence on `already_done`.

### Phase 2d — DONE (local commit; IPTV-config extraction → Phase 2 decomposition COMPLETE)

- **Landed:** `setup/iptv.py` — `_ensure_iptv_custom_tv_groups` (+ `_set_instance_setting` +
  instance-settings constants) and `_copy_device_files`/`_copy_one_device_file`/`DEVICE_FILE_COPIES`
  MOVED verbatim, plus composed `apply_iptv(env) -> LayerResult` (not called by `run()` — Phase-4).
  `pvr.iptvsimple` INSTALL deliberately stays in base `ADDONS` (its move to the IPTV gate is the
  **Phase 3** behavior change). `_configure_box` keeps the exact weather→copy→iptv→rss order.
- **No deps-seam** (ledger honored); repointed 2 list-binding patches to `iptv.*`.
- **Highest-stakes checks PASS (mutation-proven):** the `tvGroupMode=2`-only-with-groups-file gate
  (the "empty channel list" regression) is intact; **secret safety** — m3u/epg creds are never
  logged (only `bool(...)`), no real creds in module/tests (fakes only), instance XML lands only in
  userdata.
- **Review-fix:** `apply_iptv`'s change-detection was a false-negative on a device-copied box
  (`existed_before` inference); fixed so `_ensure_iptv_custom_tv_groups` returns a truthful "wrote?"
  signal that `apply_iptv` consumes — fixed BEFORE Phase-4 wiring, mutation-verified.
- **Tested:** `_tools/test_setup_iptv.py` (33 tests). **Gated:** snapshot UNCHANGED; 495 passed;
  ruff clean; secrets clean. **Coverage:** `iptv.py` **100%**. **QA review:** ACCEPT.

---

## Phase 2 COMPLETE — the decomposition

`run()`'s install/config logic is now extracted into the `tony7bones/setup/` sublibrary:
`foundation.py` (95%), `addons.py` (99%), `iptv.py` (100%), on `result.py`/`host.py`/`env.py`
(100%). Each layer has a composed `apply_*(env) -> LayerResult` (built + self-tested, NOT yet
called by `run()`). `default.py` is now thin shims; behavior is **byte-identical** (the
characterization snapshot never moved across 2a–2d). 495 tests green. **Next: Phase 3** — the first
deliberate behavior change (move `pvr.iptvsimple` install Foundation→IPTV gate).

### Phase 3 — DONE (local commit; Express orchestrator + first deliberate behavior change)

- **Landed:** `run()` → **`run_express(box_env)`** composing `apply_addons → apply_foundation →
apply_iptv` as units (the Express orchestrator). `pvr.iptvsimple` INSTALL moved from base
  `ADDONS` into `apply_iptv` (`_install_pvr_backend`, **install-or-fail-loud** — never configure a
  missing backend). `apply_addons` now owns the weather/RSS core settings.
- **First DELIBERATE snapshot change — justified by a net-installed-SET equivalence proof:** the
  full run installs the byte-identical SET of add-ons as the old monolith (pvr.iptvsimple +
  inputstream still installed, via `apply_iptv` now); ONLY the operation ORDER (interleaved→layered)
  and the summary text (`Apps 4/4→3/3` + `IPTV: installed`) changed. `lookandfeel.skin` still LAST,
  all home-trim bools present. Pinned by a permanent FROZEN-constant invariant
  `MONOLITH_NET_INSTALLED` (mutation-proven, derived from the OLD committed snapshot — NOT circular),
  independent of the regen-able snapshot.
- **L1 resolved (reviewer flag):** IPTV is **deliberately non-blocking** — a pvr-backend install
  failure does NOT abort the end-of-setup restart (matches the monolith: install failures were
  always non-fatal). The fail-loud contract is at the LAYER (no half-config written); the box still
  completes setup.
- **Tested:** 515 passed; new fail-loud, net-set-equivalence, and `run_express` orchestration tests
  (skin-last, self-uninstall-after-summary, env read-once-delete-after) — all mutation-verified; the
  source-grep flow tests converted to RUNTIME spies. **Coverage:** iptv 100%, addons 99%, foundation
  93%, default.py 95%. **QA review:** ACCEPT (equivalence real, snapshot hid nothing — both
  mutation-proven).
- **Tech-debt:** the `_BootSkinDeps` seam is now OFF the `run_express` path → kill when `run()` is
  fully decomposed; `_configure_box` is now unused by the orchestrator (removal candidate in cleanup).
- **NEXT: Phase 3b — local-Kodi wipe-and-run** = the first VIEWABLE deliverable (run Express on the
  box → MOD V2 skin appears).

### Phase 5a — DONE (local commit; standalone Foundation = the skin-only deliverable)

- **Landed:** `install_repos(dialog)` extracted from `_install_base` (behavior-preserving incl.
  the exact per-iteration cancel semantics), and `run_foundation(box_env)` in `default.py`:
  `install_repos()` → `apply_foundation()` (skin closure + modv2plus + pvr.artwork direct-extract
  - Outline-HD + file-sources + home-trim) → set `lookandfeel.skin` LAST → restart →
    `self_uninstall`. Calls **neither** `apply_addons` content **nor** `apply_iptv`.
- **The deliverable:** Foundation installs **ALL our repositories** (the 12 `REPO_ZIPS` as
  sources/plumbing) + establishes `repository.tony7bones` (host proxy present + `.tony.7.bones`
  file source) + the skin + patch + skin-infra closure — and **ZERO content add-ons** (no base
  apps, no video, no pvr.iptvsimple, no IPTV). A clean branded Kodi; Setup self-removes.
- **Express unchanged:** `run_express` still installs the identical net set (repo install is
  idempotent); the characterization snapshot and `MONOLITH_NET_INSTALLED` invariant pass UNCHANGED.
- **Tested:** `_tools/test_run_foundation.py` (13 tests) + 3 extraction tests — mutation-verified
  (all 12 repos land; ZERO content at BOTH the stubbed AND the **real-engine resolve** level — a
  content leak fails; `install_repos` extraction byte-identical incl. cancel; skin-last;
  self-uninstall-after-summary). **Coverage:** addons.py 99%, `run_foundation` ~98% (uncovered =
  defensive guards). **QA review:** ACCEPT (closed the real-engine zero-content assertion).
- **NEXT: 5a device verification — a CLEAN Kodi install running `run_foundation`** → skin-only box
  (MOD V2 active, all repos present, ZERO content add-ons).

### Phase 5a·2 — DONE (local; Foundation realignment: menu-reliability fix + weather-into-Foundation)

> _(Numbering note: this and 5a·3 are CONTINUATIONS of the Foundation layer (Phase 5a), not new
> phases. The real Phase 5b is the IPTV layer — see "Phase 5b — NEXT" at the end of this doc.)_

Two coordinated changes, both **live-verified on a clean local Kodi 21.3 Omega** running
`run_foundation`.

- **Part A — menu reliability (`script.tony7bones.modv2plus` 1.4.7 → 1.4.8).** The skinshortcuts
  caching race (`service.py:_menu_is_ours`): Setup's live skin-switch can race
  script.skinshortcuts into building the STOCK Estuary menu and writing its `<skin>.hash` BEFORE
  our menu deploys; the matching hash then makes skinshortcuts SKIP rebuilding from ours on the
  next boot. **Fix:** the (re)deploy path (`_deploy_skinshortcuts_menu`, called from
  `apply_home_menu`) now DEFEATS the race in one atomic step — it (1) CLEARS the built
  skinshortcuts cache for `skin.estuary.modv2` (via `_clear_skinshortcuts_cache`), (2) deploys our
  exact menu DATA + widget `.properties`, then (3) DROPS the built `<skin>.hash` (new
  `_drop_skinshortcuts_hash`) so skinshortcuts regenerates from OUR menu on the next build/boot.
  `_menu_is_ours()`'s POV-based marker and the menu CONTENT (Live TV, Movies→POV, TV shows→POV,
  Add-ons, Favorites, Weather) are UNCHANGED. Bumped version + news, regenerated
  addons.xml/checksums/zip (old 1.4.7.zip pruned).
- **Part B — weather into Foundation.** `weather.multi` is part of the BRANDED LOOK (the MOD V2
  skin renders a weather readout + a Weather home-menu item), not content — so its INSTALL +
  CONFIG moved OUT of the Add-ons base `ADDONS` INTO Foundation (same pattern as the pvr→IPTV move
  in Phase 3). `apply_foundation` now installs `weather.multi` (via `install_with_deps`), sets the
  core `weather.addon` provider, and writes the env-driven (or keyless Sacramento default)
  locations (`_apply_weather_from_env` + helpers lifted from `addons.py` → `foundation.py`). The
  Outline-HD weather icons are already in the skin closure Foundation installs, and modv2plus's
  apply points `WeatherIcons` at them. The Add-ons layer now owns only RSS config. `ADDONS` is now
  `[script.ezmaintenanceplus, script.realdebrid]`.
- **Express equivalence:** the `MONOLITH_NET_INSTALLED` net-set invariant PASSES UNCHANGED —
  `weather.multi` (+ its python closure) is still installed by a full run, now via `apply_foundation`
  instead of the base loop. The characterization snapshot was regenerated (justified): `Apps 3/3→2/2`,
  the `weather.addon` setting + the weather.multi enable-order shift later (Foundation runs after
  add-ons in `run_express`). Net installed SET byte-identical — proven BEFORE the regen.
- **Tested:** `test_modv2plus.py` (+5 Part-A cache-clear/hash-drop tests, mutation-verified — hash-drop
  and cache-clear each independently killed); `test_run_foundation.py` / `test_setup_foundation.py`
  (Foundation installs+configures weather; weather unit tests moved here; mutation: weather-not-configured
  → net-set invariant + Foundation tests fail); `test_setup_addons.py` (weather out of ADDONS, RSS-only
  config; mutation: weather back in ADDONS → fail); `test_bootstrap.py` repointed. **541 passed / 1 xfailed**,
  `ruff` clean, secrets clean. **Coverage:** foundation.py 95%, addons.py 99%.
- **LIVE (clean Kodi, `run_foundation`):** MOD V2 active; the home menu is modv2plus's TRIMMED menu
  (Movies/TV shows/Add-ons/Favorites/Weather/Live TV — NO Music/Pictures/Games clutter), boot service
  logged `nothing to do (menu=True)` proving `_menu_is_ours`; clicking Movies (no POV) → Kodi's
  "Add-on required: POV" prompt; WEATHER WORKS — `weather.addon=weather.multi`, location Sacramento,
  Outline-HD icons, the skin's Weather panel populated ("Sacramento, California — 82°F · Sunny" + full
  forecast). ZERO content add-ons; all 12 repos installed. Screenshots captured.

### Phase 5a·3 — DONE (local; Foundation finishers: our repo + autocomplete + env-gated IPTV auto-chain)

Three additive Foundation changes, all unit-/mutation-verified (no live-Kodi pass yet —
the owner runs the clean-Kodi verify).

- **Foundation now installs our OWN proxy repo (`repository.tony7bones`).** Previously
  Foundation installed the 12 third-party `REPO_ZIPS` but NOT our own repo. `install_repos`
  (addons.py) now also direct-extracts the proxy installer zip — resolved LIVE from the
  served `addon.xml` via `_latest_zip_url` (the SAME mechanism modv2plus uses) — then
  registers + enables it (new `PROXY_REPO_ID`). Idempotent (`is_installed` short-circuit) and
  non-fatal (a resolve/extract failure leaves the box working; `apply_foundation`'s
  `.tony.7.bones` File-Manager source still lets the user reinstall). The box ends up with our
  repo as an INSTALLED, ENABLED add-on — the lifeline (updates / the proxy / future opt-ins) —
  not merely the source entry. Counted into `fp_ok` (first-party plumbing). Both Express
  (`run_express` via `_install_base`) and Foundation get it.
- **Foundation installs `script.module.autocompletion`** (official Kodi repo, current 2.1.1) —
  the on-screen-keyboard autocomplete QoL UTILITY (helps search / IPTV portal+login typing),
  NOT content. New `AUTOCOMPLETE_ID` + `_install_autocomplete` in foundation.py; installed via
  `install_with_deps(..., OFFICIAL_BASE, ...)`. Non-fatal; recorded in the Foundation
  `LayerResult` (`installed`/`failed`).
- **Env-gated IPTV auto-chain.** New `run_foundation_setup(box_env)` composes the shared
  Foundation install seam (`_foundation_core` — repos incl. our proxy + the skin/weather/menu/
  autocomplete layer) and THEN, **iff the env carries an IPTV provider** (`_env_has_iptv` —
  true when any `IPTV_<N>_M3U` / `IPTV_<N>_PORTAL` or the single-instance
  `IPTV_M3U`/`IPTV_PORTAL`/`IPTV_EPG` is present with a non-empty value; `IPTV_GROUPS` alone does
  NOT count), chains `apply_iptv` (installs pvr.iptvsimple + writes instance-settings). With no
  IPTV env it stops at the skin-only box — identical to `run_foundation` (no pvr, no IPTV).
  `run_foundation` stayed PURE skin-only (never touches IPTV); both runners share
  `_foundation_core` so they can't drift. Terminal seam (set `lookandfeel.skin` LAST → restart
  ONCE → self-uninstall) stays orchestrator-owned. NOT wired into the shipped `run()` (still
  `run_express`) — a new entry point for later.
- **Net-set invariant updated.** `MONOLITH_NET_INSTALLED` renamed → `EXPECTED_NET_INSTALLED`
  (old name kept as an alias) and now includes the two new ids with a justification comment
  (intentional feature growth, NOT a regression). The PROVEN delta before regenerating the
  golden snapshot was EXACTLY `{repository.tony7bones, script.module.autocompletion}` added,
  nothing else (asserted by `test_full_run_net_installed_set_equals_expected` +
  `test_foundation_additions_are_exactly_two`, mutation-proven). The characterization snapshot
  was regenerated — the diff is ONLY the two additions + their enable/rescan entries (no
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
- **Coverage:** addons.py 99%, foundation.py 95%, iptv.py 100%, bootstrap default.py 96% — all
  new code covered (uncovered lines are pre-existing defensive guards / `__main__`).
- **Generated files** regenerated (deterministic — second regen byte-identical); installer zip
  present in served `repositories/`; consistency gate green. modv2plus stays 1.4.8; no other
  version bumps (deferred to the milestone push).
- **QA review gaps closed:** (GAP-1) added `test_run_foundation_ignores_iptv_env` — proves the
  PURE `run_foundation` never chains IPTV even when handed an IPTV-bearing env (purity was
  structural; now mutation-guarded). (GAP-2 decision) **`IPTV_EPG` alone no longer trips the
  gate** — an EPG with no playlist is a channel-less PVR, not a usable source; the gate is now
  M3U/PORTAL only (`apply_iptv` still consumes `IPTV_EPG` when a real provider is present).
  **558 passed.**
- **LIVE-VERIFIED (clean Kodi, `run_foundation_setup` with an IPTV-bearing env from `.env.local`):**
  `repository.tony7bones` v2.2.1 **installed + enabled** (proxy service running) — the previously-
  missing lifeline; `script.module.autocompletion` 2.1.1 **installed + enabled**; the **env-gated
  chain FIRED** (`has_iptv=True` → pvr.iptvsimple installed); MOD V2 active, trimmed menu, weather
  populated, Setup self-uninstalled.

#### ⚠️ Two IPTV-LAYER bugs the live run surfaced → first action items for Phase 5b

These are in `apply_iptv` (the IPTV layer), NOT Foundation — the chain WIRING is correct (gate
fires, backend installs). They are exactly the IPTV-layer hardening Phase 5b owns.

1. **Instance-settings clobber (the live box ends up with an UNCONFIGURED pvr).** `apply_iptv`
   ENABLES pvr.iptvsimple (which instantiates the live PVR client with stock in-memory defaults)
   BEFORE `_ensure_iptv_custom_tv_groups` WRITES the file — so the running client flushes its stale
   defaults back over the enforce's write (the same "Kodi clobbers a direct file write" class the
   project documents for `Skin.SetBool`). FIX (5b): write/enforce instance-settings BEFORE enabling
   the backend (or disable around the write, or force a reload after). The Express `_configure_box`
   path likely has the same latent race.
2. **Multi-provider → single-instance env gap.** `_ensure_iptv_custom_tv_groups` reads single-instance
   `IPTV_M3U`/`IPTV_EPG`/`IPTV_GROUPS`, but the per-device `.env` uses the multi-provider `IPTV_<N>_*`
   shape — there is no `IPTV_<N>_*` → instance derivation yet, so a real provisioner env writes
   nothing. FIX (5b): generalize `apply_iptv` to N providers (the deferred P2 work — host-side
   `build_iptv.py` from the `iptv` branch + N `instance-settings-<N>.xml`).

---

## Phase 5b — NEXT (the IPTV layer; not started)

> **Status of the build:** Phases 0–3 + **5a (Foundation, incl. 5a·2/5a·3)** are DONE, gated, and
> committed LOCALLY on `modular-setup` (HEAD `b38aa09`) — **not pushed** (milestone-push pending: it
> needs the `script.module.tony7bones` + `script.tony7bones.bootstrap` version bumps + a `--news`).
> The Foundation deliverable is complete and clean-Kodi verified. `run_express` (Express) and
> `run_foundation`/`run_foundation_setup` (skin-only + env-gated IPTV chain) exist; the shipped
> `run()` still calls `run_express`.

**5b makes the IPTV layer independently runnable AND correct.** Start here, in order:

1. **FIX the two `apply_iptv` live-box bugs** (logged under Phase 5a·3, the live run surfaced them):
   - **Instance-settings clobber** — write/enforce `instance-settings-*.xml` BEFORE enabling
     pvr.iptvsimple (the running PVR client flushes stock in-memory defaults over a later file
     write — same class as the `Skin.SetBool` clobber). Verify the Express `_configure_box` path
     for the same latent race.
   - **Multi-provider env gap** — `_ensure_iptv_custom_tv_groups` reads single-instance
     `IPTV_M3U`/`IPTV_EPG`/`IPTV_GROUPS`, but the per-device `.env` uses `IPTV_<N>_*`. Generalize
     `apply_iptv` to **N providers** → N `instance-settings-<N>.xml` + N `customTVGroups-*.xml`.
2. **Integrate the host-side IPTV build** (the deferred P2 work): bring `_tools/build_iptv.py` +
   `_tools/test_build_iptv.py` + the customization playbook over from the **`iptv` branch** (98%-
   covered, m3u + xtream modes) into the provisioner, and have `apply_iptv` consume its staged
   curated `instance-settings-<N>.xml` / `customTVGroups-*.xml` (per the panel's "IPTV is two
   halves" decision — host build + in-Kodi apply).
3. **`run_iptv(box_env)`** — make the IPTV layer independently runnable on top of an existing
   Foundation (install pvr backend if missing — it already fail-louds — + N-provider config), so a
   user who stopped skin-only can later add IPTV with no redo.
4. **Gate it** (the standing four-part bar + clean-Kodi verify): on a clean Foundation box, run
   `run_foundation_setup` with `.env.local` (real IPTV) → channels actually load (this is what the
   5a·3 live run could NOT confirm because of bug #1).

**Then:**

- **Phase 5c — the Add-ons layer independent** (`run_addons`): the opinionated curated set (POV,
  Loop, Sports HD, YouTube) as an opt-in layer on top of Foundation.
- **Phase 5d — the Guided wizard + Model A lifecycle** (the panel's keystone): the orchestrator
  persists across gates (self-uninstall only on terminal Finish); the wizard offers the next undone
  gate using installed-state probes; the **no-fork** invariant (Guided and Express drive the same
  `apply_*`). Wire a chosen default into the shipped `run()` (today still `run_express`).
- **Phase 6 — harden + Fire TV** (version-guard shared modules, `assert_box_complete`, CI gates, the
  wipe-and-run matrix on a real Stick for the Android manual-restart UX).
