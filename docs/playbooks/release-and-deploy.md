# Playbook — Release & deploy

**One command releases everything: `python3 _tools/release.py`.** It auto-detects
which add-ons changed, computes the next version, drafts + prepends the news,
raises the lockstep import, regenerates, gates, and commits — no hand-editing of
`addon.xml`, no manual `<news>`, no pinned-test edits. Below: the two release
_modes_ the one tool routes between, the GitHub Pages gotcha that has bitten us
three times, the determinism rules, and the restore-point tags. Verified against
`_tools/release.py`, `_tools/deploy.py`, `_tools/release_detect.py`,
`_tools/check_consistency.py`, `_tools/check_versions.py`,
`_tools/generate_repo.py`, `.githooks/pre-push`, and
`.github/workflows/generate_repo.yml`.

---

## One tool, two modes — `release.py` routes for you

`release.py` is the single release entry point. It detects what changed and
dispatches to one of two transactions; you rarely need to tell it which.

### Mode A — the `script.*` / `script.module.*` add-ons (default)

For `script.module.tony7bones`, `script.tony7bones.bootstrap`,
`script.tony7bones.modv2plus`. **The version bump is automatic** — Kodi
auto-upgrades by version number only, so the bump is never skipped, but you no
longer compute or type it.

```bash
python3 _tools/release.py                 # minor-bump every changed add-on, commit on the branch
python3 _tools/release.py --dry-run       # show the plan (incl. WHICH files), change nothing
python3 _tools/release.py --patch         # patch level instead of the minor default
python3 _tools/release.py --major
python3 _tools/release.py --version 1.6.0 --addon script.module.tony7bones
python3 _tools/release.py --news "script.tony7bones.bootstrap=Fix first-boot race"
python3 _tools/release.py --push          # also push the branch (default: commit only)
python3 _tools/release.py check           # the script-side consistency gate only
```

What it does, atomically (rollback to pre-release HEAD on any failure):

1. **Detect** which first-party add-ons changed vs `origin/main` (the shared
   `release_detect.changed_addons` — the SAME detector the pre-push gate uses, so
   the tool and the gate can never disagree). The generated zip + `index.html` are
   excluded; source and `resources/` count.
2. **Compute the next version** (MINOR by default; `--patch`/`--major`/`--version`
   override). Single-digit-per-component with 9.9.9 ceiling, monotonic-increase
   enforced.
3. **Draft + PREPEND the `<news>`** line from the add-on's commit subjects
   (override with `--news`), keeping a rolling cap of ~6 entries. Idempotent — a
   re-run for the same version does not stack a duplicate.
4. **Raise the lockstep `<import>`** atomically: when the shared library bumps,
   every dependent's `<import script.module.tony7bones version=…>` is rewritten to
   the new library version AND that dependent is itself bumped — in the same
   commit. A `--addon script.module.tony7bones`-scoped run auto-includes the
   dependent (it is never orphaned).
5. **Regenerate** deterministically (`generate_repo.py`), assert a second run
   yields no diff.
6. **Run the script-side consistency gate** (well-formed, single-digit, monotonic,
   lockstep `==`) before surfacing success.
7. **Commit on the branch** with a `chore(release): …` subject — then **STOP**
   (the owner keeps the branch → merge → main flow; `--push` is opt-in).

Idempotent: re-running with no new source edit is a no-op ("already released"),
never a double-bump. Refuses when the branch is behind origin, or when a 9.9.9
add-on changed with no version room (readable message → use `--version`).

> **You do NOT hand-edit `addon.xml`, the news, the lockstep import, or any test.**
> The pinned version tests were de-pinned to relational asserts (the library is
> well-formed + single-digit; the bootstrap import `==` the library version), so a
> release never touches a `_tools/test_*.py` file.

### Mode B — the `repository.tony7bones` proxy (`--proxy`)

The **virtual proxy installer**. Its release is fundamentally different: it **IS
the push** (tag + atomic push + Pages force-build + live verify), because the
proxy self-update fetches the new zip live. `release.py --proxy` runs the
**proven `deploy.py` transaction** (it delegates to `deploy.deploy` — the exact,
hardware-proven code that has shipped every proxy release; it is not a
reimplementation). It also auto-routes here when the only changed add-on is the
proxy.

```bash
python3 _tools/release.py --proxy --news "What changed"      # patch bump (proxy default)
python3 _tools/release.py --proxy --minor --news "..."       # or --major / --version X.Y.Z
python3 _tools/release.py --proxy --news "..." --dry-run      # preview, change nothing
python3 _tools/release.py --proxy --news "..." --no-push      # local commit + tag only
```

`deploy.py` remains a fully-working independent entry point — `release.py --proxy`
is a thin front door onto the identical transaction (its whole `test_deploy.py`
suite passes unchanged, and a parity test proves the resulting tree + remote are
identical whichever entry point you use). The npm wrappers still call `deploy.py`:

