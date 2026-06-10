"""Platform detection, restart, and self-uninstall primitives.

These wrap the parts of the install flow that touch Kodi's process / platform:
detecting the binary-add-on platform tag, whether we are on Android (where the
app cannot relaunch itself), removing the calling Setup add-on's own directory,
and the end-of-setup restart. They are identical between the two Setups, so they
live here once.
"""

import json
import os

import xbmc
import xbmcgui
import xbmcvfs


def platform_tag():
    """Kodi's platform/arch tag for binary add-ons, e.g. 'osx-arm64'.

    Mirrors the way the official repo names its platform-specific datadirs
    (<id>+<platform>-<arch>/). Detected at runtime from os.uname()/os.name so the
    correct native build is selected on any machine. Returns None on platforms
    whose binaries are not served from this mirror (e.g. desktop Linux, which
    ships binary add-ons via the OS package manager).
    """
    name = os.name
    try:
        sysname = os.uname().sysname.lower()
        machine = os.uname().machine.lower()
    except AttributeError:  # Windows has no os.uname()
        sysname = ""
        import platform as _platform

        machine = _platform.machine().lower()

    if sysname == "darwin":
        arch = "arm64" if machine in ("arm64", "aarch64") else "x86_64"
        return f"osx-{arch}"
    if name == "nt" or sysname.startswith("win"):
        # Kodi tags: windows-x86_64 (64-bit) / windows-i686 (32-bit).
        return "windows-x86_64" if machine in ("amd64", "x86_64") else "windows-i686"
    if "android" in sysname or os.environ.get("ANDROID_ROOT"):
        return "android-aarch64" if machine in ("aarch64", "arm64") else "android-armv7"
    # Linux/other: binaries come from the distro, not this mirror.
    return None


def is_android():
    """True when running on Android (incl. Fire Stick), where the app cannot
    relaunch itself. Detected the same way as platform_tag()."""
    if os.environ.get("ANDROID_ROOT") or os.environ.get("ANDROID_DATA"):
        return True
    try:
        return "android" in os.uname().sysname.lower()
    except AttributeError:  # Windows
        return False


def self_uninstall(addon_id, log):
    """Remove a Setup add-on's own directory so it leaves no permanent home tile.

    Kodi 21 Omega has NO uninstall path a script can call: there is no
    UninstallAddon executebuiltin (only install/enable/disable/run exist) and no
    JSON-RPC uninstall method (the Addons namespace exposes only GetAddons /
    GetAddonDetails / SetAddonEnabled / ExecuteAddon). The supported mechanism is
    therefore: delete the add-on's own directory, then let the end-of-setup
    restart finalise removal. On the next start Kodi's add-on scan
    (CAddonMgr::FindAddons) skips the now-missing dir and
    AddonDatabase::SyncInstalled deletes the stale rows — so there is no dangling
    DB row and no "broken add-on".

    Defensive by design: callers run this only after everything else succeeded,
    it never raises (a failure here must not abort the run), and it deletes ONLY
    the add-on directory whose basename matches `addon_id` — nothing else.
    """
    try:
        my_dir = xbmcvfs.translatePath("special://home/addons/" + addon_id)
        # Hard guard: only ever delete the caller's OWN add-on directory.
        if os.path.basename(os.path.normpath(my_dir)) != addon_id:
            log(f"self-uninstall: refusing unexpected path {my_dir}", xbmc.LOGERROR)
            return
        if os.path.isdir(my_dir):
            import shutil

            shutil.rmtree(my_dir, ignore_errors=True)
            log(f"self-uninstall: removed {my_dir}", xbmc.LOGINFO)
    except Exception as e:  # noqa: BLE001 - self-uninstall must never abort the run
        log(f"self-uninstall failed (non-fatal): {e}", xbmc.LOGERROR)


def _set_skin_setting(skin_id):
    """Write lookandfeel.skin via JSON-RPC (the live skin switch)."""
    xbmc.executeJSONRPC(
        json.dumps(
            {
                "jsonrpc": "2.0",
                "method": "Settings.SetSettingValue",
                "params": {"setting": "lookandfeel.skin", "value": skin_id},
                "id": 1,
            }
        )
    )


