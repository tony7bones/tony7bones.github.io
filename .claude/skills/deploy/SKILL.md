---
name: deploy
description: >-
  Deploy / release / publish a Kodi add-on in the Tony.7.Bones repository
  (tony7bones.github.io). Load whenever shipping changes to a box: releasing the
  repository.tony7bones proxy (release.py --proxy) or any script.* add-on, adding
  or updating an add-on under addons/, wiring repository.json, and (critically)
  making sure the release ACTUALLY went live on GitHub Pages so boxes can update.
  Triggers on: deploy, release, publish, ship, "push it live", proxy bump, Pages
  build, "update failed" on the repo, or a newly released add-on not appearing on
  a Kodi box.
---

# Deploy / publish to the Tony.7.Bones repo

This repo is a **virtual proxy**. A running box's `repository.tony7bones` add-on
reads a baked `resources/repository.json`, then serves Kodi a generated
`addons.xml` and proxies each add-on's zip from upstream. Two consequences drive
this whole runbook:

- **Every normal add-on is fetched from `raw.githubusercontent` (instant).**
- **The proxy add-on UNIQUELY self-updates from GitHub _Pages_**
  (`repository.json`: `repository.tony7bones` zip = `tony7bones.github.io/...`).
  So a proxy release is not live until **Pages publishes** the new root zip, and
  Pages is the flaky part.

## TL;DR

```bash
# 1. (only if adding/updating an add-on - see below) copy source, wire repository.json, regen, test
# 2. release the proxy (atomic push + tag; --news is required)
python3 _tools/release.py --proxy --news "What changed"
# 3. ALWAYS run the publish gate. release.py CANNOT force the Pages build and does
#    NOT re-trigger when the auto-build silently skips. This does both.
.claude/skills/deploy/publish-gate.sh
# 4. follow the box-side steps it prints (Check for updates TWICE / restart)
```

If you only ran `_tools/release.py --proxy` and stopped, **you are not done**:
the box cannot update until Pages serves the zip (step 3).

## Adding or updating an add-on (before releasing)

1. Copy the add-on source into `addons/<id>/` (exclude `__pycache__`, `*.pyc`,
   `.DS_Store`, `.ruff_cache`). **No secret-bearing files**: `generate_repo.py`
   drops git-ignored files from the zip, so anything the add-on needs at runtime
   must be a committed, non-ignored file. A public OAuth client_id is fine to
   commit; a client_secret is not (use PKCE).
2. If the proxy should **serve** it, add a 5-field entry to
   `addons/repository.tony7bones/resources/repository.json` mirroring an existing
   first-party entry (`id`, `username`, `repository`, `branch`, `asset_prefix`,
   `assets.zip`). No `platforms` key unless you intend to platform-restrict it.
3. `python3 _tools/generate_repo.py` (builds the zip, updates `addons.xml*`).
4. `python3 -m pytest _tools/ -q` and `ruff check _tools/`: both must pass.
5. Release (TL;DR step 2) then the publish gate (step 3).

### Manifest pre-flight (or the add-on will be INVISIBLE)

Every served add-on's `addon.xml` MUST declare
`<import addon="xbmc.python" version="3.0.0"/>` in `<requires>`. **Kodi 19+/Omega silently
hides any add-on that does not** - no error, no log, and no amount of refreshing, restarting,
or re-releasing will ever surface it. Lint before shipping:

```sh
grep -L 'addon="xbmc.python"' addons/*/addon.xml   # must print NOTHING
```

If something you released never appears under ANY category on the box, this is almost always
the cause (it cost ~2 hours once: `docs/incident-2026-06-30-ezmpp-deploy.md`). And the
general rule that would have caught it fast: when a deployed thing is not visible,
**reproduce the proxy's served `addons.xml` from live data before blaming Kodi's cache.**
Theories are not evidence.

## The publish gate (the thing that was missing)

`.claude/skills/deploy/publish-gate.sh [version]` (version auto-detected):

- Polls `https://tony7bones.github.io/repository.tony7bones-<ver>.zip`.
- If Pages did not publish, **re-triggers the build with an empty-commit push**
  (the only trigger available without a `pages: write` token) and re-polls, up to
  3 rounds.
- Verifies the live chain (Pages zip, raw zip, served-add-on count).
- Prints the exact Kodi box steps.

Run it after **every** proxy release. It is idempotent: if Pages is already live
it just confirms the chain and prints the box steps.

## Troubleshooting (every failure we actually hit)

| Symptom                                                                                                    | Cause                                                                                                                                                                      | Fix                                                                                                                                 |
| ---------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------- |
| Release "succeeded" but the box's repo shows a **retry loop** / "Update failed"                            | Pages never published the proxy zip (`tony7bones.github.io/repository.tony7bones-<ver>.zip` is 404). `release.py`'s force-build got a 403 and the auto-build did not fire. | Run `publish-gate.sh`. It re-triggers Pages until the zip is 200.                                                                   |
| Proxy updated to the new version, but a **newly added add-on is not listed** under Install from repository | Kodi cached the OLD add-on list when it checked (the proxy was still the old version at that instant).                                                                     | On the box: **Check for updates AGAIN** (second time), or restart Kodi. Already-present add-ons show; only the new one was missing. |
| `repository.json` has the add-on but the proxy does not serve it                                           | An explicit `platforms` list that excludes the box's platform (`repository.py` skips it).                                                                                  | Remove/widen the `platforms` key, re-release.                                                                                       |
| `git status` shows commits "to push" but the deploy worked                                                 | You are looking at the **source** repo (e.g. `moquette/ezmaintenanceplusplus`), not this one. They are independent; the deploy copies source _into_ this repo.             | Confirm with `git -C <repo> ls-remote origin main` vs local HEAD.                                                                   |

## Root-cause fix (recommended, do deliberately)

The fragility is that the proxy self-updates from Pages. Point its **own** zip at
raw in `repository.json` (like every other add-on) so future proxy releases never
depend on a Pages build:

```jsonc
// addons/repository.tony7bones/resources/repository.json -> the repository.tony7bones entry
"assets": { "zip": "https://raw.githubusercontent.com/{username}/{repository}/{ref}/addons/{id}/{id}-{version}.zip" }
```

Trade-off: fresh first-time installs still browse the Pages site, but installed
boxes would self-update from raw (instant, reliable). Test (`test_proxy.py`,
`test_deploy.py`) and release once, after which the Pages dependency is gone for
self-updates. Until then, `publish-gate.sh` is the safety net.
