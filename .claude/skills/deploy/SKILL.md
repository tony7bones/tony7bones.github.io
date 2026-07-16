---
name: deploy
description: >-
  Deploy / release / publish a Kodi add-on in the Tony.7.Bones repository
  (tony7bones.github.io). Load whenever shipping changes: releasing any add-on
  with release.py, adding or updating an add-on under addons/, editing the
  static catalog (_tools/catalog.json), and making sure the release ACTUALLY
  went live on GitHub Pages so boxes can update. Triggers on: deploy, release,
  publish, ship, "push it live", Pages build, "update failed" on the repo, or a
  newly released add-on not appearing on a Kodi box.
---

# Deploy / publish to the Tony.7.Bones repo

This repo is a **static** Kodi add-on repository served by GitHub Pages. The
installed `repository.tony7bones` add-on (3.0.0) points Kodi at a single static
tree, `https://tony7bones.github.io/static/`, and Kodi reads `addons.xml`, the
`.md5` checksum, and each add-on's zip from there as plain files. There is no
on-box service, no local proxy, and no engine. Two consequences drive this
runbook:

- **The whole served site is built and deployed by CI on every push to `main`**
  (`.github/workflows/pages.yml`: build with `build_site.py`, deploy via
  Pages-from-Actions, verify from the consumer seat with `verify_live_site.py`).
- **A release is not live until that Pages deploy completes.** Push, then confirm
  the deploy went green and the live site serves the new version.

## TL;DR

```bash
# 1. (only if adding/updating an add-on) edit source + _tools/catalog.json, regen, test
python3 _tools/generate_repo.py
python3 -m pytest _tools/ -q && ruff check _tools/
# 2. release the add-on (bump + news + commit on the branch)
python3 _tools/release.py --news "repository.tony7bones=What changed"
# 3. push (opt-in). On push, CI builds + deploys + verifies the static site.
python3 _tools/release.py --push          # or merge the branch to main
# 4. confirm the Pages "Build & Deploy Pages" run went green and the live site
#    serves the new version (see "Confirm it went live" below)
```

## Adding or updating an add-on (before releasing)

1. Put the add-on source under `addons/<id>/` (exclude `__pycache__`, `*.pyc`,
   `.DS_Store`, `.ruff_cache`). **No secret-bearing files**: the build copies only
   git-tracked files and excludes structural secrets, so anything the add-on needs
   at runtime must be a committed, non-ignored file. A public OAuth client_id is
   fine to commit; a client_secret is not (use PKCE).
2. If the repo should **serve** it, add its entry to the static catalog manifest
   `_tools/catalog.json`, mirroring an existing entry. For a mirrored third-party
   repo, also drop its `addon.xml` (and zip if self-hosted) under
   `addons/hosted/<id>/`.
3. `python3 _tools/generate_repo.py` (builds the zip, updates `addons.xml*`).
4. `python3 -m pytest _tools/ -q` and `ruff check _tools/`: both must pass.
5. Release (TL;DR step 2) and push (step 3).

### Manifest pre-flight (or the add-on will be INVISIBLE)

Every served add-on's `addon.xml` MUST declare
`<import addon="xbmc.python" version="3.0.0"/>` in `<requires>`. **Kodi 19+/Omega
silently hides any add-on that does not**: no error, no log, and no amount of
refreshing, restarting, or re-releasing will surface it. Lint before shipping:

```sh
grep -L 'addon="xbmc.python"' addons/*/addon.xml   # must print NOTHING
```

If something you released never appears under ANY category on the box, this is
almost always the cause (it cost ~2 hours once:
`docs/incident-2026-06-30-ezmpp-deploy.md`). The general rule that catches it fast:
when a deployed thing is not visible, **reproduce the served `addons.xml` from live
data before blaming Kodi's cache.** Theories are not evidence.

## Confirm it went live

After the push, the "Build & Deploy Pages" workflow builds, deploys, and runs a
consumer-seat verify job. Confirm it and spot-check the live site:

```bash
# the workflow run status
gh run list --workflow "Build & Deploy Pages" -L 3

# the live catalog + the new zip (want HTTP 200)
curl -sI https://tony7bones.github.io/static/addons.xml
curl -sI https://tony7bones.github.io/static/repository.tony7bones/repository.tony7bones-<ver>.zip
curl -sI https://tony7bones.github.io/repository.tony7bones-<ver>.zip   # the root installer

# or run the same verifier CI uses
python3 _tools/verify_live_site.py --manifest _tools/catalog.json
```

If the deploy job did not run, check the push touched the `pages.yml` path filter
(`addons/**`, `dropbox/**`, `_tools/**`, `index.html`, `style.css`,
`.github/workflows/**`). A docs-only or `.claude/**`-only push does not trigger it.

## Troubleshooting

| Symptom                                                      | Cause                                                                                                                                                                                                        | Fix                                                                                                                   |
| ------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | --------------------------------------------------------------------------------------------------------------------- |
| Release "succeeded" but the box does not see the new version | The Pages deploy has not completed, or the push missed the `pages.yml` path filter, so the live `/static/` tree is still the old build.                                                                      | Check the "Build & Deploy Pages" run; re-run it (`workflow_dispatch`) if it did not fire; then re-check the box.      |
| New add-on is not listed under Install from repository       | Kodi cached the OLD add-on list. The catalog is fetched only when Kodi decides to refresh.                                                                                                                   | On the box: **Check for updates** (Add-ons context menu), or restart Kodi.                                            |
| Add-on is in `_tools/catalog.json` but not served            | A build-time fallback kept the last-good entry, or the entry failed materialization (bad zip/metadata).                                                                                                      | Read the build log for the per-entry warning; fix the source/catalog entry and rebuild.                               |
| `git status` shows commits "to push" but the deploy worked   | You are looking at a **source-of-truth** repo (`moquette/estuary7` or `moquette/ezmaintenanceplusplus`), not this one. They are independent repos this repo only mirrors metadata for + points a zip URL AT. | Confirm with `git -C <repo> ls-remote origin main` vs local HEAD; a deploy here never touches those repos' git state. |
| A released **icon** change does not show on the box          | Kodi caches add-on ICONS (texture cache): same path, old render kept in `userdata/Thumbnails/` + `Textures13.db`.                                                                                            | Clear the thumbnail cache (EZ Maintenance++ -> Delete Thumbnails, or wipe `Textures13.db`) and restart; or reinstall. |

## Why a released update lags on the box (caches)

The static tree is live the instant Pages finishes deploying, but Kodi decides
WHEN to re-read it. Kodi caches the repository add-on list and only refreshes on
its own schedule or on an explicit **Check for updates**. To force it now: open
the repository add-on, context menu -> **Check for updates**, or fully force-quit
Kodi and reopen. Neither a lagging list nor a cached icon means the release
failed; confirm the live site first (above).

## The daily third-party refresh

`pages.yml` also runs on a daily cron (and on `repository_dispatch` when a sibling
repo publishes a release) with `--refresh-third-party`, so mutable upstream
metadata and release-asset versions stay fresh (Kodi-side staleness bound: <=24h
for third-party listings, minutes for owned content because those are
push-triggered).
