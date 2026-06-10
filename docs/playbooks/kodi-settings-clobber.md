# Playbook — Kodi clobbers direct settings writes (the general pattern)

> **The class of bug:** a Kodi component (the skin engine, a PVR client, core)
> holds its settings **in memory** and **flushes them to disk at a lifecycle
> event** (clean shutdown, client teardown, skin switch). Any naive interaction
> with the on-disk file races that flush, in one of two directions:
>
> 1. **Your direct file write is CLOBBERED** — the live component later flushes
>    its stale in-memory values back over the file.
> 2. **Your in-memory set is LOST** — the flush that would persist it never
>    happens (e.g. a first boot that never reaches a clean shutdown).
>
> This bit us **three separate times** before the pattern was named. Read this
> before writing ANY settings-like XML that a live Kodi component also owns.

---

## The three instances (same class, learned the hard way)

| #   | Setting file                                                           | Live owner                                    | Failure observed                                                                                                                                                                        | Fix mechanism                                                                                                                                                                                            |
| --- | ---------------------------------------------------------------------- | --------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1   | `addon_data/skin.estuary/settings.xml` (home-menu trim bools)          | the active Estuary skin                       | direct write clobbered on shutdown; `Skin.SetBool` alone lost on a first boot (no clean shutdown ever happens)                                                                          | **both**: `Skin.SetBool` (in-memory, survives a clean shutdown) AND a direct `settings.xml` merge (survives a first boot) — `_trim_home_menu_setbool()` + `_trim_home_menu_writefile()` in the bootstrap |
| 2   | `addon_data/skin.estuary.modv2/settings.xml` (modv2plus look settings) | the active MOD V2 skin                        | `Skin.SetBool`/`SetString` on Apply never flushed (first boot) → look settings missing after restart                                                                                    | modv2plus **1.4.7**: write straight to `settings.xml` on Apply; the boot service is **settings-aware** and re-applies any that are missing                                                               |
| 3   | `addon_data/pvr.iptvsimple/instance-settings-<N>.xml`                  | the running pvr.iptvsimple client instance(s) | the end-of-setup clean shutdown flushed the live client's **stale in-memory defaults** over the just-written instance files → the box restarted unconfigured (modular-setup Phase 5b·1) | the **PVR-disabled config window**: disable the client → settle → write → re-enable in a `finally` (`_pause_pvr_for_config` / `_resume_pvr_after_config` in `tony7bones.setup.iptv`)                     |

## The two known mechanisms — pick by who owns the file

### Mechanism A — write through (or around) the in-memory owner

When the owner is **always live and cannot be disabled** (the active skin):

- Use the in-memory API (`Skin.SetBool`/`Skin.SetString`) when a **clean
  shutdown is guaranteed** to follow (Setup's orderly restart) — the flush
  persists your value.
- Write the file **directly** when a clean shutdown is NOT guaranteed (first
  boot, crash-prone session) — and accept that a later clean shutdown may
  rewrite the file, so the direct write must be **reconciled** (a
  settings-aware boot service, or belt-and-suspenders both-mechanisms like the
  home-trim).
- Writing the file while Kodi is **fully down** (the provisioner's pre-boot
  `guisettings.xml` seed) is the degenerate safe case — no live owner to race.

### Mechanism B — disable the consumer around the write

When the owner **can be disabled** (a PVR client, any binary add-on):

```
disable the add-on            # its teardown flushes ITS settings NOW,
                              # BEFORE your writes — the race is over
settle (~1s)
write the settings file(s)    # nothing live holds stale values anymore
re-enable in a `finally`      # never leave the consumer disabled; the
                              # re-enable forces Kodi's scanner to RE-READ
                              # the file(s) just written, so the fresh
                              # client starts from YOUR values
```

The re-enable is as important as the disable: it makes every later flush
(including the end-of-run clean shutdown) flush **your** values, because they
are now the in-memory state. Use the install library's own `enable`/`disable`
primitives so the bounce composes with the normal install ritual (this is why
`install_with_deps` itself stays untouched — the window wraps the **config**
writes, not the install).

## Decision guide

1. **Who holds this setting in memory while Kodi runs?** (Nobody → just write
   the file. The skin → Mechanism A. A disableable add-on → Mechanism B.)
2. **When does that owner flush to disk?** (Clean shutdown only → an in-memory
   set survives an orderly restart but is lost on a first boot.)
3. **Will my write happen while the owner is live?** If yes and the owner is
   disableable, use the window. If yes and it isn't, write both ways and
   reconcile on boot.
4. **Will the box reach a clean shutdown after my write?** If not guaranteed,
   never rely on an in-memory set alone.

## Where the code lives

- Mechanism A, instance 1: `_trim_home_menu*` in
  `addons/script.tony7bones.bootstrap/default.py`; background in
  `kodi-install-mechanics.md` §11.
- Mechanism A, instance 2: `script.tony7bones.modv2plus` (Apply writes
  `settings.xml`; `service.py` reconciles) — `modv2plus-dev-cycle-and-lessons.md`.
- Mechanism B, instance 3: `_pause_pvr_for_config` / `_resume_pvr_after_config`
  in `addons/script.module.tony7bones/lib/tony7bones/setup/iptv.py`
  (every `apply_iptv` file write — device-copy AND instance-settings enforce —
  runs inside the window); full IPTV context in
  `iptv-channel-customization.md`.

> **Related but different:** `lookandfeel.skin` reverting to stock Estuary is
> NOT this class — that's the "Keep this skin?" safety timeout
> (`kodi-install-mechanics.md` §13). Same smell (your change silently undone),
> different mechanism (an unconfirmed UI timeout, not a settings flush).
