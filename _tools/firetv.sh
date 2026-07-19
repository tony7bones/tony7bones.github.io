#!/usr/bin/env bash
# shellcheck shell=bash
# Fire TV ADB helper, originally for script.tony7bones.modv2plus development.
# Usage: firetv.sh <command> [args]
#
# ⛔ TWO HAZARDS, read before running (noted 2026-07-19):
#
# 1. FIRETV_IP DEFAULTS TO 192.168.7.162, WHICH IS THE OFFICE FIRE TV, AND THAT
#    BOX IS HANDS-OFF WITHOUT EXPLICIT PER-INSTANCE OWNER PERMISSION. Running
#    any command here with no FIRETV_IP set targets it. Always set FIRETV_IP
#    explicitly.
# 2. The add-on-specific commands are DEAD. ADDON_ID is
#    script.tony7bones.modv2plus and SKIN_ID is skin.estuary.modv2, both RETIRED
#    AND DELETED at the static conversion (2026-07-15). ADDON_SRC additionally
#    resolves to <repo>/repo/<addon>, a path that has never existed in this
#    layout. So push-addon, push-xml, apply and restore cannot work.
#    The generic commands (connect, status, screencap, log, launch, stop,
#    disconnect) are unaffected and are why this script is retained.
#
# Commands:
#   connect          Connect (or reconnect) to the Fire TV
#   status           Show adb device status + Kodi add-on version
#   push-addon       Push entire add-on dir from repo to device
#   push-xml <file>  Push one patched XML directly into the live skin's xml/ dir
#   apply            Run the add-on's Apply action via JSON-RPC
#   restore          Run the add-on's Restore action via JSON-RPC
#   reload-skin      Tell Kodi to reload the skin (no restart)
#   screencap [out]  Grab a 1920x1080 PNG screenshot (default: /tmp/kodi_screen.png)
#   log [filter]     Pull kodi.log; grep for filter (default: "mod v2+")
#   launch           Force-stop then launch Kodi
#   stop             Force-stop Kodi
#   disconnect       Disconnect from Fire TV

set -euo pipefail

# ---------------------------------------------------------------------------
# Configuration — edit these if your environment differs
# ---------------------------------------------------------------------------
FIRETV_IP="${FIRETV_IP:-192.168.7.162}"
FIRETV_PORT="${FIRETV_PORT:-5555}"
FIRETV="${FIRETV_IP}:${FIRETV_PORT}"

KODI_PKG="org.xbmc.kodi"
KODI_DATA="/sdcard/Android/data/${KODI_PKG}/files/.kodi"
KODI_ADDONS="${KODI_DATA}/addons"
SKIN_ID="skin.estuary.modv2"
ADDON_ID="script.tony7bones.modv2plus"

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ADDON_SRC="${REPO_ROOT}/repo/${ADDON_ID}"

JSONRPC_URL="http://${FIRETV_IP}:8080/jsonrpc"
JSONRPC_CREDS="kodi:kodi"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
_adb() {
  adb -s "$FIRETV" "$@"
}

_rpc() {
  local payload="$1"
  curl -s --connect-timeout 5 -u "$JSONRPC_CREDS" \
    "$JSONRPC_URL" \
    -H "Content-Type: application/json" \
    -d "$payload"
  echo # newline after JSON
}

_builtin() {
  local fn="$1"
  _rpc "{\"jsonrpc\":\"2.0\",\"method\":\"GUI.ExecuteBuiltin\",\"params\":{\"function\":\"${fn}\"},\"id\":1}"
}

_require_adb() {
  if ! command -v adb &>/dev/null; then
    echo "ERROR: adb not found. Run: brew install android-platform-tools" >&2
    exit 1
  fi
}

_require_connected() {
  local state
  state=$(adb devices 2>/dev/null | grep "^${FIRETV}" | awk '{print $2}')
  if [[ "$state" != "device" ]]; then
    echo "Fire TV not connected (state: ${state:-none}). Run: firetv.sh connect" >&2
    exit 1
  fi
}

# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------
cmd_connect() {
  _require_adb
  echo "Connecting to ${FIRETV}..."
  adb start-server
  adb connect "$FIRETV"
  echo ""
  local state
  state=$(adb devices 2>/dev/null | grep "^${FIRETV}" | awk '{print $2}')
  if [[ "$state" == "unauthorized" ]]; then
    echo "WAITING FOR AUTHORIZATION: a popup appeared on the TV screen."
    echo "Go to the TV and tap Allow, then run: firetv.sh connect"
  elif [[ "$state" == "device" ]]; then
    echo "Connected. Device: $(adb -s "$FIRETV" shell getprop ro.product.model 2>/dev/null | tr -d '\r')"
  else
    echo "State: ${state:-unknown}. If offline, wake the TV and retry."
  fi
}

