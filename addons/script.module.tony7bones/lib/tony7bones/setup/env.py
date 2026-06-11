"""Per-device config (tony7bones.env) parsing — pure Python, no Kodi deps.

The provisioner derives a per-device ``tony7bones.env`` (KEY=value, shell-style)
from the owner's master ``.env`` and pushes it to the box; this reads it and feeds
the values into the existing idempotent settings writers. Pure-Python + no Kodi
deps so it is unit-testable in isolation and importable outside Kodi. NEVER log a
parsed value (secrets).

These three functions (``parse_env``, ``split_list``, ``read_box_env``) were moved
VERBATIM out of ``script.tony7bones.bootstrap/default.py`` into this shared
sublibrary so the new ``setup/`` orchestrator + layer modules and the existing
bootstrap re-export the same single implementation. No logic change.
(``env_has_iptv`` followed in Phase 6 — same move, same reason: the probes
module needs it for ``assert_box_complete`` and must not import the bootstrap.)

Phase N1 (the no-computer track) generalized the env SOURCE from the single
Android constant to an ORDERED path list: the provisioner's pushed file
(``BOX_ENV_PATH`` — wins when present) first, then the PROFILE-LOCAL persisted
env (``PROFILE_ENV_SPECIAL`` — what the on-box config collector writes; lives
inside Kodi's own writable profile, so it works on every platform with no adb /
scoped-storage dependency). ``box_env_paths`` / ``read_first_env`` /
``delete_box_envs`` are the three helpers; the module stays import-clean
without Kodi (``xbmcvfs`` is imported LAZILY, only to translate the
``special://`` profile path, and its absence simply omits that candidate).

Phase N1.1 adds the CANONICAL DEVICE ROOT and the DEVICE-RESIDENT MASTER env.

The canonical brand root is ``/storage/emulated/0/_T7B/`` (owner directive,
2026-06-10). Two distinct jobs live under it:

  * the BRAND ROOT itself (``_T7B/``) is where the owner PLACES the
    device-resident MASTER env (e.g. ``_T7B/env.office``) — confirmed by
    physical placement on every box — and where Setup SCAFFOLDS a new master;
  * the STAGING tree (``_T7B/kodi/`` — layout ``backups/ iptv/ media/
    repositories/ rss/ scripts/``) is where the provisioner pushes the derived
    ``tony7bones.env`` and stages the IPTV artifacts.

The old ``/storage/emulated/0/kodi/tony.7.bones/`` root is a LEGACY FALLBACK
only: still READ (already-provisioned boxes have files there today) but never
written to — no scaffold, no push target.

The MASTER env is the owner's editing copy placed (by ANY means — adb,
downloader app, USB, share) in a device root. Its basename is matched
DOT-OPTIONALLY: the owner uses ``env.<device>`` (no leading dot — the physical
convention); the committed example/template uses ``.env.<device>`` (leading
dot). BOTH are recognised. It is the box's PERSISTENT identity: read after the
derived pushes (the freshest deliberate provisioning act outranks the standing
identity) and before profile-local, applied through the provisioner-parity
derivation (:func:`derive_master_env`), and **NEVER deleted** — the terminal
delete set (:func:`deletable_env_paths`) deliberately excludes every master so
a Kodi wipe-and-redo works forever off the same file. The MASTER is scanned
across, in order: the BRAND ROOT (``_T7B/`` — PRIMARY, where the owner places
it) → the STAGING tree (``_T7B/kodi/``) → the LEGACY root. When NO env exists
anywhere, Setup SCAFFOLDS the master template (:func:`scaffold_master_env`) as
``_T7B/env.<device>`` (no leading dot — the owner's convention) at the BRAND
ROOT for the user to fill in and re-run.
"""

import os as _os
import re as _re

# The CANONICAL brand root (N1.1, owner directive — where the owner PLACES the
# master env and where Setup scaffolds it), the STAGING tree beneath it (the
# provisioner's push target + IPTV staging), and the LEGACY root they replace.
# The legacy root is read-only fallback: devices provisioned before N1.1 still
# carry files there, so every reader scans it AFTER the canonical roots; nothing
# ever writes there again.
BRAND_ROOT = "/storage/emulated/0/_T7B"
DEVICE_ROOT = "/storage/emulated/0/_T7B/kodi"
LEGACY_DEVICE_ROOT = "/storage/emulated/0/kodi/tony.7.bones"

