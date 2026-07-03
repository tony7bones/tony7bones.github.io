# Plan: phased bootstrap/setup refactor + automate mini shares/backup

Status: DRAFT v7 - a small, targeted correction (not a full rewrite) closing round
five's residual findings. Both reviewers signaled strong convergence in round five
(architect: "not a structural regression... a one-paragraph addition resolves it";
QA: "reached diminishing returns on the two assigned items... no new structural gap
found"). Recommend a confirmation-only sixth pass, or proceeding to implementation.
Owner ask: stop hand-configuring two things on every box (the media NFS source and
the EZ Maintenance backup location), stop the port-typo class (`:2049`) at the source,
AND restructure the Setup into explicit, stoppable/resumable phases instead of one
undifferentiated Guided/Express flow. Make a fresh/re-installed box come up correct
with zero tweaking, and let the owner stop after any phase and pick back up later
without redoing work or losing track of what's done.

Changelog v4 -> v5 (round three; both reviewers confirmed all round-two items
genuinely closed against real code, then independently found new gaps):

- **EZ Maintenance++ cannot be installed via the normal closure-resolver path.**
  `script.ezmaintenanceplusplus` is served ONLY by our own `127.0.0.1` proxy, and the
  closure resolver explicitly skips `127.0.0.1`/`localhost` - the exact same
  closure-invisibility problem already solved for `pvr.artwork`/`modv2plus` via
  direct-extract (`_latest_zip_url`). The plan now states this explicitly and
  requires verifying the install actually succeeded BEFORE `_configure_backup`
  writes settings.xml - otherwise Phase 2 could read "done" for an add-on that was
  never installed (3.1a, 5).
- **`install_repos()` would run TWICE in Express** - Phase 5 (`apply_addons`)
  already calls it internally as part of its own documented self-sufficiency, and
  Phase 1 now also calls it explicitly. Idempotent, not a correctness bug, but real
  and previously unaddressed - now documented as an accepted, sized redundancy
  (Decision J), not silently inherited (2, 3.5).
- **RSS's actual current home was misstated.** It lives in `apply_addons`
  (`addons.py`) today, not Foundation - weather's precedent doesn't extend to it.
  Section 3.1 now states RSS is EXPLICITLY moved out of `apply_addons` into Phase 1
  (owner's original placement decision), named the same way `install_repos` and the
  skin closure were (2, 3.1).
- **A third piece of `apply_foundation` had no assigned destination**:
  `script.module.autocompletion` (`_install_autocomplete`). Assigned to Phase 1
  (same "branded utility, not curatorial content" rationale as weather), flagged as
  Decision K for confirmation (2, 3.1, 4).
- **A third existing test needs retiring**, not just two:
  `test_failed_foundation_gate_no_restart_no_activate` also pins the bundled
  Foundation-gate-includes-skin-activation behavior (5).
- **Decision I is strengthened, not just deferred.** Both reviewers independently
  flagged the same asymmetry: a failed skin is visibly wrong, a failed IPTV gets
  noticed at the first channel-surf, but a silently-failed BACKUP is invisible until
  the day a restore is actually needed - the worst possible moment. Backup-phase
  failure in Express now requires a durable, must-acknowledge signal (a modal, not a
  transient notification), while the rest of Express's recovery-model fix stays
  explicitly out of scope (3.5, Decision I).
- Added a test for the FULL new Express execution order (not just "activation is
  last"), mirroring the existing `test_run_express_orchestration_order_addons_
foundation_iptv` precedent (5).

Changelog v5 -> v6 (round four; both reviewers converged on the SAME modal-placement
hazard from complementary angles, plus two narrower scoping fixes):

- **Decision I's modal fix was itself unsafe as worded.** `xbmcgui.Dialog().ok()`/
  `yesno()` BLOCK the calling thread until dismissed, and this codebase already
  engineers around that exact hazard (`restart_kodi` avoids a blocking prompt on
  Android; its desktop path uses `yesno(..., autoclose=20000)` specifically so an
  unattended box can't hang). v5's "durable, must-acknowledge modal" named neither a
  bound nor a firing point - read literally, it could hang a provisioned box forever
  mid-Setup, never reaching Phases 3-5, activation, restart, or self-uninstall: WORSE
  than the silent failure it was meant to fix. Fixed (3.1a, 3.5, Decision I): the
  signal now fires at the EXISTING terminal seam - immediately before Express's
  already-present, already-blocking end-of-run summary/restart point, not gating any
  later phase - AND uses a bounded/autoclose mechanism mirroring the proven
  `yesno(autoclose=...)` pattern, so it can never hang indefinitely even there.
- **Decision J's "safe no-op" claim was overstated.** The second `install_repos()`
  call has no `is_installed` guard - it genuinely re-fetches all 12 repo zips, and
  `apply_addons()`'s installed/failed map is rebuilt from THIS second call's result,
  which (per the stated Express order) feeds the FINAL summary. A transient network
  hiccup on this purely-redundant second fetch could make the completion dialog
  wrongly report a repo as failed when Phase 1 actually installed it fine. Fixed (2,
  5): the double-call test now asserts FINAL BOX STATE (is the repo actually
  registered?), not the second call's own transient success/failure count.
- **The Full Express-order test needed an explicit carve-out.** Under the new order,
  `install_repos` legitimately fires from two call sites (Phase 1 + Phase 5's
  internal call, Decision J). A naive copy of the cited precedent (which asserts
  single-occurrence order) would either wrongly flag the second call as a bug or risk
  someone "fixing" it by touching `apply_addons`'s internals - exactly what Decision
  J says not to do. Now stated explicitly in section 5.
- **RSS's test blast radius was incomplete.** This repo has direct precedent: when
  weather moved from `addons.py` to `foundation.py`, its tests moved with it (to
  `test_setup_foundation.py`/`test_run_foundation.py`). RSS's relocation is the
  identical move, but the ~12 RSS-coupled tests in `test_setup_addons.py` were never
  named in section 5's scope note. Added.
- Minor: flagged whether `apply_addons`'s core RSS-enable setting (distinct from
  `_apply_rss_from_env`) moves with RSS or stays - needs a one-line confirmation
  before implementation, not a design blocker.

Changelog v6 -> v7 (round five; both reviewers signaled strong convergence - a
small, targeted correction, not a full rewrite):

- **Decision I's mechanism was still underspecified.** `Dialog().ok()` has no
  `autoclose` in Kodi's real API (only `yesno()`/`input()` do), and the plan never
  said whether the new signal followed `restart_kodi`'s Android no-blocking-prompt
  precedent. Fixed (3.1a, 3.5, Decision I): the signal is now explicitly a bounded
  `yesno(autoclose=...)` call, fires identically on Android and desktop (the hazard
  behind `restart_kodi`'s carve-out is a later, unrelated race this signal's earlier
  position doesn't reach), and the plan states outright that the pre-existing,
  unconditional end-of-run summary dialog has no bound and is an accepted, untouched
  residual - not implied away by "fired at the terminal seam."
- **A one-dialog-vs-two-dialog ambiguity risked reintroducing the exact problem
  this plan exists to fix.** Read literally, v6 could mean a user who misses the
  new alert would see only the pre-existing summary, which has no Backup status
  line at all - silently invisible again. Fixed: the design is now explicitly BOTH
  an unconditional `Backup: <ok|failed>` line in the always-shown summary AND the
  bounded alert on failure specifically, so neither one failing to be seen loses the
  signal.
- Named `net.is_installed(repo_id)` explicitly for the double-call test (Decision J)
  and added a one-line note on simulating the asymmetric pass/fail via a
  call-count-aware stub.
- Corrected the RSS test count from "~12" to the verified 11 (4 direct + 7
  `apply_addons`-composed).

## 1. Problem (why this exists)

Two settings are configured BY HAND on each box today, so they drift:

1. **Media file source** - `nfs://192.168.7.2/Users/moquette/Kodi/Share` (what the
   TVs browse). Set manually in File Manager per box.
2. **EZ Maintenance backup destination** - `download.path`/`restore.path`. Set
   manually in the add-on settings per box.

Manual config is where `nfs://192.168.7.2:2049/...` came from: Kodi NFS URLs take NO
port (libnfs uses 2049/111 by default); the explicit `:2049` broke the write
(`VfsCopyError`). The Setup automates add-ons, IPTV, and the skin, but NOT these two -
so this is "half-automation": the complexity of a custom setup without the payoff.

Separately, the Setup's OWN shape has a problem: `script.tony7bones.bootstrap`'s add-on
ID says "bootstrap" but it bundles everything - safety-net infra (shares, backup tool)
and curatorial choices (skin, curated apps, IPTV) - behind one Guided/Express decision,
with no clean way to stop partway and resume without either redoing work or losing
track of what already happened.

## 2. Current mechanics (grounding - verified against actual shipped code, three review rounds)

- `foundation._add_file_sources()` writes `userdata/sources.xml`: parses/creates the
  `<files>` tree, DEDUPES new sources by name+path, NORMALIZES the repo source under a
  canonical name/URL, fully defensive (errors non-fatal), and the end-of-setup restart
  makes Kodi read it. `FILE_SOURCES` is the source list.
- **Clobber-safe add-on settings write is an established pattern here:** `_configure_box`
  writes `addon_data/weather.multi/settings.xml` DIRECTLY; `iptv.py` writes
  `addon_data/pvr.iptvsimple/instance-settings-*.xml` DIRECTLY; `_trim_home_menu` writes
  `skin.estuary/settings.xml` + `Skin.SetBool`. So writing
  `addon_data/script.ezmaintenanceplusplus/settings.xml` (download.path etc.) BEFORE the
  restart is the SAME proven pattern - no new mechanism.
- **Foundation is contractually zero-content today, and this plan preserves that.**
  `run_foundation`'s own docstring promises "stop here = a pristine, branded Kodi
  with ZERO content," and `test_run_foundation.py::test_run_foundation_installs_zero_
content` asserts it. Weather is already grandfathered in under a narrow "branded
  look, not content" rationale. EZ Maintenance++ is a real add-on with its own
  dependency closure - the same category the zero-content test explicitly excludes -
  so it does NOT go in Foundation (see 3.1a, a NEW phase, not folded in).
- **`apply_foundation()`/`foundation_done()` bundle install_repos + the skin closure
  install + weather + file sources + home-menu trim + autocomplete
  (`_install_autocomplete`) as ONE atomic unit TODAY, and `foundation_done()` checks
  ONLY skin-installed + skin-active - nothing about sources, weather, or RSS.** This
  plan's Phase 1 (repos/sources/weather/RSS/autocomplete, no skin) and Phase 4 (skin
  closure + activate + trim, no sources/weather) is a genuine SPLIT of that single
  function and its probe, not two phases added beside it. `install_repos()` and
  autocomplete move to Phase 1 (prerequisites/utilities, not curatorial); the skin
  CLOSURE install (not activation) moves to Phase 4. **RSS is NOT part of
  `apply_foundation` today** - it lives in `apply_addons` (`addons.py`) via
  `_apply_rss_from_env` - so RSS is EXPLICITLY moved out of `apply_addons` into
  Phase 1 by this plan (the owner's original placement decision - "weather and rss
  alongside the initial shares/EZM++ setup"), named the same way as the other two
  relocations, not silently assumed as "already there."
- **`install_repos()` would run TWICE in Express under this plan, and the second
  call is NOT a harmless no-op the way "idempotent" implies.** `apply_addons`'s
  internal `_install_base` already calls `install_repos()` itself, documented as that
  layer's "proven self-sufficiency." Phase 1 now also calls it explicitly.
  `extract_zip` has no `is_installed` guard, so the second call genuinely
  re-downloads and re-extracts all 12 repo zips - on-disk end state stays safe (a
  failed re-fetch leaves prior files untouched, `_read_url` raises before any write),
  but `apply_addons()`'s installed/failed map is rebuilt from THIS SECOND call's
  result, and under the stated Express order (3.5) that second call is what feeds the
  FINAL summary. A transient network hiccup on this purely-redundant refetch could
  make the completion dialog wrongly report a repo as failed when Phase 1 actually
  installed it fine. Documented as an accepted cost (Decision J), NOT fixed by
  refactoring `apply_addons`'s internals in this plan (to avoid touching that layer's
  existing, independently-relied-upon self-sufficiency contract) - but the
  double-call TEST (section 5) must assert final box state, not trust the second
  call's own transient result.
- **`run_foundation`/`run_iptv`/`run_addons` are NOT the precedent for resumable
  phases - they're dead code.** `run()` never calls them (only `run_express`/
  `run_guided`), and each one calls `self_uninstall()` on completion, deleting the
  add-on's own code directory. Citing them as "existing re-entrant layers" was wrong
  in an earlier draft of this plan.
- **`run_guided`/`_next_gate` IS the real, correct precedent for the RESUME
  MECHANISM** (persists across gates, self-uninstalls ONLY at Finish/Remove, probes
  real installed state rather than a stored marker so a crash/decline/revert
  self-heals) - but its actual per-gate PROBE CONTENT is narrower than this plan
  needs (e.g. `foundation_done()` checks only skin state, `addons_done()` matches
  Phase 5's needs closely). So: the resume MECHANISM is proven and reused; the
  Foundation/Backup/IPTV/Skin PROBE CONTENT for phases 1-4 is new code following the
  same philosophy, not a drop-in reuse. Say this plainly rather than implying full
  continuity.
- **Existing probes are shallow by design (file EXISTENCE only, not content
  validation)** - e.g. `iptv_done()` does a bare `os.path.exists()` on
  `instance-settings-<N>.xml`, no parse. A crash mid-write during the very
  PVR-disabled config window this plan already worries about could leave a
  truncated-but-present file reading as "done." New probes (sources.xml, EZM++
  settings.xml) must follow the existing "any exception -> not done, never raise"
  contract AND validate content where practical, not just presence, to avoid
  inheriting this exposure (see section 5).
- `run_express` already defers skin ACTIVATION (`lookandfeel.skin` set) to be the
  literal last statement before its single restart, running after Apps/IPTV. This is
  because Kodi's "Keep this skin?" safety timeout silently reverts to stock Estuary
  if too much time passes between setting the skin and restarting. Section 3.3
  and 3.5 preserve this ordering for Express specifically.
- **Today's actual shipped Express order is Addons -> Foundation -> IPTV** (not
  phase-numeric) **and Express has a pre-existing no-recovery characteristic**: it
  self-uninstalls and restarts UNCONDITIONALLY past its initial cancel-check, even if
  a later internal phase (Foundation or IPTV) silently fails - only the summary TEXT
  reflects the failure, nothing blocks completion or offers a retry. This plan adds a
  new Backup phase into that same one-shot chain, which widens (does not create) this
  existing failure surface. **Both review rounds independently flagged the same
  asymmetry**: unlike a failed skin (visibly stock Estuary) or failed IPTV (noticed
  at the first channel-surf), a silently-failed BACKUP is invisible until the day a
  restore is actually needed - the worst possible moment to discover it. Addressed
  with a strengthened, explicitly-flagged item, not silently inherited (see 3.5,
  Decision I).
- `apply_iptv`'s PVR-disabled config window (`_pause_pvr_for_config`/
  `_resume_pvr_after_config`) is self-contained and synchronous (disable -> write ->
  enable, all inside one call, no restart in between) - a genuinely DIFFERENT hazard
  class from skin activation, which depends on Kodi's GUI confirm timeout that only
  resolves across a restart. No restart-adjacency fix is needed for IPTV; only the
  enabled-state read gap below applies.
- **No primitive exists today to READ an add-on's enabled state** - `is_installed()`
  only checks registration, and `net.py`'s `enable()`/`disable()` are write-only. The
  Phase 3 "PVR installed AND enabled" probe (3.2, 3.6) requires building this from
  scratch (e.g. a `Addons.GetAddonDetails` JSON-RPC call with `properties:
["enabled"]`), and must be clearly distinguished from the UNRELATED per-instance
  `kodi_addon_instance_enabled` key already living inside `instance-settings-<N>.xml`
  (`iptv.py`) - conflating "is the add-on enabled in Kodi's registry" with "is this
  PVR instance enabled in its own settings file" is a real, easy implementation bug.
- **Phase 4's "patch applied" check has an existing, proven reuse target**:
  modv2plus's own `service.py::_is_applied()` already does exactly this check. Use
  it directly rather than re-deriving the logic.
- **EZ Maintenance++ is invisible to the normal add-on closure resolver.**
  `script.ezmaintenanceplusplus`'s `repository.json` entry is served ONLY by our own
  `127.0.0.1` proxy, and the closure resolver (`repos.repo_dirs()`) explicitly skips
  `127.0.0.1`/`localhost` - so `install_selection()`/`install_with_deps()` (the
  natural-looking APIs) cannot resolve or install it. This is the SAME
  closure-invisibility class already fixed for `pvr.artwork` and `modv2plus`, both of
  which use direct-extract via `_latest_zip_url` instead. Phase 2 (3.1a) must use the
  same mechanism, not the normal closure installer, and must verify the install
  actually succeeded before writing settings.xml - otherwise Phase 2's probe could
  read "done" (settings.xml present and correct) for an add-on that was never
  actually installed and can't run.
- Env model keys (`.env.device.example`): `DEVICE_IP/DEVICE_NAME`, `IPTV_*`,
  `WEATHER_*`, `RSS_*`, `KODI_WEB_*`. There is NO mini/share/backup key yet, and
  `DEVICE_IP` is the BOX's IP, not the mini's.
- `wiz.py` (the `++` backup addon): `backupdir = control.setting("download.path")`; used
  for BOTH Local(0) and Network(1) destinations (identical except the Dropbox branch
  at `destination==2` - confirmed, closes Decision D); VFS copy handles `nfs://`/`smb://`.

## 3. Proposed change: an explicit phased Setup

### 3.0 Phase 0 - human, manual, irreducible (not part of the Setup add-on)

Add the `tony7bones.github.io` file source in Kodi's File Manager, then install
`repository.tony7bones-<version>.zip` from it. This is the ONLY way any of our
add-ons (including the Setup itself) can ever reach the box - `script.tony7bones.
bootstrap` cannot install the very repository it was distributed through. No in-Kodi
script can shortcut this for a genuinely fresh box; the adb provisioner
(`_tools/provision-kodi.sh`) pre-seeds `guisettings.xml` for the boxes already in this
fleet, but that's a separate, pre-boot, adb-only mechanism and out of scope here.

### 3.1 Phase 1 - Foundation (NARROWED + one addition from today's `apply_foundation` - see section 2)

- **`install_repos()`** (moved here, unchanged logic) - a prerequisite every later
  phase's add-on installs (Backup, IPTV backend, Skin closure, Apps) depend on, so it
  belongs in the first real phase, not scattered per-phase. Runs a SECOND time inside
  Phase 5's `apply_addons` today (see section 2, Decision J) - accepted, not fixed.

- **Autocomplete** (`_install_autocomplete`, moved here, unchanged logic - Decision
  K) - a system utility, not curatorial content, same rationale as weather.

- **KodiShare + KodiBackup file sources** (both mini shares, port-free). Names match
  the mini's own SMB share names for recognizability - these are Kodi source LABELS
  only, the URL host is still the real IP, not a resolvable hostname:
  - `("KodiShare", "nfs://<MINI_HOST>/Users/moquette/Kodi/Share/")`
  - `("KodiBackup", "nfs://<MINI_HOST>/Users/moquette/Kodi/Backup/")`

  Sources are mount POINTERS, not installed content, so they don't conflict with
  Foundation's zero-content contract. `KodiBackup` isn't required for the EZ
  Maintenance add-on to work (its NFS path is set directly in settings.xml,
  independent of `sources.xml`) - it's added for symmetry and so backups are
  browsable/manually manageable from Kodi's file manager, same as Share. Extend the
  existing normalization so any legacy source pointing at the old paths OR carrying
  a `:2049` collapses to the canonical port-free entry.

- **Weather** (unchanged from today - already Foundation-resident under the existing
  "branded look, not content" precedent).

- **RSS** (`_apply_rss_from_env`, EXPLICITLY MOVED HERE from `apply_addons`/
  `addons.py` - see section 2. This is a real relocation, not "already there" -
  named the same way as `install_repos` and the skin closure).

- **NOT here (moved out, see 3.3):** the skin closure install and home-menu trim,
  which today live inside `apply_foundation` but are being split into Phase 4.

- **New Phase 1 probe (`foundation_done`, redefined - see section 2):**
  `install_repos` succeeded + autocomplete installed + KodiShare/KodiBackup sources
  present (content-checked) + weather/RSS configured (content-checked). Does NOT
  check skin state anymore - that's Phase 4's probe now.

- **Port-free invariant:** a single helper `_nfs_url(host, path)` builds every NFS
  URL generated anywhere in this phase, and a unit test asserts NO `:<digits>` ever
  appears after the host. This kills the `:2049` class permanently.

- **Config source:** optional env keys with CONSTANT defaults so nothing breaks if
  unset, and the household values are the defaults - `MINI_HOST` (default
  `192.168.7.2`), optionally `KODI_SHARE_NFS`/`KODI_BACKUP_NFS` overrides (default
  derived from `MINI_HOST`, all via `_nfs_url`).

### 3.1a Phase 2 - Backup (NEW phase, immediately follows Foundation)

**EZ Maintenance++ install + configure** (`script.ezmaintenanceplusplus`, the repo's
own fork with the NFS/SMB retry hardening - see Decision C, RESOLVED). Owner
decision: this does NOT go in Foundation (would break its tested zero-content
contract) but gets its OWN phase immediately following it, preserving the original
intent - a fresh box has a working backup/restore path as early as possible, second
only to the shares themselves.

**Install mechanism (section 2 - REQUIRED, not the obvious-looking API):** EZM++ is
served ONLY by our own `127.0.0.1` proxy, which the closure resolver skips. Install
via DIRECT EXTRACT + `_latest_zip_url`, the same mechanism already used for
`pvr.artwork`/`modv2plus`, NOT `install_selection()`/`install_with_deps()` (which
would silently install nothing). `_configure_backup(box_env)` (or a small
`setup/backup.py`), called before this phase's restart, mirroring the weather.multi
write:

- **Verify the direct-extract install actually succeeded FIRST** - do not write
  settings.xml for an add-on that was never installed.
- Compute a **port-free, per-device** NFS path:
  `nfs://<MINI_HOST>/Users/moquette/Kodi/Backup/<device-slug>/`.
- `xbmcvfs.mkdirs(...)` that dir on the share (guarded, non-fatal).
- Write `addon_data/script.ezmaintenanceplusplus/settings.xml` merging:
  `destination` = Network(1) (Decision D, RESOLVED - confirmed identical to Local(0)
  in `wiz.py` except the Dropbox branch), `download.path`, `restore.path` = that
  path. Preserve any other existing settings; idempotent; defensive.
- `setup/addons.py`'s base `ADDONS` list drops peno64's `script.ezmaintenanceplus`
  entirely - EZM++ becomes the ONLY backup tool the Setup ever installs.

**Probe requirement (section 2, 5):** must be exception-safe (any error -> not done,
never raise) AND validate BOTH that the add-on is actually installed AND that
settings.xml content is correct (the expected paths are present) - avoids the
shallow-probe/truncated-file risk this plan explicitly calls out, and avoids the
install-invisibility trap above.

**Failure signal (strengthened, mechanism + scope corrected in v7 - see Decision I,
3.5):** unlike the rest of Express's phases, a silently-failed Backup is invisible
until a restore is actually needed. Two distinct, complementary parts, resolving
round five's found ambiguity between "one merged dialog" and "two sequential
dialogs" explicitly in favor of BOTH, so neither can fail alone:

- **The persistent record:** the existing end-of-run summary text gains a
  `Backup: <ok|failed>` line, unconditionally, every run. This is the part that
  cannot be missed, dismissed, or timed out past - if the owner only ever sees the
  one dialog Express already shows today, Backup's real status is still right there
  in it. This closes the exact gap round five found: a Backup failure must never be
  invisible even if a separate alert goes unseen.
- **The attention-grabbing alert:** ADDITIONALLY, on a Backup failure specifically,
  one bounded `xbmcgui.Dialog().yesno(...)` call (NOT `.ok()` - Kodi's real `.ok()`
  has no `autoclose` parameter; only `yesno()`/`input()` do) fires immediately
  before the existing summary, with `autoclose` set (mirroring `restart_kodi`'s own
  desktop-path use of `yesno(autoclose=20000)`) so it can never hang indefinitely.
  Both button labels are the same acknowledgment action (there is no real second
  choice here, unlike `restart_kodi`'s "Restart now"/"Later") - it exists purely to
  be more attention-grabbing than a toast, not to branch behavior.
- **Platform scope, stated explicitly (round five found this unstated):** this
  alert fires the SAME way on Android and desktop. `restart_kodi`'s own Android
  carve-out (no blocking prompt at all) exists because of a DIFFERENT, later hazard
  in the flow (a skinshortcuts-reload race that can destroy an open dialog or wedge
  a half-rendered skin) - this signal fires strictly BEFORE `self_uninstall`/
  `activate_skin`, before that race window even opens, so the hazard that forced
  Android's carve-out does not apply here. No platform split is needed or added.
- **Known, accepted residual (NOT fixed by this plan):** the pre-existing, always-
  shown end-of-run `Dialog().ok()` summary itself has NO bound at all (confirmed:
  Kodi's `.ok()` never supported `autoclose`) and runs identically today regardless
  of Backup's outcome. A genuinely unattended box can still block forever at THAT
  dialog. This is a pre-existing characteristic, not introduced or worsened by this
  plan, and stays explicitly out of scope - consistent with Decision I's general
  Express recovery-model fix being deferred to a separate, follow-on plan.

This does NOT gate Phases 3-5, activation, restart, or self-uninstall - both the
summary-line addition and the alert fire at/immediately before the existing
terminal seam, not mid-flow on failure.

### 3.2 Phase 3 - IPTV

Maps onto the existing `apply_iptv` layer as-is - no design change to the apply
logic itself. **No restart-adjacency fix is needed here** (unlike skin activation):
the PVR-disabled config window is synchronous and self-contained, a genuinely
different hazard class (section 2).

**New primitive required:** an add-on-enabled READ check (e.g. `Addons.
GetAddonDetails` with `properties: ["enabled"]`) does not exist in this codebase
today and must be built - do not conflate it with the unrelated per-instance
`kodi_addon_instance_enabled` key already inside `instance-settings-<N>.xml`.

**Phase 3 probe:** `pvr.iptvsimple` installed AND enabled (via the new primitive
above) AND instance-settings present with expected content (not bare existence).

### 3.3 Phase 4 - Skin (WIDENED from v3 - now includes the closure install moved from Foundation)

Install the MOD V2 skin CLOSURE (moved here from Foundation, see 3.1/section 2) +
activate it + apply the modv2plus patch, PLUS home-menu trim (tightly coupled to the
skin: it trims _stock_ Estuary's menu, and MOD V2's own menu is handled separately by
modv2plus's boot service once that skin is active).

**Owner-confirmed tradeoff, stated explicitly:** stopping before this phase means the
home menu is never trimmed (a change from today's unconditional trim). Accepted.

**Constraint (see section 2): this phase must be atomic with its own restart in
Guided mode** - because of Kodi's skin-revert timeout, there is no safe "stop in the
middle of phase 4"; it either completes (skin set, restart happens immediately) or
hasn't started. Guided's per-phase restarts make this a non-issue - each phase
already restarts on its own.

**Express-specific requirement:** in Express's single-restart model, the skin
closure INSTALL can happen in phase order, but skin ACTIVATION (`lookandfeel.skin`
set) must stay the LITERAL LAST statement before Express's one restart - after Phase
5 (Apps) - exactly matching how `run_express` already defers it today (see 3.5 for
Express's full stated order). Phase numbering in the Guided menu is a
DISPLAY/sequencing concept; it does not dictate Express's internal execution order
for this one operation.

**New Phase 4 probe:** MOD V2 is the ACTIVE skin AND the patch is applied, reusing
modv2plus's existing `service.py::_is_applied()` directly (section 2) rather than
re-deriving the check.

### 3.4 Phase 5 - Apps

Curated video add-ons (POV, The Loop, Sports HD, YouTube) + real-debrid, matching
today's `run_addons` behavior minus the skin (phase 4), minus RSS (moved to phase 1),
and minus peno64's EZ Maintenance (phase 2, replaced by the `++` fork). Still calls
`install_repos()` internally as part of its own self-sufficiency (accepted
redundancy, Decision J). Probe: unchanged from `addons_done()`'s existing shape
(already matches this closely per QA's second-round check).

### 3.5 Guided-vs-Express scope (RESOLVED, was open Decision G) + Express's real order

The phase-menu-with-resume design in 3.6 applies to **Guided only**. Express stays a
single unattended run for env-driven/provisioned boxes: no menu shown, one summary,
one restart, self-uninstall.

**Express's stated execution order:** `install_repos` + autocomplete -> KodiShare/
KodiBackup sources -> weather/RSS (Phase 1 content) -> EZM++ direct-extract
install+configure (Phase 2) -> IPTV (Phase 3) -> skin CLOSURE install + home-menu
trim, NOT activation (Phase 4 minus activation) -> Apps, which internally re-runs
`install_repos` as its own self-sufficiency (Phase 5, Decision J) -> skin ACTIVATION,
dead last (the one deferred operation, per 3.3) -> single restart -> self-uninstall.
This is a genuine reordering from today's shipped Addons -> Foundation -> IPTV; the
reorder is safe because no phase in this plan declares a hard dependency on another's
content beyond `install_repos` (Phase 1) being a prerequisite for everything
downstream.

**Decision I (STRENGTHENED, mechanism + scope corrected in v7): Express's
pre-existing no-recovery characteristic.** Confirmed in code: `run_express`
self-uninstalls and restarts UNCONDITIONALLY once past its initial cancel-check, even
if Foundation or IPTV silently failed - only the summary TEXT differs, nothing blocks
completion or offers a retry. This plan's new Backup phase joins that same one-shot
chain. Both review rounds independently flagged that this ISN'T a uniform widening -
Backup's failure mode is qualitatively worse than a failed skin or failed IPTV,
because it is invisible until the day a restore is actually needed. Recommend a SPLIT
resolution:

- The GENERAL fix (making Express itself recoverable/retryable on any internal
  failure) stays OUT of scope for this plan - a separate, follow-on plan - with an
  explicit PINNING test (section 5) documenting today's accepted behavior for
  Foundation/IPTV/Apps failures. The pre-existing, always-shown end-of-run
  `Dialog().ok()` summary has NO bound at all (Kodi's real `.ok()` never supported
  `autoclose`) and can itself hang a truly unattended box regardless of Backup's
  outcome - a known, accepted, pre-existing characteristic this plan does not fix
  (see 3.1a's full writeup).
- Backup-phase failure SPECIFICALLY gets TWO complementary strengthenings as part of
  THIS plan (3.1a): an unconditional `Backup: <ok|failed>` line added to the
  ALREADY-shown summary (so the status can never be missed even if a separate alert
  is), PLUS a bounded `yesno(autoclose=...)` alert fired immediately before that
  summary on failure specifically (mirroring the proven pattern `restart_kodi`
  already uses on its desktop path) for extra visibility. Neither gates Phases
  3-5/activation/restart/self-uninstall - both land at/immediately before the
  existing terminal seam. Fires identically on Android and desktop: the hazard that
  forces `restart_kodi`'s OWN Android carve-out (a skinshortcuts-reload race) is a
  different, LATER hazard than this signal's position in the flow, which is strictly
  before `self_uninstall`/`activate_skin` - so that carve-out's reasoning doesn't
  transfer here, and no platform split is needed.

Needs explicit architect/QA confirmation that this corrected split (general =
deferred, Backup = strengthened at the terminal seam, bounded) is the right line to
draw.

### 3.6 Resume/relaunch behavior (Guided only) - probe-based, no persisted marker

- **Always show the phase menu on relaunch - never silently auto-continue.** The
  owner sees exactly what state the box is in on every launch, e.g.:

  ```
  Phase 1: Foundation  [done]   Re-run?
  Phase 2: Backup      [done]   Re-run?
  Phase 3: IPTV         ->      Continue
  Phase 4: Skin
  Phase 5: Apps
  ```

  Default suggested action is the first incomplete phase, but every phase - including
  already-completed ones - stays explicitly selectable (an owner may legitimately want
  to re-run phase 1 later, e.g. the mini's IP changed).

- **No persisted completion marker.** Instead of a stored flag, "done" status is
  determined by PROBING REAL INSTALLED STATE on every launch, reusing `run_guided`/
  `_next_gate`'s proven RESUME MECHANISM directly - but see section 2: the per-phase
  PROBE CONTENT for phases 1-4 is new code following that same philosophy, not a
  drop-in reuse of today's narrower `foundation_done()`/`iptv_done()` checks:
  - Phase 1 done <=> `install_repos` succeeded + autocomplete installed +
    `KodiShare`/`KodiBackup` sources exist in `sources.xml` (content-checked, not
    just present) + weather/RSS configured (content-checked).
  - Phase 2 done <=> `script.ezmaintenanceplusplus` is ACTUALLY INSTALLED (not just
    settings.xml present, per section 2's install-invisibility trap) AND its
    settings.xml has the expected `download.path`/`restore.path` (content-checked).
  - Phase 3 done <=> `pvr.iptvsimple` is installed AND enabled (new primitive, see
    3.2) with the expected instance-settings content present (not bare existence).
  - Phase 4 done <=> MOD V2 is the ACTIVE skin AND `_is_applied()` (reused from
    modv2plus, see 3.3) confirms the patch.
  - Phase 5 done <=> the curated video add-ons + real-debrid are installed
    (`addons_done()`'s existing shape, unchanged).

  This is self-healing by construction: a crash, a declined restart, or anything
  reverted outside the Setup's control shows up as "not done" on the next probe,
  rather than trusting a flag that says otherwise. It also sidesteps the entire
  "does the marker survive an add-on version bump / uninstall / reinstall" question
  from the v2 draft - there's no marker to worry about surviving anything.

- **`assert_box_complete`'s completeness check must be updated for 5 layers.** Today
  it's hardcoded to `["foundation", "addons"] + iptv` (3 layers); Guided's Finish
  check needs to name all 5 new layers explicitly or it will silently miss Backup and
  the split Foundation/Skin state.

- **Idempotency remains the safety net for RE-RUNNING a phase**, exactly as before:
  every phase's apply logic stays independently idempotent regardless of what the
  probe shows, so re-running an "already done" phase is always safe - dedup file
  sources, re-confirm an already-correct setting - matching the pattern already used
  throughout this codebase.

## 4. Open design decisions (need architect/QA ruling)

- **A. Env-driven vs constant.** Recommend: optional env keys, constant defaults
  (3.1) - matches the existing env philosophy, zero-config for this household,
  reusable later.
- **B. Per-device backup subfolder.** RESOLVED: yes, `Kodi/Backup/<device-slug>` (no
  cross-box collisions; matches the existing `ATV1`/`ATV2` shape). Slug from
  `DEVICE_NAME`.
- **C. WHICH EZ Maintenance add-on.** RESOLVED: standardize on the repo's `++` fork
  (`script.ezmaintenanceplusplus`); drop peno64's `script.ezmaintenanceplus` from the
  base `ADDONS` list entirely (phase 2 installs `++` directly via direct-extract, see
  3.1a).
- **D. `destination` value.** RESOLVED: Network(1) - confirmed against `wiz.py` that
  Local(0) and Network(1) are identical except the Dropbox branch at `==2`.
- **E. Migration of the 5 existing boxes.** Setup self-uninstalls (runs once on fresh
  install), so configured boxes will NOT re-run it. Recommend a SEPARATE idempotent
  migration (adb-driven: rewrite each box's `sources.xml` + EZ `settings.xml` to the
  canonical port-free paths, AND uninstall peno64's plain fork if present) for the
  current fleet, with the Setup change covering all future/re-installs.
- **F. RESOLVED (was: where does the completion marker live).** DROPPED - no marker;
  resume is probe-based (3.6).
- **G. RESOLVED (Guided-vs-Express phase-menu scope).** See 3.5 - Guided only,
  Express stays a single unattended run.
- **H. Phase-2-follows-Foundation naming.** Is "Backup" the right display name for
  the new phase 2? Low-stakes, not a design blocker.
- **I. Express's pre-existing no-recovery characteristic (STRENGTHENED, corrected in
  v7).** See 3.5/3.1a - general fix deferred (separate follow-on plan, pinned with a
  test, including the pre-existing unbounded end-of-run summary as an accepted
  residual). Backup-phase failure specifically gets BOTH an unconditional summary
  line AND a bounded `yesno(autoclose=...)` alert, firing identically on Android and
  desktop. Needs explicit confirmation that this split is the right line, not a
  default assumption.
- **J. `install_repos()` running twice in Express (SHARPENED in v6).** Accept as a
  sized redundancy (recommended - avoids touching `apply_addons`'s existing
  self-sufficiency contract), NOT because the second call is harmless - it genuinely
  re-fetches all 12 repo zips and its result feeds the final Express summary, so a
  transient hiccup there could misreport a repo Phase 1 already installed
  successfully. The double-call test must assert final box state via
  `net.is_installed(repo_id)` - the same registration-check primitive already used
  elsewhere in this codebase - not the second call's transient result (2, 5). Needs
  explicit confirmation.
- **L. (NEW) Does `apply_addons`'s core RSS-enable setting move with
  `_apply_rss_from_env`, or stay?** Low-stakes, needs a one-line confirmation before
  implementation - not a design blocker.
- **K. (NEW) Autocomplete's phase-home.** Assigned to Phase 1 (same rationale as
  weather) - low-stakes, needs confirmation alongside Decision H.

## 5. Testing (repo's non-negotiable workflow: implement -> TEST -> >=90% cov -> GATE -> verify)

Unit (mocked `xbmc*`, `__main__`-guarded imports, like the existing suite):

- both KodiShare and KodiBackup sources added, port-free, deduped, and legacy/`:2049`
  variants normalized to canonical.
- `_configure_backup`: verifies the EZM++ direct-extract install actually succeeded
  BEFORE writing anything; writes the EZ settings.xml with the correct port-free
  PER-DEVICE path + `destination`; preserves other settings; idempotent (2nd run
  no-op); defensive (bad/missing file -> logged, non-fatal); mkdirs guarded
  off-device.
- **EZM++ install-mechanism test:** confirms direct-extract/`_latest_zip_url` is
  used (mirroring `pvr.artwork`/`modv2plus`), not `install_selection()`/
  `install_with_deps()`, and that a failed extract is NOT masked by a
  settings.xml write anyway.
- `_nfs_url` invariant test: no `:<port>` in any generated NFS URL.
- peno64's `script.ezmaintenanceplus` no longer appears in the base `ADDONS` list;
  `script.ezmaintenanceplusplus` install + configure is exercised in its place.
- `test_run_foundation_installs_zero_content` continues to pass UNCHANGED - proves
  this refactor did not regress Foundation's existing contract.
- **RSS relocation test:** `apply_addons` no longer configures RSS; Phase 1's
  Foundation now does, exercised directly (not assumed). Per this repo's own
  precedent (weather's tests moved with it from `addons.py` to `foundation.py`), the
  11 RSS-coupled tests currently in `test_setup_addons.py` (4 direct + 7
  `apply_addons`-composed)
  (`test_apply_rss_writes_feeds_with_interval`, `test_apply_rss_noop_when_absent`,
  `test_apply_rss_default_interval_is_30`, `test_apply_rss_never_raises`, plus the
  `apply_addons`-composed tests asserting RSS writes) move to
  `test_setup_foundation.py`/`test_run_foundation.py` alongside the code - named
  explicitly here, not left to the generic scope note below.
- **Probe exception-safety + content-validation, per new file-based probe** (sources.xml,
  EZM++ settings.xml, IPTV instance-settings): a corrupted/truncated version of each
  file must read as "not done," not just a missing file - proves the probes don't
  inherit the shallow existence-only exposure named in section 2.
- **New enabled-read primitive test:** the Phase 3 PVR-enabled check is exercised
  directly against the new primitive, and a test proves it is NOT confused with the
  unrelated per-instance `kodi_addon_instance_enabled` key.
- **Phase 4 probe reuse test:** confirms the patch-applied check calls modv2plus's
  actual `service.py::_is_applied()` rather than a re-derived duplicate.
- Resume menu: completed phases shown as done + re-runnable; re-running an
  already-completed phase is a safe no-op (idempotency proof, not just a UI check).
- **Earlier-phase re-run regression:** re-run phase 1 (or 2) AFTER phases 3-5 already
  completed; assert phases 3-5's installed state and probe results are unaffected.
- **Out-of-order phase completion:** a later phase (e.g. IPTV) already reads "done"
  (a pre-existing/upgraded box) while an earlier, newly-inserted phase (Backup) does
  not; assert the resume menu still reports each phase's real, independent state
  correctly rather than assuming strict completion order.
- **Mid-phase interruption, all phases (not just Skin):** simulate an interrupted
  phase 1, 2, or 3 (partial state, e.g. one of two sources added, or PVR installed
  but not yet enabled) and assert the probe correctly reports "not done" rather than
  a false "done" - the self-healing property from 3.6 must be proven, not assumed.
- **Phase 4 (Skin) atomicity:** no code path exists that could pause between
  skin-set and its restart in Guided.
- **Full Express-order test (new):** proves the ENTIRE stated order in 3.5
  end-to-end (not just "activation is last"), mirroring the existing
  `test_run_express_orchestration_order_addons_foundation_iptv` precedent as a
  direct template for a call-order assertion. MUST explicitly state that
  `install_repos` is expected to appear TWICE (Phase 1's explicit call + Phase 5's
  internal call, per Decision J) and assert on that as a known, separate, already-
  covered case owned by the double-call test below - NOT treat a second occurrence
  as a uniqueness violation, and NOT "fix" it by touching `apply_addons`'s internals.
- **Express fragility pinning test (Decision I, general):** Express completes,
  restarts, and self-uninstalls even when Foundation/IPTV/Apps's probe would read
  "not done" immediately afterward - documents today's accepted behavior explicitly.
- **Backup failure signal test (Decision I, mechanism corrected in v7):** a failed
  Phase 2 in Express (a) produces an unconditional `Backup: failed` line in the
  always-shown summary, and (b) additionally fires a bounded `yesno(autoclose=...)`
  alert immediately before that summary - NOT immediately on Phase 2 failure mid-flow
  - and identically on Android and desktop (no platform branch). A separate test
    proves Phases 3-5, activation, restart, and self-uninstall all still run to
    completion even when Phase 2 failed (i.e. neither signal gates anything after it).
    A third test proves a Backup SUCCESS produces `Backup: ok` in the summary with no
    extra alert, so the two states are both explicitly covered, not just the failure
    path.
- **`install_repos()` double-call test (Decision J, sharpened):** asserts FINAL BOX
  STATE via `net.is_installed(repo_id)` (the repo is actually registered) is correct
  even when the second call (inside Phase 5's `apply_addons`) hits a simulated
  transient failure - using a call-count-aware stub on the extract/fetch primitive so
  the first (Phase 1) call succeeds and the second (Phase 5) call fails, proving a
  redundant-call hiccup can't misreport a repo Phase 1 already installed
  successfully, not merely "the second call doesn't crash."
- **Explicit relaunch-trigger test:** re-invoking the Setup add-on's actual entry
  point (the same mechanism Kodi uses when the owner re-launches it from Program
  add-ons) shows the phase menu with correct probe-derived state - not just a
  unit test of the menu-rendering function in isolation.
- **Express regression test:** Express's existing one-shot behavior (no menu ever
  shown, one summary, one restart, self-uninstall) is unchanged by this refactor.
- **`assert_box_complete` layer-list test:** Guided's Finish check names all 5 new
  layers; a box missing any one of them is correctly reported incomplete.
- **Test-retirement list (now three, not two):** `test_wizard_reoffers_foundation_
after_skin_revert`, `test_foundation_gate_installs_and_keeps_setup`, and
  `test_failed_foundation_gate_no_restart_no_activate` all assert today's bundled
  Foundation-includes-skin behavior and must be retired/rewritten under the split,
  not left to silently fail or silently pass on stale assumptions.
- **Scope note (sizing, not a test item):** migrating from today's 3-gate model to 5
  gates requires REWRITING (not just extending) roughly 20-23 existing tests in
  `test_run_guided.py` and 28-31 in `test_setup_probes.py` that hard-code the current
  gate boundaries - size this into the implementation estimate up front.
- coverage >=90% on new code; `pytest _tools/ -q` (+ the add-on tests) + `ruff` +
  secret-leak all green.

Live verify (real box): fresh Setup on a clean box -> phase menu appears, `KodiShare`

- `KodiBackup` sources appear after phase 1, a Full Backup writes to
  `Kodi/Backup/<device>` with ZERO manual steps and no `:2049` after phase 2, stopping
  after phase 3 and relaunching shows phases 1-3 done (via live probe, not a flag) and
  phase 4 suggested next.

## 6. Rollout

- Ship via `python3 _tools/release.py` (minor-bump `script.module.tony7bones` +
  `script.tony7bones.bootstrap` in lockstep; auto-news; gate). No proxy change.
- Then run the one-time fleet migration (item E) on the 5 boxes.

---

# PART 2 - Mini config-as-code (owner directive: "also mini")

## P.1 Problem

The mini's ENTIRE Kodi-serving config was hand-built over SSH: folder tree, NFS
exports + `nfs.conf`, SMB shares, and LaunchDaemons. If the mini is wiped or replaced,
all of it is manual to redo. Worse: **the IPTV populator CODE lives ONLY on the mini**
(`~/Kodi/services/iptv/`) - it is NOT in this repo, so it is neither versioned nor
backed up. Part 1 makes the BOXES reproducible; Part 2 makes the MINI reproducible.

## P.2 Scope - codify into an idempotent `mini/` provisioning layer in the repo

1. **The iptv populator code (biggest gap).** Bring `~/Kodi/services/iptv/` INTO the
   repo (versioned); the mini gets it via a deploy step. Today it exists only on the
   mini.
2. **Daemons as repo templates + install step:** `com.tony7bones.iptv2.plist` (+ any
   WiFi-keepalive template, conditional - only relevant while the mini is on WiFi;
   currently retired since the mini is wired); provision installs + `launchctl
bootstrap`s them.
3. **NFS:** `/etc/exports` (`Kodi/Share` + `Kodi/Backup`, `-mapall=moquette -network
192.168.7.0 -mask 255.255.255.0`) + `nfs.conf`
   (`nfs.server.mount.require_resv_port=0`, the Android-mount fix) + `nfsd
enable/update`.
4. **SMB:** shares `KodiShare` + `KodiBackup` (guest) via `sharing -a ... -s 001 -g 001`.
5. **Folder tree:** `~/Kodi/{Share,Backup,services/iptv}` (STRUCTURE only - Share media
   - Backup zips are DATA, never touched).
6. **Screen sharing:** `DisableKerberos=true` (the Finder Share-Screen fix).
7. **Runbook (documented, not scripted):** the eero DHCP reservation (wired MAC -> .2)
   and the wired-vs-WiFi switchover, since those live on the eero.

Form: `mini/provision.sh` (idempotent, re-runnable; mirrors `_tools/provision-kodi.sh`'s
philosophy for boxes) + the plists + the in-repo iptv package + a README/runbook. One
command rebuilds a mini. NEVER touches Share/Backup data.

## P.3 Open design decisions (need architect + QA ruling)

- **P-A. Repo home for the iptv code + sync.** Where does the populator live canonically
  (e.g. `mini/services/iptv/`) and how does the mini's copy stay in sync (deploy/rsync
  step, or the mini pulls from git)? Recommend: repo is canonical, provision deploys it.
- **P-B. Provisioning form.** Idempotent bash over SSH (matches the existing box
  provisioner) vs something more structured. Recommend: bash, with a `--dry-run`.
- **P-C. Secrets.** `providers.yaml` carries provider creds - MUST stay gitignored; commit
  a `.example`; provision reads the real one from a known path (mirrors the box `.env`
  model + `test_secret_leak.py` allowlisting). This is a hard gate.
- **P-D. Config-only boundary.** Provision touches CONFIG only, never DATA; must be safe to
  re-run on a live mini.
- **P-E. Testability of bash.** How do we gate it (a `bats` suite like the retired
  `mini/services/shared` had, `--dry-run` assertions, or a scratch-dir re-provision)?
  Bash is harder than the Python Setup - QA to define the acceptance test.

## P.4 Sequencing vs Part 1

Part 1 (box-side automation) and Part 2 (mini-side codification) are independent and can
ship separately. Recommend Part 1 first (smaller, higher-frequency pain), Part 2 second
(bigger, and the iptv-code-not-in-repo gap is the priority within it).

---

## Non-goals (both parts)

- Not touching the curated video add-ons' content selection or Dropbox backups.
- Part 2 codifies the mini's CONFIG only - never its DATA (Share media, Backup zips).
- Not automating the eero itself (documented runbook only).
- Home-menu trim not happening if the owner stops before Phase 4 is an ACCEPTED
  tradeoff (3.3), not an open question.
- Fixing Express's GENERAL pre-existing no-recovery characteristic (Decision I) is
  OUT of scope for this plan - pinned/documented, not silently inherited. Only the
  Backup-phase-specific failure signal is added now.
