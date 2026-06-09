"""Tony.7.Bones shared install library.

Public API used by the Tony.7.Bones Setup (script.tony7bones.bootstrap).
Everything below is the genuinely-shared install machinery; the Setup keeps only
its own configuration (which repos/apps it installs, the curated video add-ons,
the file-manager sources, the home-menu trim, the install-then-disable set).

Stable surface:

  Primitives:
    is_installed, http_get, extract_zip, update_local_addons, enable, disable
    platform_tag, is_android, self_uninstall, activate_skin, restart_kodi

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

The engine submodules (``index`` / ``install`` / ``net`` / ``repos`` / ``system``)
each do ``import xbmc`` at module top, so importing them requires a Kodi runtime.
To keep that dependency OFF the import path of the pure-Python ``tony7bones.setup``
subpackage, the public names above are bound LAZILY via PEP 562 ``__getattr__``:
``from tony7bones import install_selection`` imports the owning engine submodule on
first access, but ``import tony7bones.setup.host`` touches none of them and so
needs no ``xbmc``. (An eager ``from .index import ...`` block here would defeat that
subpackage isolation — every ``tony7bones.*`` import would drag in the engine.)
"""

from __future__ import annotations

import importlib

# Public name -> owning engine submodule. Resolved lazily so the Kodi-dependent
# engine is only imported when one of these names is actually accessed.
_NAME_TO_MODULE = {
    # index
    "SYSTEM_PREFIXES": "index",
    "build_index": "index",
    "load_index_simple": "index",
    "load_repo_index": "index",
    "merge_index": "index",
    "parse_index": "index",
    "resolve_closure_combined": "index",
    "resolve_closure_ordered": "index",
    "ver_key": "index",
    # install
    "disable_after_install": "install",
    "install_closure": "install",
    "install_selection": "install",
    "install_with_deps": "install",
    # net
    "disable": "net",
    "enable": "net",
    "extract_zip": "net",
    "http_get": "net",
    "is_installed": "net",
    "update_local_addons": "net",
    # repos
    "KODI_MAJOR": "repos",
    "enable_source_repos": "repos",
    "have_source_repos": "repos",
    "repo_dirs": "repos",
    "set_origins": "repos",
    # system
    "activate_skin": "system",
    "is_android": "system",
    "platform_tag": "system",
    "restart_kodi": "system",
    "self_uninstall": "system",
}


def __getattr__(name):
    """PEP 562 lazy attribute access — import the owning engine submodule on
    first touch and bind the requested name. Keeps the Kodi-dependent engine off
    the import path of the pure-Python ``tony7bones.setup`` subpackage."""
    module_name = _NAME_TO_MODULE.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module = importlib.import_module(f".{module_name}", __name__)
    value = getattr(module, name)
    globals()[name] = value  # cache so subsequent access skips __getattr__
    return value


def __dir__():
    return sorted(set(globals()) | set(_NAME_TO_MODULE))


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
    "activate_skin",
    "restart_kodi",
    "self_uninstall",
    "set_origins",
    "update_local_addons",
    "ver_key",
]
