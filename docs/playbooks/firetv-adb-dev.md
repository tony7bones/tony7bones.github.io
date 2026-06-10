# Fire TV ADB Dev Pipeline — `script.tony7bones.modv2plus`

Live development and verification of `script.tony7bones.modv2plus` against
the real Amazon Fire TV Stick 4K Max ("hazel") running Kodi 21.3 Omega.

---

## Device facts (confirmed)

| Field          | Value                                                            |
| -------------- | ---------------------------------------------------------------- |
| Device         | Amazon Fire TV Stick 4K Max (AFTHA004, hazel)                    |
| Android        | 9                                                                |
| LAN IP         | **192.168.7.162**                                                |
| ADB port       | 5555                                                             |
| Kodi           | 21.3 Omega (`org.xbmc.kodi`)                                     |
| Kodi data root | `/sdcard/Android/data/org.xbmc.kodi/files/.kodi/`                |
| JSON-RPC       | `http://192.168.7.162:8080/jsonrpc` (user: `kodi`, pass: `kodi`) |
| Active skin    | `skin.estuary.modv2`                                             |
| Add-on path    | `.kodi/addons/script.tony7bones.modv2plus/`                      |

The Mac's LAN IP is `192.168.7.214`; the subnet is `192.168.7.0/24`.

> **3.0 one-shot on the device.** This is still the device runbook for iterating on
> `script.tony7bones.modv2plus`. Note two things about the shipped 3.0 flow when you
> verify it on the Fire TV: (1) the one-tap Setup now **installs and activates**
> MOD V2 + the patch itself — you no longer Apply by hand for a fresh box; (2) Kodi
> on Android **cannot self-restart**, so Setup prompts the user to **close** Kodi and
> the user **reopens** it. On that reopen, MOD V2 is the active skin and the modv2plus
> **boot service** (`service.py`) auto-applies the patch — so a clean device verify
> means: run Setup → close Kodi → reopen → confirm MOD V2 is active and the patch
> marker (`show_system_info_overlay` in the live `Home.xml`) is present, without ever
> calling Apply yourself. The manual Apply/Restore commands below remain for
> re-applying or reverting.

---

## Prerequisites

### On the Mac (one-time)

```bash
brew install android-platform-tools   # installs adb, fastboot
adb version                           # verify: Version 37.0.0 or newer
```

### On the Fire TV (one-time — user must do these at the TV)

1. **Enable Developer Options**: Settings → My Fire TV → About → click "Fire TV" 7 times.
2. **Enable ADB Debugging**: Settings → My Fire TV → Developer Options → ADB Debugging → ON.
3. **Allow from unknown sources** (if not already): Settings → My Fire TV → Developer Options → Apps from Unknown Sources → ON.

ADB authorization is a one-time per-host prompt: the first `adb connect` from
a new Mac will show a popup on the TV screen. **Approve it there** — the command
shows `unauthorized` until you do. After approval it shows `device` and persists
in `~/.android/adbkey` (no re-approval unless you revoke or ADB server resets).

---

## Connect / reconnect

```bash
# Start the adb server (auto-starts on first use, but explicit is safer)
adb start-server

# Connect to the Fire TV
adb connect 192.168.7.162:5555

# Verify — should say: 192.168.7.162:5555  device  product:hazel model:AFTHA004
adb devices -l
```

**If it shows `unauthorized`:** a popup appeared on the TV. Go approve it.  
**If it shows `offline`:** the TV is asleep or on a different network segment. Wake it and retry.  
**If connection is refused:** ADB debugging was turned off or the IP changed. Re-enable on the TV.

After TV sleep/wake the TCP connection usually drops. Reconnect with the same
`adb connect 192.168.7.162:5555` — no new TV authorization needed (key is cached).

### Disconnect / cleanup

```bash
adb disconnect 192.168.7.162:5555   # drop this specific connection
adb kill-server                      # tear down the local daemon entirely (use if daemon is wedged)
```

---

## Scoped storage — adb path notes

Android 10+ enforces scoped storage for `Android/data/` paths. **Fire TV on
Android 9** does not enforce this restriction — `adb push` and `adb pull`
work directly against the full `.kodi/` tree without `run-as` or root:

```
/sdcard/Android/data/org.xbmc.kodi/files/.kodi/addons/
/sdcard/Android/data/org.xbmc.kodi/files/.kodi/userdata/
/sdcard/Android/data/org.xbmc.kodi/files/.kodi/temp/kodi.log
```

