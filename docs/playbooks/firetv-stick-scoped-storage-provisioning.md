# Provisioning a non-rooted Fire OS 8 / Android 11 Stick over ADB (scoped-storage relocation)

How the fleet provisioner (`_tools/provision-kodi.sh`) brings a **non-rooted Fire OS 8
(Android 11) Stick** (e.g. `AFTKRT` - Fire TV Stick 4K Max) to full parity with the
other boxes - wipe → install → Setup → MOD V2 + patch - entirely over adb, with no
rooting and no manual installs.

## TL;DR

A non-rooted Fire OS 8 / Android 11 Stick blocks adb from Kodi's data dir (scoped storage), so a
normal adb-push provision dies at "Library didn't land." The fix is the
**Jocala/adbLink data-relocation trick**: a one-line `/sdcard/xbmc_env.properties`
(`xbmc.data=/sdcard/kodi_data`) plus a `MANAGE_EXTERNAL_STORAGE` grant moves Kodi's
home into general `/sdcard` storage - which adb **can** write. The provisioner
auto-detects this from the device's `KODI_DATA_PATH` and sets it up for you.

## Why the normal provision fails

On Fire OS 11, `adb shell` (uid `shell`/2000) is locked out of Kodi's sandbox.
Verified dead-ends (run them yourself - `touch <path>/_wt`):

| Target                                             | adb (non-root)                                            |
| -------------------------------------------------- | --------------------------------------------------------- |
| `/sdcard/Android/data/org.xbmc.kodi/files/.kodi/…` | **denied** (FUSE scoped storage)                          |
| `/data/data` · `/data/user/0/org.xbmc.kodi`        | **denied** (needs root)                                   |
| `/mnt/{androidwritable,pass_through,installer}/…`  | **denied** (root-only ext4 mounts)                        |
| `run-as org.xbmc.kodi`                             | **denied** ("package not debuggable")                     |
| `su` · `adb root`                                  | **none** / "adbd cannot run as root in production builds" |
| `/sdcard/*` (general shared storage)               | **WRITABLE**                                              |

And it is **not rootable**: `ro.boot.verifiedbootstate=green`, `ro.secure=1`,
`ro.debuggable=0` (locked bootloader, production build). So the only adb-writable
place is general `/sdcard` - where Kodi doesn't keep its data… **until you relocate it.**

## The relocation (the unlock)

Kodi-on-Android reads `/sdcard/xbmc_env.properties` at startup and uses whatever
`xbmc.data=` points to as its home. Point it at general storage:

```bash
adb shell "mkdir -p /sdcard/kodi_data"
adb shell "printf 'xbmc.data=%s\n' /sdcard/kodi_data > /sdcard/xbmc_env.properties"
adb shell "cmd appops set --uid org.xbmc.kodi MANAGE_EXTERNAL_STORAGE allow"
adb shell "am force-stop org.xbmc.kodi"   # so it re-reads on next launch
```

On the next launch Kodi creates **`/sdcard/kodi_data/.kodi`** - adb-writable - and the
whole adb flow (wipe, seed `guisettings.xml`, push add-ons, push the per-device env)
now works exactly like a normal Android box.

> `xbmc.data=/sdcard/kodi_data` → Kodi nests `.kodi` **under** it, so the real data dir
> is `/sdcard/kodi_data/.kodi`. That nested path is the value `KODI_DATA_PATH` carries.

The per-device env + IPTV staging land at the **canonical device root**
`/storage/emulated/0/_T7B/kodi/` (N1.1, branch `no-computer-setup`) - general
shared storage, so it is adb-writable on every Stick **without** relocation; the
relocation above is needed only for Kodi's own data dir. The old
`/storage/emulated/0/kodi/tony.7.bones/` root is a read-only legacy fallback. A
device-resident master `.env.<device>` at that root is **never deleted** by Setup.

## Provisioner Fire-OS mode (automatic)

`_tools/provision-kodi.sh` does all of this from a single field in the per-device
`.env.<device>`:

```bash
# .env.travelstick
KODI_DATA_PATH="/sdcard/kodi_data/.kodi"   # outside Android/data => relocation
```

- `K="${KODI_DATA_PATH:-/sdcard/Android/data/${PKG}/files/.kodi}"` - the data dir.
- `RELOCATE` is inferred: `[[ "$K" == *Android/data* ]] || RELOCATE=1`.
- When `RELOCATE`, the **wipe step** writes `/sdcard/xbmc_env.properties`
  (`xbmc.data=$(dirname "$K")`) and grants `MANAGE_EXTERNAL_STORAGE` **before** it
  wipes/seeds/pushes - so everything lands where Kodi will actually read it.

