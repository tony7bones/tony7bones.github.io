"""apply_iptv — Layer 1 (IPTV) of the modular setup (in-Kodi CONFIG half).

The IPTV layer's in-Kodi job is two things, both LIFTED VERBATIM out of
``script.tony7bones.bootstrap/default.py`` (Phase 2d), behaviour-identical:

  * ``_copy_device_files`` / ``_copy_one_device_file`` (driven by
    ``DEVICE_FILE_COPIES``) — copy the user-placed device files
    (RssFeeds.xml + pvr.iptvsimple's instance-settings + customTVGroups) from the
    Fire-Stick ``/storage/emulated/0/kodi/tony.7.bones/...`` tree into userdata.
    Guarded: a missing source (e.g. on desktop) is logged and skipped, never an
    error. (The RSS file is technically the Add-ons layer's data, but the copy
    loop is one data-driven step that runs as a unit, so it moves WHOLE here.)
  * ``_ensure_iptv_custom_tv_groups`` (+ its helper ``_set_instance_setting`` and
    the IPTV instance-settings constants) — enforce pvr.iptvsimple's per-instance
    settings (``tvGroupMode=2`` custom + ``customTvGroupsFile`` + the m3u/epg
    playlist source + groups-only) by writing ``instance-settings-1.xml``
    DIRECTLY. These keys cannot be set via JSON-RPC (``Settings.SetSettingValue``
    reaches only CORE settings, not add-on instance settings), so a direct file
    write is the only mechanism.

``default.py`` keeps thin re-export shims that delegate here so every existing
reference and test (``boot.mod._ensure_iptv_custom_tv_groups`` /
``_copy_device_files`` / ``DEVICE_FILE_COPIES`` + the IPTV_* constants) keeps
working unchanged.

THE INTERLEAVING CONSTRAINT (read before touching ``run()``). In the monolith
``_configure_box`` the order is: weather (Add-ons, 2c) -> device-file COPY ->
IPTV instance-settings ENFORCE -> RSS (Add-ons, 2c). ``run()``/``_configure_box``
MUST keep calling these bodies (via the ``default.py`` shims) in those EXACT slots
so the characterization snapshot stays byte-identical: the copy runs BEFORE the
enforce (so the enforce patches the copied file rather than being overwritten by
it). The composed ``apply_iptv`` below runs copy+enforce together and is provided
for the Phase-4 orchestrator; it is NOT called from ``run()`` yet.

NO deps-injection seam (Tech-debt ledger, Phase 2b). These bodies touch only
``xbmc`` / ``xbmcvfs`` / ``os`` / ``ElementTree`` — NO monkeypatched install
primitives — so a plain re-export is behaviour-identical and the few IPTV/copy
unit tests that reach them via ``boot.mod.*`` keep working with no repointing.
"""

import os
from xml.etree import ElementTree as ET

import xbmc
import xbmcvfs

from tony7bones import install_with_deps, is_installed

from .env import split_list
from .result import LayerResult

MY_ID = "script.tony7bones.bootstrap"

# --------------------------------------------------------------------------- #
# The IPTV layer's own PVR backend (Phase 3a — moved out of the base ADDONS).
# --------------------------------------------------------------------------- #
# pvr.iptvsimple is the PVR backend the IPTV gate configures. As of Phase 3a its
# INSTALL belongs to THIS layer (it was previously in the base ``ADDONS`` list),
# so the IPTV gate owns its own backend: ``apply_iptv`` installs it (+ its binary
# inputstream closure) BEFORE configuring instance-settings, and FAILS LOUD if the
# install does not land — it never silently writes instance-settings for a missing
# pvr.iptvsimple. It is a BINARY add-on, so its closure resolves per-platform from
# the official repo (``install_with_deps`` loads the platform-tagged index); the
# base config-only bodies (copy/enforce) below are unchanged.
PVR_BACKEND_ID = "pvr.iptvsimple"
OFFICIAL_BASE = "https://mirrors.kodi.tv/addons/omega"


def _log(msg, level=xbmc.LOGINFO):
    xbmc.log(f"[{MY_ID}] {msg}", level)