def _wait_skin_quiescent(skin_id, log):
    """Bounded wait for script.skinshortcuts' first menu build for `skin_id`.

    When the freshly-activated skin's `script-skinshortcuts-includes.xml` does
    not exist yet, skinshortcuts builds it and finishes with a ReloadSkin that
    DESTROYS any open modal dialog — live runs lost both the "Keep this skin?"
    confirm (~270 ms after the switch; silent revert to stock) and the
    end-of-gate restart prompt to exactly this reload. Waiting here, inside the
    activation seam, keeps the caller's later dialogs out of the blast radius.

    Returns as soon as the includes file exists (plus a short grace for the
    ReloadSkin that follows the write), immediately when skinshortcuts is not
    installed (nothing will reload), and gives up after ~30s (sub-second on a
    desktop, but a real Fire TV took >14s for the first build — and that was
    while concurrent re-asserts kept reloading the skin under it; never block
    activation forever on it). Never raises.
    """
    try:
        ss_dir = xbmcvfs.translatePath("special://home/addons/script.skinshortcuts")
        if not os.path.isdir(ss_dir):
            return
        inc = xbmcvfs.translatePath(
            "special://home/addons/{}/xml/script-skinshortcuts-includes.xml".format(
                skin_id
            )
        )
        for _ in range(120):  # up to ~30s at 250ms
            if os.path.exists(inc):
                xbmc.sleep(1000)  # grace: the build's ReloadSkin follows the write
                return
            xbmc.sleep(250)
        log(
            "activate_skin: skinshortcuts menu not built within the wait — proceeding",
            xbmc.LOGINFO,
        )
    except Exception:  # noqa: BLE001 - a settle helper must never break activation
        pass


def activate_skin(skin_id, log, attempts=3):
    """Switch the active skin to skin_id, accept Kodi's "Keep this skin?"
    confirmation, and VERIFY the switch actually stuck — re-asserting it if the
    confirm was destroyed. Returns True when the skin is verified active and
    committed, False when it would not stick (logged loud, never silent).

    Setting lookandfeel.skin live triggers a skin reload and pops a yes/no
    confirm (window 10100) that DEFAULTS TO REVERT on its timeout. Two failure
    modes are covered, both observed on real boxes:

    * The confirm times out unaccepted (the original Fire TV bug): we poll for
      the dialog and click its Yes button (control 11) — verified on a real
      Fire TV.
    * The confirm is DESTROYED before our poll sees it: on a fresh box
      script.skinshortcuts' first menu build ends in a ReloadSkin that killed
      the confirm ~270 ms after the switch (log-proven), silently reverting the
      skin to stock. The poll is 200 ms (fast enough to win most races), it
      exits early when it SEES the revert (the skin was live, then flipped
      back), and — the fundamental fix — after the settle the END STATE is
      verified via getSkinDir() and the switch is RE-ASSERTED (bounded
      `attempts`). Before each re-assert we WAIT for skinshortcuts quiescence
      (`_wait_skin_quiescent`): on a slow real Fire TV the first build runs
      >14s, an immediate re-assert lands INSIDE it (the fresh confirm is
      destroyed unaccepted — Kodi treats that as "No" — even when our
      SendClick already logged the accept), and the reload each re-assert
      causes re-kicks the build, so all attempts can burn inside one build
      window (observed live: 3/3 lost, box restarted on stock). Once the
      build's includes file exists the re-asserted confirm survives and the
      accept commits.

    The post-accept settle also waits for skinshortcuts quiescence
    (`_wait_skin_quiescent`) so the caller's NEXT dialog (the restart prompt —
    the second observed victim of the same reload) is shown after the blast
    radius, not inside it.

    If the skin never even goes live and no confirm appears, the set was
    rejected outright (skin not registered/enabled — see the install ritual);
    re-asserting cannot fix that, so we bail after the first attempt and
    return False honestly.
    """
    for attempt in range(1, attempts + 1):
        _set_skin_setting(skin_id)
        accepted = False
        saw_live = False
        for _ in range(60):  # up to ~12s at 200ms for the confirm to render
            # Track live-ness FIRST, every iteration — including while the
            # confirm is visible (Kodi switches the skin live, THEN shows the
            # confirm, so the skin is already live when the dialog renders).
            # Recording it only in the no-dialog branch missed exactly this and
            # misread a destroyed-while-visible confirm as "never went live"
            # (caught on the live box).
            live_now = (xbmc.getSkinDir() or "") == skin_id
            if live_now:
                saw_live = True
            if xbmc.getCondVisibility("Window.IsVisible(10100)"):
                xbmc.executebuiltin("SendClick(11)")  # control 11 == Yes (keep)
                accepted = True
                log(
                    "activate_skin: accepted keep-skin for {}".format(skin_id),
                    xbmc.LOGINFO,
                )
                break
            if saw_live and not live_now:
                # The skin WAS live and flipped back: the confirm was destroyed
                # unaccepted and Kodi reverted. Stop polling for a dialog that
                # no longer exists; fall through to the verify + re-assert.
                log(
                    "activate_skin: keep-skin confirm lost — {} reverted "
                    "(attempt {}/{})".format(skin_id, attempt, attempts),
                    xbmc.LOGWARNING,
                )
                break
            xbmc.sleep(200)
        else:
            log(
                "activate_skin: no keep-skin dialog appeared for {}".format(skin_id),
                xbmc.LOGINFO,
            )
        xbmc.sleep(2000)  # let the keep commit + the skin settle
        # VERIFY the end state — never trust the dialog dance alone.
        if (xbmc.getSkinDir() or "") == skin_id:
            _wait_skin_quiescent(skin_id, log)
            if (xbmc.getSkinDir() or "") == skin_id:
                log(
                    "activate_skin: {} active and committed (attempt {})".format(
                        skin_id, attempt
                    ),
                    xbmc.LOGINFO,
                )
                return True
        if not saw_live and not accepted:
            # The set was rejected outright (the live switch never happened) —
            # the skin is not a registered, enabled choice. Re-asserting the
            # same rejected set cannot help; fail fast and loud instead.
            log(
                "activate_skin: {} never went live — set rejected "
                "(skin not registered/enabled?)".format(skin_id),
                xbmc.LOGERROR,
            )
            return False
        log(
            "activate_skin: {} did not stick (attempt {}/{}) — waiting for "
            "skinshortcuts quiescence, then re-asserting".format(
                skin_id, attempt, attempts
            ),
            xbmc.LOGWARNING,
        )
        # THE SLOW-BOX FIX (live-proven on a real Fire TV): a re-assert fired
        # while skinshortcuts' first build is STILL RUNNING just feeds the same
        # destroyer — the fresh confirm is torn down unaccepted (which Kodi
        # treats as "No" and reverts), and the skin reload the re-assert causes
        # re-kicks the build, perpetuating the race until the attempts run out
        # (observed: 3/3 attempts lost inside one >14s first build). Wait for
        # the build to finish BEFORE re-asserting so the next confirm survives
        # long enough for our accept to commit.
        _wait_skin_quiescent(skin_id, log)
    log(
        "activate_skin: FAILED to keep {} after {} attempts".format(skin_id, attempts),
        xbmc.LOGERROR,
    )
    return False


