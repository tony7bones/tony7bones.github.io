# Optimization & Refactoring Backlog (main)

> Salvaged from the superseded `hybrid-repo` review (closed **PR #1**), trimmed to
> only the items that apply to the **current `main`** tree. None are implemented yet.
>
> The full original backlog - including the hybrid-prototype-only items (R1 break the
> `external_addons.py` ↔ `generate_repo.py` import cycle, R5 lazy fetchers, A2 GitHub
> API caching) - is preserved in **closed PR #1** for reference. Those do **not** apply
> to `main`: there is no `external_addons.py` here. We shipped the **virtual proxy**
> (`repository.tony7bones`) instead, so the static-vs-hybrid strategy review is moot.

Verify after any change:

```bash
python3 -m pytest _tools/ -q
ruff check _tools/
python3 _tools/generate_repo.py && git status --porcelain   # expect clean (byte-identical)
```

## Performance

### A1 - Kill the per-file `git log` subprocess ⭐ biggest win

`_tools/generate_repo.py` `_fmt_date()` / `_git_date()` shell out to `git log -1` **once
per file** - every zip under `repositories/`, plus `media/`, `iptv/`, `rss/`, and the
`modv2.patch` XML tree - dozens of process forks per run, the dominant cost. Do one
`git log --name-only --format=…` traversal up front into a `dict[path → last-commit-date]`
and look it up. N subprocesses → 1. **Low blast radius; output byte-identical** (date
values unchanged).

### A3 - Tighten the CI trigger

`.github/workflows/generate_repo.yml` fires on all of `repo/**`, so dropping any
`media/`/`iptv/` asset re-runs the full validate cycle. Narrow the `paths:` to those that
actually affect generated output. CI-config only.

## Refactors

### R2 - Make `generate()`'s sub-generators symmetric

`generate_scripts_index()` / `generate_media_index()` exist, but the **repositories**
index and the sha256/md5 block are still built inline in `generate()`. Extract
`generate_repositories_index()` and `_write_checksums(path)` so `generate()` reads as a
clean orchestration list. Low risk; byte-identical.

### R4 (minor) - Extract a `_file_row(path)` helper

The `<a href="…">…</a>  date  size` row is built in both `process_addons` and
`generate_asset_indexes` (2 sites on `main`). One helper removes the duplication. Marginal.

## Deferred - revisit later

### R3 - Replace module-global config with a `RepoPaths` dataclass

`REPO_DIR` / `REPOS_DIR` / `SCRIPTS_DIR` / `MEDIA_DIR` are module globals that every test
must `monkeypatch.setattr`. A `RepoPaths` dataclass passed into the functions removes the
monkeypatch ceremony and makes them pure/testable with plain args. **HIGH blast radius**
(rewrites the generator test suite) - **DEFERRED**; only worth it if/when already
refactoring those tests.

## Suggested order

A1 (the win) → R2 → A3 → R4. Each stays byte-identical; keep the test suite green and
`git status` clean after every step. R3 is the only one with real blast radius - leave it
until it pays for itself.
