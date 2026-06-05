# TASKS

Tracking for the Tony.7.Bones repo. Current focus: **Estuary MOD V2+** (`script.tony7bones.modv2plus`).

Conventions: batch work into versioned deliverables; build bundled skin files FRESH from the current
omega source (b-jesch Omega branch / Kodinerds omega.4); verify on the real local Kodi before shipping;
no AI attribution anywhere. `script.*` changes ship via `generate_repo.py` + push (no proxy/deploy.py).

---

## Backlog / later

- [ ] **Settings menu order toggle** — "Skin Settings first", default ON; off = stock order. _Harder_ (list item order isn't cleanly conditional).
- [ ] Re-skin the MOD V2+ add-on icon to reflect the "+" branding (currently reuses the old patch icon).
- [ ] Consider a localized strings.po for our category labels/help (currently literal text).

## Done (shipped)

- [x] **1.2.0** — each tweak is now a per-item toggle in the "Tony.7.Bones MOD V2+" category, all defaulting to the stock look we ship: weather icons (`weather_modv2_colored`, off=stock white via `WeatherIconTextureVar`), clock (`clock_modv2_bold`, off=thin via `ClockLabelVar`), nav wordmark (`wordmark_modv2_original`, off=stock white hi-res; two stacked variants per logo group). Plus in-tab "Apply Tony.7.Bones tweaks" / "Restore stock MOD V2" buttons (default.py routes `apply`/`restore` argv). System Info overlay toggle unchanged.
- [x] **1.1.0** — "Tony.7.Bones MOD V2+" Skin Settings category (last); System Info overlay toggle moved there, renamed, defaults ON.
- [x] **1.0.4** — top-right weather icons swapped to stock white (49 icons extracted from stock `Textures.xbt`).
- [x] **1.0.3** — top-right clock de-bolded to match stock (thin Roboto).
- [x] **1.0.2** — nav wordmark sized to match the Kodi mark (stock proportions).
- [x] **1.0.1** — Apply/Restore auto-reload via notification (no blocking dialog).
- [x] **1.0.0** — new lean `script.tony7bones.modv2plus` from omega.4 (settings-menu swap, overlay toggle, crisp white wordmark); old `script.tony7bones.modv2.patch` retired; proxy released (repository.tony7bones 1.0.14).
