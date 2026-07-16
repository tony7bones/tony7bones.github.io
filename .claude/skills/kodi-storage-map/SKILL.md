---
name: kodi-storage-map
description: >-
  The authoritative map of WHERE Kodi stores files on each OS (tvOS/Apple TV vs
  Android/Fire TV vs Linux/macOS/Windows), what tvOS vectors into NSUserDefaults
  and by what exact rule, what survives a Caches purge, and which API (xbmcvfs vs
  plain open) to use for each class of file. Load BEFORE writing, deleting,
  backing up, restoring, or reading ANY file under special://home,
  special://profile, special://userdata, special://temp, or addon_data - and
  ALWAYS before touching tvOS/Apple TV. Triggers on: Apple TV, tvOS,
  NSUserDefaults, special:// path, userdata, addon_data, backup, restore,
  "settings revert", "menu reset", duplicate File Manager entries, "file exists
  but won't read", blank image/ControlImage, Caches purge, size limit.
---

# Kodi storage map: tvOS is NOTHING like Fire TV

Every repeated data-loss burn in this project traces to one fact: **Apple TV stores
Kodi's files somewhere fundamentally different from every other platform.** Code
correct on Fire TV can silently destroy data on tvOS.

Citations verified line-by-line against `github.com/xbmc/xbmc`, branch **Omega** (Kodi 21).

## RULE ZERO

**Where a value is stored is a per-platform question. Do not assume the filesystem
is the store.** And: **"fixed" means verified on the affected device class, not
verified in code.** Apple TV has NO adb - verify via the Xcode/`devicectl` route
(`docs/playbooks/atv-kodi-xcode-cli-troubleshooting.md`).

---

## 1. The model in one paragraph

On **tvOS**, Apple prohibits writing to `Documents`, so Kodi puts its **entire home
tree inside `Library/Caches`** - which the OS may **purge**. To survive that, Kodi
vectors **`.xml` files under `userdata/`** into **NSUserDefaults** (backing store:
`Library/Preferences/<bundleid>.plist` - a **different domain**, NOT purged with
Caches). Reads check the **key FIRST**, disk only as fallback - so **a key SHADOWS
the disk file**. On **Android/Fire TV**, `special://home` is ordinary persistent app
storage and **none** of this machinery exists.

> **Kodi NEVER rewrites disk from the mirror.** Several of our own older docs claim it
> does. They are WRONG. `MigrateUserdataXMLToNSUserDefaults` (`PreflightHandler.mm:81-93`)
> returns early forever once `UserdataMigrated` is set, and nothing copies a key back to
> disk. Settings "revert" because the stale key **shadows** the restored file.

---

## 2. Paths per OS

| special://                   | tvOS                                                                                                         | Android (Fire TV)                              | Linux         | macOS                                | Windows              |
| ---------------------------- | ------------------------------------------------------------------------------------------------------------ | ---------------------------------------------- | ------------- | ------------------------------------ | -------------------- |
| `home`                       | **`$HOME/Library/Caches/Kodi`**                                                                              | `getExternalFilesDir()/.kodi` (**persistent**) | `~/.kodi`     | `~/Library/Application Support/Kodi` | `%APPDATA%\Kodi`     |
| `masterprofile` / `userdata` | `<home>/userdata` (**always the MASTER profile**)                                                            | same                                           | same          | same                                 | same                 |
| `profile`                    | the **ACTIVE** profile's dir - equals masterprofile ONLY on a single-profile box (true for this fleet today) | same                                           | same          | same                                 | same                 |
| `database`, `thumbnails`     | `<profile>/Database`, `/Thumbnails`                                                                          | same                                           | same          | same                                 | same                 |
| `temp`                       | `<home>/temp`                                                                                                | Android **cache dir** (OS-clearable)           | `<home>/temp` | `<home>/temp`                        | `<winprofile>/cache` |
| `logpath`                    | **`$HOME/Library/Caches`** - _ONE LEVEL ABOVE `home`_, NOT inside it                                         | as temp                                        | as temp       | `~/Library/Logs`                     | `<winprofile>`       |
| `skin`                       | **dynamic** - the ACTIVE skin's install dir                                                                  | same                                           | same          | same                                 | same                 |
| `addons`                     | **NOT A ROOT** -> resolves to an **empty string**                                                            | same                                           | same          | same                                 | same                 |

- tvOS `Library/Caches` applies when **sandboxed** (true for every real install);
  the non-sandboxed branch uses `Library/Preferences` (`DarwinEmbedUtils.mm:16-41`).
- Real addon roots: **`special://home/addons`** (user-installed) and
  **`special://xbmcbinaddons`** / `xbmcaltbinaddons` (bundled). Note `addons://`
  (no `special://`) is a **different, real** VFS protocol for the addon browser.
