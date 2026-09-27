# Tony.7.Bones Kodi Repository

A GitHub Pages site that hosts a **static** Kodi add-on repository. The site is
static: no bundler, no runtime, no on-box service. Python tooling under `_tools/`
generates and deploys everything.

The repository add-on, `repository.tony7bones` (version 3.0.0), is a **normal
static-only repository add-on**. Its `addon.xml` declares a single `<dir>`
pointing at the static catalog on GitHub Pages
(`https://tony7bones.github.io/static/addons.xml` + `.md5` + datadir). Once
installed, Kodi reads add-on metadata and zips directly from that static tree as
plain files. There is no local proxy, no `xbmc.service`, and no engine.

---

## Install (end users)

The install URL is the site **root** and never changes:
`https://tony7bones.github.io/`

1. Kodi -> **Settings -> File Manager -> Add source**. Enter
   `https://tony7bones.github.io/` and name it `.tony7.bones`.
2. Kodi -> **Add-ons -> Install from zip file -> .tony7.bones ->
   `repository.tony7bones-<version>.zip`**.
3. Then **Install from repository -> Tony.7.Bones repository** to browse and
   install add-ons.

> Only the zip _filename_ carries the version (cache-busting). The base URL must
> never move; Kodi cannot follow a moving base URL.

> The bare URL `https://tony7bones.github.io/` shows exactly the owner's
> hand-authored canvas: `repositories/ media/ iptv/ rss/` plus the install zip,
> a 1:1 mirror of `dropbox/` (see Architecture below).

## The add-ons

The one add-on dir under `addons/` is `repository.tony7bones` (Tony.7.Bones
repository, 3.0.0): the static-only repository add-on that points Kodi at
`https://tony7bones.github.io/static/`. No service, no proxy. Its version is
read live from `addons/repository.tony7bones/addon.xml`.

The served catalog (`/static/`) currently lists 28 entries (four Estuary 7/8
entries were removed 2026-08-31 when both skins were decommissioned): the
repository add-on, the seven third-party repository installers under
`addons/hosted/<id>/`, OUR own add-ons and the eleven official-library modules
their dependency closures reach. Neither ours nor the modules have a copy in
this repo at all. Since 2026-09-26 the build resolves each of them from its
source of truth on every run and takes `addon.xml` and art out of the zip
(`_tools/static_catalog.py`):

- **`script.ezmaintenanceplusplus`** ("EZ Maintenance++") - a VFS-safe fork of EZ
  Maintenance+ (backup/restore over NFS/SMB/Dropbox), source at
  `~/Code/moquette/kodi/ezmpp` (`moquette/kodi-ezmpp`, public). Resolved from
  that repo's latest GitHub release `v<version>`. Backup/restore triage on
  tvOS: `~/Code/moquette/kodi/.claude/skills/apple-tv/SKILL.md`.
- **`skin.estuary.plusplus`** ("Estuary++") and **`service.tvos.pythonfix`**
  ("Apple TV Fixes") - source at `~/Code/kodi/estuary-plusplus`
  (`moquette/kodi-estuary-plusplus`, public). Resolved from the newest release
  in each add-on's tag namespace, `<id>-v<version>`. The skin's old id
  `skin.estuary.pov` (1.4.4, same repo) is served only while the boxes
  migrate to the new id (rename plan, 2026-09-26) and is retired in stage E.
- **`plugin.video.pov`** (not ours) - version read from upstream's own
  `packages/addons.xml`, zip republished from the upstream Pages host.
- **The eleven official-library modules** (not ours: `plugin.program.autocompletion`,
  `script.image.resource.select`, `script.module.autocompletion`, `certifi`,
  `chardet`, `idna`, `requests`, `simplecache`, `simpleeval`, `unidecode`,
  `urllib3`) - version read from the official Kodi repository's Piers index
  (`mirrors.kodi.tv/addons/piers/addons.xml.gz`, fetched once per build), zip
  republished from the official mirror. Served here because Kodi resolves a hard
  dependency only from the repository the add-on is installed FROM.

Fix bugs and add tests in the sibling repos. A version bump pushed to their
`main` is the release: their CI publishes the GitHub release and dispatches
this hub, whose Pages build resolves the new version. Nothing is bumped here.

## Architecture (developers)

### Single branch - `main` only

Everything lives on `main`, served by GitHub Pages: the generated root
`index.html`, the served canvas (`repositories/ media/ iptv/ rss/`, mirrored 1:1
from `dropbox/`), the add-on tree under `addons/` (add-on source, built per-addon
zips, `addons.xml`, and the mirrored third-party-repo trees under
`addons/hosted/<id>/`), and all of `_tools/`. Neither our own add-ons nor their
dependencies have a directory under `addons/hosted/` (since 2026-09-26; see
"The add-ons"); only the seven third-party repository installers do.

### The `dropbox/` canvas and the bare URL

