# Playbook — One-shot setup & the add-on architecture

The shipped three-add-on architecture, the shared-library pattern, and the
one-shot flow. Design source: `../plans/one-shot-option-b-plan.md` (implemented).
Code: `repo/script.module.tony7bones/`, `repo/script.tony7bones.bootstrap/`,
`repo/script.tony7bones.video/`.

---

## The first-party add-ons

| Add-on                          | Name (in Kodi)              | Kind                                         | On home screen?               |
| ------------------------------- | --------------------------- | -------------------------------------------- | ----------------------------- |
| `script.module.tony7bones`      | Tony.7.Bones Shared Library | `xbmc.python.module` (Python LIBRARY)        | **No** — no executable        |
| `script.tony7bones.bootstrap`   | Tony.7.Bones Setup          | `xbmc.python.script` + `provides>executable` | Only until it self-uninstalls |
| `script.tony7bones.video`       | Video Add-ons Setup         | `xbmc.python.script` + `provides>executable` | Only until it self-uninstalls |
| `script.tony7bones.modv2.patch` | Estuary MOD V2 Patch        | `xbmc.python.script` (manual-only)           | Hosted; run by hand           |

Plus the **`repository.tony7bones`** virtual proxy itself (the repo add-on).

### Shared-library pattern

`script.module.tony7bones` carries **all** the generic install machinery so the
two Setups hold only their own configuration:

- `net.py` — HTTP fetch (gunzips `.gz`), zip extract, `UpdateLocalAddons`,
  enable/disable via JSON-RPC.
- `index.py` — addons.xml load/parse/merge + the two closure resolvers
  (ordered for the base Setup; combined/highest-wins for the video Setup).
- `repos.py` — installed-repo discovery, source-repo enabling, **origin
  stamping** into `Addons<NN>.db`.
- `install.py` — the two install orchestrators (`install_with_deps`,
  `install_closure` + `disable_after_install`).
- `system.py` — platform tag, Android detection, self-uninstall, restart.

Both Setups declare `<requires><import addon="script.module.tony7bones"
version="1.0.0"/>`, so Kodi **auto-installs the library from the repo** when
either Setup is installed — no chicken-and-egg. The library is invisible on the
home screen because it provides no executable. Keep its public API small and
stable; bump the module version + both Setups' `<requires>` together if the
contract ever changes.

## The one-shot flow (base "Tony.7.Bones Setup")

`script.tony7bones.bootstrap/default.py:run()`:

1. **Front-loaded prompts (before any install):**
   - "Also install Video Add-ons after setup?" — yes/no, **default No** (opt-in,
     via `xbmcgui.DLG_YESNO_NO_BTN`, with a graceful fallback on older Kodi).
   - If Yes: the video **multiselect** (POV / The Loop / Sports HD pre-checked,
     Umbrella unchecked). Labels are static, so the picker needs no repos
     installed — the selection is captured up front.
2. **Unattended phase (no more prompts):**
   - Base install: extract the 12 repo installer zips → register/enable → install
     each base app with its full dependency closure
     (`script.ezmaintenanceplus`, `script.realdebrid` from peno64; `weather.multi`
     and the binary `pvr.iptvsimple` from the official repo, platform-correct).
   - If video was chosen: `_install_video()` delegates to the video module's
     `install_selected()` — the **same code** the standalone video Setup runs —
     so the chosen video apps + closure install, origins are stamped, and the
     install-then-disable set (Dailymotion) is applied.
3. **One combined summary** (`Repos x/12 · Patches · Apps a/b · Video v/w`).
4. **Base-only steps:** add the File-Manager sources, trim the Estuary home menu
   to TV / Add-ons / Favourites / Weather (see `kodi-install-mechanics.md` §11).
5. **Self-uninstall** the base Setup; if video was chained, also remove the video
   Setup's tile (its standalone path removes itself, but the chained path never
   reaches that code). The **shared library is left installed**.
6. **One restart** (`restart_kodi`) finalises every freshly extracted add-on and
   the self-removal.

If video = No → exactly the base behaviour, just sourced from the shared module.

A cancelled progress dialog mid-install aborts cleanly: no summary, no
self-uninstall, no restart (the partial install is harmless; re-running Setup
completes it).

## The standalone "Video Add-ons Setup"

`script.tony7bones.video/default.py:run()`: bails early with a clear message if no
source repos are installed yet; otherwise shows the same multiselect, calls
`install_selected()`, summarises, self-uninstalls, and restarts (only if at least
one app installed). `install_selected(selected, dialog)` is the shared entry point
used by **both** the standalone run and the base Setup's chained run — it never
prompts, summarises, self-uninstalls, or restarts; the caller owns those, which is
why the chained run has exactly one summary and one restart.

## How the virtual proxy serves add-ons (the baked manifest)

`repository.tony7bones` is built on i96751414's `repository.github` engine. Once
installed it runs a local HTTP server on **`127.0.0.1:61234`** (its `addon.xml`
points `<info>`/`<checksum>`/`<datadir>` there) that serves add-on metadata and
zips streamed live from GitHub. It is driven by a **baked**
`resources/repository.json` manifest — `lib/service.py` constructs the
`Repository` from `os.path.join(ADDON_PATH, "resources", "repository.json")`,
i.e. the copy inside the **installed** add-on. The proxy does **not** read
`repo/addons.xml` at runtime.

Consequence: to change what the repo serves, edit **both** `repository.json`
copies and **release** the repo add-on (see `release-and-deploy.md` → "Adding an
add-on to what the repo SERVES"). The user's installed repo add-on must update to
pick up the new baked manifest.
