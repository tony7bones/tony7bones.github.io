# Playbook — One-shot setup & the add-on architecture

The shipped first-party add-on architecture, the shared-library pattern, and the
one-shot flow. Design source: `../plans/one-shot-option-b-plan.md` (implemented).
Code: `addons/script.module.tony7bones/`, `addons/script.tony7bones.bootstrap/`,
`addons/script.tony7bones.modv2plus/`.

---

## The first-party add-ons

| Add-on                        | Name (in Kodi)              | Kind                                         | On home screen?                                      |
| ----------------------------- | --------------------------- | -------------------------------------------- | ---------------------------------------------------- |
| `repository.tony7bones`       | Tony.7.Bones Repo           | virtual proxy repository                     | n/a (the repo add-on)                                |
| `script.module.tony7bones`    | Tony.7.Bones Shared Library | `xbmc.python.module` (Python LIBRARY)        | **No** — no executable                               |
| `script.tony7bones.bootstrap` | Tony.7.Bones Setup          | `xbmc.python.script` + `provides>executable` | Only until it self-uninstalls                        |
| `script.tony7bones.modv2plus` | Estuary MOD V2+             | `xbmc.python.script` + `xbmc.service`        | Hosted; auto-applied by Setup, also runnable by hand |

> The standalone `script.tony7bones.video` ("Video Add-ons Setup") add-on has
> been **removed**. Its install logic now lives in the shared library as
> `install_selection(...)`, which the base Setup calls directly to install the
> curated video add-ons unattended (see the flow below).

### Shared-library pattern

`script.module.tony7bones` carries **all** the generic install machinery so the
Setup holds only its own configuration:

- `net.py` — HTTP fetch (gunzips `.gz`), zip extract, `UpdateLocalAddons`,
  enable/disable via JSON-RPC.
- `index.py` — addons.xml load/parse/merge + the closure resolvers (ordered for
  the base apps; combined/highest-wins for the curated video set).
- `repos.py` — installed-repo discovery, source-repo enabling, **origin
  stamping** into `Addons<NN>.db`.
- `install.py` — the install orchestrators: `install_with_deps`, `install_closure`,
  `disable_after_install`, and `install_selection(selected, official_base,
disable_ids, dialog, log)` (folded in from the retired standalone video Setup).
- `system.py` — platform tag, Android detection, self-uninstall, restart.

The Setup declares `<requires><import addon="script.module.tony7bones"
version="1.1.0"/>`, so Kodi **auto-installs the library from the repo** when the
Setup is installed — no chicken-and-egg. The library is invisible on the home
screen because it provides no executable. Keep its public API small and stable;
bump the module version + the Setup's `<requires>` together if the contract ever
changes.

## The one-shot flow (base "Tony.7.Bones Setup")

`script.tony7bones.bootstrap/default.py:run()` runs fully **unattended** — no
prompts, no video picker:

1. **Base install:** extract the 12 repo installer zips → register/enable →
   install each base app with its full dependency closure
   (`script.ezmaintenanceplus`, `script.realdebrid` from peno64; `weather.multi`
   and the binary `pvr.iptvsimple` from the official repo, platform-correct).
2. **Curated video install:** `_install_video()` delegates to the shared library's
   `install_selection()` to install the curated video add-ons — POV
   (`plugin.video.pov`), The Loop (`plugin.video.the-loop`), Sports HD
   (`plugin.video.sporthdme`), and YouTube (`plugin.video.youtube`) — with their
   closure; origins are stamped, and the install-then-disable set (Dailymotion,
   `plugin.video.dailymotion_com`, a required-but-unused import of The Loop) is
   applied. A video failure is non-fatal — it never aborts the box.
   `plugin.video.umbrella` is **not** installed (but `repository.umbrella` stays
   in the repo, browsable/proxy-served).
3. **Estuary MOD V2 skin + the MOD V2+ patch:** `_install_skin()` installs the
   `skin.estuary.modv2` skin **and** our `script.tony7bones.modv2plus` patch as
   part of the one-tap run (no longer a manual step — see "The skin install" below).
4. **One combined summary** (repos · apps · video · MOD V2 status).
5. **Self-uninstall** the base Setup. The **shared library is left installed**.
6. **Base-only steps:** add the File-Manager sources, trim the Estuary home menu
   to TV / Add-ons / Favourites / Weather (see `kodi-install-mechanics.md` §11),
   then the weather/RSS/top-bar box config.
