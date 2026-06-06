# TASKS

Tracking for the Tony.7.Bones repo. Current focus: **Estuary MOD V2+** (`script.tony7bones.modv2plus`).

Conventions: batch work into versioned deliverables; build bundled skin files FRESH from the current
omega source (b-jesch Omega branch / Kodinerds omega.4); verify on the real local Kodi before shipping;
no AI attribution anywhere. `script.*` changes ship via `generate_repo.py` + push (no proxy/deploy.py).

---

## Backlog / later

- [ ] **1.3.3 — Home-menu trim (skinshortcuts)** — disable default home items **Music, Music Videos, Radio, Games, Pictures, Videos**. NOT a skin toggle: MOD V2's main menu is skinshortcuts-driven (`shortcuts/mainmenu.DATA.xml`); the `hide_<x>category` flags only change actions, not visibility. Fix = ship a **trimmed `shortcuts/mainmenu.DATA.xml`** (default menu minus those 6 `<shortcut>` nodes) + likely clear the skinshortcuts built-menu cache so a box rebuilds from it (risk: wipes user menu customizations). **Must verify live on the Fire TV** (skinshortcuts caching is finicky) — do when the TV is awake.
- [ ] **Settings menu order toggle** — "Skin Settings first", default ON; off = stock order. _Harder_ (list item order isn't cleanly conditional).
- [ ] Re-skin the MOD V2+ add-on icon to reflect the "+" branding (currently reuses the old patch icon).
- [ ] Consider a localized strings.po for our category labels/help (currently literal text).
- [ ] Create a distinct `drop/` folder at the repo root — a staging area for incoming files/assets. _Purpose/usage to confirm._

## Done (shipped)

- [x] **1.3.2** — Apply now sets MOD V2 skin-setting defaults (new `apply_skin_settings()` / `reset_skin_settings()` via `Skin.SetBool`/`SetString`): top-bar weather/temp readout **ON** (`show_weatherinfo` — off on a fresh skin); **Splash Screen OFF** (`EnableSplashScreen`) and **Themes OFF** (`DisableThemes`) — both MOD V2 opt-out flags; **Power menu → Classic list** (`powermenu_list`, clears `powermenu_panel`/`powermenu_iconlist`). Restore clears them all back to MOD V2 stock. (Outline HD weather icons stay from 1.3.1.)
- [x] **Dev infrastructure & docs** — stood up the **ADB-over-network dev pipeline** against the Office Fire TV (`192.168.7.162`): `_tools/firetv.sh` + `docs/playbooks/firetv-adb-dev.md` (edit → push → reload → screencap on the real target). Wrote the extensive **dev-cycle + lessons** doc `docs/playbooks/modv2plus-dev-cycle-and-lessons.md`, and updated `README.md` + `CLAUDE.md` (modv2.patch → modv2plus, new playbook pointers).
- [x] **1.3.1** — Outline HD weather icons now apply to the **home weather widget** too, not just the top bar: `default.py` Apply sets MOD V2's `Skin.String(WeatherIcons.path/name)` to the Outline HD pack (the same strings MOD V2's own picker uses; empty → the `.default` fallback was the bug), and Restore clears them. Also: **Restore now asks a yes/no confirmation** before reverting (covers both the chooser and the in-tab button). Note: uninstalling/disabling the add-on does NOT auto-revert — run Restore first, then uninstall (Kodi gives scripts no on-uninstall hook).
- [x] **1.3.0** — System Info overlay now hidden by default: the panel toggle is renamed "Disable System Info overlay" (`show_system_info_overlay`, checked-by-default so the overlay is off), Home.xml group 18000 gates on `Skin.HasSetting(show_system_info_overlay) + Control.HasFocus(802)`. Weather icons are now the official Outline HD set with no toggle: `addon.xml` `<requires>` imports `resource.images.weathericons.outline-hd` (auto-installed from the official Kodi repo), Includes.xml wires the weather `<texture>` directly to `resource://resource.images.weathericons.outline-hd/`. Removed the dead weather toggle path entirely: the "Stock weather icons (white)" radiobutton, `WeatherIconTextureVar`, the `weather_modv2_colored` flag, the `MEDIA_DIRS` weather-stock copy in default.py, and the bundled `resources/media/extras/weather-stock/` icon set. Kept the clock + nav-logo toggles and the logo MEDIA entry.
- [x] **1.2.0** — each tweak is now a per-item toggle in the "Tony.7.Bones MOD V2+" category, all defaulting to the stock look we ship: weather icons (`weather_modv2_colored`, off=stock white via `WeatherIconTextureVar`), clock (`clock_modv2_bold`, off=thin via `ClockLabelVar`), nav wordmark (`wordmark_modv2_original`, off=stock white hi-res; two stacked variants per logo group). Plus in-tab "Apply Tony.7.Bones tweaks" / "Restore stock MOD V2" buttons (default.py routes `apply`/`restore` argv). System Info overlay toggle unchanged.
- [x] **1.1.0** — "Tony.7.Bones MOD V2+" Skin Settings category (last); System Info overlay toggle moved there, renamed, defaults ON.
- [x] **1.0.4** — top-right weather icons swapped to stock white (49 icons extracted from stock `Textures.xbt`).
- [x] **1.0.3** — top-right clock de-bolded to match stock (thin Roboto).
- [x] **1.0.2** — nav wordmark sized to match the Kodi mark (stock proportions).
- [x] **1.0.1** — Apply/Restore auto-reload via notification (no blocking dialog).
- [x] **1.0.0** — new lean `script.tony7bones.modv2plus` from omega.4 (settings-menu swap, overlay toggle, crisp white wordmark); old `script.tony7bones.modv2.patch` retired; proxy released (repository.tony7bones 1.0.14).
