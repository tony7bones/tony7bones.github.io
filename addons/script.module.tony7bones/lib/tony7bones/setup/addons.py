"""apply_addons — Layer 2 (Add-ons) of the modular setup.

The Add-ons layer is the curated content gate: the base source repos + base apps
(install_base) and the curated video add-ons (install_video, incl. the install-
then-disable of ``plugin.video.dailymotion_com``). Weather + RSS (both branded-
look CONFIG, not content) live in the Foundation layer instead — see
``tony7bones.setup.foundation``. Stop here = the full box.

This module holds the bodies LIFTED VERBATIM out of
``script.tony7bones.bootstrap/default.py`` (Phase 2c) — ``_install_base`` /
``_install_video`` (+ their helpers/constants), behaviour-identical.
``default.py`` now keeps thin re-export shims that delegate here so every
existing reference and test (``boot.mod._install_base`` / ``_install_video`` +
``VIDEO_APPS`` / ``ADDONS``) keeps working unchanged.

THE INTERLEAVING CONSTRAINT (the hard part — read before touching ``run()``).
In the monolith ``run()`` the order is: base install -> video install ->
``apply_foundation`` -> summary/self-uninstall -> ``_configure_box`` (weather/IPTV/
RSS) -> activate-skin -> restart. So the base/video INSTALL runs EARLY and the
weather/RSS CONFIG runs LATE, interleaved with the Foundation layer and the
terminal seam. The modular orchestrator (``run_express`` / the Guided gates) has
since replaced that monolith sequence with the composed layer functions
(``apply_addons`` -> ``apply_foundation`` -> ``apply_iptv``), so weather/RSS now
run as part of ``apply_foundation`` — the layer they conceptually belong to,
not the layer that happened to run last in the old monolith.

NO deps-injection seam (Tech-debt ledger, Phase 2b). The moved bodies resolve their
install primitives from THIS module's globals (``extract_zip`` / ``install_with_deps``
/ ``install_selection`` / ``update_local_addons`` / ``enable`` / ``_latest_zip_url``).
A ``run()``-driven test that wants to stub those for the base/video path patches
them on THIS module (``addons.*``), not via an injected ``deps`` object — the few
legacy ``boot.mod.*`` patches were repointed here. (The Foundation layer's
``_BootSkinDeps`` seam stays transitional and is killed at the Phase-4 orchestrator.)
"""

import xbmc

from tony7bones import (
    extract_zip,
    install_selection,
    install_with_deps,
    is_installed,
    update_local_addons,
)
from tony7bones import enable as _enable

from .result import LayerResult

MY_ID = "script.tony7bones.bootstrap"

# --------------------------------------------------------------------------- #
# Index bases + add-on ids (lifted verbatim from default.py).
# --------------------------------------------------------------------------- #
STATIC_BASE = "https://tony7bones.github.io/addons"
REPO_BASE = "https://tony7bones.github.io/repositories/"
OFFICIAL_BASE = "https://mirrors.kodi.tv/addons/omega"
PENO64_BASE = (
    "https://raw.githubusercontent.com/peno64/repository.peno64/master/repo/zips"
)

# Repo installer zips: (zip filename, addon id).
REPO_ZIPS = [
    ("repository.709-1.0.2.zip", "repository.709"),
    ("repository.bugatsinho-2.8.zip", "repository.bugatsinho"),
    ("repository.cocoscrapers-1.0.1.zip", "repository.cocoscrapers"),
    ("repository.diggz.zip", "repository.diggz"),
    ("repository.ivarbrandt-1.0.3.zip", "repository.ivarbrandt"),
    ("repository.kodifitzwell-0.0.1.zip", "repository.kodifitzwell"),
    ("repository.kodinerds-7.0.1.7.zip", "repository.kodinerds"),
    ("repository.loop-3.0.4.zip", "repository.loop"),
    ("repository.Magnetic-1.1.0b.zip", "repository.Magnetic"),
    ("repository.peno64-1.5.zip", "repository.peno64"),
    ("repository.redwizard-1.2.2.zip", "repository.redwizard"),
    ("repository.umbrella-2.2.6.zip", "repository.umbrella"),
]

# First-party add-on ids installed by the generic direct-extract loop. Empty:
# the MOD V2 skin + the MOD V2+ patch add-on are installed by the Foundation layer
# (which handles their proxy-invisible deps + activation), not this loop.
FIRST_PARTY = []