- **Fire TV scoped storage:** on Fire OS 11 sticks the data dir is relocated off
  `Android/data` to `/sdcard` - see `docs/playbooks/firetv-stick-scoped-storage-provisioning.md`.

Sources: `DarwinEmbedUtils.mm:16-41`, `TVOSFileUtils.mm:18-43`, `SettingsComponent.cpp`
(per-platform setters; tvOS logpath ~:325), `XBMCApp.cpp:1660-1692` (Android),
`ProfileManager.cpp:643-675`, `SpecialProtocol.cpp:106-206`.

---

## 3. The tvOS vectoring rule (ENGINE ELIGIBILITY - exact)

```cpp
// TVOSFile.cpp:39-45
bool CTVOSFile::WantsFile(const CURL& url)
{
  if (!StringUtils::EqualsNoCase(url.GetFileType(), "xml") ||
      StringUtils::StartsWithNoCase(url.GetFileNameWithoutPath(), "customcontroller.SiriRemote"))
    return false;
  return CTVOSNSUserDefaults::IsKeyFromPath(url.Get());   // path under <home>/userdata
}
```

**ELIGIBLE = `.xml` (last-dot, case-insensitive) AND filename does NOT start with
`customcontroller.SiriRemote` AND path is under `<home>/userdata` - AT ANY DEPTH.**

> **There is NO `settings.xml` carve-out in the engine.** `addon_data/<id>/*.DATA.xml`,
> `advancedsettings.xml`, `keymaps/*.xml` are ALL eligible. A key is only _created_ when
> something **writes through the VFS**. "Not vectored" is a property of **who wrote it**,
> never of the file's name.

Non-`.xml` (`.db`, `.hash`, `.properties`, images) is **never** eligible.

### Reads: key FIRST (the shadow)

```cpp
// TVOSFile.cpp:113-122
bool CTVOSFile::Exists(const CURL& url) {
  bool ret = CTVOSNSUserDefaults::KeyFromPathExists(url.Get());   // KEY FIRST
  if (!ret) { CPosixFile posix; ret = posix.Exists(url); }        // disk fallback
  return ret; }
```

`Open()` is the same shape. **`xbmcvfs.exists()` can return True off a key while the
disk file is stale or gone.**

### Writes: NSUserDefaults ONLY - no POSIX fallback, silent failure

`OpenForWrite` (`TVOSFile.cpp:87-99`) returns **`false`** if a key exists and
`bOverWrite` is false; `Write()` goes straight to `SetKeyDataFromPath` - **disk is never
touched.** **Check the return value.** Once a path is vectored, Kodi's own future _writes_
also never reach disk again.

### One write per file - NEVER chunk

`SetKeyData` **fully replaces** the key on every call. `Seek()` is disabled
(`TVOSFile.cpp:214-221`), `GetChunkSize()` returns the whole file. A chunked loop leaves
**only the last chunk** = truncated XML = settings reset to defaults.

### Directory listings do NOT dedupe

`CTVOSDirectory::GetDirectory` (`TVOSDirectory.cpp:48-106`) lists POSIX files then
`items.Add()`s every key with no membership check -> a file present in **both** layers is
listed **TWICE** (fires only where a POSIX file and a key coexist - typically post-restore
drift).

### The size limit is a KILL, and it's the WHOLE database

Apple (`UserDefaults.sizeLimitExceededNotification`), verbatim:

> _"In tvOS, the system posts this notification as a warning when the size of your app's
> defaults database reaches **512 kilobytes**. If your app continues to write to the
> defaults database, the system **terminates your app** when the database reaches or
> exceeds **1 megabyte** in size."_

(The older Apple TV Programming Guide states a ~500 KB local-storage limit - same ballpark.)
It is **cumulative across every key**, gzip-compressed (`SetKeyData`). **Kodi has no size
check and registers no observer.** Overflow = **Kodi killed on launch**. Never vector
growable data, and remember every add-on's settings shares this budget.

---

## 4. What survives a Caches purge

| Tier                                                                                                            | Location                               | Survives?                  |
| --------------------------------------------------------------------------------------------------------------- | -------------------------------------- | -------------------------- |
| Vectored `.xml` keys                                                                                            | `Library/Preferences/<bundleid>.plist` | **YES** - different domain |
| Everything else: `.db` (MyVideos, Textures, ViewModes), thumbnails, addon binaries, non-xml `addon_data`, skins | `Library/Caches/Kodi`                  | **NO - GONE, permanently** |

`CheckForRemovedCacheFolder` (`PreflightHandler.mm:65-79`) is Kodi's own acknowledgement;
its body is a stub (`//!@todo`) that never even checks whether the folder exists. **There
is no recovery.** After a purge: settings/sources/profiles come back from the keys; the
**entire library, watched status, resume points, thumbnails and add-ons are gone.**

