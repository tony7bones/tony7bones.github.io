# Apple TV (tvOS) Kodi troubleshooting over the Xcode CLI

Apple TV has **no adb** and (on 4K models) **no data USB port** — everything here is
over Wi-Fi from a Mac (or, for the `pymobiledevice3` path, any host including Linux).
This is the tvOS equivalent of `adb logcat` + `adb pull`, used to prove/verify the
EZ Maintenance++ restore bug (see `ezm-restore-hardening.md` and the
`ezm-backup-doctor` skill).

## Why this exists (the bug being proven)

Per the **Kodi Wiki** ([TvOS](https://kodi.wiki/view/TvOS),
[Userdata](https://kodi.wiki/view/Userdata)): a tvOS app gets only ~500 KB of normal
app-directory storage, so Kodi **mirrors its settings into the app's NSUserDefaults**
(a binary plist) and **rewrites the on-disk `userdata` files from that mirror on
launch**. Consequences:

- A **file-only restore reverts** on the next (often unclean, swipe-to-quit) relaunch.
- Only settings pushed **through Kodi** (JSON-RPC `Settings.SetSettingValue` /
  `xbmcaddon.Addon().setSetting()`) also update the mirror and therefore survive.
- Add-on settings written only as files (`addon_data/<id>/settings.xml`) are lost.

**The fingerprint if the hypothesis holds:** on-disk `guisettings.xml` (and
`addon_data/<id>/settings.xml`) change AFTER a restore but **revert AFTER a
force-quit+relaunch**, while the NSUserDefaults plist
`Library/Preferences/<bundle-id>.plist` holds the OLD (pre-restore) values and the boot
log shows Kodi writing settings back from that mirror.

## How I (the agent) use the output

You run these on your Mac on the home LAN; paste the log lines and the `diff`/`plutil`
output back to me and I interpret them. Three snapshots — **A** (before restore),
**B** (after restore, before relaunch), **C** (after force-quit + reopen) — prove the
bug (`B` has the restored values, `C` reverts to `A`). The same `A` vs `C` later
**verifies a fix** (a correct fix makes `C == B`).

---

## 0. Prereqs

```bash
xcode-select -p                 # Xcode toolchain present (provides xcrun devicectl)
xcrun devicectl --version       # CoreDevice CLI (Xcode 15+; replaced instruments/ideviceinstaller)
log --help | head -5            # /usr/bin/log = the unified log

export ATV_UDID="…"             # from step 1 (xcrun devicectl list devices)
export BUNDLE="org.xbmc.kodi"   # YOUR sideloaded/resigned Kodi bundle id (may be custom!)
export USERR="mobile"           # devicectl container user (iOS-documented; tvOS UNVERIFIED)
export OUT="$HOME/kodi-atv-debug"; mkdir -p "$OUT"
export KODI_HOME="Documents"    # CANDIDATE — resolve empirically in step 3a before trusting
```

Mac + Apple TV must be on the **same Wi-Fi** (no guest/IoT VLAN, no AP/client isolation).

## 1. Pair + discover the device

On the ATV: **Settings → Remotes and Devices → Remote App and Devices** (leave open).

```bash
xcrun devicectl list devices                  # note Name + Identifier(UDID); set ATV_UDID
xcrun devicectl manage pair --device "$ATV_UDID"   # confirm the code shown on the TV
xcrun devicectl device info apps --device "$ATV_UDID" | grep -i kodi   # confirm $BUNDLE
```

**Developer Mode** (tvOS 16+) is required to *launch* dev-signed builds and to access the
container; the toggle appears only after the first pairing / dev-signed launch. On tvOS
it's driven by the pairing flow rather than an obvious Settings switch
(*exact tvOS UI: partially unverified — confirm on-device*).

## 2. Log capture (the behavioral proof) — the `adb logcat` equivalent

Add `--info --debug` (or `--level debug`) always — Kodi's info/debug lines are hidden by
default. If a marker still won't show, temporarily raise the add-on's line to
`xbmc.LOGWARNING`, or enable Kodi debug logging.

### 2a. Apple `log` (primary on macOS)

```bash
# Live stream across restore → quit → reopen (survives the app restart; filters by process):
log stream --device-udid "$ATV_UDID" \
  --predicate 'process == "Kodi" OR senderImagePath CONTAINS[c] "kodi"' \
  --level debug --style compact | tee "$OUT/live.log"

# Or capture an archive and grep it offline (most reliable on tvOS 17+):
sudo log collect --device-udid "$ATV_UDID" --last 5m --output "$OUT/atv.logarchive"
log show --archive "$OUT/atv.logarchive" \
  --predicate 'process == "Kodi" OR process CONTAINS[c] "kodi"' --info --debug \
  | grep -Ei 'apply_guisettings|settings applied|EZ Maintenance|guisettings|restore|boot'
```

Predicate keys you can mix: `process`, `processImagePath`, `senderImagePath`,
`subsystem`, `category`, `eventMessage CONTAINS "apply_guisettings"`.
*NOTE: live `log stream --device-udid` over a wireless-only tvOS 17+ pairing is not
guaranteed; if it stalls, use repeated `log collect` snapshots or pymobiledevice3 (§5).*

### 2b. Classic fallbacks (may not attach on tvOS 17/18 — UNVERIFIED)

```bash
git clone https://github.com/rpetrich/deviceconsole && (cd deviceconsole && make)
./deviceconsole/deviceconsole -u "$ATV_UDID" | grep -iE 'kodi|guisettings|EZ Maintenance'

brew install libimobiledevice
idevicesyslog -u "$ATV_UDID" -m "Kodi"
```

## 3. Pull the three artifacts (the `adb pull` equivalent)

`devicectl` exposes ONLY the app data container (dev-signed apps only; your sideload
qualifies). It is not a general filesystem browser.

```bash
# 3a. Enumerate the container to find the real userdata path, then fix KODI_HOME:
xcrun devicectl device info files --device "$ATV_UDID" \
  --domain-type appDataContainer --domain-identifier "$BUNDLE" --username "$USERR"

# 3b. Pull guisettings.xml, an add-on settings.xml, and the NSUserDefaults plist:
for SRC_DST in \
  "$KODI_HOME/userdata/guisettings.xml:$OUT/guisettings.xml" \
  "$KODI_HOME/userdata/addon_data/script.ezmaintenanceplusplus/settings.xml:$OUT/ezm.settings.xml" \
  "Library/Preferences/$BUNDLE.plist:$OUT/prefs.plist" ; do
  xcrun devicectl device copy from --device "$ATV_UDID" --user "$USERR" \
    --domain-type appDataContainer --domain-identifier "$BUNDLE" \
    --source "${SRC_DST%%:*}" --destination "${SRC_DST##*:}" || true
done
xcrun devicectl device copy from --help   # confirm exact flags for your Xcode
```

**GUI fallback (most reliable when the in-container path is unknown):** Xcode →
**Window → Devices and Simulators** → the ATV → Installed Apps → Kodi → gear ⚙︎ →
**Download Container…** → it saves `Kodi ….xcappdata` (a bundle). Then
`find "Kodi ….xcappdata/AppData" -name guisettings.xml` and
`… -path '*addon_data/*settings.xml'` to learn the paths; the NSUserDefaults plist is
at `AppData/Library/Preferences/<bundle-id>.plist`.
**Never** pass `--remove-existing-content true` to `devicectl device copy to` — reported
to wipe the entire container.

## 4. Decode + diff (the mechanism proof)

```bash
plutil -p "$OUT/prefs.plist" | grep -iE 'weather|location|skin|guisettings'  # binary plist → readable
grep -iE 'weather|location|skin' "$OUT/guisettings.xml"

# Across the three snapshots:
diff -u  A/guisettings.xml C/guisettings.xml   # restore reverted on relaunch?
diff -ru A/addon_data      C/addon_data        # add-on settings vanished?
diff -u  A/prefs.txt       C/prefs.txt         # did the mirror ever absorb the restore?
```

Interpretation: `B` shows restored values on disk (write succeeded); `C` shows them
reverted from the mirror = the bug. A correct fix makes `C == B`.

## 5. Cross-platform fallback — `pymobiledevice3` (macOS AND Linux)

Use when the host is Linux, or the macOS `log`/`devicectl` paths stall on tvOS 17+.

```bash
python3 -m pip install -U pymobiledevice3

# tvOS 17+ requires the RemoteXPC tunnel BEFORE any dev service:
python3 -m pymobiledevice3 remote pair                 # trust (confirm on TV)
sudo python3 -m pymobiledevice3 remote tunneld         # TUN interface → needs sudo; prints --rsd HOST PORT
python3 -m pymobiledevice3 amfi enable-developer-mode  # if needed, headless
python3 -m pymobiledevice3 mounter auto-mount

# Logs (cross-platform equivalent of §2):
python3 -m pymobiledevice3 syslog live -m Kodi         # add --rsd HOST PORT if not using tunneld

# Apps + container files (house-arrest; dev-signed apps only):
python3 -m pymobiledevice3 apps list                   # confirm $BUNDLE installed/dev-signed
python3 -m pymobiledevice3 apps pull "$BUNDLE" "$KODI_HOME/userdata/guisettings.xml" "$OUT/guisettings.xml"
python3 -m pymobiledevice3 apps pull "$BUNDLE" "Library/Preferences/$BUNDLE.plist" "$OUT/prefs.plist"
python3 -m pymobiledevice3 apps afc  "$BUNDLE"          # interactive ls/pull to enumerate addon_data/*
python3 -m pymobiledevice3 crash pull "$OUT/crashes"    # distinguish "boot rewrite" from a crash-on-launch
```

## 6. End-to-end proof / verify script (macOS `devicectl`)

```bash
#!/usr/bin/env bash
set -euo pipefail   # requires the §0 exports
snap () {  # $1 = phase label
  local d="$OUT/$1"; mkdir -p "$d"
  for SRC_DST in \
    "$KODI_HOME/userdata/guisettings.xml:$d/guisettings.xml" \
    "$KODI_HOME/userdata/addon_data/script.ezmaintenanceplusplus/settings.xml:$d/ezm.settings.xml" \
    "Library/Preferences/$BUNDLE.plist:$d/prefs.plist" ; do
    xcrun devicectl device copy from --device "$ATV_UDID" --user "$USERR" \
      --domain-type appDataContainer --domain-identifier "$BUNDLE" \
      --source "${SRC_DST%%:*}" --destination "${SRC_DST##*:}" || true
  done
  plutil -p "$d/prefs.plist" > "$d/prefs.txt" 2>/dev/null || true
  echo "snapshot: $1"
}
snap 01-before
log stream --device-udid "$ATV_UDID" \
  --predicate 'process == "Kodi" OR senderImagePath CONTAINS[c] "kodi"' \
  --level debug --style compact > "$OUT/live.log" 2>&1 & LOGPID=$!
read -r -p ">>> Run the restore in Kodi now, then press Enter..."
snap 02-after-restore
read -r -p ">>> Force-quit Kodi (double-press TV/Home, swipe up), reopen it, then press Enter..."
snap 03-after-relaunch
kill "$LOGPID" 2>/dev/null || true
echo "=== guisettings: after-restore vs after-relaunch ==="; diff -u "$OUT/02-after-restore/guisettings.xml" "$OUT/03-after-relaunch/guisettings.xml" || true
echo "=== plist mirror: before vs after-restore ==="; diff -u "$OUT/01-before/prefs.txt" "$OUT/02-after-restore/prefs.txt" || true
echo "=== boot write-back evidence ==="; grep -iE 'apply_guisettings|settings applied|EZ Maintenance' "$OUT/live.log" || true
```

Proves: `02→03` guisettings reverts to pre-restore → file overwritten on boot; `prefs.plist`
unchanged by the restore but matching the reverted `03` → the plist is the source of truth;
`live.log` shows Kodi's boot write. A fix flips it: `02 == 03`.

## 7. Gotchas (tvOS 17/18, 2025-2026)

1. **Free-account 7-day resign.** A free Apple ID signs the sideload for only 7 days; after
   expiry it won't launch and its container is inaccessible until re-signed (data survives).
   Free tier caps 3 sideloaded apps. Do the whole proof inside one signing window.
2. **Developer Mode mandatory** (tvOS 16+); dev-signed app installs but won't launch without it.
3. **Wireless-only** on Apple TV 4K; keep both devices awake, same subnet, no VPN/firewall
   blocking Bonjour/CoreDevice.
4. **Trust/pairing lapses** on sleep, IP change, reboot, or OS update — re-run `manage pair` /
   `remote pair` when commands report "not paired/trusted".
5. **tvOS 17 tunnel.** macOS `log`/`devicectl` handle it internally; `pymobiledevice3` and
   reliable live syslog need `sudo pymobiledevice3 remote tunneld` first.
6. **Container pull needs a development-signed build** (your sideload). App Store builds can't
   be pulled. `devicectl` domains: `appDataContainer` / `appGroupDataContainer` /
   `systemCrashLogs` / `temporary` only.
7. **The container is a snapshot** — quit or idle Kodi at home before pulling, or you capture a
   half-written state.
8. **`plutil` first** — always `plutil -p` / `-convert xml1` the binary plist before `diff`.

## Explicitly UNVERIFIED (confirm on-device / against your Xcode)

- Live `log stream --device-udid` reliability over a wireless-only tvOS 17+ pairing.
- `deviceconsole` / `idevicesyslog` attaching on tvOS 17/18.
- `xcrun devicectl device process terminate` exact flags (force-quit manually if it errors).
- `--user mobile` on tvOS specifically (documented for iOS only).
- The precise tvOS Developer-Mode enablement UI.
- `KODI_HOME`/`userdata` location inside the container — resolve via §3a first.

## Citations

Fix/root-cause (this repo + Kodi Wiki): `_kodisettings.py`, `wiz.py`,
`docs/playbooks/ezm-restore-hardening.md`, `CLAUDE.md`; Kodi Wiki
[TvOS](https://kodi.wiki/view/TvOS), [Userdata](https://kodi.wiki/view/Userdata).

Xcode/CLI commands:
- devicectl domains + `--user mobile`: Apple Dev Forums
  [765386](https://developer.apple.com/forums/thread/765386),
  [749649](https://developer.apple.com/forums/thread/749649)
- `devicectl device copy from` exact shape: gist
  [ovmessage/fbc5292…](https://gist.github.com/ovmessage/fbc529292a65222191bec6ce5e5a4275)
- `manage pair` + `device info files`:
  [zenn.dev/scenee](https://zenn.dev/scenee/articles/df3a6d9fb18465)
- `list devices` / launch over CoreDevice: Apple Dev Forums
  [744765](https://developer.apple.com/forums/thread/744765)
- tvOS LAN pairing: Apple
  [Connecting a tvOS app over the local network](https://developer.apple.com/documentation/devicediscoveryui/connecting-a-tvos-app-to-other-devices-over-the-local-network)
- `log collect`/`show`/`stream` on paired devices:
  [sjdcforensics](https://www.sjdcforensics.com/collecting-iphone-unified-logs-via-macos/),
  [mac4n6](http://www.mac4n6.com/blog/2020/9/8/analysis-of-apple-unified-logs-entry-12-quick-amp-easy-unified-log-collection-from-ios-devices-for-testing),
  [log(1) man](https://keith.github.io/xcode-man-pages/log.1.html)
- Xcode Download/Replace Container GUI + `.xcappdata`:
  [codementor](https://www.codementor.io/@paulzabelin/xcode-app-data-suni6p4ma),
  [egeek.me](https://egeek.me/2021/02/06/replacing-ios-application-container-in-terminal/),
  [fluffy.es](https://fluffy.es/inspect-app-folder-in-simulators-and-real-device/)
- deviceconsole: [rpetrich/deviceconsole](https://github.com/rpetrich/deviceconsole)
- idevicesyslog: [man](https://linuxcommandlibrary.com/man/idevicesyslog)
- pymobiledevice3: [README](https://github.com/doronz88/pymobiledevice3),
  [cli-recipes](https://github.com/doronz88/pymobiledevice3/blob/master/docs/guides/cli-recipes.md),
  [RSD tunnel #566](https://github.com/doronz88/pymobiledevice3/issues/566),
  [tvOS 17 #1122](https://github.com/doronz88/pymobiledevice3/issues/1122)
- NSUserDefaults plist path + `plutil -p`: Apple Dev Forums
  [713441](https://developer.apple.com/forums/thread/713441)
- Developer Mode: Apple
  [Enabling Developer Mode](https://developer.apple.com/documentation/xcode/enabling-developer-mode-on-a-device)
- Free-account 7-day expiry: Apple
  [Provisioning profile updates](https://developer.apple.com/help/account/provisioning-profiles/provisioning-profile-updates/)

> Honest caveat carried up from research: Apple's pairing/Developer-Mode pages returned
> HTTP 403 to the fetchers, so exact tvOS **menu wording** is corroborated from forums +
> multiple walkthroughs, not quoted from the primary page. Confirm on-device.
