# Playbook — One-shot setup & the add-on architecture

The shipped first-party add-on architecture, the shared-library pattern, and the
one-shot flow. Design source: `../plans/one-shot-option-b-plan.md` (implemented).
Code: `addons/script.module.tony7bones/`, `addons/script.tony7bones.bootstrap/`,
`addons/script.tony7bones.modv2plus/`.

---

## The first-party add-ons

| Add-on                        | Name (in Kodi)              | Kind                                         | On home screen?               |
| ----------------------------- | --------------------------- | -------------------------------------------- | ----------------------------- |
| `repository.tony7bones`       | Tony.7.Bones Repo           | virtual proxy repository                     | n/a (the repo add-on)         |
| `script.module.tony7bones`    | Tony.7.Bones Shared Library | `xbmc.python.module` (Python LIBRARY)        | **No** — no executable        |
| `script.tony7bones.bootstrap` | Tony.7.Bones Setup          | `xbmc.python.script` + `provides>executable` | Only until it self-uninstalls |
| `script.tony7bones.modv2plus` | Estuary MOD V2+             | `xbmc.python.script` (manual-only)           | Hosted; run by hand           |

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
   (`plugin.video.pov`), The Loop (`plugin.video.the-loop`), and Sports HD
   (`plugin.video.sporthdme`) — with their closure; origins are stamped, and the
   install-then-disable set (Dailymotion, `plugin.video.dailymotion_com`, a
   required-but-unused import of The Loop) is applied. A video failure is
   non-fatal — it never aborts the box. `plugin.video.umbrella` is **not**
   installed (but `repository.umbrella` stays in the repo, browsable/proxy-served).
3. **One combined summary** (repos · apps · video counts).
4. **Base-only steps:** add the File-Manager sources, trim the Estuary home menu
   to TV / Add-ons / Favourites / Weather (see `kodi-install-mechanics.md` §11).
5. **Self-uninstall** the base Setup. The **shared library is left installed**.
6. **One restart** (`restart_kodi`) finalises every freshly extracted add-on and
   the self-removal.

A cancelled progress dialog mid-install aborts cleanly: no summary, no
self-uninstall, no restart (the partial install is harmless; re-running Setup
completes it).

> Installing the Estuary MOD V2 skin and applying the MOD V2+ patch
> (`script.tony7bones.modv2plus`) are still **manual** steps today — they are NOT
> part of the one-tap run.

## The curated video install (`install_selection`)

`install_selection(selected, official_base, disable_ids, dialog, log)` (in the
shared library's `install.py`) is the entry point the base Setup calls to install
the curated video apps. It enables the source repos, builds a combined index from
the installed repos plus the official repo, resolves the closure for the selected
ids, extracts/enables/origin-stamps it, and applies the install-then-disable set.
It never prompts, summarises, self-uninstalls, or restarts — the caller (the
Setup's `run()`) owns those, which is why the run has exactly one summary and one
restart.

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