# Our OWN virtual proxy repository — first-party plumbing, NOT third-party content.
# repository.tony7bones is the lifeline: it runs the local 127.0.0.1:61234 proxy that
# streams add-on metadata + zips from GitHub, drives self-update of the proxy, and
# is how the box receives any future opt-in. It is NOT one of the 12 third-party
# REPO_ZIPS (those are stand-alone source repos). install_repos direct-extracts the
# installer zip (resolved live from the served addon.xml, same mechanism modv2plus
# uses) + registers + enables it, so a Foundation box has our repo established as an
# installed, enabled add-on (not merely the .tony.7.bones File-Manager source).
PROXY_REPO_ID = "repository.tony7bones"

# Apps installed (with dependency closure) by direct extract, in order.
#   * script.realdebrid — peno64 (python).
#
# NOTE (Decision C, docs/plans/automate-share-and-backup-config.md): peno64's
# PLAIN backup fork ``script.ezmaintenanceplus`` is NO LONGER in this base list.
# The Setup was installing the WRONG backup tool — real boxes actually run this
# repo's OWN `++` fork (``script.ezmaintenanceplusplus``), which has the NFS/SMB
# retry hardening this plain fork lacks. The `++` fork is installed + configured
# by the Backup layer (``tony7bones.setup.backup``) instead, which runs
# immediately after Foundation. In a FULL Express run the NET installed set
# CHANGES here (deliberately): the plain fork is no longer installed at all —
# only the correct `++` fork is.
#
# NOTE (Phase 3a — the first deliberate behaviour change): ``pvr.iptvsimple`` is
# NO LONGER in this base list. Its INSTALL moved into the IPTV layer
# (``apply_iptv`` in ``tony7bones.setup.iptv``), so Layer 0/2 is genuinely
# content-free of the PVR backend and the IPTV gate installs-or-fails-loud its own
# backend (never silently configuring a missing add-on). In a FULL Express run the
# NET installed set is UNCHANGED — pvr.iptvsimple (+ its inputstream binary
# closure) is still installed, just via ``apply_iptv`` instead of this base loop.
#
# NOTE (weather-into-Foundation): ``weather.multi`` is ALSO no longer in this base
# list. Multi Weather is part of the BRANDED LOOK (the MOD V2 skin renders a weather
# readout + a Weather home-menu item), so its INSTALL + CONFIG moved into the
# Foundation layer (``apply_foundation`` in ``tony7bones.setup.foundation``). In a
# FULL Express run the NET installed set is UNCHANGED — weather.multi (+ its python
# module closure) is still installed, just via ``apply_foundation`` now.
ADDONS = [
    "script.realdebrid",
]

# Curated video add-ons — installed unattended (no picker) in the one-tap run.
VIDEO_APPS = [
    "plugin.video.pov",
    "plugin.video.the-loop",
    "plugin.video.sporthdme",
    "plugin.video.youtube",
]
# Install-then-disable: The Loop declares plugin.video.dailymotion_com as a
# REQUIRED import nobody here uses. Installing it satisfies the dep check;
# disabling it afterwards means it never runs and survives Loop updates with no
# re-patching.
VIDEO_DISABLE_AFTER = {"plugin.video.dailymotion_com"}

# NOTE (weather + RSS -> Foundation): both the weather provider core setting
# (weather.addon) and the RSS-enable core setting (lookandfeel.enablerssfeeds) +
# its env-driven writer moved to the Foundation layer — both are part of the
# branded look, not content. See ``tony7bones.setup.foundation`` (RSS_ENABLE_SETTING
# / _apply_rss_from_env / _apply_rss).


def _log(msg, level=xbmc.LOGINFO):
    xbmc.log(f"[{MY_ID}] {msg}", level)


def _latest_zip_url(addon_id):
    """Resolve a first-party add-on's current zip URL from its static addon.xml."""
    import re
    import urllib.request

    base = f"{STATIC_BASE}/{addon_id}"
    try:
        with urllib.request.urlopen(f"{base}/addon.xml", timeout=15) as r:
            xml = r.read().decode("utf-8", "replace")
        m = re.search(r'<addon\b[^>]*\bversion="([^"]+)"', xml)
        if m:
            return f"{base}/{addon_id}-{m.group(1)}.zip"
    except Exception as e:  # noqa: BLE001
        _log(f"cannot resolve {addon_id}: {e}", xbmc.LOGERROR)
    return None


