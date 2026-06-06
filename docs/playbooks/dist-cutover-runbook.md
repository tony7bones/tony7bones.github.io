# Runbook: Stage 3 — the `dist` cutover (PLAN — not yet executed)

> Status: **PLAN for review. NOT executed.** This is the first live-affecting
> step of the dist-branch migration ([../plans/dist-branch-decision.md](../plans/dist-branch-decision.md)).
> It changes what installed Kodi boxes fetch on their next update. Execute only
> on explicit owner go-ahead. Prerequisites: Stage 1 (publisher) and Stage 2
> (2a/2b/2c proofs) are done and QA-approved.

## What the cutover does, in one sentence

Change the **committed** proxy manifest so the 12 tony7bones-hosted add-ons are
fetched from the `dist` branch instead of `main`, then ship it as one normal
versioned proxy release. After it lands, boxes read those add-ons from `dist`.

## The only manual edit

In `repo/repository.tony7bones/resources/repository.json`, change `"branch":
"main"` → `"branch": "dist"` for exactly these **12 tony7bones-hosted** entries:

```
repository.kodifitzwell  repository.umbrella  repository.diggz
repository.Magnetic      repository.kodinerds repository.loop
repository.redwizard     repository.tony7bones
script.tony7bones.bootstrap  script.module.tony7bones
script.tony7bones.modv2plus  script.tony7bones.video
```

**Leave these 5 entries ALONE** (they fetch from _external_ upstream repos, which
have no `dist` branch — flipping them would break them):

```
repository.709  repository.bugatsinho  repository.cocoscrapers
repository.ivarbrandt  repository.peno64
```

Everything else in the release is done by `deploy.py`.

## Why this is safe for already-installed boxes (the linchpin)

The proxy delivers its **own** update from a branch-independent URL:
`https://tony7bones.github.io/repository.tony7bones-{version}.zip` (the Pages
root — no `{ref}`). So the upgrade path has no chicken-and-egg problem:

1. A box today runs proxy **2.0.0**, whose manifest still reads from `main`.
2. We release the cutover version (e.g. **2.1.0**). `deploy.py` puts 2.1.0 on
   `main` and at the Pages root zip.
3. The box's installed 2.0.0 proxy sees `main`'s addon.xml = 2.1.0 → offers the
   update → downloads `repository.tony7bones-2.1.0.zip` from the **Pages root**
   (branch-independent) → installs it.
4. The newly-installed **2.1.0** manifest reads from `dist`. From now on the box
   fetches the 12 hosted add-ons (and future self-updates) from `dist`.

The old (main-reading) proxy delivers the new (dist-reading) proxy. No box is
ever asked to read from `dist` before it is running a build that knows about it.

## Preconditions / pre-flight (verify BEFORE editing)

- [ ] `git status` clean; on `main`; up to date with origin.
- [ ] Tests green: `python3 -m pytest _tools/ -q`; `ruff check _tools/`.
- [ ] **`dist` is current** — the Stage 1 publisher has run for the latest `main`
      (`gh run list --workflow=publish-dist.yml`), and
      `raw.githubusercontent.com/.../dist/repo/addons.xml` → HTTP 200. After
      cutover `dist` is authoritative, so it must be healthy and in sync.
- [ ] Decide the version bump. Recommended: **`--minor`** (2.0.0 → 2.1.0) since
      this is a behavioral change, not a fix. (`deploy.py` defaults to patch.)

## Release procedure

1. Edit `repository.json` — flip the 12 entries (above) to `"branch": "dist"`.
2. Sanity-check locally with the same proof used in Stage 2a/2b (point the engine
   at the edited config and confirm a 12-addon `addons.xml` assembles and zips
   fetch) — optional but cheap.
3. Run the one-command release:
   ```bash
   python3 _tools/deploy.py --minor --news "Serve hosted add-ons from the dist branch"
   ```
   `deploy.py` then atomically: bumps the version in `addon.xml`, builds the proxy
   zip deterministically (baking the edited `repository.json`), syncs all four
   version locations (addon.xml, root zip filename, root index.html link, git
   tag), commits `main`, tags, `git push --atomic main <tag>`, forces a Pages
   build, and verifies live. Any failure before the push rolls back.
4. **Confirm `dist` updates after the push.** The publisher auto-fires on the
   `main` content change; confirm its run succeeded and
   `raw.../dist/repo/repository.tony7bones/addon.xml` now shows the new version.
   (If it lagged, trigger it: `gh workflow run "Publish dist branch" --ref main`.)
   Harmless if it lags briefly — a box on the new version reading an older
   self-update number from `dist` simply sees "no update", never a downgrade.

