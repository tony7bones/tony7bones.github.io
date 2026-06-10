# Plan — No-Computer Setup (repository-direct, remote-only provisioning)

> Status: **DESIGN — panel-style plan, not yet built.** This track starts AFTER the
> modular-setup Phase 6 hardening completes and the milestone push lands the
> `modular-setup` branch on `main` (the wizard this plan extends must be the SHIPPED
> wizard before a remote-only user can reach it repo-direct). It builds directly on
> `docs/plans/modular-setup.md` — the three layers (`apply_foundation` / `apply_iptv` /
> `apply_addons`), the Guided wizard + Model A lifecycle (`run_guided`, installed-state
> probes), and the `SETUP_MODE` routing are all REUSED, not reshaped. Phase numbering
> here is **N1…N5** to avoid colliding with the modular plan's 0–7.

## Goal

A user with **only a Fire TV / Android box and its remote** — no computer, no adb, no
provisioner, no pre-pushed env, no host-built artifacts — must be able to:

1. add `https://tony7bones.github.io/` as a File-Manager source (one typed URL),
2. install `repository.tony7bones-<version>.zip` from `repositories/`,
3. install **Tony.7.Bones Setup** from the repository (the library comes via `<requires>`),
4. run it,

…and end up with **the full box**: MOD V2 + patch, weather, curated content add-ons,
and — with nothing more than a provider portal + username + password typed on the
on-screen keyboard — **live TV with real channels**. The existing computer-driven
flows (provisioner one-tap Express, env-routed Guided) must not regress by one byte
of behavior.

## The two provisioning worlds (and the one seam between them)

| World           | Transport                                      | Config source                                     | Mode                                       |
| --------------- | ---------------------------------------------- | ------------------------------------------------- | ------------------------------------------ |
| **Computer**    | adb provisioner (wipe, seed, push, stage, run) | `.env.<device>` → derived `tony7bones.env` pushed | env-routed: Express default, Guided opt-in |
| **No computer** | Kodi file manager + the repository (this plan) | **on-box config collector** (wizard dialogs)      | **no env → Guided wizard** (new default)   |

The seam is deliberately tiny: the collector produces **the exact same env dict shape**
(`WEATHER_LOCATIONS`, `IPTV_<N>_*`, `RSS_*`, `SETUP_MODE`, …) the layers already
consume, persisted to the same read-then-terminal-delete lifecycle. Below the dict,
**nothing forks** — same `apply_*`, same probes, same Model A, same restart seam.

## Core principles

- **One env dict, two producers.** The provisioner's pushed file and the on-box
  collector are interchangeable producers of the same `box_env` dict. The layers,
  probes, gates, and orchestrators never know (or care) which produced it. This is the
  no-fork move: zero new install logic, zero layer changes.
- **Never regress the proven paths.** Env present → routing is byte-identical to 5d
  (no `SETUP_MODE` → Express one-tap; `SETUP_MODE=guided` → wizard). Only the
  **no-env** launch changes — and the no-env launch today produces a generic box that
  serves nobody specifically; the remote-only user IS the no-env case.
- **Every remote-typed input must be minimal and derivable.** One URL to add the
  source. Three fields (portal, user, pass) for IPTV — mode, playlist URL, and EPG URL
  are **derived and probed**, never typed. One city name for weather. Foundation
  already installs `script.module.autocompletion` for exactly this (the 5a·3
  groundwork).
- **Honest scope cuts over miserable UX.** Anything that cannot be reasonably entered
  with a TV remote (32-char API keys, the relabel/sort curation grammar) is cut from
  the on-box v1 with a documented computer-path alternative — not approximated badly.
- **Same gates, same discipline.** Every phase: implement → test (≥90% new-code
  coverage, mutation-verified) → full suite + ruff + secrets green → adversarial QA
  review → clean-box live verify with **NO env present** → document → commit. The
  working agreement from the modular plan applies verbatim.

