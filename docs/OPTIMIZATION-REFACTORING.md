# Optimization & Refactoring Backlog

> Recommendations captured from the `hybrid-repo` review session (2026-06-04).
> None of these are implemented yet — they're queued for a local development
> session. Each item notes its **blast radius** and whether output stays
> **byte-identical**. Companion docs: `HYBRID-REPO-HANDOFF.md` (context),
> `repository-github-strategy-review.md` (the strategy), `NEXT-TASK.md` (first task).

---

## How to use this file

Tackle in this suggested order. The first group (Refactor #1 + #4 + #5, then
Optimization #1) is one cohesive, low-risk change set that also unblocks the
date-cache speedup. Verify after each change with:

```bash
pytest _tools/ -q        # expect 61 passed (add tests for new behavior)
ruff check _tools/
python3 _tools/generate_repo.py && git status --porcelain   # expect clean
```

---

## Part A — Performance optimizations

### A1. Kill the per-file `git log` subprocess  ⭐ biggest win
**Where:** `_tools/generate_repo.py` — `_fmt_date()` / `_git_date()` (lines ~43–73),
called by `generate_asset_indexes()` and `process_addons()`.
**Problem:** `_fmt_date()` shells out to `git log -1` **once per file**. Across
`repositories/` (13 zips), `media/`, `iptv/`, `rss/`, and the `modv2.patch` XML
tree that's dozens of process forks every run — the dominant cost.
**Fix:** do one `git log --name-only --format=…` traversal up front, build a
`dict[path → last-commit-date]`, and look up from it. N subprocesses → 1.
**Blast radius:** low. **Output:** byte-identical (date *values* unchanged).
**Note:** lands naturally in the new `repo_common.py` module (Refactor R1).

### A2. Cache GitHub API calls in the prototype (avoid rate limits)
**Where:** `_tools/external_addons.py` — `GitHubResolver`.
**Problem:** hits `/releases/latest` + raw `addon.xml` for **every entry on every
generate run**. Unauthenticated GitHub is 60 req/hr — burns out fast in CI.
**Fixes:** (a) send `If-None-Match`/ETag and skip on `304`; (b) cache resolved
`(id → tag, version)` keyed by tag so unchanged releases don't re-download;
(c) use `GITHUB_TOKEN` in CI for the 5000/hr limit.
**Blast radius:** medium (only matters once a real manifest exists).

### A3. Tighten the CI trigger
**Where:** `.github/workflows/generate_repo.yml`.
**Problem:** fires on `repo/**`, so dropping any media/iptv file re-runs the full
validate+regenerate+commit cycle. `fetch-depth: 0` (full history) is only needed
for the git-date lookup.
**Fix:** narrow paths to those that actually affect generated output; if A1's date
cache is adopted, consider shrinking the clone depth.
**Blast radius:** low (CI config only).

### A4. (micro) Lazy fetchers in `GitHubResolver.__init__`
See Refactor R5 — it's both a cleanliness and a tiny perf fix.

---

## Part B — Structural refactors

### R1. Break the circular dependency between the two modules  ⭐ top priority
**Where:** `_tools/generate_repo.py` ↔ `_tools/external_addons.py`.
**Problem:** `generate_repo.generate()` does `from external_addons import …`, **and**
`external_addons._write_external_zip()` does `import generate_repo as gr` then reaches
into private symbols (`gr._fmt_date`, `gr._make_index`, `gr._fmt_size`). This is a
**bidirectional import cycle** that only works because both imports are lazy
(function-local). Fragile, and reaching into another module's `_private` helpers is a
smell.
**Fix:** extract shared helpers into a new `_tools/repo_common.py`:
`_make_index`, `_styled_page`, `_fmt_date`, `_fmt_size`, `_git_date`, `_zip_is_stale`.
Both modules import from `repo_common`; neither imports the other except the one-way
feature hook in `generate()`. Cycle gone, private reach-through gone, and
`repo_common` becomes the home for A1's date cache.
**Blast radius:** medium (imports + test imports). **Output:** byte-identical.
**This is the single most valuable refactor — do it with A1 and R4/R5.**

### R2. Make `generate()`'s sub-generators symmetric
**Where:** `_tools/generate_repo.py` — `generate()` (~lines 233–271).
**Problem:** `scripts/` and `media/` each have a `generate_*_index()`, but the
**repositories** index is built inline (lines ~253–261). The sha256/md5 block is also
inline.
**Fix:** extract `generate_repositories_index()` and `_write_checksums(path)` so
`generate()` reads as a clean orchestration list.
**Blast radius:** low. **Output:** byte-identical.

### R3. Replace module-global config with a dataclass
**Where:** `_tools/generate_repo.py` — `REPO_DIR`, `REPOS_DIR`, `SCRIPTS_DIR`,
`MEDIA_DIR`.
**Problem:** module globals that every test must `monkeypatch.setattr` (see the heavy
test setup). A `RepoPaths` dataclass passed into functions removes the monkeypatch
ceremony and makes the functions pure/testable with plain args.
**Blast radius:** HIGH — rewrites the test suite. Defer unless already in there.

### R4. Extract a `_file_row(path)` helper
**Where:** duplicated in `process_addons`, `generate_asset_indexes`, and
`external_addons._write_external_zip`.
**Problem:** the
`f'<a href="{name}">{name}</a>  {_fmt_date(p)}  {_fmt_size(...)}'` row pattern is
triplicated.
**Fix:** one helper in `repo_common` (from R1) removes the triplication.
**Blast radius:** low. **Output:** byte-identical.

### R5. Lazy fetchers in `GitHubResolver.__init__`
**Where:** `_tools/external_addons.py` — `GitHubResolver.__init__`.
**Problem:** always builds the real urllib fetchers even when both are injected
(tests always inject), wasting closure creation on the hot test path.
**Fix:** construct the real fetcher only for an arg that is `None`.
**Blast radius:** trivial. **Output:** byte-identical.

---

## Recommended grouping

| Group | Items | Risk | Output |
|---|---|---|---|
| **1 (do first)** | R1 + R4 + R5, then A1 | low | byte-identical |
| 2 | R2 | low | byte-identical |
| 3 | A3 | low | CI only |
| 4 (when manifest goes live) | A2 | medium | — |
| 5 (only if already refactoring tests) | R3 | high | byte-identical |

The Group 1 bundle is the sweet spot: it removes the import cycle and the
private-symbol reach-through, de-duplicates the row helper, and lands the date-cache
speedup in its natural home — all while keeping generator output byte-identical and
the 61-test suite green.
