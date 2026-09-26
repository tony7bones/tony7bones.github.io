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
  This repo carries no adb helper any more (`_tools/firetv.sh` was deleted
  2026-09-26: its add-on commands had been dead since the static conversion
  and no gate called it); the meta-root `.claude/scripts/firetv-deploy.sh`
  takes an alias or IP and echoes the target it resolved.
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
for the repo zip itself).

**Do not recreate this directory.** If a future task seems to need it, the
answer is the `/static/` catalog built from `addons/hosted/`, not a second
publishing path. Every justification once written here for the mirror turned out
false: Pages `/addons/` was NEVER a declared `<dir>` in any historical
`addon.xml` (v2.2.x pointed at `127.0.0.1:61234`, v3.0.0 at `/static/`), the
static catalog has ALWAYS read `addons/hosted/`, and the owner lifted the "keep
it for old engine bundles" rule on 2026-07-15. It was also actively harmful: the
published zip held only an `addon.xml` declaring a `library="default.py"` and an
`xbmc.service start="startup"` that were not in the zip, so Kodi installs it,
fails at every boot, and squats the add-on ID at that stale version forever,
because Kodi upgrades by version number only.

Only a pre-3.0.0 repository add-on could have read `/addons/`, and none was
found on the boxes checked before deleting. If a box ever reports a broken repo,
this commit is the cause and reinstalling `repository.tony7bones` 3.0.0 is the
fix. Fuller record, including the corrected zip size:
`~/Code/moquette/kodi/.claude/memory/project-legacy-addons-shim.md`.

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

It currently has **28 entries** (verify with `python3 -c "import json;print(len(json.load(open('_tools/catalog.json'))))"`). It is built in CI by `_tools/build_site.py` -> `_tools/static_catalog.py` from the manifest `_tools/catalog.json`, then deployed via GitHub Pages. `static_catalog.py` materializes each entry's declared art out of its zip so every icon/fanart URL resolves.

### Two source trees: `dropbox/` (canvas) and `addons/` (add-on tree)

The repo has two committed source trees, each with a different job:

- **`dropbox/`** is the owner's **pristine human canvas**. It holds ONLY hand-authored installable content (`repositories/` third-party repo installer zips and `rss/`) and NEVER any generated files (no `index.html`, no checksums). The CI build (`build_site.py`) **mirrors `dropbox/` 1:1 into the artifact ROOT**, which GitHub Pages serves at the bare URL `https://tony7bones.github.io/` - the mirror is generated fresh every deploy and is NEVER committed. Pointing Kodi's File Manager at the bare URL therefore shows exactly the canvas: `repositories/ rss/` plus the install zip and a generated Kodi index per folder. The mirror **honors `.gitignore`**, so gitignored local files are never committed or copied into the served tree. (`media/`, `zips/`, and `iptv/` were retired from the canvas 2026-07-16: everything private or generated - IPTV configs, playlists, guides, settings - lives ONLY on the KodiShare, reachable via LAN/Tailscale.)
- **`addons/`** is the add-on tree. It holds the add-on source, the built per-addon zips, `addons.xml`/`.sha256`/`.md5`, and the mirrored third-party-repo trees under `addons/hosted/<id>/`. It is NOT listed at the bare URL.

### Live add-ons under `addons/`

**One** first-party add-on dir lives directly under `addons/`:

- **`addons/repository.tony7bones/`** - the static-only repository add-on (3.0.0) described above. This is the ONLY entry in `addons/addons.xml`.

`addons/script.ezmaintenanceplusplus/` was **DELETED 2026-07-20** (`08d9a3d`); see the closed block at the top of this file. Do not recreate it, and do not resurrect the deleted full-source copy either. The EZM++ metadata that boxes actually read is resolved at build time from the latest GitHub release of `moquette/kodi-ezmpp` (no committed copy since 2026-09-26; the `addons/hosted/script.ezmaintenanceplusplus/` mirror is gone too), and its source is in the sibling repo `~/Code/moquette/kodi/ezmpp` (note the local dir is `ezmpp`, and the standalone path `~/Code/moquette/ezmaintenanceplusplus` that older docs cite DOES NOT EXIST).

