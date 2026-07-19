# TASKS

Tracking for the Tony.7.Bones repo.

> ## What is actually OPEN in this file (audited 2026-07-18)
>
> **This file is ~900 lines and is almost entirely a historical record.** Two
> items are live work for THIS repo:
>
> 1. **EZM++ legacy metadata shim deletion** - the `⛔ CORRECTION 2026-07-18`
>    block inside the P2 section. Documented, deliberately NOT executed,
>    deferred by the owner pending the IPTV Streamvision parity gate. It has no
>    checkbox, so a checkbox scan misses it. See the STOP block in `CLAUDE.md`.
> 2. **Bedroom box - full-customization backup + clone-restore test** - the
>    `🔲 ACTIVE` section; three sequential sub-items, owner-gated on the first.
>
> Everything else with an open-looking marker is stale, not live:
>
> - The **two `▶` headings near the bottom** both point at finished or
>   cancelled work. "VERY NEXT STEP - P1: extract the IPTV builder" names a
>   track this same file marks `✅ DONE 2026-07-17`, and the "Prior next-step"
>   N2 track is self-labeled CANCELLED. They are kept as history. **Neither is
>   your next task.** The unticked boxes in the P1 IPTV section were simply
>   never ticked; that work shipped.
> - The **"Mini / home-server ops - open items 🔲 ACTIVE"** header is stale:
>   all five sub-items are `[x]` DONE 2026-07-02. Only two advisory notes
>   remain (`~/Kodi/Backup` has no pruning; purge `~/Kodi/.attic` when sure).
> - The **"Estuary 7 - fork-by-build 🔲 ACTIVE"** section is a historical
>   record of THIS repo's part (hosted metadata, catalog entry). Its "Phase 5
>   not started" framing is contradicted earlier in this same file, which
>   records Phase 5 as **DROPPED as a project** (owner, 2026-07-15). Live skin
>   work belongs in `~/Code/moquette/kodi/estuary7/TASKS.md`.
> - The **"Backlog - Estuary MOD V2+"** items target
>   `script.tony7bones.modv2plus`, which is deprecated AND deleted. No repo
>   owns them. Recommend striking rather than moving.
>
> **Sibling trackers.** This is one of five repos in a meta-checkout at
> `~/Code/moquette/kodi`. Fleet meta index: `~/Code/moquette/kodi/TASKS.md`.
> Per-project: `ezmpp/TASKS.md`, `estuary7/TASKS.md`, `iptv/TASKS.md`. Note
> that `docs/incident-2026-07-16-ezmpp-full-backup-was-not-full.md` is a
> self-declared OPEN release blocker for EZM++ with two owner-gated hardware
> runs outstanding, and that a hardware-verification gate on the EZM++ release
> checklist is requested by three separate incident writeups here and appears
> never to have landed.
>
> Stale paths: several sections below cite `~/Code/moquette/estuary7` and
> `~/Code/moquette/ezmaintenanceplusplus`. **Those standalone paths do not
> exist.** The real checkouts are `~/Code/moquette/kodi/estuary7` and
> `~/Code/moquette/kodi/ezmpp`.

---

> **The repo is now a STATIC Kodi repository served by GitHub Pages.** The virtual proxy engine
> and the entire Setup add-on family (`script.tony7bones.bootstrap`, `script.module.tony7bones`,
> `script.tony7bones.modv2plus`) have been RETIRED and DELETED; `repository.tony7bones` is a
> normal static-only repository add-on (3.0.0). Sections below marked DONE that describe the
> Setup / proxy / MOD V2 era are historical records - read them for context, not current state.
> The modular Setup design + phase log lives in `docs/plans/modular-setup.md` (historical).

---

## ⛔ WORKFLOW - non-negotiable, every phase (do NOT skip or reorder)

> **implement → TEST → COVERAGE (≥90% new code) → GATE (`pytest _tools/ -q` + `ruff` + secrets all
> green) → adversarial QA completeness review → real-device verify on local Kodi (if runtime) →
> DOCUMENT (phase log) → only THEN commit → only THEN start the next phase.**

1. **NO COMMIT until ALL of the above pass.** Red suite / missing test / unreviewed change /
   undocumented phase = do not commit.
2. **NO next phase until the current phase is committed green.** Phases are sequential-gated.

This discipline caught real bugs pre-commit in every phase (the snapshot rebaseline footgun, a
tech-debt seam, the apply_iptv reporting bug, the zero-content guarantee). Keep it.

---

## P1 - Extract the IPTV builder into its own (PRIVATE) repo - ✅ DONE 2026-07-17 (raised P1 2026-07-14)

> **DONE 2026-07-17.** The IPTV builder now lives in the private `moquette/iptv` repo and the
> Mac mini runs the pipeline from a checkout of it (IPTV 2.0 share model: the mini builds
> centrally and writes to the NFS share each box reads). The duplicate `_tools/build_iptv.py`
> (+ `test_build_iptv.py`) was removed from this repo and the `provision-kodi.sh` v1
> host-build-and-stage step was retired. The scope block below is a historical record.

The IPTV builder is a real ~4,600-line two-halves orchestration currently scattered in THIS
repo. Owner decision (2026-07-13): it becomes its OWN repository, the same clean pattern as
the EZ Maintenance++ extraction - but PRIVATE (it carries live provider credentials). This
must happen BEFORE the MOD V2 machinery (`script.module.tony7bones`,
`script.tony7bones.bootstrap`, `script.tony7bones.modv2plus`) is retired. The estuary7
Phase 5 fleet migration is DROPPED as a project (owner decision 2026-07-15): boxes switch
to Estuary 7 manually at leisure, modv2plus is DEPRECATED (no further releases), and
nothing there gates this. The distribution itself is converting to a static repo - plan:
fleet meta-repo `~/Code/moquette/kodi/docs/static-repo-and-tailscale.md` (pointer stub at
`docs/plans/static-repo-and-tailscale.md`) - and this extraction is a prerequisite for it
(no secrets in the static tree).

**Scope (verified on disk 2026-07-14):**

- HOST half: `_tools/build_iptv.py` (659) + tests `test_build_iptv.py` (1062),
  `test_run_iptv.py` (490), `test_setup_iptv.py` (1512). Builds per-provider `<Token>.m3u`
  - `customTVGroups-<Token>.xml` + `instance-settings-<N>.xml` from a per-device `.env`.
- IN-KODI half: `addons/script.module.tony7bones/lib/tony7bones/setup/iptv.py` (939,
  `_apply_staged_provider`) - consumes the staged artifacts on the box. NOTE: this lives
  INSIDE the MOD V2 module being retired; decide whether the in-Kodi apply moves to the new
  repo, stays as a thin consumer, or is superseded.
- config/data: `iptv/configs/`, `iptv/groups/customTVGroups-*.xml`
- docs: `docs/plans/iptv-automation.md`, `docs/playbooks/iptv-channel-customization.md`,
  `iptv-stream-troubleshooting.md`, `docs/incident-2026-07-08-ezmpp-iptv-brick.md`
- skill: `.claude/skills/iptv-stream-doctor/SKILL.md`
- dev branch: `origin/iptv-2.0-share-populator`
- runtime home: the Mac mini "mini" (192.168.7.2), the always-on IPTV server.

**⛔ BLOCKING SECURITY CONSTRAINT (why this is not a copy-paste of the EZM++ move):**
`iptv/configs/instance-settings-1.xml` is TRACKED and committed in this PUBLIC repo (since
`24b1d38`) with REAL op.web24.live credentials - a live secret leak in public git history.
Owner said: "I will handle it. Do not touch it for now." Therefore: the new repo MUST be
PRIVATE, credentials MUST be templated out (a `.env` / example pattern, never a committed
secret), and the leaked history is the owner's to remediate. Do NOT modify that file without
the owner.

**Checklist (mirror the EZM++ extraction, minus public):**

- [ ] Create the PRIVATE repo; move host code + tests + `iptv/` data + docs + the skill.
- [ ] Template out all real credentials/provider IPs; add a `.env.example`; verify no secret
      lands in the new repo's history.
- [ ] Add its own CI (pytest + ruff + a build smoke), mirroring the ezm/estuary7 workflows.
- [ ] Decide the in-Kodi `setup/iptv.py` boundary (move / thin-consumer / supersede).
- [ ] Remove the moved source from THIS repo once the new home is verified (verify-before-remove).
- [ ] Fold in the `iptv-2.0-share-populator` branch or record its disposition.
- Full context + rationale: memory `iptv-builder-project-own-repo.md`.

## P0 - STATIC REPO CONVERSION - ✅ SHIPPED (static-only live 2026-07-15)

> **Superseded by the owner reframe (2026-07-15): NO fleet convergence.** Every
> deployment is a fresh clean Kodi install done at leisure, so the phased
> dual-`<dir>` / 2.6.0-interim / convergence / history-squash plan below was
> dropped mid-flight. The engine was full-send RETIRED and `repository.tony7bones`
> shipped STATIC-ONLY at **3.0.0** (single `<dir>` -> `https://tony7bones.github.io/static/`,
> no service, no engine code). The setup add-on family was nuked. The checkboxes
> below are the historical record of how the machinery landed.

Full plan (historical): fleet meta-repo
`~/Code/moquette/kodi/docs/static-repo-and-tailscale.md`. Pipeline: build the
ENTIRE served site in CI (`_tools/build_site.py` -> `static_catalog.py`), served
by GitHub Pages, verified from the consumer seat (`verify_live_site.py`).