def restart_kodi(title, log):
    """Restart Kodi the platform-correct way after setup completes.

    A restart is required so Kodi fully loads every freshly extracted add-on
    (avoids the Fire Stick end-of-setup freeze where half-registered add-ons
    leave the UI wedged) and so stamped origins / language resources are live on
    first launch. The user always chooses Restart now / Later.

    * Desktop (Windows / Linux / macOS): RestartApp() truly cycles the app.
    * Android / Fire Stick: RestartApp() is a no-op (it is "only implemented under
      Windows and Linux"), so Kodi cannot relaunch itself — the user reopens it by
      hand and the boot service finishes setup. We do NOT show a blocking prompt
      here: the skin was just set live, so any time spent waiting lets Kodi's
      "Keep this skin?" timeout revert it to stock, and the half-rendered new skin
      can wedge the GUI so a yes/no never clears (the "it hangs, force-kill it"
      symptom). Instead we show a non-blocking notice and Quit() promptly. Quit is
      a CLEAN shutdown — it flushes the skin choice + all skin settings to disk —
      and a hard kill (os._exit / killall) is deliberately avoided because it would
      lose those unsaved settings.
    """
    if is_android():
        log("restart: Android clean Quit() (prompt-free)", xbmc.LOGINFO)
        xbmcgui.Dialog().notification(
            title,
            "Setup complete — closing Kodi. Reopen it to finish.",
            xbmcgui.NOTIFICATION_INFO,
            6000,
        )
        xbmc.sleep(3000)  # let the notice render; well under the skin-revert window
        xbmc.executebuiltin("Quit")
        return

    # autoclose BOUNDS the prompt's lifetime (Phase 6, live-proven necessity):
    # the box is in a reload-prone state here — the skin was just activated,
    # and the modv2plus boot service applies its patch once MOD V2 is live,
    # ending in a skinshortcuts rebuild + ReloadSkin that DESTROYED a
    # still-open prompt ~45s in on a live run (Kodi then segfaulted tearing
    # the modal down mid-reload). A destroyed dialog's answer is garbage; the
    # autoclose answer is safe EITHER way: observed live it returns True →
    # the restart proceeds (the unattended one-tap completes itself); a False
    # would be the documented "Later" self-heal path (the next launch
    # re-offers the gate / Express re-runs idempotently). 20s is
    # human-generous and safely inside the observed destroyer window.
    if xbmcgui.Dialog().yesno(
        title,
        "Setup is complete. Kodi needs to restart to finish.\n\nRestart now?",
        yeslabel="Restart now",
        nolabel="Later",
        autoclose=20000,
    ):
        log("restart: RestartApp()", xbmc.LOGINFO)
        xbmc.executebuiltin("RestartApp()")