---

## Design decisions (panel-style: options → trade-offs → pick)

### D1 — Entry + mode: what does `run()` do with no env?

Today: no env (and no `SETUP_MODE`) → Express with keyless-Yahoo defaults and no IPTV.

| Option                                                           | Trade-offs                                                                                                                                                                                |
| ---------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **A. No env → Guided wizard** (pick)                             | The remote-only user gets the interview they need; the provisioned paths are untouched (the provisioner always pushes an env). Changes the no-env `run()` — snapshot rebaseline required. |
| B. Timeout-to-Express launch dialog                              | TV users walk away; a missed 10-second window silently picks the wrong mode. Worst of both.                                                                                               |
| C. Keep no-env → Express; add a second launcher entry for Guided | Preserves the snapshot, but the repo-direct user's FIRST run produces the generic box and self-uninstalls — they never meet the wizard. Fails the directive.                              |

**Decision: A.** New routing in `run()` (a strict superset of 5d's):

```
env file ABSENT (read_box_env -> {})           -> run_guided({})     (NEW — the no-computer path)
env present, no SETUP_MODE / other value       -> run_express(env)   (unchanged — provisioned one-tap)
env present, SETUP_MODE=guided                 -> run_guided(env)    (unchanged)
env present, SETUP_MODE=express (explicit)     -> run_express(env)   (already true today — any non-"guided" value)
```

Coexistence guarantees, each pinned by a test: (1) the provisioned unattended one-tap
is unreachable from this change — the provisioner pushes an env before Setup ever
runs; (2) `run_express`'s body does not change; (3) the wizard's menu gains an
**"Install everything with defaults"** entry (= the old no-env Express, one tap, runs
`run_express({})` including its self-uninstall) so a user who wants zero questions
still has the one-tap. The characterization snapshot's no-env scenario is deliberately
rebaselined with the same proof discipline as Phases 3 / 5a·2 (the Express path itself
is proven unchanged via the env-present route + the net-set invariant).

**Provisioner interplay risk (documented):** the provisioner's degraded "couldn't push
the env" path now lands in the wizard instead of unattended Express, and its
auto-dismiss (`Input.Select`) would press the wizard's first item. That path is rare
and attended (the owner is at the terminal watching warnings); N1 also teaches the
provisioner to abort before launching Setup when the env push failed, which is more
honest than the current silent degradation anyway.

### D2 — Replacing the provisioner, item by item

What `_tools/provision-kodi.sh` does today, and the on-box answer for each:

| Provisioner item                                                         | No-computer replacement                                                                                                                                                                                                                                         |
| ------------------------------------------------------------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Wipe Kodi clean                                                          | **Scope cut — none needed.** The layers are idempotent/additive on a used box (the re-entrancy principle); a truly dirty box is the user's factory-reset call. Document it.                                                                                     |
| Seed `addons.unknownsources=true` pre-launch                             | **Already solved by Kodi's own UX**: installing the repo zip from the file manager triggers Kodi's "unknown sources" prompt which deep-links to the setting. By the time Setup runs, it is on. Document the on-screen step.                                     |
| Seed web server (`services.webserver*`, `services.es*`)                  | New Foundation step `_apply_core_prefs(box_env)`: these are CORE settings, writable in-process via `Settings.SetSettingValue` — the pre-Kodi seed exists only because adb works from outside. Default per owner decision (open question Q3); env keys override. |
| Seed device name (`services.devicename`)                                 | Same `_apply_core_prefs`; the wizard optionally asks once ("Name this box?" — default keeps Kodi's). One short keyboard entry, skippable.                                                                                                                       |
| Seed settings level (Expert)                                             | Same `_apply_core_prefs` (cosmetic; default Standard unless env says otherwise — remote users don't need Expert).                                                                                                                                               |
| Seed `addons.updatemode=1`                                               | Same `_apply_core_prefs`.                                                                                                                                                                                                                                       |
| Push library + Setup + proxy repo over adb                               | **The repository-direct install path** (already shipped): file source → install `repository.tony7bones` zip → install Setup from the repo; `<requires>` auto-installs the library. Foundation then (re-)installs/updates the proxy repo idempotently (5a·3).    |
| Derive + push `tony7bones.env`                                           | **The on-box config collector** (D5): wizard dialogs → the same env dict → persisted to a profile-local env file with the same terminal-delete lifecycle.                                                                                                       |
| Host-build IPTV artifacts (`build_iptv.py`) + stage + `IPTV_STAGING_DIR` | **The hard one — D3.** v1: credential interview + auto-probe → direct-env (uncurated) config; v1.5: the on-box build with a group multiselect picker, staging into a profile-local dir consumed by the UNCHANGED `_apply_staged_provider`.                      |
| Launch, enable, run Setup, auto-dismiss summary, reopen choreography     | The user, with the remote — that is the point. The wizard's per-gate "reopen Setup to continue" copy (and the Phase 6 Android notification work) carries the choreography.                                                                                      |
| Post-run verification (skin persisted, patch marker, weather)            | The wizard's honest summaries + the installed-state probes ARE the verification surface; the probes re-offer any gate that did not stick (e.g. a keep-skin revert self-heals).                                                                                  |
| Fire OS 11 scoped-storage relocation (`xbmc_env.properties` → `/sdcard`) | **Not needed — a genuine win.** Relocation exists ONLY because adb cannot write the app sandbox. Kodi writes its own profile natively; the no-computer path never touches the sandbox from outside. The scoped-storage playbook stays computer-path-only.       |

### D3 — IPTV without a computer (the hardest one)

The host build exists because (a) pvr.iptvsimple Omega has **no native Xtream mode**
and some panels block `get.php`, so the playlist must be synthesized; (b) curation
(relabel/sort/favorites) **mutates** the playlist, requiring a local rewrite; (c) the
curation grammar lives in the env. Options weighed:

| Option                                                                   | Verdict                                                                                                                                                                                                                                                                                                                                                                                                                                                     |
| ------------------------------------------------------------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **A. On-screen credential entry, minimal fields** (v1 pick)              | Three fields — portal, user, pass — with everything else **derived**: probe `player_api.php` (auth check), probe `get.php` (mode inference: works → m3u, blocked → xtream), derive the m3u/EPG URLs from the standard Xtream layout. Autocomplete already installed. Viable today against the direct-env path.                                                                                                                                              |
| **B. In-Kodi build (port `build_iptv.py` into the library)** (v1.5 pick) | **Feasible**: the builder is pure stdlib (`urllib`, `json`, `re`, `xml.sax.saxutils`) — Kodi Omega's embedded Python 3 carries all of it; payloads are MBs, not GBs; the library already does HTTP. The curation-grammar input problem is solved NOT by typing the grammar but by a **group multiselect picker** (fetch categories/group-titles → `Dialog().multiselect` → checked groups become the selection). Relabel/sort/favorites stay computer-path. |
| C. Cloud/QR pairing (short code → type creds on a phone)                 | **Rejected for v1.** GitHub Pages is static — no server-side compute, no storage, no pairing rendezvous. Every "static" variant either exposes creds in a world-readable location or requires third-party infra holding provider credentials. A future tiny worker (Cloudflare) could do it, but it is new infrastructure with a real secret-custody burden for a problem options A+B already solve.                                                        |
| D. Defer IPTV entirely ("computer or manual pvr config" v1)              | **Rejected.** Live TV is the box's headline feature; "type three fields" (A) is cheap enough that deferral is an unforced scope cut. (Manual pvr config on a remote is far WORSE typing than A — the full get.php URL with query params.)                                                                                                                                                                                                                   |

**Recommended v1 scope, honestly stated:**

- **N3 (creds interview + auto-probe, direct-env):** the wizard asks portal / user /
  pass (password masked — `ALPHANUM_HIDE_INPUT`), probes the account, infers the mode,
  derives URLs, and writes `IPTV_1_*` keys into the collected env **with blank
  `GROUPS`** — the grammar's existing "discovery mode": every group loads,
  `tvChannelGroupsOnly` forced off. An m3u-mode provider gets full live TV immediately
  via the existing direct-env enforce. An xtream-mode provider still cannot load
  without a built playlist — in N3 it is skipped with the existing honest log + a
  wizard message ("this provider needs the curated build — coming next / use the
  computer path"). An **advanced** entry path accepts a raw m3u URL for non-Xtream
  providers.
- **N4 (on-box build + group picker):** the build engine moves into the shared library
  (`tony7bones/setup/iptv_build.py`, import-clean without Kodi); `_tools/build_iptv.py`
  becomes a thin CLI wrapper importing it — **one engine, two callers** (the same
  no-fork pattern as the layers). The wizard fetches the provider's categories
  (xtream) or group-titles (m3u), shows a multiselect, builds the curated artifacts
  into a **profile-local staging dir** (`special://profile/addon_data/…/iptv-staging/`),
  sets `IPTV_STAGING_DIR` in the collected env, and the UNCHANGED
  `_apply_staged_provider` consumes them inside the PVR-disabled window. Xtream
  providers now fully work remote-only. Favorite-icon healing comes along free (it
  lives in the engine).
- **Deferred (computer path keeps them):** display relabel, `| sort`, favorites
  (`id:` pins need stream-verification tooling), multi-provider entry beyond
  "add another provider?" looping, EPG URL override. None of these block a working,
  grouped live-TV box.

**Secret handling:** collected creds live only in the persisted env (terminal-deleted)
and the staged playlist (profile-local, same exposure class as every provisioned box
today — the m3u embeds creds in channel URLs by protocol design). Never logged (the
existing boolean-only logging contract extends to the collector); the secret-leak
suite gains collector-path checks.

### D4 — Weather / RSS without env

| Item                         | Decision                                                                                                                                                                                                                                                                                                          |
| ---------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Weather locations            | **Wizard prompt, one city** ("Your city or ZIP?" — Yahoo resolves both, keyless), with an "add another?" loop capped at 5. Skip/blank → the existing keyless Sacramento fallback (unchanged). This writes `WEATHER_LOCATIONS` into the collected env — the existing `_apply_weather_from_env` does the rest.      |
| Weatherbit / OWM API keys    | **Scope cut.** 32-char keys on a TV keyboard is hostile; they drive optional enhancement layers only. Documented: add them later via the computer path (env re-push) or Multi Weather's own settings UI.                                                                                                          |
| RSS feeds                    | **Ship a default feed list as committed, non-secret data** in the bootstrap (the owner's curated list is just URLs); env `RSS_FEEDS` overrides as today. Remote entry of feed URLs is pointless typing for a default-quality outcome. _(Owner sign-off — Q2 — since today the list only exists in private envs.)_ |
| RSS ticker toggle / interval | Defaults on / 30 as today; env overrides.                                                                                                                                                                                                                                                                         |

### D5 — Lifecycle fit: collector, persistence, and what ships where

**`run_guided` + probes + Model A are reused unchanged.** The wizard already
self-resumes from installed state and the surviving env; the collector only changes
_where the env comes from_. Two seam changes, both strict supersets:

1. **Env source generalization.** `run()` reads an ordered path list instead of the
   single Android constant: `BOX_ENV_PATH` (provisioner — wins when present) → a new
   **profile-local** path (`special://profile/addon_data/script.tony7bones.bootstrap/tony7bones.env`,
   translated; works on every platform, lives inside Kodi's own writable home — no
   scoped-storage exposure, no adb dependency). New `env.py` helpers
   (`box_env_paths()` / `read_first_env()` / `delete_box_envs()`); `_delete_box_env`
   and `_guided_finish` delete **all** paths. The provisioned path is byte-compatible
   (its file is found first).
2. **The collector** — `tony7bones/setup/collect.py` (library): pure logic, no UI —
   env-dict assembly, the Xtream probe/mode-inference/URL-derivation
   (`probe_provider(portal, user, pass) -> {mode, m3u, epg} | error`), validation,
   persistence (writes the env file with `SETUP_MODE=guided` so every reopen resumes
   the wizard — the existing self-resume mechanism, zero new state). The **dialog
   flows** (`_collect_weather`, `_collect_iptv`, `_collect_prefs`) live in the
   bootstrap `default.py` beside the gates (UI is orchestrator domain), each calling
   the library logic. Unit-testable via the conftest fakes (which already carry
   `select`/`multiselect`/`yesno` queues; an `input` queue is the one additive growth).

**Wizard surface growth (additive):** the no-env wizard runs a short **first-run
interview** before the first gate offer (device name? → weather city? → "set up live
TV now?" → persist), and the menu gains two conditional entries: **"Set up live TV"**
(when the env carries no provider and the IPTV gate isn't done — runs the IPTV
collector, persists, then offers the gate; this is also how a provisioned-without-IPTV
box adds live TV later, replacing the awkward "re-push the env" precondition the 5b·3
runners document) and **"Install everything with defaults"** (the one-tap Express
escape, D1). `_next_gate` is unchanged — it already keys the IPTV offer off
`_env_has_iptv(box_env)`, and the collector simply makes that true.

**What ships in which add-on:**

| Piece                                                       | Home                                                    |
| ----------------------------------------------------------- | ------------------------------------------------------- |
| `collect.py` (probe/derive/assemble/persist logic)          | `script.module.tony7bones` (`lib/tony7bones/setup/`)    |
| `iptv_build.py` (the build engine, N4)                      | `script.module.tony7bones` — single source of truth     |
| `_tools/build_iptv.py`                                      | becomes a thin CLI wrapper importing the library engine |
| Collector dialog flows, wizard menu growth, `run()` routing | `script.tony7bones.bootstrap`                           |
| `_apply_core_prefs`                                         | `foundation.py` (it is box-look/box-service config)     |
| Default RSS list                                            | bootstrap (committed data, non-secret)                  |

### D6 — Distribution (repository-direct install path)

Confirmed working by construction, with three milestone obligations:

- The Setup **is already in the proxy manifest** (`repository.json` lists
  `script.tony7bones.bootstrap`) and `<requires>` pins
  `script.module.tony7bones version="1.1.2"` — Kodi auto-installs the library from the
  proxy when the user installs Setup. The installer zip is browsable at
  `repositories/` per the served-canvas design. No manifest change needed.
- **The milestone push must land first** (the modular-setup branch is local-only):
  bump `script.module.tony7bones` + `script.tony7bones.bootstrap` (minor bumps — this
  is a feature batch), regenerate, push. This track's phases each bump again at their
  own milestone pushes.
- **Lockstep `<requires>` discipline:** every phase that grows the library surface the
  bootstrap calls (`collect.py`, `iptv_build.py`, env helpers) MUST raise the
  bootstrap's `<import addon="script.module.tony7bones" version="…">` minimum to the
  new library version — otherwise a box with a stale cached library pairs with a new
  bootstrap and crashes on import. Add a test: the bootstrap's required minimum equals
  the library's current `addon.xml` version whenever the bootstrap references a symbol
  introduced in it (cheap proxy: assert requires-min == library version at HEAD).

One UX note to document (not code): the very first hurdle is Kodi's own
"unknown sources" gate when installing the repo zip — Kodi's dialog deep-links to the
setting, so the user-facing install doc (a short page served from the site +
`README`) walks: Settings → File manager → Add source → type the URL → Add-ons →
Install from zip → enable unknown sources when prompted → `repositories/` → the zip →
Install from repository → Tony.7.Bones Repo → Program add-ons → Tony.7.Bones Setup.

### D7 — Testing / verification strategy

Same gated treatment as every modular phase, plus the no-env dimension:

- **Unit:** collector logic (probe/mode-inference/URL-derivation against canned
  `player_api`/`get.php` responses incl. the HTTP-884 case), env persistence
  round-trip (write → `read_first_env` → identical dict), routing matrix (no env →
  guided; env-no-mode → express; both SETUP_MODE values; precedence of
  `BOX_ENV_PATH` over profile-local), dialog flows via scripted conftest queues
  (`input` queue added), wizard menu growth (conditional entries appear/act),
  `_apply_core_prefs`. The in-Kodi build engine inherits `test_build_iptv.py`
  wholesale (the engine move is behavior-preserving — pin byte-identical artifacts
  host vs library import before the move commits).
- **Invariants (mutation-verified):** no-fork stays structural (the collector produces
  a dict, never calls install primitives); secrets never logged on the collector path;
  the provisioned routing unchanged (env-present snapshot scenarios byte-identical);
  staged-consumption unchanged (`_apply_staged_provider` untouched in N4 — only the
  artifact PRODUCER moves on-box).
- **Live verify (the acceptance bar, per phase):** a **clean local Kodi with NO env
  file anywhere**, installed via the REAL repo-direct path (file-manager source →
  repo zip → Setup from the repository — not adb-pushed), driven over JSON-RPC with
  `Input.ButtonEvent` (the 5d dialog-driving lessons; screenshot-path seeded first).
  Prove per phase the wizard launches with zero env, the interview writes the env,
  gates run, and the end state matches the same JSON-RPC evidence bars the modular
  phases used (skin active + patched, weather populated, PVR group/channel counts
  matching the build, content add-ons enabled, Setup removed on Finish, env files
  gone).
- **The track's terminal acceptance ("a remote-only user gets a full box"):** a real
  **Fire TV Stick**, factory-fresh Kodi, every input enumerated and humanly typable
  (1 URL + portal/user/pass + a city name + menu picks), no adb except as a passive
  observer (log/screenshot pulls only — never a write), ending in: MOD V2 patched,
  curated content, weather for the typed city, and the provider's channels in
  user-picked groups surviving a clean-shutdown restart. This is N5's gate.

### D8 — Risks

| Risk                                                                         | Mitigation                                                                                                                                                                                                                    |
| ---------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| No-env routing change reshapes the characterization snapshot's bare scenario | Deliberate, justified rebaseline (Phase 3 / 5a·2 precedent); Express body untouched and proven via the env-present scenario + net-set invariant + routing tests                                                               |
| Provisioner degraded path (env push failed) now lands in the wizard          | N1 makes the provisioner abort before running Setup on a failed env push (more honest than today's silent default run)                                                                                                        |
| On-box build performance on a Stick (7.5k-channel m3u fetch + curation)      | Payloads are the same MBs the box already fetches at every PVR refresh; build runs inside a progress dialog; favorites-icon healing (the only chatty part) is N/A without favorites; live-verify on real Stick hardware in N5 |
| Typing fatigue / input errors on the remote                                  | Three derivable fields max per provider; autocomplete installed by Foundation; every collector step re-promptable (wizard re-offers on failed probe with the reason)                                                          |
| Provider probe ambiguity (`get.php` half-works, odd panels)                  | The probe encodes the playbook's diagnosis recipe (auth via `player_api`, non-standard status + empty body = blocked); on ambiguity prefer xtream synthesis (N4) and say so                                                   |
| Creds in profile-local staging/env                                           | Same exposure class as every provisioned box (protocol-inherent); terminal delete covers all env paths; logging stays boolean-only; secret-leak suite extended                                                                |
| Stale library + new bootstrap after a partial repo update                    | Lockstep `<requires>` bump rule + the requires-min test (D6)                                                                                                                                                                  |
| Keep-skin revert race on first gate (5b·3 leg-1 finding)                     | Owned by Phase 6 (upstream of this track); the probes' activation-aware `foundation_done` already self-heals by re-offer                                                                                                      |
| Wizard dialogs vs Kodi modal quirks (focus-wedge class from the 5d notes)    | Keep one dialog at a time; the live-verify driver uses key-level events; collector flows are linear prompts, no stacked modals                                                                                                |

---

## Phase plan (N1…N5 — each lands a usable increment, sequential gates)

### N1 — Routing + env-source generalization (the wizard becomes reachable with no computer)

- **Deliverable:** `run()` no-env → `run_guided({})`; ordered env paths
  (`BOX_ENV_PATH` → profile-local) with `read_first_env`/`delete_box_envs`; terminal
  ops delete all paths; the wizard menu's "Install everything with defaults" entry
  (one-tap Express escape); provisioner aborts pre-Setup on a failed env push.
- **Acceptance:** routing matrix unit-pinned (incl. precedence + provisioned-path
  byte-compatibility); snapshot rebaseline justified + Express-unchanged proven;
  live verify: clean local Kodi, NO env, repo-direct install → the wizard renders;
  "defaults" entry produces exactly the old no-env Express box and self-uninstalls.

### N2 — On-box collector v1: prefs + weather (+ persistence)

- **Deliverable:** `setup/collect.py` (assembly/validation/persist with
  `SETUP_MODE=guided`); first-run interview (device name → weather city loop ≤5);
  `_apply_core_prefs` in Foundation (web server/device name/settings level/update
  mode, env-overridable, default per Q3); default RSS list as committed data (per
  Q2); conftest `input` queue.
- **Acceptance:** collector round-trip + dialog-flow tests; reopen-resume proven (the
  persisted env routes the next launch back to the wizard); live verify: remote-only
  Foundation + Add-ons walk ends with the typed city's weather, named box, RSS ticker
  on — env gone after Finish.

### N3 — IPTV credentials interview + auto-probe (direct-env live TV)

- **Deliverable:** `probe_provider` (auth check, mode inference, m3u/EPG URL
  derivation, the 884 case) in `collect.py`; the wizard's "Set up live TV" entry +
  interview (portal/user/pass masked; advanced raw-m3u entry; "add another provider?"
  loop); failed-probe re-prompt with reason; honest xtream-unstaged messaging.
- **Acceptance:** probe matrix unit-pinned against canned panel responses; secrets
  never logged/echoed (mutation-verified); live verify: remote-only entry of a real
  m3u-mode provider → all groups load with real channel counts, restart-survival; a
  real xtream-mode provider is refused honestly with the documented message.

### N4 — In-Kodi IPTV build + group multiselect (curated, xtream included, no computer)

- **Deliverable:** the build engine relocated to `tony7bones/setup/iptv_build.py`
  (import-clean, byte-identical artifacts pinned BEFORE the move commits);
  `_tools/build_iptv.py` reduced to a CLI wrapper (provisioner unchanged); the wizard
  group picker (fetch categories/group-titles → multiselect → build into
  profile-local staging → `IPTV_STAGING_DIR` in the collected env); the unchanged
  `_apply_staged_provider` consumes it.
- **Acceptance:** `test_build_iptv.py` passes against the library engine; host-vs-on-box
  artifact byte-equality test; live verify: remote-only xtream provider → picked
  groups only, builder counts == JSON-RPC counts, clean-shutdown survival; the
  computer path (provisioner staging) re-verified unchanged.

### N5 — Hardening + the real-Stick remote-only acceptance + release

- **Deliverable:** the full no-adb-writes Fire TV Stick acceptance run (D7's terminal
  bar); the user-facing install walkthrough page (served from the site) + README
  pointer; playbook updates (`one-shot-and-architecture`, the IPTV playbook's
  two-producers note); lockstep `<requires>` test; milestone release (library +
  bootstrap minor bumps, regenerate, push).
- **Acceptance:** the enumerated-inputs acceptance log (every remote input listed);
  all suites green; the provisioned fleet path re-verified on one box (no regression);
  released and installable repo-direct from the live site.

---

## Open questions for the owner (decisions needed before the matching phase)

1. **(N1) Confirm no-env → Guided** as the new default, with "Install everything with
   defaults" as the wizard's one-tap escape. (Recommended: yes — the no-env Express
   box serves nobody specifically; provisioned paths untouched.)
2. **(N2) Ship the curated RSS feed list as committed, public data** in the bootstrap
   (it is URLs, not secrets — but it is currently private-env-only by convention).
   Alternative: keep Kodi's default feed for no-env boxes.
3. **(N2) Web-server default for no-computer boxes:** on with the fleet convention
   (kodi/kodi — enables phone remotes out of the box, but a known default credential
   on a stranger's LAN), off by default, or one wizard yes/no? (Recommended: a single
   "Enable phone remote control?" yes/no — it is one remote click and the only
   security-relevant default in the flow.)
4. **(N3/N4) Accept the v1 IPTV curation scope:** group multiselect yes;
   relabel / `| sort` / favorites / API keys stay computer-path. (Recommended: yes —
   they are polish on top of a working grouped box.)
5. **(N3) Audience check:** is the no-computer path for the owner's own remote boxes,
   or for third parties? It changes nothing structural, but tunes defaults
   (settings level, RSS list, summary wording).
6. **(deferred) "Fetch config from a URL" escape hatch** (user types a URL to their
   own hosted env file): cheap to add, but it normalizes putting provider creds at a
   fetchable URL. Recommended: skip unless a concrete need appears.

## TASKS.md snippet (proposed)

```markdown
## No-Computer Setup (repository-direct, remote-only) — docs/plans/no-computer-setup.md

> Starts AFTER modular-setup Phase 6 + the milestone push. Same working agreement:
> implement → test → coverage → gate → QA review → live verify (NO env present) →
> document → commit, strictly sequential phases.

- [ ] **N1 — Routing + env sources:** no env → Guided; ordered env paths
      (BOX_ENV_PATH → profile-local); wizard "defaults" one-tap entry; provisioner
      aborts on failed env push. Gate: routing matrix + justified snapshot
      rebaseline + clean-Kodi repo-direct live verify (wizard renders with zero env).
- [ ] **N2 — Collector v1 (prefs + weather):** setup/collect.py + first-run interview
      (device name, weather cities) + \_apply_core_prefs + default RSS data +
      persisted env self-resume. Gate: round-trip/dialog tests + remote-only
      Foundation/Add-ons live walk. Needs: Q2 (RSS), Q3 (web server).
- [ ] **N3 — IPTV interview + auto-probe:** portal/user/pass (masked) → mode
      inference + URL derivation → direct-env live TV (uncurated); honest
      xtream-unstaged message; advanced raw-m3u entry. Gate: probe matrix +
      zero-secret-leak mutations + real-provider live verify.
- [ ] **N4 — On-box IPTV build + group picker:** engine → library
      (tony7bones/setup/iptv_build.py; \_tools wrapper; byte-equality pin), group
      multiselect → profile-local staging → unchanged \_apply_staged_provider.
      Gate: ported suite + artifact equality + xtream remote-only live verify +
      provisioner-path regression check.
- [ ] **N5 — Stick acceptance + release:** real Fire TV remote-only run (no adb
      writes), install walkthrough page, lockstep <requires> test, milestone
      release. Gate: enumerated-inputs acceptance log + fleet-path re-verify.
```