`addons/hosted/<id>/` holds mirrored third-party-repo trees (static, hand-committed metadata; not zipped or indexed by the generator). Since the afternoon of 2026-09-26 it holds ONLY the seven third-party repository installers (`repository.Magnetic`, `repository.kodinerds`, `repository.loop`, `repository.redwizard` as `hosted`; `repository.kodifitzwell`, `repository.umbrella`, `repository.diggz` as `hybrid` without an index): **nothing under it is ours and nothing under it is a dependency of ours.** The eleven official-library modules that used to be committed there (`plugin.program.autocompletion` 2.1.2, `script.image.resource.select` 3.0.2, `script.module.autocompletion` 2.1.1, `script.module.certifi` 2023.5.7, `script.module.chardet` 5.1.0, `script.module.idna` 3.10.0, `script.module.requests` 2.31.0, `script.module.simplecache` 2.0.2, `script.module.simpleeval` 0.9.13, `script.module.unidecode` 1.3.6, `script.module.urllib3` 2.2.3) are `hybrid` entries with `upstream_index` `https://mirrors.kodi.tv/addons/piers/addons.xml.gz` and zip template `https://mirrors.kodi.tv/addons/piers/{id}/{id}-{version}.zip`: the build reads the official Piers index (gzipped, 13MB unpacked, fetched ONCE per build for all eleven), fetches each zip from the official mirror (302 to a volunteer mirror, followed, retried up to three times, accepted only if it packages exactly that id and version), and takes `addon.xml` and art out of the zip. The committed copies were NOT stale when they left (all eleven matched the official versions, measured that day); the switch is so they cannot rot. The official zips' bytes differ from the old committed copies at the same version (packaging only, the `addon.xml` inside is byte-identical), which a box already at that version never notices, because Kodi installs by id and version. Fifteen catalog entries therefore have NO `addons/hosted/` directory at all, because the build resolves their version and metadata upstream on every run (since 2026-09-26; owner's rule: THERE MUST BE NO MIRROR VERSION TO BE WRONG). The four that are ours or serve ours directly:

- **`script.ezmaintenanceplusplus`** (no hosted dir; `release-asset` entry) - ours. Source, the full test suite and release tooling live in `~/Code/moquette/kodi/ezmpp` (GitHub `moquette/kodi-ezmpp`, public). Its CI publishes every version bump as the GitHub release `v<version>` carrying `<id>-<version>.zip` and dispatches this hub; the build resolves `releases/latest` and takes `addon.xml` from the zip. Fix bugs and add tests in the sibling repo; nothing to bump here.
- **`plugin.video.pov`** (no hosted dir; `hybrid` entry with `upstream_index`) - NOT ours. The build reads upstream's own `https://kodiyashimaru.github.io/repo/packages/addons.xml` for the current version, fetches that zip from the upstream Pages host and republishes it under our `/static/`, so no third-party binary lives in this repo. It is served because `skin.estuary.pov` declares a hard `<import>` on it, and Kodi resolves a hard dependency only from the repository the add-on is installed FROM: with POV reachable only via `repository.kodifitzwell` the install fails with `failed to find dependency plugin.video.pov`, measured on a Kodi 22 bench. The hand-typed version this entry used to carry rotted once (6.08.15 against an upstream 6.09.06, zip 404, POV dropped from the build for days).
- **`skin.estuary.pov`** (no hosted dir; `release-asset` entry) - ours. Source, tests and the reproducible build live in `~/Code/moquette/kodi/estuary-pov` (GitHub `moquette/kodi-estuary-pov`, public since 2026-09-26). A version bump pushed to its `main` becomes the GitHub release `skin.estuary.pov-v<version>` carrying `skin.estuary.pov-<version>.zip`, and the CI dispatches this hub. The tag is NAMESPACED because that repo also ships `service.tvos.pythonfix` and a repo has one `releases/latest`: the zip template in `_tools/catalog.json` spells the tag as `{id}-v{version}`, and `static_catalog._latest_namespaced_release` lists the repo's releases and takes the newest in that namespace. 1.4.2 was the last hand-copied version and 1.4.3 the first from CI (two publish paths never share a version). It is stock Kodi Estuary 4.1.0 reworked so the Movies and TV shows home tabs are driven by `plugin.video.pov`; it imports `xbmc.gui` 5.18.0 (the Kodi 22 floor), `plugin.program.autocompletion` 2.1.2 and `plugin.video.pov` 6.08.15. Its whole closure (autocompletion plugin -> autocompletion module -> requests -> urllib3/certifi/chardet/idna) is gated at build time by `_check_imports_hosted`, transitively through the build-resolved modules.
- **`service.tvos.pythonfix`** (no hosted dir; `release-asset` entry since 2026-09-26) - ours, the tvOS Python repair service, user-installed by Apple TV owners from this listing. Same repo, same CI and the same namespaced tag shape as the skin (`service.tvos.pythonfix-v<version>`). 1.1.0 was served from a committed copy until the switch; the release asset is byte-identical to it (sha256 measured), so no bump was needed. Its closure (`script.module.requests` and what it drags in) is gated at build time by `_check_imports_hosted`, transitively.

