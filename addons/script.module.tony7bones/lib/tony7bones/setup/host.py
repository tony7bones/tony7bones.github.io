"""KodiHost — the port wrapping the ``xbmc*`` calls the NEW setup code uses.

The proven engine (``net.py``, ``install.py``, ``system.py``, …) keeps its
existing ``import xbmc`` + ``sys.modules`` monkeypatch test harness untouched. The
NEW orchestrator + layer modules instead depend on this small interface and get a
plain constructor-injected fake in tests — no global module swapping.

``KodiHost`` documents the surface; ``RealKodiHost`` is the production
implementation that delegates to the real ``xbmc`` / ``xbmcgui`` / ``xbmcvfs``,
imported LAZILY inside each method so this module imports cleanly under pytest
(where those modules may be absent or mocked per-test). A ``FakeKodiHost`` for
tests can subclass ``RealKodiHost`` (overriding the methods it cares about) or
duck-type ``KodiHost`` directly — injection is just passing the instance in.

Because the parent ``tony7bones/__init__.py`` binds its Kodi-dependent engine
LAZILY (PEP 562 ``__getattr__``), ``import tony7bones.setup.host`` works OFF-box
with no ``xbmc`` installed — only an actually-CALLED ``RealKodiHost`` method (or
an engine name) pulls Kodi in. So the new setup code is testable without any
``sys.modules`` monkeypatching of xbmc: construct a fake host and inject it.

Port growth (intentional minimalism): this surface is the subset the Phase 2a
scaffolding needs. It will gain ``dialog`` / ``progress`` notifiers, the add-on
version (``getAddonInfo``), and settings get/set accessors — each added
TEST-DRIVEN in Phase 2b when the ``apply_*`` layers actually need them, not
speculatively now. ``get_cond_visibility`` is kept ahead of its first caller
because the upcoming done-probes evaluate ``Window.IsVisible(...)`` conditions;
it is the one deliberately forward-looking method.
"""

from __future__ import annotations


class KodiHost:
    """The interface the new setup/orchestrator code calls instead of ``xbmc*``.

    Subclass it (or duck-type it) to provide a fake in tests. Every method here
    raises ``NotImplementedError`` so an incomplete fake fails loudly rather than
    silently returning ``None``.
    """

    # Logging level constants — mirror xbmc.LOG* so callers can pass them through.
    LOGINFO = 1
    LOGWARNING = 2
    LOGERROR = 4

    def log(self, msg, level=LOGINFO):
        """Write a log line at the given level (xbmc.log)."""
        raise NotImplementedError

    def sleep(self, ms):
        """Block the calling thread for ``ms`` milliseconds (xbmc.sleep)."""
        raise NotImplementedError

    def get_cond_visibility(self, condition):
        """Evaluate a Kodi boolean condition string (xbmc.getCondVisibility).

        Forward-looking: no Phase 2a caller yet, kept because the Phase 2b
        done-probes evaluate ``Window.IsVisible(...)`` to confirm a screen
        settled before proceeding."""
        raise NotImplementedError

    def execute_jsonrpc(self, request):
        """Send a JSON-RPC request string, return the response string
        (xbmc.executeJSONRPC)."""
        raise NotImplementedError

    def execute_builtin(self, command):
        """Run a Kodi builtin command (xbmc.executebuiltin)."""
        raise NotImplementedError

    def translate_path(self, path):
        """Resolve a ``special://`` path to an absolute path
        (xbmcvfs.translatePath)."""
        raise NotImplementedError

    def get_skin_dir(self):
        """Return the active skin's add-on id (xbmc.getSkinDir)."""
        raise NotImplementedError

    def exists(self, path):
        """True if the file/dir at ``path`` exists (xbmcvfs.exists)."""
        raise NotImplementedError

    def mkdirs(self, path):
        """Recursively create ``path``; return bool success (xbmcvfs.mkdirs)."""
        raise NotImplementedError

    def copy(self, src, dst):
        """Copy ``src`` to ``dst`` (overwriting); return bool success
        (xbmcvfs.copy)."""
        raise NotImplementedError


class RealKodiHost(KodiHost):
    """Production ``KodiHost`` delegating to the real Kodi modules.

    All ``xbmc`` / ``xbmcvfs`` imports are done lazily inside the methods so this
    module imports without a running Kodi (e.g. under pytest). The level
    constants are bound from ``xbmc`` on first ``log`` call so callers that pass
    ``host.LOGINFO`` get the real values.
    """

    def log(self, msg, level=None):
        import xbmc

        if level is None:
            level = xbmc.LOGINFO
        xbmc.log(msg, level)

    def sleep(self, ms):
        import xbmc

        xbmc.sleep(ms)

    def get_cond_visibility(self, condition):
        import xbmc

        return xbmc.getCondVisibility(condition)

    def execute_jsonrpc(self, request):
        import xbmc

        return xbmc.executeJSONRPC(request)

    def execute_builtin(self, command):
        import xbmc

        xbmc.executebuiltin(command)

    def translate_path(self, path):
        import xbmcvfs

        return xbmcvfs.translatePath(path)

    def get_skin_dir(self):
        import xbmc

        return xbmc.getSkinDir()

    def exists(self, path):
        import xbmcvfs

        return xbmcvfs.exists(path)

    def mkdirs(self, path):
        import xbmcvfs

        return xbmcvfs.mkdirs(path)

    def copy(self, src, dst):
        import xbmcvfs

        return xbmcvfs.copy(src, dst)
