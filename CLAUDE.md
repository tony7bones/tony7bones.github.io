# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## HARD RULE: you may not say something is impossible on Apple TV

**Read `~/Code/moquette/kodi/.claude/skills/apple-tv/SKILL.md` before claiming
you cannot do something on a tvOS box.** One file, dispatch index in section 0.
Everything this project has ever needed is in it and proven on hardware: how to
wake a box that is OFF (section 7, you reboot it), how to read the logs
(section 3), how to read any setting with Kodi CLOSED (section 5), crash reports
and memory kills (section 4), deploying and proving the bytes landed (section 7),
and why a file listing is a FALSE NEGATIVE on tvOS (section 8).

Every "it is not supported", "there is no way to" and "the box is unreachable"
ever written about these boxes has been **wrong**, each time because someone
stopped after one failed command instead of reading what was already written.

Before writing that something cannot be done you must have: read the relevant
section of that playbook, checked `.claude/memory/`, retried the exact command
three times (wireless tvOS pairings throw transient errors on healthy boxes),
checked the flag against the subcommand (`copy from` takes `--user`, `info files`
takes `--username`), and run `xcrun devicectl <subcommand> --help`. Then report
what you tried and what it returned.

The ONE genuine gap is screenshots, which are impossible on tvOS because
`WinSystemTVOS.mm` never registers a screenshot surface. Cite that. Everything
else is documented.

**"Fixed" means verified on the affected device class, not verified in code.**
A green suite is not a fix. Cheapest-first: the two-layer test fake, then the
wipeable macOS bench, then a real box (playbook section 12a).

## Markdown rules (enforced by the global git hook)

These are the whole standard. There is no skill to load.

- No em dash, en dash, horizontal bar, robot emoji, or AI attribution anywhere.
  The plain hyphen `-` is always fine.
- Never begin a wrapped line with `+`, `-`, or `*`. CommonMark turns it into a
  list item and splits your paragraph.
- Never let an inline code span cross a line break. It strips the
  list-continuation indent and leaves the next agent editing a stale copy.
- Markdown is deliberately NOT auto-formatted here. Do not add it back.

## House rules

- **Routine changes get a one-line commit message.** Long-form records
  (acceptance logs, multi-paragraph commits) are for genuine incidents only.
- Approval is needed for DESTRUCTIVE or OUTWARD-FACING actions only: wiping or
  restoring onto a box, publishing, pushing. Reading logs, listing files,
  read-only JSON-RPC queries and inspecting archives need no approval. The
  office Fire TV `192.168.7.162` HANDS-OFF rule was **LIFTED 2026-07-21**; it
  is a normal target and the rule must not be reinstated.
- **Always pin `adb -s <ip>:5555`.** Several boxes sit on adb at once, so an
  unpinned command lands on whichever one adb happens to pick.
  `_tools/firetv.sh` lost its silent `192.168.7.162` default on 2026-07-21: it
  now needs an alias or `FIRETV_IP` and echoes the target it resolved. Check
  what it points at before running it.
- Safety core, unchanged: a backup must contain what it claims (one
  archive-contents inspection when backup/restore code changes); CI green before
  deploy; skins install from the Kodi repo, never adb/devicectl push; the
  publish allowlist and secret gate stay exactly as they are.

---

## READ FIRST: where the open work is

There is no tracker. `TASKS.md` was deleted 2026-07-21 along with the fleet
process; `docs/OPTIMIZATION-BACKLOG.md` still holds five unstarted hub tooling
items and states plainly that none are implemented. `git log` is the load-bearing
fact.


**This repo is a PUBLISHING SURFACE, but publishing is now an ALLOWLIST**
(changed 2026-07-18; the previous text here said every tracked file is
published, which was true then and is false now).

`_tools/build_site.py` copies a tracked file into the Pages artifact only if
`check_site_secrets.publish_refusal()` allows it: the dirs `addons/`, `images/`
and `dropbox/`, plus `README.md`, `style.css`, `.nojekyll` and `package.json`.
Everything else is refused, including `docs/`, `.claude/`,
`_tools/`, `.github/` and this file. Tracked symlinks are refused outright,
because a copy dereferences them and would publish whatever they point at.

Why it was inverted: an audit found the fleet's LAN addresses in 17 tracked
files, 39 occurrences in one playbook alone, all live on the public site,
alongside agent skills, adb runbooks and NFS export layouts. A denylist was
tried first and an adversarial review enumerated bypasses in one pass. An
allowlist fails toward "a public file is missing", which someone notices,
instead of "an internal file was published", which nobody does.

