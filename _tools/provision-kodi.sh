#!/usr/bin/env bash
#
# provision-kodi.sh — guided, notebook-driven install + bootstrap of a fresh
# Tony.7.Bones Kodi box on a Fire TV / Android device over ADB-on-network.
#
# Asks for the device NAME (not an IP), then walks you through every step:
# connect, reboot, wipe, install the Setup, run it, accept the summary,
# clean-close, reopen, and verify. See docs/playbooks/install-from-notebook.md.
#
# Usage:   _tools/provision-kodi.sh [DEVICE]
# Example: _tools/provision-kodi.sh bedroom
#
# DEVICE selects the per-device config .env.<DEVICE> in the repo root, which
# supplies the box IP and everything else. Passing an IP does NOT work: it is
# looked up as .env.192.168.7.84 and the script dies "No per-device config".
#
# ⛔ BROKEN, DO NOT RUN (noted 2026-07-19, not yet repaired). Step 4 installs
# script.module.tony7bones + script.tony7bones.bootstrap, both RETIRED AND
# DELETED at the static conversion (2026-07-15). The curl 404s and the local
# `cp -R` fails because addons/ no longer holds those dirs. Step 3 WIPES the
# box before step 4 fails, so a run leaves a wiped Kodi with nothing installed
# and the error message misattributes it to "no internet?". Repairing this to
# install repository.tony7bones only is an open item; until then the script is
# retained for its adb/scoped-storage mechanics, not for execution.
#
set -u

# --- pretty output ---------------------------------------------------------- #
if [[ -t 1 ]]; then
  B=$'\033[1m'
  G=$'\033[32m'
  Y=$'\033[33m'
  R=$'\033[31m'
  C=$'\033[36m'
  Z=$'\033[0m'
else
  B=''
  G=''
  Y=''
  R=''
  C=''
  Z=''
fi
say() { printf '%s\n' "${C}$*${Z}"; }
ok() { printf '%s\n' "${G}  ✓ $*${Z}"; }
warn() { printf '%s\n' "${Y}  ! $*${Z}"; }
die() {
  printf '%s\n' "${R}  ✗ $*${Z}" >&2
  exit 1
}
step() { printf '\n%s\n' "${B}━━ $* ━━${Z}"; }
ask() {
  local p="$1" d="${2:-}" a
  read -r -p "${B}$p${Z} " a
  printf '%s' "${a:-$d}"
}
pause() { read -r -p "${B}$1${Z} "; }
confirm() {
  local a
  a=$(ask "$1 [y/N]")
  [[ "$a" == [yY]* ]]
}

# --- constants -------------------------------------------------------------- #
PKG="org.xbmc.kodi"
K="/sdcard/Android/data/${PKG}/files/.kodi"
RAW="https://raw.githubusercontent.com/tony7bones/tony7bones.github.io/main/addons"

command -v adb >/dev/null 2>&1 || die "adb not found. Install it: brew install android-platform-tools"

