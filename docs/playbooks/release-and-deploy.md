# Playbook - Release & deploy

**The only add-on released from this repo is `repository.tony7bones`, and its
release is a hand edit of `addon.xml` plus a regenerate, gated by
`check_versions.py`.** The repo is a STATIC Kodi repository served by GitHub
Pages; there is no proxy engine, no separate proxy release path, and since
2026-09-26 no automatic release tool either (`release.py` was deleted that
day; see the dated note below). On push, CI builds and deploys the static
site.

Verified against `_tools/release_lib.py`, `_tools/release_detect.py`,
`_tools/check_versions.py`, `_tools/generate_repo.py`, `_tools/build_site.py`,
`_tools/static_catalog.py`, `_tools/verify_live_site.py`, `.githooks/pre-push`
and `.github/workflows/pages.yml`. Brought current 2026-09-26, the day the hub
stopped carrying any copy of the owner's add-ons and the day the release tool
and the duplicate validation workflow left; the dated history below is kept
for the WHY.

---

## Releasing `repository.tony7bones`

Four steps, all by hand:

1. Edit `addons/repository.tony7bones/addon.xml`: raise the `version`
   attribute (single digits per component, monotonic; Kodi compares versions
   numerically) and prepend a `<news>` line describing the change.
2. `python3 _tools/generate_repo.py`: rebuilds the zip at the new version,
   prunes the superseded zip, rewrites `addons/addons.xml` and its `.md5` and
   `.sha256`, and the per-add-on `index.html`. Run it twice if a zip churns
   (see Determinism below).
3. Commit the source edit and the generated output TOGETHER. The pre-push
   hook and CI both fail on stale generated files.
4. `git push origin main`. CI builds the site, places the fresh
   `repository.tony7bones-<version>.zip` at the root and under
   `repositories/`, deploys, and verifies live.

**Every release MUST bump the version.** Kodi auto-upgrades by version number
only, so a same-version byte change silently breaks upgrades. The rule is
ENFORCED, not remembered: `check_versions.py` compares each `addons/<id>/`
tree against a baseline (`origin/main` in the pre-push hook; the push's
`github.event.before` SHA in CI, so a main push is judged across the pushed
range and not against itself) and blocks the push if the add-on's source
changed without its `addon.xml` version increasing. The generated zip and
`index.html` are excluded from "changed"; source and `resources/` count. A
revert lowers the version and the gate rightly blocks it: roll FORWARD with a
new bump.

The pieces the gate is built from: `_tools/release_lib.py` (version parsing
and comparison, including the loose date-stamped scheme EZM++ once used),
`_tools/release_detect.py` (the ONE `changed_addons` detector, so no second
definition of "changed" can drift from the gate) and
`_tools/check_versions.py`, pinned by `test_release_detect.py` and
`test_check_versions.py`.

> **Dated note, 2026-09-26: `release.py` deleted.** From the hub's first
> commit (`c01f6fc`, 2026-07-16) to 2026-09-26 `python3 _tools/release.py`
> did steps 1 to 3 automatically
> (detect what changed vs `origin/main`, compute a minor bump, draft the
> `<news>` from commit subjects, regenerate, run a consistency gate, commit
> `chore(release): ...`). A read-only survey that day measured that the only
> add-on it could act on had last been bumped 2026-07-16, that no workflow,
> hook or `bin/check-all` ran it, and that its sandbox tests were 29.5s of the
> suite's 40s. Its two git helpers moved into `publish_canvas.py`, the tool
> and `test_release.py` were deleted, and the suite fell from 264 tests in
> 39.5s to 209 in 9s (measured). Nothing the gate relies on left.

## What each add-on is

- `repository.tony7bones` (static-only, 3.0.0) - built from
  `addons/repository.tony7bones/` and released like any add-on.
- `script.ezmaintenanceplusplus`, `skin.estuary.plusplus` (Estuary++) and
  `service.tvos.pythonfix` - OUR add-ons whose source lives in sibling repos
  (`~/Code/kodi/ezmpp` = `moquette/kodi-ezmpp`;
  `~/Code/kodi/estuary-plusplus` = `moquette/kodi-estuary-plusplus`; both
  public). `skin.estuary.pov` is the skin's OLD id, served from the same repo
  only while the boxes migrate to the new one (since 2026-09-26) and retired
  in stage E of the rename plan. This repo carries NO copy of them, not even `addon.xml`: their
  `_tools/catalog.json` entries are `release-asset` templates and
  `static_catalog.py` resolves the latest release at build time
  (`releases/latest` for ezmpp's `v<version>` tags; the newest in the
  `<id>-v<version>` namespace for the estuary-plusplus add-ons, because several add-ons
  share that repo and a repo has one `releases/latest`), then takes `addon.xml`
  and art out of the zip. Fix bugs and bump the version in the sibling repo; a
  bump pushed to its `main` is the release (its CI publishes and dispatches this
  hub). Nothing is bumped or released here for them.
