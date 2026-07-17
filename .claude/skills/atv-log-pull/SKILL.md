---
name: atv-log-pull
description: Pull and read Kodi logs (kodi.log, kodi.old.log, NSUserDefaults plist) from a fleet Apple TV over the network - no adb exists on tvOS. Use when diagnosing any ATV crash, skin failure, or storage bug, when the user says "check the ATV logs", or when the EZM++ in-app log viewer cannot be used (it dies silently on crash-corrupted logs). Proven end-to-end on atv2 2026-07-17.
---

# Pull Kodi logs from an Apple TV (no adb on tvOS)

Proven working recipe, executed for real against ATV2 on 2026-07-17 to diagnose
the menu-refresh crash. Every flag quirk below cost a failed attempt; follow
exactly.

## The map (verified against a live box)

| What | Where |
| --- | --- |
| Fleet ATVs | atv2 = `192.168.7.183` (JSON-RPC TCP 9090; HTTP 8080, auth `kodi`/`kodi`). Office Fire TV `192.168.7.162` is HANDS-OFF. |
| devicectl device names | `ATV1`, `ATV2` (already paired on this workstation; `xcrun devicectl list devices`) |
| Kodi bundle id | `ca.koditvbox.kodi.tvos.21` |
| Kodi home in the container | `Library/Caches/Kodi` |
| **kodi.log / kodi.old.log** | **`Library/Caches/kodi.log`** (NOT under `Kodi/` and NOT in `temp/` - `special://logpath/` maps to `Library/Caches`) |
| NSUserDefaults plist (the key layer) | `Library/Preferences/ca.koditvbox.kodi.tvos.21.plist` (inspect with `plutil -p`) |
| skinshortcuts menu data | `Library/Caches/Kodi/userdata/addon_data/script.skinshortcuts/` |

## 1. Quick triage over JSON-RPC first (no pull needed)

Port 9090 is raw TCP JSON-RPC (curl to 8080 needs auth and the /vfs/ handler
is whitelist-blocked for logpath - do not fight it). One-liner pattern:

```python
import socket, json
s = socket.create_connection(("192.168.7.183", 9090), timeout=5)
s.sendall(json.dumps({"jsonrpc":"2.0","id":1,"method":"XBMC.GetInfoLabels",
  "params":{"labels":["System.FriendlyName","Skin.CurrentSkin","System.BuildVersion"]}}).encode())
print(s.recv(65536))
```

Useful: `Addons.GetAddonDetails` (installed versions), `Settings.GetSettingValue`
(webserver creds are readable). `Files.GetDirectory` REFUSES `special://` roots -
known, do not retry variants.

## 2. Pull the logs with devicectl (the recipe)

```bash
UDID=$(xcrun devicectl list devices 2>/dev/null | awk '/ATV2/{print $3}')
BUNDLE=ca.koditvbox.kodi.tvos.21
OUT=/tmp/atvlogs; mkdir -p "$OUT"

for f in kodi.log kodi.old.log; do
  xcrun devicectl device copy from --device "$UDID" --user mobile \
    --domain-type appDataContainer --domain-identifier "$BUNDLE" \
    --source "Library/Caches/$f" --destination "$OUT/atv2-$f"
done

# The key layer, for storage bugs:
xcrun devicectl device copy from --device "$UDID" --user mobile \
  --domain-type appDataContainer --domain-identifier "$BUNDLE" \
  --source "Library/Preferences/$BUNDLE.plist" --destination "$OUT/prefs.plist"
plutil -p "$OUT/prefs.plist" | grep userdata   # the /userdata/* keys
```

Flag traps (each one was hit for real):

- `copy from` takes **`--user mobile`**; `info files` takes **`--username mobile`**.
  Same tool, different flag names. A wrong one errors ("Unknown option").
- Tunnel errors (`CoreDeviceError 4000` / `RemotePairingError 1001`) are
  TRANSIENT on wireless tvOS pairings - retry up to 3 times before concluding
  anything.
- `device info files` output TRUNCATES on big trees; enumerate a narrow
  `--subdirectory`, and remember the LOG IS NOT IN THE SUBTREE YOU EXPECT:
  list the container ROOT to find `Library/Caches/kodi.log`.
- NEVER pass `--remove-existing-content true` to `copy to` (wipes the container).

## 3. Read the pulled logs correctly

- **Use `grep -a`.** A crashed session's log tail contains BINARY GARBAGE
  (heap bytes in the final error lines); plain grep silently treats the file
  as binary and prints nothing - that non-output has misled a session before.
- Session boundaries: each launch starts with
  `----------------------------------------------------------------------` +
  `Starting Kodi (...)`. `kodi.old.log` is the PREVIOUS session (the crashed
  one, usually the one you want); `kodi.log` is current.
- Crash signature: log ends abruptly mid-line, often after a storm of
  `SQLite error SQLITE_MISUSE` on `Textures13.db` (texture threads hitting a
  dying process) - that storm is FALLOUT, not the cause.
- The skin's own markers: `estuary7: customizeMenu rebuild fired`,
  `estuary7: syncMenu key=[...] posix=[...]`, `resetMenu: ...`,
  `ezmaintenanceplus: stale NSUserDefaults key purge ...`,
  `load skin from ... (version: X)` (= ReloadSkin / skin switch),
  `NSUSerDefaults: compressed ...` (= a key write; note the typo'd name).
- Startup logs the full `special:// is mapped to:` table - read paths from
  there, never assume.

## 4. Why not the EZM++ in-app log viewer

`logviewer.py` / `TextViewer.py` decode the log with STRICT UTF-8 and wrap
everything in `except: pass`. A crash-corrupted log (invalid UTF-8 in the tail)
makes both the viewer and the pastebin uploader die silently - exactly when you
need them most (root-caused 2026-07-17 on atv2's kodi.old.log, decode failure
at byte 230127). Until fixed with `errors="replace"`, pull logs with this skill
instead after any crash.

## Related

- `docs/playbooks/atv-kodi-xcode-cli-troubleshooting.md` - the full devicectl /
  unified-log / pymobiledevice3 toolbox (pushing files, plist diffing, §3a).
- `~/Code/moquette/kodi/.claude/skills/tvos-kodi-storage/SKILL.md` - what the
  pulled plist keys MEAN (the NSUserDefaults shadow model).
