# Playbook — Kodi add-on install mechanics (Omega)

How the Tony.7.Bones Setup add-ons install third-party add-ons on Kodi 21
"Omega" **without** a single blocking prompt, and why each non-obvious choice is
the way it is. Every claim here is implemented in `script.module.tony7bones`
(`lib/tony7bones/*.py`) and the two Setup `default.py` files.

---

## 1. Never use `InstallAddon` from a script — it deadlocks

Kodi 21 Omega exposes **no JSON-RPC install method**: the `Addons` namespace is
`GetAddons` / `GetAddonDetails` / `SetAddonEnabled` / `ExecuteAddon` only. There
is no `Addons.Install`.

`xbmc.executebuiltin("InstallAddon(<id>)")` pops a **blocking modal**
(`CAddonInstaller::InstallModal`, waiting on `CHOICE_YES`) on the GUI thread. A
script driving it from the same thread never returns — this is the "Registering
add-ons" freeze.

**What we do instead:** resolve the dependency closure ourselves, download +
extract every zip directly into `special://home/addons/`, then register each
add-on with JSON-RPC `Addons.SetAddonEnabled`. This never blocks.

- Extract: `net.extract_zip()`
- Rescan after extract: `net.update_local_addons()` (`UpdateLocalAddons()`)
- Register/enable: `net.enable()` → `Addons.SetAddonEnabled(enabled=true)`

`SetAddonEnabled` is the step that inserts a directly-extracted add-on into
Kodi's installed table and makes it runnable. It works **independently of the
unknown-sources setting**.

## 2. Stamp `origin` — this is what makes apps actually browse

Kodi's own repository installer records which repo an add-on came from in the
`installed.origin` column of `Addons<NN>.db` (Omega ships `Addons33.db`).
Direct-extract leaves `origin` **blank**, and a blank origin is treated as
"installed by an unofficial repository / unknown source." Concrete breakage:

- **The Loop** opens a blocking "installed from unknown source" modal on every
  launch → headless `GetDirectory` aborts → empty.
- **POV** can't load its language resource → `getLocalizedString` returns `''` →
  `setLabel` receives an int → "must be unicode or str" → empty menu.

**Fix:** after extracting + enabling, write each add-on's `origin` into the
Addons DB, and enable the source repos so that origin references a repo Kodi
knows. Implemented in `repos.set_origins()` (an `UPDATE ... WHERE origin=''`, so
only blank rows are touched) and `repos.enable_source_repos()`. The change takes
effect on the next Kodi start (hence the end-of-run restart).

## 3. Do NOT toggle `addons.unknownsources`

That setting only gates Kodi's _install-from-zip GUI_. It has **no bearing** on
the direct-extract + `SetAddonEnabled` path. Flipping it also pops the "access to
personal data… Proceed?" warning. Leaving it untouched = zero prompts. The Setup
code never touches it (see the docstring in `script.tony7bones.bootstrap/default.py`).

## 4. Skip optional dependencies

The closure resolvers drop any `<import optional="true">` — matching Kodi's own
behaviour (Kodi installs optional deps on-demand at runtime, not eagerly). This
is `index._required_dep_ids()`. Why it matters: `resolveurl` declares
`plugin.googledrive` (and other cloud resolvers) **optional**, so eager
resolution was pulling Google Drive nobody asked for. Skipping optional imports
fixed that.

## 5. Install-then-disable for an unwanted REQUIRED dependency

The Loop declares `plugin.video.dailymotion_com` as a **required** import, but
nobody here uses Dailymotion. Two bad options and the good one:

- ❌ Exclude it + patch The Loop's manifest → the patch is overwritten by The
  Loop's next auto-update.
- ❌ Leave it out → The Loop's required-dependency check fails → "broken add-on".
- ✅ **Install it, then disable it.** It stays _installed_ (satisfies the required
  dep check, no broken flag, no "required" lock) but never runs. Durable across
  the requiring app's auto-updates with no per-update re-patching.