# --- load the owner's master .env ------------------------------------------- #
# Provides defaults (DEVICE_IP / DEVICE_NAME / KODI_WEB_* / SETTINGS_LEVEL) and is
# the source we derive the per-device tony7bones.env from (pushed to the box;
# absent .env -> built-in defaults, exactly like the bootstrap's own fallback).
# Per-device DERIVED env path on the box (matches the bootstrap's BOX_ENV_PATH;
# read then REMOVED by the bootstrap so its secrets don't linger). N1.1: the
# DERIVED push + the IPTV staging live under the STAGING tree
# /storage/emulated/0/_T7B/kodi/ (the old kodi/tony.7.bones/ root is a read-only
# legacy fallback — never push there). NOTE: this is the machine-derived push
# ONLY. The owner's PERSISTENT MASTER env lives ONE LEVEL UP at the BRAND ROOT
# /storage/emulated/0/_T7B/env.<device> (no leading dot) — placed by hand, never
# pushed or deleted by this script or the bootstrap; the bootstrap scans the
# brand root FIRST, then this staging tree, then the legacy root.
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEVICE_ROOT="/storage/emulated/0/_T7B/kodi"
BOX_ENV_PATH="$DEVICE_ROOT/tony7bones.env"
# USE_LOCAL=1 pushes the WORKING-TREE add-ons instead of fetching from the live
# site (main) — required to verify a feature branch on the box BEFORE merging.
USE_LOCAL="${USE_LOCAL:-}"
# First arg selects the per-device config .env.<device> (e.g. shield, bedroom,
# travelstick). The box IP + name + shared config all come from that one file.
_devices() { ls "$REPO_ROOT"/.env.* 2>/dev/null | sed 's|.*/\.env\.||' | grep -v '^example$' | tr '\n' ' '; }
DEVICE="${1:-}"
[[ -n "$DEVICE" ]] || DEVICE=$(ask "Which device? (have: $(_devices)):")
ENV_FILE="$REPO_ROOT/.env.$DEVICE"
[[ -f "$ENV_FILE" ]] || die "No per-device config .env.$DEVICE (have: $(_devices))"
# shellcheck disable=SC1090
source "$ENV_FILE"
# Settings level (Standard|Advanced|Expert) -> Kodi's <settinglevel> 1|2|3.
case "$(printf '%s' "${SETTINGS_LEVEL:-expert}" | tr '[:upper:]' '[:lower:]')" in
  standard | basic) SL=1 ;;
  advanced) SL=2 ;;
  *) SL=3 ;;
esac
# Kodi data dir comes from the per-device file (KODI_DATA_PATH). When it points
# OUTSIDE Android/data — a Fire OS 11 Stick where adb is locked out of the app
# sandbox — we RELOCATE Kodi's data there via /sdcard/xbmc_env.properties (the
# Jocala/adbLink method) so the entire adb push/wipe/seed flow works normally.
K="${KODI_DATA_PATH:-$K}"
RELOCATE=""
[[ "$K" == *Android/data* ]] || RELOCATE=1

# --- 0. device IP ----------------------------------------------------------- #
clear 2>/dev/null || true
say "${B}Tony.7.Bones — Kodi box provisioner${Z}"
say "Provisions a FRESH box: wipe → install → run Setup → reopen → verify."
say "Make sure ADB debugging is ON at the TV (Settings → My Fire TV → Developer options)."
IP="${DEVICE_IP:-}"
[[ -n "$IP" ]] || IP=$(ask "DEVICE_IP missing from .env.$DEVICE — enter the box IP:")
[[ "$IP" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]] || die "That doesn't look like an IP: '$IP'"
D="$IP:5555"
# Device name (shown to phone remotes) comes straight from the per-device file.
DEVNAME="${DEVICE_NAME:-Kodi}"
DEVNAME="${DEVNAME//&/and}" # keep it XML-safe in guisettings.xml
DEVNAME="${DEVNAME//</}"
DEVNAME="${DEVNAME//>/}"
DEVNAME="${DEVNAME//\"/}"

# NB: </dev/null on every adb call — `adb shell` otherwise drains the script's
# stdin, eating queued prompt answers (breaks non-interactive/automated runs).
_adb() { adb -s "$D" "$@" </dev/null; }
rpc() { curl -s -m 6 -H 'Content-Type: application/json' -d "$1" "http://$IP:${KODI_WEB_PORT:-8080}/jsonrpc" 2>/dev/null; }
kodi_up() { rpc '{"jsonrpc":"2.0","method":"JSONRPC.Ping","id":1}' | grep -q pong; }
kodi_running() { _adb shell 'pidof '"$PKG"' >/dev/null' 2>/dev/null; }

# --- 1. connect ------------------------------------------------------------- #
step "1/8  Connect to $D"
adb connect "$D" </dev/null >/dev/null 2>&1
sleep 1
MODEL=$(_adb shell 'getprop ro.product.model' 2>/dev/null | tr -d '\r')
if [[ -z "$MODEL" ]]; then
  warn "Couldn't reach the device. If the TV shows an 'Allow USB debugging?' prompt,"
  warn "check 'Always allow' and accept it, then press Enter to retry."
  pause "Press Enter to retry…"
  adb connect "$D" </dev/null >/dev/null 2>&1
  sleep 1
  MODEL=$(_adb shell 'getprop ro.product.model' 2>/dev/null | tr -d '\r')
  [[ -n "$MODEL" ]] || die "Still can't reach $D. Check the IP and ADB debugging."
