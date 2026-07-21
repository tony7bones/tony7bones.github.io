# Incident 2026-07-17: Estuary 7 menu edits did not refresh on demand (the missing producer)

> **STATUS: RESOLVED and DEPLOYED in `skin.estuary7` 1.0.66 (2026-07-17).**
> Hardware-verified by the owner the same day: power menu > Customize Main Menu >
> disable an item > back, and the Home menu updated IMMEDIATELY, in-session, no
> Kodi restart. Test build staged to KodiShare `apps/`, then released.

## Symptom (owner-reported, recurring)

Menu customizations did not appear when made. Edits "saved" but the Home menu
kept rendering the old layout until Kodi was restarted or the user happened to
wander into another window and back. Worst on the Apple TVs. This survived FOUR
consecutive fix releases (1.0.62, 1.0.63, 1.0.64, 1.0.65 - all shipped
2026-07-17) and repeated "fixed in code" claims, none of which had a recorded
Apple TV hardware run (nothing since 1.0.38).

## How it was finally root-caused

A 4-agent panel (2 QA + 2 architects) ran a full-system analysis with mandatory
reading of every prior incident and playbook, followed by an adversarial review
of the implemented diff by 2 of the same agents. Key discipline: the panel
traced the ENTIRE trigger graph (producer -> store -> rebuild -> render) instead
of re-fixing the storage layer again.

## Root causes (four, compounding)

1. **The primary, owner-visible one - and NOT a tvOS storage bug: the power-menu
   "Customize Main Menu" entry had NO rebuild trigger at all.** Added in 1.0.47,
   it launched `RunScript(script.skinshortcuts,type=manage&group=mainmenu)`
   directly from DialogButtonMenu. The editor is a `WindowXMLDialog` opened OVER
   a still-loaded Home; closing a dialog never re-fires Home's `<onload>`, which
   is the only place a rebuild is triggered. On save, skinshortcuts only sets
   `skinshortcuts-reloadmainmenu` (gui.py:835) - it never fires a build. So the
   flag sat there until the user left Home once. Upstream MOD V2 never exhibits
   this because its only editor entry lives behind the SkinSettings WINDOW,
   whose close path re-inits Home. All platforms; presentation was tvOS-heavy
   because the Siri keymap parks users on Home. Releases 1.0.62-1.0.65 all
   fixed the CONSUMER side (onload machinery) and never noticed the missing
   PRODUCER.

2. **tvOS ordering race.** Home's onload fired `syncMenu` (the DATA reconcile)
   and the later-load `buildxml` as two parallel async RunScripts. A build that
   won the race read the DATA before the reconcile re-materialized a purged
   POSIX copy (baking the shipped default into the includes), and consumed the
   single-use `reloadmainmenu` flag that syncMenu's durability push depended on
   - so a fresh edit could render once and then silently miss durable-key
     registration, reverting on the next Caches purge.

3. **Upstream `script.skinshortcuts` 2.0.3 hash blindness (source-verified).**
   `writexml` does `if hexdigest: hashlist.append(...)` and the hasher returns
   None for an absent file, so a DATA file absent at build time is OMITTED from
   the hash file - the "New file detected" rebuild branch is dead code. A menu
   file that appears out-of-band (EZM++ restore, syncMenu re-materialize) can
   NEVER trigger a rebuild via the hash. Standing rule from this incident:
   **on-demand refresh rides the `skinshortcuts-reloadmainmenu` flag, never the
   hash.**

4. **resetMenu left stale NSUserDefaults keys.** The POSIX wipe (`os.remove`)
   cannot reach the key layer, so a Caches purge could resurrect the pre-reset
   menu through a surviving key, and the ~500KB NSUD budget only ever ratcheted
   up.

## The fix (skin.estuary7 1.0.66 - salvage, no engine rewrite)

All in `tools/skin_transforms.py` (sibling repo `moquette/estuary7`):