If you ever provision a Fire TV on Android 10+ (e.g. a non-rooted Fire OS 8 /
Android 11 Stick), the `adb shell run-as org.xbmc.kodi` trick only works for
debuggable builds, which Kodi releases are not — and these devices are not
rootable. The supported path is the **non-root data-relocation method**
(`xbmc.data=/sdcard/kodi_data` in `/sdcard/xbmc_env.properties` +
`MANAGE_EXTERNAL_STORAGE` grant) documented in
[`firetv-stick-scoped-storage-provisioning.md`](firetv-stick-scoped-storage-provisioning.md),
which the fleet provisioner automates. **For this hazel/Android 9 device, direct
push/pull works — no relocation needed.**

> **See also:**
> [`firetv-stick-scoped-storage-provisioning.md`](firetv-stick-scoped-storage-provisioning.md)
> (non-root relocation for Fire OS 8 / Android 11 Sticks) and
> [`install-from-notebook.md`](install-from-notebook.md) (the full from-laptop
> provision runbook).

---

## Inner dev loop — edit → push → reload → screencap

This is the fastest cycle for iterating on any file that `script.tony7bones.modv2plus`
patches into `skin.estuary.modv2`.

### Variables

```bash
FIRETV=192.168.7.162:5555
KODI_ADDONS=/sdcard/Android/data/org.xbmc.kodi/files/.kodi/addons
SKIN_XML=${KODI_ADDONS}/skin.estuary.modv2/xml
ADDON_SRC=/Users/moquette/Code/tony7bones.github.io/addons/script.tony7bones.modv2plus
```

### Step 1 — edit a source file on the Mac

Edit any file under `addons/script.tony7bones.modv2plus/resources/xml/` (e.g.
`Home.xml`, `SkinSettings.xml`) or `resources/media/` in your editor.

### Step 2 — push the changed file(s)

**Push a single patched XML into the live skin** (fastest, no zip needed):

```bash
adb -s 192.168.7.162:5555 push \
  ${ADDON_SRC}/resources/xml/Home.xml \
  ${SKIN_XML}/Home.xml
```

**Push the whole add-on directory** (when default.py or addon.xml changed):

```bash
adb -s 192.168.7.162:5555 push \
  ${ADDON_SRC}/. \
  ${KODI_ADDONS}/script.tony7bones.modv2plus/
```

### Step 3 — tell Kodi to pick up the change

**Reload the skin** (for XML-only changes — no Kodi restart needed):

```bash
curl -s -u kodi:kodi http://192.168.7.162:8080/jsonrpc \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","method":"GUI.ExecuteBuiltin","params":{"function":"ReloadSkin"},"id":1}'
```

**Run the Apply action** (when you want the patch script to re-copy its files
into the skin and you changed default.py logic):

```bash
curl -s -u kodi:kodi http://192.168.7.162:8080/jsonrpc \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","method":"Addons.ExecuteAddon","params":{"addonid":"script.tony7bones.modv2plus","params":["apply"]},"id":1}'
```

**Restart Kodi entirely** (for addon.xml changes or anything that requires a
full re-init — slowest, but sometimes necessary):

```bash
adb -s 192.168.7.162:5555 shell am force-stop org.xbmc.kodi
adb -s 192.168.7.162:5555 shell am start -n org.xbmc.kodi/.Splash
```

**ALWAYS surface Kodi to the foreground when launching or driving it.** On Fire
Sticks Kodi is frequently already running but BACKGROUNDED (Fire OS parks it
behind the launcher; screensaver/HOME presses do this constantly). A backgrounded
Kodi still answers JSON-RPC, which makes "it's up" checks misleading — but key
events go to whatever app is foregrounded, and screencaps show the launcher, not
Kodi. The `am start` above is the habit: it is idempotent (launches Kodi if dead,
surfaces it if backgrounded), so run it before ANY interaction sequence — every
launch, every reopen, every time you come back to drive the UI:

```bash
adb -s $FIRETV shell am start -n org.xbmc.kodi/.Splash   # launch OR foreground — always safe
```

### Step 4 — screencap

```bash
adb -s 192.168.7.162:5555 exec-out screencap -p > /tmp/kodi_screen.png
open /tmp/kodi_screen.png
```

Output is a 1920×1080 PNG. `open` launches Preview on macOS.

### Step 5 — pull the log

```bash
adb -s 192.168.7.162:5555 pull \
  /sdcard/Android/data/org.xbmc.kodi/files/.kodi/temp/kodi.log \
  /tmp/kodi.log

grep -i "mod v2+" /tmp/kodi.log | tail -30
```

The add-on logs with prefix `[mod v2+]` at INFO level; errors use ERROR level.

---