7. **Activate MOD V2 LAST:** set `lookandfeel.skin = skin.estuary.modv2`
   **immediately before the restart** — this is load-bearing (see
   `kodi-install-mechanics.md` §13).
8. **One restart** (`restart_kodi`) finalises every freshly extracted add-on, the
   self-removal, and boots into MOD V2. On the next boot the modv2plus **service**
   auto-applies the patch (the Setup is gone by then).

A cancelled progress dialog mid-install aborts cleanly: no summary, no
self-uninstall, no restart (the partial install is harmless; re-running Setup
completes it).

## The curated video install (`install_selection`)

`install_selection(selected, official_base, disable_ids, dialog, log)` (in the
shared library's `install.py`) is the entry point the base Setup calls to install
the curated video apps. It enables the source repos, builds a combined index from
the installed repos plus the official repo, resolves the closure for the selected
ids, extracts/enables/origin-stamps it, and applies the install-then-disable set.
It never prompts, summarises, self-uninstalls, or restarts — the caller (the
Setup's `run()`) owns those, which is why the run has exactly one summary and one
restart.

## The skin install (`_install_skin`)

`_install_skin(dialog)` in the base Setup installs **and activates** Estuary
MOD V2 plus the MOD V2+ patch as part of the one-tap run. The non-obvious part:
two of the pieces are **invisible to the closure resolver**, because `repos.py`
deliberately skips our own `127.0.0.1` proxy as a content source (it is not a
real repo). So they cannot resolve through the normal closure and are
**direct-extracted** first:

1. `script.module.pvr.artwork` — a hard requirement of the skin, but it is
   b-jesch's **GitHub-only** module (not in Kodinerds/official, and proxy-invisible).
   Direct-extracted from our Pages `/addons/hosted/` mirror, along with its
   `script.module.requests` / `script.module.simplecache` deps from the official
   repo, so the skin's dependency check is satisfied **before** the closure resolve.
2. `script.tony7bones.modv2plus` — our own first-party patch add-on is proxy-only
   too, so it is direct-extracted at its **live** version (resolved via
   `_latest_zip_url()` reading its static `addon.xml`), and its
   `resource.images.weathericons.outline-hd` dep is pulled from the official repo.
3. The skin itself + its remaining closure (`skin.estuary.modv2` + skinshortcuts
   - image.resource.select from Kodinerds; pvr.artwork already satisfied) installs
     via `install_selection([SKIN_ID])` from the installed repos.
4. **Rescan + settle + enable** everything just extracted (`update_local_addons()`,
   then `enable()` on pvr.artwork, modv2plus, and the skin) **before** the skin is
   chosen — a freshly-extracted skin must be registered AND enabled or Kodi
   silently rejects the skin setting and boots stock Estuary (a bug the
   wipe-and-test caught — see `local-kodi-verification.md`).

`_install_skin` does **not** set `lookandfeel.skin` — `run()` sets it LAST, right
before the restart, for the activation-revert reason in
`kodi-install-mechanics.md` §13. After the restart MOD V2 is the active skin and
the modv2plus boot **service** auto-applies the patch (the Setup cannot apply it
itself, because the patch only runs once MOD V2 is the live skin, and by then the
Setup has self-uninstalled).

## How the virtual proxy serves add-ons (the baked manifest)

`repository.tony7bones` is built on i96751414's `repository.github` engine. Once
installed it runs a local HTTP server on **`127.0.0.1:61234`** (its `addon.xml`
points `<info>`/`<checksum>`/`<datadir>` there) that serves add-on metadata and
zips streamed live from GitHub. It is driven by a **baked**
`resources/repository.json` manifest — `lib/service.py` constructs the
`Repository` from `os.path.join(ADDON_PATH, "resources", "repository.json")`,
i.e. the copy inside the **installed** add-on. The proxy does **not** read
`addons/addons.xml` at runtime.

Consequence: to change what the repo serves, edit the single canonical
`repository.json` at `addons/repository.tony7bones/resources/` and **release** the
repo add-on (see `release-and-deploy.md` → "Adding an add-on to what the repo
SERVES"). The user's installed repo add-on must update to pick up the new baked
manifest.