fi
ok "Connected: $MODEL ($D)"

# --- 2. reboot device (clears any GPU wedge) -------------------------------- #
step "2/8  Reboot the device (recommended — clears any wedged graphics state)"
if confirm "Reboot the TV now?"; then
  _adb reboot >/dev/null 2>&1
  printf '  waiting for it to come back'
  _adb wait-for-device 2>/dev/null
  for _ in $(seq 1 40); do
    [[ "$(_adb shell 'getprop sys.boot_completed' 2>/dev/null | tr -d '\r')" == 1 ]] && break
    printf '.'
    sleep 5
  done
  printf '\n'
  sleep 10
  ok "Rebooted."
else
  warn "Skipped reboot (if Kodi crashes on launch later, re-run and reboot)."
fi

# --- 3. wipe Kodi ----------------------------------------------------------- #
step "3/8  Wipe Kodi clean"
warn "This ERASES the Kodi profile on $MODEL (add-ons, settings, everything)."
confirm "Wipe Kodi now?" || die "Aborted before any changes."
_adb shell "am force-stop $PKG" >/dev/null 2>&1
sleep 2
# Fire OS relocation (KODI_DATA_PATH points outside Android/data): tell Kodi to use
# the writable dir via /sdcard/xbmc_env.properties + grant all-files access, so the
# wipe/seed/push below land where Kodi actually reads them (Jocala/adbLink method).
if [[ -n "$RELOCATE" ]]; then
  _adb shell "printf 'xbmc.data=%s\n' '$(dirname "$K")' > /sdcard/xbmc_env.properties" >/dev/null 2>&1
  _adb shell "cmd appops set --uid $PKG MANAGE_EXTERNAL_STORAGE allow" >/dev/null 2>&1
  warn "Fire OS scoped storage -> relocated Kodi data to $(dirname "$K") (xbmc_env.properties)."
fi
_adb shell "rm -rf $K && mkdir -p $K/userdata $K/addons" >/dev/null 2>&1
# Seed guisettings: web server on (so we can drive Kodi headless), the remote-
# control block (kodi/kodi, auth OFF, SSL off, remote control from this AND other
# systems on — for phone remotes like Kore/Yatse), the device name, and the
# Expert settings level (<settinglevel>3</settinglevel> lives under <general>).
printf '<settings version="2"><setting id="services.devicename">%s</setting><setting id="services.webserver">true</setting><setting id="services.webserverport">%s</setting><setting id="services.webserverusername">%s</setting><setting id="services.webserverpassword">%s</setting><setting id="services.webserverauthentication">false</setting><setting id="services.webserverssl">false</setting><setting id="services.esenabled">true</setting><setting id="services.esallinterfaces">true</setting><setting id="addons.unknownsources">true</setting><setting id="addons.updatemode">1</setting></settings>' "$DEVNAME" "${KODI_WEB_PORT:-8080}" "${KODI_WEB_USER:-kodi}" "${KODI_WEB_PASS:-kodi}" >/tmp/_t7b_gs.xml
_adb push /tmp/_t7b_gs.xml "$K/userdata/guisettings.xml" >/dev/null 2>&1
# pre-grant storage so Kodi doesn't pop a permissions prompt at the TV after the
# data wipe (Android-9 runtime grants reset on data clear). The appops line covers
# Android 11+ sticks (MANAGE_EXTERNAL_STORAGE) and is a harmless no-op on older ones.
_adb shell "pm grant $PKG android.permission.READ_EXTERNAL_STORAGE" 2>/dev/null
_adb shell "pm grant $PKG android.permission.WRITE_EXTERNAL_STORAGE" 2>/dev/null
_adb shell "appops set $PKG MANAGE_EXTERNAL_STORAGE allow" 2>/dev/null
ok "Wiped. Seeded: web server (user ${KODI_WEB_USER:-kodi}, port ${KODI_WEB_PORT:-8080}, remote control on), device name \"$DEVNAME\", storage granted."