- **`customizeMenu` wrapper** wired to all 3 power-menu items: launches the
  editor, waits for the deterministic close signal
  (`Window(10000).Property(skinshortcuts)` is stamped exactly once after
  `doModal()` returns, on save AND cancel - skinshortcuts.py:351), then if the
  save flag is set: Fire OS fires ONE buildxml directly; tvOS arms
  `t7b_chainbuild` and spawns ONLY syncMenu.
- **Ordered tvOS pipeline**: Home's onload sets `t7b_chainbuild` synchronously
  (later loads only) BEFORE the syncMenu spawn; the parallel onload buildxml is
  now `!System.Platform.TVOS`-gated; syncMenu fires the one build strictly
  AFTER reconciling (in a separate try block, so a reconcile crash cannot
  strand the build; no marker on first boot, so nothing builds inside the
  keep-skin dialog window - the AlarmClock defer owns the first build).
- **Flag-free durable-key registration**: `xbmcvfs.listdir` merges POSIX and
  key names WITHOUT dedupe (TVOSDirectory.cpp), so a name listed once alongside
  a present POSIX file provably has no key - syncMenu registers the key from
  that structural signal instead of the racy flag, and SETS `reloadmainmenu`
  whenever it changed the POSIX layer (the bytes skinshortcuts reads), which
  defeats the hash blindness.
- **resetMenu key hygiene**: after the POSIX wipe, a tvOS-gated
  `xbmcvfs.delete` of every listed `*.DATA.xml` key (`settings.xml` excluded;
  on tvOS delete drops ONLY the key - the one place that asymmetry is the
  correct tool). Reported as `keydrop=N`.

## Verification

- 138 tests green, including the NEW trigger-graph suites
  (`tests/test_menu_triggers.py`, rewritten `tests/test_syncmenu_tvos.py`)
  that exec the REAL payloads against the two-layer tvOS-accurate fake -
  the trigger graph previously had ZERO coverage, which is exactly how the
  missing producer escaped four releases.
- Build determinism check passed; adversarial diff review by 2 panel agents
  (verdicts: SHIP / APPROVED); the one review finding (the wrapper briefly
  reintroduced a parallel build-vs-reconcile spawn) was fixed and is pinned by
  an end-to-end one-build test.
- **Owner hardware verification, 2026-07-17**: power menu > Customize >
  disable Pictures > back -> menu updated immediately. This is the first
  hardware-verified menu-refresh release since 1.0.38.

## Deliberate tradeoff (disclosed, do not "fix")

The reconcile dual-layers every `*.DATA.xml` (POSIX + durable key), so tvOS
File Manager lists those files TWICE. That is the expected cosmetic cost of
durability - both layers carry identical bytes after every reconcile - and is
NOT the incident-2026-07-08 duplicate-userdata corruption (which was EZM++
vectoring files it should not have).

## Lessons (add to the do-not-repeat list)

1. **Trace the trigger graph before re-fixing the storage layer.** Four
   releases hardened the consumer side of a chain whose producer did not
   exist. When a "refresh" bug survives a fix, ask WHO fires the rebuild for
   THIS entry point, not just where the bytes land.
2. **Every editor entry point must own its refresh.** A dialog-hosted entry
   bypasses window-lifecycle triggers. The built skin now bans direct
   `type=manage` launches in DialogButtonMenu by test.
3. **Never depend on skinshortcuts' hash for on-demand refresh** (upstream
   drops absent-file entries). The flag is the contract.
4. **A single-use window property read by two async consumers is a race, not
   a signal.** Structural detection (the listdir dup-count) beat the flag.
5. **"Fixed in code" is not fixed** - re-confirmed. The one hardware run found
   the fix good in minutes; four releases of test-only confidence did not.

Full technical write-up: `~/Code/moquette/kodi/estuary7/docs/playbooks/skinshortcuts-reset-tvos-vfs-split.md`
(section "Post-1.0.65") and the release entry in `~/Code/moquette/kodi/estuary7/TASKS.md`.