# The per-device config the provisioner derives from the owner's master .env and
# pushes to the box (the COMPUTER-path producer). Moved here from the bootstrap
# in Phase N1 so the path list has one home; the bootstrap re-exports it.
# N1.1: MOVED under the canonical root (the provisioner's push target moved in
# the same commit — one root for everything new); the legacy location is still
# READ (second) for boxes provisioned before the move.
BOX_ENV_PATH = DEVICE_ROOT + "/tony7bones.env"
LEGACY_BOX_ENV_PATH = LEGACY_DEVICE_ROOT + "/tony7bones.env"

# The PROFILE-LOCAL env (the NO-COMPUTER-path producer — the on-box collector
# persists here from Phase N2 on). Inside Kodi's own profile: writable
# everywhere Kodi runs, no adb, no scoped-storage exposure.
PROFILE_ENV_SPECIAL = (
    "special://profile/addon_data/script.tony7bones.bootstrap/tony7bones.env"
)


def profile_env_path():
    """The translated real path of the profile-local env, or ``None`` when not
    running under Kodi (``xbmcvfs`` unavailable — pure-Python callers)."""
    try:
        import xbmcvfs

        return xbmcvfs.translatePath(PROFILE_ENV_SPECIAL)
    except Exception:  # noqa: BLE001 - off-Kodi: no profile path to offer
        return None


def staging_dir(primary=None):
    """The CANONICAL on-box STAGING root — the dir holding the pushed derived
    env and the ``iptv/`` artifact staging (``_T7B/kodi/`` in production).
    Derived from the primary candidate so a test's monkeypatched
    ``BOX_ENV_PATH`` carries its whole staging dir along."""
    return _os.path.dirname(primary or BOX_ENV_PATH)


def brand_root(primary=None):
    """The BRAND ROOT (``_T7B/``) — where the owner PLACES the master env and
    where Setup scaffolds it (one level ABOVE the staging tree). Derived from
    the primary candidate: when the staging dir is the production ``…/kodi``
    leaf, the brand root is its parent; otherwise (a test's flat tmp staging,
    or any non-``kodi`` layout) the brand root IS the staging dir, so existing
    fixtures that drop masters beside the pushed env keep resolving."""
    staging = staging_dir(primary)
    if _os.path.basename(staging) == "kodi":
        return _os.path.dirname(staging)
    return staging


def legacy_staging_dir():
    """The LEGACY staging root (read-only fallback) — derived from the legacy
    push path the same way, so a test can monkeypatch
    ``LEGACY_BOX_ENV_PATH`` and carry the legacy root along."""
    return _os.path.dirname(LEGACY_BOX_ENV_PATH)


# The STAGING subdirs onboarding ensures under the DEVICE_ROOT (``_T7B/kodi/``).
# Single source of truth, mirrored from ``docs/directory_structure.txt`` (the
# canonical layout) and the provisioner's pre-boot ``mkdir -p``. Setup creates
# any of these that are missing so the device→userdata file conventions
# (RSS / IPTV staging / media / repositories / backups) have a home on a box
# that was never touched by the adb provisioner (the no-computer path).
DEVICE_STAGING_SUBDIRS = ("backups", "iptv", "media", "repositories", "rss")


