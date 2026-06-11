# Plan — Eliminate manual version bumping for the first-party add-ons

> Status: **DECISIONS LOCKED (2026-06-10) — Phases 0, 1, 2, 3 + O7 SHIPPED
> (committed locally on `no-computer-setup`, not pushed).** The owner's calls on
> O1–O6 are recorded below. **Phase 0** generalized `release_lib` (pure transforms
> `next_version` / `set_import_version` / `read_import_version` /
> `prepend_addon_news` capped+idempotent), no add-on bump. **Phase 1** de-pinned
> the two literal version tests (relational + negative tests). **Phase 2** added
> the ONE shared `changed_addons()` detector (tool + gate route through it, MF-1)
> and wired `check_versions.py` into CI (O7). **Phase 3** shipped `_tools/release.py`
> (detect → bump (minor default) → news → lockstep → regen → determinism gate →
> commit; `--dry-run`/`--patch`/`--major`/`--version`/`--news`/`--push`/`check`;
> all QA must-fixes MF-1…MF-9; bare-remote e2e tests). O8–O10 remain owner
> questions. Phases 4 (docs default) and 5 (proxy unification) remain proposed.

## Owner decisions — LOCKED (2026-06-10)

These supersede the recommendations in the Design Decisions section where they
differ; the per-decision prose below is annotated `LOCKED`.

- **Bump level (O1):** **MINOR by default**, with `--patch` / `--major` /
  `--version` overrides. NOT conventional-commit auto-level by default
  (`--auto-level` remains an opt-in suggestion mode, never the default).
- **Autonomy (O4):** the tool **BUMPS + COMMITS ON BRANCH and STOPS.** The owner
  keeps the branch → merge → main push flow. No auto-push, no auto-merge. A
  `--push` flag may exist but is never the default.
- **News (O2 + O3):** **AUTO-DRAFT** the news line from commit subjects, and
  **PREPEND** to the existing `<news>` body (switch `set_addon_news` from REPLACE
  to PREPEND), keeping a rolling **~6 entries** (capped). `--news` overrides the
  draft.
- **Scope (O5):** **EVENTUALLY UNIFY** both release paths (`script.*` + the proxy)
  under one `release.py`, **PHASED** so the working proxy `deploy.py` is never
  broken (Phase 5 stays last and optional).

## Goal

Make the version bump for a `script.*` / `script.module.*` add-on **automatic
and correct** instead of a hand-edited, multi-file, error-prone ritual. The
owner is done with manual bumping: "It's long, open to errors and bullshit."

Today, shipping a one-line fix to `script.tony7bones.bootstrap` forces the human
to, in order:

1. Hand-edit `addons/<id>/addon.xml` `version=`.
2. Hand-write a new `<news>` line (and decide whether to prepend the prior one).
3. Hand-raise the lockstep `<requires>`/`<import>` (bootstrap's import of the
   library) when the library moved.
4. Hand-edit the **version-pinned tests** that assert the literal version
   (`_tools/test_module.py:61`, `_tools/test_bootstrap.py:840`).
5. Run `generate_repo.py`, settle the deterministic zip, commit.
6. Get past the pre-push hook's `check_versions.py`, which BLOCKS the push if any
   changed add-on did not bump.

The goal is to delete steps 1–4 (and most of 5) — one command does the bump, the
news, the lockstep, the pins, the regen, and the commit. The bump itself is
**never** skipped: Kodi auto-upgrades by version number only, so a byte change
under the same version silently breaks upgrades. We are removing the _human_, not
the bump.

## ⚠️ The hard constraint we design AROUND (never violate)

**Kodi auto-upgrades installed add-ons by VERSION NUMBER ONLY.** A byte change
shipped under the same version is invisible to every box that already has the
add-on — they never re-fetch it. This repo has been bitten by it and documents it
repeatedly (`CLAUDE.md` "Releasing"; `release_lib.is_greater` exists precisely to
enforce "every deploy bumps"). Therefore:

- Every release of a changed add-on **MUST** bump that add-on's `version`.
- The automation's job is to compute the _correct next version_ and write it
  everywhere, with zero human edits — not to make bumping optional.
- The existing monotonic-increase gate (`check_versions.py`) and the
  single-digit-per-component scheme (`release_lib.is_single_digit`) stay in force
  as the safety net; the new tool must satisfy them, and ideally subsume them.

This is the single most important rule in this plan.

## Current state (what exists today — file cites)

### Two release paths, by design

- **Path A — `script.*` / `script.module.*`** (`script.module.tony7bones`,
  `script.tony7bones.bootstrap`, `script.tony7bones.modv2plus`): **manual**. Bump
  `addon.xml`, write news, raise requires, fix pinned tests, `generate_repo.py`,
  `git push`. Gated by the pre-push hook. This is the painful path; **this plan
  targets it.** (`docs/playbooks/release-and-deploy.md` Path A.)
- **Path B — `repository.tony7bones`** (the virtual proxy): **automated** by
  `_tools/deploy.py` — one command bumps, builds deterministically, syncs all
  version-bearing locations from a single string, commits `main`, tags, pushes
  `main + tag` atomically, forces a Pages build, verifies live. This is the GOOD
  pattern. (`docs/playbooks/release-and-deploy.md` Path B.)

The asymmetry is the whole problem: the proxy has a one-command release; the
three add-ons people actually iterate on do not.

### The machinery, precisely