# --- 4. install the Setup add-ons from the live site ------------------------ #
step "4/8  Install the Setup (from the live site)"
ver() { curl -s -m 15 "$RAW/$1/addon.xml" | grep -oE 'version="[0-9]+\.[0-9]+\.[0-9]+"' | grep -oE '[0-9]+\.[0-9]+\.[0-9]+' | head -1; }
MV=$(ver script.module.tony7bones)
BV=$(ver script.tony7bones.bootstrap)
PV=$(ver repository.tony7bones)
[[ -n "$MV" && -n "$BV" ]] || die "Couldn't resolve versions from the live site (no internet?)."
say "  library=$MV  setup=$BV  repo=${PV:-?} — fetching…"
T=$(mktemp -d)
trap 'rm -rf "$T"' EXIT
curl -s -o "$T/m.zip" "$RAW/script.module.tony7bones/script.module.tony7bones-$MV.zip"
curl -s -o "$T/b.zip" "$RAW/script.tony7bones.bootstrap/script.tony7bones.bootstrap-$BV.zip"
(cd "$T" && unzip -oq m.zip && unzip -oq b.zip)
if [[ -n "$USE_LOCAL" ]]; then
  # Pre-merge verification: push the WORKING-TREE add-ons, not the live-site ones.
  rm -rf "$T/script.module.tony7bones" "$T/script.tony7bones.bootstrap"
  cp -R "$REPO_ROOT/addons/script.module.tony7bones" \
    "$REPO_ROOT/addons/script.tony7bones.bootstrap" "$T/"
  warn "USE_LOCAL: pushing the working-tree add-ons (pre-merge test, not main)."
fi
_adb push "$T/script.module.tony7bones" "$K/addons/" >/dev/null 2>&1
_adb push "$T/script.tony7bones.bootstrap" "$K/addons/" >/dev/null 2>&1
# the virtual proxy repository (Tony.7.Bones Repo) — so the box can browse/update
# add-ons from our repo + self-update. Non-fatal if it can't be resolved.
if [[ -n "$PV" ]] && curl -s -f -o "$T/r.zip" "$RAW/repository.tony7bones/repository.tony7bones-$PV.zip"; then
  (cd "$T" && unzip -oq r.zip)
  _adb push "$T/repository.tony7bones" "$K/addons/" >/dev/null 2>&1
  ok "Tony.7.Bones Repo $PV installed."
else
  warn "Couldn't install the proxy repo (repository.tony7bones) — non-fatal, box still works."
fi
_adb shell "ls $K/addons/script.module.tony7bones/lib/tony7bones/system.py" >/dev/null 2>&1 ||
  die "Library didn't land correctly. Re-run (the wipe creates addons/ up front)."
ok "Setup $BV + library $MV installed."

# --- 4b. establish the canonical on-device tree ----------------------------- #
# The five subdirs are the canonical layout (docs/directory_structure.txt) and
# match DEVICE_STAGING_SUBDIRS in tony7bones.setup.env: onboarding self-creates
# the SAME tree in-Kodi (ensure_device_dirs), so this is belt-and-suspenders for
# the computer path. Survives the Kodi wipe above (lives outside the Kodi data
# dir). Idempotent.
#
# NOTE: the old v1 host-build-and-stage IPTV step (Phase 5b.2: build_iptv.py ->
# per-box staged artifacts consumed by apply_iptv) was RETIRED. The IPTV builder
# was extracted to its own private repo (moquette/iptv) and the fleet moved to
# the IPTV 2.0 share model: the Mac mini builds centrally and writes to an NFS
# share that each box reads directly, so no per-box host build happens here.
# IPTV_STAGED stays empty; the per-device env below omits IPTV_STAGING_DIR.
_adb shell "mkdir -p $DEVICE_ROOT/backups $DEVICE_ROOT/iptv $DEVICE_ROOT/media $DEVICE_ROOT/repositories $DEVICE_ROOT/rss" >/dev/null 2>&1

IPTV_STAGED=""