def _install_pvr_backend(dialog):
    """Install pvr.iptvsimple (+ its binary inputstream closure), or fail loud.

    The IPTV gate owns its own PVR backend (Phase 3a): resolve + direct-extract
    pvr.iptvsimple's full closure from the official repo (platform-aware — it is a
    BINARY add-on, so ``install_with_deps`` loads the platform-tagged official
    index and picks the matching native build). Returns True once it reports
    installed. A no-op short-circuit when it is already installed (re-entry).

    Resolves its install primitives (``install_with_deps`` / ``is_installed``) from
    THIS module's globals, so a test that stubs the install path patches them here
    (``iptv.*``) — no injected deps seam (Tech-debt ledger)."""
    if is_installed(PVR_BACKEND_ID):
        return True
    return bool(install_with_deps(PVR_BACKEND_ID, dialog, [], OFFICIAL_BASE, _log))


# Device → userdata file copies. The user places these files on the device under
# the Android/Fire-Stick /storage/emulated/0/kodi/ tree (note the exact
# "tony.7.bones" spelling); Setup copies each one into Kodi's userdata over any
# default. Every file is USER-PROVIDED — Setup never downloads or creates them; it
# only copies each when present, overwriting the destination. They carry the
# user's private config and land in userdata/addon_data ONLY, never the repo.
#
# Each entry is (source-on-device, destination special:// path):
#   * the home-screen RSS news ticker feeds (over Kodi's default RssFeeds.xml)
#   * pvr.iptvsimple's instance settings (the IPTV add-on is already installed by
#     the base step, so addon_data/pvr.iptvsimple/ may need creating)
#   * pvr.iptvsimple's custom TV channel groups (the channelGroups/ subdir won't
#     exist on a fresh box — the copy creates it)
DEVICE_FILE_COPIES = [
    (
        "/storage/emulated/0/kodi/tony.7.bones/rss/RssFeeds.xml",
        "special://home/userdata/RssFeeds.xml",
    ),
    (
        "/storage/emulated/0/kodi/tony.7.bones/iptv/instance-settings-1.xml",
        "special://home/userdata/addon_data/pvr.iptvsimple/instance-settings-1.xml",
    ),
    (
        "/storage/emulated/0/kodi/tony.7.bones/iptv/customTVGroups-Network24.xml",
        "special://home/userdata/addon_data/pvr.iptvsimple/channelGroups/"
        "customTVGroups-Network24.xml",
    ),
]


def _copy_one_device_file(src, dst_special):
    """Copy a single USER-PROVIDED device file into userdata, guarded.

    FROM the device path `src`, TO the translated `dst_special` — creating the
    destination directory if missing (fresh boxes lack addon_data/pvr.iptvsimple/
    and its channelGroups/ subdir) and OVERWRITING the destination if it exists.
    GUARDED: if the source is absent (e.g. on desktop, or the user hasn't placed
    it) this logs and skips — it never errors. Idempotent."""
    if not xbmcvfs.exists(src):
        _log(
            f"_configure_box: device file not found, skipping: {src}",
            xbmc.LOGINFO,
        )
        return
    dst = xbmcvfs.translatePath(dst_special)
    # Create the destination directory tree if it doesn't exist yet.
    dst_dir = os.path.dirname(dst)
    if dst_dir and not xbmcvfs.exists(dst_dir):
        xbmcvfs.mkdirs(dst_dir)
    # xbmcvfs.copy overwrites an existing destination.
    if xbmcvfs.copy(src, dst):
        _log(f"_configure_box: copied device file {src} -> {dst}")
    else:
        _log(
            f"_configure_box: xbmcvfs.copy reported failure copying {src} -> {dst}",
            xbmc.LOGERROR,
        )