- [x] **Phase 0 - machinery alongside** (2026-07-15, commit `035646f`):
      `static_catalog.py` (all 31 entries classified/materialized, last-good
      fallback, shrink guard, 90MB gate), `build_site.py` (tracked-files copy +
      structural secret exclusion at copy time), `check_site_secrets.py` +
      `secret_patterns.py`, `verify_live_site.py`, `pages.yml` (deploy/verify
      gated `if: false`), 40 new tests incl. `test_raw_url_contract.py` (the
      standing rule as CI). THREE green CI builds verified across all trigger
      types (push, workflow_dispatch, repository_dispatch). Release-dispatch
      senders live in `moquette/estuary7` + `moquette/ezmaintenanceplusplus`
      (`notify-hub.yml`, `T7B_DISPATCH_TOKEN` secret set). NOTE: the copy-time
      secret exclusion caught the tracked `instance-settings-1.xml` pair
      (dropbox + mirror) - excluded from every artifact; the FILES stay
      tracked per the owner's "I will handle it" (history remediation still
      owner-owned, and MUST land before the Phase 6 squash).
- [x] **Phase 0 adversarial QA + architecture review** (2026-07-15, both
      independent agent reviews complete). QA REPRODUCED two ways a green
      build could publish a broken catalog; the architect verified the
      dual-`<dir>` design against Kodi's actual Repository.cpp. ALL pre-flip
      findings fixed same day: F1 fallback freshness + version cross-check in
      the single writer; F2 per-run cache key (the content-hash key silently
      DOWNGRADED third-party versions daily); F3 baseline non-404 failure is
      now a hard BuildError + verify gained an --expect-count floor; F4
      per-entry fallback for corrupt zips/unparseable metadata, zip-validated
      cache writes (no poisoning), first-party corruption fails loud; F5
      internal zip id/version cross-check; F6 verify KeyError guard +
      rotating full-GET coverage; R2 consistency/version-bump gates added to
      pages.yml + deploy permissions scoped to the deploy job; R5 served
      indexes delist structural-secret files (the credential file's URL is no
      longer advertised); Fetcher unit suite covering the exploited cache
      seams. 1263 tests green; real 31-entry build + determinism + secret
      gate re-verified.
- [x] **Phase 0 dev-Kodi assumption check** (2026-07-15, real Kodi 21.3
      Omega on the Mac, driven via JSON-RPC + EventServer; NOTE Omega's
      JSON-RPC has NO ExecuteBuiltin - builtins fire via EventServer UDP
      9777, helper kept in the session scratchpad). Results, all
      evidence-backed (access log + Addons33.db + kodi.log):
      **A PASS** - Kodi fully consumes the static tree: addons.xml+md5
      fetched, all 31 entries in the DB, installs resolve from the datadir
      with origin stamped, per-item icon GETs while browsing.
      **B PASS** - dual-dir both-alive merges (duplicate catalog rows, both
      indexed).
      **C CONFIRMED** - a dead `<dir>` kills the WHOLE repo update:
      first-dir checksum failure short-circuits (dir2 never even fetched),
      STATUS_ERROR, stale catalog retained. Exactly Repository.cpp's
      behavior as the architecture review predicted.
      **D CONFIRMED WORSE** - duplicate-entry install picks the dead dir's
      datadir and FAILS OUTRIGHT; Kodi never falls back to the live
      duplicate row.
      **DECISION (evidence-forced): the dual-`<dir>` interim is REJECTED.**
      C+D make it strictly worse than either single shape. Revised release
      path: ONE static-only release (single `<dir>` -> /static/, NO
      xbmc.service, engine code dropped from the zip), shipped as 3.0.0
      through the still-alive engine update path - the 2.6.0 interim is
      cancelled, collapsing old Phases 2-5 into: release 3.0.0 -> fleet
      convergence -> Phase 6. This also moots the service.py port-heal
      patch (no service ships), though the dir-rewrite footgun stays
      documented for anyone resurrecting the engine.
      **Build gap found and FIXED same day**: 7/13 repository icons and all
      `resources/icon.png` assets 404'd (metadata dirs never carried them);
      `static_catalog._fill_art_from_zip` now materializes declared art out
      of each entry's zip - 31/31 icons served (test pinned).
      Kodi profile backup from the run: `~/Library/Application
      Support/Kodi.backup-20260715-124124` (deletable once confirmed).