> **"The backup" means OUR tool (EZ Maintenance++), never an Apple device backup** - Apple
> excludes `Library/Caches` from iCloud/Finder backups, so a stock Apple TV backup captures
> **none** of it.

### Therefore: a correct tvOS BACKUP must read BOTH layers

A filesystem-only walk **silently misses every setting** (that is
`incident-2026-07-08-ezmpp-atv-settings-nsuserdefaults.md`). A correct backup:

1. decodes the **NSUserDefaults plist** for every vectored `.xml`, **and**
2. separately walks the POSIX `Library/Caches/Kodi` tree for everything else.

---

## 5. ⚠️ DROPPING THE POSIX COPY HAS **ZERO** FALLBACK

Our shipped `nsud` drops the POSIX shadow after vectoring (to fix duplicate File Manager
entries). The old justification - _"Kodi re-materializes the disk file from the mirror on
the next launch"_ - **is FALSE** (§1). Once dropped, that setting exists **only** as one
NSUserDefaults key. If the key is ever lost - app reinstall, a budget overflow, an eviction,
any reset flow - **the data is gone, permanently, with no disk copy to recover from.**

This is a **conscious trade** (a cosmetic duplicate listing vs. a structural no-fallback
risk), not a self-healing state. Treat any expansion of what we vector as a decision that
spends the 512 KB / 1 MB budget.

---

## 6. API decision table

| File class                                                                                              | Who READS it                                                                  | Read with               | Write with              | May drop POSIX copy?                                                                                                                                       |
| ------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------- | ----------------------- | ----------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------- |
| top-level `userdata/*.xml` (guisettings, sources, profiles, favourites, RssFeeds, **advancedsettings**) | Kodi core (`XFILE::CFile`)                                                    | `xbmcvfs`               | `xbmcvfs`, ONE call     | Only with §5 understood                                                                                                                                    |
| `addon_data/<id>/settings.xml`, `instance-settings-*.xml`                                               | Kodi core addon-settings framework (`Addon.cpp` -> `CXBMCTinyXML` -> `CFile`) | `xbmcvfs`               | `xbmcvfs`               | Only with §5 understood                                                                                                                                    |
| `keymaps/*.xml` (custom)                                                                                | Kodi core                                                                     | `xbmcvfs`               | `xbmcvfs`               | Only with §5 understood                                                                                                                                    |
| **`customcontroller.SiriRemote*.xml`**                                                                  | Kodi, via **CPosixFile** (excluded from `WantsFile`)                          | plain                   | plain                   | **NEVER.** An `xbmcvfs` write is a POSIX round-trip that _always_ "confirms" while **nothing reaches NSUserDefaults** - dropping it deletes the only copy. |
| other `addon_data/<id>/*` (skinshortcuts `*.DATA.xml`, `.properties`, `.hash`)                          | **the add-on itself**                                                         | _match the owner's API_ | _match the owner's API_ | **NEVER drop, and do NOT vector.** Eligible, but the owner reads with plain `open()`: a key it can't see + a deleted disk file = data gone.                |
| a local file **we** wrote with plain Python (`zipfile`/`open`)                                          | us                                                                            | **plain `open()`**      | -                       | Kodi's VFS silently returns **EMPTY** reads for a local file a non-VFS writer produced.                                                                    |
| an image shown via **`ControlImage`**                                                                   | Kodi's **texture loader**                                                     | -                       | **`xbmcvfs`**           | Must write **THROUGH** `xbmcvfs` or the loader reads nothing. Also: 32-bit PNG + a **fresh filename**.                                                     |

**Proven vs assumed:** the `WantsFile`/`CTVOSFile` mechanism is universal engine behavior.
_Which_ API a given add-on uses is **per-add-on** - confirmed by reading code only for
`script.skinshortcuts` (Python, plain `open()`). A binary add-on's `kodi::vfs::CFile`
bridges into the **same** VFS. **Verify per add-on.**

---

## 7. THE FOUR tvOS I/O BUGS - THEIR FIXES ARE OPPOSITE

Do **not** collapse these into one "avoid mixed mode" rule. A blanket "prefer plain
`open()`" fixes 1/3/4 and **BREAKS 2**.

