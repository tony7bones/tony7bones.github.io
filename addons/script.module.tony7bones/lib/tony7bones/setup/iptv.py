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
import re
from xml.etree import ElementTree as ET

import xbmc
import xbmcvfs

from tony7bones import disable, enable, install_with_deps, is_installed

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

# --------------------------------------------------------------------------- #
# Multi-provider env (Phase 5b·1) — IPTV_<N>_* -> instance-settings-<N>.xml.
# --------------------------------------------------------------------------- #
# The real per-device .env uses a multi-provider shape — one numbered block per
# provider (IPTV_1_NAME/MODE/M3U/EPG/GROUPS/GROUPS_ONLY, IPTV_2_...). Each m3u-mode
# provider becomes ONE pvr.iptvsimple INSTANCE: Kodi's multi-instance add-on
# support enumerates addon_data/pvr.iptvsimple/instance-settings-<N>.xml files, so
# provider N is written to instance-settings-<N>.xml plus its own
# channelGroups/customTVGroups-<Name>.xml. Two instance-identity keys make a
# CREATED instance file real to Kodi (and label it in the PVR client list):
IPTV_INSTANCE_NAME_KEY = "kodi_addon_instance_name"
IPTV_INSTANCE_ENABLED_KEY = "kodi_addon_instance_enabled"
IPTV_CHANNEL_GROUPS_DIR_SPECIAL = (
    "special://userdata/addon_data/pvr.iptvsimple/channelGroups/"
)
# A numbered provider key: IPTV_<N>_<FIELD> (N is the 1-based provider index that
# doubles as the pvr.iptvsimple instance id).
_IPTV_NUMBERED_KEY = re.compile(r"^IPTV_(\d+)_([A-Z0-9_]+)$")

# --------------------------------------------------------------------------- #
# HOST-BUILT staged artifacts (Phase 5b·2 — the "IPTV is two halves" decision).
# --------------------------------------------------------------------------- #
# The host half (_tools/build_iptv.py, run by the provisioner) builds the
# CURATED per-provider artifacts — the local playlist (with the full groups
# grammar applied: display relabel, | sort, the favorites group; and for an
# xtream-mode provider the playlist SYNTHESIZED from the Xtream player_api,
# the only way it can load since pvr.iptvsimple Omega has no Xtream mode and
# the provider's get.php m3u export is server-blocked), the customTVGroups
# display-label list, and a ready instance-settings-<N>.xml. The provisioner
# stages them on the box and points the per-device env at the dir via
# IPTV_STAGING_DIR. There is deliberately NO default staging dir: the key is
# present iff the host actually staged artifacts, so a legacy/un-provisioned
# box can never accidentally enter the staged path (zero behaviour change).
IPTV_STAGING_DIR_KEY = "IPTV_STAGING_DIR"


def _instance_settings_special(n):
    """special:// path of pvr.iptvsimple's instance-settings file for instance n.

    For n=1 this is exactly IPTV_INSTANCE_SETTINGS_SPECIAL (the legacy
    single-instance path), so provider 1 / the legacy shape land in the same file
    the monolith always wrote."""
    return (
        "special://home/userdata/addon_data/pvr.iptvsimple/instance-settings-%d.xml" % n
    )


def _groups_file_special(provider):
    """special:// path of the provider's custom-TV-groups file.

    LEGACY single-instance providers keep the historical constant
    (customTVGroups-Network24.xml) so existing envs, the DEVICE_FILE_COPIES
    device-copy convention, and every shipped box stay byte-compatible. Numbered
    providers derive customTVGroups-<Name>.xml from the provider NAME (non-alnum
    stripped: "Network 24" -> Network24 — deliberately identical to the legacy
    constant for provider 1 of the real env), falling back to Provider<N>."""
    if provider["legacy"]:
        return IPTV_CUSTOM_TV_GROUPS_FILE_VALUE
    token = re.sub(r"[^A-Za-z0-9]+", "", provider["name"]) or (
        "Provider%d" % provider["n"]
    )
    return IPTV_CHANNEL_GROUPS_DIR_SPECIAL + "customTVGroups-%s.xml" % token