- [~] **Phase 1 - LIVE (2026-07-15, owner "proceed"); soaking.** Pages source
  flipped to GitHub Actions (via `actions/configure-pages enablement:true`
  in the deploy job - the pushing moquette account has push-not-admin, so
  the REST flip 404'd; the workflow token did it). Both gates enabled;
  first push-run built + deployed + the consumer-seat verify job passed
  (commit `f2e05a4`). Live-confirmed from the seat: `/static/addons.xml`
  md5 invariant holds, all 31 zip URLs 200, `skin.estuary7` **1.0.42**
  served, 7 previously-404 icons now 200, root installer 200, legacy
  `/addons/addons.xml` still 200, and the leaked
  `iptv/configs/instance-settings-1.xml` now **404s** on the live site
  (excluded from the artifact - the URL is no longer served, though the
  file stays in git history for the owner to remediate before Phase 6).
  **Real-box proof (Office Fire TV 192.168.7.162):** a static-only test
  repo pointed at the LIVE `https://tony7bones.github.io/static/`
  populated all 31 entries into the box's `Addons33.db` with correct
  versions (estuary7 1.0.42, ezm 2026.07.15.0) and the static datadir/art
  URLs (`tony7bones.github.io/static/.../fanart.jpg`), proving real fleet
  hardware consumes the Pages-from-Actions tree over the internet;
  install-from-datadir itself is already dev-Kodi-proven (the box's
  InstallAddon confirm-dialog couldn't be driven headless - a harness
  limit, not a tree problem). Box restored to found state (test repo
  removed, engine repo re-enabled). SOAK ~1 week before Phase 2.
  Rollback if needed: `gh api -X PUT .../pages -f build_type=legacy` (or
  the UI) - the committed tree still serves from main. TODO during soak:
  widen/drop the push path filter (docs-only pushes otherwise go stale up
  to 24h now that the build IS the deploy).
- [x] **ENGINE RETIRED - static-only 3.0.0 SHIPPED (2026-07-15, commit
      `08229a9`).** Owner reframe: every deployment is a fresh clean Kodi
      install, done manually at leisure (first target: Office Fire TV, then an
      ATV). No fleet to keep converged => the whole 2.6.0-interim /
      convergence-gate / raw-URL-standing-rule framework is CANCELLED, not
      deferred. `repository.tony7bones` is now a plain static-only add-on
      (single `<dir>` -> `https://tony7bones.github.io/static/`, no
      `xbmc.service`, no `lib/`, no local proxy). Deleted: the engine
      (~925 lines), `deploy.py` + the proxy release transaction,
      `check_consistency.py`, and the engine/deploy/proxy test suites
      (`test_proxy`, `test_update_propagation`, `test_deploy`,
      `test_raw_url_contract`) - net -6355 lines. Manifest moved to
      `_tools/catalog.json` (out of the shipped add-on). `release.py` treats
      the repo add-on like any other; `build_site.place_root_installer`
      produces the served root installer in CI. VERIFIED: 1054 tests green,
      real 31-entry build deterministic + secret-clean; real local-Kodi fresh
      install of the 3.0.0 zip ingested the static catalog, installed an
      add-on from the datadir, rendered icons - no service/proxy/engine; and
      LIVE on Pages - root `repository.tony7bones-3.0.0.zip` 200, old 2.5.0
      404, live catalog self-entry 3.0.0 with ZERO `127.0.0.1:61234`
      references.
- [x] **Fresh-install the Office Fire TV** (owner-confirmed done 2026-07-16):
      clean Kodi + `https://tony7bones.github.io/` source +
      `repository.tony7bones-3.0.0.zip` + install from repository.
- [x] **Post-install cleanup (2026-07-16):** main is now SOURCES-ONLY.
      Purged from git: the committed `static/` tree (which was silently
      serving the RETIRED bootstrap/library add-ons by direct URL - live-
      verified 200 pre-purge), the committed root canvas mirror
      (`repositories/ media/ iptv/ rss/ zips/ index.html robots.txt`), the
      committed root installer, and 31 superseded `repository.tony7bones`
      zips (2.2.0-2.5.0; `generate_repo.py` now auto-prunes superseded
      versions). `build_site.py` generates the canvas mirror + root index +
      robots.txt into the CI artifact (the END-STATE MODE its docstring
      promised); `sync_share.py` sources the installer from
      `addons/repository.tony7bones/`; `publish_canvas.py` is commit+push
      only. pages.yml path filter dropped (every push deploys - the soak
      TODO). Byte-parity of the built site vs pre-change baseline verified
      (only intended removals differ). The Setup-addon proxy-skip
      simplification is MOOT (family deleted in `0dde2cf`).
- [x] **Credential remediation + history squash (2026-07-16):**
      `dropbox/iptv/configs/instance-settings-1.xml` untracked (kept locally),
      .gitignore patterns fixed (they were commented out AND missed the
      configs/ subdir), `test_secret_leak.py` now forbids tracking any
      `instance-settings*.xml`, all tags deleted, history squashed to a
      single root commit and force-pushed - the credential and the ~62MB of
      binary-zip history are gone from the reachable repo. The leaked IPTV
      provider credentials were ROTATED by the owner 2026-07-16, closing the
      exposure fully (orphaned commits fetchable by SHA now carry dead
      credentials).

## P2 - Pre-static hub cleanup - 🔄 IN PROGRESS (started 2026-07-15)

Context: distribution is converting to a static repo (plan: fleet meta-repo
`~/Code/moquette/kodi/docs/static-repo-and-tailscale.md`, pointer stub at
`docs/plans/static-repo-and-tailscale.md`). Clean the hub first so the static tree is
generated from a minimal, truthful repo.

- [x] Purge the stale "proxy not released past v2.4.5" audit alarms from TASKS.md and
      CLAUDE.md - resolved by the v2.5.0 release (2026-07-15).
- [x] Mark `script.tony7bones.modv2plus` DEPRECATED in CLAUDE.md (owner decision
      2026-07-15: no further releases; boxes switch to Estuary 7 manually at leisure;
      retired at estuary7 Phase 6 once the last box leaves MOD V2).
- [x] Dead branches: verified `virtual-repo` and `hybrid-repo` are already deleted from
      the remote and that NO released tag's baked manifest ever referenced `virtual-repo`;
      corrected the stale "may still exist" note in CLAUDE.md.
- [x] Remove `_tools/repo-sources/` (hand-rebuild reference copies; nothing read them).
- [ ] Remove the moved IPTV source from this repo - tracked by the IPTV-extraction P1
      above (verify-before-remove).
- [x] Leaked credential history remediation + history squash (2026-07-16) - done
      together: the file is untracked/gitignored, all tags deleted, and history
      squashed to a single root commit (see the post-install cleanup entry above).
      Credentials rotated by the owner 2026-07-16 - remediation COMPLETE.
- ~~⛔ DO NOT CLEAN: anything an old engine bundle references~~ LIFTED by the
  2026-07-15 owner reframe (no fleet convergence; fresh installs only).
- ⛔ **CORRECTION 2026-07-18:** the follow-on claim previously written here (that
  the EZM++ metadata shim `addons/script.ezmaintenanceplusplus/` "stays because
  the catalog builds from it") is FALSE, and was false when written. The catalog
  reads `addons/hosted/`, and has since `catalog.json` first appeared. Both
  written justifications for that shim are disproven; it is slated for deletion,
  documented but not executed. See the STOP block at the top of `CLAUDE.md` and
  the full finding at `~/Downloads/kodi-legacy-addons-shim-finding-20260718.md`.

## P1 - EZ Maintenance++ boot path + cache-clean bugs - ✅ DONE (2026-07-09, branch `ezm-boot-cleanup`, released as 2026.07.09.1)

> **OUTCOME (all 9 items shipped; read this before touching this add-on again):**
>
> - **Gate at completion:** 1270 passed / 1 xfailed, ruff clean (`_tools/` scope; the add-on
>   itself went 92 -> 45 pre-existing findings, none added), deterministic regen, coverage
>   maintenance.py 95% / service.py 75% (misses = the `__main__` block, PY2 shims, and
>   swallow-guards; all new logic covered). New test file:
>   `_tools/test_ezmaintenanceplusplus_maintenance.py` (33 tests).
> - **Adversarial QA caught a REAL defect the unit tests could not see:** on a real box
>   `special://thumbnails` ALIASES `userdata/Thumbnails`, so the naive two-pass
>   `deleteThumbnails` rmtree'd the 0-f/ bucket skeleton the first pass preserved (the OLD
>   code preserved it only BY ACCIDENT - the `file_count` bug disabled its rmtree). Fixed
>   with an `os.path.realpath` aliasing guard + a test that models the aliasing.
> - **The device verify caught a second real bug that 1268 green tests missed:** deleting
>   `import requests` broke `urllib.parse.quote_plus` at `default.py` import
>   (`AttributeError: module 'urllib' has no attribute 'parse'` live on the Office box) -
>   a bare `import urllib` does NOT expose `urllib.parse`; requests had been loading it
>   transitively. NOTHING in the suite imported EZM's `default.py`, so it shipped green.
>   Fixed with explicit `from urllib.parse import ...` (same latent landmine hardened in
>   `pastebin.py`), and the suite now imports `default.py` exactly as Kodi invokes it
>   (`_import_plugin` in the new test file) so an import-time break can never ship green
>   again. THIS is why the hardware-verify rule exists.
> - **Office Fire TV verify (2026-07-09):** cold-boot A/B old-vs-new = 6.4s BOTH (3+2 runs;
>   the folders on that box are tiny - 2MB packages / 74 thumbnails - so no measurable
>   speedup was expected or claimed; the win is structural: no walks, no modal prompts, no
>   deletions on the boot path). Root menu + Maintenance submenu render live (screenshots,
>   `Container.FolderPath`/NumItems proven), live Clear Cache ran with `kodi.log` surviving,
>   zero tracebacks. Gotchas hit: the panel must be AWAKE or Kodi dies at CreateGUI
>   (display OFF -> EGL fails; wake with `input keyevent KEYCODE_WAKEUP`);
>   `Files.GetDirectory` cannot list a `provides>executable` plugin over JSON-RPC - use
>   `GUI.ActivateWindow(programs, [plugin-url, "return"])` (the STRUCTURED call; the
>   ExecuteBuiltin string form with escaped quotes silently no-ops) + InfoLabels;
>   after a failed GetDirectory Kodi won't re-navigate to that path until restart.
> - **Release path (resolves the open question):** the date scheme needs an explicit
>   version - `release.py --addon script.ezmaintenanceplusplus --version 2026.07.09.1`
>   (auto-bump refuses `2026.*`); everything else (news prepend, regen, gate, commit) works.
> - Also folded in: `time.sleep(3)` removed, 60s monitor tick, dead loop logging dropped,
>   `skinSwitch.py` deleted, `control.py` no longer instantiates `WindowDialog`/
>   `DialogProgress`/`Player` at import (kept `setSetting` - the wiz restore test uses it
>   as a tripwire), `pastebin.py` urllib hardened.

**Done (9 items, one branch):**

- [x] **1. Move the whole boot preamble off module scope.** `service.py` lines 27-103 run at
      import, at Kodi startup. It walks `addons/packages` and `userdata/Thumbnails` calling
      `os.path.getsize()` per file, then fires two modal `Dialog().yesno()` prompts
      (`service.py:46`, `service.py:70`) before the GUI is confirmed up. A "yes" runs
      `deleteThumbnails()` synchronously in the service thread at boot, nuking the Thumbnails
      tree and `Textures13.db`. The file already knows this is wrong: `_wait_kodi_ready`
      (`service.py:117`) exists with the docstring "so we never prompt on a black boot screen",
      and only the restore prompt honors it. Relocate the scan, prompts, notification and
      autoclean into the monitor loop behind `_wait_kodi_ready`. This one change removes the
      boot I/O, the black-screen prompt, and the boot-time deletion together.
- [x] **2. Fix the packages file count.** `service.py:38` resets `count = 0` inside the outer
      `os.walk` loop, so the dialog reports the LAST subdirectory's count, not the total.
      Masked today only because `packages/` is normally flat.
- [x] **3. Delete `time.sleep(3)`** (`service.py:99`). It blocks abort and serves no purpose.
      Note the review's suggested fix (`monitor.waitForAbort(3)`) is a `NameError` at module
      scope: `monitor` does not exist yet. Item 1 makes the correct fix available; simplest is
      to drop the sleep.
- [x] **4. Fix the cache-clean skip bug (real functional bug, needs a unit test).** In
      `maintenance.py` `clearCache` (lines 44-70, and the duplicated 74-101 `tempPath` block),
      `for d in dirs: shutil.rmtree(...)` is nested inside `if file_count > 0:`. **A directory
      level holding subdirectories but zero loose files is never cleaned at all.** Same shape in
      `purgePackages` (199-210) and `deleteThumbnails` (162-184). Fold the copy-pasted
      cache/temp block into one helper (doing so is what surfaces this) and cover it with a
      test: a dir-only tree must be emptied, protected names must survive.
- [x] **5. Delete the dead code** rather than "fixing" it:
  - `maintenance.py:23-27` - `addonPath` points at `script.ezmaintenance` (no `plusplus`),
    but its only consumer `mediaPath` is referenced NOWHERE. Both lines go. Correcting the
    string would resurrect dead code.
  - `default.py:10` `import requests` and `default.py:194` `OPEN_URL` - `OPEN_URL` is called
    from nowhere. Delete both. (Lazy-importing is the wrong fix: Kodi keeps `sys.modules`
    across script invocations in a session, so the cost is once per boot, not per menu open.)
  - `service.py:31` `maxpackage_zips` is read, never used. `purgePackages`'s local `dialog`
    is assigned, never used. `purgePackages`'s FIRST `os.walk` (199-201) only counts, and the
    count is unused (the confirm dialog is commented out).
- [x] **6. Guard `getNextMaintenance` after all - a REAL cross-process crash path (found in
      the 2026-07-09 full sweep; supersedes the rejection below).** `default.py:170`
      (`MAINTENANCE()`) calls `maintenance.getNextMaintenance()` from the PLUGIN process.
      The window property is only set by the SERVICE's `determineNextMaintenance()`, and
      today's service can sit in its boot preamble for arbitrarily long (it can be parked on
      a modal yesno). Open the Maintenance submenu in that window and `int("")` throws
      ValueError: the listing fails to render. Guard with a default of 0 on empty/invalid.
      Item 1 narrows the window (Monitor() init runs before the relocated preamble) but does
      not close it; the guard is one line.