def ensure_device_dirs(primary=None, log=None):
    """Create the canonical ``_T7B`` device tree if it is not already there.

    Ensures (idempotent, ``makedirs(..., exist_ok=True)``) the BRAND ROOT
    (``_T7B/``), the DEVICE_ROOT staging tree (``_T7B/kodi/``), and each
    :data:`DEVICE_STAGING_SUBDIRS` entry under it — only the ones missing.
    Reuses :func:`brand_root` / :func:`staging_dir`, so a test's monkeypatched
    ``primary`` (its tmp staging root) is honored exactly like every other
    helper, and production resolves the real ``/storage/emulated/0/_T7B`` roots.

    Does NOT create or touch the device-resident master ``.env.<device>`` (the
    scaffold owns that). Fully GUARDED and NON-FATAL: any failure — a read-only
    filesystem, an off-Kodi host where ``/storage`` cannot exist (macOS dev),
    a permission error — is logged through ``log`` (FILE PATHS only, never
    secrets) and SWALLOWED, because onboarding must never abort over staging
    dirs. Returns the list of directories ACTUALLY created this call (for an
    honest log line); an already-complete box returns ``[]`` (a clean no-op)."""
    created = []
    roots = [brand_root(primary), staging_dir(primary)]
    staging = staging_dir(primary)
    roots.extend(_os.path.join(staging, sub) for sub in DEVICE_STAGING_SUBDIRS)
    for path in roots:
        if _os.path.isdir(path):
            continue
        try:
            _os.makedirs(path, exist_ok=True)
            created.append(path)
        except OSError as e:  # noqa: PERF203 - per-dir guard: one failure ≠ abort
            if log:
                log("device-dir create skipped ({}): {}".format(path, e))
    if created and log:
        log("device tree ensured: created {}".format(", ".join(created)))
    return created


def derived_env_paths(primary=None):
    """The DERIVED (provisioner-pushed ``tony7bones.env``) candidates, ordered:
    the canonical push path first, the legacy push path second (boxes
    provisioned before the N1.1 root move still have theirs there). Deduped —
    a test's primary may coincide with the legacy path."""
    paths = [primary or BOX_ENV_PATH]
    if LEGACY_BOX_ENV_PATH not in paths:
        paths.append(LEGACY_BOX_ENV_PATH)
    return paths


# A device-resident MASTER env basename is ``env.<device>`` OR ``.env.<device>``
# (dot-OPTIONAL — the owner places the no-dot form on the box; the committed
# example/template uses the dot form). The ``<device>`` suffix must be non-empty
# (``env`` / ``.env`` bare are not masters). Editor/build/example artifacts that
# happen to start ``env.`` (``env.bak``, ``env.py``, ``env.swp``, the committed
# ``…device.example`` template, …) are explicitly EXCLUDED so a stray file on
# the box never routes (owner directive N1.1: "exclude obvious non-env matches").
_MASTER_NAME = _re.compile(r"^\.?env\..+$")
# Suffix denylist for the dot-optional master match — backup/editor/source
# artifacts, never a device config. ``.example`` covers the committed template.
_NON_MASTER_SUFFIXES = (
    ".example",
    ".bak",
    ".orig",
    ".tmp",
    ".swp",
    ".swo",
    ".old",
    ".save",
    ".py",
    ".pyc",
    ".pyo",
    ".sample",
    "~",
)


def is_master_env_filename(name):
    """True for a MASTER env BASENAME — ``env.<device>`` or ``.env.<device>``
    (dot-optional) — excluding obvious non-config artifacts (``*.example``,
    ``*.bak``, ``*.py``, editor swap files, …; see ``_NON_MASTER_SUFFIXES``)."""
    name = name or ""
    if not _MASTER_NAME.match(name):
        return False
    return not name.endswith(_NON_MASTER_SUFFIXES)


def is_master_env_path(path):
    """True for a device-resident MASTER env path — the user-placed/scaffolded
    persistent identity file (basename ``env.<device>`` or ``.env.<device>``,
    dot-optional), as opposed to the derived ``tony7bones.env`` push or the
    profile-local collector env."""
    return is_master_env_filename(_os.path.basename(path or ""))


def master_env_roots(primary=None):
    """The roots scanned for MASTER envs, ordered: the BRAND ROOT first (``_T7B/``
    — PRIMARY, where the owner physically places the master), then the STAGING
    tree (``_T7B/kodi/`` — the prior N1.1 location, kept as fallback), then the
    LEGACY root (read-only fallback). Deduped — in a flat test layout the brand
    root and staging dir coincide."""
    roots = []
    for root in (brand_root(primary), staging_dir(primary), legacy_staging_dir()):
        if root not in roots:
            roots.append(root)
    return roots


