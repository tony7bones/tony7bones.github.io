# Strategy review: `i96751414/repository.github` vs. this repo

_Date: 2026-06-03 · Scope: comparative review + a prototype of the hybrid path._

## TL;DR

Both projects distribute Kodi add-ons but with **opposite architectures**:

- **This repo (`tony7bones.github.io`)** — a **static, build-ahead-of-time** model.
  `_tools/generate_repo.py` pre-generates zips + `addons.xml`, which are committed
  and served over GitHub Pages / `raw.githubusercontent.com`.
- **`i96751414/repository.github`** — a **dynamic, resolve-at-runtime virtual
  repository**. A Kodi add-on runs a tiny local HTTP server that synthesizes
  `addons.xml` and streams zips straight from GitHub releases/branches on demand.

Recommendation: **a targeted hybrid, not a migration.** Borrow their *declarative,
GitHub-sourced* idea while keeping our static serving model. A working prototype of
that idea ships alongside this doc — see [The prototype](#the-prototype).

## How each one works

| | This repo | `repository.github` |
|---|---|---|
| Model | Static site, pre-built artifacts | Virtual repo, runtime-generated |
| Who builds zips | `generate_repo.py`, run by human/CI | The add-on itself, on the user's Kodi box |
| Source of truth | Files committed under `repo/` | A `repository.json` pointing at GitHub repos |
| `addons.xml` | Generated file, committed | Synthesized in-memory, served at `/addons.xml` |
| Hosting | GitHub Pages / `raw.githubusercontent.com` | Local HTTP server inside Kodi |
| Update flow | Edit source → run generator → commit → push | Hit `/update`; it re-reads GitHub |
| Versioning | Bump `version=` in `addon.xml` by hand | Resolved: release commit → tag → default branch → `main` |
| Config | Directory layout under `repo/` | One JSON file: `id`, `username`, `assets`, `tag_pattern`, `platforms`, `token`… |

Their endpoints: `/addons.xml`, `/addons.xml.md5`, `/{addon_id}/{asset_path}`, and
`/update` (refreshes entries + clears cache). Their `repository.json` supports template
variables (`{username}`, `{repository}`, `{ref}`, `{version}`, `{system}`, `{arch}`) and
**per-platform binaries** — genuinely powerful for native add-ons.

## Our points of friction

1. **Manual regeneration is a footgun.** The whole `generate_repo.py` + pre-commit +
   CI apparatus exists only because zips and `addons.xml` are committed artifacts that
   drift from source. Their model deletes this entire class of problem.
2. **Hand-managed version bumps.** We edit `version=` in each `addon.xml` by hand
   (e.g. `repository.tony7bones` at v1.0.5). Theirs derives it from releases/tags.
3. **Storage duplication.** We store an add-on's *source* (`repo/<id>/…`), a committed
   *zip* of it, and a second copy under `_tools/repo-sources/` — the same bytes 2–3×.
4. **Documentation drift (found during review):**
   - `CLAUDE.md`/`README.md` say the canonical source URL is
     `https://tony7bones.github.io/repo`, but `addon.xml` (live + `repo-sources` master)
     points `info`/`checksum`/`datadir` at `raw.githubusercontent.com/.../main/repo/`.
   - `CLAUDE.md` says "CI never commits anything back to main," but
     `.github/workflows/generate_repo.yml` **does** auto-commit & push stale output.
5. **`<hashes>false</hashes>`.** Hash verification is disabled to make the static
   setup behave; their `/addons.xml.md5` flow keeps integrity checking working.

## What we'd gain from their approach

- No build step, no staleness CI, no committed binaries — the biggest maintenance win.
- Automatic version tracking from releases/tags.
- Per-platform binary distribution (`platforms` + `{system}`/`{arch}`).
- Private-repo support via `token`.
- `/update` cache-busting so users pull new versions without a repo re-publish.

## What we'd lose / what doesn't fit

- Their model needs add-ons to live in **their own GitHub repos with releases.** Our
  first-party add-ons (`script.tony7bones.bootstrap`, `…modv2.patch`) are small in-tree
  scripts with no separate repos or tags. _(Decision 2026-06-03: keep them in-tree for
  now, revisit splitting later.)_
- **It only helps plugin add-ons.** A large fraction of this repo is **not** add-ons:
  `repo/repositories/` (13 third-party installer zips), `repo/scripts/`, `repo/media/`,
  `repo/rss/`, `repo/iptv/`, plus `misc/` m3u tooling. The virtual-repo model says
  nothing about any of that — `generate_repo.py`'s asset indexing stays necessary.
- Runtime dependency on GitHub reachability from each Kodi client and on the
  virtual-repo add-on itself. Our static files work behind any CDN/mirror.
- Loss of the human-browsable styled site (`style.css`, per-area index pages).

## Recommendation — a targeted hybrid

Don't replace the static repo. Borrow the ideas that kill our worst friction:

1. **Declarative, GitHub-sourced add-ons resolved at generate time.** Adopt their
   `repository.json` *concept*: describe an external add-on by its GitHub coordinates,
   let tooling resolve the version + zip and emit committed artifacts — exactly like
   in-tree add-ons. This is what the prototype below does.
2. **Stop committing first-party zips eventually; build them at publish time.** Keep
   sources in-tree, generate zips in CI as a Pages artifact instead of committing them.
   (Third-party `repositories/` zips stay committed — we don't own their sources.)
3. **Quick wins, independent of the above:** fix the two doc/impl mismatches in
   friction #4 and reconsider re-enabling `<hashes>`.

## The prototype

`_tools/external_addons.py` implements idea #1 as an **opt-in, fully-tested** module:

- Reads a manifest (`_tools/external-addons.json`; schema in
  `_tools/external-addons.example.json`) describing add-ons by GitHub coordinates.
- Resolves the latest release/tag → version, derives the zip URL via template
  substitution (`{username}`, `{repository}`, `{version}`, `{tag}`, `{ref}`), and fetches
  the remote `addon.xml` to build an `addons.xml` entry — the same `<addon>` element our
  in-tree pipeline produces.
- Network access is injected, so the test suite (`_tools/test_external_addons.py`) runs
  fully offline with fake fetchers.
- **Off by default:** with no manifest file present it is a no-op, so
  `generate_repo.py`'s committed output stays byte-identical and CI stays green. It is
  wired into `generate()` behind that guard, so dropping in a manifest is all it takes
  to opt in.

Usage:

```bash
# Dry run — resolve + print what would be emitted, write nothing
python3 _tools/external_addons.py

# Resolve, download zips into repo/<id>/, and write per-addon indexes
python3 _tools/external_addons.py --write
```

### Why this is the right first step

It proves the highest-value borrowed idea (declarative GitHub-sourced add-ons) end to
end, without destabilising the live static pipeline and without requiring our own
add-ons to move repos. When/if first-party add-ons are split into their own repos, the
same manifest path absorbs them with no new machinery.
