# Estuary MOD V2+ — Development Cycle & Lessons Learned

The big picture of how we build, verify, and ship **`script.tony7bones.modv2plus`** (the patch add-on
that customizes the Estuary MOD V2 skin), plus the hard-won knowledge behind it. If you read one doc
before touching this add-on, read this — then the command-level runbook in
[`firetv-adb-dev.md`](firetv-adb-dev.md).

---

## 0. TL;DR — the breakthrough

We develop **directly against the real Amazon Fire TV** over the network (ADB + Kodi JSON-RPC), not
against the Mac's local Kodi. The Mac is a build/courier box; the Fire TV is the test bench.

```
edit a shipped skin XML on the Mac  →  adb push it into the live skin  →  ReloadSkin  →  screencap the TV
```

Seconds per iteration, on the **actual deployment target**. This single change eliminated the entire
class of "works on the Mac, broken on the Fire Stick" bugs that ate days early on.

---

## 1. What the product is (and the architecture decision)

`script.tony7bones.modv2plus` ("Estuary MOD V2+") is a **patch**, not a fork. On **Apply**, it
layers our customizations onto the installed `skin.estuary.modv2`; on **Restore**, it reverts
cleanly. It has **two extension points**: an `xbmc.python.script` (the manual Apply/Restore
chooser + the in-skin buttons) and an `xbmc.service` (`service.py`) that auto-applies the patch
on boot once MOD V2 is the active skin — see §1.5. As of 3.0 the one-tap Setup installs and
activates this add-on for you (the manual run is still available for re-applying or restoring).

### Patch vs. fork — why patch (decided deliberately)

- **Patch (chosen):** tiny, and we **ride Guilouz/b-jesch's upstream development for free** (Kodi-version
  compat, fixes, features). Cost: it's a runtime overlay, so it must be re-applied after a skin update,
  and it doesn't auto-revert on uninstall.
- **Hard fork:** total control + one-install UX, but we'd **own a ~94 MB, fast-moving skin forever** and
  lose upstream updates (manual merges). Rejected for now.
- **Fork-by-build (the hybrid to remember if we ever reconsider):** keep our changes as deltas, apply
  them at _build_ time to the latest MOD V2, ship the _result_ as our own rebranded skin. Best of both;
  re-basing = re-run the build. MIT licensed, so allowed (must keep license + credit the authors).

### How the patch works

- `default.py` copies each file in `FILES` from `resources/xml/<file>` over the live skin's
  `xml/<file>`, taking a **one-time `<file>.bak`** snapshot first. It also copies loose **media**, sets
  some **skin strings**, then `ReloadSkin()`.
- A launch chooser (`Dialog().select`) offers **Apply patches / Restore original**; it also accepts a
  direct `apply` / `restore` argv (used by the in-tab buttons via `RunScript(...,apply|restore)`).
- **Apply** = back up + overwrite the XMLs, copy media, set skin strings, reload.
  **Restore** = (after a yes/no confirm) revert XMLs from `.bak`, delete added media, reset skin
  strings, reload.

### 1.5 The boot service — auto-apply (added in 1.4.0)