# --- 4c. push the per-device config (derived from the master .env) ---------- #
# Drop DEVICE_IP (laptop-only connection metadata) and override DEVICE_NAME with
# the prompted value. The bootstrap reads this for weather/IPTV/RSS during the
# run, then REMOVES it. Absent .env -> nothing pushed -> bootstrap uses defaults.
if [[ -f "$ENV_FILE" ]]; then
  grep -v '^[[:space:]]*DEVICE_IP=' "$ENV_FILE" |
    sed "s|^DEVICE_NAME=.*|DEVICE_NAME=\"$DEVNAME\"|" >/tmp/_t7b_env
  # Point the in-Kodi half at the staged artifacts — ONLY when they landed.
  [[ -n "$IPTV_STAGED" ]] && printf 'IPTV_STAGING_DIR="%s"\n' "$IPTV_STAGED" >>/tmp/_t7b_env
  _adb shell "mkdir -p $(dirname "$BOX_ENV_PATH")" >/dev/null 2>&1
  if _adb push /tmp/_t7b_env "$BOX_ENV_PATH" >/dev/null 2>&1; then
    ok "Per-device config pushed (weather + IPTV + RSS from .env)."
  else
    # Phase N1: a box with NO env now launches the GUIDED WIZARD (the
    # no-computer route) — and this script's auto-dismiss would blindly press
    # the wizard's first item. Aborting before the Setup launch is the honest
    # move (it always was: the old silent "built-in defaults" run shipped a
    # generic box that served nobody). Fix the adb/storage issue and re-run.
    rm -f /tmp/_t7b_env
    die "Couldn't push the per-device env to $BOX_ENV_PATH — aborting BEFORE launching Setup (a no-env launch opens the Guided wizard, which this unattended script must not drive). Fix the push and re-run."
  fi
  rm -f /tmp/_t7b_env
else
  # Unreachable in practice (the script dies at startup without .env.<device>),
  # but keep the guard honest: never launch Setup env-less from this script.
  die "No local .env — refusing to launch Setup without a per-device env (the no-env launch is the interactive Guided wizard)."
fi

# --- 5. launch + enable ----------------------------------------------------- #
step "5/8  Launch Kodi + enable the Setup"
_launch_wait() { # poll kodi_up for ~($1*3)s after a launch; return 0 once up
  printf '  starting Kodi'
  for _ in $(seq 1 "$1"); do
    kodi_up && {
      printf '\n'
      return 0
    }
    printf '.'
    sleep 3
  done
  printf '\n'
  return 1
}
_adb shell "monkey -p $PKG -c android.intent.category.LAUNCHER 1" >/dev/null 2>&1
if ! _launch_wait 50 && [[ -n "$RELOCATE" ]]; then
  # Relocated Fire OS stick: the FIRST launch on a fresh profile bounces to the
  # all-files-access settings (ApplicationsActivity) and Kodi never finishes
  # starting — the appops grant is already set, the stuck settings task is the
  # only blocker. Clear it + relaunch. (playbook: firetv-stick-scoped-storage-*)
  warn "First launch stalled on the Fire OS all-files-access bounce — clearing + retrying."
  _adb shell "am force-stop com.amazon.tv.settings.v2" >/dev/null 2>&1
  _adb shell "am force-stop $PKG" >/dev/null 2>&1
  sleep 2
  _adb shell "monkey -p $PKG -c android.intent.category.LAUNCHER 1" >/dev/null 2>&1
  _launch_wait 50 || true
fi
kodi_up || die "Kodi didn't come up. Reboot the device and try again."
for a in script.module.tony7bones script.tony7bones.bootstrap repository.tony7bones; do
  rpc "{\"jsonrpc\":\"2.0\",\"method\":\"Addons.SetAddonEnabled\",\"params\":{\"addonid\":\"$a\",\"enabled\":true},\"id\":1}" >/dev/null
done
ok "Kodi up, Setup enabled."

