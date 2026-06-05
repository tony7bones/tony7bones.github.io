# Tony.7.Bones Kodi Repository

A GitHub Pages site that hosts a Kodi **virtual** add-on repository. The site is
static — no bundler, no runtime; Python tooling under `_tools/` generates
everything.

The repository add-on, `repository.tony7bones`, is a **virtual repository** built
on [i96751414's `repository.github`](https://github.com/i96751414/repository.github)
engine: once installed in Kodi it runs a local HTTP proxy on `127.0.0.1:61234`
that streams add-on metadata and zips live from GitHub at runtime, driven by a
baked `repository.json` manifest. There are no committed per-add-on zips for the
third-party repos it lists.

---

## Install (end users)

The install URL is the site **root** and never changes:
`https://tony7bones.github.io/`

1. Kodi → **Settings → File Manager → Add source**. Enter
   `https://tony7bones.github.io/` and name it `.tony7.bones`.
2. Kodi → **Add-ons → Install from zip file → .tony7.bones →
   `repository.tony7bones-<version>.zip`**.
3. Then **Install from repository → Tony.7.Bones Repo** to browse and install
   add-ons, or run **Tony.7.Bones Setup** (below) for a one-tap build.

> Only the zip _filename_ carries the version (cache-busting). The base URL must
> never move — Kodi cannot follow a moving base URL.

## The add-ons

| Add-on                        | Name in Kodi                | What it is                                                                                                                                                                                  |
| ----------------------------- | --------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `repository.tony7bones`       | Tony.7.Bones Repo           | The virtual proxy repository (runs the local `127.0.0.1:61234` server).                                                                                                                     |
| `script.module.tony7bones`    | Tony.7.Bones Shared Library | Python LIBRARY (`xbmc.python.module`) — the shared install machinery. Invisible on the home screen.                                                                                         |
| `script.tony7bones.bootstrap` | Tony.7.Bones Setup          | One-tap base setup (12 repos + base apps), with an optional front-loaded video step. Self-uninstalls after running.                                                                         |
| `script.tony7bones.video`     | Video Add-ons Setup         | Pick-and-install video add-ons (POV, The Loop, Sports HD, Umbrella). Self-uninstalls after running.                                                                                         |
| `script.tony7bones.modv2plus` | Estuary MOD V2+             | Patch for `skin.estuary.modv2`: gear-menu reorder, a "Tony.7.Bones MOD V2+" settings category with per-item toggles, crisp white nav logo, thin clock, Outline HD weather. Apply / Restore. |

### One-tap setup

Install and run **Tony.7.Bones Setup** from the repo. It front-loads two prompts
(optionally also install video add-ons → multiselect), then runs unattended:
installs the base repos + apps and (if chosen) the video apps with their full
dependency closures, stamps each add-on's source repo, adds file-manager sources,
trims the Estuary home menu, shows one summary, self-uninstalls, and restarts
once. See `docs/playbooks/one-shot-and-architecture.md`.

## Architecture (developers)

### Single branch — `main` only

Everything lives on `main`, served by GitHub Pages: the root installer zip(s),
`index.html`, the static browsable area under `repo/`, the proxy add-on source at
`repo/repository.tony7bones/`, the first-party add-ons, the mirrored
third-party-repo trees under `repo/hosted/<id>/`, and all of `_tools/`. **The
proxy fetches everything from `main`** via raw.githubusercontent.

> The old `virtual-repo` branch is retired (its `hosted/<id>/` trees moved to
> `repo/hosted/`, and the proxy's self-update source was consolidated into the
> main `addon.xml`). It may linger as a fallback but is unreferenced.

### How the virtual proxy serves add-ons

The proxy reads a **baked** `resources/repository.json` from inside the installed
add-on (`lib/service.py`), not `repo/addons.xml`. It serves the listed add-ons
from its local server, streaming zips from GitHub. To change what the repo serves,
edit the single `repository.json` at `repo/repository.tony7bones/resources/` (drop
any mirrored third-party `addon.xml`/zip under `repo/hosted/<id>/`) and release the
repo add-on.

### Content areas under `repo/`

| Path                                     | Purpose                                                                                                        |
| ---------------------------------------- | -------------------------------------------------------------------------------------------------------------- |
| `repo/<addon-id>/`                       | Any dir with an `addon.xml` becomes a zip and is listed in `addons.xml` (the first-party add-ons + the proxy). |
| `repo/repositories/`                     | Third-party repository installer zips (Kodi installs them manually).                                           |
| `repo/scripts/`                          | One-shot script zips (installed manually).                                                                     |
| `repo/hosted/<id>/`                      | Mirrored third-party-repo trees the proxy fetches from `main` (not auto-indexed/zipped).                       |
| `repo/media/`, `repo/iptv/`, `repo/rss/` | Assets auto-indexed for file-manager browsing.                                                                 |

### Generated files (must be committed)

`generate_repo.py` produces `repo/addons.xml(.sha256/.md5)`, the per-addon
`index.html` + zips, and the `repositories/`, `scripts/`, `media/` index pages.
Run it after any source change and commit the output — CI fails on stale output.

## Develop & release

```bash
python3 _tools/generate_repo.py     # regenerate addons.xml, zips, index pages
python3 -m pytest _tools/ -q        # tests
ruff check _tools/                  # lint
git config core.hooksPath .githooks # install the pre-push gate (once after clone)
```

Two release paths (full detail in `docs/playbooks/release-and-deploy.md`):

- **`script.*` / `script.module.*` add-on** — bump its `addon.xml` version,
  `generate_repo.py`, commit, `git push`. NOT `deploy.py`.
- **`repository.tony7bones`** — `python3 _tools/deploy.py --news "…"`. It bumps
  the version in four locations on `main` (the main `addon.xml` doubles as the
  proxy self-update source), builds deterministically, commits + tags, pushes
  `main` + tag, forces a Pages build, and verifies live.

The pre-push hook blocks a push unless tests pass, lint is clean, generated files
are fresh, every changed add-on bumped its version, and the version locations on
main agree and are tagged.

## Documentation

- `docs/playbooks/kodi-install-mechanics.md` — how Setup installs add-ons on Omega
  (no blocking prompts, origins, optional/required deps, binaries, self-uninstall).
- `docs/playbooks/release-and-deploy.md` — the two release paths + the Pages gotcha.
- `docs/playbooks/local-kodi-verification.md` — driving the real local Kodi; honest
  verification.
- `docs/playbooks/one-shot-and-architecture.md` — the three-add-on architecture and
  the one-shot flow.
- `docs/playbooks/modv2plus-dev-cycle-and-lessons.md` — the MOD V2+ patch: the
  ADB-on-real-Fire-TV development cycle + hard-won lessons.
- `docs/playbooks/firetv-adb-dev.md` — driving the Fire TV over ADB + JSON-RPC
  (`_tools/firetv.sh`).
- `docs/plans/` — historical design docs (implemented).
- `.claude/skills/kodi-super-agent/SKILL.md` — agent operating guide.