- `plugin.video.pov` - NOT ours; a `hybrid` entry with `upstream_index`. The
  build reads upstream's `packages/addons.xml` for the version and republishes
  the upstream zip. Served only because the skin hard-imports it.
- the eleven official-library modules (`plugin.program.autocompletion`,
  `script.image.resource.select`, `script.module.autocompletion`, `certifi`,
  `chardet`, `idna`, `requests`, `simplecache`, `simpleeval`, `unidecode`,
  `urllib3`) - NOT ours; `hybrid` entries with `upstream_index` on the official
  Kodi repository's Piers index (`mirrors.kodi.tv/addons/piers/addons.xml.gz`,
  since the afternoon of 2026-09-26). Their committed zips left the same day.
  Served because Kodi resolves a hard dependency only from the repository the
  add-on is installed FROM, and the build walks the whole closure through them.

  History, dated: until 2026-09-26 this repo carried a hand-maintained
  metadata mirror under `addons/hosted/<id>/` for each of these, and a release
  reached no box until someone bumped it. `skin.estuary7` 1.0.71 went
  unreachable for 15 hours that way (2026-07-19); EZM++ 2026.09.17.1 sat
  unmirrored for nine days with a freshness gate red; POV's hand-typed version
  rotted and dropped it from the build. A bot-sync workflow lived for a few
  hours on 2026-09-26 and was retired the same afternoon for build-time
  resolution. Owner's rule: THERE MUST BE NO MIRROR VERSION TO BE WRONG. Do not
  reinstate a committed copy or a gate that compares one. (`skin.estuary7`
  itself was decommissioned 2026-08-31.)

## Adding or changing what the repo SERVES

The static catalog manifest is **`_tools/catalog.json`** (a list of entries;
`static_catalog.py` classifies each: first-party build / hosted mirror / hybrid /
streamed / release-asset). To add or change a served add-on:

1. Add/edit its entry in `_tools/catalog.json`. For a mirrored third-party
   repository INSTALLER, also drop its `addon.xml` (and zip if self-hosted) under
   `addons/hosted/<id>/`; nothing else lives there. A `release-asset` entry or a
   `hybrid` entry with `upstream_index` (ours, POV, every official-library
   module) gets NO hosted directory (`static_catalog.metadata_resolved_at_build`);
   the build resolves it and walks its `<import>`s, and `test_closure.py` pins
   that no `addon.xml` is committed for it.
2. Commit and push (or, for a canvas-only asset, publish - see below). CI
   rebuilds the `/static/` catalog and deploys. No version bump is needed
   here unless `addons/repository.tony7bones/` itself changed.

## How the static site is built and served

`main` is sources-only; the served site is built into the Pages artifact by
CI and never committed:

- The artifact ROOT is the 1:1 mirror of `dropbox/` (the bare-URL canvas:
  `repositories/ rss/` + a generated Kodi index per folder + the root installer
  zip; `media/` and `iptv/` retired 2026-07-16), generated by `build_site.py`.
- `/static/` is the Kodi repository the add-on points at (`addons.xml` +
  `addons.xml.md5` + per-add-on zips + materialized art). It is built by
  `build_site.py` -> `static_catalog.py` from `_tools/catalog.json`.

CI (`.github/workflows/pages.yml`) builds the ENTIRE site (canvas + `/static/`
catalog) on every push to `main` (no path filter), on a daily cron, on manual
dispatch, and on the `repository_dispatch` type `ezmpp-release` that ezmpp CI
and estuary-plusplus CI send when they publish a release (the name is historical),
then deploys to Pages and runs the consumer-seat verify. Every one of those
runs re-resolves the release-asset and `upstream_index` entries, so a sibling
release needs no commit here. If a push run's verify fails, the verify job
re-dispatches the deploy once (a Pages branch-build race clobbered a deploy on
2026-09-26). Fault policy in the
build: per-entry last-good fallback, a catalog shrink guard, a file-size gate,
and a never-empty guarantee, so a bad build cannot publish garbage - a red CI
never deploys and the site keeps serving the last known-good state. The Pages
source is GitHub Actions; main is sources-only (the served canvas mirror, root
index, robots.txt, /static/ catalog, and root installer are all generated into
the artifact by `build_site.py`, never committed). `pages_source_guard.yml`
keeps that Pages setting on "workflow" (it was found on "legacy" 2026-09-26)
using the `T7B_PAGES_ADMIN_TOKEN` secret, and `ci_failure_alert.yml` opens an
issue assigned to the owner when a deploy-path run fails and closes it on the
next green run. All workflows run on `ubuntu-26.04`.

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

## Kodi share backup mirror (automatic, best-effort)

The Mac mini share holds ONE backup-install directory that must track
releases: `/Volumes/Kodi/Share/repositories/`, the current
`repository.tony7bones-<version>.zip` root installer plus the hand-authored
third-party installer zips from `dropbox/repositories/`.

