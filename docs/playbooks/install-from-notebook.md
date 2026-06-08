# Install & Bootstrap a Kodi Box From Your Notebook (ADB)

A repeatable runbook to provision a fresh Tony.7.Bones Kodi box on a Fire TV /
Android device **entirely from your laptop** over ADB-on-network — wipe, install
the repo, run the one-tap Setup, restart, and verify. This is the
hardware-proven flow (bedroom TV, 2026-06-08) after the restart-and-continue
fixes landed (module 1.1.2 / bootstrap 1.3.2 / modv2plus 1.4.4).

> **What the Setup produces (one run):** 12 source repos + base apps + curated
> video add-ons + Live TV (pvr.iptvsimple) + Weather (Multi→Sacramento) + RSS +
> file sources, then **installs and activates Estuary MOD V2 + the MOD V2+
> patch**, then closes Kodi cleanly. You reopen once and the box is done.

---

## 0. One-time prerequisites

**On your notebook (Mac):**

```bash
brew install android-platform-tools     # provides `adb`
adb version                             # confirm it runs
```

**On the Fire TV (at the TV, once per device):**

- Settings → My Fire TV → Developer options → **ADB debugging = ON**
  (if Developer options is hidden: Settings → My Fire TV → About → click the
  device name 7×).
- Note the device IP: Settings → My Fire TV → About → Network → **IP address**.
- The first `adb connect` pops an **"Allow USB debugging?"** prompt on the TV —
  check "Always allow" and accept it (this is the one physical step you cannot
  do from the notebook).

---

## 1. Set your variables (every session)

```bash
export PATH="/opt/homebrew/bin:$PATH"
IP=192.168.7.84                 # <-- the device's IP
D=$IP:5555
K=/sdcard/Android/data/org.xbmc.kodi/files/.kodi   # Kodi's profile dir on Fire TV
RAW=https://raw.githubusercontent.com/tony7bones/tony7bones.github.io/main/addons
RPC(){ curl -s -m 6 -H 'Content-Type: application/json' -d "$1" http://$IP:8080/jsonrpc 2>/dev/null; }
adb connect $D
adb -s $D shell 'getprop ro.product.model'         # sanity: prints the device model
```

---

## 2. (Recommended) Reboot the device first

Rapid Kodi stop/start cycles can wedge the Fire TV GPU (Kodi then crashes at GL
init on the next launch). A clean **device** reboot clears it. Always start a
provision from a fresh device reboot:

```bash
adb -s $D reboot
adb -s $D wait-for-device
until adb -s $D shell 'getprop sys.boot_completed 2>/dev/null' | grep -q 1; do sleep 5; done
sleep 12     # let the launcher settle
```

---

## 3. Wipe Kodi clean

```bash
adb -s $D shell am force-stop org.xbmc.kodi; sleep 2
# IMPORTANT: create addons/ AND userdata/ up front — if addons/ doesn't exist,
# the first `adb push` dumps an add-on's *contents* loose into addons/ instead
# of making a subdir (a real bug we hit).
adb -s $D shell "rm -rf $K && mkdir -p $K/userdata $K/addons"
# turn the web server on so the rest of this runbook can drive Kodi headless
printf '<settings version="2"><setting id="services.webserver">true</setting><setting id="services.webserverport">8080</setting><setting id="services.webserverauthentication">false</setting><setting id="services.esenabled">true</setting></settings>' > /tmp/kodi_gs.xml
adb -s $D push /tmp/kodi_gs.xml "$K/userdata/guisettings.xml"
```

---

## 4. Install the Setup add-ons (from the live site)

The Setup is `script.tony7bones.bootstrap`; it requires the shared library
`script.module.tony7bones`. Fetch both at their current published versions and
push them in:

```bash
ver(){ curl -s -m 15 "$RAW/$1/addon.xml" | grep -oE 'version="[0-9]+\.[0-9]+\.[0-9]+"' | grep -oE '[0-9]+\.[0-9]+\.[0-9]+' | head -1; }
MV=$(ver script.module.tony7bones); BV=$(ver script.tony7bones.bootstrap)
echo "module=$MV bootstrap=$BV"
rm -rf /tmp/t7b && mkdir -p /tmp/t7b && cd /tmp/t7b
curl -s -o m.zip "$RAW/script.module.tony7bones/script.module.tony7bones-$MV.zip"
curl -s -o b.zip "$RAW/script.tony7bones.bootstrap/script.tony7bones.bootstrap-$BV.zip"
unzip -oq m.zip && unzip -oq b.zip
adb -s $D push script.module.tony7bones "$K/addons/"
adb -s $D push script.tony7bones.bootstrap "$K/addons/"
# verify the library landed correctly (this path must exist):
adb -s $D shell "ls $K/addons/script.module.tony7bones/lib/tony7bones/system.py"
```

---

## 5. Launch Kodi + enable the add-ons

```bash
adb -s $D shell monkey -p org.xbmc.kodi -c android.intent.category.LAUNCHER 1
until RPC '{"jsonrpc":"2.0","method":"JSONRPC.Ping","id":1}' | grep -q pong; do sleep 3; done
for a in script.module.tony7bones script.tony7bones.bootstrap; do
  RPC "{\"jsonrpc\":\"2.0\",\"method\":\"Addons.SetAddonEnabled\",\"params\":{\"addonid\":\"$a\",\"enabled\":true},\"id\":1}"
done
```

---

## 6. Run the one-tap Setup

```bash
RPC '{"jsonrpc":"2.0","method":"Addons.ExecuteAddon","params":{"addonid":"script.tony7bones.bootstrap"},"id":1}'
```

