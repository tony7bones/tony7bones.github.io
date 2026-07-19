# Playbook - Release & deploy

**One command releases every add-on: `python3 _tools/release.py`.** The repo is a
STATIC Kodi repository served by GitHub Pages; there is no proxy engine and no
separate proxy release path anymore. `release.py` auto-detects which add-ons
changed, computes the next version, drafts + prepends the news, regenerates
deterministically, gates, and commits on the branch - no hand-editing of
`addon.xml`, no manual `<news>`, no pinned-test edits. On push, CI builds and
deploys the static site.

Verified against `_tools/release.py`, `_tools/release_lib.py`,
`_tools/release_detect.py`, `_tools/check_versions.py`, `_tools/generate_repo.py`,
`_tools/build_site.py`, `_tools/static_catalog.py`, `_tools/verify_live_site.py`,
`.githooks/pre-push`, `.github/workflows/generate_repo.yml`, and
`.github/workflows/pages.yml`.

---

## Releasing an add-on - `release.py`

`release.py` is the single release entry point for EVERY add-on, including the
static repository add-on `repository.tony7bones` (it is a normal static-only
add-on now, released the same way as any other).

```bash
python3 _tools/release.py                 # minor-bump every changed add-on, commit on the branch
python3 _tools/release.py --dry-run       # show the plan (incl. WHICH files), change nothing
python3 _tools/release.py --patch         # patch level instead of the minor default
python3 _tools/release.py --major
python3 _tools/release.py --version 3.1.0 --addon repository.tony7bones
python3 _tools/release.py --news "repository.tony7bones=Add a new hosted add-on"
python3 _tools/release.py --push          # also push the branch (default: commit only)
python3 _tools/release.py check           # the script-side consistency gate only
```

What it does, atomically (rollback to pre-release HEAD on any failure):

1. **Detect** which add-ons changed vs `origin/main` (the shared
   `release_detect.changed_addons` - the SAME detector the pre-push gate uses, so
   the tool and the gate can never disagree). The generated zip + `index.html` are
   excluded; source and `resources/` count.
2. **Compute the next version** (MINOR by default; `--patch`/`--major`/`--version`
   override). Single-digit-per-component with a 9.9.9 ceiling, monotonic increase
   enforced. An add-on already on a legacy date-stamped scheme (EZ Maintenance++'s
   real `2026.07.x` lineage) is compared and bumped WITHIN that scheme (loose,
   Kodi-comparable), never forced onto single-digit `X.Y.Z`.
3. **Draft + PREPEND the `<news>`** line from the add-on's commit subjects
   (override with `--news`), keeping a rolling cap of ~6 entries. Idempotent: a
   re-run for the same version does not stack a duplicate.
4. **Regenerate** deterministically (`generate_repo.py`), asserting a second run
   yields no diff.
5. **Run the script-side consistency gate** (well-formed, single-digit, monotonic)
   before surfacing success.
6. **Commit on the branch** with a `chore(release): ...` subject - then **STOP**
   (the owner keeps the branch -> merge -> main flow; `--push` is opt-in).

Idempotent: re-running with no new source edit is a no-op ("already released"),
never a double-bump. Refuses when the branch is behind origin, or when a 9.9.9
add-on changed with no version room (readable message -> use `--version`).
Add-ons are **independent**: there is no shared library and no "lockstep", so a
change to one never forces a bump of another.

> **You do NOT hand-edit `addon.xml`, the news, or any test.** The version tests
> are relational (well-formed + single-digit / monotonic), so a release never
> touches a `_tools/test_*.py` file. The pre-push hook's `check_versions.py` still
> BLOCKS an un-bumped hand-edit as a fail-closed backstop.

## What each add-on is

- `repository.tony7bones` (static-only, 3.0.0) - built from
  `addons/repository.tony7bones/` and released like any add-on.