## Full inner-loop command sequence (copy-paste)

```bash
FIRETV=192.168.7.162:5555
KODI_ADDONS=/sdcard/Android/data/org.xbmc.kodi/files/.kodi/addons
SKIN_XML=${KODI_ADDONS}/skin.estuary.modv2/xml
ADDON_SRC=/Users/moquette/Code/tony7bones.github.io/addons/script.tony7bones.modv2plus

# 1. Push changed XML directly into the live skin
adb -s $FIRETV push ${ADDON_SRC}/resources/xml/Home.xml ${SKIN_XML}/Home.xml

# 2. Reload skin (no restart)
curl -s -u kodi:kodi http://192.168.7.162:8080/jsonrpc \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","method":"GUI.ExecuteBuiltin","params":{"function":"ReloadSkin"},"id":1}'

# 3. Screenshot
adb -s $FIRETV exec-out screencap -p > /tmp/kodi_screen.png && open /tmp/kodi_screen.png

# 4. Check logs
adb -s $FIRETV pull /sdcard/Android/data/org.xbmc.kodi/files/.kodi/temp/kodi.log /tmp/kodi.log
grep -i "mod v2+" /tmp/kodi.log | tail -30
```

---

## Deploying a new version of the add-on

When `default.py`, `addon.xml`, or any resource changed and you want to ship
the updated add-on to the device without going through the repo release cycle:

```bash
FIRETV=192.168.7.162:5555
KODI_ADDONS=/sdcard/Android/data/org.xbmc.kodi/files/.kodi/addons
ADDON_SRC=/Users/moquette/Code/tony7bones.github.io/addons/script.tony7bones.modv2plus

# Push entire addon dir
adb -s $FIRETV push ${ADDON_SRC}/. ${KODI_ADDONS}/script.tony7bones.modv2plus/

# Notify Kodi to rescan local addons
curl -s -u kodi:kodi http://192.168.7.162:8080/jsonrpc \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","method":"GUI.ExecuteBuiltin","params":{"function":"UpdateLocalAddons"},"id":1}'

# Confirm version picked up
curl -s -u kodi:kodi http://192.168.7.162:8080/jsonrpc \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","method":"Addons.GetAddonDetails","params":{"addonid":"script.tony7bones.modv2plus","properties":["enabled","version"]},"id":1}'
```

---

## Running the patch Apply / Restore

```bash
# Apply — patches the skin XML and media files
curl -s -u kodi:kodi http://192.168.7.162:8080/jsonrpc \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","method":"Addons.ExecuteAddon","params":{"addonid":"script.tony7bones.modv2plus","params":["apply"]},"id":1}'

# Restore — reverts skin to .bak originals and removes new media files
curl -s -u kodi:kodi http://192.168.7.162:8080/jsonrpc \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","method":"Addons.ExecuteAddon","params":{"addonid":"script.tony7bones.modv2plus","params":["restore"]},"id":1}'
```

After Apply or Restore, reload the skin to see the change without restarting Kodi:

```bash
curl -s -u kodi:kodi http://192.168.7.162:8080/jsonrpc \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","method":"GUI.ExecuteBuiltin","params":{"function":"ReloadSkin"},"id":1}'
```

---

## Navigating Kodi from the Mac (key events)

Use `adb shell input keyevent` to drive the UI when you need the remote:

```bash
FIRETV=192.168.7.162:5555

adb -s $FIRETV shell input keyevent KEYCODE_HOME          # Fire TV home
adb -s $FIRETV shell input keyevent KEYCODE_BACK          # back
adb -s $FIRETV shell input keyevent KEYCODE_DPAD_CENTER   # select / OK
adb -s $FIRETV shell input keyevent KEYCODE_DPAD_UP
adb -s $FIRETV shell input keyevent KEYCODE_DPAD_DOWN
adb -s $FIRETV shell input keyevent KEYCODE_DPAD_LEFT
adb -s $FIRETV shell input keyevent KEYCODE_DPAD_RIGHT
adb -s $FIRETV shell input keyevent KEYCODE_MENU          # context menu (equivalent to Kodi's 'c')
```

Launch Kodi if it was closed:

```bash
adb -s $FIRETV shell am start -n org.xbmc.kodi/.Splash
```

Force-stop Kodi (clean restart):

```bash
adb -s $FIRETV shell am force-stop org.xbmc.kodi
```

---

## Verify-only mode (no adb needed)

When you only need to confirm what's on the device without pushing anything,
JSON-RPC over the LAN is sufficient:

