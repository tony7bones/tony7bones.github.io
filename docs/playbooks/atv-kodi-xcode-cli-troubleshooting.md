# Apple TV (tvOS) Kodi troubleshooting over the Xcode CLI

> **CORRECTION (2026-07-14, from Kodi Omega source).** The claim that Kodi "rewrites the on-disk userdata files from the mirror on boot/launch" is **FALSE**. `MigrateUserdataXMLToNSUserDefaults` (PreflightHandler.mm:81-93) returns early forever once `UserdataMigrated` is set, and nothing ever copies a key back to disk. What actually happens: `CTVOSFile::Exists`/`Open` (TVOSFile.cpp:70-122) check the NSUserDefaults **key FIRST** and only fall back to POSIX - so a key **SHADOWS** the disk file. A file-only restore "reverts" because the stale key wins, not because disk was rewritten. Consequence: **dropping the POSIX copy has ZERO fallback** - nothing re-materializes it. See the `kodi-storage-map` skill.

Apple TV has **no adb** and (on 4K models) **no data USB port** - everything here is
over Wi-Fi from a Mac (or, for the `pymobiledevice3` path, any host including Linux).
This is the tvOS equivalent of `adb logcat` + `adb pull`, used to prove/verify the
EZ Maintenance++ restore bug (see `ezm-restore-hardening.md` and the
`ezm-backup-doctor` skill).

## Why this exists (the bug being proven)

Per **Kodi's own source** (Omega, `xbmc@f8815ee4` - the Wiki's summary of this is wrong and
cost us a data-loss bug, see the correction above): Kodi's home lives in `Library/Caches` on
tvOS (Apple forbids writing to `Documents`, `DarwinEmbedUtils.mm:16-41`), which the system may
purge. So Kodi **vectors `userdata/*.xml` into the app's NSUserDefaults** (a different, non-purged
domain) - every `.xml` under `userdata` except `customcontroller.SiriRemote*`
(`CTVOSFile::WantsFile`, `TVOSFile.cpp:39-45`).

It does **NOT** rewrite the disk files from that store. `CTVOSFile::Exists`/`Open`
(`TVOSFile.cpp:70-122`) simply check the **key first** and fall back to POSIX, so a key
**SHADOWS** the disk file. Nothing ever copies a key back to disk.

Consequences:

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
output back to me and I interpret them. Three snapshots - **A** (before restore),
**B** (after restore, before relaunch), **C** (after force-quit + reopen) - prove the
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
export KODI_HOME="Documents"    # CANDIDATE - resolve empirically in step 3a before trusting
```

Mac + Apple TV must be on the **same Wi-Fi** (no guest/IoT VLAN, no AP/client isolation).

## 1. Pair + discover the device

On the ATV: **Settings → Remotes and Devices → Remote App and Devices** (leave open).

```bash
xcrun devicectl list devices                  # note Name + Identifier(UDID); set ATV_UDID
xcrun devicectl manage pair --device "$ATV_UDID"   # confirm the code shown on the TV
xcrun devicectl device info apps --device "$ATV_UDID" | grep -i kodi   # confirm $BUNDLE
```

**Developer Mode** (tvOS 16+) is required to _launch_ dev-signed builds and to access the
container; the toggle appears only after the first pairing / dev-signed launch. On tvOS
it's driven by the pairing flow rather than an obvious Settings switch
(_exact tvOS UI: partially unverified - confirm on-device_).

## 2. Log capture (the behavioral proof) - the `adb logcat` equivalent

Add `--info --debug` (or `--level debug`) always - Kodi's info/debug lines are hidden by
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
_NOTE: live `log stream --device-udid` over a wireless-only tvOS 17+ pairing is not
guaranteed; if it stalls, use repeated `log collect` snapshots or pymobiledevice3 (§5)._

### 2b. Classic fallbacks (may not attach on tvOS 17/18 - UNVERIFIED)

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
**Never** pass `--remove-existing-content true` to `devicectl device copy to` - reported
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

## 5. Cross-platform fallback - `pymobiledevice3` (macOS AND Linux)

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
4. **Trust/pairing lapses** on sleep, IP change, reboot, or OS update - re-run `manage pair` /
   `remote pair` when commands report "not paired/trusted".
5. **tvOS 17 tunnel.** macOS `log`/`devicectl` handle it internally; `pymobiledevice3` and
   reliable live syslog need `sudo pymobiledevice3 remote tunneld` first.
6. **Container pull needs a development-signed build** (your sideload). App Store builds can't
   be pulled. `devicectl` domains: `appDataContainer` / `appGroupDataContainer` /
   `systemCrashLogs` / `temporary` only.
7. **The container is a snapshot** - quit or idle Kodi at home before pulling, or you capture a
   half-written state.
8. **`plutil` first** - always `plutil -p` / `-convert xml1` the binary plist before `diff`.

## Hard-won specifics (proven on ATV1 during the 2026.07.08.6 restore-dup fix)

The whole devicectl loop - launch Kodi, PUSH the add-on tree + its GitHub-only deps,
pull `kodi.log` + the NSUserDefaults plist, verify - was run for real on ATV1 to prove the
duplicate-userdata fix. The specifics that cost time, none of them obvious from the flag help:

- **`device copy to` CREATES missing parent dirs**, so a SINGLE-file push whose parent is
  misspelled silently lands an orphan file at the wrong depth instead of erroring. When you
  push an add-on tree, push it top-down (or verify each destination with a follow-up
  `device info files` listing) - a wrong `--destination` does not fail, it just makes a stray
  copy Kodi never loads.
- **`device info files` TRUNCATES its output on a large tree** (the full `addons/` tree in the
  container overflows what the listing returns), so you cannot trust "the file is not listed"
  as proof it is absent. Enumerate a NARROW subpath (the one add-on id, or `.../userdata`) to
  get a complete listing, or pull-and-diff instead of relying on the listing.
- **JSON-RPC cannot browse `special://`** - `Files.GetDirectory` refuses `special://` roots
  (and there is no adb/shell on tvOS), so you cannot enumerate `special://profile` remotely to
  confirm the File-Manager duplicate-entry symptom programmatically. The dup count has to be
  read off the on-TV File Manager UI (or inferred from the container listing + the plist keys:
  single POSIX copies on disk vs the `/userdata/*` keys in the NSUserDefaults plist).