**So adding a new tracked file no longer publishes it by accident.** The
inverse now applies: if you add something that genuinely SHOULD be public,
add it to `_PUBLISH_DIRS` / `_PUBLISH_FILES` or it will silently not ship.

**IMPORTANT:** exclusion from the artifact is NOT exclusion from the public.
This repo and its full history remain public on GitHub, so everything listed
above is still readable by anyone who clicks through. The change removes it
from the served origin and from Pages crawling; it does not un-publish it.

---

## CLOSED - the legacy `addons/script.ezmaintenanceplusplus/` shim is DELETED

**EXECUTED 2026-07-20 (`08d9a3d`) with owner approval. Nothing to do here.**

The directory, its `index.html`, and its code-less zip are gone, and
`addons/addons.xml` was regenerated by `generate_repo.py` down to a single entry
(`repository.tony7bones`, which STAYS: `/addons/` is still the bootstrap path
for the repo zip itself). 237 tests pass and no reference to the deleted path
remains anywhere in the tree.

**Do not recreate this directory.** If a future task seems to need it, the
answer is the `/static/` catalog built from `addons/hosted/`, not a second
publishing path.

Verified before deleting, rather than assumed: `repository.tony7bones` 3.0.0
points at `https://tony7bones.github.io/static/addons.xml`, the live static tree
was current, and both reachable boxes (atv2 and the bedroom Fire TV at
`192.168.7.84`) run repository 3.0.0. Only a pre-3.0.0 repository addon could
have read `/addons/`; none was found. atv1, ts1, ts2 and the hands-off office
box at `192.168.7.162` were not checked, so if one of those ever reports a
broken repo, this commit is the cause and reinstalling repository 3.0.0 is the
fix.

One correction to the record below: the published zip was **3508 bytes**, not
1,866. The substance was right, and the deletion was carried out on the same
reasoning. Retained for the WHY:

**The verdict was: the mirror is unjustified and should be deleted.** Every
justification previously written in this file was false:

- Pages `/addons/` was NEVER a declared `<dir>` in any historical `addon.xml`
  (v2.2.x pointed at `127.0.0.1:61234`, v3.0.0 points at `/static/`).
- The static catalog has ALWAYS read `addons/hosted/`, never this directory.
- The owner LIFTED the "keep it for old engine bundles" rule on 2026-07-15
  (no fleet convergence, fresh installs only).

It was also actively harmful: the published zip contained only `addon.xml`,
which declares `library="default.py"` and an `xbmc.service start="startup"` that
were not in the zip. Kodi installs it, fails at every boot, and squats the
add-on ID at the stale version forever, because Kodi upgrades by version number
only.

Full finding: `~/Downloads/kodi-legacy-addons-shim-finding-20260718.md`.

The two gotchas it flagged, and how they played out:

1. Do NOT bundle an "exclude `addons/` from Pages" change. `pages.yml` passes
   `--transition` and `verify_live_site.py` then HEADs `/addons/addons.xml`, so
   excluding the tree fails CI. **Honored: no Pages exclusion was bundled, and
   `/addons/addons.xml` still exists for `repository.tony7bones`.**
2. The deletion is a catalog SHRINK and may need `--allow-catalog-shrink` on the
   first deploy. **Watch the first deploy for this.**

---

## What this repo is

A GitHub Pages site (`tony7bones.github.io`) that hosts a **static** Kodi add-on repository. The site is static: no bundler, no runtime, no on-box service. Python tooling under `_tools/` generates and deploys everything; `package.json` is only a script-runner wrapper.

The repository add-on, `repository.tony7bones` (version 3.0.0), is a **normal static-only repository add-on**. Its `addon.xml` declares a SINGLE `<dir>` pointing at the static catalog on GitHub Pages:

```xml
<dir>
    <info>https://tony7bones.github.io/static/addons.xml</info>
    <checksum>https://tony7bones.github.io/static/addons.xml.md5</checksum>
    <datadir zip="true">https://tony7bones.github.io/static/</datadir>
</dir>
```

Once installed, Kodi reads add-on metadata and zips directly from that static tree as plain files. There is NO `xbmc.service`, NO local HTTP proxy, NO `127.0.0.1:61234`, and NO `repository.github` engine. The add-on is just metadata + icon/fanart + this one `<dir>`.