def _group_source(item):
    """Extract the SOURCE group name from one IPTV_*_GROUPS grammar item.

    The groups grammar is ``SOURCE > Display Label | sort`` (display relabel and
    sort directive are HOST-side curation — build_iptv.py, Phase 5b step 2). The
    in-Kodi half needs the SOURCE side: pvr.iptvsimple matches a custom group's
    <channelGroupName> against the playlist's group-title values, which are the
    provider's ORIGINAL group names — pointing it at the display label would match
    nothing and load zero channels. A plain legacy item ("USA ENTERTAINMENT") has
    no '>'/'|' and passes through unchanged."""
    if ">" in item:
        item = item.split(">", 1)[0]
    else:
        item = item.split("|", 1)[0]
    return item.strip()


def _iptv_providers(box_env):
    """Parse the env into an ordered list of IPTV provider dicts.

    Numbered ``IPTV_<N>_*`` blocks win: one provider per N (sorted), with
    ``legacy=False`` and the env's N as the pvr.iptvsimple instance id. ``mode``
    is the explicit ``IPTV_<N>_MODE`` (lowercased), defaulting to ``xtream`` when
    the block has a PORTAL but no M3U, else ``m3u``.

    With NO numbered keys the legacy single-instance shape (``IPTV_M3U`` /
    ``IPTV_EPG`` / ``IPTV_GROUPS`` / ``IPTV_GROUPS_ONLY``) maps to ONE
    ``legacy=True`` provider 1 — ALWAYS returned, even on an empty env, because
    the legacy enforce must still run its gated no-op probe (a device-copied
    groups file with no env at all still gets custom group mode, exactly as the
    monolith behaved)."""
    numbered = {}
    for key, val in box_env.items():
        m = _IPTV_NUMBERED_KEY.match(key)
        if m:
            numbered.setdefault(int(m.group(1)), {})[m.group(2)] = val
    if numbered:
        providers = []
        for n in sorted(numbered):
            f = numbered[n]
            m3u = (f.get("M3U") or "").strip()
            portal = (f.get("PORTAL") or "").strip()
            mode = (f.get("MODE") or "").strip().lower()
            if not mode:
                mode = "xtream" if (portal and not m3u) else "m3u"
            providers.append(
                {
                    "n": n,
                    "legacy": False,
                    "name": (f.get("NAME") or "").strip(),
                    "mode": mode,
                    "m3u": m3u,
                    "epg": (f.get("EPG") or "").strip(),
                    "groups": f.get("GROUPS") or "",
                    "groups_only": f.get("GROUPS_ONLY", "true") or "true",
                }
            )
        return providers
    # Legacy single-instance shape (or an empty env): one provider-1, m3u mode,
    # writing the SAME paths the monolith always wrote (back-compat by
    # construction — the legacy provider never derives a NAME-based groups path
    # and never writes the instance-identity keys).
    return [
        {
            "n": 1,
            "legacy": True,
            "name": (box_env.get("IPTV_NAME") or "").strip(),
            "mode": "m3u",
            "m3u": (box_env.get("IPTV_M3U") or "").strip(),
            "epg": (box_env.get("IPTV_EPG") or "").strip(),
            "groups": box_env.get("IPTV_GROUPS") or "",
            "groups_only": box_env.get("IPTV_GROUPS_ONLY", "true") or "true",
        }
    ]