def _masters_in(root):
    """Sorted MASTER-env files in one root (basename ``env.*`` or ``.env.*``,
    dot-optional, ``*.example`` excluded); ``[]`` when the root is unreadable or
    absent (off-device — no ``/storage`` root exists on macOS)."""
    try:
        return sorted(
            _os.path.join(root, n)
            for n in _os.listdir(root)
            if is_master_env_filename(n) and _os.path.isfile(_os.path.join(root, n))
        )
    except OSError:
        return []


def master_env_paths(primary=None, log=None):
    """The device-resident MASTER env candidates: every master file (basename
    ``env.*`` or ``.env.*``, dot-optional) in the BRAND ROOT (sorted), then the
    STAGING tree (sorted), then the LEGACY root (sorted) — deterministic, brand
    root wins. More than one IN TOTAL is a misconfiguration — warn through
    ``log`` (FILE PATHS only, never values) and let the ordered read pick the
    first NON-EMPTY one (same skip-degenerate semantics as every other
    candidate). Off-device (no root exists) returns ``[]``."""
    paths = []
    for root in master_env_roots(primary):
        paths.extend(_masters_in(root))
    if len(paths) > 1 and log:
        log(
            "multiple master envs: {} — reading in brand-root-first sorted "
            "order, first non-empty wins".format(", ".join(paths))
        )
    return paths


def _dir_has_content(path):
    """True when ``path`` is a directory holding at least one entry. Guarded —
    an absent/unreadable dir is ``False`` (off-device, no ``/storage``). Used to
    distinguish a REAL IPTV staging dir (artifacts pushed in) from the EMPTY
    ``iptv/`` :func:`ensure_device_dirs` self-creates on every box."""
    try:
        return _os.path.isdir(path) and bool(_os.listdir(path))
    except OSError:
        return False


def derive_master_env(env, path):
    """Provisioner-parity derivation for a RAW master env (the provisioner
    applies the same shaping when it derives ``tony7bones.env`` — see
    ``_tools/provision-kodi.sh`` step 4c):

      * ``DEVICE_IP`` is DROPPED (laptop-only connection metadata; the
        provisioner greps it out).
      * ``IPTV_STAGING_DIR`` is injected iff absent AND the sibling ``iptv/``
        staging dir holds STAGED ARTIFACTS (is non-empty) — equivalent to the
        provisioner appending the key iff the artifact push landed
        (``apply_iptv`` validates per-provider artifacts and falls back to
        direct-env, so a stale/partial dir is safe). NOTE: the test is
        NON-EMPTY, not mere existence, because onboarding now self-creates an
        EMPTY ``iptv/`` on every box (:func:`ensure_device_dirs`); an empty
        staging dir is no staging, and must not make an otherwise-empty master
        (e.g. one carrying only ``DEVICE_IP``) look configured.
      * ``DEVICE_NAME`` divergence (documented): the provisioner overrides it
        with its interactive prompt; there is no prompt on the no-computer
        path, so the master's own value is authoritative.
    """
    env = dict(env)
    env.pop("DEVICE_IP", None)
    if "IPTV_STAGING_DIR" not in env:
        # The IPTV artifacts stage under the STAGING tree (``_T7B/kodi/iptv/``).
        # A master placed AT the staging tree finds ``iptv/`` as a sibling; a
        # master placed at the BRAND ROOT (``_T7B/env.office``) finds it one
        # level down under ``kodi/`` — check both, sibling first.
        master_dir = _os.path.dirname(path)
        for iptv_dir in (
            _os.path.join(master_dir, "iptv"),
            _os.path.join(master_dir, "kodi", "iptv"),
        ):
            # Non-empty = staged artifacts actually landed. An EMPTY iptv/ (the
            # one onboarding self-creates) is not staging and must not inject.
            if _dir_has_content(iptv_dir):
                env["IPTV_STAGING_DIR"] = iptv_dir
                break
    return env


