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