def _apply_staged_provider(provider, staging_dir):
    """Consume the HOST-BUILT staged artifacts for ONE provider (instance N).

    PARSE-BASED consumption (no filename-convention coupling): read the staged
    ``instance-settings-<N>.xml``, resolve every side-file it references — the
    local playlist when ``m3uPathType=0`` and the customTVGroups file when
    ``tvGroupMode=2`` — and require each to exist in the staging dir BEFORE
    anything is written (a partial staging must never poison the box with an
    instance pointing at missing files). Then copy the side-files to their
    translated ``special://`` destinations and write the instance file, with
    ``m3uPath`` REWRITTEN from the staged portable ``special://`` form to the
    translated ABSOLUTE path (the form proven to load in pvr.iptvsimple;
    ``customTvGroupsFile`` keeps its special:// form — live-proven on every
    shipped box).

    Returns True iff the staged config was FULLY applied (the caller then skips
    the direct-env enforce for this provider); False on no/partial/malformed
    staging or any copy failure — each logged, never raised — so the caller
    falls back to the Phase 5b·1 direct-env behaviour. Always applies when
    complete (the host artifacts are authoritative; re-copying identical bytes
    on re-entry is harmless inside the PVR-disabled window). Secret values
    (playlist/EPG URLs with creds) are never logged."""
    n = provider["n"]
    src = staging_dir.rstrip("/") + "/instance-settings-%d.xml" % n
    if not xbmcvfs.exists(src):
        return False
    try:
        root = ET.parse(src).getroot()
    except Exception as e:  # noqa: BLE001 - malformed staging must only fall back
        _log(
            "_apply_staged_provider: staged instance-settings-%d.xml unreadable "
            "(%s) — falling back to direct env config" % (n, e),
            xbmc.LOGERROR,
        )
        return False
    if root.tag != "settings":
        _log(
            "_apply_staged_provider: staged instance-settings-%d.xml is not a "
            "<settings> file — falling back to direct env config" % n,
            xbmc.LOGERROR,
        )
        return False
    vals = {s.get("id"): (s.text or "") for s in root.findall("setting")}
    # The side-files this instance references; each MUST be staged alongside.
    needed = []  # (staged-src, dest special://, kind)
    m3u_special = (vals.get("m3uPath") or "").strip()
    if vals.get("m3uPathType") == "0" and m3u_special:
        needed.append((m3u_special, "playlist"))
    groups_special = (vals.get("customTvGroupsFile") or "").strip()
    if vals.get("tvGroupMode") == IPTV_TV_GROUP_MODE_CUSTOM and groups_special:
        needed.append((groups_special, "groups"))
    staged = []
    for special, kind in needed:
        fname = special.rstrip("/").rsplit("/", 1)[-1]
        side_src = staging_dir.rstrip("/") + "/" + fname
        if not xbmcvfs.exists(side_src):
            _log(
                "_apply_staged_provider: instance %d: staged %s file %s is "
                "MISSING — falling back to direct env config" % (n, kind, fname),
                xbmc.LOGERROR,
            )
            return False
        staged.append((side_src, special, kind))
    # All present — copy the side-files into the profile, then the instance file.
    for side_src, special, kind in staged:
        dst = xbmcvfs.translatePath(special)
        dst_dir = os.path.dirname(dst)
        if dst_dir and not xbmcvfs.exists(dst_dir):
            xbmcvfs.mkdirs(dst_dir)
        if not xbmcvfs.copy(side_src, dst):
            _log(
                "_apply_staged_provider: instance %d: copying the staged %s "
                "file failed — falling back to direct env config" % (n, kind),
                xbmc.LOGERROR,
            )
            return False
        if kind == "playlist":
            # Rewrite the portable special:// form to the translated absolute
            # path — the m3uPath form the POC proved pvr.iptvsimple loads.
            for el in root.findall("setting"):
                if el.get("id") == "m3uPath":
                    el.text = dst
    xml_path = xbmcvfs.translatePath(_instance_settings_special(n))
    os.makedirs(os.path.dirname(xml_path), exist_ok=True)
    with open(xml_path, "w", encoding="utf-8") as f:
        f.write(ET.tostring(root, encoding="unicode"))
    _log(
        "_apply_staged_provider: instance %d: applied HOST-BUILT staged config "
        "(playlist=%s groups=%s)"
        % (
            n,
            any(k == "playlist" for *_x, k in staged),
            any(k == "groups" for *_x, k in staged),
        )
    )
    return True


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