> **Retired (do not describe as live).** The old "virtual proxy engine" is gone: the local `127.0.0.1:61234` HTTP proxy, i96751414's `repository.github` engine, runtime streaming from GitHub, and the baked `resources/repository.json` a former `lib/service.py` read. Also retired and DELETED: the entire Setup add-on family (`script.tony7bones.bootstrap`, the shared library `script.module.tony7bones`, the Estuary MOD V2+ skin patch `script.tony7bones.modv2plus`) and everything they did (the modular "0-1-2" Setup, Express/Guided wizards, the per-device `.env` model, the adb provisioner, the in-Kodi IPTV apply half, MOD V2 skin install/activation). The proxy release tooling is gone too (`deploy.py`, `check_consistency.py`, the `release.py --proxy` mode, the shared-library "lockstep"). None of this ships anymore.

**Install URL (must stay constant): `https://tony7bones.github.io/`** (the root). Users add this as a Kodi File Manager source, then install `repository.tony7bones-<version>.zip` from it. The base URL never moves; only the zip filename's version changes (cache-busting comes ONLY from the versioned filename, because Kodi cannot follow a moving base URL).

### The static catalog (`/static/`)

The served `/static/` tree is the Kodi repository the add-on points at:

- `/static/addons.xml` + `/static/addons.xml.md5` (the catalog index + checksum),
- per-add-on zips and materialized art under `/static/<id>/`.

It currently has **26 entries** (verify with `python3 -c "import json;print(len(json.load(open('_tools/catalog.json'))))"`). It is built in CI by `_tools/build_site.py` -> `_tools/static_catalog.py` from the manifest `_tools/catalog.json`, then deployed via GitHub Pages. `static_catalog.py` materializes each entry's declared art out of its zip so every icon/fanart URL resolves.

### Two source trees: `dropbox/` (canvas) and `addons/` (add-on tree)

The repo has two committed source trees, each with a different job:

- **`dropbox/`** is the owner's **pristine human canvas**. It holds ONLY hand-authored installable content (`repositories/` third-party repo installer zips and `rss/`) and NEVER any generated files (no `index.html`, no checksums). The CI build (`build_site.py`) **mirrors `dropbox/` 1:1 into the artifact ROOT**, which GitHub Pages serves at the bare URL `https://tony7bones.github.io/` - the mirror is generated fresh every deploy and is NEVER committed. Pointing Kodi's File Manager at the bare URL therefore shows exactly the canvas: `repositories/ rss/` plus the install zip and a generated Kodi index per folder. The mirror **honors `.gitignore`**, so gitignored local files are never committed or copied into the served tree. (`media/`, `zips/`, and `iptv/` were retired from the canvas 2026-07-16: everything private or generated - IPTV configs, playlists, guides, settings - lives ONLY on the KodiShare, reachable via LAN/Tailscale.)
- **`addons/`** is the add-on tree. It holds the add-on source, the built per-addon zips, `addons.xml`/`.sha256`/`.md5`, and the mirrored third-party-repo trees under `addons/hosted/<id>/`. It is NOT listed at the bare URL.

### Live add-ons under `addons/`

**One** first-party add-on dir lives directly under `addons/`:

- **`addons/repository.tony7bones/`** - the static-only repository add-on (3.0.0) described above. This is the ONLY entry in `addons/addons.xml`.

`addons/script.ezmaintenanceplusplus/` was **DELETED 2026-07-20** (`08d9a3d`); see the closed block at the top of this file. Do not recreate it, and do not resurrect the deleted full-source copy either. The EZM++ metadata that boxes actually read lives at `addons/hosted/script.ezmaintenanceplusplus/`, and its source is in the sibling repo `~/Code/moquette/kodi/ezmpp` (`moquette/ezmaintenanceplusplus`, public; note the local dir is `ezmpp`, and the standalone path `~/Code/moquette/ezmaintenanceplusplus` that older docs cite DOES NOT EXIST).

`addons/hosted/<id>/` holds mirrored third-party-repo trees (static, hand-committed metadata; not zipped or indexed by the generator). **Two of the `hosted/<id>/` entries are OUR OWN add-ons**, mirrored here as metadata only with source in a sibling repo:

- **`skin.estuary7`** (`addons/hosted/skin.estuary7/`) - source, build pipeline, and tests live in `~/Code/moquette/kodi/estuary7` (`moquette/estuary7`). This repo holds only `addon.xml` + `icon.png`/`fanart.jpg`; the catalog points `assets.zip` at that repo's GitHub Release asset.
- **`script.ezmaintenanceplusplus`** (`addons/hosted/script.ezmaintenanceplusplus/`) - source, the full test suite, and release tooling live in `~/Code/moquette/kodi/ezmpp`. Same mirror pattern. Fix bugs and add tests in the sibling repo; only bump the hosted metadata + release here. 

