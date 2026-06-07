"""Install-closure orchestration shared by both Setups.

Two orchestrators, mirroring the two resolvers in index.py:

* install_with_deps — the base Setup's single-app installer: resolve one app's
  closure across ordered indexes (peno64 then official, platform-aware for binary
  add-ons), extract the closure, rescan, enable dependencies-first. No origins,
  no disable list.

* install_closure — the video Setup's installer: extract a pre-resolved combined
  closure (deps first), rescan, enable all, stamp every add-on's origin with its
  source repo, then disable any install-then-disable ids that ended up installed.

Neither uses Kodi's InstallAddon builtin (a modal job on the GUI thread that
blocks forever when driven from a script); both register add-ons by
direct-extract + SetAddonEnabled, which never freezes.
"""

import xbmc

from . import index, net, repos, system


def install_with_deps(addon_id, dialog, ordered_bases, official_base, log):
    """Install an app and its full dependency closure by direct extract.

    `ordered_bases` is an ordered list of repo base urls to resolve plain
    (python) add-ons from (e.g. [peno64]); `official_base` is loaded with this
    machine's platform tag so binary add-ons (pvr.iptvsimple + inputstream.*
    clients) resolve to the correct native build, and is appended LAST. After
    extracting the closure we rescan local add-ons and enable each id
    dependencies-first, which registers them and makes them function. Returns True
    once the app reports as installed.
    """
    if net.is_installed(addon_id):
        return True
    plat = system.platform_tag()
    indexes = [(b, index.load_index_simple(b)) for b in ordered_bases]
    indexes.append((official_base, index.load_index_simple(official_base, plat)))
    closure = index.resolve_closure_ordered([addon_id], indexes)
    if not any(aid == addon_id for aid, _ in closure):
        return False  # could not even resolve the app itself
    for aid, url in closure:
        if net.is_installed(aid):
            continue
        net.extract_zip(url, dialog, 100, log)
    # Rescan so Kodi sees the freshly extracted dirs, then enable the closure
    # dependencies-first so each app's imports are satisfied when it is enabled.
    net.update_local_addons()
    xbmc.sleep(2000)
    for aid, _url in closure:
        net.enable(aid)
    return net.is_installed(addon_id)


def disable_after_install(installed_ids, disable_ids, log):
    """Disable every id in `disable_ids` that actually got installed.

    `installed_ids` is the set of ids present after the closure was extracted +
    enabled. Only ids that ended up installed are disabled (e.g. Dailymotion is
    present only when The Loop was selected).

    Why disable instead of exclude: the disabled add-on remains installed, which
    satisfies the requiring add-on's REQUIRED dependency check (no broken flag, no
    "required" lock) while the add-on itself never runs. This survives an
    auto-update of the requiring add-on with no per-update re-patching.

    Never raises: a failure here must not abort the run.
    """
    for aid in sorted(disable_ids):
        if aid not in installed_ids:
            continue
        try:
            net.disable(aid)
            log(f"disabled after install: {aid}", xbmc.LOGINFO)
        except Exception as e:  # noqa: BLE001 - one bad disable must not abort
            log(f"disable_after_install failed for {aid}: {e}", xbmc.LOGERROR)


def install_closure(closure, dialog, disable_ids, log):
    """Extract every zip in `closure` (deps first), rescan, enable each, stamp
    every add-on's origin with its source repo, then disable any install-then-
    disable ids that ended up installed.

    `closure` is a list of (addon_id, zip_url, origin). `disable_ids` is the set
    of ids to install-but-disable (e.g. {plugin.video.dailymotion_com}). Returns
    the count of closure ids that report installed afterwards.

    Order: extract -> enable all -> stamp origins -> disable the disable-list. The
    requiring apps stay enabled; only ids in `disable_ids` are disabled at the end.
    """
    for aid, url, _origin in closure:
        if net.is_installed(aid):
            continue
        net.extract_zip(url, dialog, 100, log)
    # Rescan so Kodi sees the freshly extracted dirs, then enable the closure
    # dependencies-first so each app's imports are satisfied when enabled.
    net.update_local_addons()
    xbmc.sleep(2000)
    for aid, _url, _origin in closure:
        net.enable(aid)
    # Stamp origins so the apps are not treated as "unknown source" orphans.
    repos.set_origins({aid: origin for aid, _url, origin in closure}, log)
    # Now that everything is extracted, enabled and origin-stamped, disable the
    # install-then-disable ids (e.g. Dailymotion) that actually got installed —
    # installed (so the requiring app's dep is satisfied) but never run.
    installed_ids = {aid for aid, _url, _origin in closure if net.is_installed(aid)}
    disable_after_install(installed_ids, disable_ids, log)
    return sum(1 for aid, _url, _origin in closure if net.is_installed(aid))


def install_selection(selected, official_base, disable_ids, dialog, log):
    """Resolve + install a set of apps with their combined dependency closure.

    The shared entry point folded in from the retired standalone Video Add-ons
    Setup. Enables the source repos (so stamped origins reference repos Kodi
    knows about — a blank origin is what breaks The Loop and POV), builds the
    combined index from the installed repos + the official repo (platform-aware,
    `official_base` last), resolves the closure for `selected`, then extracts +
    enables + origin-stamps it via install_closure and applies the install-then-
    disable set (`disable_ids`). Shares the caller's progress `dialog` (may be
    None). NEVER prompts, summarises, self-uninstalls, or restarts — the caller
    owns that UX. Returns how many of `selected` ended up installed.
    """
    if dialog is not None:
        dialog.update(0, "Resolving add-ons...")
    repos.enable_source_repos(log)
    plat = system.platform_tag()
    idx = index.build_index(repos.repo_dirs(log), official_base, plat)
    if not idx:
        log("could not read any repository index", xbmc.LOGERROR)
        return 0
    closure, _missing = index.resolve_closure_combined(selected, idx)
    if closure:
        if dialog is not None:
            dialog.update(10, "Installing add-ons and dependencies...")
        install_closure(closure, dialog, disable_ids, log)
    return sum(1 for aid in selected if net.is_installed(aid))
