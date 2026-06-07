"""Video Add-ons Setup — pick-and-install video add-ons for a Tony.7.Bones box.

run() (standalone):
  * shows a multiselect picker of four video add-ons (POV, The Loop, Sports HD,
    Umbrella); the first three are preselected.
  * for each chosen add-on it resolves the FULL dependency closure live from the
    repositories ALREADY INSTALLED on this box (their addons.xml indexes) plus
    the official Kodi repo (for the shared script.module.* deps), then installs
    every add-on in the closure by direct download + extract, registers + enables
    each, and STAMPS each installed add-on's `origin` with its source repo.
  * finally removes ITSELF after a successful run and restarts Kodi to finish.

install_selected(selected, dialog) is the shared install entry point used by BOTH
the standalone run() above AND the base Tony.7.Bones Setup when it chains video
installs into its single unattended run. It does the install + origin-stamp +
install-then-disable work and returns how many selected apps ended up installed;
it does NOT prompt, summarise, self-uninstall, or restart — the caller owns those
(so the chained run has exactly one summary and one restart).

The shared install machinery (HTTP fetch, addons.xml index load/merge/resolve,
zip extract, enable/disable, repo discovery, origin stamping, source-repo
enabling, self-uninstall, restart, platform detection) lives in the
script.module.tony7bones library; this file holds only the picker config and the
install-then-disable set.

Why stamp `origin`: Kodi's repository installer records which repo an add-on came
from in installed.origin. The direct-extract path leaves it blank, and a blank
origin breaks the video apps (The Loop: "installed from unknown source"; POV:
empty menu). After installing we set origin to the providing repo.

Why resolve from the INSTALLED repos: these apps live across several third-party
repos and pull shared modules from those repos and the official repo. Reading
each installed repository.* add-on.xml, building a combined index, and walking
<requires>/<import> means we always fetch the versions the box's own repos
publish — no hardcoded source that can drift.

Why not Kodi's InstallAddon builtin: on Omega it is a modal job on the GUI thread
that blocks forever when driven from a script. So the library resolves the closure
itself and extracts every zip directly, then enables each one.

No secrets are embedded in this script.
"""

import xbmc
import xbmcgui

# Shared install library (script.module.tony7bones).
from tony7bones import (
    build_index,
    enable_source_repos,
    have_source_repos,
    install_closure,
    is_installed,
    platform_tag,
    repo_dirs,
    resolve_closure_combined,
    restart_kodi,
    self_uninstall,
)

# This add-on's own id (used for self-uninstall and to skip itself).
MY_ID = "script.tony7bones.video"

# The picker. (label, addon_id). Order is load-bearing — the test pins it and the
# preselect indexes below refer to these positions.
APPS = [
    ("POV", "plugin.video.pov"),
    ("The Loop", "plugin.video.the-loop"),
    ("Sports HD", "plugin.video.sporthdme"),
    ("Umbrella", "plugin.video.umbrella"),
]

# Indexes of APPS that start checked. POV, The Loop, Sports HD on; Umbrella off.
PRESELECT = [0, 1, 2]

# Add-ons to INSTALL normally but DISABLE once the run's installs are done.
# The Loop declares plugin.video.dailymotion_com as a REQUIRED import, but nobody
# here uses Dailymotion. Installing it satisfies The Loop's dependency check (no
# broken flag, no "required" lock), then disabling it at the end means it never
# runs — and because it stays installed, this survives Loop auto-updates with no
# re-patching. Only ids listed here are disabled, and only if they ended up
# installed in this run.
DISABLE_AFTER_INSTALL = {"plugin.video.dailymotion_com"}

# The official Kodi repo index — source of last resort for shared modules so a
# script.module.* dep resolves to the Kodi-matched build.
OFFICIAL_BASE = "https://mirrors.kodi.tv/addons/omega"


def _log(msg, level=xbmc.LOGINFO):
    xbmc.log(f"[{MY_ID}] {msg}", level)


def install_selected(selected, dialog):
    """Install the chosen video apps + their full closure. Returns how many of
    `selected` ended up installed.

    Shared by run() (standalone) and the base Setup's chained run. It enables the
    source repos, builds the combined index from the installed repos + official
    repo, resolves the closure for `selected`, then extracts + enables + stamps
    origins + applies the install-then-disable set (Dailymotion). It NEVER
    prompts, summarises, self-uninstalls, or restarts — the caller owns those.

    `dialog` is a DialogProgress shared with the caller (so a chained run shows
    one continuous progress bar). May be None.
    """
    if dialog is not None:
        dialog.update(0, "Resolving video add-ons...")

    # Enable the source repos so the origins we stamp reference repos Kodi knows
    # about (a blank origin is what breaks The Loop and POV).
    enable_source_repos(_log)

    plat = platform_tag()
    index = build_index(repo_dirs(_log), OFFICIAL_BASE, plat)
    if not index:
        _log("could not read any repository index", xbmc.LOGERROR)
        return 0

    closure, _missing = resolve_closure_combined(selected, index)
    if closure:
        if dialog is not None:
            dialog.update(10, "Installing video add-ons and dependencies...")
        install_closure(closure, dialog, DISABLE_AFTER_INSTALL, _log)

    return sum(1 for aid in selected if is_installed(aid))


def run():
    # Bail early with a clear message if the box has no source repos yet.
    if not have_source_repos(_log):
        xbmcgui.Dialog().ok(
            "Video Add-ons Setup",
            "No source repositories are installed yet.\n\n"
            "Run the main Tony.7.Bones Setup first, then run this again.",
        )
        return

    labels = [label for label, _aid in APPS]
    choices = xbmcgui.Dialog().multiselect(
        "Video Add-ons Setup", labels, preselect=PRESELECT
    )
    # Cancelled (None) or nothing selected: make no changes and DO NOT
    # self-uninstall, so the user can re-run the picker later.
    if not choices:
        _log("picker cancelled or empty — no changes")
        return

    selected = [APPS[i][1] for i in choices]

    dialog = xbmcgui.DialogProgress()
    dialog.create("Video Add-ons Setup", "Resolving add-ons...")

    installed_ok = install_selected(selected, dialog)
    # Track unresolved APP targets (not just deps) so the summary can name them.
    unresolved_apps = [aid for aid in selected if not is_installed(aid)]

    dialog.close()

    msg = f"Installed {installed_ok}/{len(selected)} selected add-on(s)."
    if unresolved_apps:
        msg += "\n\nNot installed: " + ", ".join(unresolved_apps)
    msg += "\n\nKodi will restart to finish setup."
    xbmcgui.Dialog().ok("Video Add-ons Setup", msg)

    # Self-remove only after an actual install run completed. Never raises.
    self_uninstall(MY_ID, _log)

    # Restart so the freshly installed apps load their language resources and the
    # stamped origins take effect on first launch. Only reached after an install.
    if installed_ok:
        restart_kodi("Video Add-ons Setup", _log)


if __name__ == "__main__":
    run()
