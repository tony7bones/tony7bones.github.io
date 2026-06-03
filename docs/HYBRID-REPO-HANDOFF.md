# Hybrid Repo — Handoff & Working Notes

> **Purpose of this file.** A self-contained context dump so a fresh Claude Code
> session (running locally on the maintainer's desktop) can pick up exactly where
> the cloud session left off. Read this top-to-bottom before touching code.
>
> **Branch:** `hybrid-repo` (created from `claude/hello-jxdcr` @ commit `a5de055`).
> **Companion doc:** `docs/repository-github-strategy-review.md` — the full
> comparative analysis. This file is the *operational* handoff; that file is the
> *reasoning*.

---

## 1. The idea in one paragraph

We maintain a **static** Kodi add-on repository (`tony7bones.github.io`): a Python
generator (`_tools/generate_repo.py`) pre-builds zips + `addons.xml`, which are
committed and served over GitHub Pages / `raw.githubusercontent.com`. We reviewed
**`i96751414/repository.github`**, which solves the same problem the opposite way —
a Kodi add-on that runs a local HTTP server and synthesizes the repository at
**runtime** from a declarative `repository.json` pointing at GitHub repos. The plan
is **not** to migrate, but to **borrow their declarative, GitHub-sourced model** and
run it at **our** generate time, emitting static artifacts as we already do. A
working, opt-in prototype of that hybrid already exists on this branch.

---

## 2. The referenced repo — `i96751414/repository.github`

- **URL:** https://github.com/i96751414/repository.github
- **What it is:** a Kodi add-on ("GitHub virtual repository") that removes the need
  for a dedicated add-on storage repo. It dynamically generates add-on packages from
  existing GitHub repositories.
- **How it works:** runs an HTTP server inside Kodi exposing four endpoints:
  | Endpoint | Purpose |
  |---|---|
  | `/addons.xml` | Main manifest, synthesized in-memory |
  | `/addons.xml.md5` | Checksum for integrity verification |
  | `/{addon_id}/{asset_path}` | Serves add-on zips/assets dynamically |
  | `/update` | Refreshes entries and clears cached data |
- **Config:** a JSON list (`resources/repository.json`). Per-entry fields:
  - **Required:** `id` (add-on id), `username` (GitHub owner)
  - **Optional:** `repository` (defaults to `id`), `branch`, `assets` (dict; `zip` is
    special), `asset_prefix`, `tag_pattern`, `token` (private repos), `platforms`.
  - **Template variables:** `{username}`, `{repository}`, `{ref}`, `{version}`,
    `{system}`, `{arch}` — substituted at resolve time. `platforms` + `{system}`/`{arch}`
    enable **per-platform native binaries** (e.g. `plugin.video.torrest`).
- **Version resolution (their hierarchy):** latest release commit → matching tag →
  default branch → `main` fallback.
- **Their example `repository.json`:**
  ```json
  [
    {
      "id": "repository.github",
      "username": "i96751414",
      "asset_prefix": "https://raw.githubusercontent.com/{username}/{repository}/{ref}/",
      "assets": {
        "zip": "https://github.com/{username}/{repository}/archive/v{version}.zip"
      }
    }
  ]
  ```

---

## 3. Static vs. virtual — the architecture contrast

| | This repo (static) | `repository.github` (virtual) |
|---|---|---|
| Model | Build ahead of time | Resolve at runtime |
| Who builds zips | `generate_repo.py` (human/CI) | The add-on, on the Kodi box |
| Source of truth | Files under `repo/` | `repository.json` → GitHub repos |
| `addons.xml` | Generated + committed | Synthesized in-memory |
| Hosting | GitHub Pages / raw.githubusercontent | Local HTTP server in Kodi |
| Update flow | edit → generate → commit → push | hit `/update` |
| Versioning | hand-bump `version=` in `addon.xml` | resolved from releases/tags |
| Non-addon assets (repositories/scripts/media/iptv/rss) | first-class, indexed | not handled |

---

## 4. Our friction points (why we care)

1. **Manual regeneration is a footgun** — the whole generator + pre-commit + CI
   staleness machinery exists only because zips/`addons.xml` are committed artifacts
   that drift from source.
2. **Hand-managed version bumps** in each `addon.xml` (e.g. `repository.tony7bones`
   at v1.0.5).
3. **Storage duplication** — add-on source under `repo/<id>/`, a committed zip, and a
   second copy under `_tools/repo-sources/` (same bytes 2–3×).
4. **Two doc/impl mismatches found during review (still OUTSTANDING — see §7):**
   - `CLAUDE.md`/`README.md` say the canonical source URL is
     `https://tony7bones.github.io/repo`, but `addon.xml` (live + `repo-sources`
     master) points `info`/`checksum`/`datadir` at
     `https://raw.githubusercontent.com/tony7bones/tony7bones.github.io/main/repo/`.
   - `CLAUDE.md` says *"CI never commits anything back to main,"* but
     `.github/workflows/generate_repo.yml` (the "Regenerate and commit if stale" step)
     **does** auto-commit and `git push`.
5. **`<hashes>false</hashes>`** in `addon.xml` — hash verification disabled to make the
   static setup behave.

---

## 5. The recommendation (what we agreed)

A **targeted hybrid, NOT a migration**:

1. **Declarative, GitHub-sourced add-ons resolved at generate time** — adopt their
   `repository.json` *concept*, emit static artifacts like our in-tree add-ons.
   _(Prototyped — see §6.)_
2. **Stop committing first-party zips eventually**; build them in CI as a Pages
   artifact. Third-party `repositories/` zips stay committed (we don't own the source).
3. **Quick wins** independent of the above: fix the two mismatches in friction #4 and
   reconsider re-enabling `<hashes>`.

**Decision recorded (2026-06-03):** first-party add-ons (`script.tony7bones.bootstrap`,
`script.tony7bones.modv2.patch`) **stay in-tree for now**; revisit splitting them into
their own GitHub repos (which would make the full i96751414 model viable) *later*.

---

## 6. What's already built on this branch (commit `a5de055`)

### New / changed files
| File | What it is |
|---|---|
| `docs/repository-github-strategy-review.md` | Full comparative review (the reasoning). |
| `docs/HYBRID-REPO-HANDOFF.md` | This file. |
| `_tools/external_addons.py` | **The prototype** — manifest-driven resolver. |
| `_tools/external-addons.example.json` | Manifest schema example. |
| `_tools/test_external_addons.py` | Offline tests (injected fake fetchers). |
| `_tools/generate_repo.py` | Added a **guarded opt-in hook** in `generate()`. |
| `.github/workflows/generate_repo.yml` | Trigger broadened to `_tools/**.py`; runs full `_tools/` suite. |
| `.pre-commit-config.yaml` | Runs full `_tools/` suite. |

### How the prototype (`external_addons.py`) works
- Reads a manifest at `_tools/external-addons.json` (schema in the `.example.json`).
  Each entry describes an add-on by GitHub coordinates (`id`, `username`, optional
  `repository`, `tag_pattern`, `asset_prefix`, `assets.zip`, `token`).
- `GitHubResolver.resolve(entry)`:
  1. GETs `…/releases/latest` → `tag_name`.
  2. Derives `version` from the tag via `_version_from_tag` (inverts `tag_pattern`,
     else strips a leading `v`).
  3. Builds the zip URL by template substitution (`{username}`, `{repository}`,
     `{version}`, `{tag}`, `{ref}`).
  4. Fetches the remote `addon.xml` (from `asset_prefix + "addon.xml"`), parses it into
     the same `<addon>` element our in-tree pipeline produces, validates the `id`.
- `process_external_addons(write=…)` orchestrates: dry-run by default; with `write=True`
  it downloads the zip into `repo/<id>/` and writes a Kodi-compatible per-addon
  `index.html` (reusing `generate_repo._make_index/_fmt_date/_fmt_size`).
- **Network is injected** (`fetch_text`/`fetch_bytes` callables) — tests pass fakes, so
  the suite runs fully offline. Real runs use `_urllib_fetchers()`.

### Off by default (important invariant)
With **no** `_tools/external-addons.json` present, `process_external_addons()` returns
`([], [])` **before any network access**, so `generate_repo.generate()` output stays
**byte-identical**. Verified: running the generator left `repo/` clean in `git status`.
The integration hook in `generate()` is wrapped so manifest/network errors *never* break
the build.

### Status: all green
- `pytest _tools/ -q` → **61 passed**.
- `ruff check _tools/` → clean.
- `python3 _tools/generate_repo.py` → no changes to committed output.

---

## 7. Open questions & suggested next steps (for the local session)

**Decisions still needed from the maintainer:**
- [ ] Apply the **quick-win fixes** (friction #4)? Reconcile the canonical-URL story
      (pick `tony7bones.github.io/repo` **or** `raw.githubusercontent.com`, then make
      `addon.xml`, `CLAUDE.md`, `README.md` agree) and fix the "CI never commits" line.
- [ ] Re-enable `<hashes>` in `addon.xml`? (Requires the served `addons.xml.md5` flow to
      be trustworthy — it is, since we generate it.)
- [ ] When (if) to **split first-party add-ons** into their own repos with tagged
      releases — that unlocks resolving *our* add-ons through the same manifest.

**Natural development tasks (build on the prototype):**
- [ ] Add a real `_tools/external-addons.json` with one safe public add-on and do a live
      `python3 _tools/external_addons.py` dry run, then `--write`, to prove end-to-end.
- [ ] Decide whether external zips should be **committed** (current `--write` behavior)
      or **CI-built and Pages-deployed** (recommendation #2). If Pages-deployed, that
      means moving off `raw.githubusercontent.com` serving to an `actions/deploy-pages`
      flow — bigger change, plan separately.
- [ ] Support `platforms` / `{system}` / `{arch}` for per-platform binaries (the one
      genuinely powerful feature we lack). Not needed unless we ship native add-ons.
- [ ] Caching layer so repeated generate runs don't re-hit the GitHub API for unchanged
      releases (mirror their `/update` cache-busting idea at build time).
- [ ] Rate-limit / token handling for the GitHub API in CI (use `GITHUB_TOKEN`).

---

## 8. Local environment cheat-sheet

```bash
# Regenerate everything (zips, addons.xml, indexes). Safe; no-op for committed output
# unless sources changed or a manifest exists.
python3 _tools/generate_repo.py

# Run the whole test suite (now includes the prototype tests)
python3 -m pytest _tools/ -q        # or: pytest _tools/ -q

# Lint
ruff check _tools/

# Try the prototype (dry run — writes nothing, needs a manifest to do anything)
python3 _tools/external_addons.py
# Resolve + download zips into repo/<id>/ and write indexes
python3 _tools/external_addons.py --write

# One-time pre-commit setup (runs pytest before every commit)
pip install pre-commit && pre-commit install
```

**Key source locations:**
- Generator: `_tools/generate_repo.py` (see `generate()` for the opt-in hook).
- Prototype: `_tools/external_addons.py` (start at `process_external_addons` and
  `GitHubResolver.resolve`).
- Live repo add-on manifest: `repo/repository.tony7bones/addon.xml` (the `<dir>` URLs).
- Source-of-truth copy: `_tools/repo-sources/repository.tony7bones/addon.xml`.
- Project rules: `CLAUDE.md` (read it — it overrides default behavior).

---

## 9. Git state

- This branch `hybrid-repo` builds on `claude/hello-jxdcr` (which itself sits on
  `main` + a CI "regenerate indexes" commit).
- Everything described above is committed in `a5de055` plus this handoff doc.
- No pull request has been opened (none was requested).
