#!/usr/bin/env python3
"""Assemble the complete Pages site into an output dir (the CI build step).

END-STATE MODE (post static conversion): main is sources-only. This tool

1. copies every TRACKED file into the output dir - `git ls-files` is the copy
   list, so a gitignored local secret (e.g. the IPTV instance settings) can
   never reach the artifact even on a developer machine - with structural
   secret exclusion applied at copy time (the canvas mirror in step 2 copies
   from the working-tree dropbox/ and skips gitignored files, so an untracked
   non-ignored stray file WOULD ride into a local build; CI always builds
   from a fresh tracked-only checkout),
2. GENERATES the served canvas mirror into the output dir (dropbox/ ->
   repositories/, media/, iptv/, rss/, ... plus per-folder Kodi indexes, the
   root index.html, and robots.txt) via the generate_repo mirror functions -
   the mirror is never committed,
3. builds the `/static/` Kodi repository tree next to it via
   static_catalog.py, and
4. places the current repository.tony7bones installer at the site root and in
   the browsable repositories/ folder.

--first-party-only skips the /static/ catalog build and the installer
placement (no network): the tracked copy + the generated canvas mirror alone.

Usage:
    python3 _tools/build_site.py --out _site
        [--refresh-third-party] [--allow-catalog-shrink] [--no-baseline]
        [--first-party-only] [--base-url https://tony7bones.github.io]
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import check_site_secrets  # noqa: E402
import generate_repo  # noqa: E402
import static_catalog  # noqa: E402

REPO_ROOT = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
)


def tracked_files(repo_root: str = REPO_ROOT) -> list[str]:
    """Relative paths of every git-tracked file - the ONLY copy list, so
    gitignored local files (secrets) structurally cannot reach the artifact."""
    out = subprocess.run(
        ["git", "-C", repo_root, "ls-files", "-z"],
        capture_output=True,
        check=True,
    )
    return [p for p in out.stdout.decode().split("\0") if p]


def copy_tracked_tree(out_dir: str, repo_root: str = REPO_ROOT) -> int:
    """Mirror the tracked tree into out_dir (replacing it wholesale)."""
    if os.path.isdir(out_dir):
        shutil.rmtree(out_dir)
    count = 0
    for rel in tracked_files(repo_root):
        src = os.path.join(repo_root, rel)
        if not os.path.isfile(src):  # deleted-but-staged edge
            continue
        # The structural secret rules apply at COPY time, not just at the
        # post-build gate: even if a secret-bearing artifact were ever
        # tracked again, it could not ship in a built artifact.
        # check_site_secrets.py remains the backstop for content that
        # arrives any other way (e.g. downloaded at build time).
        violation = check_site_secrets.publish_refusal(rel)
        if violation:
            static_catalog.warn(f"excluded from artifact ({violation}): {rel}")
            continue
        dst = os.path.join(out_dir, rel)
        os.makedirs(os.path.dirname(dst) or out_dir, exist_ok=True)
        shutil.copyfile(src, dst)
        count += 1
    return count


def build_site(
    out_dir: str,
    first_party_only: bool = False,
    refresh_third_party: bool = False,
    allow_shrink: bool = False,
    no_baseline: bool = False,
    base_url: str = static_catalog.DEFAULT_BASE_URL,
    repo_root: str = REPO_ROOT,
) -> None:
    count = copy_tracked_tree(out_dir, repo_root)
    print(f"site: copied {count} tracked files -> {out_dir}")

    # Generate the served canvas mirror into the output dir (never committed):
    # dropbox/ -> repositories/, media/, ... + indexes, root index, robots.txt.
    listing = generate_repo.mirror_canvas(out_dir, os.path.join(repo_root, "dropbox"))
    generate_repo.write_root_index(out_dir, listing)
    generate_repo.write_robots(out_dir)

    if first_party_only:
        print("site: --first-party-only, skipping /static/ catalog build")
        return
    manifest = static_catalog.build(
        os.path.join(out_dir, "static"),
        fetcher=static_catalog.Fetcher(refresh_mutable=refresh_third_party),
        baseline_url=None if no_baseline else f"{base_url}/static/catalog.json",
        base_url=base_url,
        allow_shrink=allow_shrink,
        repo_json=os.path.join(repo_root, "_tools", "catalog.json"),
        repo_root=repo_root,
    )
    place_root_installer(out_dir, manifest)


def place_root_installer(out_dir: str, manifest: dict) -> None:
    """Serve the repository.tony7bones zip at the site ROOT and in repositories/.

    A first-time user adds https://tony7bones.github.io/ as a file source and
    installs repository.tony7bones-<v>.zip from it. That installer IS the
    static-only add-on the /static/ build already produced - copy it to the
    root and into the browsable canvas repositories/ folder (no committed root
    zip anywhere; it is built fresh every deploy). Any stale committed root
    installer that rode in via the tracked-tree copy is removed first.
    """
    info = manifest["entries"].get("repository.tony7bones")
    if info is None:
        raise static_catalog.BuildError(
            "repository.tony7bones missing from the catalog - no installer to serve"
        )
    built = os.path.join(out_dir, "static", info["zip"])
    version = info["version"]
    installer = f"repository.tony7bones-{version}.zip"

    # Drop any stale root installer copied from the tracked tree.
    for name in os.listdir(out_dir):
        if name.startswith("repository.tony7bones-") and name.endswith(".zip"):
            os.remove(os.path.join(out_dir, name))
    shutil.copyfile(built, os.path.join(out_dir, installer))

    repos = os.path.join(out_dir, "repositories")
    if os.path.isdir(repos):
        for name in os.listdir(repos):
            if name.startswith("repository.tony7bones-") and name.endswith(".zip"):
                os.remove(os.path.join(repos, name))
        shutil.copyfile(built, os.path.join(repos, installer))
        # Regenerate the repositories/ index so Kodi's "Install from zip"
        # browser actually LISTS our installer alongside the third-party repo
        # zips - copying the file in is not enough; Kodi reads the HTML index.
        _reindex(repos)


def _reindex(folder: str) -> None:
    """Rewrite a served folder's Kodi-parseable HTML 3.2 index from its real
    contents (every file listed as an <a href>, plus Parent Directory)."""
    rows = ['<a href="../">Parent Directory</a>']
    for name in sorted(os.listdir(folder)):
        if name == "index.html":
            continue
        size = os.path.getsize(os.path.join(folder, name))
        rows.append(f'<a href="{name}">{name}</a>  {generate_repo._fmt_size(size)}')
    generate_repo._make_index(folder, f"Index of /{os.path.basename(folder)}/", rows)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", required=True)
    ap.add_argument("--first-party-only", action="store_true")
    ap.add_argument("--refresh-third-party", action="store_true")
    ap.add_argument("--allow-catalog-shrink", action="store_true")
    ap.add_argument("--no-baseline", action="store_true")
    ap.add_argument("--base-url", default=static_catalog.DEFAULT_BASE_URL)
    args = ap.parse_args(argv)
    try:
        build_site(
            args.out,
            first_party_only=args.first_party_only,
            refresh_third_party=args.refresh_third_party,
            allow_shrink=args.allow_catalog_shrink,
            no_baseline=args.no_baseline,
            base_url=args.base_url,
        )
    except static_catalog.BuildError as exc:
        print(f"BUILD FAILED: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
