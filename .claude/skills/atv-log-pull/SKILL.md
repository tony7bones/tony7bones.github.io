---
name: atv-log-pull
description: Pull and read Kodi logs (kodi.log, kodi.old.log, NSUserDefaults plist) from a fleet Apple TV over the network - no adb exists on tvOS. Use when diagnosing any ATV crash, skin failure, or storage bug, when the user says "check the ATV logs", or when the EZM++ in-app log viewer cannot be used (it dies silently on crash-corrupted logs). Proven end-to-end on atv2 2026-07-17.
---

# Pull Kodi logs from an Apple TV (no adb on tvOS)

## STOP. Read this before you report that something cannot be done.

This box IS reachable. The tooling DOES cover crash reports, jetsam kills,
settings, the key layer, and the logs. Every "it is not supported" and "there is
no way to" written about this device so far has been **wrong**, and each one was
written by someone who stopped after a single failed command.

You are not allowed to conclude failure until you have done all four:

1. **Retried the exact same command three times**, with a short sleep. Wireless
   tvOS pairings throw `RemotePairingError 1001` and `CoreDeviceError 1011` on a
   perfectly healthy box. First attempt failing means nothing.
2. **Checked the flags against the subcommand.** `copy from` takes `--user`.
   `info files` takes `--username`. Same tool. Wrong one gives
   `Error: Unknown option`, which is NOT the same as unsupported.
3. **Run `xcrun devicectl <subcommand> --help` and read the valid values.**
   `systemCrashLogs` was sitting in that help text the whole time a session
   spent declaring crash reports unreachable.
4. **Read this whole file AND
   `docs/playbooks/atv-kodi-xcode-cli-troubleshooting.md` §5.** A 2026-07-18
   session announced a documentation gap twice in one hour. Both recipes it said
   were missing were already written down.

"Connection refused" on port 9090 is not a dead box either: tvOS suspends
background apps, so Kodi only answers JSON-RPC while foregrounded. Use
`devicectl`, which reads the container whether Kodi is running or not.

A negative result is only worth something if you actually looked. Reporting "I
could not get it" when the recipe exists wastes the owner's time and teaches the
next agent the same wrong lesson.

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

## 5. Crash reports and jetsam (memory kills) - NO sudo needed

Added 2026-07-18 after a session wasted time concluding "the tooling does not
cover crash reports". It does, twice over, and the easy route is not the one
documented in the troubleshooting playbook's §5.

`devicectl` has a **`systemCrashLogs`** domain. It needs no root, no tunnel
daemon, and no `pymobiledevice3`. It reuses the pairing you already have.

```bash
UDID=$(xcrun devicectl list devices 2>/dev/null | awk '/ATV2/{print $3}')
OUT=/tmp/atvcrash; mkdir -p "$OUT"

# 1. LIST (note: info files takes --username)
xcrun devicectl device info files --device "$UDID" --username mobile \
  --domain-type systemCrashLogs > "$OUT/list.txt"

# 2. What is there
grep -ioE "JetsamEvent-[0-9.-]+\.ips" "$OUT/list.txt" | sort -u   # memory kills
grep -ioE "Kodi-[0-9.-]+\.ips"        "$OUT/list.txt" | sort -u   # Kodi crashes

# 3. PULL (note: copy from takes --user, NOT --username)
xcrun devicectl device copy from --device "$UDID" --user mobile \
  --domain-type systemCrashLogs --source "JetsamEvent-2026-07-11-135709.ips" \
  --destination "$OUT/jetsam1.ips"
```

**Reading a jetsam report.** It lists every process the kernel jettisoned in
that event. Search it for the app name:

```bash
grep -oic 'kodi' "$OUT/jetsam1.ips"
```

- **Non-zero** means Kodi WAS memory-killed. Look for `reason` (per-process-limit
  = it breached its own high-water mark; vm-pageshortage = system-wide pressure)
  and for `ActiveHardMemoryLimit`, which is the only reliable way to learn the
  real per-app ceiling on this hardware. Apple does not publish it for Apple TV.
- **Zero** means Kodi was NOT a victim of that event, so a crash at a nearby
  timestamp is a code bug, not memory. That is a genuine negative result and it
  closes the memory hypothesis; do not keep chasing it.

A jetsam SIGKILL leaves NO Kodi-side trace at all: `kodi.log` just stops
mid-line, which looks identical to a power cut. So the crash report store is the
only place the distinction exists. Conversely, if `kodi.old.log` ends with the
orderly `unload skin` / `Unloaded skin` / `Exiting the application...` sequence,
that session did NOT crash, and no jetsam pull is needed to prove it.

## Do not give up early: the three failure modes that look terminal

Every one of these has already cost a session. None of them means "it cannot be
done".

1. **Tunnel errors are transient, and they are LOUD.**
   `RemotePairingError 1001`, `CoreDeviceError 4000`, `CoreDeviceError 1011`
   ("unable to locate a device matching the requested device identifier") all
   appear on a healthy, paired, powered-on box. **Retry three times with a short
   sleep before concluding anything.** On 2026-07-18 attempt 1 failed with 1001
   and attempt 2 succeeded immediately, same command, no change.

2. **The flag names differ between sibling subcommands.**
   `copy from` takes `--user mobile`. `info files` takes `--username mobile`.
   Passing the wrong one gives `Error: Unknown option`, which reads like the
   feature is missing. It is not. This trap was already documented for log
   pulls, and it bit again on `systemCrashLogs`.

3. **"The tooling does not support X" is almost always wrong here.**
   Before writing that sentence, read BOTH
   `docs/playbooks/atv-kodi-xcode-cli-troubleshooting.md` (its §5 already had a
   `pymobiledevice3 crash pull` recipe) AND `devicectl <subcommand> --help`
   (which lists `systemCrashLogs` as a valid domain). A 2026-07-18 session
   declared a documentation gap that did not exist, twice, in the same hour.

Also: `pymobiledevice3 remote browse` and `remote tunneld` require root, and the
Apple TVs do NOT appear in `pymobiledevice3 usbmux list` because tvOS 17+ pairs
over RemoteXPC. That is expected, not a fault. Prefer `devicectl` on macOS and
keep `pymobiledevice3` for Linux hosts or when `devicectl` genuinely stalls.

## What lives where on the box (verified 2026-07-18)

`guisettings.xml` is often ABSENT as a POSIX file in the container
(`Failed to retrieve the file node`). That is correct behaviour, not a broken
pull: on tvOS the NSUserDefaults key SHADOWS the file. Read settings from
`Library/Preferences/<bundle>.plist` with `plutil -p`, not from userdata.
See the `tvos-kodi-storage` skill for what the keys mean.

## Related

- `docs/playbooks/atv-kodi-xcode-cli-troubleshooting.md` - the full devicectl /
  unified-log / pymobiledevice3 toolbox (pushing files, plist diffing, §3a).
- `~/Code/moquette/kodi/.claude/skills/tvos-kodi-storage/SKILL.md` - what the
  pulled plist keys MEAN (the NSUserDefaults shadow model).