Config: `VIDEO_DISABLE_AFTER = {"plugin.video.dailymotion_com"}` in
`script.tony7bones.bootstrap/default.py` (passed to the shared library's
`install_selection()`); logic in `install.disable_after_install()` (only disables
ids that actually ended up installed).

## 6. Binary / platform add-ons — pick the entry for THIS machine

Binary add-ons (`pvr.iptvsimple`, the `inputstream.*` clients) are listed in the
official Kodi repo **once per platform**, each with a `<platform>` tag and an
explicit `<path>` (e.g. `pvr.iptvsimple+osx-arm64/...`). Detect this machine's
Kodi platform tag at runtime and keep only the matching entry:

- `system.platform_tag()` → `osx-arm64`, `windows-x86_64`, `android-aarch64`, …
- It returns `None` on desktop Linux (binaries come from the distro package
  manager, not the mirror).
- The index parsers honour the declared `<path>` instead of the conventional
  `<id>/<id>-<ver>.zip` when one is present (`index.load_index_simple` /
  `index.parse_index`); `index._platform_match()` drops arch entries for other
  arches.

**Never hardcode** the platform — let `platform_tag()` decide.

## 7. Closure resolution — highest-version-wins, official-preferred for modules

The resolvers walk `<requires>/<import>` **recursively**, dependencies ordered
**before** their dependents (safe extraction order), skipping `xbmc.*` / `kodi.*`
(the runtime provides them).

- **Base Setup** (`resolve_closure_ordered`): an ordered list of indexes
  (peno64 first, official Kodi repo last, platform-aware); first repo to declare
  an id wins.
- **Curated video install** (`install_selection` → `build_index` +
  `resolve_closure_combined`): a single combined index across every repo installed
  on the box plus the official repo. Across
  third-party repos the **highest version wins** (`merge_index` / `ver_key`), but
  the **official repo is preferred** (`prefer=True`) for shared `script.module.*`
  so those stay Kodi-matched.

Why highest-wins matters: an old fork shadowing e.g. `script.module.resolveurl
5.0.09` is rejected by Omega as incompatible; highest-wins pulls `5.1.200`, which
loads.

## 8. Self-uninstall — delete your own dir, let the restart finalise

Omega has **no uninstall builtin and no JSON-RPC uninstall** (see §1's namespace
list). The supported mechanism:

1. Delete the add-on's own directory under `special://home/addons/`
   (`system.self_uninstall()`, **basename-guarded** so it can only ever remove
   itself).
2. The end-of-run restart lets Kodi's add-on scan skip the missing dir and
   `AddonDatabase::SyncInstalled` delete the stale rows — no dangling DB row, no
   "broken add-on".

Safe on macOS/Linux/Android. On Windows the running file is locked, so removal is
non-fatal (`shutil.rmtree(..., ignore_errors=True)`). A **library** add-on
(`script.module.tony7bones`) is deliberately left installed.

## 9. Restart at the end — platform-correct

`system.restart_kodi()` asks the user Restart-now / Later, then:

- **Desktop** (macOS / Windows / Linux): `RestartApp()`. (A macOS app bundle
  accepts it but may not relaunch — acceptable.)
- **Android / Fire Stick**: `RestartApp()` can't relaunch, so `Quit()` and tell
  the user to reopen Kodi (`system.is_android()` gates this).

A restart is needed to settle binary add-ons, apply stamped origins / language
resources, and pick up skin + sources changes (including the just-set MOD V2 skin
— see §13). On Android / Fire TV, where Kodi cannot self-relaunch, the user
reopens it manually; on that reopen MOD V2 is the active skin and the modv2plus
boot service auto-applies the patch.

## 10. The home-screen "program tile" trap