- [x] **7. Excise the dead Wizard/Builds machinery (~350 lines).** The recent settings.xml
      rewrite REMOVED the Wizard Creator settings (`enable_wiz1-5`, `name/url/img1-5`,
      `backup_database`, `backup_addon_data`, `remote_backup` - none are in the current
      settings.xml), but the code half survived. Verified unreachable and delete together:
  - `default.py`: the `wizard1-5` module-top reads (27-31); `USB`/`backupfull`/
    `backupaddons`/`backupzip` (32-35) and `backup_zip` (48), all unused; `ENABLE_WIZARD()`
    (67-76, zero callers); `BUILDS()` (199-297, its empty-state row points at a
    "Settings > Wizard Creator" section that no longer exists); the `builds` route (524) -
    NO menu entry anywhere generates `action=builds`, so it and everything behind it is
    unreachable; the `install_build` route (571-584); `CAT_TOOLS()` + the `tools` route
    (the TOOLS menu row is commented out at 105); `REMOVE_EMPTY_FOLDERS()` (339-355, zero
    callers); the dead video-addon querystring params (474-504: `title year tvdb tmdb
    season episode tvshowtitle premiered image meta select query content` - `select` is
    even shadowed at 563).
  - `wiz.py`: `skinswap()` (168-206, only caller is the dead `install_build` route; it
    does sleep-then-`ReloadSkin` from a plugin thread, the exact pattern memory says hangs
    Kodi - good riddance); `buildInstaller()` (1103-1128, whose own comment at 1118 says
    "buildInstaller is dead (removed in a later PR)"); the DOWNLOADER block (1135-~1210,
    `downloader`/`customdownload`/`_pbhook` - only caller is `buildInstaller`);
    `ENABLE_ADDONS()` (120, zero callers). Keep `get_Kodi_Version`/`FIX_SPECIAL` (used by
    `backup`).
- [x] **8. Stop creating GUI objects at import time; delete control.py's dead surface.**
      `control.py` runs on EVERY plugin invocation (imported at `default.py` top) and
      instantiates at module scope: `progressDialog = DialogProgress()`, `progressDialogBG`,
      `windowDialog = xbmcgui.WindowDialog()` (allocates a real GUI window), `player =
      xbmc.Player()`, `playlist`. Only TEN control attrs are used anywhere (`setting`,
      `selectDialog`, `infoDialog`, `USERDATA`, `openSettings`, `HOME`, `addonInfo`,
      `addonIcon`, `addonFanart`, plus `idle` internally - usage counts verified by grep).
      Everything else goes, including the latently BROKEN `addonThumb`/`addonPoster`/
      `addonBanner`/`addonNext` (they call an undefined `appearance()` and call the string
      `artPath` as a function - instant crash if ever used). Same pattern, smaller: the
      module-top `dp = xbmcgui.DialogProgress()` in `wiz.py:38` and `tools.py:30` - keep
      only if actually consumed at module level, else make local.
- [x] **9. maintenance.py leftovers (fold into item 4's helper).** The two ATV2 blocks
      (`clearCache` 105-135) target the 2010 Apple TV 2, a platform Kodi dropped a decade
      ago; the fleet is Fire TV + Apple TV 4K on Kodi 21. Delete. The `cacheEntries = []`
      loop (137-151) iterates a hardcoded empty list. Delete.

**Deliberately NOT touched (in scope of the sweep, left alone on purpose):** `speedtest.py`
(reachable from the menu, vendored speedtest-cli, works); `dropbox_remote.py` retry sleeps
(user-invoked flows, not the service); `nsub.py`/`nsud.py`/`onetap.py`/`ui.py` (recent
owner-authored hardened code, reviewed separately); `FRESHSTART`'s swallow-all-then-report
(a deliberate wipe-robustness choice - flag to the owner only if it bites).

**Explicitly REJECTED, do not redo these (measured/verified 2026-07-09):**

- **`os.scandir` + `entry.stat().st_size` is NOT "several times faster."** That is a
  Windows-only property. On Unix `DirEntry.stat()` always issues a stat syscall; what scandir
  gives free is `is_dir()`/`is_file()` from `d_type`, not size. And `os.walk` already uses
  scandir internally. Benchmarked over 20,000 files: 29.3ms vs 25.3ms, i.e. 14%. Item 1 deletes
  100% of that cost, so the micro-optimization is moot.
- **"Skip the scan when the alerts are off"** is not expressible today. `resources/settings.xml`
  gives `filesize_alert` a minimum of 25 and `filesizethumb_alert` a minimum of 50, so there is
  no off value, and `notify_mode` consumes both totals anyway. Needs a schema change first.
- **"`clearCache` walks trees it is about to delete"** is false. `os.walk` is a lazy generator:
  it recurses into `dirs` only AFTER the loop body runs, by which point `rmtree` removed them,
  `scandir` fails, and `onerror=None` swallows it. You already pay one top-level pass.
- **Raising the monitor tick from 10s to 60s** is fine but buys nothing measurable.
  `logMaintenance` is indeed a no-op (`maintenance.py:262`), so the formatted strings at
  `service.py:179-182` are discarded, but that is six string formats per minute and there is no
  disk in that loop. Do it for tidiness; do not sell it as a perf or disk-wear win.
- **CORRECTION (2026-07-09 sweep): guarding `getNextMaintenance` is now item 6.** The first
  review pass rejected it as unreachable, reasoning only about the SERVICE process (where
  `Monitor.__init__` does set the property first). That reasoning missed the second consumer:
  `default.py:170` calls it from the PLUGIN process, where nothing guarantees the service got
  there first. Wrong call, superseded. (Still true and still low-priority: the
  `if autoCleanDays is None` guards at `maintenance.py:221` are dead, since `getSetting`
  returns `""` and never `None`; only the schema defaults keep `int()` from raising.)

**Gate (the WORKFLOW block above applies in full).** Item 4 is a behavior change and needs a
test before commit. Items 1-3 change the boot path, so this **must** get a real-device verify
(kodi.log plus a timed cold boot) on a Fire TV or the Apple TV. A code-only "fixed" claim on
this add-on has burned the owner repeatedly: see
`docs/incident-2026-07-08-ezmpp-repeated-hardware-burns.md`. Do not claim a boot-time
improvement without a timed run on the box; cheap-box I/O is where syscall intuitions fail.

**Open question before committing:** confirm the release path for this add-on. It is
date-versioned (`2026.07.09.0`), not single-digit semver like the other `script.*` add-ons, so
verify `release.py` / `check_versions.py` handle it before relying on the usual flow.
RESOLVED (see the outcome block): the date scheme needs an explicit
`--version`; everything else in the flow works unchanged.

---

## Estuary 7 - fork-by-build the skin - 🔲 ACTIVE (2026-07-14: Phases 0-4 done, Phase 5 not started)

> **The patch-vs-fork decision has been REVERSED (owner, 2026-07-10).** After the 1.8.0
> bold sweep the overlay rewrites 50+ skin files at runtime, and upstream Omega is
> maintenance-only (b-jesch moved to Kodi 22 "Piers") - so the overlay's "ride upstream
> for free" benefit is gone while its machinery remains. The new home is a STANDALONE
> repo `~/Code/moquette/estuary7`: fork-by-build, id `skin.estuary7`, built from pinned
> upstream `8d9b2c7c` (21.4+omega.4, verified byte-identical to the fleet's stock via
> the Office box .bak snapshots), shipped via GitHub Release assets (the proxy engine's
> plain-URL/`release_asset://` support is live-verified). Full phase plan + decision
> record: **`~/Code/moquette/estuary7/docs/PLAN.md`**. Upstream is ALREADY at omega.5 -
> do not let that auto-land surprise anyone; the omega.5 rebase is a deliberate
> post-baseline exercise.
>
> THIS repo's involvement comes in later phases: Phase 2 (hosted metadata +
> repository.json entry + proxy release), Phase 4 (SKIN_ID flip in setup/skin.py +
> bootstrap, probes simplification, EXPECTED_NET_INSTALLED), Phase 5 (modv2plus 2.0.0
> becomes a one-shot migrator), Phase 6 (retire modv2plus, correct the playbook's wrong
> "MIT" license note - upstream is GPL-2.0 code + CC-BY-SA-4.0 art). Until Phase 5, the
> fleet stays on overlay 1.8.0 - nothing regresses.
>
> **Status update (2026-07-14 doc audit):** Phase 2 shipped as proxy release 2.2.7
> (`addons/hosted/skin.estuary7/` + the `repository.json` entry). Phase 4 shipped as
> library 1.9.0 + bootstrap 2.3.0 (commit `077a60a`, release `e564b78`) - `SKIN_ID` ->
> `skin.estuary7`, `_install_skin` direct-extracts the fork's release asset, seeds the
> skinshortcuts properties, no longer installs modv2plus on fresh boxes. The skin itself
> has since moved past its Phase 3 baseline to **1.0.38** on the bench (a whole
> post-launch hardening arc, 1.0.28-1.0.38, none of it a formal phase - see
> `~/Code/moquette/estuary7/TASKS.md`, especially the 1.0.36-1.0.38 tvOS restore
> self-heal / every-boot menu-rebuild-loop saga, cross-linked from
> `docs/incident-2026-07-14-ezmpp-restore-wiped-custom-menu-tvos.md` below). Phase 5
> (fleet migration) and Phase 6 (retirement) have **not** started; the 6-box fleet
> (beyond the bench) is still on overlay 1.8.0.