def _copy_device_files():
    """Copy each USER-PROVIDED device file in DEVICE_FILE_COPIES into userdata.

    Data-driven loop over (src, dst) pairs: the custom RSS feeds plus the
    pvr.iptvsimple instance settings and custom TV channel groups. Each copy
    creates its destination dir if missing, overwrites the destination if present,
    and is GUARDED — a missing source (or any per-file error) is logged and
    skipped, never aborting the rest of setup. Idempotent."""
    for src, dst_special in DEVICE_FILE_COPIES:
        try:
            _copy_one_device_file(src, dst_special)
        except Exception as e:  # noqa: BLE001 - one bad file must not abort the rest
            _log(
                f"_copy_device_files: copy {src} failed (non-fatal): {e}",
                xbmc.LOGERROR,
            )


# --------------------------------------------------------------------------- #
# pvr.iptvsimple instance-settings keys (1a/1b — TV custom groups)
# --------------------------------------------------------------------------- #
# pvr.iptvsimple stores its per-instance config in
#   addon_data/pvr.iptvsimple/instance-settings-1.xml
# (a <settings version="2"> file keyed by setting id). These two keys make the
# add-on serve the user's custom TV channel groups instead of "all channels":
#
#   * tvGroupMode = 2   -> "Custom groups" (schema enum: 0=ALL, 1=SOME, 2=CUSTOM,
#     confirmed in resources/instance-settings.xml, option label 30038)
#   * customTvGroupsFile -> the channelGroups/ file we copy from the device
#
# These are ADD-ON INSTANCE settings: Kodi's JSON-RPC Settings.SetSettingValue
# reaches only CORE settings (system.*, weather.*, …) and has no method for
# per-instance PVR add-on settings — so the only way to set them is to write the
# instance-settings file directly. We already COPY the user's file here; this
# step then ENFORCES the two keys on top of whatever was copied, so the box ends
# up correct even if the user's file omits or mis-sets them. If the copied file
# already has them, it's a no-op. The path uses the same special://userdata form
# the add-on itself writes (it resolves to the same channelGroups/ dir as the
# copy destination).
IPTV_INSTANCE_SETTINGS_SPECIAL = (
    "special://home/userdata/addon_data/pvr.iptvsimple/instance-settings-1.xml"
)
IPTV_TV_GROUP_MODE_KEY = "tvGroupMode"
IPTV_TV_GROUP_MODE_CUSTOM = "2"  # schema enum: 2 == CUSTOM_GROUPS
IPTV_CUSTOM_TV_GROUPS_FILE_KEY = "customTvGroupsFile"
IPTV_CUSTOM_TV_GROUPS_FILE_VALUE = (
    "special://userdata/addon_data/pvr.iptvsimple/channelGroups/"
    "customTVGroups-Network24.xml"
)
# "Only load TV channels in groups" — pvr.iptvsimple shows only channels that
# belong to a (custom) group, hiding the ungrouped firehose. Enforced true.
IPTV_TV_CHANNEL_GROUPS_ONLY_KEY = "tvChannelGroupsOnly"


def _set_instance_setting(root, setting_id, value):
    """Ensure <setting id="setting_id"> in `root` has exactly `value`.

    Updates the element in place if present (and drops the default="true" flag,
    since we're now overriding the default), creates it if missing. Returns True
    if anything changed, so the caller can skip a no-op write. Mirrors how Kodi's
    own settings writer stamps a user-set value."""
    el = None
    for s in root.findall("setting"):
        if s.get("id") == setting_id:
            el = s
            break
    changed = False
    if el is None:
        el = ET.SubElement(root, "setting")
        el.set("id", setting_id)
        changed = True
    # A user-set value is no longer the schema default.
    if el.get("default") is not None:
        el.attrib.pop("default", None)
        changed = True
    if (el.text or "") != value:
        el.text = value
        changed = True
    return changed