Both patterns mean a `git status` / "commits to push" question about the skin or EZM++ almost always resolves in the OTHER repo, not this one; see the deploy skill's troubleshooting table. Build-resolved entries whose lookup fails (release API down, upstream index unreachable, zip 404, packaged version not matching the tag) fall back to the live last-good copy and are marked `stale` in the manifest, exactly like any other entry; their `<import>`s are checked against the catalog at build time (`_check_imports_hosted`, transitively through the other build-resolved entries, each `addon.xml` read out of its resolved zip), since no committed `addon.xml` is left for `test_closure.py` to walk offline; that file now pins that every id the fleet installs directly is build-resolved and exercises the walk against a fake tree.

### Single branch - `main` only

Everything lives on `main`. Main is **sources-only**: the canvas (`dropbox/`), the `addons/` tree (source + current-version zips + `addons.xml`), `_tools/`, and docs. The served site (canvas mirror, root `index.html`, `robots.txt`, `/static/` catalog, root installer) is built by CI into the Pages artifact and never committed.

## Commands

```bash
# Regenerate the COMMITTED add-on artifacts: addons.xml + hashes, per-addon zips
# (current version only; superseded zips are pruned) and per-addon index pages.
# Run this locally before committing whenever you change addon sources.
python3 _tools/generate_repo.py            # npm run build

# Run the full test suite (209 tests, all green, 9s wall; measured 2026-09-26
# after the release tool and its 30s of sandbox tests were deleted)
python3 -m pytest _tools/ -q               # npm test

# Lint the Python tooling. Needs the PINNED ruff: ruff.toml declares
# required-version, so any other ruff refuses to run rather than reporting
# findings CI would never report. ../bin/check-all provisions the pin for you.
ruff check _tools/                         # npm run lint

# Build the full served site into an output dir (what CI does, plus the /static/ catalog)
python3 _tools/build_site.py --out _site

# Publish canvas-only changes (dropbox/ edits) WITHOUT an add-on release:
# regenerate, commit, push main. Refuses to publish credential-like content
# to the public site unless --allow-secrets.
python3 _tools/publish_canvas.py -m "Add foo repo zip to canvas"   # npm run publish
python3 _tools/publish_canvas.py -m "..." --dry-run                # npm run publish:dry

# Refresh the Kodi share's repositories/ backup copy of the installer zips by
# hand. Runs automatically on every push of main (pre-push hook);
# mount-guarded, best-effort, never blocks.
python3 _tools/sync_share.py --dry-run

# The version-bump gate the pre-push hook and CI run (see "Releasing" below)
python3 _tools/check_versions.py           # npm run check
```

## Releasing

The ONLY add-on released from this repo is `repository.tony7bones`
(`addons/repository.tony7bones/`); everything else the hub serves is resolved
at build time from a sibling repo's release or an upstream index (see "Live
add-ons under `addons/`"). Releasing it is a hand edit, four steps:

1. Edit `addons/repository.tony7bones/addon.xml`: raise the `version`
   attribute and prepend a `<news>` line.
2. `python3 _tools/generate_repo.py` (rebuilds the zip, `addons.xml` and
   the hashes; the superseded zip is pruned).
3. Commit the source and the generated output together.
4. Push `main`. CI builds and deploys the static site; the root installer
   `repository.tony7bones-<version>.zip` is placed fresh every deploy.