cmd_status() {
  _require_adb
  echo "=== adb devices ==="
  adb devices -l 2>/dev/null | grep -E "^${FIRETV}|^List"
  echo ""

  local state
  state=$(adb devices 2>/dev/null | grep "^${FIRETV}" | awk '{print $2}')
  if [[ "$state" != "device" ]]; then
    echo "Fire TV not connected (state: ${state:-none})"
    return 0
  fi

  echo "=== Kodi add-on version ==="
  _rpc "{\"jsonrpc\":\"2.0\",\"method\":\"Addons.GetAddonDetails\",\"params\":{\"addonid\":\"${ADDON_ID}\",\"properties\":[\"enabled\",\"version\"]},\"id\":1}" \
    2>/dev/null || echo "(JSON-RPC unavailable — Kodi may not be running)"
  echo ""

  echo "=== Patch state (skin .bak files) ==="
  _adb shell ls "${KODI_ADDONS}/${SKIN_ID}/xml/" 2>/dev/null | grep '\.bak$' &&
    echo "Patch is APPLIED (backup files found)" ||
    echo "Patch is NOT applied (no .bak files)"
}

cmd_push_addon() {
  _require_adb
  _require_connected
  if [[ ! -f "${ADDON_SRC}/addon.xml" ]]; then
    echo "ERROR: addon source not found at ${ADDON_SRC}" >&2
    exit 1
  fi
  local version
  version=$(grep -oP 'version="\K[^"]+' "${ADDON_SRC}/addon.xml" | head -1)
  echo "Pushing ${ADDON_ID} v${version} to device..."
  _adb push "${ADDON_SRC}/." "${KODI_ADDONS}/${ADDON_ID}/"
  echo "Done. Run 'firetv.sh reload-skin' or 'firetv.sh apply' next."
}

cmd_push_xml() {
  local fname="${1:-}"
  if [[ -z "$fname" ]]; then
    echo "Usage: firetv.sh push-xml <filename.xml>" >&2
    echo "Available:" >&2
    ls "${ADDON_SRC}/resources/xml/" 2>/dev/null >&2
    exit 1
  fi
  _require_adb
  _require_connected
  local src="${ADDON_SRC}/resources/xml/${fname}"
  local dst="${KODI_ADDONS}/${SKIN_ID}/xml/${fname}"
  if [[ ! -f "$src" ]]; then
    echo "ERROR: ${src} not found" >&2
    exit 1
  fi
  echo "Pushing ${fname} directly into live skin..."
  _adb push "$src" "$dst"
  echo "Done. Run 'firetv.sh reload-skin' to pick up the change."
}

cmd_apply() {
  echo "Running Apply on device..."
  _rpc "{\"jsonrpc\":\"2.0\",\"method\":\"Addons.ExecuteAddon\",\"params\":{\"addonid\":\"${ADDON_ID}\",\"params\":[\"apply\"]},\"id\":1}"
  echo "Reloading skin..."
  _builtin "ReloadSkin"
}

cmd_restore() {
  echo "Running Restore on device..."
  _rpc "{\"jsonrpc\":\"2.0\",\"method\":\"Addons.ExecuteAddon\",\"params\":{\"addonid\":\"${ADDON_ID}\",\"params\":[\"restore\"]},\"id\":1}"
  echo "Reloading skin..."
  _builtin "ReloadSkin"
}

cmd_reload_skin() {
  echo "Reloading skin..."
  _builtin "ReloadSkin"
}

cmd_screencap() {
  local out="${1:-/tmp/kodi_screen.png}"
  _require_adb
  _require_connected
  echo "Capturing screenshot to ${out}..."
  _adb exec-out screencap -p >"$out"
  echo "Done: $(du -h "$out" | cut -f1) — $(file "$out" | grep -oE '[0-9]+ x [0-9]+.*')"
  if command -v open &>/dev/null; then
    open "$out"
  fi
}

cmd_log() {
  local filter="${1:-mod v2+}"
  _require_adb
  _require_connected
  local logfile="/tmp/kodi_firetv.log"
  echo "Pulling kodi.log..."
  _adb pull "${KODI_DATA}/temp/kodi.log" "$logfile" 2>&1
  echo ""
  echo "=== grep: ${filter} (last 50 matches) ==="
  grep -i "$filter" "$logfile" | tail -50 || echo "(no matches for '${filter}')"
  echo ""
  echo "Full log at: ${logfile}"
}

cmd_launch() {
  _require_adb
  _require_connected
  echo "Force-stopping Kodi..."
  _adb shell am force-stop "$KODI_PKG"
  sleep 1
  echo "Launching Kodi..."
  _adb shell am start -n "${KODI_PKG}/.Splash"
}

cmd_stop() {
  _require_adb
  _require_connected
  echo "Force-stopping Kodi..."
  _adb shell am force-stop "$KODI_PKG"
}

cmd_disconnect() {
  _require_adb
  echo "Disconnecting ${FIRETV}..."
  adb disconnect "$FIRETV"
}

# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------
CMD="${1:-help}"
shift || true

case "$CMD" in
  connect) cmd_connect ;;
  status) cmd_status ;;
  push-addon) cmd_push_addon ;;
  push-xml) cmd_push_xml "${1:-}" ;;
  apply) cmd_apply ;;
  restore) cmd_restore ;;
  reload-skin) cmd_reload_skin ;;
  screencap) cmd_screencap "${1:-/tmp/kodi_screen.png}" ;;
  log) cmd_log "${1:-mod v2+}" ;;
  launch) cmd_launch ;;
  stop) cmd_stop ;;
  disconnect) cmd_disconnect ;;
  help | --help | -h)
    grep '^#   ' "$0" | sed 's/^#   /  /'
    ;;
  *)
    echo "Unknown command: ${CMD}. Run 'firetv.sh help' for usage." >&2
    exit 1
    ;;
esac