Both patterns mean a `git status` / "commits to push" question about the skin or EZM++ almost always resolves in the OTHER repo, not this one; see the deploy skill's troubleshooting table.

### Single branch - `main` only

Everything lives on `main`. Main is **sources-only**: the canvas (`dropbox/`), the `addons/` tree (source + current-version zips + `addons.xml`), `_tools/`, and docs. The served site (canvas mirror, root `index.html`, `robots.txt`, `/static/` catalog, root installer) is built by CI into the Pages artifact and never committed.

## Commands

```bash
# Regenerate the COMMITTED add-on artifacts: addons.xml + hashes, per-addon zips
# (current version only; superseded zips are pruned) and per-addon index pages.
# Run this locally before committing whenever you change addon sources.
python3 _tools/generate_repo.py            # npm run build

# Run the full test suite (237 tests, all green; verified 2026-07-19)
python3 -m pytest _tools/ -q               # npm test

# Lint the Python tooling
ruff check _tools/                         # npm run lint

# Build the full served site into an output dir (what CI does, plus the /static/ catalog)
python3 _tools/build_site.py --out _site

# Publish canvas-only changes (dropbox/ edits) WITHOUT an add-on release:
# regenerate, commit, push main. Refuses to publish credential-like content
# to the public site unless --allow-secrets.
python3 _tools/publish_canvas.py -m "Add foo repo zip to canvas"   # npm run publish
python3 _tools/publish_canvas.py -m "..." --dry-run                # npm run publish:dry

# Refresh the KodiShare backup mirror by hand. Runs automatically on every push
# of main (pre-push hook); mount-guarded, best-effort, never blocks.
python3 _tools/sync_share.py --dry-run

# Release ANY add-on - one command (see "Releasing" below)
python3 _tools/release.py --dry-run        # preview the plan
python3 _tools/release.py                  # bump + news + commit on the branch
```

## Releasing

**`python3 _tools/release.py` is THE release command for EVERY add-on.** The static repository add-on releases the same way as any other add-on: there is no separate proxy path anymore. The tool detects what changed vs `origin/main` (via the shared `release_detect.changed_addons`, the SAME detector the pre-push gate uses, so the two can never disagree), computes the next version (MINOR by default), drafts and PREPENDS the `<news>`, regenerates deterministically, runs the script-side consistency gate, and commits `chore(release): ...` on the branch, then STOPS. No auto-push. On push, CI builds and deploys the static site.

```bash
python3 _tools/release.py                          # minor-bump every changed add-on, commit, STOP
python3 _tools/release.py --dry-run                # show the plan (incl. WHICH files), change nothing
python3 _tools/release.py --patch                  # patch instead of the minor default (or --minor / --major)
python3 _tools/release.py --version 3.1.0 --addon repository.tony7bones
python3 _tools/release.py --news "repository.tony7bones=Add a hosted add-on"
python3 _tools/release.py --push                   # also push the branch (default: commit only)
python3 _tools/release.py check                    # the script-side consistency gate only
```

Every release MUST bump the version (Kodi auto-upgrades by version number only, so a same-version byte change silently breaks upgrades). The tool computes the correct bump and never skips it; the rule is enforced by `check_versions.py` in both the pre-push hook and CI. The tool is idempotent: a re-run with no new source edit is a no-op, never a double-bump. It refuses when the branch is behind origin or at the 9.9.9 version ceiling. Rolls back to the pre-release HEAD on any failure. Full detail: `docs/playbooks/release-and-deploy.md`.

The release tooling is split for testability: `_tools/release_lib.py` (pure version math + file transforms), `_tools/release_detect.py` (the ONE shared `changed_addons` detector behind both the tool and the gate), and `_tools/release.py` (the unified tool + the script-side consistency gate), with `_tools/test_release.py` / `_tools/test_release_detect.py` / `_tools/test_check_versions.py`.

## Gates (pre-push hook + CI)

`.githooks/pre-push` blocks a push unless the test suite passes, lint is clean, generated files are up to date, and every changed add-on bumped its version (`check_versions.py`). It also runs the KodiShare mirror sync (`sync_share.py`, main only, best-effort). Install once after cloning:

```bash
git config core.hooksPath .githooks
```