`service.py` runs at Kodi start. The patch can **only** run when `skin.estuary.modv2` is the
**active** skin (it overwrites the live skin's XML, sets skin strings, reloads) — but in the
one-tap Setup flow the skin only becomes active _after_ the end-of-Setup restart, by which point
the Setup add-on has self-uninstalled. The service closes that gap:

- On start it waits up to **90 s** for `xbmc.getSkinDir()` to become `skin.estuary.modv2`
  (Kodi briefly reports the previous/booting skin), polling every 3 s and bailing on
  `waitForAbort`.
- **Applied-marker:** it considers the patch already applied iff the string
  `show_system_info_overlay` is present in the live `skin.estuary.modv2/xml/Home.xml` — a string
  stock MOD V2 never contains. A skin **update** overwrites `Home.xml` with stock, which clears
  the marker, so the service **re-applies automatically after a MOD V2 update**.
- If MOD V2 is active **and** the marker is absent, it auto-applies once by calling the add-on's
  own `default._apply(skin_root, skin_xml)`. It is a **no-op** on every normal start (already
  patched) and whenever a different skin is active. A service must never crash Kodi, so the whole
  thing is wrapped defensively.

This makes the one-shot truly hands-off: install via Setup → restart → MOD V2 active → service
applies the patch. On **Android / Fire TV**, where Kodi can't self-relaunch, the user reopens
Kodi after Setup prompts to close — and the service applies the patch on that reopen.

The service has grown three more responsibilities since 1.4.0: it **waits for the Home to render
before patching** (1.4.4 — patching before the home is up left a blank menu); it **deploys and
self-heals the six-item home menu** (1.4.5 fixed a trim race, 1.4.6 made it lay down a verbatim
home layout and self-heal it); and it is **settings-aware** (1.4.7 — it re-applies if the look
settings are missing from `settings.xml`, see the persistence note in §3).

### What it currently ships / changes (as of 1.4.7)

| File / mechanism                                        | Purpose                                                                                                                                                                                                                                                                                      |
| ------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `Home.xml`                                              | overlay gate (group 18000) + nav **wordmark** retarget/sizing                                                                                                                                                                                                                                |
| `SkinSettings.xml`                                      | the **"Tony.7.Bones MOD V2+"** category (last) + its toggles & Apply/Restore buttons; Settings-menu reorder context                                                                                                                                                                          |
| `Settings.xml`                                          | gear-menu reorder — **Skin Settings above Media sources**                                                                                                                                                                                                                                    |
| `Includes.xml`                                          | top-bar **clock** de-bold; top-bar weather icon path                                                                                                                                                                                                                                         |
| `Variables.xml`                                         | `ClockLabelVar` (clock toggle) + the category help-text value                                                                                                                                                                                                                                |
| loose media: `extras/logo-text-hires.png`               | crisp white "KODI" wordmark                                                                                                                                                                                                                                                                  |
| skin strings: `WeatherIcons.path` / `WeatherIcons.name` | point all weather widgets at **Outline HD**                                                                                                                                                                                                                                                  |
| skin settings (set on Apply, in `apply_skin_settings`)  | `show_weatherinfo` ON; splash OFF (`EnableSplashScreen`), seasonal themes OFF (`DisableThemes`); Power menu → Classic list (`powermenu_list`); plain backgrounds for Power/Settings/Search (`enable_*_background`, 1.3.5) — all opt-out flags where _setting_ the flag turns the feature off |
| dependency: `resource.images.weathericons.outline-hd`   | the official Outline HD weather icon pack                                                                                                                                                                                                                                                    |
| `service.py` (1.4.0+)                                   | boot service that auto-applies the patch once MOD V2 is the active skin; **waits for the Home to render** before patching (1.4.4), **deploys/self-heals the six-item home menu** (1.4.5/1.4.6), and is **settings-aware** — re-applies if the look settings are missing (1.4.7). See §1.5    |

### The two patch-isms (the service now handles #1, but know them)

1. **The patch must be re-applied after any MOD V2 skin update** — an update overwrites our patched
   XMLs with stock ones. As of 1.4.0 the **boot service does this automatically** (the applied-marker
   clears when `Home.xml` reverts to stock); you no longer have to remember to re-run Apply.
2. **Restore before uninstall** — uninstalling/disabling the add-on does **not** revert anything (Kodi
   gives scripts no on-uninstall hook). Our changes live in the skin dir + userdata, not in the add-on.

---

## 2. The development cycle

### Environments

- **Mac** — source of truth (the git repo), build tools (`generate_repo.py`, `pytest`, `ruff`), and the
  ADB/curl courier. We **do not** test on the Mac's Kodi anymore (it diverges from the Fire TV — see §3).
- **Office Fire TV (`192.168.7.162`)** — the real test bench. Kodi 21.3 Omega, `skin.estuary.modv2`.
  Control via `adb -s 192.168.7.162:5555` and JSON-RPC at `http://192.168.7.162:8080/jsonrpc`
  (auth `kodi:kodi`). Helper: `_tools/firetv.sh` (pinned to this device).

### Inner loop (fast — for skin XML / media tweaks)

```
1. Edit addons/script.tony7bones.modv2plus/resources/xml/<file> on the Mac
2. _tools/firetv.sh push-xml <file>      # adb push into the live skin
3. _tools/firetv.sh reload-skin           # or restart Kodi for cached assets
4. _tools/firetv.sh screencap             # look at the real TV
5. _tools/firetv.sh log                   # pull kodi.log if something's off
```

### Release loop (the full, safe path)

```
1. Build each shipped skin file FRESH from the CURRENT omega source (see §3) + apply our deltas
2. Update _tools/test_modv2plus.py (assert the new shape; keep the suite green)
3. Bump addon.xml version (+ <news>); python3 _tools/generate_repo.py; git rm the stale zip
4. python3 -m pytest _tools/ -q   &&   ruff check _tools/
5. VERIFY ON THE REAL FIRE TV before pushing (push 1.x.y, Apply, screencap each change)
6. git commit + git push   (pre-push hook runs tests/ruff/staleness/version gates)
7. Confirm live: raw.githubusercontent addon.xml = new version, zip 200, Pages addons.xml = new version
```

**Verify before ship.** The unit tests prove shape; the Fire TV proves behavior.

### Delegation

Multi-file changes + real-TV verification + ship are typically handed to an expert agent
(implement+verify+ship). Keep agents **device-pinned and Kodi-only** (see Safety). For small, fast,
visible tweaks, drive inline so it's transparent.

---

## 3. Hard-won lessons (the gold — don't relearn these)

### Mac ≠ Fire TV (which bugs live where)

- **Only reproduce on the device:** resolution-dependent rendering, corrupted/stale-profile issues, and
  anything skinshortcuts/dependency-related (the Mac's MOD V2 home menu often won't render because its
  skinshortcuts/simpleeval are missing).
- **Reproduce anywhere (pure skin geometry):** proportions/sizing, control gating, label/markup.
- **Rule:** if the Mac can't reproduce a user-reported bug, suspect device/install/resolution — get the
  Fire TV's `kodi.log` or settings; don't conclude "no bug."
- Two real cases: "invisible add-on labels" = a corrupted _old install_ (clean omega.4 was fine); the
  **wordmark** could never be visually confirmed on the Mac (broken skinshortcuts) but was fine on the TV.

### Build from the CURRENT omega — always

The patch overwrites **whole** skin files, so a bundled file from the wrong build = breakage. We shipped
a **Nexus-era `Home.xml`** (2226 lines) onto an Omega skin (2529 lines) for a while — subtle wrongness.
Always rebuild bundled files from the current upstream: **b-jesch/skin.estuary.modv2 @ `Omega` branch**
(== Kodinerds `omega` = the user's build, currently `21.4+omega.4`).

### Weather icons: set the skin strings, don't repoint files

MOD V2 resolves weather icons through **`Skin.String(WeatherIcons.path)` / `WeatherIcons.name`** (the
strings its own icon picker sets). When empty, it falls back to the `.default` pack — that was the
"home Weather tab still default" bug. The fix is **not** to edit `Includes_Home.xml`; it's to set those
strings (we do it in `default.py` Apply via `Skin.SetString(...)`, reset on Restore). One mechanism,
covers the home widget _and_ the top bar.

### Default-ON toggles need opt-OUT flags

Kodi skin booleans are **false when unset**. To have a toggle **checked by default**, gate on
`!Skin.HasSetting(<flag>)` and store an opt-out flag. Examples: `show_system_info_overlay` (default
unset → overlay hidden), `wordmark_modv2_original` (default unset → our crisp wordmark).

### Design principle: "all toggles ON = closest to stock Estuary"

Every per-item toggle in our category defaults to ON, and ON = the stock-Estuary look. That's why the
overlay toggle was renamed **"Disable System Info overlay"** (ON = overlay hidden = stock-like) — so it
matches the others instead of being the odd one out.

### Don't block the reload

A modal `Dialog().ok(...)` _before_ `ReloadSkin()` blocks the reload until the user clicks OK — while the
text claims it's "Reloading…". Use a **non-blocking `Dialog().notification(...)`** then reload, so it's
automatic. (Keep blocking `ok()` only for genuine errors the user must read.)

### The logo: wordmark vs mark, and resolution ≠ distortion

- The home logo is two pieces: the **mark** (blue Kodi glyph) and the **wordmark** ("KODI" text).
- MOD V2's wordmark looked "big/ugly" because it was **low-res (112×36)** and blurred when upscaled —
  _resolution loss, not stretch_. Fix = more pixels, not geometry changes.
- We ship a crisp white wordmark as a **loose file** and retarget the two Home.xml wordmark controls to
  it (no `Textures.xbt` repack needed; a loose path Kodi isn't bundling loads fine). Sized to **height
  39** so its cap-height matches the mark (stock ratio ≈ 0.695). The mark itself is left untouched.

### Kodi JSON-RPC limits on this box

- **No `Addons.Install`** and **no `GUI.ExecuteBuiltin`** over JSON-RPC ("Method not found"). So:
  install deps by **direct-extract** into `.kodi/addons/` + restart + `Addons.SetAddonEnabled`; run
  builtins (e.g. `Skin.SetString`) **from inside the add-on** (`default.py`'s `xbmc.executebuiltin`), or
  via `adb shell input`. `Addons.ExecuteAddon` works and is how we trigger Apply/Restore remotely.

### Skin settings vs patched files (persistence)

- **Skin strings/settings** live in `userdata/addon_data/skin.estuary.modv2/settings.xml` → survive skin
  reloads _and_ skin updates.
- **Patched XML files** live in the skin's `addons/skin.estuary.modv2/xml/` → **overwritten** by a skin
  update (hence patch-ism #1).
- **First-boot caveat (1.4.7):** `Skin.SetBool`/`Skin.SetString` only **flush to `settings.xml` on a
  clean shutdown**. A freshly-provisioned box that never reaches a clean shutdown on its first boot
  therefore **lost** the look settings and showed stock. So as of 1.4.7 the look settings
  (`show_weatherinfo`, `WeatherIcons.path`/`.name` → Outline HD, `enable_power/settings/search_background`,
  `powermenu_list`) are written **straight to `settings.xml` on Apply** instead of only via the skin
  builtins. The **boot service is settings-aware** to match: it re-applies if those settings are missing.

### Textures.xbt (XBTF) extraction — the "header fix"

Stock weather/logo art is packed in `media/Textures.xbt` (XBTF v2). Gotchas that crash naïve parsers:
frame header is **40 bytes (no `duration` field)**; LZO-compressed **iff `packedSize != unpackedSize`**
(not a flag); pixels are **BGRA straight alpha** for format `0x10`. Full details + Python in
`~/Downloads/skin.estuary.modv2-Omega/LOGO_HANDOFF.md` §5–6. (We later preferred resource add-ons /
loose files over repacking the XBT.)

### Dependencies & where they come from

- `resource.images.weathericons.outline-hd`, `script.skinshortcuts`, `script.image.resource.select`,
  `script.module.simpleeval/simplecache` → **official Kodi repo** (enabled by default → clean `<requires>`).
- `script.module.pvr.artwork` → **NOT** on Kodinerds despite MOD V2 importing it; comes from
  **b-jesch's GitHub** (`master`). `skin.estuary.modv2` itself + the `omega` tree → **Kodinerds repo**
  (which the Tony.7.Bones repo hosts). Install order on a clean box: Tony.7.Bones repo → Kodinerds repo →
  MOD V2 (deps resolve) → MOD V2+.

---

## 4. Release paths & the proxy

- **A `script.*` add-on** (like modv2plus): bump `addon.xml`, `generate_repo.py`, commit, **push** — the
  proxy serves it live from `raw.githubusercontent` (no Pages build needed). This is 99% of our work.
- **Adding/removing a _served_ add-on** (editing the proxy's baked `repository.json`): requires a
  **proxy release via `deploy.py`** (the manifest is baked into `repository.tony7bones`). Sequencing
  trick: `deploy.py` refuses a dirty tree, but the pre-push version gate evaluates the whole
  `origin/main..HEAD` range — so **commit the content + repository.json locally first** (clean tree),
  then run `deploy.py`; its proxy version bump "covers" the manifest change.
- **Propagation:** the proxy caches its manifest ~1 h in memory (restart Kodi to clear). For _existing_
  served add-ons, a version bump is live from raw immediately; the box picks it up on its next update
  check.

---

## 5. Safety rules for driving the Fire TV (non-negotiable)

- **Pin the device:** always `adb -s 192.168.7.162:5555` and JSON-RPC only to `…162:8080`. There are
  several Fire TVs in the house + an unauthorized adb device at `.84` — a bare `adb` could hit the wrong
  one. Confirm `settings get global device_name` == "Office TV" before any write.
- **Kodi only:** only ever read/write `org.xbmc.kodi` data (`/sdcard/Android/data/org.xbmc.kodi/files/.kodi/`).
  **Never** `pm uninstall` / `pm clear` / modify any other package.
- **Back up before destructive ops:** `cp -R` the profile with absolute paths and verify it's non-empty
  before wiping (`pm clear org.xbmc.kodi` = a full data wipe / fresh Kodi). No fragile `ls`-parsing for
  deletions.
- **Two-Kodi confusion:** the Mac may have its own Kodi window open — that's _not_ the device. Keep them
  straight (or quit the Mac's Kodi).

---

## 6. Today's shipped releases (the arc)

| Ver   | What                                                                                                                                                                                                                                                              |
| ----- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1.0.0 | New lean add-on from omega.4 (settings-menu swap, overlay toggle, crisp white wordmark); old `script.tony7bones.modv2.patch` retired; proxy released (repository.tony7bones 1.0.14)                                                                               |
| 1.0.1 | Apply/Restore auto-reload via notification (no blocking dialog)                                                                                                                                                                                                   |
| 1.0.2 | Nav wordmark sized to match the Kodi mark                                                                                                                                                                                                                         |
| 1.0.3 | Top-bar clock de-bolded (thin)                                                                                                                                                                                                                                    |
| 1.0.4 | Top-bar weather → stock white (49 icons extracted from `Textures.xbt`)                                                                                                                                                                                            |
| 1.1.0 | "Tony.7.Bones MOD V2+" Skin Settings category; overlay toggle moved there                                                                                                                                                                                         |
| 1.2.0 | Per-item toggles (weather/clock/wordmark) + in-tab Apply/Restore buttons                                                                                                                                                                                          |
| 1.3.0 | Overlay hidden by default ("Disable System Info overlay"); weather → Outline HD pack (replaced the bundled white set with a dependency)                                                                                                                           |
| 1.3.1 | Outline HD applied to the **home** weather widget too (set `WeatherIcons` skin strings); **Restore now confirms**                                                                                                                                                 |
| 1.3.5 | Power/Settings/Search **backgrounds OFF** by default (the `enable_*_background` opt-out flags in `apply_skin_settings`)                                                                                                                                           |
| 1.4.0 | **Boot service** (`service.py`) — auto-applies the patch once MOD V2 is the active skin, and re-applies after a MOD V2 update (the one-tap Setup now produces a fully patched box with no manual step). Manual Apply/Restore unchanged.                           |
| 1.4.1 | Channel numbers off in Live TV; new V2+ icon                                                                                                                                                                                                                      |
| 1.4.2 | Home-menu tweaks: TV → Guide, Favorites, hide 6 widgets                                                                                                                                                                                                           |
| 1.4.3 | Build the skinshortcuts home menu deterministically                                                                                                                                                                                                               |
| 1.4.4 | Service **waits for the Home to render** before patching (patching too early left a blank menu)                                                                                                                                                                   |
| 1.4.5 | Six-item home-menu **trim race** fixed (deploy the menu without losing items)                                                                                                                                                                                     |
| 1.4.6 | Service lays down a **verbatim home layout** and **self-heals** the six-item menu                                                                                                                                                                                 |
| 1.4.7 | **First-boot look-settings persistence** — look settings now write straight to `settings.xml` on Apply (skin builtins only flush on a clean shutdown, which a first boot never reaches); the boot service is **settings-aware** and re-applies if they're missing |

> The 1.3.2–1.3.4 intermediate releases are not detailed here (their `<news>` is in the
> add-on history); 1.3.5 and 1.4.0 are the load-bearing steps for the 3.0 one-shot, and
> 1.4.7 is the load-bearing step for first-boot look-settings persistence.

---

## 7. Quick reference

- **Device:** Office Fire TV `192.168.7.162:5555` (adb) / `:8080` (JSON-RPC, `kodi:kodi`). Helper:
  `_tools/firetv.sh` (`connect`, `status`, `push-addon`, `push-xml <f>`, `apply`, `restore`,
  `reload-skin`, `screencap`, `log`, `launch`, `stop`).
- **Live skin paths:** `…/org.xbmc.kodi/files/.kodi/addons/skin.estuary.modv2/{xml,media,extras}/`;
  skin settings: `…/userdata/addon_data/skin.estuary.modv2/settings.xml`.
- **Add-on source:** `addons/script.tony7bones.modv2plus/` (`default.py` = manual Apply/Restore,
  `service.py` = boot auto-apply, `resources/xml/*`, `resources/media/*`).
- **Tests:** `_tools/test_modv2plus.py` (import under mocked `xbmc*`).
- **Related docs:** [`firetv-adb-dev.md`](firetv-adb-dev.md) (commands), `kodi-install-mechanics.md`,
  `release-and-deploy.md`, `local-kodi-verification.md`, and the repo `TASKS.md`.

---

_Patches keep us lean and current; the Fire TV keeps us honest. Build from current omega, verify on the
real TV, ship small._
