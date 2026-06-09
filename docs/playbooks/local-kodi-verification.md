# Playbook — Local Kodi verification

The biggest lesson in this project: **honest verification.** "No ImportError /
script ran" is NOT proof — an add-on can "run" and still produce an empty menu.
This playbook is how to drive the real local Kodi and prove actual behaviour.

---

## The dev box runs Kodi locally

- Profile: `~/Library/Application Support/Kodi/`
- Log: `~/Library/Logs/kodi.log`
- Add-ons DB (Omega): `~/Library/Application Support/Kodi/userdata/Database/Addons33.db`

Drive it **headlessly** via the webserver JSON-RPC at
`http://localhost:8080/jsonrpc`. Enable it in `guisettings.xml` **before boot**:

```
services.webserver = true
services.webserverport = 8080
services.webserverauthentication = false
```

> On a real device the provisioner seeds more than the webserver: it also sets the
> **device name**, **settings level**, `addons.unknownsources = true`, and
> `addons.updatemode = 1` (see "Fresh-profile reset" below).

## Fresh-profile reset (for clean tests)

1. Quit Kodi cleanly, then force-kill:
   ```bash
   osascript -e 'tell application "Kodi" to quit'
   pkill -9 -x Kodi
   ```
2. Back up `~/Library/Application Support/Kodi` to a timestamped dir.
3. Create a fresh profile, **preserving**:
   - `userdata/sources.xml` — keeps the `.tony7.bones` file source.
   - `userdata/advancedsettings.xml` — `<loglevel>1</loglevel>` for debug logging.
   - a pre-seeded `userdata/guisettings.xml` with the webserver on.

> **Gotcha:** Kodi **rewrites `sources.xml` on fresh-profile init** and may drop
> a pre-seeded files source. If the `.tony7.bones` source vanishes, re-add it and
> restart once.

> **On a real device the canonical reset+seed is `_tools/provision-kodi.sh
<device>`.** It reads `.env.<device>` (per-box weather / IPTV / RSS / device
> config; `.env.device.example` is the committed template), wipes the box, and
> seeds guisettings **before Kodi starts** — web server, device name, settings
> level, `addons.unknownsources = true`, and `addons.updatemode = 1`. Use it
> instead of hand-wiping a device profile.

### Fire OS 11 Sticks — the live data dir is relocated

On a **non-rooted Fire OS 11 Stick** the provisioner relocates Kodi's data
**outside** the default `Android/data` path to writable `/sdcard` (via a
per-device `KODI_DATA_PATH`, e.g. `/sdcard/kodi_data/.kodi`, applied through
`xbmc_env.properties` → `xbmc.data=/sdcard/kodi_data`). **On a relocated stick the
live data dir, `kodi.log`, the Addons DB, `guisettings.xml`, and `settings.xml`
all live under `/sdcard/kodi_data/.kodi`, NOT the default Android/data tree** —
target verification at THAT path. See
`docs/playbooks/firetv-stick-scoped-storage-provisioning.md`.

## Triggering a script add-on

```jsonc
// enable, then run
{"jsonrpc":"2.0","method":"Addons.SetAddonEnabled","params":{"addonid":"script.tony7bones.bootstrap","enabled":true},"id":1}
{"jsonrpc":"2.0","method":"Addons.ExecuteAddon","params":{"addonid":"script.tony7bones.bootstrap"},"id":2}
```

## HONEST verification — prove it, don't assume it

This is the rule. Several false "it works" claims (checking only imports, or
rationalizing an empty menu) cost trust. **Always verify the rendered result.**

A run is only verified when you have shown:

- **Non-empty `Files.GetDirectory`** listings for the installed app, e.g.
  `plugin://plugin.video.pov/` returns real items.
- A **browsable submenu** (drill one level in and get items back).
- The app **installed + enabled + origin set** in `Addons33.db` (query the
  `installed` table; `origin` must NOT be empty — see
  `kodi-install-mechanics.md` §2).
- The **rendered home menu** in a `TakeScreenshot` capture.

Verify with `Files.GetDirectory`, `Addons.GetAddonDetails`, the Addons DB, and
`TakeScreenshot`. Read the debug log (`~/Library/Logs/kodi.log`) for the real
cause when something is empty — don't guess.

## Pattern that worked

Dispatch a focused agent to **drive the REAL local Kodi and read the debug log**,
rather than guessing/iterating blind. Seeing the actual rendered menu and the
actual `GetDirectory` output is what turned "I think it works" into "it works."

## Hard lesson — a wipe-and-run is non-negotiable

The one-shot (skin + MOD V2+ patch installed and activated by Setup) passed
**unit-green AND code-QA-green** and was still broken on a real box. A genuine
**wipe-and-test on a fresh Kodi** (and a real Fire TV) caught **three integration
bugs that the tests and code-only review both missed**:

1. **An `is_installed` import was auto-stripped as "unused"** by a tooling pass, so
   the whole skin step silently no-op'd. The unit tests mock the install machinery
   and never exercised that import path; a wipe-and-run did.
2. **modv2plus + the outline-hd weather icons never installed**, because both are
   **proxy-invisible** — the closure resolver skips our `127.0.0.1` proxy
   (`repos.py`), so they don't resolve through the normal closure. Fix: direct-extract
   them (see `one-shot-and-architecture.md` → "The skin install"). Unit tests using a
   fake index never hit this gap.
3. **The skin reverted to stock Estuary**, because `lookandfeel.skin` was set too
   long before the restart and Kodi's "Keep this skin?" timeout reverted it
   unattended (see `kodi-install-mechanics.md` §13). No unit test can model that
   live timeout.

**Rule:** unit-green + code-QA-green is NOT proof. Before declaring a one-shot
change shipped, wipe the profile (or `pm clear` on the device), run the full
Setup, restart, and verify the END STATE on the real box.

### Verifying the skin one-shot specifically

After the post-Setup restart, confirm — don't assume:

- `xbmc.getSkinDir()` (or `Settings.GetSettingValue lookandfeel.skin`) returns
  **`skin.estuary.modv2`**, not `skin.estuary` (no silent revert).
- `script.tony7bones.modv2plus`, `script.module.pvr.artwork`, and
  `resource.images.weathericons.outline-hd` are all installed + enabled.
- The patch is **applied**: the marker string `show_system_info_overlay` is present
  in the live `skin.estuary.modv2/xml/Home.xml` (the same marker the modv2plus
  service uses to decide whether to auto-apply).
- A `TakeScreenshot` shows the patched MOD V2 home, not stock Estuary.