Then **watch the install** (it takes ~3–4 min — 12 repos, apps, video, skin):

```bash
# tail the Setup's progress
adb -s $D shell "grep -aE '\[script.tony7bones.bootstrap\]|activate_skin|clean Quit' $K/temp/kodi.log | tail -20"
```

The Setup ends with a **summary dialog** (one "OK"), then it sets the skin,
**accepts Kodi's "Keep this skin?" confirm** (so MOD V2 sticks), and **cleanly
Quits** (no force-kill needed). Dismiss the summary OK from the notebook:

```bash
# when the install is done, dismiss the summary dialog so run() finishes:
RPC '{"jsonrpc":"2.0","method":"Input.Select","id":1}'
```

(Or just click OK on the TV remote.) Kodi then closes itself within ~25s. Confirm:

```bash
until ! adb -s $D shell 'pidof org.xbmc.kodi >/dev/null'; do sleep 3; done
echo "Kodi closed cleanly."
# the skin must have persisted as MOD V2 (NOT reverted to skin.estuary):
adb -s $D shell "grep lookandfeel.skin\" $K/userdata/guisettings.xml"
#   -> <setting id="lookandfeel.skin">skin.estuary.modv2</setting>
```

---

## 7. Reopen — the box finishes itself

```bash
adb -s $D shell am start -n org.xbmc.kodi/.Splash
```

On this single reopen Kodi boots into MOD V2, and the **modv2plus boot service**
waits for the home to render, then builds the skinshortcuts menu and applies the
patch automatically. Give it ~30–40s.

---

## 8. Verify the box

```bash
# active skin + current window (want skin.estuary.modv2 + Home/10000)
RPC '{"jsonrpc":"2.0","method":"GUI.GetProperties","params":{"properties":["skin","currentwindow"]},"id":1}'
# patch applied? (1 = patched)
adb -s $D shell "grep -c show_system_info_overlay $K/addons/skin.estuary.modv2/xml/Home.xml"
# menu built + home not blank? (0 = good)
adb -s $D shell "grep -ac 'Control 9000 in window 10000' $K/temp/kodi.log"
# weather wired?
RPC '{"jsonrpc":"2.0","method":"XBMC.GetInfoLabels","params":{"labels":["Weather.Location"]},"id":1}'
# eyeball it:
adb -s $D shell screencap -p /sdcard/home.png && adb -s $D pull /sdcard/home.png /tmp/home.png && open /tmp/home.png
```

A good box: `skin.estuary.modv2` active, current window `Home`, patch marker `1`,
`0` focus errors, weather `Sacramento`, and the screenshot shows the trimmed
MOD V2+ menu (Movies / TV shows / TV / Add-ons / **Favorites** / Weather).

---

## 9. One-time manual steps (cannot be automated)

- **PVR "All channels" group** — hide via PVR & Live TV → Channels → Group
  manager (the flag lives in the PVR DB, which only exists after channels sync).
- **TV → Options sort** — "Sort by Name" on Channels + Timeline are per-window
  view-states (ViewModes6.db); set them once on the device, they persist.
- The first `adb connect` debug-authorization prompt (step 0).

---

## Troubleshooting (hard-won)

| Symptom                                                                            | Cause + fix                                                                                                                                                |
| ---------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Kodi **crashes at GL init** on launch (`GLES: Maximum texture …`, before the skin) | GPU wedged by rapid stop/start cycles. **Reboot the device** (step 2). Don't rapid-cycle restarts.                                                         |
| Box boots **stock Estuary**, not MOD V2                                            | The "Keep this skin?" confirm wasn't accepted. Fixed in bootstrap ≥ 1.3.2 (`activate_skin` clicks Yes). Make sure you installed current versions (step 4). |
| **Blank home** / `Control 9000 … can't focus` after reopen                         | skinshortcuts menu not built yet. Fixed in modv2plus ≥ 1.4.4 (service waits for the home, then builds). Give it ~30s; if still blank, one more reopen.     |
| `import tony7bones` fails / Setup errors instantly                                 | The library landed loose in `addons/`. You skipped `mkdir -p $K/addons` (step 3) — re-wipe with the mkdir.                                                 |
| `adb connect` says **unauthorized**                                                | Accept the "Allow USB debugging?" prompt at the TV.                                                                                                        |
| `adb` shows **offline** / connection refused                                       | `adb disconnect; adb kill-server; adb connect $D`. Re-enable ADB debugging on the TV if needed.                                                            |
| Setup hangs at the end, needs force-kill                                           | Pre-1.1.2 behavior. Current module Quits cleanly; if you see this, you're on an old build — reinstall current versions.                                    |

---

## The remote-only alternative (no ADB for the install)

If you'd rather not drive the install over ADB, do steps 1–3 from the notebook
(connect + reboot + wipe), then at the TV:

1. Settings → File Manager → Add source → `https://tony7bones.github.io/`
2. Install from zip → that source → `repositories/` →
   `repository.tony7bones-<ver>.zip`
3. Install from repository → Tony.7.Bones Repo → Program add-ons →
   **Tony.7.Bones Setup** (installs + auto-runs)
4. Click **OK** on the summary; Kodi closes itself.
5. Reopen Kodi from the home screen — done.

Then verify from the notebook (step 8).

---

## See also

- `docs/playbooks/kodi-restart-and-continue.md` — why the finish works (the
  clean-Quit + keep-skin-dialog + service-readiness fixes).
- `docs/playbooks/firetv-adb-dev.md` — the inner DEV loop (edit → push → reload)
  for the modv2plus patch, and `_tools/firetv.sh` helpers.
- `docs/playbooks/release-and-deploy.md` — how the add-ons themselves are built
  and shipped.