```bash
# Is the patch applied? (check for .bak files in skin xml dir)
adb -s 192.168.7.162:5555 shell ls \
  /sdcard/Android/data/org.xbmc.kodi/files/.kodi/addons/skin.estuary.modv2/xml/ \
  | grep '\.bak$'

# What version of the add-on is installed?
curl -s -u kodi:kodi http://192.168.7.162:8080/jsonrpc \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","method":"Addons.GetAddonDetails","params":{"addonid":"script.tony7bones.modv2plus","properties":["enabled","version"]},"id":1}'
```

---

## Troubleshooting

### `unauthorized` after `adb connect`

A popup appeared on the TV screen asking to authorize this computer's RSA key.
Go to the TV and tap **Allow**. If the TV is off or the popup already dismissed,
run `adb disconnect 192.168.7.162:5555 && adb connect 192.168.7.162:5555` to
trigger it again. The popup times out — be watching the TV when you connect for
the first time from a new Mac.

### `offline` or `connection refused`

The TV is asleep or ADB was disabled. Wake the TV and check Settings → My Fire TV
→ Developer Options → ADB Debugging is still ON. Then reconnect.

### `adb connect` succeeded but `adb devices` shows nothing

Run `adb kill-server && adb start-server && adb connect 192.168.7.162:5555`.
A stale daemon sometimes loses its connection table.

### IP changed after router DHCP reassignment

Use the Fire TV Settings → About → Network to get the new IP. Reserve a static
DHCP lease for MAC `e2:d8:c4:19:8f:ce` in your router to avoid this. (The MAC
has the locally-administered bit set — normal for modern Amazon devices using
randomized MAC addresses; note the actual hardware OUI is `d4:a3:3d` but the
device advertises the randomized `e2:d8:c4` form.)

### `adb push` permission denied on `Android/data/`

This only happens on Android 10+. This device is Android 9 — if you see it,
double-check `adb -s 192.168.7.162:5555 shell getprop ro.build.version.release`.
If it is ≥10 (e.g. a non-rooted Fire OS 8 / Android 11 Stick), use the non-root
data-relocation method in
[`firetv-stick-scoped-storage-provisioning.md`](firetv-stick-scoped-storage-provisioning.md)
instead of expecting direct push to work.

### ReloadSkin has no visible effect

Some XML changes (especially in `Includes.xml` or dialog-level definitions)
require a full Kodi restart, not just a skin reload:

```bash
adb -s 192.168.7.162:5555 shell am force-stop org.xbmc.kodi
adb -s 192.168.7.162:5555 shell am start -n org.xbmc.kodi/.Splash
```

### JSON-RPC returns 401

The webserver credentials changed. Check `guisettings.xml`:

```bash
adb -s 192.168.7.162:5555 shell grep webserverpassword \
  /sdcard/Android/data/org.xbmc.kodi/files/.kodi/userdata/guisettings.xml
```

### JSON-RPC connection refused / timeout

Kodi's webserver was disabled. Enable it without touching the TV:

1. Force-stop Kodi: `adb -s 192.168.7.162:5555 shell am force-stop org.xbmc.kodi`
2. Edit guisettings.xml to set `services.webserver` to `true`:
   ```bash
   adb -s 192.168.7.162:5555 pull \
     /sdcard/Android/data/org.xbmc.kodi/files/.kodi/userdata/guisettings.xml \
     /tmp/guisettings.xml
   # edit /tmp/guisettings.xml: set <setting id="services.webserver">true</setting>
   adb -s 192.168.7.162:5555 push /tmp/guisettings.xml \
     /sdcard/Android/data/org.xbmc.kodi/files/.kodi/userdata/guisettings.xml
   ```
3. Start Kodi: `adb -s 192.168.7.162:5555 shell am start -n org.xbmc.kodi/.Splash`

---

## Discovery notes (how this IP was found)

Run these on the Mac to rediscover the Fire TV if the IP changes:

```bash
# mDNS — fastest, fires immediately
dns-sd -B _amzn-wplay._tcp local.     # Amazon Fire TV devices advertise this

# Resolve the found service name to get its IP
dns-sd -L "<service-name>" _amzn-wplay._tcp local.

# ARP table — lists hosts seen recently (no traffic needed)
arp -a | grep -v incomplete

# Port scan — Fire TV with ADB enabled listens on 5555
for ip in $(seq 1 254); do
  nc -z -G1 192.168.7.$ip 5555 2>/dev/null && echo "192.168.7.$ip:5555 OPEN" &
done; wait
```

The Fire TV's Amazon device ID is `A359HI7OGMDZRV` (from mDNS TXT record);
its mDNS name is "Office TV".