# --------------------------------------------------------------------------- #
# Repos install (extract + register + enable all REPO_ZIPS + first-party).
# --------------------------------------------------------------------------- #
def install_repos(dialog, *, total=None, step=0):
    """Extract + register + enable the source repos (REPO_ZIPS) and FIRST_PARTY.

    The repos are the SOURCES/plumbing the rest of setup resolves its add-on
    closures from — NOT content. This is the reusable repo-install loop EXTRACTED
    VERBATIM out of ``_install_base`` (Phase 5a) so the **Foundation layer** can
    establish all our repos independently (the Estuary MOD V2 skin closure resolves
    the skin + skinshortcuts + image.resource.select from the installed source
    repos, so they must exist before the skin install).

    Establishes ALL our repositories: the 12 ``REPO_ZIPS`` by direct extract +
    register + enable, PLUS our OWN virtual proxy repo ``repository.tony7bones``
    (``PROXY_REPO_ID``) — first-party plumbing, the lifeline (updates / the proxy /
    future opt-ins). The proxy installer zip is direct-extracted (resolved live from
    the served addon.xml, the same ``_latest_zip_url`` mechanism the modv2plus patch
    uses) so the box ends up with our repo as an INSTALLED, ENABLED add-on — not
    merely the ``.tony.7.bones`` File-Manager SOURCE ``apply_foundation``'s
    ``_add_file_sources`` also registers. The proxy install is idempotent
    (``is_installed`` short-circuits) and non-fatal (a resolve/extract failure leaves
    the box working — the source entry still lets the user reinstall).

    Returns ``(repo_ok, fp_ok, step, canceled)`` — how many repos / first-party
    add-ons extracted, the running progress ``step`` so the caller
    (``_install_base``) can continue the shared progress bar into the apps stage, and
    whether the user cancelled the progress dialog DURING the repo/first-party loop
    (the exact per-iteration cancel checks the monolith had, preserved verbatim).
    Behaviour-preserving: ``_install_base`` calls this then installs the base apps,
    with the SAME total, step accounting, dialog updates, AND cancel semantics the
    monolith had. Idempotent — ``extract_zip`` / ``enable`` short-circuit an
    already-present add-on.

    Resolves its install primitives (extract_zip / _latest_zip_url /
    update_local_addons / enable) from THIS module's globals, so a test that stubs
    the repo path patches them here (addons.*) — no injected deps seam.

    Parameters
    ----------
    dialog
        The shared progress dialog (forwarded to ``extract_zip`` + ``dialog.update``).
    total
        The denominator for the progress percentage. Defaults to the full base total
        (``REPO_ZIPS`` + ``FIRST_PARTY`` + ``ADDONS`` + 1) so a ``_install_base`` call
        produces byte-identical progress percentages to the monolith. A
        Foundation-only caller passes the repo-only total.
    step
        The starting progress step (0 for a fresh bar).

    Returns
    -------
    (repo_ok, fp_ok, step, canceled)
        ``repo_ok`` / ``fp_ok`` extracted counts; ``step`` the running step AFTER the
        register-and-enable step (only meaningful when not cancelled); ``canceled``
        True if the user cancelled mid-loop (the caller aborts).
    """
    if total is None:
        total = len(REPO_ZIPS) + len(FIRST_PARTY) + len(ADDONS) + 1
    repo_ok = fp_ok = 0

    # 1. repos by direct extract
    for zip_name, _rid in REPO_ZIPS:
        step += 1
        if extract_zip(REPO_BASE + zip_name, dialog, int(step / total * 100), _log):
            repo_ok += 1
        if dialog.iscanceled():
            return repo_ok, fp_ok, step, True

    # 2. first-party add-ons by direct extract
    for addon_id in FIRST_PARTY:
        step += 1
        url = _latest_zip_url(addon_id)
        if url and extract_zip(url, dialog, int(step / total * 100), _log):
            fp_ok += 1
        if dialog.iscanceled():
            return repo_ok, fp_ok, step, True

    # 2b. our OWN virtual proxy repo (repository.tony7bones) — first-party plumbing,
    # the lifeline (updates / the proxy / future opt-ins). Direct-extract the
    # installer zip resolved LIVE from the served addon.xml (the same _latest_zip_url
    # mechanism the modv2plus patch uses), so the box ends up with our repo as an
    # installed, enabled add-on. Counted into fp_ok so the progress accounting and the
    # caller's first-party tally stay coherent; enabled in step 3 below. Defensive: a
    # resolve/extract failure is non-fatal (the .tony.7.bones File-Manager source
    # apply_foundation adds still lets the user reinstall).
    if not is_installed(PROXY_REPO_ID):
        proxy_url = _latest_zip_url(PROXY_REPO_ID)
        if proxy_url and extract_zip(proxy_url, dialog, int(step / total * 100), _log):
            fp_ok += 1
            _log(f"install_repos: extracted our proxy repo {PROXY_REPO_ID}")
    if dialog.iscanceled():
        return repo_ok, fp_ok, step, True

    # 3. register + enable the repos and first-party add-ons (incl. the proxy repo).
    step += 1
    dialog.update(int(step / total * 100), "Registering add-ons...")
    update_local_addons()
    xbmc.sleep(3000)
    for _zip_name, rid in REPO_ZIPS:
        if rid:
            _enable(rid)
    for addon_id in FIRST_PARTY:
        _enable(addon_id)
    _enable(PROXY_REPO_ID)

    return repo_ok, fp_ok, step, False