def _ensure_iptv_instance(provider):
    """Enforce ONE provider's pvr.iptvsimple instance settings (instance N).

    The per-provider body of the enforce (the old single-instance logic,
    generalized): generate the provider's custom-TV-groups file from its GROUPS
    grammar (SOURCE names only — see ``_group_source``), then write/patch
    ``instance-settings-<N>.xml`` — the m3u/epg playlist source, and (gated on the
    groups file existing) custom group mode + the groups-file path + groups-only.
    For a NUMBERED provider it additionally enforces the instance-identity keys
    (``kodi_addon_instance_name``/``kodi_addon_instance_enabled``) so a CREATED
    instance file is real to Kodi's multi-instance scanner and labelled with the
    provider name; the LEGACY provider never writes them (byte-compat with the
    monolith's instance-settings-1.xml).

    XTREAM-mode providers are SKIPPED here with an honest log: pvr.iptvsimple on
    Omega (21.x) has NO native Xtream-Codes connection mode — the only XTREAM
    reference in its instance-settings schema is the ``allChannelsCatchupMode``
    CATCHUP enum, not a portal/user/pass source — and this provider's m3u export
    is server-blocked, so deriving a get.php URL would not work either. The
    host-side build (``_tools/build_iptv.py``) owns Xtream -> m3u derivation:
    its staged artifacts are consumed by ``_apply_staged_provider`` BEFORE this
    direct-env body runs, so this skip only fires when staging is absent.
    No credentials are logged.

    Returns True if it actually wrote/changed this instance's settings file."""
    n = provider["n"]
    if provider["mode"] == "xtream":
        _log(
            "_ensure_iptv_custom_tv_groups: provider %d is xtream-mode with NO "
            "staged host-built config — skipped in-Kodi (pvr.iptvsimple Omega "
            "has no native Xtream connection mode; run the host build "
            "_tools/build_iptv.py / the provisioner to stage it)" % n,
            xbmc.LOGERROR,
        )
        return False
    groups_special = _groups_file_special(provider)
    groups_file = xbmcvfs.translatePath(groups_special)
    groups = [g for g in map(_group_source, split_list(provider["groups"])) if g]
    if groups:
        os.makedirs(os.path.dirname(groups_file), exist_ok=True)
        groot = ET.Element("customChannelGroups")
        for name in groups:
            ET.SubElement(groot, "channelGroupName").text = name
        with open(groups_file, "w", encoding="utf-8") as f:
            f.write(ET.tostring(groot, encoding="unicode"))
        _log(
            "_ensure_iptv_custom_tv_groups: instance %d: generated %d custom "
            "group(s) from env" % (n, len(groups))
        )
    # The playlist SOURCE (m3u/epg) and the group MODE are independent: inject
    # the source whenever the env supplies it, but only force CUSTOM group mode
    # when the groups file exists (crit A — never tvGroupMode=2 at a missing
    # file). With neither, there's nothing to do — leave the all-channels default.
    m3u = provider["m3u"]
    epg = provider["epg"]
    have_groups = os.path.exists(groups_file)
    if not (m3u or epg or have_groups):
        _log(
            "_ensure_iptv_custom_tv_groups: instance %d: nothing to set (no "
            "m3u/epg, no groups file %s) — leaving the all-channels default"
            % (n, groups_file)
        )
        return False
    xml_path = xbmcvfs.translatePath(_instance_settings_special(n))
    os.makedirs(os.path.dirname(xml_path), exist_ok=True)

    root = None
    if os.path.exists(xml_path):
        try:
            root = ET.parse(xml_path).getroot()
        except ET.ParseError as e:
            _log(
                "_ensure_iptv_custom_tv_groups: instance-settings-%d.xml "
                "malformed, recreating: %s" % (n, e),
                xbmc.LOGERROR,
            )
            root = None
    if root is None or root.tag != "settings":
        root = ET.Element("settings")
        root.set("version", "2")

    changed = False
    # Instance identity — NUMBERED providers only (the legacy single-instance file
    # stays byte-compatible). The name labels the client in Kodi's PVR list; the
    # enabled flag makes a CREATED instance file count to the instance scanner.
    if not provider["legacy"]:
        if provider["name"]:
            changed = (
                _set_instance_setting(root, IPTV_INSTANCE_NAME_KEY, provider["name"])
                or changed
            )
        changed = (
            _set_instance_setting(root, IPTV_INSTANCE_ENABLED_KEY, "true") or changed
        )
    # Playlist source (provider creds — SECRET; never logged as values).
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
            _set_instance_setting(root, IPTV_CUSTOM_TV_GROUPS_FILE_KEY, groups_special)
            or changed
        )
        only = (provider["groups_only"] or "true").strip().lower()
        only_val = "true" if only in ("true", "1", "yes", "on") else "false"
        changed = (
            _set_instance_setting(root, IPTV_TV_CHANNEL_GROUPS_ONLY_KEY, only_val)
            or changed
        )
    else:
        _log(
            "_ensure_iptv_custom_tv_groups: instance %d: no groups file — m3u/epg "
            "set, group mode left at the all-channels default" % n
        )

    if changed:
        with open(xml_path, "w", encoding="utf-8") as f:
            f.write(ET.tostring(root, encoding="unicode"))
        _log(
            "_ensure_iptv_custom_tv_groups: instance %d: groups=%s only=%s m3u=%s "
            "epg=%s in %s" % (n, have_groups, only_val, bool(m3u), bool(epg), xml_path)
        )
    else:
        _log(
            "_ensure_iptv_custom_tv_groups: instance %d: keys already correct "
            "(no change)" % n
        )
    return changed


