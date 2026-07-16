#!/usr/bin/env bash
# Post-release PUBLISH GATE for the repository.tony7bones proxy.
#
# Why this exists (the bug this prevents):
#   release.py --proxy pushes main + tag, then *tries* to force a GitHub Pages
#   build and poll for it. But:
#     1. The force-build needs a token with 'pages: write'. The owner's token
#        does not have it -> the API returns 403 -> deploy.py falls back to the
#        auto-build and only WARNS.
#     2. GitHub Pages frequently does NOT auto-fire a build for a content-only
#        push (deploy.py's own docstring says so). When that happens, verify_live
#        just times out and the release still reports success.
#     3. The proxy UNIQUELY self-updates FROM Pages
#        (repository.json: repository.tony7bones zip = tony7bones.github.io/...),
#        while every other add-on is served from raw.githubusercontent. So an
#        unpublished Pages zip = boxes can never update the proxy = a newly added
#        add-on never appears, and the repo shows a retry loop.
#
# This gate verifies Pages ACTUALLY published the proxy zip and RE-TRIGGERS the
# build (the only trigger available without pages:write is a fresh push) until it
# does, then verifies the live chain and prints the exact box-side steps.
#
# Usage:  .claude/skills/deploy/publish-gate.sh [proxy_version]
#         (version auto-detected from addons/repository.tony7bones/addon.xml)
set -uo pipefail

# Resolve the repo root from THIS script's location, not the caller's cwd.
cd "$(git -C "$(dirname "${BASH_SOURCE[0]}")" rev-parse --show-toplevel)" || {
  echo "not in the repo"
  exit 1
}

PAGES="https://tony7bones.github.io"
RAW="https://raw.githubusercontent.com/tony7bones/tony7bones.github.io/main"

VER="${1:-$(grep -oE 'version="[0-9]+\.[0-9]+\.[0-9]+"' addons/repository.tony7bones/addon.xml |
  head -1 | grep -oE '[0-9]+\.[0-9]+\.[0-9]+')}"
[ -n "$VER" ] || {
  echo "could not determine proxy version"
  exit 1
}

ZIP="$PAGES/repository.tony7bones-$VER.zip"
echo "Publish gate: repository.tony7bones v$VER"
echo "  self-update zip (Pages): $ZIP"

code() { curl -s -o /dev/null -w "%{http_code}" "$1"; }

poll() { # poll <url> <attempts> <delay_s>
  local i c
  for i in $(seq 1 "$2"); do
    c="$(code "$1")"
    [ "$c" = "200" ] && {
      echo "  published (200) after ~$((i * $3))s"
      return 0
    }
    sleep "$3"
  done
  echo "  not published (last=$c) after ~$(($2 * $3))s"
  return 1
}

published=
for round in 1 2 3; do
  echo "Round $round: polling Pages for the proxy zip..."
  if poll "$ZIP" 9 20; then
    published=1
    break
  fi
  if [ "$round" -lt 3 ]; then
    echo "  -> Pages auto-build did not fire; re-triggering with an empty push..."
    git commit --allow-empty -q -m "Republish Pages for repository.tony7bones v$VER" &&
      git push origin main 2>&1 | tail -1
  fi
done

if [ -z "$published" ]; then
  cat <<EOF
FAILED: Pages is still not serving $ZIP.
  This is a Pages-side problem, not the release. Options:
    - GitHub -> repo Settings -> Pages -> re-select/save the source branch (forces a build).
    - Grant the deploy token 'pages: write' so release.py can force the build via the API.
EOF
  exit 1
fi

echo
echo "Live chain:"
printf "  %-34s %s\n" "Pages proxy zip (self-update)" "$(code "$ZIP")"
printf "  %-34s %s\n" "raw proxy zip" "$(code "$RAW/addons/repository.tony7bones/repository.tony7bones-$VER.zip")"
served="$(curl -s "$RAW/addons/repository.tony7bones/resources/repository.json" |
  python3 -c 'import sys,json;print(len(json.load(sys.stdin)))' 2>/dev/null)"
printf "  %-34s %s\n" "repository.json served add-ons" "${served:-?}"

cat <<EOF

PUBLISHED. On each Kodi box (the proxy self-updates FROM Pages):
  1. Add-ons -> Add-on browser -> (context menu) -> Check for updates
       updates the proxy to v$VER.
  2. Check for updates AGAIN  (or restart Kodi).
       Kodi cached the OLD add-on list during step 1; a NEWLY added add-on only
       shows after a second read THROUGH the now-updated proxy. This is the
       #1 "I released it but it's not listed" gotcha.
  3. Install from repository -> Tony.7.Bones Repository -> <category> -> <add-on>.
EOF