# --------------------------------------------------------------------------- #
# Base install (repos + first-party + apps).
# --------------------------------------------------------------------------- #
def _install_base(dialog):
    """Run the base install: repos + first-party + apps. Returns (repo_ok, fp_ok,
    app_ok, canceled). Shares the progress dialog with the (optional) video stage
    so the user sees one continuous progress bar. `canceled` is True if the user
    cancelled the progress dialog mid-install (run() then aborts with no summary,
    exactly today's behaviour).

    The repo-install loop (extract + register + enable REPO_ZIPS + FIRST_PARTY, with
    its per-iteration cancel checks) is EXTRACTED VERBATIM into the reusable
    ``install_repos`` (Phase 5a) so the Foundation layer can establish all our repos
    independently; ``_install_base`` is now ``install_repos()`` + the base-apps
    install with the SAME total/step accounting AND cancel semantics, so the net
    effect (and the characterization snapshot) is unchanged.

    Resolves its install primitives (extract_zip / _latest_zip_url /
    update_local_addons / enable / install_with_deps) from THIS module's globals,
    so a test that stubs the base path patches them here (addons.*) — no injected
    deps seam (Tech-debt ledger)."""
    total = len(REPO_ZIPS) + len(FIRST_PARTY) + len(ADDONS) + 1
    app_ok = 0

    # 1-3. repos + first-party: extract (with cancel checks), register, enable.
    repo_ok, fp_ok, step, canceled = install_repos(dialog, total=total, step=0)
    if canceled:
        return repo_ok, fp_ok, app_ok, True

    # 4. install each app with its dependency closure by direct extract.
    for addon_id in ADDONS:
        step += 1
        dialog.update(int(step / total * 100), f"Installing {addon_id}")
        if install_with_deps(addon_id, dialog, [PENO64_BASE], OFFICIAL_BASE, _log):
            app_ok += 1
        if dialog.iscanceled():
            return repo_ok, fp_ok, app_ok, True

    return repo_ok, fp_ok, app_ok, False


# --------------------------------------------------------------------------- #
# Curated video add-ons — installed unattended (no picker).
# --------------------------------------------------------------------------- #
def _install_video(dialog):
    """Install the curated video add-ons + their closure, unattended.

    Delegates to the shared library's install_selection (folded in from the
    retired standalone Video Add-ons Setup): enable the source repos, build the
    combined index from the installed repos + the official repo, resolve the
    closure for VIDEO_APPS, extract/enable/origin-stamp it, and apply the
    install-then-disable set. Shares this run's progress dialog. Returns how many
    of VIDEO_APPS ended up installed. Never raises — a video failure must not
    abort the box.

    Resolves install_selection from THIS module's globals, so a run()-driven test
    that stubs the video path patches addons.install_selection (the repointed
    boot.mod patch) — no injected deps seam."""
    try:
        return install_selection(
            VIDEO_APPS, OFFICIAL_BASE, VIDEO_DISABLE_AFTER, dialog, _log
        )
    except Exception as e:  # noqa: BLE001 - video failure must not abort the run
        _log(f"video install failed (non-fatal): {e}", xbmc.LOGERROR)
        return 0


