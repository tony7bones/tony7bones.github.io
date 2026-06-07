"""Tony.7.Bones shared install library.

Public API used by the Tony.7.Bones Setup (script.tony7bones.bootstrap).
Everything below is the genuinely-shared install machinery; the Setup keeps only
its own configuration (which repos/apps it installs, the curated video add-ons,
the file-manager sources, the home-menu trim, the install-then-disable set).

Stable surface:

  Primitives:
    is_installed, http_get, extract_zip, update_local_addons, enable, disable
    platform_tag, is_android, self_uninstall, restart_kodi

  Index + closure (base Setup, ordered indexes):
    load_index_simple, resolve_closure_ordered

  Index + closure (video Setup, combined index with origins):
    parse_index, load_repo_index, ver_key, merge_index, build_index,
    resolve_closure_combined

  Repos / origins:
    repo_dirs, have_source_repos, enable_source_repos, set_origins

  Install orchestration:
    install_with_deps, install_closure, install_selection, disable_after_install

  Constants:
    SYSTEM_PREFIXES, KODI_MAJOR
"""

from .index import (
    SYSTEM_PREFIXES,
    build_index,
    load_index_simple,
    load_repo_index,
    merge_index,
    parse_index,
    resolve_closure_combined,
    resolve_closure_ordered,
    ver_key,
)
from .install import (
    disable_after_install,
    install_closure,
    install_selection,
    install_with_deps,
)
from .net import (
    disable,
    enable,
    extract_zip,
    http_get,
    is_installed,
    update_local_addons,
)
from .repos import (
    KODI_MAJOR,
    enable_source_repos,
    have_source_repos,
    repo_dirs,
    set_origins,
)
from .system import is_android, platform_tag, restart_kodi, self_uninstall

__all__ = [
    "KODI_MAJOR",
    "SYSTEM_PREFIXES",
    "build_index",
    "disable",
    "disable_after_install",
    "enable",
    "enable_source_repos",
    "extract_zip",
    "have_source_repos",
    "http_get",
    "install_closure",
    "install_selection",
    "install_with_deps",
    "is_android",
    "is_installed",
    "load_index_simple",
    "load_repo_index",
    "merge_index",
    "parse_index",
    "platform_tag",
    "repo_dirs",
    "resolve_closure_combined",
    "resolve_closure_ordered",
    "restart_kodi",
    "self_uninstall",
    "set_origins",
    "update_local_addons",
    "ver_key",
]