Standard Android boxes (KODI_DATA_PATH inside `Android/data`) are untouched -
`RELOCATE` stays empty and no `xbmc_env.properties` is written.

## Gotchas (hard-won - don't relearn these)

1. **The first launch bounces to the Fire TV settings.** On the _first_ launch
   against a fresh relocated profile, Kodi requests all-files access and the box
   jumps to `com.amazon.tv.settings.v2/.tv.applications.ApplicationsActivity`; Kodi
   never finishes starting, so the provisioner's `kodi_up` poll times out and it
   bails at "Kodi didn't come up." **The `appops` grant _is_ sufficient** - the stuck
   settings task is the only blocker. Recovery: `am force-stop com.amazon.tv.settings.v2`
   then relaunch Kodi; it comes straight up (web server live, relocated profile
   initialised: `temp/`, `kodi.log`, `Database/` appear). The provisioner retries this
   automatically on a relocated device.

2. **"No signal" / the TV switches inputs.** When the Setup flips the skin to MOD V2
   (or any display-mode change), the Stick renegotiates HDMI and some TVs auto-switch
   inputs on the brief signal drop. Not a failure - switch the TV back to the Stick's
   HDMI input. adb is over the network, so you can diagnose the Stick regardless of
   what the TV shows.

3. **The Android "restart" = force-stop + relaunch.** Kodi can't self-restart on
   Android. The skin choice persists via `lookandfeel.skin` in `guisettings.xml`, so
   `am force-stop org.xbmc.kodi` + relaunch boots straight into MOD V2, and the
   modv2plus boot service applies the patch (~60-90 s; a brief screen freeze during
   its skin reload is normal - confirm liveness with a `JSONRPC.Ping`, not the screen).

4. **Self-uninstall + the sdcardfs `rm` quirk.** Force-stopping mid-Setup interrupts
   the bootstrap's self-uninstall, leaving `addons/script.tony7bones.bootstrap`.
   Deleting it over adb is flaky: `rm -rf` returns `rc=0` but `ls -d` can still show a
   contentless **phantom dir entry** for a beat (FUSE cache lag) even though the files
   are gone. Don't trust `ls` here - verify via **Kodi**: `Addons.GetAddonDetails` for
   `script.tony7bones.bootstrap` returning an `error` (add-on unknown) is the real
   "uninstalled" signal. If it's still a known add-on, `Addons.SetAddonEnabled …
enabled=false` is the clean fallback - a disabled add-on shows no home tile and
   never runs (functionally uninstalled), no flaky delete required.

5. **IPTV verification tag.** pvr.iptvsimple custom groups use `<channelGroupName>`,
   **not** `<name>` - grep the right tag or you'll read 0 groups when 3 actually landed.

## First-boot verification (against the relocated dir)

`K=/sdcard/kodi_data/.kodi`; drive via the box's web server (seeded on by the wipe).

- **Relocation took:** `cat /sdcard/xbmc_env.properties` == `xbmc.data=/sdcard/kodi_data`;
  `$K/temp/kodi.log` exists; `touch $K/_wt` is WRITABLE.
- **MOD V2 + patch:** `GUI.GetProperties skin` == `skin.estuary.modv2`;
  `grep show_system_info_overlay $K/addons/skin.estuary.modv2/xml/Home.xml`.
- **Look settings (first boot, no manual Apply):** `$K/userdata/addon_data/skin.estuary.modv2/settings.xml`
  has `show_weatherinfo=true`, `WeatherIcons.path` = outline-hd,
  `enable_{power,settings,search}_background=true`, `powermenu_list=true`.
- **Env config:** weather `loc[1-5]_name` (5), `RssFeeds.xml` `<feed` count,
  IPTV `instance-settings-1.xml` (`tvGroupMode=2`, m3u/EPG URLs) +
  `channelGroups/customTVGroups-*.xml` `<channelGroupName>` count.
- **Core:** `services.devicename`, `addons.unknownsources=true`, `addons.updatemode=1`.
- **Setup gone:** `addons/script.tony7bones.bootstrap` absent.

## Sources

- adbLink "Scoped Storage" - <https://www.jocala.com/android11.html>
- AFTVnews, Kodi full file access on Fire OS 8 -
  <https://www.aftvnews.com/the-best-way-to-install-kodi-with-full-file-access-on-a-fire-os-8-device-like-the-2nd-gen-fire-tv-stick-4k-4k-max/>