Every release MUST bump the version: Kodi auto-upgrades by version number
only, so a same-version byte change silently breaks upgrades. The bump is
enforced, not remembered: `check_versions.py` (the pre-push hook, and CI on
every push against the push's `before` SHA) blocks any push where the add-on's
source changed without its version increasing. Reverting a release lowers the
version and the gate rightly blocks it; roll FORWARD with a new bump.

`_tools/release.py`, the automatic bump-and-news tool, and its
`test_release.py` were deleted 2026-09-26: the one add-on it could act on was
last bumped 2026-07-16, no workflow, hook or `bin/check-all` ran it, and its
sandbox tests were 29.5s of a 40s suite. What survives is what the gates use:
`_tools/release_lib.py` (version parsing and comparison),
`_tools/release_detect.py` (the ONE `changed_addons` detector) and
`_tools/check_versions.py`, with `test_release_detect.py` and
`test_check_versions.py`. Full detail: `docs/playbooks/release-and-deploy.md`.

## Gates (pre-push hook + CI)

`.githooks/pre-push` blocks a push unless the test suite passes, lint is clean, generated files are up to date, and every changed add-on bumped its version (`check_versions.py`). It also refreshes the KodiShare `repositories/` backup copy of the installer zips (`sync_share.py`, main only, best-effort; its `apps/` and `media/`,`rss/` halves were deleted 2026-09-26 because those directories no longer exist on the share). Install once after cloning:

```bash
git config core.hooksPath .githooks
```

The hook installs its own pinned tooling from `requirements-ci.txt`, the same
file the workflows install from, into a cached venv under `.git/hook-tools`
(untracked, rebuilt only when the pins change). **Nothing to install by hand on
a fresh clone.**

That indirection is load-bearing, not tidiness. The hook previously ran
`python3 -m pytest` and `ruff` off the bare PATH, and on 2026-07-25 that made it
STRICTER than CI: PATH ruff was 0.16.0 against a CI pin of 0.15.22, so it
blocked pushes CI would have passed and the only way through was `--no-verify`,
which also skips the version-bump gate. A local gate that disagrees with CI in
either direction trains people to bypass it.

Two files carry the pins, and they move together. `requirements-ci.txt` is the
version source of truth for the hook and both workflows. `ruff.toml` repeats the
ruff version as `required-version` (so a hand-run `ruff` fails with one clear
sentence instead of a wall of findings that look like defects) and, more
importantly, declares `[lint] select`. The 2026-07-24/25 red deploys were ruff's
DEFAULT RULE SET changing, not its version: with the set declared, 0.15.22 and
0.16.0 both report 0 findings here, against 0 and 95 on their respective
defaults. Bump both files in one commit that also clears whatever the new
version flags, and never bump a pin to make a red build go green.

Everything above is also runnable across all four repos at once with
`../bin/check-all` (12 gates across the four repos, this one contributing pytest and ruff; measured 2026-09-26), which provisions the same pinned venv this hook
uses.

ONE push workflow plus two operational backstops, and **none of them ever commits to main**. All run on `ubuntu-26.04` with current action majors (`checkout@v7`, `setup-python@v7`, `cache@v6`, `upload-artifact@v7`, `download-artifact@v8`, `upload-pages-artifact@v5`, `deploy-pages@v5`, `configure-pages@v6`; measured 2026-09-26):

- **`.github/workflows/pages.yml`** ("Build & Deploy Pages") is the push workflow. On a push it runs the test suite, lint, the generator-staleness check and the version-bump gate (`check_versions.py` against `github.event.before`, so the bump is judged across the pushed range and not against itself); on the daily cron and on `repository_dispatch`, where no hub source changed, the test, lint and version steps are skipped (`if: github.event_name == 'push'`, pinned by `test_pages_workflow.py`) and the run goes straight to the artifact gates. Every run builds the full site with `build_site.py` (including the `/static/` catalog, with `GH_TOKEN` set to `T7B_SOURCE_READ_TOKEN` when stored, else `GITHUB_TOKEN`, so the release lookups use the REST API; both source repos are public, the secret is an optional escape hatch), runs the secret gate (`check_site_secrets.py`) and a double-build determinism diff, then **deploys via GitHub Pages** (Pages source = GitHub Actions) and verifies live from the consumer seat (`verify_live_site.py`). If a push run's live verify fails, the verify job re-dispatches the deploy ONCE (a branch-build race clobbered a deploy on 2026-09-26; a genuinely broken site cannot loop). It also runs on a daily cron to refresh mutable third-party metadata, and on `repository_dispatch` when a sibling repo (ezmpp or estuary-pov, both sending the historical type `ezmpp-release`) publishes a release. Every one of those runs re-resolves the EZM++ release, the two estuary-pov releases and the POV upstream index, so a new version needs no commit here.
- **`.github/workflows/ci_failure_alert.yml`** ("Alert on CI failure") runs after every "Build & Deploy Pages" run: a failure opens ONE GitHub issue assigned to moquette (or comments on the open one), and the next green run closes it. A red run nobody hears is not a gate; the freshness gate went red for nine days unheard before this existed.
- **`.github/workflows/pages_source_guard.yml`** runs daily and by hand and keeps the Pages source on "workflow". It was found on "legacy" on 2026-09-26, which made GitHub's branch build race the workflow deploy and took the site to 404 once. It writes with the repository secret `T7B_PAGES_ADMIN_TOKEN` (a tony7bones classic PAT, recorded in the owner's vault, never in this tree) and only warns when that secret is absent.