## EZ Maintenance++ repo migration + tvOS storage hardening - ✅ DONE (2026-07-14)

> **EZ Maintenance++'s source, full test suite, and build/release tooling moved OUT of
> this repo to its own standalone repo, `moquette/ezmaintenanceplusplus`** (public, same
> "own repo + GitHub Release asset" pattern already proven for `skin.estuary7`/
> `moquette/estuary7`). This repo previously held BOTH a copy of the add-on source
> (`addons/script.ezmaintenanceplusplus/`, now DELETED) AND, separately and exclusively,
> its full test suite (`_tools/test_ezmaintenanceplusplus_*.py` + fakes) - a split that let
> the two source copies drift for weeks (fixes landed proxy-side without traveling back
> to the standalone repo's stale copy). That duplication is gone: this repo now carries
> only a hosted metadata mirror (`addons/hosted/script.ezmaintenanceplusplus/` -
> `addon.xml` + `icon.png` + `fanart.jpg`, hand-synced to the released version) and
> `repository.json`'s `assets.zip` pointing at the other repo's release asset. Full
> record: `moquette/ezmaintenanceplusplus`'s own `RESUME.md` + `README.md`; triage guide
> here: `.claude/skills/ezm-backup-doctor/SKILL.md` (verified current in this audit).
>
> **Also shipped this session, migrated into the new repo's `tests/`:** the chokepoint
> lint banning a raw userdata-XML write that bypasses `nsud.persist_one`
> (`test_no_raw_userdata_writer.py` - written after an adversarial review found the SAME
> bug class already fixed once, unguarded, in a second function nobody had tested); a
> two-layer tvOS storage fake (`fake_kodi_sandbox_io.py`) plus contract tests covering
> `ControlImage` write-through and the foreign-local-VFS-read bug; and a machine-generated
> hardware-verification gate (`tools/verify_device.py` +
> `test_storage_change_requires_device_verification.py`) that pulls live device evidence
> over JSON-RPC and fails a change to `nsud.py`/`boxsetup.py` that lacks a fresh
> `verification/<version>.json` artifact - `verification/2026.07.14.1.json` is the first
> one. Full suite in the new repo: 203 passed / 1 skipped, ruff clean.
>
> **Corrected fact, now consistent everywhere (2026-07-14):** `xbmcvfs.delete()` CANNOT
> delete a userdata `*.xml` on tvOS - it drops the NSUserDefaults key and reports success;
> the POSIX file is left on disk. And Kodi does NOT re-materialize a disk file from its
> NSUserDefaults mirror - a key SHADOWS the disk, nothing ever copies it back. Six docs +
> the auto-loading agent memory carried the disproven "rewrites disk from the mirror"
> model; all six are corrected, and `_tools/test_no_false_tvos_belief.py` now fails CI if
> that sentence reappears unmarked. Authoritative model: `.claude/skills/kodi-storage-map/SKILL.md`.
>
> **RESOLVED (2026-07-15):** the proxy release flagged here as outstanding has shipped.
> `repository.tony7bones` is released and live at v2.5.0 (tagged, Pages serves
> `repository.tony7bones-2.5.0.zip`), whose baked `repository.json` points
> `script.ezmaintenanceplusplus` at the `moquette/ezmaintenanceplusplus` release asset.
> **Hardware-verified on the Office Fire TV bench (2026-07-15, later the same day):**
> the box self-updated to 2.5.0 (JSON-RPC `Addons.GetAddonDetails`), its ON-BOX engine
> serves the full 31-entry catalog with a matching md5 (fetched through an adb tunnel
> to `127.0.0.1:61234`), and the EZM++ 2026.07.15.0 zip - the exact fetch that caused
> the deadlock - streams through the on-box engine as a valid 42-member zip
> (`zipfile.testzip()` clean). Scope: ONE box; the other six are confirmed by the
> static-conversion convergence checks (P0 Phases 3/5), not by this note.
> The 2026-07-15 engine-404 fleet deadlock this gap caused (and its fix, engine
> hardening in 2.4.9) is written up in
> `docs/incident-2026-07-15-proxy-engine-404-fleet-deadlock.md`.

## ATV2 caches-wipe recovery + system-wide thin fonts - ✅ DONE (2026-07-10, modv2plus 1.7.0 + 1.8.0)

> **1.8.0 addendum - the FULL bold sweep ("no bold ANYWHERE").** 1.7.0's font-table swap
> left headers bold (owner spotted PVR "Categories"/"Channel groups" on ATV2) because bold
> has THREE sources in this skin, and a fontset fixes only one:
>
> 1. bold font FILES - fixed 1.7.0 (Font.xml re-binds, Default fontset);
> 2. `<style>bold</style>` declarations - synthesize bold via FreeType REGARDLESS of the
>    bound file; 1.8.0 neutralizes the three UI ids (font10/12/37_bold) in Default
>    (lyrics faces keep theirs - decorative, not chrome);
> 3. literal `[B]..[/B]` MARKUP in ~46 window XMLs - also synthetic, no fontset can help.
>    1.8.0 pre-strips our 4 shipped XMLs (86 tags) and adds `sweep_bold_markup()`: at
>    apply time every non-ours skin xml loses its [B]/[/B] (one-time .bak, per-file
>    fail-soft, idempotent, governed by the existing version sentinel). `restore_patches`
>    gained a generic *.xml.bak revert for swept files - SKIPPING `FILES` (during dev the
>    first cut skipped only PATCH_FILES and un-laid the SHELL, deleting the master toggle;
>    the existing keeps-the-shell test caught it).
>
> Verified: Office Fire TV apply = 42 swept / 0 failed, PVR channel list renders regular,
> live skin greps ZERO [B] outside .baks; ATV2 pushed to 1.8.0 directly (tvOS build has no
> GUI.ExecuteBuiltin JSON method - devicectl push + restart; boot service auto-applied:
> 42 swept, menu rebuilt). 113 modv2plus tests (6 new sweep/static contracts).

> **What happened:** tvOS purged ATV2's `Library/Caches` overnight (the koditvbox build
> keeps Kodi's whole home there - a LEGAL eviction target; box is on a tvOS 26.6 beta).
> Every installed add-on and file-based artifact vanished; the build's NSUserDefaults
> plist persistence saved the userdata (guisettings, favourites, sources, ALL addon_data
> incl. the RD token and EZM's One-Tap pins). Kodi fell back to the APP-BUNDLED stock
> Estuary - whose regular-weight fonts the owner loved ("I WANT THIS FONT").
>
> - **Restore (done):** drove EZM One-Tap remotely - devicectl-pushed a bootstrap EZM
>   (requests requirement dropped; the vfs path never imports it) + a temporary
>   `script.t7b.devtools` builtin-runner (RunScript bridge + pin fixer; wiped by the
>   restore itself), re-aimed pin 1 at `base_skin_iptv_202607091111.zip` (the old pin's
>   zip had been rotation-pruned; port-FREE nfs url), owner pressed Wipe+Restore on the
>   TV. 173 add-ons back; benign EPG-settle noise only. ATV2 now runs restored data ON
>   stock Estuary (the skin setting from the fallback survived) - owner chose to KEEP it
>   there for now ("Both" decision).
> - **Fonts (shipped):** modv2plus **1.7.0** ships `Font.xml` as a PATCH_FILES entry -
>   the skin's Default fontset with NotoSans-Bold -> Regular (exact stock-Estuary parity:
>   Estuary binds every `*_title` id and `font_MainMenu` to Regular) and
>   RobotoCondensed-Bold -> Light (the four flag badges; family-internal, metric-safe).
>   Font-id inventory byte-identical; Arial/ArialUnicodeMS/Economica/lyrics fontsets
>   untouched. This CONSCIOUSLY SUPERSEDES the 1.5.0 rule "never ship Font.xml" (its two
>   test pins replaced by structural guards: inventory intact, no bold in Default,
>   sidenav ids keep stock binds). QA: zero defects (byte-level diff census = exactly 16
>   face swaps + header). Device-verified on the Office Fire TV: apply clean, home menu
>   renders regular-weight, zero font errors. Fleet gets it via auto-update + boot-service
>   re-apply; ATV2 gets it whenever the owner switches it back to MOD V2.
> - Ops notes for next time: tvOS can re-purge Caches on ANY Apple TV Kodi (backups are
>   the mitigation); `devicectl` file listing/copy works while asleep but app LAUNCH does
>   not; the koditvbox plist persistence is why "blank" boxes remember their skin/config.

## KodiShare backup mirror - ✅ DONE (2026-07-09, commits `574f5f0` + `d416ce9` + `fd3343b`)

> **The mini share (`/Volumes/KodiShare`) now tracks releases automatically.** Full contract:
> `docs/playbooks/release-and-deploy.md` § "KodiShare backup mirror"; implementation
> `_tools/sync_share.py`, pinned by `_tools/test_sync_share.py` (26 tests, 95% cov).
>
> - **Origin:** a fossil `repository.tony7bones-1.0.5.zip` on the share pointed at the
>   long-dead `repo/` layout - installed cleanly on a fresh box, then silently served
>   NOTHING (and was a refused downgrade on current boxes). A June EZM++ zip sat in
>   `apps/` predating the entire July backup/restore hardening - sideloading it to
>   restore a wiped box would have resurrected exactly the bugs the July releases fixed.
>   A full share audit also found `media/` one canvas rename behind (the old image under
>   the old filename, `background.jpg` missing).
> - **What syncs:** `repositories/` (current root installer + `dropbox/repositories/`
>   zips; superseded installer versions pruned); `apps/` (first-party add-on zips,
>   OPT-IN-BY-PRESENCE - drop any version of an add-on there once and the sync keeps it
>   current; stale copies pruned only AFTER the fresh copy lands); `media/` + `rss/`
>   (canvas 1:1, strictly additive, nothing ever deleted). NOT `iptv/` - the mini's
>   populator daemon owns that.
> - **Triggers (every publish path):** `publish_canvas.py` post-push, and
>   `.githooks/pre-push` (main only) - the hook is what covers add-on releases, which
>   publish via plain `git push`. Manual: `python3 _tools/sync_share.py [--dry-run]`.
>   (Amended 2026-07-19: this list previously led with `deploy.py` post-push "incl.
>   `release.py --proxy`". Both were deleted with the proxy engine on 2026-07-15; the
>   pre-push hook is now the only automatic trigger.)
> - **Hard guarantees:** only when the volume is mounted (skip note otherwise - never
>   creates dirs, never mounts, NEVER fails or blocks a release/push); additive toward
>   owner-curated foreign files; SANDBOX-SAFE by construction (`sync_share.py` stays OUT
>   of the system tests' sandbox copy lists, the tools import it behind
>   `try/except ImportError`, and a test fails the suite if anyone adds it to a copy
>   list). Verified adversarially: full suite run with before/after fingerprints of all
>   four share dirs - untouched.
> - **Declined (owner, 2026-07-09):** stocking a Kodi 21.3 APK on the share for
>   factory-reset cold starts - the share presumes Kodi is already installed.
> - Observation, no action: `profile/RssFeeds.xml` duplicates `rss/`'s copy (identical
>   content, not in the canvas); the sync treats it as foreign.

