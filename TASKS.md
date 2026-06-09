# TASKS

Tracking for the Tony.7.Bones repo. Current focus: **Estuary MOD V2+** (`script.tony7bones.modv2plus`).

Conventions: batch work into versioned deliverables; build bundled skin files FRESH from the current
omega source (b-jesch Omega branch / Kodinerds omega.4); verify on the real local Kodi before shipping;
no AI attribution anywhere. `script.*` changes ship via `generate_repo.py` + push (no proxy/deploy.py).

> Shipped/done history is not tracked here — the live state lives in `addons/*/addon.xml` versions,
> git tags, and CLAUDE.md (architecture + "Restore points"). This file holds only open work.

---

## Open

- [ ] **Settings menu order toggle** — "Skin Settings first", default ON; off = stock order. _Harder_ (list item order isn't cleanly conditional).
- [ ] **Re-skin the MOD V2+ add-on icon** to reflect the "+" branding (currently reuses the old patch icon).
- [ ] **Localized `strings.po`** for our category labels/help (currently literal text).
- [ ] **`drop/` staging folder** at the repo root — a staging area for incoming files/assets. _Purpose/usage to confirm before building._