def _ensure_iptv_custom_tv_groups(box_env=None):
    """Enforce TV-group-mode=Custom + the custom-TV-groups file path in
    pvr.iptvsimple's instance-settings-1.xml (1a/1b).

    Runs AFTER _copy_device_files() (which may have copied the user's own
    instance-settings-1.xml). Reads the file if present, else starts a fresh
    <settings version="2"> tree, then ensures the two keys are correct and writes
    back only if something changed. The destination dir is created if absent (a
    fresh box without the copied file). Idempotent and fully defensive: any
    failure is logged and swallowed — never aborts the rest of setup. These keys
    cannot be set via JSON-RPC (it does not reach add-on instance settings), so a
    direct file write is the only mechanism.

    GATED: only enforces custom-group mode when the custom-groups file actually
    exists (copied from the device, or generated from the env's IPTV_GROUPS). On a
    no-env / no-file box, forcing tvGroupMode=2 at a MISSING file gives
    pvr.iptvsimple an empty channel list — so we leave the all-channels default.

    When `box_env` provides IPTV_GROUPS the groups file is GENERATED from it first
    (channel-group names only — not secret); IPTV_M3U/IPTV_EPG are injected as
    m3uUrl/epgUrl (+ remote path type); tvChannelGroupsOnly comes from
    IPTV_GROUPS_ONLY (default true). Secret values are never logged.

    Returns
    -------
    bool
        ``True`` if it actually WROTE/changed the instance-settings file this call
        (group mode and/or m3u/epg keys), ``False`` otherwise — i.e. on the gated
        no-op (no m3u/epg and no groups file), on an already-correct file (the
        ``if changed:`` write-skip), or on a swallowed failure. The aggregate is the
        OR of every ``_set_instance_setting`` change, so it is the truthful
        "did config land?" signal ``apply_iptv`` reports from. ``_configure_box``
        ignores it (the return is purely additive — file side effects are
        byte-identical to before).
    """
    box_env = box_env or {}
    try:
        groups_file = xbmcvfs.translatePath(IPTV_CUSTOM_TV_GROUPS_FILE_VALUE)
        groups = split_list(box_env.get("IPTV_GROUPS", ""))
        if groups:
            os.makedirs(os.path.dirname(groups_file), exist_ok=True)
            groot = ET.Element("customChannelGroups")
            for name in groups:
                ET.SubElement(groot, "channelGroupName").text = name
            with open(groups_file, "w", encoding="utf-8") as f:
                f.write(ET.tostring(groot, encoding="unicode"))
            _log(
                "_ensure_iptv_custom_tv_groups: generated %d custom group(s) from env"
                % len(groups)
            )
        # The playlist SOURCE (m3u/epg) and the group MODE are independent: inject
        # the source whenever the env supplies it, but only force CUSTOM group mode
        # when the groups file exists (crit A — never tvGroupMode=2 at a missing
        # file). With neither, there's nothing to do — leave the all-channels default.
        m3u = (box_env.get("IPTV_M3U") or "").strip()
        epg = (box_env.get("IPTV_EPG") or "").strip()
        have_groups = os.path.exists(groups_file)
        if not (m3u or epg or have_groups):
            _log(
                "_ensure_iptv_custom_tv_groups: nothing to set (no m3u/epg, no "
                f"groups file {groups_file}) — leaving the all-channels default"
            )
            return False
        xml_path = xbmcvfs.translatePath(IPTV_INSTANCE_SETTINGS_SPECIAL)
        os.makedirs(os.path.dirname(xml_path), exist_ok=True)

        root = None
        if os.path.exists(xml_path):
            try:
                root = ET.parse(xml_path).getroot()
            except ET.ParseError as e:
                _log(
                    f"_ensure_iptv_custom_tv_groups: instance-settings-1.xml "
                    f"malformed, recreating: {e}",
                    xbmc.LOGERROR,
                )
                root = None
        if root is None or root.tag != "settings":
            root = ET.Element("settings")
            root.set("version", "2")

        # Playlist source (provider creds — SECRET; never logged as values).
        changed = False
        if m3u:
            changed = _set_instance_setting(root, "m3uPathType", "1") or changed
            changed = _set_instance_setting(root, "m3uUrl", m3u) or changed
        if epg:
            changed = _set_instance_setting(root, "epgPathType", "1") or changed
            changed = _set_instance_setting(root, "epgUrl", epg) or changed
        # Custom group mode — ONLY when the groups file exists.
        only_val = "n/a"
        if have_groups:
            changed = (
                _set_instance_setting(
                    root, IPTV_TV_GROUP_MODE_KEY, IPTV_TV_GROUP_MODE_CUSTOM
                )
                or changed
            )
            changed = (
                _set_instance_setting(
                    root,
                    IPTV_CUSTOM_TV_GROUPS_FILE_KEY,
                    IPTV_CUSTOM_TV_GROUPS_FILE_VALUE,
                )
                or changed
            )
            only = (box_env.get("IPTV_GROUPS_ONLY", "true") or "true").strip().lower()
            only_val = "true" if only in ("true", "1", "yes", "on") else "false"
            changed = (
                _set_instance_setting(root, IPTV_TV_CHANNEL_GROUPS_ONLY_KEY, only_val)
                or changed
            )
        else:
            _log(
                "_ensure_iptv_custom_tv_groups: no groups file — m3u/epg set, group "
                "mode left at the all-channels default"
            )

        if changed:
            with open(xml_path, "w", encoding="utf-8") as f:
                f.write(ET.tostring(root, encoding="unicode"))
            _log(
                "_ensure_iptv_custom_tv_groups: groups=%s only=%s m3u=%s epg=%s in %s"
                % (have_groups, only_val, bool(m3u), bool(epg), xml_path)
            )
        else:
            _log("_ensure_iptv_custom_tv_groups: keys already correct (no change)")
        return changed
    except Exception as e:  # noqa: BLE001 - never abort the rest of setup
        _log(
            f"_ensure_iptv_custom_tv_groups failed (non-fatal): {e}",
            xbmc.LOGERROR,
        )
        return False