| #   | Bug                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                          | Fix                                                                                                                                                                                                                |
| --- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| 1   | **NSUserDefaults shadow.** A key shadows the disk file, so `xbmcvfs` sees one thing and plain `open()` another. Vectoring + deleting the POSIX copy made skinshortcuts' `xbmcvfs.exists()` pass and its `ETree.parse()` fail -> silent fallback to the skin's DEFAULT menu.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                  | **Match the layer the real consumer reads.** Owner uses plain `open()` -> keep a POSIX copy, don't vector.                                                                                                         |
| 2   | **ControlImage / texture.** An image written with plain `open()` is **invisible** to Kodi's texture loader -> blank. (The Dropbox QR barcode.)                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                               | **WRITE THROUGH `xbmcvfs`** - the OPPOSITE of 1.                                                                                                                                                                   |
| 3   | **VFS can't read foreign local files.** `xbmcvfs` read of a file _we_ wrote with plain `open()`/`zipfile` returns **0 bytes** while `Stat()` reports the right size.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                         | **Read local paths with plain `open()`.**                                                                                                                                                                          |
| 4   | **`xbmcvfs.delete()` CANNOT delete a userdata `*.xml` on tvOS.** It drops the NSUserDefaults key and reports success; the POSIX file is left on disk, silently, forever. Traced 2026-07-14 from source (`xbmc@f8815ee4`): `CTVOSFile::Delete` (`TVOSFile.cpp:101-111`) is `DeleteKeyFromPath(); if (!ret) POSIX-delete`, but `DeleteKey` (`TVOSNSUserDefaults.mm:188-202`) does `removeObjectForKey` (a silent no-op when absent) and then `return [defaults synchronize] == YES` - **true whether or not a key existed**. So `if (!ret)` is UNREACHABLE for exactly the files `CTVOSFile` is dispatched for (`FileFactory.cpp:117` gates on `WantsFile`). The POSIX-delete "fallback" only ever fires for paths OUTSIDE userdata. This is what broke the Estuary 7 main-menu **reset** (stale content, not a missing file). | **Verify with the SAME API the consumer uses.** Never trust the boolean - it is true even when nothing happened. To really remove such a file, use `os.remove` on the translated real path (and drop the key too). |

**The unifying rule is ORIGIN-based, not "prefer POSIX":**

> **Read a file through the SAME layer it was WRITTEN through. When creating a new file any
> Kodi-internal reader might touch, default to writing it THROUGH `xbmcvfs`.**

---

## 8. Known UPSTREAM Kodi bugs (not ours)

- `MigrateUserdataXMLToNSUserDefaults` (`PreflightHandler.mm:141-174`) calls
  `srcfile.Delete(srcUrl)` **unconditionally after the copy loop**, with no flag
  distinguishing a clean EOF from an error `break` -> **deletes the source even if the copy
  failed.** If `UserdataMigrated` is ever cleared, this re-runs over **every** `.xml`.
- `CheckForRemovedCacheFolder` never checks whether the folder exists; recovery is an
  unimplemented `//!@todo`, while its call site comment claims it "will trigger the restore."

---

## 9. Symptom -> cause (Apple TV)

| Symptom                                              | Cause                                                                                                                                                                                   |
| ---------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Settings revert after reopening Kodi                 | Restored files written POSIX-only; a stale key **shadows** them. Vector them through `xbmcvfs`.                                                                                         |
| Every userdata file listed **twice** in File Manager | File exists in BOTH layers; `GetDirectory` doesn't dedupe.                                                                                                                              |
| Main menu resets to the shipped default              | An `addon_data/script.skinshortcuts/*.DATA.xml` was vectored **and its POSIX copy deleted** -> `xbmcvfs.exists()` passes, plain-`open()` read fails, falls through to the skin default. |
| A "reset" appeared to work but nothing changed       | Bug 4 - `xbmcvfs.delete`/`copy` false success on a `special://` path.                                                                                                                   |
| "File exists but reads empty / won't parse"          | Wrong layer (see §7), or the VFS reading a plain-written local file.                                                                                                                    |
| A generated image renders blank                      | Written with plain `open()`; and/or grayscale PNG; and/or a reused filename.                                                                                                            |
| **Kodi killed on launch**                            | NSUserDefaults database >= 1 MB -> **OS terminates the app**.                                                                                                                           |
| Library / watched / thumbnails vanished              | A **Caches purge**. Nothing but the `.xml` keys survives.                                                                                                                               |
| Worked on Fire TV, broke on Apple TV                 | Default assumption: you touched a userdata file and hit one of the above.                                                                                                               |

---

## 10. Related (note: several still carry the disproven "rewrites disk on boot" claim - trust THIS doc)

- `docs/playbooks/kodi-vfs-cannot-read-foreign-local-files.md`
- `docs/playbooks/kodi-settings-clobber.md` (also: **restore ORDERING** - Mechanism B)
- `docs/playbooks/ezm-restore-hardening.md` (restore ordering, wipe-after-validate)
- `estuary7/docs/playbooks/skinshortcuts-reset-tvos-vfs-split.md` (Bug 4)
- `docs/playbooks/atv-kodi-xcode-cli-troubleshooting.md` (how to verify - no adb)
- `docs/playbooks/firetv-stick-scoped-storage-provisioning.md`
- `.claude/skills/ezm-backup-doctor/SKILL.md` (RULE ZERO)
