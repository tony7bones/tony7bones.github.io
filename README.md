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

Current shipped versions are read live from the manifests (`grep version=
addons/<id>/addon.xml`). The two add-on dirs under `addons/` are:

| Add-on                         | Name in Kodi            | What it is                                                                                                              |
| ------------------------------ | ----------------------- | ----------------------------------------------------------------------------------------------------------------------- |
| `repository.tony7bones`        | Tony.7.Bones repository | The static-only repository add-on (3.0.0). Points Kodi at `https://tony7bones.github.io/static/`. No service, no proxy. |
| `script.ezmaintenanceplusplus` | EZ Maintenance++        | A **hosted metadata mirror** (`addon.xml` + icon/fanart only). Real source lives in `moquette/ezmaintenanceplusplus`.   |

The served catalog (`/static/`) currently lists 28 entries (four Estuary 7/8
entries were removed 2026-08-31 when both skins were decommissioned): the two
above, the mirrored third-party repos under `addons/hosted/<id>/`, and OUR own
add-ons hosted there with their source in a sibling repo, among them:

- **`script.ezmaintenanceplusplus`** ("EZ Maintenance++") - a VFS-safe fork of EZ
  Maintenance+ (backup/restore over NFS/SMB/Dropbox), built at
  `~/Code/moquette/kodi/ezmpp` (public, its own repo since 2026-07-14).
  See `~/Code/moquette/kodi/.claude/skills/ezm-backup-doctor/SKILL.md`.

Fix bugs and add tests in those sibling repos; only bump the hosted metadata +
release here.

## Architecture (developers)

### Single branch - `main` only

Everything lives on `main`, served by GitHub Pages: the generated root
`index.html`, the served canvas (`repositories/ media/ iptv/ rss/`, mirrored 1:1
from `dropbox/`), the add-on tree under `addons/` (add-on source, built per-addon
zips, `addons.xml`, and the mirrored third-party-repo trees under
`addons/hosted/<id>/`), and all of `_tools/`.

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
serves, edit `_tools/catalog.json` (and, for a mirrored third-party repo, drop
its `addon.xml`/zip under `addons/hosted/<id>/`).

### Source areas

| Path                    | Purpose                                                                                                                                                                                                                           |
| ----------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `addons/<addon-id>/`    | Any dir with an `addon.xml` is built into a zip and listed in `addons.xml`.                                                                                                                                                       |
| `addons/hosted/<id>/`   | Mirrored third-party-repo trees (not auto-indexed/zipped); includes the EZM++ metadata mirror.                                                                                                                        |
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
python3 -m pytest _tools/ -q        # tests (237, all green; verified 2026-07-19)
ruff check _tools/                  # lint
python3 _tools/build_site.py --out _site   # build the full served site (incl. /static/)
git config core.hooksPath .githooks # install the pre-push gate (once after clone)
```

`python3 _tools/release.py` is THE release command for **every** add-on,
including `repository.tony7bones`. It detects what changed vs `origin/main`,
minor-bumps it, drafts + prepends the news, regenerates, runs the gates, and
commits on the branch (`--push` is opt-in; `--dry-run` previews the plan). On
push, CI builds and deploys the static site via GitHub Pages. No hand-edited
`addon.xml`, no hand-written `<news>`. Full detail:
`docs/playbooks/release-and-deploy.md`.

The pre-push hook blocks a push unless tests pass, lint is clean, generated files
are fresh, and every changed add-on bumped its version. Two CI workflows
(`generate_repo.yml` validates; `pages.yml` builds + deploys + verifies live)
back it up and never commit to main.

## Documentation

- `docs/playbooks/release-and-deploy.md` - the release flow + the static-CI-deploy
  pipeline + determinism.
- `docs/playbooks/kodi-install-mechanics.md` - installing add-ons on Omega without
  blocking prompts (origins, optional/required deps, binaries).
- `docs/playbooks/local-kodi-verification.md` - driving the real local Kodi; honest
  verification.
- `docs/playbooks/firetv-adb-dev.md` - driving a Fire TV over ADB + JSON-RPC
  (`_tools/firetv.sh`).
- `docs/playbooks/firetv-stick-scoped-storage-provisioning.md` - provisioning a
  non-rooted Fire OS 11 Stick over ADB.
- `~/Code/moquette/kodi/.claude/skills/kodi-storage-map/SKILL.md` - the
  authoritative Kodi storage model per OS.
- `~/Code/moquette/kodi/.claude/skills/ezm-backup-doctor/SKILL.md` - triage guide
  for EZ Maintenance++ (source in `moquette/ezmaintenanceplusplus`, not here).
- `.claude/skills/deploy/SKILL.md` - the release + deploy runbook.
- `.claude/skills/kodi-super-agent/SKILL.md` - agent operating guide.
- `docs/plans/` and the `docs/incident-*` writeups - historical records (the
  retired proxy architecture, the static conversion). Not current.