The hook runs `python3 -m pytest` and `ruff` with the bare interpreter on PATH, so those deps must be importable by that `python3` or the hook fails closed. On a fresh clone install them once (on an externally-managed PEP 668 Homebrew/macOS python):

```bash
python3 -m pip install --user --break-system-packages pytest ruff
```

Two CI workflows back this up and **never commit to main**:

- **`.github/workflows/generate_repo.yml`** ("Validate Kodi Repository") re-runs the tests, lint, the hosted-mirror release-freshness gate (`check_hosted_release_sync.py`), the generator-staleness check, and the per-add-on version-bump gate (main only).
- **`.github/workflows/pages.yml`** ("Build & Deploy Pages") runs the same gates, builds the full site with `build_site.py` (including the `/static/` catalog), runs the secret gate (`check_site_secrets.py`) and a double-build determinism diff, then **deploys via GitHub Pages** (Pages source = GitHub Actions) and verifies live from the consumer seat (`verify_live_site.py`). It also runs on a daily cron to refresh mutable third-party metadata, and on `repository_dispatch` when a sibling repo (estuary7 / ezmpp) publishes a release.

Note: pages.yml has NO path filter - every push to main builds and deploys (any tracked file can shape the artifact). Only generate_repo.yml keeps a path filter.

**Rollback:** a bad canvas/tooling commit rolls back with `git revert` + push (CI redeploys). A bad ADD-ON release must roll FORWARD (new version bump) - reverting lowers the version and the version-bump gate rightly blocks it. NEVER flip the Pages source back to branch serving (`build_type=legacy`): main is sources-only and would serve a site with no /static/, no root index, and no installer.

## Architecture

### Source areas

| Path                    | Purpose                                                                                                                                                                                                                                                       |
| ----------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `addons/<addon-id>/`    | Any dir with an `addon.xml` is built into a zip and listed in `addons/addons.xml`. Currently `repository.tony7bones` ONLY, since the `script.ezmaintenanceplusplus` shim was deleted 2026-07-20.                                                              |
| `addons/hosted/<id>/`   | Mirrored third-party-repo trees (`addon.xml` + zip). Static, committed by hand, NOT zipped or indexed by the generator (`hosted` is the sole `_ADDONS_SPECIAL` entry). Includes the `skin.estuary7` / `script.ezmaintenanceplusplus` metadata mirrors.        |
| `dropbox/repositories/` | Hand-authored third-party repository installer zips. Not in `addons.xml`; Kodi installs them manually via File Manager. Mirrored 1:1 to the served `/repositories/`.                                                                                          |
| `dropbox/rss/`          | Hand-authored asset dir. Mirrored to the served root and recursively auto-indexed for File-Manager browsing. Git-ignored files are kept locally and never copied into the served tree. (`media/`, `iptv/`, `zips/` retired 2026-07-16.)                       |

`dropbox/` is **pristine**: the build NEVER writes generated files (index.html, checksums) back into it; `build_site.py` mirrors it into the CI artifact ROOT, which is what GitHub Pages serves at the bare URL. Nothing mirror-related is committed.

### Generated files (must be committed)

`generate_repo.py` produces, and every one must be committed:

- `addons/addons.xml`, `addons/addons.xml.sha256`, `addons/addons.xml.md5`
- per-addon `index.html` and the CURRENT-version zip under `addons/<addon-id>/` (superseded zips are pruned automatically)

The served canvas mirror, root `index.html`, and `robots.txt` are NOT in this list anymore: `build_site.py` generates them into the CI artifact every deploy. Always run `python3 _tools/generate_repo.py` locally and commit the output before pushing. CI fails on stale generated files.

### The build/deploy pipeline

`build_site.py` assembles the complete served site into an output dir: it copies every **git-tracked** file (`git ls-files` is the copy list, so a gitignored local secret can never reach the artifact) with structural secret exclusion applied at copy time, GENERATES the served canvas mirror + root `index.html` + `robots.txt` from `dropbox/` (via the `generate_repo` mirror functions), then builds the `/static/` catalog next to it via `static_catalog.py`. `place_root_installer()` copies the freshly built `repository.tony7bones-<version>.zip` to the site root and into the browsable `repositories/` folder (no committed root zip; it is built fresh every deploy). CI runs this and deploys the result via Pages.

### Determinism