---

## Bedroom box - full-customization backup + clone-restore test - 🔲 ACTIVE

> Operational (not a repo code change). Backup system + runbook live OUTSIDE the repo:
> on the box at `/storage/emulated/0/_T7B/kodi/backups/snapshots/` (survives a Kodi wipe)
> and mirrored on the Mac at `~/T7B-backups/snapshots/`. Full method: that dir's
> `README.txt`. Box = Bedroom Fire TV, `192.168.7.84`, Kodi 21.3 Omega.

Sequence (do in order - do NOT wipe/test until the fresh backup is taken):

- [ ] **1. Fine-tune** - owner finishes tweaking remaining items (video add-ons, program
      add-on settings, skin, etc.) so the box reflects FULL customization.
- [ ] **2. Fresh full backup** - re-snapshot BOTH halves capturing the final state:
      `bedroom-userdata-<date>/` (settings/data, IPTV EPG cache stripped) +
      `bedroom-addons-<date>/` (programs). Mirror both to the Mac. These supersede the
      throwaway `2026-06-10` snapshots.
- [ ] **3. Clone-restore test** - `pm clear org.xbmc.kodi` (pristine, NO bootstrap) →
      copy both folders into `.kodi` → open Kodi → verify it boots identical (skin =
      Estuary MOD V2, ~69 add-ons enabled, POV/resolveurl/pvr.iptvsimple present, RD
      token intact, home-screen screenshot). Backups make this fully recoverable.

---

## Mini / home-server ops - open items 🔲 ACTIVE

> Operational (not a repo code change). Mac mini home server, reachable at
> `192.168.7.2` (WiFi; eero DHCP reservation WiFi -> .2, wired -> .3). Context: the
> 2026-07-02 session fixed Kodi<->mini NFS (a SurfShark per-app VPN was tunneling
> Kodi's traffic through the VPN), mini Screen Sharing (disabled Kerberos so the
> Finder button falls back to password auth), the Hue / HomeKit lights (bridge was
> plugged into the modem, moved behind the eero -> `192.168.7.69`), and iptv2 (now a
> system LaunchDaemon at 10am/4pm, was a broken user agent). These remain open:

> **2026-07-02 REORG DONE (Model B - data vs workers split):** the mini home is now
> `~/Kodi/{Share,Backup,services/{iptv,backup}}` (+ `~/Kodi/.attic`). **DATA:** `Share`
> = NFS/SMB export, content-only (`apps iptv media repositories rss`); `Backup` =
> ATV1/ATV2 device backups. **WORKERS:** `services/iptv` = the populator (package
> renamed `iptv2`->`iptv`, daemon runs `python3 -m iptv`, logs `services/iptv/logs`).
> The `services/backup` worker was later TRASHED per owner (see item 1) - only
> `services/iptv` remains; `~/Kodi/Backup` (the data folder) is kept.
> NFS export + SMB "KodiShare" share both repointed to `/Users/moquette/Kodi/Share`;
> bedroom box source -> `nfs://192.168.7.2/Users/moquette/Kodi/Share/`; the IPTV output
> folder renamed `Share/2.0/iptv`->`Share/iptv` (`nfs_base=nfs://KodiShare/iptv`).
> Daemon + providers.yaml + backup scripts (`BASE_PATH`) + crontab all repointed and
> verified live. Logs kept per-service (not a top-level `~/Kodi/logs`).

- [x] **1. Backup rotation/sync - TRASHED per owner (2026-07-02).** Owner decided the
      rotation + sync machinery isn't needed ("all we need is the backup folder").
      Removed the cron jobs (crontab is now EMPTY) and retired the whole
      `services/backup` worker (kodi_rotate/kodi_sync/kodi_git_sync/cert_reminder +
      its sync tree: git-config, profiles, pvr-config, restore_points) to
      `~/Kodi/.attic/services-backup` (recoverable). `~/Kodi/Backup` (ATV1/ATV2 device
      backups) is KEPT as-is. Trade-off: nothing prunes backups now, so `~/Kodi/Backup`
      grows over time (currently ~1.1G, and the boxes write into nested `ATV*/EZM/` +
      `ATV*/KB/` from two backup tools) - clean up by hand if it gets large. Purge
      `~/Kodi/.attic` when sure none of it is needed.
- [x] **2. Share declutter - DONE (2026-07-02).** Reorganized as above; the TV browse
      is now content-only. `_eztest` (test 777) + legacy top-level `iptv` (superseded
      by `2.0/iptv`, no local EPG, no box referenced it) moved to `~/Kodi/.attic`
      (recoverable); empty `1.0/` removed; `backups/` + `sync/` surfaced out of the
      share. Tier 3 ALSO DONE: renamed `Share/2.0/iptv` -> `Share/iptv`
      (providers.yaml `output.root` + `nfs_base` -> `nfs://KodiShare/iptv`,
      regenerated all 8 artifacts, old `2.0` wrapper in `.attic`); low-risk because no
      live box reads the mini NFS for IPTV (bedroom has no pvr.iptvsimple config, zero
      active 2049 conns). CAVEAT: if the repo box Setup/`apply_iptv` hardcodes
      `2.0/iptv` anywhere, update it there so future box provisions use `iptv`.
- [x] **3. Gigabit switch (mini back to WIRED) - DONE (2026-07-02).** Netgear switch on
      the eero's single LAN port -> mini AND Hue both wired. Mini moved off WiFi to wired
      `en0`, WiFi turned OFF (`en1` down). Addressing finished DHCP-native: the eero's WIRED
      reservation (MAC `d0:11:e5:7a:05:ec`) now hands `en0` -> `.2` (the old WiFi `.2`
      reservation was removed), so `en0` reports `DHCP Configuration` at `192.168.7.2` - a
      real reservation, NOT the manual/static hack. Both Kodi NFS exports live, ~8-14ms
      wired. (The flip auto-reverted to static once when the eero change hadn't propagated,
      then stuck on the retry.)
- [x] **3a. WiFi keepalive - REMOVED (2026-07-02).** No longer needed now the mini is WIRED
      (the radio-nap latency problem only existed while WiFi was the primary link). Retired
      the daemon: `launchctl bootout system/com.moquette.wifi-keepalive` + removed the plist + `~/bin/wifi-keepalive.sh`. Verified gone.
- [x] **3b. iptv populator daemon - CONFIRMED LOADED (2026-07-02).** After the network/reboot
      work `com.tony7bones.iptv2` was booted out; re-bootstrapped clean (bootout ghost ->
      enable -> bootstrap). Verified `- 0 com.tony7bones.iptv2` in `launchctl list`, both
      calendar fires (10:00 + 16:00) registered, last populate run built 492 channels + EPG.
      Op-note: over SSH to the mini WITHOUT a PTY, a bare `sudo` fails silently on the
      password prompt (`2>/dev/null` hides it) and reads come back empty/false-negative -
      pipe the password once per shell: `printf 'test\n' | sudo -S -p "" -v` then reuse.