- `skin.estuary7` and `script.ezmaintenanceplusplus` - OUR add-ons whose source
  lives in sibling repos (`~/Code/moquette/estuary7`,
  `~/Code/moquette/ezmaintenanceplusplus`). This repo carries only a hosted
  metadata mirror (`addons/hosted/<id>/` + a `_tools/catalog.json` entry pointing
  at the sibling repo's GitHub Release asset). Fix bugs and bump the real version
  in the sibling repo; only bump the hosted metadata + re-release here.

## Adding or changing what the repo SERVES

The static catalog manifest is **`_tools/catalog.json`** (a list of entries;
`static_catalog.py` classifies each: first-party build / hosted mirror / hybrid /
streamed / release-asset). To add or change a served add-on:

1. Add/edit its entry in `_tools/catalog.json`. For a mirrored third-party repo,
   also drop its `addon.xml` (and zip if self-hosted) under `addons/hosted/<id>/`.
2. Release (or, for a canvas-only asset, publish - see below). CI rebuilds the
   `/static/` catalog and deploys.

## How the static site is built and served

The served site lives committed on `main` and is served by GitHub Pages:

- The repo ROOT is the 1:1 mirror of `dropbox/` (the bare-URL canvas:
  `repositories/ media/ iptv/ rss/` + a generated Kodi index per folder + the
  root installer zip), regenerated by `generate_repo.py`.
- `/static/` is the Kodi repository the add-on points at (`addons.xml` +
  `addons.xml.md5` + per-add-on zips + materialized art). It is built by
  `build_site.py` -> `static_catalog.py` from `_tools/catalog.json`.

CI (`.github/workflows/pages.yml`) builds the ENTIRE site (canvas + `/static/`
catalog) on every push (path-filtered) plus a daily cron and manual dispatch,
then deploys to Pages and runs the consumer-seat verify. Fault policy in the
build: per-entry last-good fallback, a catalog shrink guard, a file-size gate,
and a never-empty guarantee, so a bad build cannot publish garbage - a red CI
never deploys and the site keeps serving the last known-good state. The Pages
source is GitHub Actions; main is sources-only (the served canvas mirror, root
index, robots.txt, /static/ catalog, and root installer are all generated into
the artifact by `build_site.py`, never committed). Historical phasing:
fleet meta-repo `docs/static-repo-and-tailscale.md`.

**Consumer-seat verify** (`_tools/verify_live_site.py`, run by the CI verify job):
fetches `/static/addons.xml` + `.md5` and the changed zip URLs through the exact
public URLs Kodi uses, asserts the md5 matches the bytes, and fails loud on any
mismatch. Run it by hand against the live site anytime.

## Canvas-only changes (no add-on release)

For `dropbox/` edits (a new third-party installer zip, a media image, an RSS
change) with no add-on version bump:

```bash
python3 _tools/publish_canvas.py -m "Add foo repo zip to canvas"   # npm run publish
python3 _tools/publish_canvas.py -m "..." --dry-run                # npm run publish:dry
```

It commits the canvas edit and pushes `main`; the CI deploy regenerates the
served mirror. It refuses to publish credential-like content to the public site
unless `--allow-secrets`.

## KodiShare backup mirror (automatic, best-effort)

The Mac mini share holds backup-install copies that MUST track releases:

- `/Volumes/KodiShare/repositories/` - the current
  `repository.tony7bones-<version>.zip` root installer plus the hand-authored
  third-party installer zips from `dropbox/repositories/`.
- `/Volumes/KodiShare/apps/` - sideloadable add-on zips, **opt-in-by-presence**:
  the owner curates WHICH add-ons belong by having any version of one in the dir;
  the sync refreshes those to the current release and prunes superseded versions,
  and never adds add-ons on its own. This matters most for EZ Maintenance++ - it
  is the RESTORE tool a wiped box sideloads from this share, so a stale copy
  resurrects exactly the backup/restore bugs later releases fixed.
- `/Volumes/KodiShare/{media,rss}/` - mirrored 1:1 from the canvas
  (`dropbox/media`, `dropbox/rss`), **strictly additive**: unversioned filenames
  are overwritten on change but NOTHING is ever deleted, and a missing share
  subdir is skipped, never created. NOT `iptv/`: the mini's populator daemon owns
  the share's iptv output; the sync stays away from it.

Two triggers cover every publish path:

- `publish_canvas.py` after a canvas publish;
- **`.githooks/pre-push` (main only)** - covers add-on releases, which publish
  via plain `git push`.

The contract lives in `_tools/sync_share.py` (pinned by `test_sync_share.py`):

- **Only when the volume is mounted.** If a share dir does not exist the sync
  prints a skip note and does nothing - it never creates the dir, never attempts a
  mount, and NEVER fails (or blocks) a release or push.
- **Additive.** Foreign zips on the share are never touched; the only deletions
  are superseded versions of zips we own, and an app's stale copy is only pruned
  AFTER its fresh copy landed.
- **Sandbox-safe by construction.** `sync_share.py` must NEVER join the
  system-test copy whitelists (a test enforces this), so a sandboxed run cannot
  write test artifacts to the real share.

Run it by hand anytime: `python3 _tools/sync_share.py [--dry-run]`.

## Never hand-create a release (2026-07-19 incident)

`ci.yml` gates publishing on the test job (`publish: needs: [test, anchored-build-check]`)
and that gate WORKS - on a red run, `publish` is skipped. It was not bypassed by
a workflow defect. It was bypassed by a human-equivalent running:

```bash
gh release create ...     # DO NOT DO THIS
```

which publishes an asset with no CI involvement at all. That is how skin.estuary7
v1.0.67 shipped against a failing test suite. The agent that did it then reported
its own bypass as a workflow defect, and that false report reached the owner.

**Rules:**

- Releases are published BY CI. If you find yourself typing `gh release create`,
  stop - you are about to defeat the gate, not use it.
- A red CI run is a hard stop on deployment even when the release asset already
  exists and even when local tests pass. Local green is not the gate; the CI run
  on the pushed commit is.
- Before reporting a pipeline defect, READ THE WORKFLOW. This one was four lines
  and would have taken thirty seconds to check.

**The guard that now catches it:** `tools/verify_release.py` +
`.github/workflows/release-guard.yml` in `estuary7`. It fails a release whose tag
commit has no successful CI run, and independently checks the published asset
byte-matches a deterministic rebuild of that commit. Demonstrated firing: run
29690268676 FAILED on the hand-made v1.0.67, run 29690248062 passed on the
CI-published v1.0.70.

**Both legs are needed.** v1.0.67's asset hash DID match its recorded sha, so an
integrity-only check would have passed the very release being policed. Only the
provenance leg catches it.

**Do not trust `skin_build.lock`'s `zip_sha256` as an integrity oracle** - it
records the last LOCAL build, not the published asset. It was stale by two
versions at v1.0.61. The deterministic rebuild is authoritative.

**Detection is not prevention.** The guard makes a hand-made release loudly red
AFTER the fact. Actual prevention is a repo setting only the owner can apply:
GitHub, Settings, Rules, Rulesets, new tag ruleset, pattern `v*`, restricted to
the `github-actions` bot.

## Skins install from the repository, never by hand

Owner rule, 2026-07-19. A skin reaches a box through Kodi's own add-on update
from the Tony.7.Bones repository. No `adb push` of skin files, no
`devicectl copy`, no unzipping a build onto a box.

If a box does not offer the update, that is a DEFECT TO REPORT, not something to
route around with a manual copy. Two reasons it matters:

- Hand-pushing means "installed" and "installed the way a user installs" keep
  diverging. A version bump twice carried the wrong bytes because of it.
- On tvOS, `devicectl copy to` silently refuses to overwrite existing files while
  reporting success, so a hand-push can leave a box running old code while every
  report says it upgraded.

Verify an install came through the repo by reading Kodi's log on the box, not by
assuming. And note Kodi caches its repository index: a box with
`addons.updatemode=1` (notify, do not auto-install) will not see a new version
until its next scheduled check or until the owner triggers Settings, Add-ons,
Check for updates. Do not force it and do not change that setting.

## CI - validation

`.github/workflows/generate_repo.yml` (the push-validation workflow):

- Triggers on `main` pushes touching its path filter (plus `workflow_dispatch`).
- Runs the same gate as the pre-push hook (pytest, ruff, generator-staleness, and
  the per-add-on version-bump gate `check_versions.py` on main) and **NEVER commits
  to main** - it only validates. If generated files are stale the author must
  regenerate and commit.
- `docs/**` and `.claude/**` are NOT in the path filter, so doc/skill-only commits
  trigger no CI run.

`.github/workflows/pages.yml` is the build/deploy/verify pipeline (above).

## Determinism

`generate_repo.py` builds zips **reproducibly** and **excludes `__pycache__`**
(pyc files left by test imports made zips non-reproducible -> CI staleness
failures). When committing, a freshly built zip may differ only by mtime on the
first build. Settle it:

```bash
git commit ...
python3 _tools/generate_repo.py
git commit --amend --no-edit          # absorb the settled zip
python3 _tools/generate_repo.py       # confirm: a second run yields NO diff
```

## Restore-point tags

Create a tag for any known-good state before risky work. The current static-only
state ships `repository.tony7bones` 3.0.0. Pre-static / pre-modular tags
(`main-pre-modular-2026-06-10`, `perfectly-working-2026-06-06`,
`main-rollback-2026-06-06`, `clean-setup-1.0.17`) predate the static conversion
and the retired proxy/setup add-on family - use them to inspect history, not as a
rollback target for the current static repo.

## Current source versions (on `main`)

> Read live from the manifests - never hand-maintained. To list them:
> `for d in addons/*/; do [ -f "$d/addon.xml" ] && grep -o 'id="[^"]*" name' "$d/addon.xml" >/dev/null && python3 -c "import sys;sys.path.insert(0,'_tools');import release_lib as r;print('$d', r.read_addon_version(open('$d/addon.xml').read()))"; done`

| Add-on                         | Where its source lives                            |
| ------------------------------ | ------------------------------------------------- |
| `repository.tony7bones`        | `addons/repository.tony7bones/` (this repo)       |
| `skin.estuary7`                | `~/Code/moquette/estuary7` (sibling repo)         |
| `script.ezmaintenanceplusplus` | `~/Code/moquette/ezmaintenanceplusplus` (sibling) |