# --------------------------------------------------------------------------- #
# The IPTV layer entry point (composed device-copy + instance-settings enforce).
# --------------------------------------------------------------------------- #
def apply_iptv(env, *, dialog=None, log=None):
    """Apply Layer 1 (IPTV): install the PVR backend (pvr.iptvsimple + its binary
    inputstream closure) OR FAIL LOUD, then copy the user's device files into
    userdata, then enforce pvr.iptvsimple's instance-settings (custom group mode +
    custom-groups file + the env's m3u/epg playlist source + groups-only) —
    returning a LayerResult.

    Phase 3a — the FIRST deliberate behaviour change. The IPTV gate now OWNS its
    own PVR backend: ``pvr.iptvsimple``'s INSTALL moved OUT of the base ``ADDONS``
    list (``tony7bones.setup.addons``) and INTO this layer. So ``apply_iptv``:

      1. installs pvr.iptvsimple (+ its binary inputstream closure) via
         ``_install_pvr_backend`` — install-or-fail-loud. If the backend does NOT
         install, the layer returns ``ok=False`` with ``failed[pvr.iptvsimple]`` and
         WRITES NO instance-settings (never silently configure a missing add-on).
      2. copies the user's device files into userdata (guarded; skips missing).
      3. enforces the instance-settings (gated on the groups file).

    In a FULL Express run the NET installed set is UNCHANGED vs the old monolith:
    pvr.iptvsimple (+ inputstream.*) is still installed — just via THIS layer
    instead of the base loop. The copy-then-enforce body is the verbatim
    ``_configure_box`` IPTV order (copy BEFORE enforce, so the enforce patches the
    copied file rather than being overwritten by it).

    Parameters
    ----------
    env
        The already-parsed per-device env dict (passed in by the orchestrator). The
        instance-settings enforce reads IPTV_GROUPS / IPTV_M3U / IPTV_EPG /
        IPTV_GROUPS_ONLY from it; secret values (m3u/epg creds) are never logged.
        ``None`` is treated as the empty env — on a no-env box the device-copy is a
        guarded no-op and the enforce leaves the all-channels default (writes
        nothing), so apart from the backend install ``apply_iptv`` is a clean no-op.
    dialog
        The shared progress dialog (or ``None``); forwarded to the PVR backend
        install so the user sees one continuous progress bar. The copy/enforce do no
        progress reporting (fast file ops).
    log
        The logging callable; reserved for future per-layer logging — the lifted
        bodies keep using this module's ``_log`` so their log lines stay identical
        to the monolith.

    Returns
    -------
    LayerResult
        ``layer="iptv"``. ``ok`` is True only when the PVR backend installed; a
        backend-install failure is the ONE hard-failure path (``ok=False``,
        ``failed[pvr.iptvsimple]="install failed"``, no instance-settings written) —
        the orchestrator checks ``ok`` BEFORE restarting. The copy + enforce halves
        stay fully defensive (every failure is logged and swallowed); a missing
        source / missing groups file is the no-op contract, not an error.
        ``installed`` records ``"pvr.iptvsimple": "installed"`` once the backend
        landed, upgraded to ``"configured"`` when the enforce actually WROTE the
        instance-settings file (group mode and/or m3u/epg). The "did config land?"
        signal is the enforce's OWN return (the OR of every ``_set_instance_setting``
        change), NOT whether the file pre-existed — so on a normally-provisioned box,
        where the device-copy stages instance-settings-1.xml BEFORE the enforce, a
        real enforce write is reported truthfully (the old ``existed_before`` probe
        lied here). ``already_done`` means "no NEW work this run": the backend was
        already installed AND no config was written (the gated no-op OR an
        already-correct file the enforce left byte-identical). It is honest for "did
        this layer do new work?" but is NOT a deep re-provision probe; don't build
        idempotence on it. ``needs_restart=True`` is a REQUEST the orchestrator owns
        (pvr.iptvsimple re-reads instance settings on restart).
    """
    env = env or {}

    # --- install the PVR backend FIRST — install-or-fail-loud (Phase 3a) ---
    # The IPTV gate owns its own backend now; if pvr.iptvsimple does not install,
    # the layer fails (ok=False) and writes NO instance-settings — never silently
    # configure a missing add-on. A re-entry where it is already installed is a
    # no-op short-circuit (already_installed below stays True for already_done math).
    already_installed = is_installed(PVR_BACKEND_ID)
    pvr_ok = _install_pvr_backend(dialog)
    if not pvr_ok:
        _log(
            "apply_iptv: pvr.iptvsimple did NOT install — refusing to configure a "
            "missing PVR backend (no instance-settings written)",
            xbmc.LOGERROR,
        )
        return LayerResult(
            layer="iptv",
            ok=False,
            already_done=False,
            installed={},
            failed={PVR_BACKEND_ID: "install failed"},
            needs_restart=False,
            detail="pvr.iptvsimple install failed — IPTV not configured",
        )

    # --- copy the user's device files into userdata (guarded; skips missing) ---
    _copy_device_files()

    # --- enforce pvr.iptvsimple instance-settings (gated on the groups file) ---
    # Take the enforce's OWN return signal for "did config land?". The enforce
    # aggregates every _set_instance_setting change and returns True only when it
    # actually WROTE the instance-settings file this call (group mode and/or m3u/epg
    # keys). This is the truthful signal: the old `existed_before` probe lied on a
    # normally-provisioned box, where the device-copy stages instance-settings-1.xml
    # BEFORE this enforce — so the file ALWAYS pre-exists, yet the enforce still
    # writes real config. The return value can't be fooled by that staging.
    wrote_instance = _ensure_iptv_custom_tv_groups(env)

    # The backend installed (pvr_ok is True here); record it, then UPGRADE the state
    # to "configured" if the enforce actually wrote instance-settings this run.
    installed = {PVR_BACKEND_ID: "configured" if wrote_instance else "installed"}

    # already_done = no NEW work this run: the backend was already installed AND no
    # config was written (the gated no-op — no m3u/epg and no groups file — or an
    # already-correct instance-settings file the enforce's `if changed:` write-skip
    # left byte-identical). A fresh backend install is real work, so it is never
    # already_done. This is "did this layer do new work?" semantics; it is NOT the
    # orchestrator's deeper re-entry probe — don't build idempotence on it.
    already_done = already_installed and not wrote_instance
    if wrote_instance:
        detail = "pvr.iptvsimple installed; instance-settings written"
    else:
        detail = (
            "pvr.iptvsimple installed; no config written "
            "(no m3u/epg+no groups file, or already correct)"
        )
    return LayerResult(
        layer="iptv",
        ok=True,
        already_done=already_done,
        installed=installed,
        failed={},
        needs_restart=True,
        detail=detail,
    )
