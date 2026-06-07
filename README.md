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

> The bare URL `https://tony7bones.github.io/` shows exactly the owner's
> hand-authored canvas: `repositories/ media/ iptv/ rss/` plus the install zip —
> a 1:1 mirror of `dropbox/` (see Architecture below).

## The add-ons

Current shipped versions: `repository.tony7bones` 2.2.1 · `script.tony7bones.bootstrap`
1.3.0 · `script.tony7bones.modv2plus` 1.4.0 · `script.module.tony7bones` 1.1.0.

| Add-on                        | Name in Kodi                | What it is                                                                                                                                                                                                                                                                     |
| ----------------------------- | --------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `repository.tony7bones`       | Tony.7.Bones Repo           | The virtual proxy repository (runs the local `127.0.0.1:61234` server).                                                                                                                                                                                                        |
| `script.module.tony7bones`    | Tony.7.Bones Shared Library | Python LIBRARY (`xbmc.python.module`) — the shared install machinery. Invisible on the home screen.                                                                                                                                                                            |
| `script.tony7bones.bootstrap` | Tony.7.Bones Setup          | One-tap base setup (12 repos + base apps + curated video add-ons + the Estuary MOD V2 skin), unattended. Self-uninstalls after running.                                                                                                                                        |
| `script.tony7bones.modv2plus` | Estuary MOD V2+             | Patch for `skin.estuary.modv2`: gear-menu reorder, a "Tony.7.Bones MOD V2+" settings category with per-item toggles, crisp white nav logo, thin clock, Outline HD weather. A boot service auto-applies the patch when MOD V2 is active; manual Apply / Restore also available. |

### One-tap setup

Install and run **Tony.7.Bones Setup** from the repo. One run on a fresh Kodi
produces the complete box — it runs fully unattended (no prompts, no picker) and:

- installs the base repos + base apps plus a curated set of video add-ons (POV,
  The Loop, Sports HD, YouTube) with their full dependency closures, stamping each
  add-on's source repo;
- installs **and activates** the Estuary MOD V2 skin (the MOD V2+ patch
  auto-applies on the next start via its boot service — no hand step);
- adds file-manager sources, trims the Estuary home menu, sets weather/RSS/top-bar
  preferences, copies any user-placed device files;
- shows one summary, self-uninstalls, then restarts once.

On desktop Kodi the restart is automatic. On Fire TV / Android, Kodi cannot
self-restart, so Setup prompts the user to close Kodi and reopen it; on reopen MOD
V2 is the active skin and the modv2plus service applies the patch. See
`docs/playbooks/one-shot-and-architecture.md`.

## Architecture (developers)

### Single branch — `main` only

Everything lives on `main`, served by GitHub Pages: the root installer zip(s),
the generated root `index.html`, the served canvas (`repositories/ media/ iptv/
rss/`, mirrored 1:1 from `dropbox/`), the add-on tree under `addons/` (first-party
add-on source, the proxy source at `addons/repository.tony7bones/`, built per-addon
zips, `addons.xml`, and the mirrored third-party-repo trees under
`addons/hosted/<id>/`), and all of `_tools/`. **The proxy fetches add-on metadata
and zips from `main`** via raw.githubusercontent (`.../main/addons/...`).

> The old `virtual-repo` branch is retired (its `hosted/<id>/` trees moved to
> `addons/hosted/`, and the proxy's self-update source was consolidated into the
> main `addon.xml`). It may linger as a fallback but is unreferenced.

### The `dropbox/` canvas and the bare URL

`dropbox/` is the owner's **pristine human canvas** — it holds ONLY hand-authored
installable content (`repositories/` third-party repo installer zips, `media/`,
`iptv/`, `rss/`) and NEVER any generated files (no `index.html`, no checksums).
The build mirrors `dropbox/` 1:1 to the repo ROOT, which is what GitHub Pages
serves at the bare URL `https://tony7bones.github.io/`. So pointing Kodi's File
Manager at the bare URL shows exactly the canvas: `repositories/ media/ iptv/
rss/` plus the install zip and a generated `index.html` per folder. The mirror
honors `.gitignore`, so secrets (e.g. `dropbox/iptv/instance-settings*.xml`) are
kept locally and never copied into the served tree.

### How the virtual proxy serves add-ons

The proxy reads a **baked** `resources/repository.json` from inside the installed
add-on (`lib/service.py`), not `addons/addons.xml`. It serves the listed add-ons
from its local server, streaming zips from GitHub. To change what the repo serves,
edit the single `repository.json` at `addons/repository.tony7bones/resources/`
(drop any mirrored third-party `addon.xml`/zip under `addons/hosted/<id>/`) and
release the repo add-on.

### Source areas

| Path                                              | Purpose                                                                                                           |
| ------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------- |
| `addons/<addon-id>/`                              | Any dir with an `addon.xml` is built into a zip and listed in `addons.xml` (the first-party add-ons + the proxy). |
| `addons/hosted/<id>/`                             | Mirrored third-party-repo trees the proxy fetches from `main` (not auto-indexed/zipped).                          |
| `dropbox/repositories/`                           | Third-party repository installer zips (Kodi installs them manually). Mirrored to the served `/repositories/`.     |
| `dropbox/media/`, `dropbox/iptv/`, `dropbox/rss/` | Hand-authored assets. Mirrored to the served root and auto-indexed for file-manager browsing.                     |

### Generated files (must be committed)

`generate_repo.py` produces `addons/addons.xml(.sha256/.md5)`, the per-addon
`index.html` + zips, the served canvas mirror at the repo root (the `repositories/
media/ iptv/ rss/` copies with a Kodi index per folder), and the root `index.html`
(the bare-URL canvas listing). Run it after any source change and commit the output
— CI fails on stale output.

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
  the version, syncing all four version-bearing locations on `main` — the main
  `addon.xml` (which doubles as the proxy self-update source), the root install
  zip filename, the root `index.html` link (now produced by the generator, not a
  separate rewrite), and the git tag — builds deterministically, commits + tags,
  pushes `main` + tag, forces a Pages build, and verifies live.

The pre-push hook blocks a push unless tests pass, lint is clean, generated files
are fresh, every changed add-on bumped its version, and the version locations on
main agree and are tagged.

## Documentation

- `docs/playbooks/kodi-install-mechanics.md` — how Setup installs add-ons on Omega
  (no blocking prompts, origins, optional/required deps, binaries, self-uninstall).
- `docs/playbooks/release-and-deploy.md` — the two release paths + the Pages gotcha.
- `docs/playbooks/local-kodi-verification.md` — driving the real local Kodi; honest
  verification.
- `docs/playbooks/one-shot-and-architecture.md` — the first-party add-on
  architecture and the one-shot flow.
- `docs/playbooks/modv2plus-dev-cycle-and-lessons.md` — the MOD V2+ patch: the
  ADB-on-real-Fire-TV development cycle + hard-won lessons.
- `docs/playbooks/firetv-adb-dev.md` — driving the Fire TV over ADB + JSON-RPC
  (`_tools/firetv.sh`).
- `docs/plans/` — historical design docs (implemented).
- `.claude/skills/kodi-super-agent/SKILL.md` — agent operating guide.