# --- 6. run the one-tap Setup ----------------------------------------------- #
step "6/8  Run the one-tap Setup"
rpc '{"jsonrpc":"2.0","method":"Addons.ExecuteAddon","params":{"addonid":"script.tony7bones.bootstrap"},"id":1}' >/dev/null
say "  ${B}Installing${Z} (12 repos, apps, video, skin + patch) — ~3–4 min. Watching, no action needed."
# Auto-detect install completion: the skin lands + the add-on count goes stable.
# Also watch for recurring network errors (the library now retries, but flag it).
_prev=-1
_stable=0
_done=0
_net=0
for _i in $( # up to ~9 min
  seq 1 90
); do
  sleep 6
  _cnt=$(_adb shell "ls $K/addons/ 2>/dev/null | wc -l" | tr -d '\r')
  _ne=$(_adb shell "grep -ac 'connection abort\|urlopen error' $K/temp/kodi.log 2>/dev/null" | tr -d '\r')
  [[ "${_ne:-0}" -gt "$_net" ]] 2>/dev/null && {
    _net="$_ne"
    warn "transient network error on a download (library auto-retries)"
  }
  if _adb shell "ls -d $K/addons/skin.estuary.modv2 >/dev/null 2>&1"; then
    [[ "$_cnt" == "$_prev" ]] && _stable=$((_stable + 1)) || _stable=0
    [[ "$_stable" -ge 2 ]] && {
      _done=1
      break
    }
  fi
  _prev="$_cnt"
  printf '\r  installing… %s add-ons ' "${_cnt:-?}"
done
printf '\n'
[[ "$_done" == 1 ]] && ok "Install complete." || warn "Install didn't clearly finish — continuing; verify at the end."
# Auto-dismiss the summary (a blocking ok() dialog); retry until run() moves past it.
sleep 2
for _ in 1 2 3 4; do
  rpc '{"jsonrpc":"2.0","method":"Input.Select","id":1}' >/dev/null # click OK
  _moved=0
  for _ in $(seq 1 10); do
    _adb shell "grep -aq 'activate_skin\|clean Quit' $K/temp/kodi.log" 2>/dev/null && {
      _moved=1
      break
    }
    kodi_running || {
      _moved=1
      break
    }
    sleep 2
  done
  [[ "$_moved" == 1 ]] && break
  sleep 3
done
ok "Summary accepted — Setup is finishing (skin activate + clean close)."
printf '  waiting for Kodi to close itself'
# Up to ~4 min: on a real Fire TV the post-summary terminal seam is SLOW — the
# first-ever MOD V2 load + script.skinshortcuts' first menu build (>14 s cold,
# and activate_skin now deliberately WAITS the build out between re-asserts) +
# the keep-skin dance + the close notice all run before the clean Quit. The old
# 60 s bound expired mid-dance on a real Stick and the forced REBOOT below
# killed Kodi before the clean shutdown flushed lookandfeel.skin — a stock-skin
# box. The reboot is a last resort; give the dance the time it actually needs.
for _ in $(seq 1 80); do
  kodi_running || break
  printf '.'
  sleep 3
done
printf '\n'
if kodi_running; then
  # The Setup's Quit didn't take (a busy/hung skin switch can swallow it). Force a
  # clean restart via a DEVICE reboot — a Kodi-only force-stop can leave a wedged
  # GPU that crash-loops; only a device reboot reliably clears it.
  warn "Kodi didn't self-close — forcing a clean restart (stop + device reboot)."
  _adb shell "am force-stop $PKG" >/dev/null 2>&1
  sleep 2
  _adb reboot >/dev/null 2>&1
  _adb wait-for-device 2>/dev/null
  for _ in $(seq 1 40); do
    [[ "$(_adb shell 'getprop sys.boot_completed' 2>/dev/null | tr -d '\r')" == 1 ]] && break
    sleep 5
  done
  sleep 10
  ok "Device rebooted — clean state for the reopen."
else
  ok "Kodi closed cleanly — no force-kill needed."
fi
SKIN_SET=$(_adb shell "grep lookandfeel.skin\\\" $K/userdata/guisettings.xml" 2>/dev/null | tr -d '\r')
if grep -q 'skin.estuary.modv2' <<<"$SKIN_SET"; then
  ok "Skin persisted as MOD V2 (did not revert to stock Estuary)."