def box_env_paths(primary=None, log=None):
    """The ORDERED env-source candidates (N1.1):

      1. the pushed ``BOX_ENV_PATH`` (or the caller's ``primary`` override) —
         the freshest provisioner derivation; the provisioned path stays
         byte-compatible by construction,
      2. the LEGACY push path (boxes provisioned before the ``_T7B`` root
         move),
      3. the device-resident MASTER candidates (``env.*`` / ``.env.*``,
         dot-optional) — brand root → staging tree → legacy root, each sorted
         (the persistent identity),
      4. the profile-local persisted env (omitted off-Kodi).

    Derived-before-master because a derived push is a fresh, deliberate
    provisioning act (the provisioner just ran against the owner's current
    config); the master is the standing identity it refreshes."""
    paths = derived_env_paths(primary)
    paths.extend(master_env_paths(primary, log=log))
    profile = profile_env_path()
    if profile:
        paths.append(profile)
    return paths


def deletable_env_paths(primary=None):
    """The candidates the TERMINAL ops may delete: the derived pushes (both
    roots) + the profile-local collector env — all machine-derived, all
    secret-bearing, all re-creatable. The device-resident MASTER ``.env.*``
    (either root) is **NEVER** in this set: it is the box's persistent
    identity, and a wipe-and-redo must keep working off it forever (owner
    contract, N1.1)."""
    paths = derived_env_paths(primary)
    profile = profile_env_path()
    if profile:
        paths.append(profile)
    return paths


def read_first_env(paths, reader=None):
    """Read the FIRST candidate path that parses to a NON-EMPTY env dict.

    An absent, unreadable, empty, or comment-only file is skipped (it carries
    no configuration — same class as absent, so a degenerate push can never
    shadow a real profile-local env; an unedited SCAFFOLD — all lines
    comment-disabled — is the same class, so it never hijacks routing). A
    MASTER candidate is passed through the provisioner-parity derivation
    (:func:`derive_master_env`); if that empties it (e.g. the file carried
    only ``DEVICE_IP``), it is skipped like any other degenerate. Returns
    ``{}`` when no candidate yields config — the bootstrap's no-env signal
    (→ the Guided wizard). ``reader`` defaults to :func:`read_box_env`;
    injectable so the bootstrap's re-exported (monkeypatchable) name keeps
    working."""
    reader = reader or read_box_env
    for path in paths:
        env = reader(path)
        if env and is_master_env_path(path):
            env = derive_master_env(env, path)
        if env:
            return env
    return {}


def delete_box_envs(paths):
    """Remove EVERY path given (guarded; a missing file is a no-op). The
    terminal ops (Express completion, Guided Finish / Remove Setup) call this
    with :func:`deletable_env_paths` so no machine-derived secret-bearing env
    lingers (Model A semantics) — while the device-resident MASTER survives
    (it is never in the deletable set)."""
    for path in paths:
        try:
            _os.remove(path)
        except OSError:
            pass


def sanitize_device_name(name):
    """Sanitize a Kodi device name into the ``.env.<device-name>`` suffix:
    lowercase, every non-alphanumeric run collapsed to a single dash, edges
    stripped; empty/unusable input falls back to the generic ``device``."""
    slug = _re.sub(r"[^a-z0-9]+", "-", (name or "").lower()).strip("-")
    return slug or "device"


# Prepended to the scaffolded master template so the file explains itself on
# the box. Placeholders only — no secret can appear here by construction.
_SCAFFOLD_BANNER = """\
# ------------------------------------------------------------------------------
#  Created by Tony.7.Bones Setup (no configuration was found on this box).
#
#  Every setting below is DISABLED (commented out). To configure the box:
#  remove the leading "# " from a line, fill in your value, save, and run
#  Setup again. Setup reads this file on every run and NEVER deletes it —
#  it is this box's persistent identity (a Kodi wipe-and-redo keeps working).
# ------------------------------------------------------------------------------

"""


def scaffold_template_text(template_text):
    """The scaffolded master content: the bundled ``.env.device.example``
    template with every active ``KEY=value`` line comment-DISABLED, plus the
    self-explaining banner. Disabling the placeholders is deliberate: an
    UNEDITED scaffold must parse to ``{}`` (the no-env class) so the next
    launch still reaches the wizard — active placeholder values would route
    Express with garbage config and make the wizard unreachable."""
    lines = []
    for line in template_text.splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            lines.append("# " + line)
        else:
            lines.append(line)
    return _SCAFFOLD_BANNER + "\n".join(lines) + "\n"