Note: pages.yml has NO path filter - every push to main builds and deploys (any tracked file can shape the artifact).

Retired 2026-09-26, later the same day: `.github/workflows/generate_repo.yml`
("Validate Kodi Repository"). It duplicated pages.yml's build job step for
step, and its only extra trigger was a branch (`modular-setup`) that does not
exist on the remote (`git ls-remote` shows `main` only). Deleted outright; the
alert workflow's list and the workflow tests were updated with it.

Retired 2026-09-26, both on the same day: the hosted release-freshness gate
(`check_hosted_release_sync.py`, which turned a stale hand-maintained mirror
into a red build after a 2h grace) and the mirror sync workflow
(`sync_hosted_mirror.yml` + `_tools/sync_hosted_mirror.py`, which bumped the
mirror by bot commit). Both existed to keep a committed version in step with
an upstream truth; with no committed version there is nothing for either to
check or bump. Do not reinstate a committed `addon.xml` for a build-resolved
entry, and do not add a gate that compares one.

**Rollback:** a bad canvas/tooling commit rolls back with `git revert` + push (CI redeploys). A bad ADD-ON release must roll FORWARD (new version bump) - reverting lowers the version and the version-bump gate rightly blocks it. NEVER flip the Pages source back to branch serving (`build_type=legacy`): main is sources-only and would serve a site with no /static/, no root index, and no installer.

## Architecture

### Source areas

| Path                    | Purpose                                                                                                                                                                                                                                                       |
| ----------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `addons/<addon-id>/`    | Any dir with an `addon.xml` is built into a zip and listed in `addons/addons.xml`. Currently `repository.tony7bones` ONLY, since the `script.ezmaintenanceplusplus` shim was deleted 2026-07-20.                                                              |
| `addons/hosted/<id>/`   | The seven third-party repository installers only (`addon.xml` + zip). Static, committed by hand, NOT zipped or indexed by the generator (`hosted` is the sole `_ADDONS_SPECIAL` entry). Our four add-ons and the eleven official-library modules have NO directory here: the build resolves them upstream (since 2026-09-26). |
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

Version gate: `check_versions.py`, `release_detect.py`, `release_lib.py`. Build/deploy: `generate_repo.py`, `build_site.py`, `static_catalog.py` (+ manifest `catalog.json`; it also owns `BUILTINS` and `OFFICIAL_LIBRARY`, the two import-walk exclusion sets, since 2026-09-26), `verify_live_site.py`, `check_site_secrets.py`, `secret_patterns.py`. Canvas + backup: `publish_canvas.py`, `sync_share.py`. Every module has a `test_<name>.py` beside it except `secret_patterns.py` (covered through its importers) and `release_lib.py` (covered through `test_check_versions.py`).

Deleted 2026-09-26, none with a caller left: `release.py` + `test_release.py` (see "Releasing"); `mirror_closure.py` (about 190 lines kept for two constants, its fetch code aimed at the Omega repo while the build uses Piers; the constants moved into `static_catalog.py`); `firetv.sh` and `provision-kodi.sh` (self-declared partly dead and "BROKEN, DO NOT RUN", no gate ran either; the meta-root `.claude/scripts/firetv-deploy.sh` is the live adb helper) with the provisioner's `.env.device.example` template; `make_custom_m3u.py` (no test, no caller; the IPTV builder it belonged to was extracted to the private `moquette/iptv` repo 2026-07-17, and the mini serves IPTV over the NFS share). Earlier: `check_hosted_release_sync.py` and `sync_hosted_mirror.py` (2026-09-26, morning), `build_iptv.py` (2026-07-17).

