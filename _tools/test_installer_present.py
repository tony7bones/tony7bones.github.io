"""DEPLOYMENT GATE — the repository.tony7bones installer MUST be browsable in the
served ``repositories/`` folder, or the build/deploy fails loudly.

This has bitten us repeatedly: if the proxy installer zip is missing from the
served ``repositories/`` (a forgotten/broken ``generate_repo`` injection), users
have **no way to install or update** our repo — every box that installs from the
bare URL becomes an orphan (no first-party updates, no proxy, no "opt into more
later"). It must never silently ship missing.

By design the installer is a GENERATED artifact: it lives at the served ROOT
(``repository.tony7bones-<version>.zip``) and ``generate_repo.py`` injects a copy
into the served ``repositories/`` (``dropbox/`` stays pristine — it is NOT kept in
``dropbox/repositories/``). This gate verifies the injected output, so a stale or
forgotten injection cannot reach a release.
"""

import glob
import os

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SERVED_REPOS = os.path.join(ROOT, "repositories")


def _root_installers():
    return sorted(glob.glob(os.path.join(ROOT, "repository.tony7bones-*.zip")))


def test_exactly_one_root_installer():
    """Exactly one versioned installer at the served root (the source of truth)."""
    zips = _root_installers()
    names = [os.path.basename(z) for z in zips]
    assert len(zips) == 1, (
        "DEPLOYMENT GATE: expected exactly ONE repository.tony7bones-<version>.zip "
        f"at the served root, found {names}. Old zips must be pruned at release."
    )


def test_installer_present_in_served_repositories():
    """The installer MUST exist in the served repositories/ (where users install)."""
    name = os.path.basename(_root_installers()[0])
    served = os.path.join(SERVED_REPOS, name)
    assert os.path.isfile(served), (
        f"DEPLOYMENT GATE FAILED: {name} is MISSING from served repositories/. "
        "A box installing from the bare URL would be an ORPHAN (no install/update "
        "path). Run `python3 _tools/generate_repo.py` (it injects the installer) "
        "and commit the result before deploying."
    )


def test_served_installer_matches_root_byte_for_byte():
    """The injected copy must be byte-identical to the root installer (not stale)."""
    root = _root_installers()[0]
    served = os.path.join(SERVED_REPOS, os.path.basename(root))
    assert os.path.isfile(served), "served installer missing (see prior test)"
    with open(root, "rb") as a, open(served, "rb") as b:
        assert a.read() == b.read(), (
            "DEPLOYMENT GATE FAILED: the repositories/ installer is STALE — it "
            "differs from the root installer. Re-run generate_repo.py to re-inject."
        )


def test_installer_is_browsable_in_repositories_index():
    """The installer must be listed in repositories/index.html so it is browsable
    in Kodi's file manager (an unlisted zip is effectively un-installable)."""
    name = os.path.basename(_root_installers()[0])
    index = os.path.join(SERVED_REPOS, "index.html")
    assert os.path.isfile(index), (
        "DEPLOYMENT GATE FAILED: served repositories/index.html is missing."
    )
    with open(index, encoding="utf-8") as fh:
        listing = fh.read()
    assert name in listing, (
        f"DEPLOYMENT GATE FAILED: {name} is not listed in repositories/index.html "
        "— it would not be browsable/installable in Kodi's file manager."
    )
