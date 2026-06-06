# Playbook: the `dist` branch + its publisher

> Status (2026-06-06): **Stage 1 complete and QA-approved.** The publisher is
> live and keeps `dist` up to date, but **nothing reads `dist` yet** — the proxy
> and every installed Kodi box still fetch from `main`. The cutover (pointing
> the proxy at `dist`) is a deliberate later stage and has NOT happened.
>
> Background and rationale: [../plans/dist-branch-decision.md](../plans/dist-branch-decision.md).

## What `dist` is

`dist` is a **CI-generated branch** holding the compiled output of the build —
the eventual fetch target for the virtual proxy. It is **machine-owned**: never
hand-edit it, never open PRs against it. It is force-pushed on every build, so
any manual commit there would be silently clobbered.

`main` stays the human source of truth. The end-state goal is: humans work only
on `main`, the generated clutter lives only on `dist`.

## The publisher workflow

`.github/workflows/publish-dist.yml`:

- **Triggers**
  - automatically on `push` to `main` that touches served content
    (`repo/**`, `_tools/**`, `index.html`); and
  - on-demand via the manual "Run workflow" button (`workflow_dispatch`).
- **What it does**: checks out `main`, runs `python3 _tools/generate_repo.py`,
  `git add -A`, commits only if the build produced changes, then
  `git push --force origin HEAD:refs/heads/dist`.
- **Permissions**: `contents: write` (it pushes a branch — nothing more).
- **Concurrency**: serialized (`group: publish-dist`, no cancel) so two builds
  never race.

### Why it can't loop (important)

The `push` trigger is scoped to `branches: [main]`. The workflow's own pushes
land on `dist`, which can never match a `main`-scoped trigger — self-triggering
is **structurally impossible**. As a second, independent layer, the path
allow-list (`repo/**`, `_tools/**`, `index.html`) does not include `.github/**`,
so editing the workflow itself does not trigger a build.

## Operating it

- **Manual rebuild**: `gh workflow run "Publish dist branch" --ref main`, then
  `gh run watch <run-id> --exit-status`.
- **Check what dist serves**:
  `curl -s -o /dev/null -w "%{http_code}\n" https://raw.githubusercontent.com/tony7bones/tony7bones.github.io/dist/repo/addons.xml`
- **Recovery point for the whole effort**: tag `safety/pre-dist-spike-ce5ae11`
  on origin. Rewind with `git reset --hard safety/pre-dist-spike-ce5ae11`.

## Known considerations for the cutover (NOT yet addressed — by design)

These are deliberately deferred to the stage where the proxy is repointed at
`dist`. Recorded here so they aren't relearned the hard way:

1. **`dist` currently mirrors the full `main` tree** (`.github/`, `_tools/`,
   `docs/`, source add-on dirs, etc.) plus generated artifacts — because the
   publisher does `git add -A` on a `main` checkout. Harmless while nothing reads
   `dist`. At cutover, decide whether `dist` should be pruned to an output-only
   tree. (It does not affect the proxy, which fetches specific `repo/...` paths.)
2. **Workflow-only edits don't republish `dist`** (the path allow-list does not
   include `.github/**`), so after such a commit `dist` sits one source-commit
   behind `main`. Expected; press the manual button if a republish is ever
   wanted. (A no-change build still force-pushes, advancing `dist` to the
   current `main` HEAD even when no new build commit is created.)
3. **No branch protection on `dist`** — intentional (it's force-pushed
   generated output), but it means a stray human push there is clobbered on the
   next build.
4. **The cutover itself is the first live-affecting step.** Repointing
   `repository.json` entries to `"branch": "dist"` ships as a normal, versioned
   proxy release via `_tools/deploy.py`, verified against local Kodi first, and
   is reversible.

## Roadmap status

- **Stage 1 — build the translator**: ✅ done (1a manual → 1b automatic →
  1c this playbook), QA-approved at each step.
- **Stage 2 — prove the proxy serves off `dist`** on a throwaway version: pending.
- **Stage 3 — cutover** (repoint proxy at `dist`, versioned release): pending.
- **Stage 4 — clean `main`** (remove generated clutter): pending.