def _ensure_iptv_custom_tv_groups(box_env=None):
    """Enforce pvr.iptvsimple's per-instance settings for EVERY env provider.

    Phase 5b·2: when the env carries ``IPTV_STAGING_DIR`` (the provisioner set
    it after staging the host-built curated artifacts), each provider FIRST
    tries ``_apply_staged_provider`` — the staged instance-settings + curated
    playlist + display-label groups file are applied verbatim (this is how an
    xtream-mode provider, impossible to configure from the raw env, lands; and
    how relabel/sort/favorites reach an m3u provider). A provider with
    no/partial/malformed staging falls back per-provider to the direct-env
    enforce below — no provider with a usable source is ever left unconfigured
    when its staging exists.

    Phase 5b·1 generalization of the old single-instance enforce: the env's
    ``IPTV_<N>_*`` provider blocks (or the legacy single-instance
    ``IPTV_M3U``/``IPTV_EPG``/``IPTV_GROUPS``/``IPTV_GROUPS_ONLY`` shape, treated
    as provider 1 with the monolith's exact file paths) each drive ONE
    ``instance-settings-<N>.xml`` + one ``customTVGroups-*.xml`` via
    ``_ensure_iptv_instance``. Runs AFTER _copy_device_files() (which may have
    staged a user-provided instance-settings file the enforce then patches).
    These keys cannot be set via JSON-RPC (it does not reach add-on instance
    settings), so a direct file write is the only mechanism — which is exactly
    why ``apply_iptv`` runs this inside the PVR-DISABLED window (the running
    client otherwise flushes its stale in-memory defaults back over the write).

    Idempotent and fully defensive: a failing provider is logged and skipped
    (the others still apply), and any outer failure is swallowed — never aborts
    the rest of setup. Secret values (m3u/epg URLs with creds) are never logged.

    Returns
    -------
    bool
        ``True`` if it actually WROTE/changed ANY instance-settings file this
        call (the OR across providers of each instance's ``_set_instance_setting``
        aggregate), ``False`` otherwise — i.e. on the gated no-op (no m3u/epg and
        no groups file), on already-correct files (the ``if changed:``
        write-skip), on an xtream-mode skip, or on a swallowed failure. This is
        the truthful "did config land?" signal ``apply_iptv`` reports from.
        ``_configure_box`` ignores it (purely additive).
    """
    box_env = box_env or {}
    try:
        # The host-staged dir — present iff the provisioner actually built and
        # staged curated artifacts (NO default: legacy boxes never enter this).
        staging = (box_env.get(IPTV_STAGING_DIR_KEY) or "").strip()
        wrote = False
        for provider in _iptv_providers(box_env):
            try:
                if staging and _apply_staged_provider(provider, staging):
                    wrote = True
                    continue  # staged config is authoritative — skip direct env
                wrote = _ensure_iptv_instance(provider) or wrote
            except Exception as e:  # noqa: BLE001 - one bad provider must not abort the rest
                _log(
                    "_ensure_iptv_custom_tv_groups: instance %d failed "
                    "(non-fatal): %s" % (provider["n"], e),
                    xbmc.LOGERROR,
                )
        return wrote
    except Exception as e:  # noqa: BLE001 - never abort the rest of setup
        _log(
            f"_ensure_iptv_custom_tv_groups failed (non-fatal): {e}",
            xbmc.LOGERROR,
        )
        return False


# --------------------------------------------------------------------------- #
# The PVR-disabled config window (Phase 5b·1 — the instance-settings clobber fix).
# --------------------------------------------------------------------------- #
def _pause_pvr_for_config():
    """Disable pvr.iptvsimple BEFORE writing its config files; True if disabled.

    The clobber fix (the 5a·3 live run's bug #1): enabling pvr.iptvsimple
    instantiates the live PVR client with stock in-memory defaults, and the
    client flushes those in-memory settings back to ``instance-settings-*.xml``
    (latest at the end-of-setup shutdown) — silently OVERWRITING any direct file
    write made while it runs. Same failure class as the documented
    ``Skin.SetBool`` clobber. Disabling the add-on tears the client down — its
    stale-defaults flush lands BEFORE our writes — and the re-enable
    (``_resume_pvr_after_config``) instantiates fresh clients FROM our files, so
    in-memory state matches disk and every later flush preserves it. This uses
    the library's own ``disable``/``enable`` primitives rather than forking the
    shared ``install_with_deps`` (whose final enable is correct for every other
    add-on), and uniformly covers BOTH the fresh-install path (just enabled by
    ``install_with_deps``) and re-entry on an already-enabled box.

    No-op (returns False) when the backend is not installed; any failure is
    logged and swallowed (the write still proceeds — a clobber risk beats
    aborting setup)."""
    try:
        if not is_installed(PVR_BACKEND_ID):
            return False
        disable(PVR_BACKEND_ID)
        # Settle: let the client teardown finish (and flush ITS settings) before
        # our file writes, so the teardown flush can never land after them.
        xbmc.sleep(1000)
        return True
    except Exception as e:  # noqa: BLE001 - never abort setup over the pause
        _log(f"_pause_pvr_for_config failed (non-fatal): {e}", xbmc.LOGERROR)
        return False