> Reference: memory files `mini-nfs-kodi-share`, `mini-screensharing-kerberos`,
> `home-network-topology`, `mini-iptv2-share-populator`.

---

## Release automation - kill manual version bumping - ✅ TRACK COMPLETE (2026-06-10)

> Design + phase log: **`docs/plans/release-automation.md`** (LOCKED owner decisions
> O1-O10, the QA must-fixes MF-1…MF-9). Committed LOCALLY on `no-computer-setup`, NOT
> pushed. No add-on versions were bumped by this work - the TOOL is what bumps.
>
> **DONE (2026-06-10), later simplified by the static conversion.** `python3
_tools/release.py` is THE release command for every add-on. As shipped in
> 2026-06 it routed two paths: the `script.*` add-ons AND the `repository.tony7bones`
> proxy (`--proxy`, delegating to `deploy.py`). When the proxy engine was retired
> (2026-07-15), the proxy path, `deploy.py`, and the shared-library "lockstep" were
> DELETED - `repository.tony7bones` is now a normal static-only add-on released the
> same single way as any other. The manual `addon.xml`/news/pinned-test ritual is
> gone; CI runs the per-add-on version-bump gate on `main` (O7). The checkboxes
> below are the historical implementation record.

- [x] **P0** Generalize `release_lib`: `next_version`, `set_import_version` /
      `read_import_version` (lockstep), `prepend_addon_news` (capped + idempotent,
      MF-9); `set_addon_news` REPLACE kept for `deploy.py`. +19 unit tests, 99% cov,
      no add-on bump. Shipped 2026-06-10.
- [x] **P1** De-pin the two literal version tests → relational + negative tests.
      Shipped 2026-06-10 (pre-existing).
- [x] **P2** ONE shared `changed_addons(repo, base_ref, *, worktree)` detector (tool + gate route through it, MF-1); `check_versions.py` inline diff REPLACED by the
      call; `check_versions.py` wired into CI on `main` (O7).
- [x] **P3** `_tools/release.py`: detect → bump (minor default / `--patch`/`--major`/
      `--version`) → auto-draft+prepend news (`--news` override) → lockstep (MF-2) →
      regen → determinism gate → commit on branch; `--dry-run` (shows WHICH files,
      MF-4), `--push`, `check`; guardrails dirty/behind-origin (MF-5)/monotonic/ceiling
      (MF-8)/idempotent (MF-6); rollback on any failure. Bare-remote e2e tests.
- [x] **P4** `release.py` is the documented release command for BOTH paths; the
      manual ritual purged from CLAUDE.md / the playbook / the SKILL; the version
      tables noted as auto-derived; the pinned-test caveat removed (de-pinned in
      P1). Shipped 2026-06-10.
- [x] **P5** Unify: `release.py --proxy` (and proxy auto-detect) runs the proxy
      release by **delegating to `deploy.py`'s exact transaction** (`deploy.deploy`) -
      NOT a reimplementation; `deploy.py` stays an independent fully-working entry
      point with `test_deploy.py` UNCHANGED, and a parity test proves the resulting
      tree+remote are identical via either entry point. +17 e2e/in-proc tests, 92%
      cov on `release.py`. Shipped 2026-06-10.
- Open owner Qs - all RESOLVED: **O8** lockstep test strict `==` (LOCKED permanent),
  **O9** scoped `--addon` auto-includes the dependent, **O10** idempotent re-run is a
  no-op with a message.

---

## ▶ HISTORICAL, NOT YOUR NEXT STEP - P1: extract the IPTV builder into its own PRIVATE repo (see the P1 track near the top)

> **SUPERSEDED 2026-07-17. Heading annotated 2026-07-18; text below left
> intact.** This extraction is DONE: the P1 track near the top of this file
> marks it `✅ DONE 2026-07-17`, the builder lives in `moquette/iptv` (local
> checkout `~/Code/moquette/kodi/iptv`), and `_tools/build_iptv.py` was removed
> here in commit `b16ea06`. The original "VERY NEXT STEP" wording sent
> returning agents at finished work, which is why this banner exists. For the
> IPTV project's real open items, see `~/Code/moquette/kodi/iptv/TASKS.md`.

---

> **N2-N5 CANCELLED (owner decision 2026-06-10): "nuke N2… our .env method is working
> fine."** The device-resident `.env.<device>` delivery mode (owner edits `.env.<device>`
> on the Mac → drops it at the box's `/storage/emulated/0/_T7B/` → Setup reads, applies,
> never deletes it; scaffolds a template if missing; self-creates the folder tree) is the
> CHOSEN, WORKING solution - proven across all 5 boxes (Office, Bedroom, Travelstick,
> Travelstick2, Shield). The on-box config collector (N2 prefs/weather, N3 IPTV creds
> interview, N4 in-Kodi IPTV build, N5 remote-only acceptance) was only for the
> "no env file at all, configure from on-screen dialogs" case - which the owner does not
> need. The no-computer-setup track is CLOSED at N1.2 (shipped, live). Its open questions
> Q2-Q5 are moot (collector-only). No active track queued; await direction. Cancelled
> detail: `docs/plans/no-computer-setup.md`.

## ▶ HISTORICAL, NOT YOUR NEXT STEP - prior next-step, N2 on-box config collector (CANCELLED)

> **Annotated 2026-07-18; text below left intact.** Everything in this section
> is cancelled or deleted work, but it runs for roughly 90 lines and contains
> detailed "Next: N2..." instructions plus two owner questions (Q2 RSS list, Q3
> web-server default) that the block just above declares moot. The whole
> subject (`script.tony7bones.bootstrap`, `script.module.tony7bones`) has since
> been RETIRED AND DELETED. Read for archaeology only.

---

> **Phase N1.2 is RELEASED to `main` (2026-06-10)** - `script.tony7bones.bootstrap`
> **1.8.0** + `script.module.tony7bones` **1.5.0** (release commit `74e4553`,
> fast-forward merge of `no-computer-setup`; proxy untouched at 2.2.1; live-verified:
> the 1.8.0/1.5.0 zips serve 200 from raw `main`, the old 1.7.0/1.4.0 zips 404,
> `addons.xml` advertises both new versions and the bootstrap's `<requires>` on the
> library is 1.5.0). Onboarding (`run()` first statement + every route: Express,
> Guided, and the no-env wizard) now **self-creates** the `_T7B/kodi/{backups,iptv,
media,repositories,rss}` device staging tree via the shared library's new
> `ensure_device_dirs()` / `DEVICE_STAGING_SUBDIRS`; the provisioner `mkdir -p`s the
> same set; and the `IPTV_STAGING_DIR` injection now requires a **NON-EMPTY** `iptv/`
> dir, fixing the empty-dir false-Express route. Gate at release: 856 passed / 1
> xfailed, ruff clean, deterministic regen (byte-identical second run), version-bump
>
> - consistency gates green on main. Auto-update impact on completed boxes: they
>   auto-update the library 1.4.0 → 1.5.0 (an import-only superset - adds
>   `ensure_device_dirs`/`DEVICE_STAGING_SUBDIRS` + the staging guard; idempotent
>   mkdir, no behavior change on a configured box - benign); the bootstrap
>   self-uninstalls so 1.8.0 is not on completed boxes (it lands only on the next fresh
>   Setup install from the repo). Full record: the N1.2 build-log entry in
>   `docs/plans/no-computer-setup.md`.
>
> **Phase N1.1 is RELEASED to `main` (2026-06-10)** - `script.tony7bones.bootstrap`
> **1.7.0** + `script.module.tony7bones` **1.4.0** (release commit `4ce11ec`,
> fast-forward merge of `no-computer-setup`; proxy untouched at 2.2.1; live-verified:
> the 1.7.0/1.4.0 zips serve 200 from raw `main`, the old 1.6.0/1.3.0 zips 404,
> `addons.xml` advertises the new versions and the bootstrap's `<requires>` on the
> library is 1.4.0). The owner PLACES the device-resident master env at the BRAND
> ROOT `/storage/emulated/0/_T7B/` (dot-optional `env.<device>`); the STAGING tree
> `/storage/emulated/0/_T7B/kodi/` (layout: `backups/ iptv/ media/
repositories/ rss/ scripts/`) is one level below it; the old `kodi/tony.7.bones/` root is a read-only
> LEGACY fallback (read second, never written). The device-resident MASTER
> `.env.<device>` lives at the canonical root, is read with provisioner-parity
> derivation (`DEVICE_IP` dropped, `IPTV_STAGING_DIR` injected iff staged), and is
> **NEVER deleted** (wipe-and-redo forever); only the derived `tony7bones.env`
> (both roots) + the profile-local collector env are terminal-deletable. With NO
> env anywhere Setup SCAFFOLDS the comment-disabled master template
> `env.<device-name>` (no leading dot) at the BRAND ROOT (bundled
> `resources/env.device.example`, drift-pinned byte-identical to the committed
> `.env.device.example`) and still opens the wizard. Provisioner push targets (env +
> IPTV staging) moved under `_T7B`; `DEVICE_FILE_COPIES` reads both roots (canonical
> first). Env-source order: derived (canonical → legacy) → masters (brand root →
> staging → legacy, sorted) → profile-local. Gate at release: 839 passed / 1 xfailed,
> ruff clean, deterministic regen, version-bump + consistency gates green on main.
> **DEVICE-PROVEN (2026-06-10): the Office Fire TV ran the working-tree N1.1
> Express end-to-end off the device-resident master alone (no derived env, no
> adb-pushed `tony7bones.env`) - full box verified (MOD V2 + patch, both IPTV
> providers 1:1 with the host build, 555 channels, restart-survival) and the
> master `.env.office` SURVIVED the run untouched.** Full
> record: the N1.1 build-log entry in `docs/plans/no-computer-setup.md`.
> Auto-update impact on completed boxes: they auto-update the library 1.3.0 → 1.4.0
> (an import-only superset - new env-source helpers + scaffold; no caller change on a
> box that already has its env - benign); the bootstrap self-uninstalls so 1.7.0 is
> not on completed boxes (it lands only on the next fresh Setup install from the repo).
>
> **Phase N1 is RELEASED to `main` (2026-06-10)** - `script.tony7bones.bootstrap`
> **1.6.0** + `script.module.tony7bones` **1.3.0** (release commit `fbf4b24`, merge
> `38b9237`; proxy untouched at 2.2.1; live-verified: the 1.6.0/1.3.0 zips serve 200
> from raw `main`, the 1.5.0/1.2.0 zips 404). Auto-update impact on completed boxes:
> they will pull library 1.3.0 (an import-only change - benign); the bootstrap is not
> installed on completed boxes (it self-uninstalls). N1 = routing + env-source
> generalization: NO env anywhere →
> `run_guided({})` (the remote-only user lands in the wizard, with the
> "Install everything with defaults" one-tap escape = the exact old no-env Express);
> env present → byte-identical provisioned routing (no `SETUP_MODE` → Express,
> `SETUP_MODE=guided` → wizard); ordered env sources (`BOX_ENV_PATH` wins →
> profile-local second) with terminal deletes covering both; the provisioner now
> ABORTS pre-Setup on a failed env push. **The track's contract: THREE first-class
> delivery modes** (owner directive) - (1) adb provisioner, (2) self-contained
> user-placed env at a device env path (no adb - documented + test-pinned), (3) no
> env → the Guided wizard. Full record: the N1 build-log entry in
> `docs/plans/no-computer-setup.md`. Gate evidence: 797 passed / 1 xfailed, env.py
> 100% / default.py 98%, five keystone mutations killed, clean-Kodi live verify
> (no-env wizard render + Foundation gate walk + MOD V2 boot + hand-placed-env
> Express routing).
>
> **Next: N2 - the on-box collector v1 (prefs + weather + persistence)** per the plan:
> `setup/collect.py` (assembly/validation/persist with `SETUP_MODE=guided`), the
> first-run interview (device name → weather city loop ≤5), `_apply_core_prefs` in
> Foundation, the default RSS list as committed data, the conftest `input` queue.
> N2 needs owner answers to **Q2 (ship the RSS list as public data?)** and **Q3
> (web-server default for no-computer boxes)** - see the plan's open questions.
> Also still queued: a production-path device test (fresh provision + Setup installed
> from the live repo on `main`); optionally document `SETUP_MODE` in
> `.env.device.example` (a protect-hook kept the agent from adding the commented
> block). Pre-N1 context: the modular-setup MERGE to `main` (commit `cedab3d`,
> 1.5.0/1.2.0/1.4.8 shipped, restore tag `main-pre-modular-2026-06-10`) is recorded
> in `docs/plans/modular-setup.md`.