- **`_tools/release_lib.py`** — pure version math + file transforms, no I/O.
  `parse_version`, `bump(version, level)` (single-digit rollover, ceiling at
  9.9.9), `is_greater`, `is_single_digit` (each component 0–9), `read_addon_version`
  / `set_addon_version` (regex on `<addon ... version="...">`), `set_addon_news`
  (REPLACES the `<news>` body with one line; the docstring at line 162–174 notes
  this is intentional single-line news, "if a rolling changelog is ever wanted,
  change this to prepend instead"). It is **hard-coded to `ADDON_ID =
"repository.tony7bones"`** (line 23) — `zip_name`, `version_from_zip_name`,
  `_ZIP_RE`, `is_root_zip_name`, `DeployPlan` are all proxy-specific. To reuse it
  for the `script.*` add-ons we must generalize the ID-bound parts (the version
  math and the addon.xml transforms are already ID-agnostic).
- **`_tools/check_versions.py`** — the per-add-on bump gate. For every dir under
  `addons/` with an `addon.xml`, it diffs `origin/main..HEAD` for that dir
  **excluding `*.zip` and `index.html`** (lines 55–64), and if the source changed
  but the version did not increase, it BLOCKS (lines 86–91). It also enforces
  `is_single_digit` on the NEW version only (line 80). **This is exactly the
  "what changed since the last release" detector we need** — the diff definition
  (source yes; generated zip/index no) is already correct and battle-tested. The
  baseline is `origin/main` (the last released state), NOT a per-add-on tag.
- **`_tools/check_consistency.py`** — proxy-only version-bearing-location gate
  (main addon.xml `version`, the single root zip filename, the git tag). It does
  NOT cover the `script.*` add-ons; their only cross-file invariant today is the
  hand-maintained lockstep `<import>` and the pinned tests.
- **`_tools/deploy.py`** — the proxy orchestrator (the template to extend):
  pre-flight (clean tree, on main, not behind origin, monotonic, tag/zip don't
  exist), bump, deterministic build + byte-identity assertion, determinism gate
  (regen → tree stays clean), tag, consistency gate, atomic push, rollback on any
  failure (`git reset --hard` + `git tag -d`).
- **`.githooks/pre-push`** — runs pytest, ruff, generator-staleness, then
  `check_consistency.py` (main only) and `check_versions.py`. Fails closed.
- **`.github/workflows/generate_repo.yml`** — CI runs the same gate, **never
  commits to main**, validates generated-files freshness and (main only)
  consistency. NOTE: its `paths:` filter still lists `repo/**` (pre-rename) — a
  pre-existing bug flagged in the playbook, out of scope here but worth fixing in
  the same pass.

### The version-pinned tests (the hand-edit tax — confirmed, all sites)

Two of these WERE LITERAL `==` pins that had to be hand-edited every release; two
are floors that are already automation-safe. **Phase 1 (shipped 2026-06-10)
de-pinned the two literals** to relational asserts:

| Site                           | Assertion (after Phase 1)                                              | Type            | Needs hand-edit?  |
| ------------------------------ | ---------------------------------------------------------------------- | --------------- | ----------------- |
| `_tools/test_module.py`        | `parse_version(v)` + `is_single_digit(v)` (was `== "1.5.0"`)           | relational      | NO (de-pinned)    |
| `_tools/test_bootstrap.py`     | `import.version == library.version` (both read live; was `== "1.5.0"`) | relational `==` | NO (de-pinned)    |
| `_tools/test_modv2plus.py:195` | `parts >= (1, 3, 4)`                                                   | floor           | no (already safe) |
| `_tools/test_bootstrap.py:95`  | `rl.is_greater(v, "1.0.22")`                                           | floor           | no (already safe) |

So the recurring pin tax is exactly **two assertions**: the library's own version,
and bootstrap's lockstep import of it. Both encode an invariant that is better
expressed _relationally_ than as a literal (see Decision 4).

### How the add-ons are released today (history check)

`git log` on `addons/script.module.tony7bones/addon.xml` shows releases are
commits like `chore(release): bootstrap 1.8.0 + library 1.5.0 …` — and the
`script.*` add-ons are **NOT tagged per release** (only the proxy carries
`vX.Y.Z` tags). So "the last released version" for a `script.*` add-on is
**whatever its `addon.xml` says on `origin/main`** — which is precisely the
baseline `check_versions.py` already uses. We do not need a per-add-on tag scheme.

Current shipped versions on `main` (read live, for context only — do not bump):
library `1.5.0`, bootstrap `1.8.0`, modv2plus `1.4.8`, proxy `2.2.1`. (The
playbook's version table is stale; the automation should make that table
auto-derivable so it stops drifting.)

---

## Design decisions (options, trade-offs, recommendation)

### Decision 1 — Detect which add-ons changed since their last release

**Definition of "changed" (precise):** an add-on is changed iff `git diff
origin/main..HEAD -- addons/<id> ':(exclude)addons/<id>/*.zip'
':(exclude)addons/<id>/index.html'` is non-empty. Source and `resources/` files
count; the generated zip and the generated `index.html` do not. The version line
inside `addon.xml` is _included_ in the diff (so a release commit that bumped it
still reads as "changed" — which is correct, because that commit IS its release).

Options:

- **(1a) Reuse `check_versions.py`'s diff verbatim** — it already implements this
  exact definition against the `origin/main` baseline. **RECOMMENDED.** Promote
  its per-add-on diff into a small shared helper (`changed_addons(base_ref)`) in a
  new `release_lib`-adjacent module, consumed by both the gate and the new tool, so
  the detector and the gate can never disagree (same pattern as
  `check_consistency` backing three call sites).
- (1b) Per-add-on git tags (`script.module.tony7bones-1.5.0`) as the baseline —
  more precise "last release" pointer, survives history rewrites. Trade-off: adds a
  whole new tag namespace and ceremony for zero current benefit (the `origin/main`
  baseline is already correct and the add-ons aren't tagged today). Rejected for
  now; revisit only if `main` history ever gets rewritten.

**Recommendation: 1a.** The detector is the existing, proven diff. Subtlety to
encode: when the tool runs **before** committing (the normal case), the baseline
must be `origin/main` and the comparison includes the working tree, so the tool
diffs `origin/main` against the _working tree_ (`git diff origin/main -- …`,
no `HEAD`), then makes its edits on top. When it runs in the hook (post-commit,
pre-push), the baseline comparison is `origin/main..HEAD` as today.

### Decision 2 — Decide the bump level automatically

The owner's stated cadence (`feedback_release_bump_cadence`): **prefer MINOR for
feature batches, PATCH only for small fixes**; dislikes patch climbing to double
digits; never renumber to shorten digits. The single-digit-per-component scheme
means a component rolls over at 9, so we cannot let patch run away anyway.

Options:

- **(2a) Conventional-commits parsing.** Scan commit subjects since the baseline
  for the changed add-on: `feat:` → minor, `fix:`/`chore:`/`refactor:` → patch,
  `feat!:` or `BREAKING CHANGE` → major. Matches the owner's cadence _if_ commit
  discipline holds. Trade-off: the repo's history is mixed (`chore(release):`,
  `fix:`, `docs:`, bare subjects) — parsing is only as good as the messages, and a
  mis-tagged commit silently picks the wrong level.
- **(2b) Default to MINOR, with `--patch`/`--major`/`--version` overrides.**
  Dead simple, matches "minor for feature batches" as the common case, and the
  human still controls the rare patch/major via a flag. Trade-off: a pure typo-fix
  defaults to minor, burning minor numbers faster (but single-digit rollover makes
  that cheap, and the owner explicitly dislikes patch-climbing, so erring toward
  minor aligns with the stated preference).
- **(2c) Explicit per-release intent** — the human always passes `--minor` /
  `--patch`. No magic. Trade-off: it is one more required input, but it is a
  _flag_, not five file edits, so it is still a 95% reduction in friction.

**LOCKED (2026-06-10): 2b — MINOR default with `--patch`/`--major`/`--version`
overrides; `--auto-level` opt-in only, never default.**

**Recommendation: hybrid 2b + 2a-assist.** Default level is **MINOR** (honors the
cadence; the common case is a feature batch). Accept `--patch` / `--major` /
`--version X.Y.Z` overrides. **Additionally**, parse conventional-commit prefixes
to _suggest_ a level and print it ("commits since last release look like `fix:` ×3
→ suggest `--patch`"), but only ACT on the suggestion when `--auto-level` is
passed. This gives the owner a zero-thought default (minor), a one-flag override,
and an opt-in fully-automatic mode once commit discipline is trusted — without ever
silently guessing wrong. The single-digit ceiling (9.9.9) and rollover are already
handled by `release_lib.bump`.

### Decision 3 — Write `<news>` and handle the lockstep `<requires>` automatically

**News.** Options: (3a) `--news "line"` required input, like `deploy.py` today —
predictable, human-authored, one line. (3b) Auto-generate from commit subjects
since the baseline (the conventional-commit bodies). (3c) Hybrid: auto-generate a
draft from commit subjects, but let `--news` override.

**LOCKED (2026-06-10): 3c + PREPEND.** Auto-draft the news line from commit
subjects (override with `--news`), and switch `set_addon_news` from REPLACE to
PREPEND, capped at ~6 rolling entries.

**Recommendation: 3c.** Default to auto-drafting the news line from the changed
add-on's commit subjects since `origin/main` (strip the conventional-commit
prefix, join the subjects), and accept `--news "…"` to override. Reuse the
existing `set_addon_news` transform (which replaces the single-line body). **Open
question O3:** the owner's manifests currently keep a _rolling_ parenthesized
history inside one `<news>` line (e.g. `v1.8.0: … (v1.7.0: … (v1.6.0: …`). The
current `set_addon_news` REPLACES rather than prepends. If the owner wants the
rolling history preserved automatically, we switch `set_addon_news` to _prepend_
`vX.Y.Z: <line>` ahead of the existing body (the docstring already anticipates
this). Recommended: **prepend**, capped at N entries (say 6) to keep the field
bounded.

**Lockstep `<requires>`.** Bootstrap declares `<import addon="script.module.tony7bones"
version="1.5.0"/>`. The invariant: **bootstrap's import min-version must equal (or
not exceed) the library's shipped version**, and when the library bumps, bootstrap
must (a) re-ship with its import raised to the new library version AND (b) itself
bump (because its `addon.xml` changed). The tool must, when the library is among
the changed add-ons:

1. Compute the library's next version first.
2. Rewrite bootstrap's `<import addon="script.module.tony7bones" version="…">` to
   that next version (a new `set_import_version(xml, addon_id, version)` transform
   in `release_lib`, mirroring `set_addon_version`).
3. Mark bootstrap as changed (its source now differs) and bump it too.

This makes the lockstep a _derived_ fact, not a human chore. Dependency order is
fixed and shallow (library → bootstrap; modv2plus is independent), so a simple
two-pass (bump leaves first, then dependents) suffices — no general topo-sort
needed, but the tool should read the actual `<import>` graph among first-party IDs
so a future third dependency is handled automatically.

### Decision 4 — Kill the version-pinned-test friction (core of the goal)

The two literal pins (`test_module.py:61`, `test_bootstrap.py:840`) exist to assert
two things that are really _relational invariants_, not literals:

- The library's `addon.xml` version is well-formed and single-digit.
- Bootstrap's `<import>` of the library **matches the library's actual shipped
  version** (the lockstep is in sync).

Options:

- **(4a) Make the tests read the version dynamically and assert the
  RELATION, not a literal.** Replace `== "1.5.0"` with: parse the library's
  `addon.xml`, assert `is_single_digit`; and in the bootstrap test, parse BOTH
  manifests and assert `bootstrap.import("script.module.tony7bones").version ==
library.version` (or `<=`, if we ever allow bootstrap to pin a floor below
  current). **RECOMMENDED.** This _deletes the hand-edit forever_ AND turns the
  test into a real lockstep guard (today it only checks a stale literal; a
  forgotten lockstep bump would pass the literal pin if it happened to match an old
  value). It is strictly safer and self-maintaining.
- (4b) Have the release tool auto-rewrite the literal pins as part of the bump
  (regex-replace the `== "x"` in the test files). Trade-off: the tool now edits
  test files with regexes — brittle, and it leaves the test asserting a literal
  that is only "true" because the tool keeps overwriting it. Strictly worse than
  4a. Rejected.

**LOCKED + SHIPPED (2026-06-10): 4a, strict `==` lockstep.** Implemented in
Phase 1 (this commit). `test_module.py` now asserts the library version is
well-formed + single-digit (via `release_lib.parse_version` + `is_single_digit`)
instead of `== "1.5.0"`; `test_bootstrap.py` now asserts bootstrap's `<import>`
of the library **== the library's actual shipped version** (both read live),
strict equality, NOT a `>=` floor. Two negative tests landed in the same commit
(lockstep drift FAILS on mismatch; malformed version rejected). The existing
floors are kept.

**Recommendation: 4a.** Rewrite the two pinned assertions to be relational/dynamic
**as Phase 1** (it is independently shippable, requires no version bump of any
add-on — it only touches `_tools/test_*.py`, not `addons/**`, so `check_versions`
won't demand a bump). Keep the existing floors (`>= (1,3,4)`,
`is_greater(v,"1.0.22")`) — they are already automation-safe and serve as
historical floors. After Phase 1 there are **zero** literal version pins in the
suite, so the release tool never touches a test file.

### Decision 5 — One command (or zero): the release tool

Extend the proven `deploy.py` / `release_lib.py` architecture to a single
`release` tool that handles the `script.*` path:

1. Detect changed first-party add-ons (Decision 1).
2. For each, compute the next version (Decision 2), in dependency order, raising
   lockstep imports (Decision 3).
3. Write `version` + `<news>` into each changed `addon.xml`; rewrite lockstep
   imports.
4. `generate_repo.py`; assert determinism (regen → clean), mirroring `deploy.py`.
5. Commit `main` with a generated `chore(release): …` subject summarizing the
   bumps (matches existing history style).
6. Run the gates (pytest, ruff, `check_versions`, generated-staleness) **before**
   surfacing success; roll back on any failure (`git reset --hard` to the
   pre-release HEAD), exactly like `deploy.py`.
7. Optionally push (default: leave committed on the branch for the owner's
   branch→merge→main workflow; `--push` to push).

**Unify both paths?** Options: (5a) keep `deploy.py` for the proxy and add a
sibling `release.py` for the `script.*` add-ons (two tools, shared `release_lib`).
(5b) Fold both into ONE `release.py` that detects which add-ons changed —
_including_ `repository.tony7bones` — and dispatches: a proxy change runs the
existing proxy transaction (root zip, tag, Pages force-build, live verify); a
`script.*` change runs the new transaction; a release touching both does both in
the right order.

**LOCKED (2026-06-10): 5b, phased.** Eventually unify under one `release.py`,
phased so the working proxy `deploy.py` is never broken (Phase 5 last + optional).
Autonomy is fixed to **commit-on-branch + STOP** (no auto-push / auto-merge).

**Recommendation: 5b, phased.** The end state is **one** `release.py` so the owner
never has to remember which path. But ship it incrementally: Phase 3 delivers the
`script.*`-only tool as a new entry point reusing `release_lib`; Phase 5 absorbs
`deploy.py`'s proxy transaction into the same tool and deprecates `deploy.py` to a
thin shim. This keeps each step shippable and never breaks the working proxy
release.

### Decision 6 — Where it runs

Options:

- **(6a) Local one-command** (`python3 _tools/release.py`), like `deploy.py`. The
  owner runs it on the branch, reviews the commit, merges to `main`. Deterministic,
  matches the current branch→merge→push workflow, keeps "CI never commits to main."
  **RECOMMENDED as the primary mode.**
- (6b) Pre-push hook auto-bumps. Trade-off: a hook that mutates the tree and
  _amends/adds a commit_ during `git push` is surprising, fights the "review before
  ship" instinct, and can fight a rebase/force-push. Rejected as the primary path;
  the hook stays a _validator_ (`check_versions` still BLOCKS an unbumped change —
  now as a safety net behind the tool, not the primary mechanism).
- (6c) CI release job. Trade-off: violates the repo's firm "CI never commits to
  main" rule and removes the determinism/inspection of a local run. Rejected.

**Recommendation: 6a primary, hook stays validator.** The tool runs locally and
makes the commit; the human merges. The pre-push hook keeps `check_versions.py` as
the fail-closed backstop (if someone hand-edits an add-on and forgets the tool, the
push is still blocked — the automation is additive, not a replacement for the
guard). This preserves "CI never commits to main" and the owner's existing
branch→merge flow.

### Decision 7 — Safety / guardrails (must be SAFER than manual)

The automation must strengthen, not weaken, every existing invariant:

- **Monotonic increase:** the tool computes `next = bump(current, level)` and
  asserts `is_greater(next, current)` before writing (already in `release_lib`);
  `check_versions.py` remains the independent backstop in the hook + CI.
- **Single-digit-per-component:** `is_single_digit` is still enforced (confirmed
  still live — `release_lib.is_single_digit`, called by both gates and
  `DeployPlan.__post_init__`). The tool refuses a bump that would exceed 9.9.9 (the
  ceiling already raises in `bump`).
- **Determinism:** after writing, the tool runs `generate_repo.py` twice and
  asserts the second run produces no diff (the `deploy.py` determinism gate),
  catching the `__pycache__`/`.ruff_cache`-in-zip class of nondeterminism.
- **Consistency:** a new `check_consistency`-style relation for the `script.*`
  add-ons — assert every changed `addon.xml` is well-formed, single-digit, greater
  than `origin/main`, and that the lockstep import equals the library version.
  Wire it into the hook + CI as the script-side analog of the proxy consistency
  gate.
- **Rollback:** the whole transaction is `git reset --hard <pre-release-HEAD>` on
  any failure, exactly like `deploy.py` (lines 292–299). Nothing is pushed until
  every gate is green.
- **No-secret guard:** unchanged — `test_secret_leak.py` still runs in the suite
  the tool invokes; the tool touches only `addons/**` and `_tools/test_*` (Phase 1)
  and never reads `.env*`.

### Decision 8 — Migration / rollout (phased, each step shippable)

Each phase is independently shippable and the **existing manual path keeps working
until the automation is proven**. Honors the repo's non-negotiable workflow
(implement → test → ≥90% coverage → gate → QA → document).

---

## Proposed tool / command UX

```bash
# Default: bump every changed first-party add-on a MINOR, auto-draft news from
# commit subjects, raise the lockstep import, regenerate, commit on the branch.
python3 _tools/release.py

# Preview only — show the plan (which add-ons changed, computed next versions,
# the news line, lockstep raises), change nothing.
python3 _tools/release.py --dry-run

# Override the level (applies to all changed add-ons, or scope to one):
python3 _tools/release.py --patch
python3 _tools/release.py --addon script.tony7bones.modv2plus --patch
python3 _tools/release.py --addon script.module.tony7bones --version 1.6.0

# Opt-in fully automatic level from conventional-commit prefixes:
python3 _tools/release.py --auto-level

# Override the news line for a specific add-on:
python3 _tools/release.py --news "script.tony7bones.bootstrap=Fix first-boot race"

# Push too (default leaves the commit on the branch for the merge-to-main flow):
python3 _tools/release.py --push

# Gate-only (the script-side consistency check), reused by the hook + CI:
python3 _tools/release.py check
```

Dry-run output (illustrative):

```
Release plan (baseline origin/main):
  changed add-ons:
    script.module.tony7bones   1.5.0 -> 1.6.0  (minor)   [3 commits: feat, fix, fix]
    script.tony7bones.bootstrap 1.8.0 -> 1.9.0  (minor)   [lockstep: import raised 1.5.0 -> 1.6.0; 1 commit]
  unchanged: script.tony7bones.modv2plus (1.4.8), repository.tony7bones (2.2.1)
  news:
    library:  "v1.6.0: <auto-drafted from commit subjects>"
    bootstrap:"v1.9.0: <auto-drafted>; requires library >= 1.6.0"
  actions: write addon.xml x2, raise 1 import, generate_repo.py, commit "chore(release): library 1.6.0 + bootstrap 1.9.0"
  push: NO (--push to publish)
```

---

## Phase plan (numbered, with per-phase acceptance)

### Phase 0 — Generalize `release_lib` (no behavior change) — SHIPPED 2026-06-10

- ✅ Added pure, ID-agnostic transforms to `_tools/release_lib.py` (no I/O, no git):
  - `next_version(current, level="minor")` — explicitly-named alias over `bump`
    for the tool's locked MINOR default (the proxy `deploy.py` keeps its PATCH
    default by calling `bump` directly). Version math stays single-source in `bump`
    (single-digit rollover + 9.9.9 ceiling).
  - `read_import_version(xml, addon_id)` / `set_import_version(xml, addon_id, version)`
    — read/rewrite a `<import addon=… version=…>` (the lockstep). Only the matching
    import is touched; idempotent; raises if the import is absent; order-independent
    regex (handles `addon=` before or after `version=`).
  - `prepend_addon_news(xml, line, *, version, cap=NEWS_CAP)` — PREPEND-with-cap news
    (O3): `vX.Y.Z: <line>` newest-first, rolling cap of ~6, **idempotent (MF-9)** —
    a re-run for the same version is a no-op (does not stack a duplicate). The
    existing `set_addon_news` (REPLACE) is kept UNCHANGED for the proxy `deploy.py`.
- **Decision (documented):** `set_addon_news` kept as-is (REPLACE) for `deploy.py`;
  the new `prepend_addon_news` is a SEPARATE function so the proxy path is untouched
  and byte-identical. The ID-bound proxy helpers (`zip_name`, `_ZIP_RE`, `DeployPlan`)
  stay in `release_lib` as-is — the script.\* tool uses the ID-agnostic transforms
  (`set_addon_version`, `set_import_version`, `prepend_addon_news`) directly with an
  arbitrary add-on id, so no module split was needed.
- **Acceptance MET:** `deploy.py` and all existing tests pass unchanged (882 passed
  / 1 xfailed; +19 new Phase-0 unit tests in `test_deploy.py`); `release_lib` at 99%
  coverage (the 2 uncovered lines are pre-existing `read/set_addon_version` error
  paths, not Phase-0 code); ruff clean; deterministic regen (no `addons/**` diff);
  NO add-on bump. Commit (local): `feat(release): release_lib lockstep+news transforms (Phase 0)`.

### Phase 1 — De-pin the tests (independently shippable, no add-on bump) — SHIPPED 2026-06-10

- ✅ Rewrote `test_module.py` (was `:61`) and `test_bootstrap.py` (was `:840`) to
  assert the relation (Decision 4a): library version is well-formed +
  single-digit (`release_lib.parse_version` + `is_single_digit`); bootstrap's
  `<import>` == the library's actual shipped version (both read live, strict `==`).
  Existing floors kept.
- ✅ Negative tests landed in the same commit:
  `test_lockstep_negative_library_raised_without_import_raise` (a synthetic
  manifest pair: library raised, import not → relation FAILS on a value
  **mismatch**, proven `is False`, not a parse exception) and
  `test_module_version_well_formedness_rejects_malformed` (rejects `1.10.0`,
  `1.5.O`, `1..5.0`, `1.5`, ``, `abc`).
- ✅ **Acceptance met:** suite green; the de-pinned tests fail on a real lockstep
  drift and on a malformed version (proven); `check_versions` does NOT demand a
  bump (only `_tools/**` changed — no `addons/**` content, so `generate_repo.py`
  produces no diff and no add-on version moves).
- ⚠️ **O7 finding (CI gap, recorded for Phase 2):** `check_versions.py` runs only
  in the pre-push hook, NOT in CI. De-pinning makes the monotonic guarantee
  depend on the hook alone — Phase 2 must wire the per-add-on bump gate into CI.

### Phase 2 — Change detector + CI version-bump gate (O7) — SHIPPED 2026-06-10

- ✅ Added `_tools/release_detect.py` — the ONE shared change detector:
  `changed_addons(repo_root, base_ref="origin/main", *, worktree=False)` returns
  the sorted ids of first-party add-ons whose source changed vs `base_ref`,
  EXCLUDING the generated `*.zip` + `index.html` (the exact definition
  `check_versions.py` used inline). The explicit `worktree` flag is the ONLY
  difference between the two call sites: `worktree=False` = committed
  `base_ref..HEAD` (the gate); `worktree=True` = working-tree vs `base_ref` (the
  tool, pre-commit). Plus `changed_files(...)` for the tool's `--dry-run` "why is
  this changed?" (MF-4) and `base_ref_exists`/`addon_dirs` helpers. Skips cleanly
  (`[]`) when `base_ref` does not resolve.
- ✅ **REPLACED** `check_versions.py`'s inline diff (old lines ~37–64) with a call
  to `rd.changed_addons(..., worktree=False)` and `rd.addon_dirs` — no duplicated
  logic; the gate's behavior is byte-identical (all 6 pre-existing
  `test_check_versions.py` tests pass unchanged).
- ✅ **MF-1 regression guard:** `test_release_detect.py` asserts gate-mode and
  tool-mode return the SAME set on a committed tree (single + multiple changed),
  and that the only legitimate divergence is an UNCOMMITTED edit (tool sees it,
  gate does not). 14 detector tests, 100% coverage on `release_detect`.
- ✅ **O7 (the CI gap the de-pinning made load-bearing):** wired
  `check_versions.py` into `.github/workflows/generate_repo.yml` as a MAIN-ONLY
  "Version-bump gate" step. Because on a `main` push `origin/main` already equals
  the pushed HEAD (the default baseline would compare a commit against itself and
  pass vacuously), the step points the gate at the push's `github.event.before`
  SHA via a new `CHECK_VERSIONS_BASE_REF` env override (empty override ignored →
  falls back to `origin/main`; the all-zeros first-push "before" and a missing
  baseline are skipped cleanly). CI still NEVER commits — validate only. 3 new
  override tests prove it catches an unbumped pushed range and passes a bumped one.
- **Acceptance MET:** 899 passed / 1 xfailed (+17 new); 100% coverage on
  `release_detect`; the gate flags an unbumped change (hook + CI); existing
  hook/CI behavior preserved; deterministic regen; NO add-on bump. Commit (local):
  `feat(release): shared changed_addons detector + CI version gate (Phase 2)`.

### Phase 3 — `release.py` for the `script.*` path (the headline) — SHIPPED 2026-06-10

- ✅ Added `_tools/release.py`: detect (shared `changed_addons`, worktree mode) →
  compute next version (MINOR default; `--patch`/`--major`/`--version`) →
  auto-draft + PREPEND news (`--news` override, per-addon `id=line` or bare) →
  raise lockstep import + bump holder atomically (MF-2) → `generate_repo.py` →
  determinism gate → script-side consistency gate → commit on the branch → STOP.
  `--dry-run` (prints WHICH files per add-on, MF-4), `--push` (opt-in),
  `check` sub-command (the script-side consistency gate). Full rollback
  (`git reset --hard <pre-release HEAD>`) on any mid-transaction failure.
- ✅ **Guardrails (the QA must-fixes):**
  - MF-2 atomic lockstep: the dependency graph is read live (`dependents_of`), so
    a library bump always raises every dependent's `<import>` AND bumps it; a
    `--addon script.module.tony7bones` scoped run auto-includes bootstrap (O9:
    auto-include, not refuse).
  - MF-5 behind-origin preflight (ported from `deploy.py`): refuses when the
    branch is behind its origin counterpart; offline fetch degrades to a warning.
  - MF-6 idempotency: an already-bumped-but-unpushed add-on with NO new source
    change since its bump commit is a NO-OP (printed "already released"), never a
    double-bump (O10: no-op with a message). Implemented via
    `_last_version_change_commit` + `_source_changed_since` (compares source —
    excluding `addon.xml`'s own version/news — between the last bump and the tree).
  - MF-7 single bump regardless of reason count (source + lockstep → one bump).
  - MF-8 single-digit ceiling: a 9.9.9 add-on with a source change fails cleanly
    with a readable "version space exhausted … use --version" message, not a
    traceback.
  - MF-9 news prepended once, capped at `NEWS_CAP` (6), idempotent on re-run.
- ✅ **Tests** (`_tools/test_release.py`, mirroring `test_deploy.py`): 22
  bare-remote e2e (happy path, lockstep atomicity, modv2plus independence,
  dry-run snapshot, idempotent re-run no-op, news cap, behind-origin/ceiling/
  double-digit/unknown-addon refusals, determinism, push vs default-no-push,
  rollback-on-push-failure) + 29 in-process tests (build_plan, lockstep two-pass,
  news drafting, script_consistency, idempotency, `main()`/`check`/`--patch`/
  `--dry-run`, behind-origin, push, rollback). 51 tests; **92% line coverage on
  `release.py` from the in-process suite alone** (the remaining lines are
  offline/error-print branches the subprocess e2e tests exercise).
- ⚠️ **Test-safety hardening (lesson encoded):** `release.git()` resolves `REPO`
  at CALL time (not as a default arg bound at import) so an in-process test that
  monkeypatches `release.REPO` to a sandbox redirects EVERY git call — including
  the rollback `git reset --hard` — into the sandbox, never the real repo. The
  `inproc` fixture asserts `REPO` is the sandbox before running, as a tripwire.
  (A default-arg binding of `REPO` is a footgun: a sandbox rollback can reset the
  real working tree.)
- **Acceptance MET:** 950 passed / 1 xfailed; ≥90% coverage on `release.py`;
  `--dry-run`/`check` demonstrated live (reports "no changed add-ons" + lockstep
  in sync on the current tree); the manual path is untouched (the tool is opt-in,
  the hook still backstops a hand-edit); deterministic regen; ruff + secret-leak
  green; NO add-on bump by the work. Commit (local): `feat(release): release.py
one-command bump+news+lockstep (Phase 3)`.

### Phase 4 — Make it the documented default; auto-derive the version table

- Update `docs/playbooks/release-and-deploy.md`: Path A becomes "run
  `release.py`"; keep the manual steps as the fallback. Generate the "current
  versions" table from the manifests so it stops drifting.
- **Acceptance:** playbook updated; a script regenerates the version table; QA
  signs off the docs.

### Phase 5 — Unify the proxy path (optional end state)

- Fold `deploy.py`'s proxy transaction into `release.py` (Decision 5b); `deploy.py`
  becomes a thin shim that calls `release.py --addon repository.tony7bones`.
- **Acceptance:** the proxy release is byte-for-byte equivalent through the new
  tool (sandbox + live dry-run); `npm run deploy:*` wrappers still work.

---

## Open questions for the owner (need your call)

- **O1 — Bump-level default. RESOLVED (2026-06-10): MINOR by default**, with
  `--patch` / `--major` / `--version` overrides. NOT conventional-commit
  auto-level by default; `--auto-level` stays an opt-in suggestion mode.
- **O2 — News source. RESOLVED (2026-06-10): AUTO-DRAFT** the news line from
  commit subjects, override with `--news`.
- **O3 — News history. RESOLVED (2026-06-10): PREPEND** — switch `set_addon_news`
  from REPLACE to PREPEND, keep a rolling ~6 entries (capped).
- **O4 — Push behavior. RESOLVED (2026-06-10): commit-on-branch, do NOT push.**
  The owner keeps the branch → merge → main flow; `--push` may exist but is never
  the default. (No auto-push / auto-merge.)
- **O5 — Unify the tools (Phase 5). RESOLVED (2026-06-10): EVENTUALLY UNIFY**
  both paths under one `release.py`, **phased** so the working proxy `deploy.py`
  is never broken (Phase 5 stays last and optional).
- **O6 — Lockstep direction. RESOLVED for the TEST (2026-06-10): strict `==`.**
  The shipped lockstep test (now de-pinned, Phase 1) asserts bootstrap's import
  **equals** the library's actual version — a `>=` floor would let the manifests
  drift silently and is a coverage regression vs the old literal. (The _runtime_
  Kodi `<import>` min-version semantics are unchanged; this is about what the
  manifests must SHIP. See O8 for the explicit runtime-vs-test split, still open.)

### Still open (QA's O7–O10 — genuinely unresolved)

- **O7 — Does `check_versions.py` run in CI? CONFIRMED: NO — must-fix for Phase 2.**
  `check_versions.py` (the per-add-on monotonic "every changed add-on bumped"
  gate) runs **only** in `.githooks/pre-push` (line 33). CI
  (`.github/workflows/generate_repo.yml`) runs the test suite, ruff, the
  generated-staleness check, and `check_consistency.py` (the **proxy-only**
  3-location gate, main-only, line 78) — but **never invokes `check_versions.py`.**
  Phase 1's de-pinning REMOVES the literal pins that implicitly froze a known-good
  version, so the monotonic guarantee now lives **only** in the hook. A push from
  an un-hooked clone, a `--no-verify` push, or any non-hooked path therefore loses
  the "every changed add-on is bumped" guarantee entirely. **This is a real,
  pre-existing CI gap that the de-pinning makes load-bearing.** Phase 2 MUST add
  `check_versions.py` (or the shared `script_consistency` gate that subsumes it)
  to CI on `main`. Not fixed in Phase 1 (out of scope: Phase 1 is test-only and
  ships no `addons/**` change), but recorded here as a Phase 2 must-fix.
- **O8 — Should the lockstep TEST assert `==` even if the runtime O6 decision is
  `>=`?** QA recommendation (and the Phase 1 implementation): the shipped lockstep
  **test** asserts `==` regardless of any runtime min-version floor. Confirm this
  split is the intended permanent policy.
- **O9 — Scoped `--addon` that excludes a must-re-ship dependent (MF-2).**
  Auto-include the dependent (recommended) or hard-refuse with a message? Owner's
  call — deferred to Phase 3 (the tool does not exist yet).
- **O10 — Idempotency policy on re-run (MF-6).** No-op silently, or print "already
  released at vX.Y.Z (run `--force` to re-bump)"? Recommend: no-op with an explicit
  message, never silent. Deferred to Phase 3.

---

## Proposed TASKS.md snippet

```markdown
## Release automation — kill manual version bumping (script.\* path)

- [ ] P0 Generalize release_lib (set_import_version; proxy helpers isolated) — deploy.py + tests unchanged
- [x] P1 De-pin tests: test_module.py / test_bootstrap.py assert the relation (library single-digit; bootstrap import == library, strict ==) + negative tests. Shipped 2026-06-10, NO add-on bump. (O7 CI gap recorded as a Phase 2 must-fix.)
- [ ] P2 changed_addons() detector + script-side consistency gate (single-digit / monotonic / lockstep) wired into hook + CI
- [ ] P3 release.py for script.\* : detect → bump (minor default) → news → lockstep → regen → determinism gate → commit; --dry-run/--patch/--news/--push/check; rollback on failure; sandbox e2e test; ≥90% cov
- [ ] P4 Make release.py the documented Path A; auto-derive the version table in the playbook
- [ ] P5 (optional) Unify: deploy.py becomes a shim over release.py --addon repository.tony7bones
- Open Qs for owner: O1 level default, O2 news source, O3 news prepend, O4 push default, O5 unify, O6 lockstep ==/>=
```

---

## QA REVIEW

> Reviewed against the live machinery: `_tools/check_versions.py`,
> `check_consistency.py`, `release_lib.py`, `deploy.py`, `test_deploy.py`,
> `test_check_versions.py`, the two pinned tests (`test_module.py:61`,
> `test_bootstrap.py:840`), `.githooks/pre-push`, and the shipped first-party
> `addon.xml` files. Verdict and rationale below; the design is sound but ships
> with **must-fix** gaps that, if unaddressed, would make the automation
> LESS safe than the manual process at exactly the failure points that matter.

### Verdict: ACCEPT-WITH-CHANGES

The architecture (reuse the proven diff, share one detection function, de-pin to
relational asserts, sandbox-test like `deploy.py`, hook stays a fail-closed
backstop) is the right one. But the prime directive — "automation must be SAFER
than the manual process" — is only met if the must-fix items below are folded in.
Three of them (MF-1, MF-2, MF-5) are correctness bugs that could ship a WRONG or
MISSING bump; the rest harden the guards to the existing ≥90%/gated bar.

---

### 1. Failure-mode analysis

Each row: the failure, how it ships a wrong/missing bump, severity, and the guard
that MUST exist. "Missing bump" = a same-version byte change = the cardinal sin.

**MF-1 (HIGH) — Detector baseline mismatch between tool and gate (pre-commit vs
pre-push semantics).** The plan's Decision 1 says the _tool_ diffs `origin/main`
against the **working tree** (`git diff origin/main -- …`, no `HEAD`), while the
_gate_ (`check_versions.py`) diffs `origin/main..HEAD` (lines 55–64, committed
only). These are NOT the same comparison. Concrete break: the tool runs, computes
"library changed → bump," writes the bump, commits. The owner then makes ONE more
hand edit to a third add-on and force-amends, or stages-but-forgets a file. The
two definitions can now disagree about what changed, and a release can pass the
tool but be re-judged differently by the hook (or vice-versa). The plan asserts
"the detector and the gate can never disagree" but then specifies two different
git invocations for them. _Guard:_ the shared `changed_addons(base_ref, *,
worktree: bool)` MUST take an explicit mode flag and BOTH call sites must route
through it; the e2e suite must assert tool-mode and gate-mode return the **same
set** for a committed tree. Do not let "working tree" and "HEAD" be implicit.

**MF-2 (HIGH) — Lockstep is bumped but the dependent's bump can be MISSED on
re-run / partial run.** Decision 3 bumps the library, raises bootstrap's import,
and bumps bootstrap. But the _trigger_ for bumping bootstrap is "its source now
differs." If the library bump and import-raise land in commit A, but the run
aborts before bootstrap's own `version=` is written (interrupt, gate failure
mid-write, a `--addon script.module.tony7bones`-scoped run), the repo now has
bootstrap's `addon.xml` changed (import raised) **without** bootstrap's version
bumped — a same-version byte change. `check_versions` would catch it on push ONLY
if bootstrap's dir diffs against `origin/main`, which it does — good, the hook is
the net. But the _tool itself_ must treat "raise an import" and "bump the holder"
as one atomic unit: never raise an import without, in the same transaction,
bumping the holder. _Guard:_ (a) reject `--addon script.module.tony7bones` in
isolation when bootstrap imports it unless bootstrap is also in the change set
(or auto-include bootstrap); (b) e2e test: library-only scoped run still bumps
bootstrap; (c) e2e test: kill the run after the import-raise and assert rollback
leaves bootstrap's version == origin/main (no orphaned import bump).

**MF-3 (MED) — Detector misses a source change that lives OUTSIDE
`addons/<id>/`.** The diff is scoped to `addons/<id>` minus zip/index. But a
first-party add-on's _behavior_ can change without its own dir changing: e.g.
bootstrap and the modv2plus service both depend on the shared library's Python;
a change to `script.module.tony7bones/lib/**` correctly bumps the library, and
the lockstep correctly forces a bootstrap re-ship. That path is covered. The
real gap: shared _non-addon_ code that gets vendored/copied into an add-on at
generate time, or a generator change that alters a zip's _contents_ without
touching the add-on source. Today the generator is pure-mirror so this is
latent, but if `generate_repo.py` ever starts injecting computed content into an
add-on zip, the source-diff detector would see "no source change" while the
shipped zip bytes changed → missing bump. _Guard:_ document the invariant that
"add-on zip bytes are a pure function of `addons/<id>/` source (minus excludes)";
add a determinism/repro test that a generator change which alters zip bytes for
an unchanged-source add-on is either impossible or itself flagged. Severity MED
because it is latent today, but it is exactly the class the manual process also
couldn't catch — flag it so it never silently regresses.

**MF-4 (MED) — Whitespace / no-op / mode-only diffs trigger a needless bump.**
`git diff --quiet` returns "changed" for a pure whitespace or line-ending or file-
mode change in a source file. That is not a wrong bump (it's safe — over-bumping
never breaks Kodi upgrades, only burns version space), but with the single-digit
ceiling (9.9.9) and the owner's dislike of churn, needless minor bumps from a
re-indent are real friction. _Guard:_ acceptable to leave as-is (safe side), but
`--dry-run` MUST surface _why_ an add-on is considered changed (show the diffstat
/ changed file list, not just "changed"), so the owner can spot a no-op trigger
before committing a wasted version. Add a dry-run snapshot test asserting the
changed-files list is printed.

**MF-5 (HIGH) — Baseline drift: `origin/main` moved during the run.** Both the
tool's preflight and the diff read `origin/main`. `deploy.py` already guards this
with `_behind_origin()` (fetch + `rev-list --count main..origin/main`). The new
tool MUST do the same: if `origin/main` advanced after the tool computed its plan
(another machine pushed), the computed "next version" can collide or the diff
baseline is stale → wrong bump target. The plan's Decision 7 lists monotonic/
single-digit/determinism/rollback but **omits the behind-origin preflight**.
_Guard:_ port `deploy.py`'s `_behind_origin()` into the new tool's preflight;
negative test: tool refuses when `main` is behind `origin/main`.

**MF-6 (MED) — Re-run / idempotency double-bump.** Run the tool, get
library 1.5.0→1.6.0 committed but NOT pushed. Run it again. Does it see "library
changed vs origin/main (still 1.5.0)" and bump AGAIN to 1.7.0? With the
working-tree-vs-`origin/main` baseline, the already-committed bump still diffs
against the un-advanced `origin/main`, so yes — a second run would re-bump.
_Guard:_ the tool must detect "this add-on already has a version greater than
`origin/main` AND its only change since `origin/main` is the version/news bump
itself" and treat that as already-released (no-op), exactly the way
`check_versions` _passes_ an already-bumped add-on. Idempotency test: running the
tool twice with no intervening source edit produces the SAME tree the second time
(second run is a no-op). This is the single most likely real-world footgun (the
owner re-runs after a typo) — must-fix.

**MF-7 (MED) — Concurrent change to both add-ons + dependency order.** If the
same working tree changes both library and bootstrap source independently, the
two-pass (leaves first) must: bump library → raise bootstrap import to the NEW
library version → bump bootstrap ONCE (not twice — once for its own source, once
for the import raise). _Guard:_ the bootstrap bump is a single computed step
regardless of how many reasons it changed; e2e test: both changed → library
bumped once, bootstrap bumped once, import == new library version.

**MF-8 (LOW/MED) — Single-digit rollover at the 9→boundary inside auto-level.**
`release_lib.bump` handles rollover and the 9.9.9 ceiling (raises ValueError).
The tool must surface that ValueError as a clean preflight failure (like
`deploy.py:127`), not a traceback, and `--auto-level` must never silently pick a
level that hits the ceiling without telling the owner. _Guard:_ negative test —
an add-on at 9.9.9 with a source change fails the tool with a readable "version
space exhausted" message; the owner is told to use `--version` to reset major
(or that this needs a human decision).

**MF-9 (MED) — News non-determinism breaks the determinism gate.** If
`set_addon_news` auto-drafts from commit subjects (Decision 3c) AND the plan
switches to PREPEND (O3), the news body now contains free text derived from git
log. Re-running the tool after a commit would produce a DIFFERENT news line →
the determinism gate (`generate_repo.py` twice → clean) still passes (news is
written once, before generate), BUT the idempotency property (MF-6) is harder:
the second run must not re-draft and re-prepend a duplicate entry. _Guard:_ news
is computed once per release transaction and the prepend must be idempotent (if
the top entry already reads `vX.Y.Z:` for the version being shipped, do not
prepend again). Test: double-run does not stack duplicate news entries; the
N-entry cap (≤6) is enforced and tested.

---

### 2. The de-pinning risk (the keystone)

**What the two literal pins actually caught.** `test_module.py:61`
(`version == "1.5.0"`) and `test_bootstrap.py:840` (`import version == "1.5.0"`)
are crude, but they caught one real, high-value regression class: **a release
that bumped the library's `addon.xml` but FORGOT to raise bootstrap's `<import>`
in lockstep** (or vice-versa) — because at least one of the two literals would
then fail to match the new common value. They also caught a _typo'd_ version
(`1.5.O`, `1..5.0`) by exact-match. They did NOT catch much else: they are stale
the moment a release ships, and (the plan's own insight) a forgotten lockstep
bump would PASS the literal pin if the old literal happened to still match.

**What the relational asserts must replace them with — exact assertions.**
Replacing `==` with a relation only preserves coverage if the relation is
_strict and cross-manifest_. Specify:

- In `test_module.py`: parse the library `addon.xml`; assert
  `rl.is_single_digit(version)` AND `rl.parse_version(version)` does not raise.
  (Catches malformed / double-digit / typo'd versions — the well-formedness half
  of the old pin.)
- In `test_bootstrap.py`: parse BOTH manifests; assert
  `bootstrap.import("script.module.tony7bones").version == library.version`
  **exact string equality**, not `>=`. (This is the lockstep guard the old
  literal only approximated.) See O6 — recommend strict `==` here; a `>=` floor
  would let the two drift and the test would not catch it, which is a coverage
  REGRESSION versus the literal pin.

**NEW tests the de-pinning DEMANDS (or coverage drops):**

1. **Lockstep negative test (in-fixture mutation).** Build a temp pair of
   manifests where the library is bumped but bootstrap's import is NOT raised;
   assert the relational test FAILS. Without this, the relational assert can pass
   _vacuously_ (e.g. if a parse helper silently returns `None == None`). Phase 1's
   acceptance already lists this — make it a hard gate, and assert the failure is
   on the _mismatch_, not on a parse error.
2. **Well-formedness negative test.** A double-digit (`1.10.0`) or malformed
   library version makes the module test FAIL.
3. **Monotonic-increase test in CI (the real replacement for the lost literal).**
   The literal pin implicitly froze a known-good version; its replacement is a
   gate that asserts every changed add-on's version is **strictly greater than
   `origin/main`**. This is what `check_versions` does — so the keystone is:
   **`check_versions` MUST run in CI, not only the pre-push hook.** Confirm CI
   invokes it (the hook does; CI must too) so the de-pinning does not move the
   monotonic guarantee from "always" to "only on push from a hooked clone."
4. **"Every changed add-on is bumped" test runnable in CI** — already
   `check_versions`; assert it covers all three first-party add-ons by id, so a
   newly-added fourth add-on is automatically in-scope (the gate iterates
   `addons/*/addon.xml`, so it is — add an explicit test asserting the iteration
   includes each first-party id).
5. **Lockstep-consistency test driven by the new script-side consistency gate**
   (Phase 2): assert `bootstrap.import == library.version` reading from git refs
   (like `check_consistency` reads main), so it validates what will SHIP, not the
   working tree.

Net: the relational tests are strictly safer than the literals **iff** assertions
above are `==`/strict and the monotonic guarantee is moved into CI, not just the
hook. With `>=` on the lockstep, de-pinning is a regression — flag O6 as
**must-resolve to `==`** for the test (the _runtime_ import floor can still be
whatever Kodi needs; the test asserts the shipped lockstep equals the library).

---

### 3. Test strategy for the automation itself (must-have cases)

Mirror `test_deploy.py`'s two layers: pure-unit + bare-remote e2e. The new
`release.py`/`changed_addons`/script-side consistency modules need the same
≥90% coverage and the same gated treatment. Must-have cases:

**Pure unit (release_lib generalization, Phase 0):**

- `set_import_version(xml, addon_id, version)` sets the right import, leaves other
  imports untouched, is idempotent, raises if the import is absent.
- The generalized addon.xml transforms work for an arbitrary `addon_id` (not just
  `repository.tony7bones`) and `deploy.py`'s proxy path is byte-identical after
  the refactor (regression: run the existing `test_deploy.py` e2e unchanged).

**Detector (`changed_addons`, Phase 2):**

- Returns the changed set, gate-mode (`origin/main..HEAD`) and tool-mode
  (working-tree) agree on a committed tree (MF-1).
- Source change → included; zip-only / index-only change → excluded (mirror
  `test_check_versions.py::test_ignores_generated_zip_and_index`).
- New add-on with no baseline → handled (no crash).
- No `origin/main` → skip cleanly (mirror `test_skips_when_no_origin`).

**Script-side consistency gate (Phase 2):**

- Flags an unbumped source change (returncode 1).
- Flags a broken lockstep (import != library).
- Flags a double-digit / malformed version.
- Passes a clean, bumped, in-lockstep tree.
- Reads from git refs (validates what ships), reused by hook + CI (one function).

**`release.py` end-to-end sandbox (Phase 3, bare remote like `test_deploy.py`):**

- _Happy path:_ edit a `script.*` source → run → correct bump + news + regen +
  commit; tree clean after; determinism gate green.
- _Lockstep:_ edit library source → library bumped, bootstrap import raised to
  new version, bootstrap bumped, both in one commit (MF-2, MF-7).
- _modv2plus independence:_ edit modv2plus → only modv2plus bumps; library and
  bootstrap untouched.
- _Dry-run snapshot:_ `--dry-run` changes nothing on disk and prints the changed-
  files reason per add-on (MF-4); snapshot the plan text.
- _Determinism:_ after the tool's writes, `generate_repo.py` twice → zero diff;
  no `__pycache__`/`.ruff_cache` leaks into the zip (the bug that shipped a
  stray cache in modv2plus-1.4.7).
- _Idempotency (MF-6):_ run twice, no intervening edit → second run is a no-op;
  news not double-prepended (MF-9); version not double-bumped.
- _Negative — dirty tree:_ refuse (or refuse to push) on a dirty tree where it
  would matter; match `deploy.py`'s clean-tree preflight semantics for `--push`.
- _Negative — behind origin (MF-5):_ refuse when `main` is behind `origin/main`.
- _Negative — ceiling (MF-8):_ add-on at 9.9.9 + source change → readable refusal.
- _Negative — detector vs gate disagreement:_ construct a tree where a naive tool
  would bump but the gate would not (or vice-versa) and assert they agree (this
  is the regression test for the shared-function contract, item 4).
- _Rollback:_ inject a failure at EACH transaction step (after version write,
  after news, after generate, after commit, after the consistency gate) and
  assert the tree returns exactly to pre-release HEAD and nothing is pushed
  (mirror `deploy.py`'s `git reset --hard main_head` + `git tag -d`).
- _Coverage:_ assert ≥90% line coverage on `release.py` + the new modules; CI
  fails under threshold.

---

### 4. Guardrail integration — the shared-detection contract

The plan's whole safety claim rests on "the detector and the gate can never
disagree." Today that is achieved for the proxy by `check_consistency.check()`
backing three call sites. The new tool must follow the SAME pattern, with a
hardened contract:

**Contract:**

- ONE function `changed_addons(repo, base_ref, *, worktree: bool) -> set[str]`
  lives in a single module (suggest `release_lib` or a sibling `release_core`),
  imported by BOTH `check_versions.py` (gate, `worktree=False`) and `release.py`
  (tool, `worktree=True` pre-commit). `check_versions.py`'s inline diff (lines
  55–64) is REPLACED by a call to it — not duplicated. (Per MF-1, the `worktree`
  flag is the only difference, and the e2e suite proves both modes agree on a
  committed tree.)
- ONE function `script_consistency(repo, ref) -> (ok, info, problems)` (the
  script-side analog of `check_consistency.check`) backs the hook, CI, and the
  tool's pre-commit assertion — asserting per changed add-on: well-formed,
  single-digit, `is_greater` vs `origin/main`, and `bootstrap.import ==
library.version`. The tool calls it BEFORE committing; the hook + CI call it on
  the refs. Divergence is structurally impossible because there is one
  implementation.
- The version math stays exclusively in `release_lib` (`bump`, `is_greater`,
  `is_single_digit`) — the tool MUST NOT re-implement any comparison.
- **Regression guard for the contract:** a test that deliberately would let the
  tool and gate diverge (different baseline, different exclude globs) and asserts
  they return the same verdict. If this test is absent, the contract is just a
  comment.

**Why this is non-negotiable:** a divergence means a release passes the tool,
the owner merges, and the pre-push hook then BLOCKS the push (annoying) — or
worse, the tool under-bumps, the _hook's_ `check_versions` happens to agree
(because it shares the bug), and a same-version byte change ships. The shared
function is the only thing that makes "automation safer than manual" true.

---

### 5. Rollout safety

- **Phase 0 (generalize `release_lib`)** — correctly a no-op for `addons/**`, so
  no bump. Its acceptance ("`deploy.py` + all tests pass byte-for-byte") is the
  right gate. **Confirm:** run the existing `test_deploy.py` e2e unchanged after
  the refactor as the proof that the proxy path is untouched. Independently
  shippable. OK.
- **Phase 1 (de-pin tests)** — touches only `_tools/test_*.py`, NOT `addons/**`.
  **Confirmed:** `check_versions.py` iterates `addons/*/addon.xml` and diffs each
  add-on dir; a change under `_tools/` is invisible to it, so it correctly does
  NOT demand a bump. Verified against the gate's diff scope (lines 52–64). Phase 1
  truly needs no add-on bump. The ONE caveat: Phase 1 must land the relational
  asserts with the negative tests (MF/keystone item 1–2) IN THE SAME commit, or
  the suite briefly has weaker coverage than before. Independently shippable. OK.
- **Phase 2 (detector + script consistency gate)** — additive, fail-closed,
  behind existing gates. Risk: wiring a new gate into the hook can block
  legitimate pushes if the gate is buggy. **Require:** the gate ships with its
  full negative-test suite and a `check`-only entry point before it is wired into
  the hook, and it must SKIP cleanly when there is no `origin/main` (mirror
  `check_versions`'s skip — do not let a fresh clone or CI shallow checkout fail
  closed for the wrong reason). Independently shippable. OK with that guard.
- **Phase 3 (`release.py`)** — opt-in; manual path still works. This is the right
  sequencing: the tool is additive and the hook still backstops a hand-edit.
  **Confirm the manual path is genuinely intact** — i.e. a human who bumps by
  hand and never runs `release.py` still passes all gates. The plan says so;
  add a test/CI assertion that the manual happy-path (hand-bumped tree) passes
  the new script-side gate. Independently shippable. OK.
- **Phase 4 (docs + auto version table)** — docs-only; the auto-derived table is
  good (kills the documented drift). No release risk.
- **Phase 5 (unify proxy into `release.py`)** — the only phase with real
  regression risk to the WORKING proxy release. Its acceptance ("byte-for-byte
  equivalent through the new tool; `npm run deploy:*` still work") is correct but
  must be enforced by keeping the _entire existing_ `test_deploy.py` e2e suite
  green against the unified tool, plus a live `--dry-run` against the real origin
  before the first real unified release. Flag: Phase 5 is genuinely optional —
  do not let it block the headline value (Phases 1–4). Recommend explicitly
  marking Phase 5 as "defer until 1–4 are hardware-proven on a real release."

**No phase is mis-sequenced.** Each is independently shippable. The only rollout
risk is shipping Phase 2's gate into the hook before its negative tests exist —
called out above.

---

### 6. Must-fix items, open questions, and verdict

**Must-fix (before/with implementation):**

- **MF-1** — Shared `changed_addons(base_ref, *, worktree)` with an explicit mode
  flag; both call sites route through it; test proves both modes agree on a
  committed tree.
- **MF-2** — "Raise an import" and "bump the holder" are one atomic unit; reject
  (or auto-include) a library-only scoped run that would orphan a bootstrap import
  bump; rollback test for a mid-lockstep abort.
- **MF-5** — Port `deploy.py`'s `_behind_origin()` preflight into the new tool;
  negative test.
- **MF-6** — Idempotency: a second run with no source edit is a no-op (no
  double-bump, no double-news). Highest real-world footgun.
- **De-pinning keystone** — lockstep test asserts strict `==` (NOT `>=`); add the
  in-fixture negative test (mutated library w/o import raise FAILS); **move the
  monotonic guarantee into CI** by confirming `check_versions.py` runs in CI, not
  only the pre-push hook.
- **Shared-detection contract** — one `changed_addons` and one
  `script_consistency` function back tool + hook + CI, with a regression test that
  asserts tool and gate cannot disagree.

**Should-fix:**

- MF-3 (document the "zip bytes are a pure function of source" invariant + repro
  test), MF-4 (`--dry-run` prints the changed-files reason), MF-7 (single bootstrap
  bump regardless of reason count), MF-8 (clean ceiling refusal), MF-9 (idempotent,
  capped news prepend).

**New open questions for the owner (architect did not list):**

- **O7 — Does `check_versions.py` (the monotonic gate) currently run in CI, or
  only in the pre-push hook?** Confirmed it runs in the hook (`.githooks/pre-push`
  line 33). The plan's de-pinning REMOVES the literal that implicitly froze a
  known version; the monotonic guarantee must then live in CI too, else a push
  from an un-hooked clone (or `--no-verify`) loses it. **Must confirm CI invokes
  `check_versions.py`** — if it does not today, that is a pre-existing gap the
  de-pinning makes load-bearing.
- **O8 — Should the lockstep TEST assert `==` even if the runtime O6 decision is
  `>=`?** QA recommendation: the shipped lockstep test asserts `==` (so the
  manifests cannot silently drift), independent of whatever min-version floor
  Kodi enforces at install. Confirm this split.
- **O9 — What is the desired behavior when the tool detects a change but the owner
  passes a scoped `--addon` that EXCLUDES a dependent that must be re-shipped
  (the MF-2 case)?** Auto-include the dependent (recommended) or hard-refuse with
  a message? The owner should pick.
- **O10 — Idempotency policy (MF-6):** on a re-run with an already-bumped-but-
  unpushed add-on, no-op silently, or print "already released at vX.Y.Z (run
  `--force` to re-bump)"? Recommend: no-op with an explicit message, never silent.

**Bottom line:** the plan's architecture is correct and the phasing is sound and
shippable. It becomes SAFER than the manual process only once MF-1/2/5/6, the
strict-`==` lockstep + monotonic-in-CI keystone, and the single shared-detection
contract are in. As written, the working-tree-vs-`HEAD` detector split (MF-1),
the missing behind-origin preflight (MF-5), and the re-run double-bump (MF-6) are
real holes the manual process did not have. Fix those and this is a clear ship.

#### One concrete doc note (not silently rewritten)

The plan's "Current state" section (line 130) states current shipped bootstrap is
`1.8.0`; the live `addons/script.tony7bones.bootstrap/addon.xml` reads
`version="1.8.0"` and its `<import>` of `script.module.tony7bones` reads
`version="1.5.0"`, matching the live library `addon.xml` `version="1.5.0"` — so
the lockstep is currently in sync and the de-pinning baseline is clean. No error;
recorded as confirmation, not a fix.
