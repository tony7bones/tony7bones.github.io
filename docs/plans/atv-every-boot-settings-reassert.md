# Design: every-boot settings re-assert (Apple TV restore durability)

**Status: REJECTED (2026-07-08) by unanimous adversarial review — DO NOT IMPLEMENT.**
Three independent reviewers (QA + two architects) each proved it cannot work, two from
Kodi's own tvOS source. The review also surfaced the *correct* fix. See the verdict at the
bottom. This design is kept as a record so the every-boot re-assert is never re-proposed.
The original "written to be attacked" doc follows unchanged.

## The problem this must solve (and the graveyard behind it)

On Apple TV a full-backup restore does not stick: RSS, weather, TV/IPTV, remote,
keyboard, skin all revert and must be rebuilt by hand.

**Root cause (Kodi Wiki + code-confirmed):** tvOS gives an app only ~500 KB of normal
app-directory storage, so Kodi mirrors its settings into the app's **NSUserDefaults**
(binary plist) and **rewrites `userdata/guisettings.xml` from that mirror on launch**
([Kodi Wiki TvOS](https://kodi.wiki/view/TvOS), [Userdata](https://kodi.wiki/view/Userdata)).
The live in-memory store flushes to NSUserDefaults **only on a clean shutdown**. Apple TV
users quit by swiping the app away = **unclean** → the flush never happens → next boot
rewrites the on-disk files from the **stale** mirror → the restore is erased.

**What has already been tried and FAILED (do not re-propose):**
`_kodisettings.apply_guisettings` — re-applying restored settings by pushing them through
Kodi's live store via JSON-RPC `Settings.SetSettingValue` — shipped in **2026.06.30.28**
and has been in every restore release since. It is "Layer B." It does not work on Apple
TV, for exactly the reason above: it writes to a store that is discarded on the unclean
quit before it is ever persisted. Extending the same `setSetting` call to add-on settings
("Layer A") dies at the identical point. The device-name "both-ways" write (2026.07.08.1)
rests on the same clean-shutdown assumption and was only ever verified on **Fire TV**,
never on tvOS.

## The one idea the graveyard has NOT tried

Stop trying to make a single post-restore write *persist*. Instead **re-apply the restored
settings from a revert-proof stash on EVERY boot**, so the **running session is always
correct** even though NSUserDefaults stays stale — self-healing until (if ever) a clean
shutdown finally commits them. This does not depend on the clean shutdown that Apple TV
users never give.

## Design

### D1 — Stash at restore time (`wiz.restore`)
At the existing post-extract point where `tools.mark_buffer_prompt_pending()` is called
(after the wipe/extract, before `ask_restart`), also:

1. Copy the just-restored `userdata/guisettings.xml` into EZM's own `addon_data` as
   `.ezm_settings_stash/guisettings.xml` — plain Python file I/O (never `xbmcvfs`, per
   `kodi-vfs-cannot-read-foreign-local-files.md`).
2. Snapshot the add-on settings we intend to re-assert: copy each
   `userdata/addon_data/<id>/settings.xml` we care about into
   `.ezm_settings_stash/addon_data/<id>/settings.xml` (skip `script.ezmaintenanceplusplus`
   itself; skip `instance-settings-*.xml` — see the limits section).
3. Drop a **new, persistent** marker `.ezm_settings_reassert` (distinct from the one-shot
   `.ezm_buffer_prompt`, which is cleared after the tune-up; this one must survive many
   boots). Reuse the exact `BUFFER_PROMPT_MARKER` mechanism.

The stash + marker live under `addon_data/script.ezmaintenanceplusplus/`, which
`onetap._wipe_excludes()` preserves and which is **not** guisettings.xml (so, per the
assumptions below, not subject to the NSUserDefaults rewrite).

### D2 — Re-assert at boot (`service.py`)
Add `_maybe_reassert_settings(monitor)` called **before** `_maybe_prompt_after_restore`,
mirroring its discipline: check the marker FIRST (instant no-op on a normal boot). If the
marker + stash exist:

1. A light bounded readiness probe (a few `Settings.GetSettingValue` retries — NOT the full
   `Window.IsVisible(home)` wait, so no GUI delay) to ensure the settings subsystem is up.
2. `_kodisettings.apply_guisettings(stash/guisettings.xml)` for core settings, **minus a
   denylist** of `services.devicename` and `filecache.memorysize` (owned by the tune-up
   prompt — re-asserting them would fight the user's rename/retune every boot).
3. `_kodisettings.apply_addon_settings(stash/addon_data)` via `xbmcaddon.Addon(id).setSetting`
   for the snapshotted add-on settings.
4. All fully guarded (`try/except`), count-only logging, no per-item GUI (per the SIGSEGV
   lesson), never blocks the maintenance loop.

### D3 — Self-terminate
Before re-applying, compare each stashed value against the current on-disk
`guisettings.xml` (which at boot reflects NSUserDefaults). If they already match, a clean
shutdown has committed them → **clear the marker, delete the stash, done.** Otherwise
re-apply and leave the marker for next boot. Defensive bound: also clear after N boots
regardless (a boot counter in the marker) so a coercion-mismatch can't pin it forever.

### D4 — Honest limits baked in
- **pvr.iptvsimple instance settings** (`instance-settings-*.xml`) cannot be set via
  `setSetting`/JSON-RPC at all — out of scope. TV/IPTV restore stays a file-restore +
  PVR-disabled-window problem, tracked separately.
- The re-assert makes the **session** correct; it does not make NSUserDefaults correct
  until a clean shutdown ever occurs.

## Assumptions this design STANDS OR FALLS on (attack these)

- **A1 — The stash + marker files survive an unclean quit + reboot on tvOS.** The whole
  design reads from them on the *second and later* boots. If tvOS's ~500 KB limit / the
  "NSUserDefaults is the only persistent storage" behavior means arbitrary
  `addon_data/<id>/` files under EZM are NOT durably persisted (or are also vectored/lost),
  there is nothing to re-apply from and the design is dead on boot 2. **This is unproven on
  tvOS** — the buffer/device-name markers that "prove" the pattern were verified on Fire TV
  only.
- **A2 — `setSetting`/`SetSettingValue` at boot actually takes behavioral effect** for the
  target settings (weather locations/keys, skin bools) without a further restart, and
  reaches the add-on's runtime, not just an in-memory value nothing reads.
- **A3 — Re-applying every boot does not fight the user.** If self-terminate (D3) never
  fires on Apple TV (because a clean shutdown never happens), the box re-applies the
  restored snapshot on every launch — meaning any setting the USER changes post-restore is
  reverted on the next boot. This could be *worse* than the original bug.
- **A4 — Boot cost is acceptable.** Right after a revert, many settings differ → potentially
  hundreds of JSON-RPC calls at every startup, unthrottled, before the maintenance loop.
- **A5 — No proof is possible without hardware.** Per the `ezm-backup-doctor` RULE ZERO and
  the "local Mac Kodi proves nothing about a tvOS-specific bug" lesson, none of this is
  confirmable except on a real Apple TV via the Xcode CLI capture
  (`atv-kodi-xcode-cli-troubleshooting.md`).

## Verification gate (before any ship)
1. Unit tests reproducing the stash → boot re-assert → self-terminate flow (the only
   confidence obtainable off-device).
2. The Xcode CLI plist-vs-XML diff across restore→quit→reopen→reopen, proving (a) the stash
   file survives reboot [A1], and (b) the re-asserted values are live after the second boot.
3. Only then ship, with the version/news hand-edited per this add-on's `YYYY.MM.DD.N`
   convention.

---

# ADVERSARIAL REVIEW VERDICT (2026-07-08): REJECTED — three independent kills

All three reviewers were told to *prove it cannot work*. They agreed, by different routes:

**Kill 1 — QA, "makes it worse" (attacks A3/A4).** Add-on settings are plain files
(`addon_data/<id>/settings.xml`), NOT guisettings/NSUserDefaults. Logical pincer: if those
files survive reboot, the user's own post-restore edits already persist and re-asserting the
*base-backup* values every boot is a pure regression (reverts the user's changes every
launch); if they don't survive, the stash is gone on boot 2 and the design is inert. No
third branch. Also: the D3 self-terminate compare is unreachable (subset of settings
`apply_guisettings` even attempts, default-pruning asymmetry, type coercion `"true"!=True`),
so on a swipe-quit box the marker never clears — it fights the user for N boots, then the
N-boot bound stops re-asserting while NSUserDefaults is *still* stale → **the original bug
returns.** No stable "restore stuck, user happy" state exists.

**Kill 2 — Architect, "A1 is fatal" (Kodi tvOS source).** `TVOSDirectory.cpp` /
`TVOSFile.cpp`: on tvOS, non-`.xml` files and dirs live in the **non-persistent Caches
tree**; only `.xml` files written **through Kodi's `CTVOSFile` VFS** vector into the
persistent NSUserDefaults. The design writes its stash + marker with **plain Python**
(mandated, to dodge the VFS-read bug) → they land in purgeable Caches; the marker isn't even
`.xml`. tvOS purges Caches on reboot; Kodi's recovery routine is an unimplemented `TODO`. So
`_maybe_reassert_settings` finds no marker on boot 2 → no-op. **Dead where A1 predicted.**

**Kill 3 — Architect, "premise unsound + better fix exists."** The design's core claim —
"only a clean shutdown persists NSUserDefaults" — is **FALSE**. Kodi source
(`TVOSNSUserDefaults.mm`): a `.xml` write under `/userdata` **through `xbmcvfs`** calls
`SetKeyData(..., synchronize=true)` → `[NSUserDefaults synchronize]` **immediately**,
persisted before the call returns, with **no dependency on a clean shutdown.**

## The REAL root cause (what every prior attempt missed)

The restore extracts with plain Python `zipfile` (`wiz.py` ~L925, `zin.extract`) = plain
POSIX writes. On tvOS those **bypass the VFS**, so restored `.xml` files never enter
NSUserDefaults. At boot Kodi reads settings back **through** the VFS (from NSUserDefaults —
the stale mirror) and never sees the POSIX files the restore wrote. **The restore is
*shadowed*, not "un-flushed."** `apply_guisettings` (live store) is lost on the unclean quit,
so nothing reaches the persistent store. That is why 06.30.28 → 07.08.1 never stuck.

## The CORRECTED fix (to be written up + hardware-verified next)

At the post-extract point, one-time reconcile:
1. **Re-write the restored `userdata/**/*.xml` THROUGH `xbmcvfs`** — `guisettings.xml`,
   `RssFeeds.xml`, `keymaps/*.xml`, `addon_data/<id>/settings.xml`, and
   `pvr.iptvsimple/instance-settings-*.xml` + `customTVGroups-*.xml` (all `.xml` under
   `/userdata`, all satisfy `WantsFile()`). This vectors them into NSUserDefaults with
   `synchronize=true` → **durable on the FIRST reopen regardless of quit cleanliness.**
2. Keep the shipped `apply_guisettings` JSON-RPC so a *clean* shutdown path also holds.

Properties: no marker, no boot counter, no self-terminate, no per-boot RPC storm, **no A3
regression** (it does not fight later user edits — it runs once), and it **covers the user's
entire list incl. TV/IPTV** (instance settings are `.xml` and vector too). This is *simpler
and more complete* than the rejected design.

## Open caveats on the corrected fix (do not skip)
- **500 KB NSUserDefaults budget** (`NSUserDefaultsSize`/`NSUserDefaultsPurge`): a large
  restored `addon_data` written into NSUserDefaults could exceed it and silently fail. Kodi
  already stores this class of data there normally, but a restore's userdata can be larger —
  must be measured on-device.
- **The live-PVR clobber is orthogonal** and still needs the PVR-disabled config window
  (`kodi-settings-clobber.md` #3) for TV/IPTV to hold across the post-restore sync.
- **Write-through-VFS is verified in Kodi SOURCE, not yet on hardware.** The Xcode-CLI plist
  diff (`atv-kodi-xcode-cli-troubleshooting.md`) must confirm the restored values appear IN
  `Library/Preferences/<bundle>.plist` after the re-write and survive the swipe-quit reopen,
  before shipping. (This mechanism *is* confirmable in source today, unlike the rejected
  design's assumptions — a strictly better evidence position.)

Sources: Kodi tvOS source `TVOSFile.cpp`, `TVOSDirectory.cpp`, `TVOSNSUserDefaults.mm`,
`PreflightHandler.mm`; repo playbooks `kodi-vfs-cannot-read-foreign-local-files.md`,
`kodi-settings-clobber.md`.