def scaffold_master_env(device_name, template_text, primary=None, log=None):
    """Create the device-resident master env TEMPLATE (the N1.1 scaffold duty:
    no env anywhere → Setup CREATES ``env.<device-name>`` — NO leading dot, the
    owner's convention — at the BRAND ROOT (``_T7B/``) for the user to fill in
    and re-run. Never the staging tree or the legacy root).

    Guarantees: NEVER overwrites anything (skipped when ANY master already
    exists at ANY scanned root — also avoids proliferating masters — and the
    create itself is ``open(..., "x")``, race-safe); creates the brand-root
    dir; guarded and non-fatal where the root cannot exist (macOS/off-device:
    the OSError is logged through ``log`` and the scaffold is SKIPPED — the
    desktop user has a computer path by definition). Returns the created path,
    or ``None`` when nothing was created."""
    if master_env_paths(primary):
        return None
    root = brand_root(primary)
    path = _os.path.join(root, "env." + sanitize_device_name(device_name))
    try:
        _os.makedirs(root, exist_ok=True)
        with open(path, "x", encoding="utf-8") as fh:
            fh.write(scaffold_template_text(template_text))
    except OSError as e:
        if log:
            log("master env scaffold skipped ({}): {}".format(path, e))
        return None
    return path


# IPTV env detection: an IPTV provider is configured when the per-device env
# carries a PLAYLIST SOURCE — a multi-provider ``IPTV_<N>_M3U`` /
# ``IPTV_<N>_PORTAL`` key (N a 1-based provider index) OR the single-instance
# ``IPTV_M3U`` / ``IPTV_PORTAL``. NOTE: ``IPTV_EPG`` alone does NOT trip the
# gate — an EPG with no playlist is a channel-less PVR (guide metadata, zero
# channels), not a usable source; ``apply_iptv`` still consumes ``IPTV_EPG``
# when a real playlist provider IS present. ``IPTV_GROUPS`` alone (group names,
# useless without a playlist) likewise does not count.
_IPTV_PROVIDER_KEY = _re.compile(r"^IPTV_(?:\d+_)?(?:M3U|PORTAL)$")


def env_has_iptv(box_env):
    """True when the per-device env carries an IPTV provider PLAYLIST source.

    Scans the env keys for any ``IPTV_<N>_M3U`` / ``IPTV_<N>_PORTAL``
    (multi-provider) or the single-instance ``IPTV_M3U`` / ``IPTV_PORTAL`` —
    and only counts a key whose VALUE is non-empty (an empty ``IPTV_M3U=`` is
    not a provider). This is the gate the orchestrators use to decide whether
    the IPTV layer applies to this box; the probes use it the same way for
    ``assert_box_complete``. Pure-Python; never raises.
    """
    box_env = box_env or {}
    for key, val in box_env.items():
        if _IPTV_PROVIDER_KEY.match(key) and (val or "").strip():
            return True
    return False


def parse_env(text):
    """Parse KEY=value config text into a dict. Tolerant of the real .env shape:
    blank lines and full-line `#` comments are ignored; a value may be single- or
    double-quoted (quotes stripped, inline `#` kept if inside quotes); an UNquoted
    value drops an inline `# comment`; CRLF is handled; a line without `=` is
    skipped. Values stay raw strings — callers split `;`-lists via split_list()."""
    env = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        val = val.strip()
        if val[:1] in ("'", '"'):
            val = val[1:].split(val[0], 1)[0]  # quoted body up to the closing quote
        else:
            val = val.split("#", 1)[0].strip()  # drop inline comment when unquoted
        if key:
            env[key] = val
    return env


def split_list(value, sep=";"):
    """Split a `sep`-delimited multi-value field; trim each item, drop empties."""
    return [item.strip() for item in (value or "").split(sep) if item.strip()]


def read_box_env(path):
    """Read + parse the per-device tony7bones.env at `path`. Returns {} when the
    file is absent or unreadable (the no-env fallback — never raises). N1.1:
    "unreadable" includes NON-TEXT content (``UnicodeError``) — a user-placed
    master can be any bytes a file app produced, and a binary file carries no
    configuration (same class as absent)."""
    try:
        with open(path, encoding="utf-8") as fh:
            return parse_env(fh.read())
    except (OSError, UnicodeError):
        return {}