# --------------------------------------------------------------------------- #
# Weather + RSS — MOVED to the Foundation layer (tony7bones.setup.foundation).
# --------------------------------------------------------------------------- #
# Multi Weather (weather.multi) and the RSS news ticker are both part of the
# BRANDED LOOK, not content (the MOD V2 skin renders a weather readout + a
# Weather home-menu item, and the ticker is a skin-level toggle) — their
# INSTALL + CONFIG (WEATHER_ADDON / WEATHER_LOCATION / RSS_ENABLE_SETTING /
# _apply_weather_from_env / _apply_rss_from_env + the core provider settings)
# moved to ``tony7bones.setup.foundation``. The Add-ons layer installs content
# only: base repos/apps + the curated video add-ons.


# --------------------------------------------------------------------------- #
# The Add-ons layer entry point (composed install).
# --------------------------------------------------------------------------- #
def apply_addons(env, *, dialog=None, log=None):
    """Apply Layer 2 (Add-ons): the base source repos + base apps and the
    curated video add-ons (incl. the install-then-disable of
    plugin.video.dailymotion_com) — returning a LayerResult.

    Behaviour-preserving COMPOSITION of the monolith's ``_install_base`` /
    ``_install_video``. Weather + RSS config (formerly composed here too) moved
    to ``apply_foundation`` — this layer is install-only content now.

    Parameters
    ----------
    env
        The already-parsed per-device env dict (passed in by the orchestrator
        for a uniform per-layer contract; this layer does not read it today).
        ``None`` is treated as the empty env.
    dialog
        The shared progress dialog (or ``None``); forwarded to the base + video
        install so the user sees one continuous progress bar.
    log
        The logging callable; reserved for future per-layer logging — the lifted
        bodies keep using this module's ``_log`` so their log lines stay identical
        to the monolith.

    Returns
    -------
    LayerResult
        ``layer="addons"``. ``ok`` is True unless the user cancelled the base
        install mid-run. ``installed`` records the base apps + repos + video apps
        that landed and ``failed`` records the apps that did not (so the
        orchestrator can decide before restarting). ``disabled`` add-ons (the
        install-then-disable set) are recorded in ``installed`` with state
        "disabled". ``already_done`` reflects a true no-op re-entry (nothing
        installed, nothing newly-failed) — NOT cargo-culted always-False.
        ``needs_restart=True`` is a REQUEST the orchestrator owns.
    """
    env = env or {}

    # --- install (base repos + apps, then curated video) ---
    repo_ok, _fp_ok, app_ok, canceled = _install_base(dialog)
    installed = {}
    failed = {}
    for i, (_zip_name, rid) in enumerate(REPO_ZIPS):
        # repo_ok counts the leading successes (extract loop is ordered); record
        # the ones that landed as installed, the rest as failed.
        (installed if i < repo_ok else failed)[rid] = (
            "installed" if i < repo_ok else "extract failed"
        )
    for i, aid in enumerate(ADDONS):
        (installed if i < app_ok else failed)[aid] = (
            "installed" if i < app_ok else "install failed"
        )

    video_ok = 0
    if not canceled:
        video_ok = _install_video(dialog)
        # install_selection installs VIDEO_APPS' closure + the disable-after set.
        for i, aid in enumerate(VIDEO_APPS):
            (installed if i < video_ok else failed)[aid] = (
                "installed" if i < video_ok else "video install failed"
            )
        # The install-then-disable set is a side effect of the video install
        # (The Loop pulls dailymotion); only stamp it when video actually
        # installed something, so a true no-op (no video apps installed) does not
        # spuriously report a "disabled" install and flip already_done.
        if video_ok:
            for aid in VIDEO_DISABLE_AFTER:
                installed[aid] = "disabled"

    # A cancelled base install is the only not-ok path (it aborts with no summary
    # in the monolith). NOTE: already_done here means "no work was INSTALLED"
    # (empty install lists) — NOT "the box is already provisioned". The install
    # primitives don't distinguish already-present from freshly-installed, so on a
    # real re-entry against a set-up box `installed` is full and already_done is
    # False. True re-entry detection is the orchestrator's installed-state probes
    # (Phase 4), not this field — don't build idempotence on it.
    ok = not canceled
    already_done = ok and not installed and not failed
    detail = (
        "cancelled mid-install"
        if canceled
        else "repos=%d apps=%d video=%d" % (repo_ok, app_ok, video_ok)
    )
    return LayerResult(
        layer="addons",
        ok=ok,
        already_done=already_done,
        installed=installed,
        failed=failed,
        needs_restart=not canceled,
        detail=detail,
    )