Until 2026-09-26 `sync_share.py` also refreshed `/Volumes/Kodi/Share/apps/`
(sideload copies of first-party zips, opt-in by presence) and mirrored the
canvas `media/` and `rss/` to same-named share dirs. Measured that day, the
share holds `iptv/`, `repositories/` and `userdata/` only: none of those
target directories exists, so both syncs were unreachable code and were
deleted with their tests. (`iptv/` was never in scope: the mini's populator
daemon owns it.)

Two triggers cover every publish path:

- `publish_canvas.py` after a canvas publish;
- **`.githooks/pre-push` (main only)** - covers installer releases, which
  publish via plain `git push`.

The contract lives in `_tools/sync_share.py` (pinned by `test_sync_share.py`):

- **Only when the volume is mounted.** If the share dir does not exist the sync
  prints a skip note and does nothing - it never creates the dir, never attempts a
  mount, and NEVER fails (or blocks) a push.
- **Additive.** Foreign zips on the share are never touched; the only deletions
  are superseded versions of our own installer.
- **Sandbox-safe by construction.** `sync_share.py` must NEVER join the
  system-test copy whitelists (a test enforces this), so a sandboxed run cannot
  write test artifacts to the real share.

Run it by hand anytime: `python3 _tools/sync_share.py [--dry-run]`.

## Never hand-create a release (2026-07-19 incident)

Dated record, 2026-07-19, on the since-decommissioned `estuary7` repo; the
lesson stands for ezmpp and estuary-plusplus, whose CI publishes on a version bump.

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

**The guard that caught it then:** `tools/verify_release.py` +
`.github/workflows/release-guard.yml` in `estuary7` (archived 2026-08-31). It fails a release whose tag
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
until its next scheduled check or until someone triggers Settings, Add-ons,
Check for updates. **Never change `addons.updatemode`.** Triggering the check
itself is fine and is the sanctioned remedy
(`.claude/skills/deploy/SKILL.md:112`).

CORRECTED 2026-07-21. This paragraph read "Do not force it and do not change
that setting", which banned both the setting and the check, contradicted the
deploy skill that preflight routes you to, and stalled a release for an hour.
Only the setting is off limits.

Update mode is also the wrong first suspect for a box that will not update.
MEASURED 2026-07-21: ts1 and atv2 were BOTH at `addons.updatemode=1` and ts1
installed a repository update anyway. What actually blocked atv2 was a blank
`installed.origin` in `Addons33.db`, which makes Kodi treat the add-on as
hand-installed and offer no Update button at all, with `addons://outdated/`
empty while the repo index correctly advertised the new version
(`docs/playbooks/kodi-install-mechanics.md:33`). Installing once from the
repository restamps the origin and returns the box to the normal channel. Check
the origin column before blaming update mode.

## CI - one push workflow

`.github/workflows/pages.yml` ("Build & Deploy Pages") is the ONLY workflow a
push triggers, and it NEVER commits to `main`:

- On a **push** it runs the source gates first (pytest, ruff, generator
  staleness, and the per-add-on version-bump gate `check_versions.py` against
  `github.event.before`, skipped cleanly on a first push or an unresolvable
  baseline), then the artifact gates (build, secret gate, determinism double
  build), deploy, and the consumer-seat verify.
- On the **daily cron** and on **`repository_dispatch`** no hub source
  changed, so the test, lint and version-bump steps are skipped
  (`if: github.event_name == 'push'`, pinned by `test_pages_workflow.py`) and
  the run goes straight to the artifact gates, deploy and verify.
- It has NO path filter: doc-only and skill-only commits build and deploy too.

`.github/workflows/generate_repo.yml` ("Validate Kodi Repository") was
deleted 2026-09-26. It re-ran the same four source gates step for step on the
same push, and its only extra trigger was a `modular-setup` branch that does
not exist on the remote (`git ls-remote` shows `main` only). The failure alert
workflow's list and the workflow pins were updated with it.

`.github/workflows/ci_failure_alert.yml` and
`.github/workflows/pages_source_guard.yml` are the operational backstops
(above). None of the three commits to `main`.

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

| Add-on                         | Where its source lives                                        | Served version comes from                                  |
| ------------------------------ | ------------------------------------------------------------- | ---------------------------------------------------------- |
| `repository.tony7bones`        | `addons/repository.tony7bones/` (this repo)                   | the committed `addon.xml`                                  |
| `script.ezmaintenanceplusplus` | `~/Code/moquette/kodi/ezmpp` (`moquette/kodi-ezmpp`)          | latest GitHub release `v<version>`, resolved at build time |
| `skin.estuary.plusplus`        | `~/Code/kodi/estuary-plusplus` (`moquette/kodi-estuary-plusplus`) | newest release `skin.estuary.plusplus-v<version>`      |
| `skin.estuary.pov`             | same repo, old id; served only during the migration, retired in stage E | newest release `skin.estuary.pov-v<version>`      |
| `service.tvos.pythonfix`       | same repo as the skin                                         | newest release `service.tvos.pythonfix-v<version>`         |
| `plugin.video.pov`             | upstream (not ours)                                           | upstream's `packages/addons.xml`                           |