- **The dup proof is disk-listing vs plist-keys.** `devicectl` listing of
  `Library/Caches/Kodi/userdata` shows the single POSIX `*.xml`; the NSUserDefaults plist
  `Library/Preferences/<bundle-id>.plist` (`plutil -p`) shows the `/userdata/*` keys the rewrite
  populated - the two layers the buggy build listed separately. On the koditvbox tvOS build the
  bundle id is `ca.koditvbox.kodi.tvos.21` and userdata lives under `Library/Caches/Kodi`, not
  `Documents` - resolve `KODI_HOME`/`BUNDLE` per §3a, do not assume.

## Explicitly UNVERIFIED (confirm on-device / against your Xcode)

- Live `log stream --device-udid` reliability over a wireless-only tvOS 17+ pairing.
- `deviceconsole` / `idevicesyslog` attaching on tvOS 17/18.
- `xcrun devicectl device process terminate` exact flags (force-quit manually if it errors).
- `--user mobile` on tvOS specifically (documented for iOS only).
- The precise tvOS Developer-Mode enablement UI.
- `KODI_HOME`/`userdata` location inside the container - resolve via §3a first.

## 8. Launching, deploying, and reading code back (2026-07-19)

Sections above cover pulling artifacts. This covers RUNNING the app and PUTTING
FILES on the box. Every item here cost real time in one session.

**The bundle id is NOT `org.xbmc.kodi`.** The fleet runs a KodiTVBox sideload:
`ca.koditvbox.kodi.tvos.21`. The wrong id returns **OSStatus -10814**, which
reads like sleep or permissions and actually means "application not found". Do
not diagnose sleep from it - a box was rebooted on that misreading. Enumerate:

```bash
xcrun devicectl device info apps --device "$UDID" | grep -i kodi
```

**Kodi's tree is at `Library/Caches/Kodi/`, not `Documents/.kodi/`.** Probing the
Documents path returns `CoreDeviceError 7000`, which looks like "the deploy never
landed". List rather than guess:

```bash
xcrun devicectl device info files --device "$UDID" \
  --domain-type appDataContainer --domain-identifier ca.koditvbox.kodi.tvos.21
```

Everything Kodi owns therefore sits under a directory tvOS may purge under
storage pressure, and `guisettings.xml` does not exist on disk (NSUD-shadowed).

**An asleep Apple TV refuses a foreground launch** with `RequestDenied`. Apple
TVs ignore Wake-on-LAN and devicectl has no wake verb. `xcrun devicectl device
reboot` wakes it; the launch then works after a few retries while the tunnel
re-establishes. Non-destructive, verified on atv1 and atv2.

**JSON-RPC answers only while Kodi is foregrounded.** "Port 8080 closed" almost
always means "Kodi is not in the foreground", not "unreachable". Launch first.

**`devicectl device copy to` SKIPS FILES IT THINKS ARE UNMODIFIED, AND ITS TEST
IS SIZE-BASED.** Its own help says "skipping files that have not been modified".
Measured on atv2 2026-07-19: overwriting an existing file with DIFFERENT content
of the SAME LENGTH is silently skipped, zero errors, old content intact.
Different-length content overwrites fine. So it is not "refuses to overwrite" -
it is "same size looks unmodified".

This is lethal for deploys here because `build.py` stamps every file with a fixed
1980 timestamp for reproducibility, so mtime is constant across builds and
staleness detection collapses onto SIZE ALONE. A same-length edit - a bumped
version string, a flipped comparison, a reflowed docstring - is silently dropped
while the command reports success. Nine consecutive attempts to push
`addon.xml` 2026.07.19.2 -> .3 failed this way; the two files are the same length.

Force it with `-r, --remove-existing-content`, or ALWAYS read a code file back
off the box and HASH it against source. A bumped manifest proves nothing.

Separately: a wrong flag ORDER prints a `Usage:` block that reads like success.

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