else
  warn "Skin in guisettings: ${SKIN_SET:-<none>} — expected skin.estuary.modv2."
fi

# --- 7. reopen — the box finishes itself ------------------------------------ #
step "7/8  Reopen Kodi (the box finishes itself)"
pause "→ Press Enter to reopen Kodi…"
# Expert settings level: a fresh-profile seed resets to Standard on first boot, so
# set it on the now-established guisettings right before the final boot — it sticks.
_adb shell "sed -i 's|<settinglevel>[0-9]*</settinglevel>|<settinglevel>$SL</settinglevel>|' $K/userdata/guisettings.xml" >/dev/null 2>&1
_adb shell "am start -n $PKG/.Splash" >/dev/null 2>&1
printf '  booting MOD V2 + applying patch + menu'
built=0
for _ in $(seq 1 48); do
  pov=$(_adb shell "grep -c plugin.video.pov $K/addons/skin.estuary.modv2/xml/script-skinshortcuts-includes.xml 2>/dev/null" | tr -dc '0-9')
  mark=$(_adb shell "grep -c show_system_info_overlay $K/addons/skin.estuary.modv2/xml/Home.xml 2>/dev/null" | tr -dc '0-9')
  if [[ "${pov:-0}" -ge 1 && "${mark:-0}" -ge 1 ]]; then
    built=1
    break
  fi
  printf '.'
  sleep 5
done
printf '\n'
[[ "$built" == 1 ]] && ok "Menu built (POV) + patch applied." || warn "Patch/menu not detected in time — verifying anyway."

# --- 8. verify -------------------------------------------------------------- #
step "8/8  Verify the box"
for _ in $(seq 1 20); do
  kodi_up && break
  sleep 3
done
GUI=$(rpc '{"jsonrpc":"2.0","method":"GUI.GetProperties","params":{"properties":["skin","currentwindow"]},"id":1}')
# weather.multi resolves a few seconds after boot (returns "Busy" mid-fetch),
# so poll up to ~30s for the location instead of flagging a transient "Busy".
WEATHER=""
for _ in $(seq 1 10); do
  WEATHER=$(rpc '{"jsonrpc":"2.0","method":"XBMC.GetInfoLabels","params":{"labels":["Weather.Location"]},"id":1}')
  grep -q 'Sacramento' <<<"$WEATHER" && break
  sleep 3
done
MARK=$(_adb shell "grep -c show_system_info_overlay $K/addons/skin.estuary.modv2/xml/Home.xml" 2>/dev/null | tr -d '\r')
FOCUS=$(_adb shell "grep -ac 'Control 9000 in window 10000' $K/temp/kodi.log" 2>/dev/null | tr -d '\r')
grep -q 'skin.estuary.modv2' <<<"$GUI" && ok "Active skin: Estuary MOD V2" || warn "Skin not MOD V2: $GUI"
grep -q '"id":10000' <<<"$GUI" && ok "Home window is up (10000)" || warn "Not on Home: $GUI"
[[ "$MARK" == 1 ]] && ok "MOD V2+ patch applied" || warn "Patch marker: ${MARK:-?}"
[[ "$FOCUS" == 0 ]] && ok "Home renders (0 focus errors)" || warn "Focus errors: ${FOCUS} (give it another reopen)"
grep -q 'Sacramento' <<<"$WEATHER" && ok "Weather: Sacramento" || warn "Weather: $WEATHER"
if confirm "Grab a screenshot of the home screen?"; then
  _adb shell screencap -p /sdcard/_t7b_home.png >/dev/null 2>&1
  _adb pull /sdcard/_t7b_home.png /tmp/_t7b_home.png >/dev/null 2>&1 && { open /tmp/_t7b_home.png 2>/dev/null || say "  saved /tmp/_t7b_home.png"; }
fi

echo
say "${B}${G}Done.${Z} ${C}If anything looks off, see docs/playbooks/install-from-notebook.md → Troubleshooting.${Z}"
say "${C}One-time manual steps still needed at the TV: hide the PVR \"All channels\" group, and TV → Options → Sort by Name.${Z}"