```bash
npm run deploy -- --news "..."     # → deploy.py (proxy)
npm run deploy:dry   deploy:minor   deploy:major   deploy:local   check   verify
```

The proxy transaction, atomically:

1. Bump `addons/repository.tony7bones/addon.xml` (version + news). This single
   file is **both** the installed-addon metadata **and** the proxy's self-update
   version source (the baked manifest points the `repository.tony7bones` entry's
   `asset_prefix` at `.../main/addons/repository.tony7bones/`), so the one bump
   covers self-update too.
2. Build deterministically; copy the generated zip to the **root** zip; assert
   byte-identity.
3. Prune any stale root installer zips, then rebuild — the **generator** owns the
   root `index.html` (the bare-URL canvas listing), so it produces the install
   link for the new zip filename; there is no separate index-link rewrite.
4. Commit `main`.
5. Determinism gate: regenerate — the tree must stay clean.
6. Tag the `main` release commit (`vX.Y.Z`).
7. Run the version-consistency gate **before** pushing.
8. `git push --atomic origin main refs/tags/<tag>`.
9. Force a GitHub Pages build (`gh api --method POST .../pages/builds`), then
   verify live on Pages.

Pre-flight refuses to run on a dirty tree, off `main`, when behind origin, or
when the new version is not strictly greater than the current. **Any failure
before the push rolls main and the tag back** to their pre-deploy state.

> **Historical — the old manual `script.*` ritual (no longer needed).** Before the
> release automation, a `script.*` release meant: hand-edit `addon.xml` `version=`,
> hand-write `<news>`, hand-raise the lockstep `<import>`, hand-edit the
> version-pinned tests, run `generate_repo.py`, commit, push. `release.py` does all
> of that. The pre-push hook's `check_versions.py` still BLOCKS an un-bumped
> hand-edit as a fail-closed backstop, so the manual path technically still works —
> but there is no reason to use it.

The **four version-bearing locations** (all kept in sync by deploy.py, all
checked by `check_consistency.py`):

| #   | Location                                            | Branch      |
| --- | --------------------------------------------------- | ----------- |
| 1   | `addons/repository.tony7bones/addon.xml` `version=` | main        |
| 2   | root `repository.tony7bones-<ver>.zip` filename     | main        |
| 3   | `index.html` install link (generated)               | main        |
| 4   | git tag `vX.Y.Z`                                    | (annotated) |

> The version lives ONLY in `addon.xml`. `package.json` deliberately does not
> mirror it. There is **no `virtual-repo` branch** and **no separate hosted
> self-update addon.xml** anymore — both retired in the single-branch migration.

## What the proxy fetches from `main`

The proxy serves from its **baked** `addons/repository.tony7bones/resources/repository.json`
(read locally at runtime — see `one-shot-and-architecture.md`). Most entries now
resolve to `main`:

- The first-party add-ons (`repository.tony7bones`, `script.tony7bones.bootstrap`,
  `script.module.tony7bones`, `script.tony7bones.modv2plus`) resolve from
  `.../main/addons/<id>/`.
- The 7 mirrored third-party repos resolve their `addon.xml` (and, for
  `repository.Magnetic` / `.kodinerds` / `.loop` / `.redwizard`, their zip too)
  from `.../main/addons/hosted/<id>/`. `repository.kodifitzwell`, `.umbrella`,
  `.diggz` read their `addon.xml` from `addons/hosted/<id>/` but pull the **zip**
  from the original upstream project.
- `repository.tony7bones` (self-update) reads its `addon.xml` from
  `.../main/addons/repository.tony7bones/` and its zip from the Pages root.
- `repository.709`, `.bugatsinho`, `.cocoscrapers`, `.ivarbrandt`, and `.peno64`
  resolve entirely from their own upstream repos — `repository.peno64`'s URLs
  legitimately contain `/repo/` because that is **peno64's own** repo layout, not
  our `addons/` tree.

## Adding an add-on to what the repo SERVES

1. Add the entry to `addons/repository.tony7bones/resources/repository.json`
   (single canonical copy — there is no second branch). If it is a mirrored
   third-party repo, drop its `addon.xml` (and zip if self-hosted) under
   `addons/hosted/<id>/` and point `asset_prefix` at
   `.../{ref}/addons/hosted/{id}/` with `"branch": "main"`.
2. `python3 _tools/deploy.py --news "add <id>"` so the new manifest ships inside
   the installer zip.

Because the proxy reads the _baked_ manifest, the user's installed repository
add-on must update (i.e. you must release) before they see the new entry.

## GitHub Pages GOTCHA (hit every release) — now baked into deploy.py

Pages frequently **skips the auto-build** on a push, so live-verify would time
out even though the push succeeded. `deploy.py` now **forces a Pages build**
after pushing (`force_pages_build()` → `gh api --method POST .../pages/builds`)
before polling. If you ever need to do it by hand:

```bash
gh api --method POST repos/tony7bones/tony7bones.github.io/pages/builds
# then poll:
curl -sI https://tony7bones.github.io/repository.tony7bones-<ver>.zip   # want HTTP 200
```

Key distinction:

- **Add-on zips and all proxy-fetched content** (including `addons/hosted/**`) are
  served from `raw.githubusercontent.com` (`main`) and are live **instantly** —
  no Pages build involved.
- Only the **repo installer zip** at the site root rides Pages.

## CI — "Validate Kodi Repository"

`.github/workflows/generate_repo.yml`:

- Triggers on **`branches: [main]`** pushes touching the workflow's path filter
  (plus `workflow_dispatch`). **Tag pushes are excluded** — the atomic main+tag
  push re-points the tag at main's HEAD (already validated), and on a detached tag
  checkout the consistency gate can't resolve `main`, so a tag run fails
  spuriously.
  > NOTE: the workflow's `paths:` filter still lists `repo/**` (pre-rename) rather
  > than `addons/**`/`dropbox/**`. It is a code file (out of scope for this doc
  > pass) and should be re-pointed so add-on/canvas pushes still trigger CI.
- It runs the same gate as the hook (pytest, ruff, generator-staleness,
  version consistency on main, **and the per-add-on version-bump gate**
  `check_versions.py` on main — wired into CI so the "every changed add-on
  bumped" guarantee no longer lives only in the pre-push hook) and **NEVER
  commits to main** — it only validates. If generated files are stale the author
  must regenerate and commit. On a `main` push the bump gate uses the push's
  `before` SHA as its baseline (comparing against `origin/main` would judge the
  pushed HEAD against itself).
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

- `perfectly-working-2026-06-06` — the shipped, hardware-proven one-shot state.
- `main-rollback-2026-06-06` — the pre-one-shot `main`, for rolling back a bad release.
- `v2.2.1` — the current `repository.tony7bones` proxy release.

Historical (kept for reference):

- `clean-setup-1.0.17` — a bare, clean baseline.
- `perfectly-working-2026-06-04` — full working build before the one-shot work.

## Current source versions (on `main`)

> Read live from the manifests — never hand-maintained. To regenerate this table:
> `python3 -c "import sys;sys.path.insert(0,'_tools');import release_lib as r;[print(f'{a:30} {r.read_addon_version(open(f\"addons/{a}/addon.xml\").read())}') for a in ('repository.tony7bones','script.module.tony7bones','script.tony7bones.bootstrap','script.tony7bones.modv2plus')]"`

| Add-on                        | Version |
| ----------------------------- | ------- |
| `repository.tony7bones`       | 2.2.1   |
| `script.module.tony7bones`    | 1.5.0   |
| `script.tony7bones.bootstrap` | 1.8.0   |
| `script.tony7bones.modv2plus` | 1.4.8   |

> The one-shot (skin + MOD V2+ patch installed and activated by Setup) is
> **deployed live and proven on a wiped Kodi and a real Fire TV**. The earlier
> milestone established the core flow: `script.module.tony7bones` → 1.1.0 (the
> `install_selection` API), `script.tony7bones.bootstrap` → 1.3.0 (unattended
> video + the skin/patch install step), `script.tony7bones.modv2plus` → 1.4.0
> (the boot auto-apply service; 1.3.5 added the backgrounds-off opt-out flags),
> and the proxy `repository.tony7bones` → 2.2.1. The standalone
> `script.tony7bones.video` add-on was removed.
>
> The most recent work hardened per-device provisioning and first-boot
> reliability:
>
> - **`script.tony7bones.bootstrap` → 1.4.0** — per-device `.env` configuration.
>   Each box carries one gitignored `.env.<device>` that drives its weather / IPTV
>   / RSS / device settings; the provisioner pushes it to the device as
>   `tony7bones.env`, and bootstrap injects it then **reads-then-removes** it so no
>   secrets linger. `.env.device.example` is the committed placeholder template.
> - **`script.tony7bones.modv2plus` → 1.4.7** — first-boot persistence: the boot
>   service now waits for the Home to render before building the menu (shipped
>   ≥ 1.4.4), so the patched MOD V2 home renders on the first paint instead of
>   racing the async skinshortcuts build.
> - **`script.module.tony7bones` → 1.1.3** — the shared library now accepts Kodi's
>   "Keep this skin?" dialog (window 10100) via `SendClick(11)` in `activate_skin`
>   (≥ 1.1.2), so the skin persists without relying on restart timing.
> - **The provisioner workflow** — `_tools/provision-kodi.sh <device>` reads
>   `.env.<device>`, wipes the box, and seeds guisettings (web server, device
>   name, settings level, `addons.unknownsources=true`, `addons.updatemode=1`)
>   **before Kodi starts**. For non-rooted Fire OS 11 Sticks it relocates Kodi
>   data to writable `/sdcard` — see
>   `docs/playbooks/firetv-stick-scoped-storage-provisioning.md`. All five boxes
>   are provisioned.