Generated zips are **reproducible** so CI's staleness gate does not flag them on every run. `generate_repo.py` excludes build-time cruft dirs (`_CRUFT_DIRS`: `__pycache__`, `.ruff_cache`, `.pytest_cache`, `.mypy_cache`) from every zip/index/mirror. When committing, a freshly built zip may differ only by mtime on the first build; settle it by regenerating and `git commit --amend --no-edit`, then confirm a second regenerate yields no diff.

### Shared stylesheet

`style.css` at the repo root holds the dark theme used by any styled user-facing page. The directory-listing pages the generator writes (via `_make_index()`) intentionally use HTML 3.2 format for Kodi parser compatibility and do NOT apply the stylesheet.

### The `_tools/` inventory

Release: `release.py`, `release_lib.py`, `release_detect.py`, `check_versions.py`. Build/deploy: `generate_repo.py`, `build_site.py`, `static_catalog.py` (+ manifest `catalog.json`), `verify_live_site.py`, `check_site_secrets.py`, `secret_patterns.py`, `check_hosted_release_sync.py`, `mirror_closure.py`. Canvas + backup: `publish_canvas.py`, `sync_share.py`. Device tooling: `firetv.sh`, `provision-kodi.sh` (the adb provisioner; the Setup add-ons it drove are retired, but the script is retained). IPTV builder: `build_iptv.py` (+ its test suite) was **extracted to its own private repo (`moquette/iptv`) and removed here (2026-07-17)**; the mini builds IPTV centrally and serves it over the NFS share (IPTV 2.0), so this repo no longer host-builds. `make_custom_m3u.py` remains.

## Adding content

### Adding a new Kodi add-on

1. Create `addons/<addon-id>/addon.xml` following the Kodi addon.xml schema and add any source files.
2. Run `python3 _tools/generate_repo.py` (builds the zip, updates `addons.xml`).
3. `git add addons/<addon-id>/ addons/addons.xml addons/addons.xml.sha256 addons/addons.xml.md5`
4. Release it with `python3 _tools/release.py` so it gets a version bump + news, then push (CI builds and deploys the static site).

### Adding a new repository installer zip

1. Drop the `.zip` into `dropbox/repositories/` (the canvas - the served copy is generated in CI).
2. Commit it (`publish_canvas.py -m "..."` does commit+push in one step); CI mirrors the canvas and regenerates the served `repositories/` listing on deploy.

## Playbooks + skills that still apply

> These carry the WHY and exact code locations. Read the matching one before acting.
>
> - `docs/playbooks/release-and-deploy.md` - the release flow + the static-CI-deploy pipeline + determinism.
> - `docs/playbooks/local-kodi-verification.md` - drive the real local Kodi; honest verification (prove non-empty `GetDirectory` + rendered menu, not just "no ImportError").
> - `docs/playbooks/kodi-install-mechanics.md` - install on Omega without blocking prompts (direct-extract + `SetAddonEnabled`, origin stamping, deps, platform binaries).
> - `docs/playbooks/kodi-settings-clobber.md` - the "Kodi clobbers direct settings writes" class and the two fix mechanisms.
> - `docs/playbooks/kodi-vfs-cannot-read-foreign-local-files.md` - Kodi's VFS can silently return empty reads for a local file a non-VFS writer produced.
> - `docs/playbooks/iptv-channel-customization.md` - the env-driven IPTV curation pipeline (the host `build_iptv.py` half; extracted to `moquette/iptv` 2026-07-17, kept here as historical reference).
> - `docs/playbooks/firetv-adb-dev.md` - driving a Fire TV over ADB + JSON-RPC (`_tools/firetv.sh`).
> - `docs/playbooks/firetv-stick-scoped-storage-provisioning.md` - provisioning a non-rooted Fire OS 11 Stick over adb.
> - `docs/playbooks/mac-mini-media-server.md` - the `Mini` box that serves every Kodi client over NFS/SMB.
> - `.claude/skills/deploy/SKILL.md` - the release + deploy runbook.
> - `.claude/skills/kodi-super-agent/SKILL.md` - distilled agent operating guide.
> - `~/Code/moquette/kodi/.claude/skills/apple-tv/SKILL.md` - **THE Apple TV reference** (storage model, deploy traps, crash inventory). Section 0 is a dispatch index.
> - `docs/playbooks/modv2plus-dev-cycle-and-lessons.md` - the retired MOD V2+ patch; kept as a historical record of hard-won Kodi lessons.
> - `docs/incident-2026-07-15-proxy-engine-404-fleet-deadlock.md` and `docs/plans/` - historical records of the retired proxy architecture and the static conversion. Do not treat as current.