`dropbox/` is the owner's **pristine human canvas**: it holds ONLY hand-authored
installable content (`repositories/` third-party repo installer zips and `rss/`)
and NEVER any generated files. The build mirrors `dropbox/` 1:1 to the repo
ROOT, which is what GitHub Pages serves at the bare URL. Pointing Kodi's File
Manager at the bare URL shows exactly the canvas plus the install zip and a
generated `index.html` per folder. The mirror honors `.gitignore`, so
gitignored local files are never copied into the served tree.
(`media/`, `zips/`, and `iptv/` retired from the canvas 2026-07-16: everything
private or generated lives on the KodiShare, reachable only via LAN/Tailscale -
the public site serves `repositories/` and `rss/` only.)

### The static catalog (`/static/`)

The served `/static/` tree is the Kodi repository the add-on points at:
`/static/addons.xml` + `.md5` + per-add-on zips + materialized art. It is built
in CI by `_tools/build_site.py` -> `_tools/static_catalog.py` from the manifest
`_tools/catalog.json`, then deployed via GitHub Pages. To change what the repo
serves, edit `_tools/catalog.json` (and, for a mirrored third-party repository
installer only, drop its `addon.xml`/zip under `addons/hosted/<id>/`; an add-on
of ours or an official-library module is never committed, the build resolves
it from its release or from the official index).

### Source areas

| Path                    | Purpose                                                                                                                                                                                                                           |
| ----------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `addons/<addon-id>/`    | Any dir with an `addon.xml` is built into a zip and listed in `addons.xml`.                                                                                                                                                       |
| `addons/hosted/<id>/`   | The seven third-party repository installers (not auto-indexed/zipped). No entry for our own add-ons or their dependencies: the build resolves those from their releases and from the official Kodi index.                    |
| `dropbox/repositories/` | Third-party repository installer zips (Kodi installs them manually). Mirrored to the served `/repositories/`.                                                                                                                     |
| `dropbox/rss/`          | Hand-authored assets. Mirrored to the served root and auto-indexed for file-manager browsing. (`dropbox/media/` and `dropbox/iptv/` retired 2026-07-16; private/generated content lives only on the KodiShare via LAN/Tailscale.) |

### Generated files (must be committed)

`generate_repo.py` produces `addons/addons.xml(.sha256/.md5)` and the per-addon
`index.html` + current-version zip (superseded zips are pruned). The served
canvas mirror, root `index.html`, and `robots.txt` are generated in CI by
`build_site.py` and never committed. Run the generator after any source change
and commit the output; CI fails on stale output.

## Develop & release

```bash
python3 _tools/generate_repo.py     # regenerate addons.xml, zips, index pages
python3 -m pytest _tools/ -q        # tests (209, all green, 9s; measured 2026-09-26)
ruff check _tools/                  # lint
python3 _tools/build_site.py --out _site   # build the full served site (incl. /static/)
git config core.hooksPath .githooks # install the pre-push gate (once after clone)
```

The only add-on released from here is `repository.tony7bones`; everything
else the hub serves is resolved at build time from a sibling repo's release
or an upstream index. To release it: raise the `version` and prepend a
`<news>` line in `addons/repository.tony7bones/addon.xml`, run
`python3 _tools/generate_repo.py`, commit source and generated output
together, push `main`. CI builds and deploys the static site via GitHub Pages.
The bump is enforced by `check_versions.py` in the pre-push hook and in CI
(the automatic `release.py` was deleted 2026-09-26). Full detail:
`docs/playbooks/release-and-deploy.md`.

The pre-push hook blocks a push unless tests pass, lint is clean, generated files
are fresh, and every changed add-on bumped its version. One push workflow and
two backstops, none of which commits to main: `pages.yml` runs those same
source gates on push, then builds + deploys + verifies live (on push, daily,
and on the `ezmpp-release` dispatch a sibling repo sends when it publishes;
the cron and dispatch runs skip the source gates, since no hub source
changed); `ci_failure_alert.yml` opens an issue assigned to the owner on a
red run and closes it on the next green; `pages_source_guard.yml` keeps the
Pages source on "workflow". All on `ubuntu-26.04`.

## Documentation

- `docs/playbooks/release-and-deploy.md` - the release flow + the static-CI-deploy
  pipeline + determinism.
- `docs/playbooks/kodi-install-mechanics.md` - installing add-ons on Omega without
  blocking prompts (origins, optional/required deps, binaries).
- `docs/playbooks/local-kodi-verification.md` - driving the real local Kodi; honest
  verification.
- `docs/playbooks/firetv-adb-dev.md` - historical since 2026-09-26 (the retired
  modv2plus add-on's adb loop); the generic adb mechanics still hold.
- `docs/playbooks/firetv-stick-scoped-storage-provisioning.md` - provisioning a
  non-rooted Fire OS 11 Stick over ADB.
- `~/Code/moquette/kodi/.claude/skills/apple-tv/SKILL.md` - the Kodi storage
  model on tvOS and the EZ Maintenance++ backup/restore triage that lives with
  it (the `kodi-storage-map` and `ezm-backup-doctor` skills were deleted
  2026-07-21; EZM++ source is in `moquette/kodi-ezmpp`, not here).
- `.claude/skills/deploy/SKILL.md` - the release + deploy runbook.
- `.claude/skills/kodi-super-agent/SKILL.md` - agent operating guide.
- `docs/plans/` and the `docs/incident-*` writeups - historical records (the
  retired proxy architecture, the static conversion). Not current.