## Adding content

### Adding a new Kodi add-on

1. Create `addons/<addon-id>/addon.xml` following the Kodi addon.xml schema and add any source files.
2. Run `python3 _tools/generate_repo.py` (builds the zip, updates `addons.xml`).
3. `git add addons/<addon-id>/ addons/addons.xml addons/addons.xml.sha256 addons/addons.xml.md5`
4. Make sure its `addon.xml` carries a `version` (the bump gate compares every later change against it) and add its `_tools/catalog.json` entry, commit, push (CI builds and deploys the static site). In practice `repository.tony7bones` is the only add-on built here; see "Releasing".

### Serving a new official-library dependency

Never commit it. Add a `_tools/catalog.json` entry shaped exactly like `script.module.requests`'s (`asset_prefix` on our hosted prefix, zip template `https://mirrors.kodi.tv/addons/piers/{id}/{id}-{version}.zip`, `upstream_index` `https://mirrors.kodi.tv/addons/piers/addons.xml.gz`), bump the count pins in `_tools/test_static_catalog.py` and `_tools/test_closure.py`, and the build resolves it and walks its imports. An import the catalog does not serve fails the importing entry at build time (it falls back to last-good, `stale`), which is the signal to add the next entry.

### Adding a new repository installer zip

1. Drop the `.zip` into `dropbox/repositories/` (the canvas - the served copy is generated in CI).
2. Commit it (`publish_canvas.py -m "..."` does commit+push in one step); CI mirrors the canvas and regenerates the served `repositories/` listing on deploy.

## Playbooks + skills that still apply

> These carry the WHY and exact code locations. Read the matching one before acting.
>
> - `docs/playbooks/release-and-deploy.md` - the release flow + the static-CI-deploy pipeline + determinism, and how the sibling repos' releases reach `/static/` (build-time resolution since 2026-09-26).
> - `docs/playbooks/local-kodi-verification.md` - drive the real local Kodi; honest verification (prove non-empty `GetDirectory` + rendered menu, not just "no ImportError").
> - `docs/playbooks/kodi-install-mechanics.md` - install on Omega without blocking prompts (direct-extract + `SetAddonEnabled`, origin stamping, deps, platform binaries).
> - `docs/playbooks/kodi-settings-clobber.md` - the "Kodi clobbers direct settings writes" class and the two fix mechanisms.
> - `docs/playbooks/kodi-vfs-cannot-read-foreign-local-files.md` - Kodi's VFS can silently return empty reads for a local file a non-VFS writer produced.
> - `docs/playbooks/iptv-channel-customization.md` - the env-driven IPTV curation pipeline (the host `build_iptv.py` half; extracted to `moquette/iptv` 2026-07-17, kept here as historical reference).
> - `docs/playbooks/firetv-adb-dev.md` - HISTORICAL since 2026-09-26: the retired modv2plus add-on's adb loop; its generic adb and JSON-RPC mechanics still hold, the add-on steps do not.
> - `docs/playbooks/firetv-stick-scoped-storage-provisioning.md` - provisioning a non-rooted Fire OS 11 Stick over adb.
> - `docs/playbooks/mac-mini-media-server.md` - the `Mini` box that serves every Kodi client over NFS/SMB.
> - `.claude/skills/deploy/SKILL.md` - the release + deploy runbook.
> - `.claude/skills/kodi-super-agent/SKILL.md` - distilled agent operating guide.
> - `~/Code/moquette/kodi/.claude/skills/apple-tv/SKILL.md` - **THE Apple TV reference** (storage model, deploy traps, crash inventory). Section 0 is a dispatch index.
> - `docs/playbooks/modv2plus-dev-cycle-and-lessons.md` - the retired MOD V2+ patch; kept as a historical record of hard-won Kodi lessons.
> - `docs/incident-2026-07-15-proxy-engine-404-fleet-deadlock.md` and `docs/plans/` - historical records of the retired proxy architecture and the static conversion. Do not treat as current.
