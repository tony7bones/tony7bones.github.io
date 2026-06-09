# Kodi: Restart-and-Continue — Research + Findings

How a Kodi one-shot installer should restart Kodi and reliably continue afterward
(applying a patch / finishing config), across desktop and Android/Fire TV.

> **Provenance.** The autonomous research agents were blocked by approval prompts
> and never produced reports. This document is a synthesis of (a) direct web
> research against the Kodi wiki, Kodi forums, the Kodi GitHub, and a real
> force-close add-on, and (b) **first-hand findings from debugging the Office/
> bedroom Fire TV live** — we reproduced every failure mode below on real
> hardware this cycle.

---

## TL;DR — why our finish is flaky

Three independent things collide at the end of Setup:

1. **`RestartApp` is a no-op on Android / Fire TV.** Kodi cannot relaunch itself
   on Android — the OS owns the app lifecycle. So on a Fire Stick the "restart"
   does nothing: `run()` ends, the progress dialog closes, and Kodi just sits
   there. That idle state _looks_ like a freeze → the user force-kills it.
2. **The boot service races the skin load.** After reopening, the modv2plus
   service can run before the skin/GUI is fully up, and `script.skinshortcuts`
   builds the home menu **asynchronously** → the home renders blank until a later
   build/reload. This is the "sometimes it continues, sometimes it doesn't."
3. **Rapid force-kill / relaunch cycles can wedge the GPU state.** We saw Kodi
   crash at GL init (`GLES: Maximum texture width …`, before the skin even loads)
   after several quick stop/start cycles; only a full **device reboot** cleared it.

None of these is "the script is wrong" — they're platform + timing realities.

---

## ⭐ THE fix (proven on hardware 2026-06-08) — three changes, in order

This is the most important section. The finish is now **deterministic** on a real
Fire TV. There were actually **three** problems, and the third is the one that was
hiding:

1. **Accept Kodi's "Keep this skin?" dialog.** _(the missing piece)_ Changing
   `lookandfeel.skin` live raises a yes/no confirm (**window 10100**) that
   **defaults to REVERT on its timeout**. If you don't accept it, Kodi rolls the
   skin back to stock Estuary. The old code never accepted it — it only ever
   "worked" by accident when a freeze/force-kill stopped Kodi _before_ it could
   revert. Earlier guidance here ("set the skin last and restart _promptly_ to
   beat the timeout") was **wrong**: restarting faster just guarantees you quit
   before accepting → guaranteed revert.
   **Fix:** after setting the skin, wait for window 10100 and click its **Yes**
   button — **`SendClick(11)`** (control 11 = Yes of Kodi's yes/no dialog).
   Verified live: control 11 keeps the skin, no revert. → shipped as
   `tony7bones.system.activate_skin(skin_id, log)` (module ≥ 1.1.2).
2. **Clean `Quit`, not `RestartApp` and not a hard kill.** On Android `RestartApp`
   is a no-op; a hard kill (`os._exit`) loses unsaved settings. `Quit` cleanly
   shuts down (flushing the now-committed skin), Kodi closes unambiguously, the
   user reopens. Do it **prompt-free** (no blocking yes/no) so nothing stalls.
   → `restart_kodi` (module ≥ 1.1.1).
3. **The boot service waits for the home to render, then builds the menu.** It
   waits for `Window.IsVisible(10000)` **and** the skin to be active (not just
   `getSkinDir()==id`), settles, then applies — so it never races the async
   skinshortcuts build. → modv2plus ≥ 1.4.4. Run-once stays idempotent (the
   Home.xml marker).

**Sequence that works:** install → `activate_skin` (set + **accept dialog**) →
clean `Quit` → reopen → service waits for home → builds menu → renders.
Hardware result: no force-kill, skin persists as `skin.estuary.modv2`, home
renders first try with **0** `Control 9000` focus errors.

---

## (A) Restart builtins — what each does, per platform

| Builtin      | Desktop (Win / Linux)                                          | macOS      | Android / Fire TV              |
| ------------ | -------------------------------------------------------------- | ---------- | ------------------------------ |
| `RestartApp` | Restarts Kodi ✓                                                | unreliable | **NO-OP** — does nothing       |
| `Quit`       | Exits Kodi cleanly                                             | Exits      | Closes Kodi (no relaunch)      |
| `ShutDown`   | System power action (configurable: power off / suspend / quit) | —          | triggers Android leave-app     |
| `Reboot`     | Reboots the **device**                                         | —          | device-level (usually blocked) |
| `Powerdown`  | Powers off the **device**                                      | —          | device-level (usually blocked) |

**Key takeaway:** on Android/Fire TV there is **no builtin that cleanly restarts
Kodi**. `RestartApp` is documented as Linux/Windows-only; the long-standing forum
thread "Quit, Shutdown, Restart, Reboot not working" is specifically about Android
devices where these are no-ops. (Confirmed first-hand on our Fire TV.)

---

## (B) Why it hangs at the end of install

- **Android RestartApp no-op** (the main one): the run finishes, the dialog
  closes, nothing relaunches → looks frozen.
- **A big direct-extract install + `UpdateLocalAddons()` scan + enabling dozens
  of add-ons** leaves Kodi busy; firing a restart while the GUI/script is still
  mid-work can freeze the UI. (Kodi has a reproducible "install add-on → UI
  freeze" class of bug — see xbmc/xbmc#28032.)
- **The skin was just switched** (`lookandfeel.skin`) and is mid-load; if the
  skinshortcuts menu hasn't built, the home is blank/unfocusable
  (`Control 9000 … can't focus`).
- **Modal dialogs from a script thread** (`Dialog().ok/yesno`) block until
  dismissed; if the box is mid-restart the click never lands.

**Avoid the hang:** finish all work, close every dialog, let `run()` be
effectively done, add a short settle delay, _then_ restart — and on Android don't
pretend `RestartApp` did anything.

---

## (C) The robust restart-and-continue pattern

1. Do **all** install + config work first.
2. Set `lookandfeel.skin`, then **accept Kodi's "Keep this skin?" dialog**
   (window 10100) by clicking its Yes button — **`SendClick(11)`** — so the skin
   persists instead of reverting to stock on the dialog's timeout. Shipped as
   `tony7bones.system.activate_skin(skin_id, log)` (module ≥ 1.1.2). _(Do NOT rely
   on "restart promptly to beat the timeout" — that advice was wrong; see the ⭐
   fix section above.)_
3. Self-uninstall (delete own dir; the restart finalizes it).
4. **Restart, platform-correctly:**
   - **Desktop:** `RestartApp`.
   - **Android / Fire TV:** you _cannot_ self-restart. Choose:
     - **a. Prompt to close + reopen** (what we do now) — works, but the idle
       state reads as "frozen."
     - **b. Force-close so reopening is the only step** — a force-close add-on
       (e.g. `Based-Skid/plugin.close.kodi`) kills Kodi; the user just taps the
       icon again. Unambiguous end state (Kodi is gone → reopen), which is a
       _better UX_ than "it looks stuck."
     - **c. Android intent relaunch** — cleanest in theory, but a script inside
       Kodi generally can't `am force-stop` itself without the right
       permissions/root; treat as unverified.
5. **After reopen, a boot SERVICE continues the work.** A one-shot script has no
   native "run after restart" callback — an `xbmc.service` add-on running on
   startup is the only reliable hook.

---

## (D) The continue-after-restart pattern (our service)

- **`xbmc.service` add-on = correct** (we have one: modv2plus `service.py`).
- **It MUST wait for the GUI/skin to be ready before acting.** Services start
  _before_ the skin finishes loading. Poll with
  `xbmc.Monitor().waitForAbort(interval)` until **both**: the target skin is
  active **and** `System.HasLoaded` / the Home window (10000) is visible — then
  act. This kills the "sometimes blank" race.
- **Run EXACTLY once via an idempotent state check** (we do: the Home.xml marker)
  — self-healing, better than a delete-me marker file.
- **Build the menu deterministically and wait** for the includes before reloading
  (our modv2plus 1.4.1 fix) so the home isn't blank on the first paint.

State-persistence options, ranked for our case:

| Mechanism                                               | Pros                                        | Cons                                      |
| ------------------------------------------------------- | ------------------------------------------- | ----------------------------------------- |
| **Idempotent state check** (marker in the patched file) | self-healing, no cleanup, run-once for free | must have a reliable "is it done?" signal |
| Marker file in `addon_data`                             | simple                                      | must clear it; can desync                 |
| Window property (`Window(10000).Property`)              | survives within a session                   | **lost on restart** — useless here        |
| Settings flag                                           | persists                                    | must reset; clutters settings             |

---

## (E) Gotchas we hit live this session

- **"Keep this skin?" timeout** reverted `lookandfeel.skin` when the dialog
  (window 10100) was never accepted → after setting the skin, **accept the dialog
  via `SendClick(11)`** (`activate_skin`, module ≥ 1.1.2). _(fixed)_
- **skinshortcuts builds async** → blank home until built → service must
  **build + wait**. _(fixed in modv2plus 1.4.1)_
- **Service raced the skin load** → no-op / partial apply → the service now waits
  for the Home (window 10000) to render AND the target skin to be active before
  applying (see D). _(SHIPPED in modv2plus ≥ 1.4.4; current 1.4.7)_
- **Rapid force-kill cycles wedged GL init** → only a device reboot cleared it.
  Don't hammer restarts.
- **Freshly-extracted add-ons** need `UpdateLocalAddons()` + a settle delay before
  they're enabled/usable.

---

## (F) Concrete recommendations for OUR Setup

1. **Platform-correct restart — SHIPPED.** Desktop uses `RestartApp`; on
   Android / Fire TV Setup uses **`Quit`** (clean shutdown that flushes the skin)
   plus a clear "Setup complete — **close Kodi and reopen it** to finish" message,
   not `RestartApp` (a no-op there) and not a hard kill.
2. **Service readiness wait — SHIPPED** (modv2plus ≥ 1.4.4; current 1.4.7): the
   boot service polls until the skin is active **and** the Home window (10000) has
   actually rendered, before applying — not just `skin == skin.estuary.modv2`.
3. **Keep run-once as an idempotent state check** (Home.xml marker), not a fragile
   marker file.
4. **Never rapid-cycle restarts** (wedges Fire TV graphics).
5. **Evaluate a force-close** (the `plugin.close.kodi` technique) on Android so the
   end state is unambiguous (Kodi closes → user reopens), replacing the ambiguous
   "it froze" experience.

> **Relocated Fire OS 11 Sticks:** on a non-rooted Fire OS 11 Stick Kodi's data
> lives under the relocated `KODI_DATA_PATH` (e.g. `/sdcard/kodi_data/.kodi`), not
> the default Android/data tree — so the log, guisettings, and Addons DB you read
> to verify the restart/continue are under that path. See
> `docs/playbooks/firetv-stick-scoped-storage-provisioning.md`.

---

## (G) Deep-dive findings (confirmed against source) + reference code

**Builtin descriptions — verbatim from the Kodi builtins reference:**

- `Quit` → "Quits Kodi" (clean shutdown — **saves settings/db on the way out**).
- `RestartApp` → "Restarts Kodi (**only implemented under Windows and Linux**)".
- `ShutDown` → "Trigger default Shutdown action defined in System Settings".
- `Restart` / `Reboot` → restart/cold-reboot the **device** (not the app).
- `Powerdown` → power off the **device**.

So `RestartApp` being a no-op on Android/macOS is **official**, not folklore.

**Force-close is real but DANGEROUS for us.** The popular force-close add-on
`plugin.close.kodi` does it two ways:

- "Flawless" / instant kill: `os._exit(1)` — a hard exit of the Python process,
  which (running inside Kodi's process) kills Kodi instantly.
- "Old" method: shell kill by PID — on Android
  `kill $(ps | busybox grep org.xbmc.kodi …)`, on desktop `killall -9 kodi.bin`.

**Both are UNGRACEFUL — they skip Kodi's shutdown flush, so unsaved in-memory
settings are LOST** (confirmed: forcing a close means "changes may not be saved
as Kodi updates on exit … loss of GUI settings"). Our Setup sets `lookandfeel.skin`
and a pile of `Skin.SetBool` values in memory that only persist on a clean
shutdown — **so we must NOT hard-kill.** This rules out the force-close add-on
trick for us.

### The Android resolution (this is the fix for the "hang")

On Fire TV the right call is **`Quit`**, not `RestartApp` and not a force-kill:

- `Quit` triggers Kodi's **clean shutdown** → it **flushes `lookandfeel.skin` +
  all `Skin.SetBool` settings to disk**, then the app **actually closes** (no
  ambiguous "is it frozen?" state).
- Android can't relaunch the app itself (no builtin — `StartAndroidActivity`
  only launches _other_ packages), so the user reopens Kodi → the boot service
  continues. Closing cleanly + a clear "reopen to finish" message replaces the
  current limbo where `RestartApp` does nothing and the box just sits there.

Set `lookandfeel.skin` immediately before `Quit` so the in-memory skin is what
gets flushed (beats the "Keep this skin?" revert), then:

```python
import xbmc
if xbmc.getCondVisibility("System.Platform.Android"):
    # clean shutdown: flushes guisettings (skin!) then exits the app
    xbmc.executebuiltin("Quit")
else:
    xbmc.executebuiltin("RestartApp")
```

### The service-readiness wait (this is the fix for "sometimes blank / doesn't continue")

The boot service must wait for the **home window (id 10000)** to actually render
**and** the target skin to be active before it touches anything — services start
before the skin is up. Confirmed idiom (used by embycon, skin.helper.service):

```python
import xbmc
SKIN_ID = "skin.estuary.modv2"
monitor = xbmc.Monitor()
# wait until the GUI is really up: home window visible AND our skin active
while not monitor.abortRequested():
    if (xbmc.getCondVisibility("Window.IsVisible(10000)")
            and xbmc.getSkinDir() == SKIN_ID):
        break
    if monitor.waitForAbort(1):   # yields; returns True on shutdown
        break
# ...now safe to apply the patch / build the menu...
```

`Window.IsVisible(10000)` (10000 = the Home window) true ⇒ the skin has rendered
the home screen. Pair it with `xbmc.getSkinDir()` so we only act under MOD V2.
Run-once stays an **idempotent state check** (our Home.xml marker), so even if the
service fires twice it's harmless.

---

## Sources

- [List of built-in functions — Official Kodi Wiki](https://kodi.wiki/view/List_of_built-in_functions)
- [List of built-in functions (mirror, with verbatim Quit/RestartApp text)](https://alwinesch.github.io/page__list_of_built_in_functions.html)
- [AndroidBuiltins.cpp — only StartAndroidActivity, no self-restart (xbmc/xbmc)](https://github.com/xbmc/xbmc/blob/master/xbmc/interfaces/builtins/AndroidBuiltins.cpp)
- [plugin.close.kodi default.py — os.\_exit(1) + busybox/killall (Based-Skid)](https://github.com/Based-Skid/plugin.close.kodi/blob/master/default.py)
- [embycon service.py — wait-for-home-window idiom](https://github.com/faush01/plugin.video.embycon/blob/master/service.py)
- [skin.helper.service — Monitor/condition idioms](https://github.com/kodi-community-addons/script.skin.helper.service)
- [How to shut down Kodi properly (clean vs force-close loses settings) — Kodi forum](https://forum.kodi.tv/showthread.php?tid=294981)
- [Quit, Shutdown, Restart, Reboot not working (Android) — Kodi forum](https://forum.kodi.tv/showthread.php?tid=358820)
- [RestartApp doesn't work — xbmc/xbmc#19837](https://github.com/xbmc/xbmc/issues/19837)
- [Reproducible UI freeze on "install missing addon" — xbmc/xbmc#28032](https://github.com/xbmc/xbmc/issues/28032)
- [Service add-ons — Official Kodi Wiki](https://kodi.wiki/view/Service_add-ons)
- [Autoexec Service — Official Kodi Wiki](https://kodi.wiki/view/Autoexec_Service)
- [Based-Skid/plugin.close.kodi — force-close add-on (GitHub)](https://github.com/Based-Skid/plugin.close.kodi)
- First-hand: this repo's Fire TV debugging — see `docs/playbooks/modv2plus-dev-cycle-and-lessons.md` and `firetv-adb-dev.md`.
