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

__all__ = [
    "KodiHost",
    "LayerResult",
    "RealKodiHost",
    "parse_env",
    "read_box_env",
    "split_list",
]