## Verification (before and after)

Use the local Kodi 21.3 Omega already installed for Stage 2c.

- **Before:** note current served state (proxy 2.0.0, manifest → main).
- **After:** install the released version through the normal flow (or update the
  local profile's proxy to the shipped zip) and confirm in `~/Library/Logs/kodi.log`:
  `Using ref dist` for the 12 entries and `…/dist/repo/…` GETs at HTTP 200, plus
  a rendered repo browse — exactly the 2c evidence, now from the _shipped_
  release rather than a hand-edited profile.
- If a real Fire Stick is reachable, verify there too (it is the true target).

## Fleet / multi-platform notes (FireTV, Fire Sticks, Nvidia Shield, mixed Android)

The cutover is **platform-agnostic by construction** — reassuring for a
heterogeneous fleet:

- It changes only _which branch_ the proxy fetches from. Every device gets the
  **same bytes** from the **same host** (`raw.githubusercontent.com`) over the
  **same TLS** it already uses for `main` today — `dist` is just a different path
  on that host. No new connectivity, certificate, or OS requirement is
  introduced, so even older Fire OS / Android builds are unaffected.
- All 12 flipped entries are **platform-neutral**: none use platform-binary
  placeholders (`{system}`/`{arch}`) and none carry a `platforms` filter, so no
  device family (Fire OS vs. Android/Shield) gets a different or dropped add-on
  because of the flip.
- The proxy is pure Python running inside Kodi; branch-ref resolution is
  identical on every device. Stage 2c proved the exact code path live.

**Verification across the fleet:** because the change is uniform, the local Kodi
proof plus **one real device per family** (one Fire OS box + the Shield) is
ample — you are spot-checking connectivity/render, not per-platform behavior,
since there is no per-platform behavior in this change. Update the proxy on a
couple of representative boxes first, confirm the repo still browses and an
add-on still installs, then let the rest of the fleet pick it up.

**Execution-layer quirks are real here — but they are a different layer.** The
recent modv2plus **1.3.4** fix (`a3176b7`: `shutil.copy2` → `copyfile`, because
`copy2`'s chmod/utime fails on Android 11 `sdcardfs`, Fire OS 8 / Shield) is a
reminder that add-on _runtime_ behavior can differ per device. That bug lived in
the add-on's Python, in how it writes files on the device — **not** in how the
proxy fetches it. The cutover changes only the fetch branch and serves the
**same, already-fixed 1.3.4** zip (byte-identical from `dist`, proven in 2c), so
it cannot reintroduce it. Practical upshot: the post-cutover device check is a
**connectivity/fetch** spot-check (does the repo still browse and install from
`dist`?), not a re-test of each add-on's on-device behavior — that is unchanged
by a branch flip. Still, include an **Android 11 device (Shield / Fire OS 8)** in
the spot-check, since that is where this fleet has historically surprised us.

> If a future change ships **platform-specific binaries** (uses `{system}`/
> `{arch}` or a `platforms` filter), that one would need per-family verification.
> This cutover does not.

## Rollback (roll FORWARD — never downgrade)

Kodi upgrades by version number and will not downgrade, so rollback = ship a new
higher version that points back at `main`:

1. Revert the `repository.json` branch flip (back to `main`).
2. `python3 _tools/deploy.py --patch --news "Revert hosted add-ons to main branch"`.
   Boxes on the dist version then update to this version and read `main` again.

The deeper backstop for the whole effort remains the tag
`safety/pre-dist-spike-ce5ae11` (state before any of this began).

## Risks & non-obvious gotchas

- **Don't flip the 5 external entries** — repeated because it's the easiest
  mistake and it breaks those repos.
- **`dist` becomes load-bearing.** After cutover, the proxy depends on `dist`
  being correct and current; the Stage 1 publisher must stay healthy. (Proven in
  Stage 1, but it graduates from "nice" to "production-critical" here.)
- **Every release must bump the version** — same-version byte changes silently
  break Kodi auto-upgrade. `deploy.py` enforces this.
- **The self-update zip is intentionally branch-independent** (Pages root). Do
  NOT "helpfully" rewrite it to a `{ref}` URL — that would reintroduce a
  chicken-and-egg on the next cutover-style change.

## Go / no-go checklist (execution gate)

- [ ] Pre-flight all green (above).
- [ ] `dist` healthy and in sync with `main`.
- [ ] Only the 12 entries flipped; the 5 external untouched.
- [ ] Owner has explicitly approved going live.
- [ ] A real Kodi (local and/or a Fire Stick) is available to verify after.
- [ ] Rollback path understood (roll forward to a main-pointed version).
