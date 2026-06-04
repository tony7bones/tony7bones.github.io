# Playbook — Release & deploy

Two distinct release paths, the GitHub Pages gotcha that has bitten us three
times, the determinism rules, and the restore-point tags. Verified against
`_tools/deploy.py`, `_tools/check_consistency.py`, `_tools/check_versions.py`,
`_tools/generate_repo.py`, `.githooks/pre-push`, and
`.github/workflows/generate_repo.yml`.

---

## Two release paths — pick the right one

### Path A — a `script.*` / `script.module.*` add-on

For `script.module.tony7bones`, `script.tony7bones.bootstrap`,
`script.tony7bones.video`, `script.tony7bones.modv2.patch`.

1. Edit the add-on's `repo/<id>/addon.xml` — **bump `version`** (and update
   `<news>`).
2. `python3 _tools/generate_repo.py` — zips the add-on and regenerates
   `repo/addons.xml`, `.sha256`, `.md5`, and the index pages.
3. `git add` the changed source + the regenerated files.
4. `git push` — the pre-push hook runs the full gate.

**Do NOT use `deploy.py` for these.** `deploy.py` is only for the repository
add-on. The pre-push hook (`.githooks/pre-push`) enforces, in order: pytest,
`ruff check _tools/`, generated-files freshness (regenerate → tree must stay
clean), cross-branch version consistency (`check_consistency.py`), and the
per-add-on versioning gate (`check_versions.py` — _any_ add-on whose source
changed vs `origin/main`, excluding its zip + index.html, must have bumped its
`addon.xml` version).

### Path B — the repository add-on (`repository.tony7bones`)

This is the **virtual proxy installer**, and its version lives in **five**
locations across **both** branches. Never hand-edit them. Run:

```bash
python3 _tools/deploy.py --news "What changed"      # patch bump (default)
python3 _tools/deploy.py --minor --news "..."       # or --major / --version X.Y.Z
python3 _tools/deploy.py --news "..." --dry-run     # preview, change nothing
python3 _tools/deploy.py --news "..." --no-push     # local commit + tag only
python3 _tools/deploy.py check                       # consistency gate only
```

`deploy.py` does the whole transaction atomically:

1. Bump `repo/repository.tony7bones/addon.xml` (version + news).
2. Build deterministically; copy the generated zip to the **root** zip; assert
   byte-identity.
3. Rewrite the `index.html` install link to the new zip filename.
4. Commit `main`.
5. Determinism gate: regenerate — the tree must stay clean.
6. Update `virtual-repo:hosted/repository.tony7bones/addon.xml` **via a
   `git worktree`** (so `main` never leaves `main`), copy the archived zip there,
   commit.
7. Tag the `main` release commit (`vX.Y.Z`).
8. Run the cross-branch consistency gate **before** pushing.
9. `git push --atomic origin main virtual-repo refs/tags/<tag>`.
10. Verify live on Pages.

Pre-flight refuses to run on a dirty tree, off `main`, when behind origin, or
when the new version is not strictly greater than the current. **Any failure
before the push rolls main, the tag, and virtual-repo back** to their pre-deploy
state.

The **five version-bearing locations** (all kept in sync by deploy.py, all
checked by `check_consistency.py`):

| #   | Location                                            | Branch       |
| --- | --------------------------------------------------- | ------------ |
| 1   | `repo/repository.tony7bones/addon.xml` `version=`   | main         |
| 2   | root `repository.tony7bones-<ver>.zip` filename     | main         |
| 3   | `index.html` install link                           | main         |
| 4   | `hosted/repository.tony7bones/addon.xml` `version=` | virtual-repo |
| 5   | git tag `vX.Y.Z`                                    | (annotated)  |

> The version lives ONLY in `addon.xml`. `package.json` deliberately does not
> mirror it.

## Adding an add-on to what the repo SERVES

The proxy serves from its **baked** `repository.json` (read locally at runtime —
see `one-shot-and-architecture.md`). To add a served add-on:

1. Add its entry to **both** `repository.json` copies:
   - `repo/repository.tony7bones/resources/repository.json` (main — plain edit)
   - the `virtual-repo` root `repository.json` (via a worktree commit)
2. `python3 _tools/deploy.py --news "add <id>"` so the new manifest ships inside
   the installer zip.

Because the proxy reads the _baked_ manifest, the user's installed repository
add-on must update (i.e. you must release) before they see the new entry.

## GitHub Pages GOTCHA (hit 3×)

Pages frequently **skips the auto-build** on a push, so `deploy.py`'s live-verify
(`verify_live()` polls the root zip URL for HTTP 200 + sha match) times out even
though the push succeeded. Force the build, then re-poll:

```bash
gh api --method POST repos/tony7bones/tony7bones.github.io/pages/builds
# then poll:
curl -sI https://tony7bones.github.io/repository.tony7bones-<ver>.zip   # want HTTP 200
```

Key distinction:

- **Add-on zips** are served from `raw.githubusercontent.com` (main / virtual-repo)
  and are live **instantly** — no Pages build involved.
- Only the **repo installer zip** at the site root rides Pages.

(Possible future improvement: bake a force-Pages-build call into `deploy.py`.)

## CI — "Validate Kodi Repository"

`.github/workflows/generate_repo.yml`:

- Triggers on **`branches: [main]`** pushes touching `repo/**`, `_tools/**`, or
  `index.html` (plus `workflow_dispatch`). **Tag pushes are excluded** — the
  atomic main+virtual-repo+tag push re-points the tag at main's HEAD (already
  validated), and on a detached tag checkout the consistency gate can't resolve
  `main`, so a tag run fails spuriously.
- It runs the same gate as the hook (pytest, ruff, generator-staleness,
  cross-branch consistency) and **NEVER commits to main** — it only validates. If
  generated files are stale the author must regenerate and commit.
- The `docs/**` and `.claude/**` paths are **not** in the path filter, so
  doc/skill-only commits trigger no CI run.

## Determinism

`generate_repo.py` builds zips **reproducibly** and **excludes `__pycache__`**
(pyc files left by test imports made zips non-reproducible → CI staleness
failures). When committing, a freshly built zip may differ only by mtime on the
first build. Settle it:

```bash
git commit ...
python3 _tools/generate_repo.py
git commit --amend --no-edit          # absorb the settled zip
python3 _tools/generate_repo.py       # confirm: a second run yields NO diff
```

## Restore-point tags

Create a tag for any known-good state. Current ones:

- `clean-setup-1.0.17` — a bare, clean baseline.
- `perfectly-working-2026-06-04` — full working build before the one-shot work.

## Current live versions (as of this writing)

| Add-on                          | Version |
| ------------------------------- | ------- |
| `repository.tony7bones`         | 1.0.11  |
| `script.module.tony7bones`      | 1.0.0   |
| `script.tony7bones.bootstrap`   | 1.1.0   |
| `script.tony7bones.video`       | 1.1.0   |
| `script.tony7bones.modv2.patch` | 1.0.3   |
