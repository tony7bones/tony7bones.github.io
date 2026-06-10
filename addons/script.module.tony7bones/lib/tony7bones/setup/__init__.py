"""tony7bones.setup — the modular setup sublibrary.

Scaffolding for the 0-1-2 (Foundation / IPTV / Add-ons) decomposition. This
package holds the new primitives the orchestrator + layer modules are built on:

  * ``LayerResult`` — the value object each ``apply_*`` layer returns; lets a
    layer REQUEST terminal operations the orchestrator decides.
  * ``KodiHost`` / ``RealKodiHost`` — the port wrapping the ``xbmc*`` calls the
    NEW code uses, so it gets a constructor-injected fake in tests instead of
    ``sys.modules`` monkeypatching. The parent package binds its Kodi-dependent
    engine lazily (PEP 562), so this whole subpackage imports OFF-box with no
    ``xbmc`` — only a CALLED ``RealKodiHost`` method pulls Kodi in.
  * env parsing (``parse_env`` / ``read_box_env`` / ``split_list``) — moved here
    verbatim from the bootstrap so it has one shared home.

The layer modules (``apply_foundation`` / ``apply_iptv`` / ``apply_addons``) and
the orchestrator land in later phases (2b/2c/2d/4).
"""

from .env import parse_env, read_box_env, split_list
from .host import KodiHost, RealKodiHost
from .result import LayerResult

# The setup-API capability level this library ships (Phase 6). The bootstrap
# declares the level it NEEDS (REQUIRED_SETUP_API in its default.py) and fails
# LOUD at import when the installed library is older — a cross-gate or sideload
# can pair a too-old library with a too-new bootstrap, and without this guard
# that pairing dies as a cryptic mid-run crash instead of an honest "update the
# library" message. Kodi's own <requires> version check does NOT cover our
# direct-extract install path, so the guard lives at runtime. Bump this (and
# the bootstrap's REQUIRED_SETUP_API) whenever the bootstrap starts depending
# on a new library capability.
# Level 2 (Phase N1): the ordered env-source helpers (env.box_env_paths /
# read_first_env / delete_box_envs) the bootstrap's run() routing now calls.
# Level 3 (Phase N1.1): the device-resident master env + scaffold helpers
# (env.deletable_env_paths / scaffold_master_env / master_env_paths) — the
# bootstrap's terminal deletes and no-env scaffold call them.
SETUP_API = 3

__all__ = [
    "KodiHost",
    "LayerResult",
    "RealKodiHost",
    "apply_foundation",
    "parse_env",
    "read_box_env",
    "split_list",
]


def __getattr__(name):
    """Lazily expose ``apply_foundation`` without eagerly importing
    ``foundation`` (which imports ``xbmc`` at module top — see the parent
    package's PEP 562 note). ``import tony7bones.setup`` stays Kodi-free;
    only ``tony7bones.setup.apply_foundation`` access pulls the engine in."""
    if name == "apply_foundation":
        from .foundation import apply_foundation

        return apply_foundation
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
