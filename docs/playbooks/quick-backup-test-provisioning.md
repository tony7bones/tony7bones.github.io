# Playbook - fast pristine-to-backup-ready Kodi box (skip the full Setup)

Purpose: get a freshly wiped Kodi box to the point where
`script.ezmaintenanceplusplus` (or any single repo add-on) can be installed
and run - for a backup/restore test - without the manual friction of Fire
TV's/Kodi's first-run experience (approving unknown-source installs, renaming
the device, enabling the web server by hand) AND without waiting through the
full curated Setup (video add-ons, skin, IPTV - none of which matters for a
backup test).

This is a **documented plan, not yet a script**. `_tools/provision-kodi.sh`
already proves every mechanism used below (it's where the exact
`guisettings.xml` payload and adb sequencing come from) - see "Where this
could become a real script" at the end for turning this into a one-command
tool.

---

## Why this is faster than the full provisioner

`_tools/provision-kodi.sh` already eliminates all the MANUAL friction (device
rename, the "install from unknown sources" permission, the web server) by
seeding `guisettings.xml` over adb **before Kodi's first boot** - none of it
ever goes through Kodi's UI. But it always continues into the full one-tap
Express Setup (video add-ons + skin + IPTV, ~5-10 minutes unattended,
`provision-kodi.sh` step 6/8). For a backup test, none of that matters: by
the time Express would even start, the repo (`repository.tony7bones`) is
already installed and enabled, so EZ Maintenance++ (or anything else served
from it) can be installed straight from the Add-on browser, permission-dialog
free, in seconds - no need to wait for or run the curated bundle at all.

## The fast path

Steps 1-4 mirror `provision-kodi.sh`'s steps 1-4 (`_tools/provision-kodi.sh`
lines ~124-217) almost exactly - the difference starts at step 5, where this
path stops pushing the full Setup and installs only the repo.

1. **Connect.**

   ```
   adb connect <DEVICE_IP>:5555
   ```

   Fire TV: ADB debugging must already be enabled in Developer Options and
   the device paired once (cached after that - no re-auth needed). Per-device
   specifics for Office: `docs/playbooks/firetv-adb-dev.md`. A non-rooted
   Fire OS 11 Stick needs the scoped-storage relocation trick first - see
   `docs/playbooks/firetv-stick-scoped-storage-provisioning.md`.

2. **Reboot** (recommended - clears any wedged graphics state from a prior
   session).

   ```
   adb reboot
   adb wait-for-device
   ```

3. **Wipe Kodi clean.**

   ```
   adb shell am force-stop org.xbmc.kodi
   adb shell pm clear org.xbmc.kodi
   ```

   On a non-rooted Fire OS 11 Stick where `pm clear` can't reach the app
   sandbox, use the `KODI_DATA_PATH` relocation variant in the scoped-storage
   playbook instead.

4. **Seed `guisettings.xml` BEFORE Kodi ever starts.** This one step is what
   eliminates every bit of manual permission/rename friction. Push a
   `guisettings.xml` into `$K/userdata/` (where
   `$K=/sdcard/Android/data/org.xbmc.kodi/files/.kodi`, or the relocated path
   on a scoped-storage Stick) containing at minimum:
   `services.devicename` (the name you want), `services.webserver=true` (so
   the box can be driven headless over JSON-RPC), `addons.unknownsources=true`
   (this is the "permission to install from anywhere" - pre-granted, no
   dialog), and `addons.updatemode=1`. The exact XML this repo already builds
   and proves works is in `_tools/provision-kodi.sh` around line 176 - reuse
   it verbatim rather than hand-rolling a new one.

5. **Push ONLY the repo (skip the library + bootstrap Setup).**
   `provision-kodi.sh` step 4 fetches and pushes THREE add-ons
   (`script.module.tony7bones`, `script.tony7bones.bootstrap`,
   `repository.tony7bones`) because it's about to run the full Setup. This
   fast path needs only the last one:

   ```
   curl -s -o r.zip "https://raw.githubusercontent.com/tony7bones/tony7bones.github.io/main/addons/repository.tony7bones/repository.tony7bones-<version>.zip"
   unzip -oq r.zip
   adb push repository.tony7bones "$K/addons/"
   ```

   (Resolve `<version>` first from
   `.../main/addons/repository.tony7bones/addon.xml`, same as
   `provision-kodi.sh`'s `ver()` helper does.) Deliberately do NOT push the
   library or bootstrap - they're only needed to run the curated Setup, which
   this path skips.

6. **Launch Kodi, enable the repo.**

   ```
   adb shell am start -n org.xbmc.kodi/.Splash
   ```

   Wait for it to come up (poll `getprop sys.boot_completed` /
   `Application.GetProperties` over JSON-RPC), then enable the repo - the web
   server is already live from step 4, so this works immediately, no UI
   interaction:

   ```
   curl -s -u kodi:kodi http://<DEVICE_IP>:8080/jsonrpc \
     -d '{"jsonrpc":"2.0","method":"Addons.SetAddonEnabled","params":{"addonid":"repository.tony7bones","enabled":true},"id":1}'
   ```

7. **Install EZ Maintenance++ directly** - either over JSON-RPC
   (`Addons.InstallAddon`, `params: {"addonid": "script.ezmaintenanceplusplus"}`)
   or from the on-screen Add-on browser (also dialog-free now, since
   `unknownsources` is already on). Either way, no confirmation prompts.

8. **Run a backup.** Open the add-on, set the destination (`nfs://`,
   `smb://`, Dropbox, or local), run Backup. From a wiped box to a completed
   backup attempt: well under 2 minutes of actual wait, versus the ~10-15
   minutes the full provisioner takes to reach the same readiness (because it
   installs the whole curated bundle first).

## What you lose by skipping the full Setup

No skin, no curated video add-ons, no IPTV, no weather/RSS config - none of
which affects whether EZ Maintenance++ can back up or restore. If a later
test also needs those, either run `script.tony7bones.bootstrap` afterward
(push it the same way as step 5, then execute it - a normal add-on install
away) or just fall back to the full `_tools/provision-kodi.sh <device>` from
a fresh wipe.

## Where this could become a real script

`_tools/provision-kodi.sh` already has essentially every piece this path
needs (the wipe, the exact `guisettings.xml` payload, the adb-push
mechanics, the boot-wait polling) - a `--repo-only` (or `--minimal`) flag
that stops after step 4 ("Install the Setup") and pushes only
`repository.tony7bones` instead of all three add-ons, then skips straight to
launch + enable (current step 5) without ever calling
`Addons.ExecuteAddon` on the bootstrap, would turn this into a one-command
tool. Not built yet - worth building if this path ends up used often enough
to justify it; until then this document is the reference for doing it by
hand.

> **Related but different:** this is not about diagnosing a backup FAILURE
> (that's `~/Code/moquette/kodi/.claude/skills/ezm-backup-doctor/SKILL.md` and
> `docs/playbooks/kodi-vfs-cannot-read-foreign-local-files.md`) - this is
> about getting a clean box ready to attempt one in the first place, as
> quickly as possible.
