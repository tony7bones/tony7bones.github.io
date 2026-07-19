---
name: atv-log-pull
description: Reach a fleet Apple TV over the network - pull Kodi logs, crash and jetsam reports, read any setting without Kodi running, LAUNCH Kodi, deploy files, and read code back off the box. No adb exists on tvOS. Use for any ATV crash, skin failure, storage bug, deploy, or verification, and BEFORE concluding an Apple TV is unreachable - it almost never is. Covers the bundle-id trap (-10814), the Library/Caches container path, reboot-to-wake, and the two silent copy-to traps. Proven on atv1 and atv2 2026-07-17 through 2026-07-19.
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

## 6. Read ANY Kodi setting off an Apple TV without Kodi running

Proven on both atv1 and atv2, 2026-07-18. This is the workaround for the fact
that tvOS suspends background apps, so JSON-RPC on 9090 is refused whenever
Kodi is not foregrounded. `devicectl` reads the container regardless.

**The trick: `guisettings.xml` is vectored into the NSUserDefaults key store AND
GZIP COMPRESSED inside the key.** Reading it with `plutil -p` shows only binary.
That compression is the `NSUSerDefaults: compressed` log line (note the
upstream typo in the name).

```bash
UDID=$(xcrun devicectl list devices 2>/dev/null | awk '/ATV1/{print $3}')
BUNDLE=ca.koditvbox.kodi.tvos.21
OUT=/tmp/atvcfg; mkdir -p "$OUT"

xcrun devicectl device copy from --device "$UDID" --user mobile \
  --domain-type appDataContainer --domain-identifier "$BUNDLE" \
  --source "Library/Preferences/$BUNDLE.plist" --destination "$OUT/prefs.plist"
```

```python
import plistlib, gzip, re
with open("/tmp/atvcfg/prefs.plist", "rb") as f:
    d = plistlib.load(f)
s = gzip.decompress(d["/userdata/guisettings.xml"]).decode("utf-8", errors="replace")
m = re.search(r'<setting id="filecache\.memorysize"([^>]*)>([^<]*)</setting>', s)
print(m.group(2))
```

A `<setting .../>` self-closing form means EMPTY, and a `default="true"`
attribute means Kodi is using its built-in default rather than a chosen value.
Both distinctions matter and neither is visible over JSON-RPC.

The same plist lists every vectored `/userdata/*` path, which is the fastest way
to see what the tvOS key layer is actually shadowing.

### DO NOT write settings back this way

You can decompress, edit, recompress and `copy to`. **It will be silently
clobbered.** A suspended Kodi still holds its settings in memory, and on resume
or clean shutdown `CApplication::Stop` -> `SaveSettings` serializes that memory
over the store. This is the documented settings-clobber class
(`docs/playbooks/kodi-settings-clobber.md`); writing the key while Kodi lives is
instance N+1 of it.

To CHANGE a setting on an Apple TV: foreground Kodi on the TV, then set it live
over JSON-RPC so the in-memory copy is the one that persists.

## Fleet values read this way, 2026-07-18

Recorded because they answered questions that had been guessed at for days.
Both Apple TVs are identical:

| Setting | atv1 | atv2 |
| --- | --- | --- |
| `debug.screenshotpath` | EMPTY | EMPTY |
| `filecache.memorysize` | 200 | 200 |
| `filecache.readfactor` | 400 (default) | 400 (default) |
| `services.webserver` | true | true |
| `lookandfeel.skin` | skin.estuary7 | skin.estuary7 |

`services.webserver` being true on both proves the JSON-RPC refusals are purely
the tvOS suspend lifecycle, not a config problem. The empty screenshot path is
the confirmed trigger for the screenshot reentrancy crash class.

## What lives where on the box (verified 2026-07-18)

`guisettings.xml` is often ABSENT as a POSIX file in the container
(`Failed to retrieve the file node`). That is correct behaviour, not a broken
pull: on tvOS the NSUserDefaults key SHADOWS the file. Read settings from
`Library/Preferences/<bundle>.plist` with `plutil -p`, not from userdata.
See the `tvos-kodi-storage` skill for what the keys mean.

## 7. Launch Kodi, deploy to the box, and read code back (2026-07-19)

Everything above reads. This section covers RUNNING the app and PUTTING FILES on
the box. Learned the hard way in one session; each item cost real time.

### The bundle id is NOT `org.xbmc.kodi`

The fleet's Apple TVs run a KodiTVBox sideload:

```
ca.koditvbox.kodi.tvos.21
```

Launching `org.xbmc.kodi` returns **OSStatus -10814**, which reads like a
permission or sleep problem and actually means "application not found". Do not
diagnose sleep from it. Enumerate first, every time:

```bash
xcrun devicectl device info apps --device "$UDID" | grep -i kodi
```

### Kodi's tree is at `Library/Caches/Kodi/`, not `Documents/.kodi/`

Probing the Documents path returns `CoreDeviceError 7000`, which looks like "the
file is missing" or "the deploy never landed". List instead of guessing:

```bash
xcrun devicectl device info files --device "$UDID" \
  --domain-type appDataContainer --domain-identifier ca.koditvbox.kodi.tvos.21
```

Two consequences: everything Kodi owns lives under a directory tvOS may purge
under storage pressure, and `guisettings.xml` does **not** exist on disk there -
it is NSUserDefaults-shadowed (section 6 reads it correctly).

### An asleep Apple TV refuses a foreground launch - reboot wakes it

A launch against a sleeping box returns `RequestDenied`
(`FBSOpenApplicationServiceErrorDomain error 1`). Apple TVs ignore Wake-on-LAN
and `devicectl` has no wake verb. What works:

```bash
xcrun devicectl device reboot --device "$UDID"
# device goes "unavailable" for ~1 minute
until xcrun devicectl list devices | grep -i "^ATV2" | grep -qi available; do sleep 10; done
# then retry the launch a few times while the tunnel re-establishes
xcrun devicectl device process launch --device "$UDID" ca.koditvbox.kodi.tvos.21
```

Non-destructive. Verified on atv1 and atv2.

### JSON-RPC answers ONLY while Kodi is foregrounded

tvOS suspends background apps. "Port 8080 closed" nearly always means "Kodi is
not in the foreground", not "no route to this box". Launch it first, then query.
Credentials `kodi`/`kodi`, port 8080.

### `devicectl device copy to` has two SILENT traps

1. **A directory destination silently no-ops.** Pass the FULL destination path
   including the target directory name.
2. **It silently refuses to OVERWRITE an existing file**, reporting success
   either way. Writing to a NEW filename works fine. Proven: a probe under a new
   name landed as the new version while `addon.xml` stayed on the old one across
   nine attempts, single-file and directory, with Kodi stopped and after a reboot.

So: **always read a CODE file back off the box** to confirm a deploy. A bumped
`addon.xml` version proves nothing - the manifest can move while the code does
not. If you must replace files and overwrite is refused, the supported route is
Kodi's own repository update, not `copy to`.

### Error codes are distinct - read them, do not guess

| Code | Means |
| --- | --- |
| `OSStatus -10814` | wrong bundle id (NOT sleep) |
| `RequestDenied` / `FBSOpenApplicationServiceErrorDomain error 1` | box is asleep |
| `error 10002` | launch failed for another reason |
| `CoreDeviceError 1011` | device not locatable right now - retry, tunnel is down |
| `CoreDeviceError 4000` | connectivity interrupted mid-operation |
| `CoreDeviceError 7000` | path does not exist in that container |

### Screenshots are genuinely impossible on tvOS

`WinSystemTVOS.mm` never calls `CScreenshotSurfaceGLES::Register()`, unlike
`WinSystemIOS.mm`, `WinSystemAndroid.cpp` and the GBM/Wayland GLES backends. So
Kodi's own screenshot is unregistered there and Apple TVs have no adb. This is
the one ATV gap that is real. Report it as NOT PROVEN with this citation rather
than substituting an XML check and calling it visual proof.

### Reading state needs NO launch, NO foreground, NO reboot (added by qa-skin)

The `appDataContainer` domain reads version, `addon_data` DATA files and the
active includes with Kodi SUSPENDED. For read-only fleet state this is strictly
better than JSON-RPC: no wake, no reboot, no taking over a screen in someone's
house. Reach for `copy from` first and only foreground Kodi when you genuinely
need a live query.

Corollary, and this is the mistake that cost hours: **a closed port 8080 means
"Kodi is not foregrounded", NOT "no path to this box".** Treating one failed
probe as proof of absence is how both Apple TVs were reported unreachable all
session while a container read would have answered every question.

### `CoreDeviceError 1011` is often transient on first contact

A box can show `available (paired)` in `devicectl list devices` and still throw
1011 on the first real request - the tunnel establishes lazily. One retry clears
it. So "available" is necessary but not sufficient: probe with a cheap REAL
command (`device info apps`) and poll on ITS success, not on the state string.

### Retry loops built on fast-failing commands do not wait

25 launch attempts against an absent device fail instantly and look like 25 real
tries. Poll for the state you need (`devicectl list devices` for `available`),
do not just repeat the command.

### Stale `__pycache__` cannot be removed with devicectl

Observed on atv2. `devicectl` has no delete verb, so bytecode left by a previous
build stays. An add-on can remove its own `__pycache__` in-process at startup;
nothing external can. Relevant because CPython invalidates a `.pyc` on the
source's mtime AND size, and deterministic builds stamp a fixed timestamp, so a
same-length edit can leave stale bytecode executing.

## Related

- `docs/playbooks/atv-kodi-xcode-cli-troubleshooting.md` - the full devicectl /
  unified-log / pymobiledevice3 toolbox (pushing files, plist diffing, §3a).
- `~/Code/moquette/kodi/.claude/skills/tvos-kodi-storage/SKILL.md` - what the
  pulled plist keys MEAN (the NSUserDefaults shadow model).

### CORRECTION 2026-07-19: copy-to overwrite behaviour

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