def _resume_pvr_after_config():
    """Re-enable pvr.iptvsimple AFTER the config writes (the window's other half).

    The enable makes Kodi's multi-instance scanner re-read every
    ``instance-settings-<N>.xml`` we just wrote — including a freshly CREATED
    instance file for an additional provider — so the client(s) start with OUR
    settings in memory. Defensive: a failure is logged, never raised (callers
    run this in a ``finally``)."""
    try:
        enable(PVR_BACKEND_ID)
    except Exception as e:  # noqa: BLE001 - never abort setup over the resume
        _log(f"_resume_pvr_after_config failed (non-fatal): {e}", xbmc.LOGERROR)


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
      2. DISABLES the backend (``_pause_pvr_for_config`` — the Phase 5b·1 clobber
         fix: the live client otherwise flushes stock in-memory defaults back over
         the file writes below; the 5a·3 live run shipped an unconfigured pvr that
         way), then
      3. copies the user's device files into userdata (guarded; skips missing), and
      4. enforces the instance-settings — ONE ``instance-settings-<N>.xml`` per env
         provider (``IPTV_<N>_*``; the legacy single-instance keys are provider 1).
         With ``IPTV_STAGING_DIR`` in the env each provider first consumes the
         HOST-BUILT staged artifacts (curated playlist + display-label groups +
         ready instance file — the only path an xtream-mode provider can land
         through), falling back per-provider to the direct-env enforce (gated on
         its groups file; xtream skipped with an honest log when unstaged) — then
      5. RE-ENABLES the backend (in a ``finally``) so the fresh client instances
         start from the files just written.

    In a FULL Express run the NET installed set is UNCHANGED vs the old monolith:
    pvr.iptvsimple (+ inputstream.*) is still installed — just via THIS layer
    instead of the base loop. The copy-then-enforce body is the verbatim
    ``_configure_box`` IPTV order (copy BEFORE enforce, so the enforce patches the
    copied file rather than being overwritten by it).

    Parameters
    ----------
    env
        The already-parsed per-device env dict (passed in by the orchestrator). The
        instance-settings enforce reads the multi-provider ``IPTV_<N>_NAME / MODE /
        M3U / EPG / GROUPS / GROUPS_ONLY`` blocks (one pvr.iptvsimple instance per
        provider), or the legacy single-instance IPTV_GROUPS / IPTV_M3U / IPTV_EPG /
        IPTV_GROUPS_ONLY as provider 1; secret values (m3u/epg creds) are never
        logged.
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

    # --- the PVR-DISABLED config window (Phase 5b·1 — the clobber fix) ---
    # The copy AND the enforce both write pvr.iptvsimple's instance-settings files
    # directly; with the just-enabled live client running, it flushes its stale
    # in-memory defaults back over those writes (the 5a·3 live run shipped an
    # UNCONFIGURED pvr exactly this way). Disable the backend first (its teardown
    # flush lands BEFORE our writes), write, then re-enable in a finally (never
    # leave the backend disabled) so fresh clients start FROM our files.
    paused = _pause_pvr_for_config()
    try:
        # --- copy the user's device files into userdata (guarded; skips missing) ---
        _copy_device_files()

        # --- enforce pvr.iptvsimple instance-settings (gated on the groups file) ---
        # Take the enforce's OWN return signal for "did config land?". The enforce
        # aggregates every _set_instance_setting change and returns True only when it
        # actually WROTE an instance-settings file this call (group mode and/or
        # m3u/epg keys, across every env provider). This is the truthful signal: the
        # old `existed_before` probe lied on a normally-provisioned box, where the
        # device-copy stages instance-settings-1.xml BEFORE this enforce — so the
        # file ALWAYS pre-exists, yet the enforce still writes real config.
        wrote_instance = _ensure_iptv_custom_tv_groups(env)
    finally:
        if paused:
            _resume_pvr_after_config()

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