Estuary's home **Programs** widget is `addons://sources/executable/` — every
add-on with `<provides>executable</provides>`, the same list as _My add-ons >
Program add-ons_. You cannot be runnable-and-listed without also being a home
tile. Tactics used here:

- A one-shot utility **self-uninstalls** after running (both Setups).
- A shared library is `xbmc.python.module` with **no** executable → invisible
  (`script.module.tony7bones`).
- A **repository** must NOT carry an `xbmc.python.script` extension — that is
  exactly what made our repo show up as a program; it was removed.

## 11. Estuary skin settings persistence — write in-memory, not to the file

Kodi holds the active skin's bools in memory and **rewrites `settings.xml` on
shutdown**, so a direct file write to
`addon_data/skin.estuary/settings.xml` is clobbered. Use
`xbmc.executebuiltin("Skin.SetBool(<id>)")` (in-memory) — that value persists on
shutdown.

Home-menu hide ids are `HomeMenuNo<X>Button`; some are **singular**
(`HomeMenuNoMovieButton`, `HomeMenuNoMusicVideoButton`). Setting the bool true ⇒
the item is hidden (Estuary gates each with
`<visible>!Skin.HasSetting(HomeMenuNo<X>Button)</visible>`).

The code applies **both** mechanisms: `_trim_home_menu_setbool()`
(`Skin.SetBool`, the one that survives the restart) and
`_trim_home_menu_writefile()` (a belt-and-suspenders `settings.xml` merge that
preserves all other settings, using the lowercase ids the skin persists —
`Skin.HasSetting` is case-insensitive). It is a no-op when a non-Estuary skin is
active. See `_trim_home_menu*` in `script.tony7bones.bootstrap/default.py`.

## 12. File-manager sources

Edit `userdata/sources.xml`'s `<files>` section: create the file/section if
missing, **preserve** every existing source, and **dedupe on name OR path**.
Changes go live after the restart (Kodi caches `sources.xml` at startup). See
`_add_file_sources()` / `_make_files_source()` in the base Setup. (The fresh-box
file source the user adds by hand to reach the repo is named `.tony7.bones` — see
the verification playbook.)

## 13. Skin activation — set `lookandfeel.skin` RIGHT before the restart

This one is non-obvious and cost a real wipe-and-test to catch.
`Settings.SetSettingValue("lookandfeel.skin", <id>)` **does** switch the live
skin immediately — but it also starts Kodi's **"Keep this skin?" ~10 s safety
timeout**. If nothing confirms within that window, Kodi **reverts** to the
previous skin. Unattended there is nothing to confirm, so if there is a long gap
between setting the skin and the restart, the box reverts to stock Estuary before
shutdown ever persists the choice.

Two reliable ways to make the activation stick:

- ✅ **Set `lookandfeel.skin` immediately before the restart** (what the bootstrap
  does). Kodi writes the in-memory skin to `guisettings.xml` on shutdown, and a
  short set→restart gap beats the revert timeout.
- ✅ **Write `guisettings.xml` while Kodi is fully down** (no live timeout to race).

What the bootstrap does (`script.tony7bones.bootstrap/default.py:run()`):
`_install_skin()` extracts + enables the skin and its proxy-invisible deps but
**does NOT set the skin**. `run()` then does the box config and, **last**, sets
`lookandfeel.skin = skin.estuary.modv2` and immediately calls `restart_kodi()`.

> Two prerequisites before the skin can even be set (else Kodi silently keeps
> stock Estuary regardless of timing): the freshly-extracted skin must be
> **registered** (`UpdateLocalAddons`) AND **enabled** (`SetAddonEnabled`). See
> `_install_skin()` and §1–2 above.

The MOD V2+ patch is NOT applied during Setup — it cannot run until MOD V2 is the
**active** skin, which only happens after this restart, by which point the Setup
has self-uninstalled. The `script.tony7bones.modv2plus` **boot service** closes
that gap (see `modv2plus-dev-cycle-and-lessons.md`).