Context: all of Phase 5 + Phase 6 are DONE - 5a (Foundation), 5b·1/2/3 (IPTV), 5c
(`run_addons`), 5d (Guided + Model A), 6 (harden + the Fire TV matrix on the Bedroom box:
both legs, two real bugs found + fixed + re-verified - the slow-box keep-skin race and the
provisioner self-close bound; full evidence in the Phase 6 addendum in
`docs/plans/modular-setup.md`). NOTE: Kodi's `RestartApp` is a NO-OP on
macOS - the clean-quit+relaunch IS the real restart on the local box; drive wizard list
dialogs over JSON-RPC with `Input.ButtonEvent` (key-level), not `Input.Select`.

---

## ▶ HISTORICAL, NOT CURRENT STATE - Build status (modular-setup branch)

> **Read as history only (banner added 2026-07-19).** This section records the
> state of the modular Setup track as it stood at the 2026-06-10 merge. Every
> add-on it calls "the shipped production code" (`script.module.tony7bones`,
> `script.tony7bones.bootstrap`, `script.tony7bones.modv2plus`) was RETIRED AND
> DELETED at the static conversion on 2026-07-15, and the proxy version it cites
> refers to an engine that no longer exists. Nothing below describes what ships
> today. The suite counts and branch names here are equally frozen in time.

- **DONE, gated, committed LOCALLY** (suite **768 passed / 1 xfailed**):
  Phases 0-3 + 5a (Foundation, incl. 5a·2/5a·3) + **5b·1** (the two `apply_iptv` bugs - clobber
  window + N-provider env) + **5b·2** (the host-side IPTV build integrated - BOTH real
  providers, xtream included, clean-Kodi channel-load proven with the full curation grammar) +
  the **favorites-icon healing** addendum (dead xtream placeholder icons borrowed from live
  duplicates at build time, live-proven) + **5c** (`run_addons` - the standalone Add-ons layer,
  clean-Kodi proven on a Foundation-only box; MOD V2 untouched, RSS/origins/disable-after all
  live-verified, restart-survival proven) + **5b·3** (`run_iptv` - the standalone IPTV layer,
  clean-FOUNDATION-box proven: pvr backend installed BY the layer, both providers staged-applied,
  counts == builder's 158/47/24 + 214/100/12 + 5 favorites + 560 all, MOD V2 untouched,
  restart-survival; **Phase 5b COMPLETE - all three layers independently runnable**) +
  **5d** (the Guided wizard + Model A lifecycle - `run_guided` + `tony7bones.setup.probes` +
  the `SETUP_MODE=guided` routing in the shipped `run()`; the full multi-gate walk live-proven
  on a clean local Kodi: per-gate restarts each landing on a complete working box, Setup
  persisting across gates, env consumed only at Finish, Finish self-uninstall; the
  no-fork/cadence/end-state-equivalence invariants in `_tools/test_no_fork.py`; Express
  byte-identical - snapshot + `EXPECTED_NET_INSTALLED` unchanged) +
  **6** (harden - the keep-skin verify-then-re-assert fix + quiescence settle, the
  `SETUP_API` version guard, `assert_box_complete` + the closure walk with the bundled
  system-tree fix, the restart-prompt autoclose, CI gates on this branch; live-proven incl.
  a forced lost-confirm re-assert AND the fresh full Express run - the computer-setup track
  is COMPLETE) +
  **the Fire TV matrix** (Phase 6 addendum - BOTH legs on the real owner-authorized Bedroom
  Stick: the Guided per-gate manual-reopen walk incl. an accidental interrupted-run resume
  proof, and the unattended Express one-tap; found + fixed the SLOW-BOX keep-skin race in
  `activate_skin` and the provisioner's too-short self-close wait, both re-verified on the
  box; verbatim Android UX copy recorded; box left complete and working).
- **MERGED to `main` and PUSHED (2026-06-10, merge commit `cedab3d`)** - the modular Setup
  is the shipped production code: `script.module.tony7bones` 1.2.0 +
  `script.tony7bones.bootstrap` 1.5.0 + modv2plus 1.4.8 (proxy untouched at 2.2.1).
  Pre-merge restore point: tag `main-pre-modular-2026-06-10`.
- The deploy gate (`_tools/test_installer_present.py`) is on **`main`**. The superseded
  `iptv` branch (deliverables integrated in Phase 5b·2) was **deleted** - origin and local -
  at the milestone push.

---

## ▶ CLOSED, NOT ACTIONABLE - Backlog - Estuary MOD V2+ (`script.tony7bones.modv2plus`)

> **CLOSED 2026-07-19.** `script.tony7bones.modv2plus` is DEPRECATED AND DELETED
> (see the banner at the top of this file). The first three items below can never
> be done: there is no add-on left to do them to, and no repo owns them. They are
> struck rather than removed so the design intent stays on the record. Do not pick
> any of them up. The fourth item (`drop/`) was never modv2plus-scoped; its own
> feasibility doc is `docs/plans/drop-folder-feasibility.md`, which is still open
> and needs an owner decision.

- ~~**Settings menu order toggle** - "Skin Settings first", default ON; off = stock order. _Harder_ (list item order isn't cleanly conditional).~~
- ~~**Re-skin the MOD V2+ add-on icon** to reflect the "+" branding (currently reuses the old patch icon).~~
- ~~**Localized `strings.po`** for our category labels/help (currently literal text).~~
- ~~**`drop/` staging folder** at the repo root - a staging area for incoming files/assets.~~ Moved out of this dead backlog; see `docs/plans/drop-folder-feasibility.md`.

> Conventions: batch work into versioned deliverables; build bundled skin files FRESH from current
> omega source (b-jesch Omega / Kodinerds omega.4); verify on real local Kodi before shipping; no AI
> attribution anywhere. `script.*` changes ship via `generate_repo.py` + push (no proxy/deploy.py).
> Shipped/done history is not tracked here - live state lives in `addons/*/addon.xml` versions, git
> tags, and CLAUDE.md.
