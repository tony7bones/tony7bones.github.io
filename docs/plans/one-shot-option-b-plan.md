# One-Shot Setup — Option B implementation plan (shared module + inline, front-loaded)

> **STATUS: DONE / IMPLEMENTED.** Shipped in `repository.tony7bones` 1.0.11
> (`script.module.tony7bones` 1.0.0, `script.tony7bones.bootstrap` 1.1.0,
> `script.tony7bones.video` 1.1.0). The code matches this plan — the shared
> machinery lives in `script.module.tony7bones`, the base Setup front-loads the
> two prompts and runs the video step inline, one combined summary, one restart,
> the base Setup self-uninstalls, the library stays installed (invisible). See
> `../playbooks/one-shot-and-architecture.md`.

Status: APPROVED DIRECTION, ready to build on your go. No code yet. Internal planning doc.
Supersedes the options discussion in `one-shot-setup-plan.md` for the chosen path.

## Decisions locked (your answers)

1. "Include video" checkbox default → **unchecked (opt-in)**.
2. Prompts → **front-loaded** (all interaction up front, then unattended walk-away).
3. Architecture → **Option B: shared library module + inline step**.
4. Summary → **one combined summary at the very end**.
5. Shared module → **leave it installed**. (It's a `script.module` _library_ add-on — no
   `executable`, no script entry point — so it NEVER appears on the home screen or under
   Program add-ons. Your "unless it takes up space on the Home Screen" condition is
   satisfied automatically: libraries are invisible there.)

## Target architecture — three add-ons

1. **`script.module.tony7bones`** (NEW) — a Python library add-on (`xbmc.python.module`)
   that holds ALL the shared install machinery. Invisible on home (library, not a program).
   - Houses: repo discovery (`_repo_dirs`), index build/merge with **highest-version-wins**
     (`_build_index`/`_merge_index`/`_ver_key`), platform tag for binaries (`_platform_tag`),
     official-repo index load, closure resolver (`_resolve_closure`), download+extract
     (`_extract_zip`), enable (`_enable` via JSON-RPC `SetAddonEnabled`), `UpdateLocalAddons`
     refresh, `_self_uninstall`, and `_restart_kodi`.
   - One public entry the Setups call, e.g. `install_ids(ids, dialog, progress)` →
     resolves closure across installed repos (+ official) and extracts+enables, returning
     per-id results for the summary.
2. **`script.tony7bones.bootstrap`** ("Tony.7.Bones Setup") — base essentials, now with the
   optional one-shot video step. `<requires>` the shared module.
3. **`script.tony7bones.video`** ("Video Add-ons Setup") — standalone video installer,
   refactored to call the shared module. `<requires>` the shared module. Behaviour for the
   standalone case is unchanged from today.

Kodi resolves `<requires>` from our repo at install time, so installing either Setup from
"Tony.7.Bones Repo" **auto-pulls `script.module.tony7bones`** — no chicken-and-egg.

## The one-shot control flow (base setup, front-loaded)

Running **Tony.7.Bones Setup**:

1. **Prompt 1** (front): _"Also install Video Add-ons after setup?"_ — Yes / No.
   Default highlight = **No** (opt-in).
2. **Prompt 2** (front, only if Yes): the video **multiselect** — POV / The Loop / Sports HD
   pre-checked, Umbrella unchecked. The labels are static, so this can be shown BEFORE any
   install; the selection is captured and held.
   - _Insight that makes front-loading clean:_ the picker needs no repos installed to be
     shown (fixed labels), so we capture the choice up front, then run everything unattended.
3. **Unattended phase** (no more prompts):
   a. Base install — 12 repos + EZ Maintenance+ + RealDebrid + Multi Weather + IPTV Simple
   (binary, platform-correct), via the shared module.
   b. `UpdateLocalAddons()` so the freshly-extracted repos are registered.
   c. If video was chosen — install the selected video apps + closure via the shared module,
   now resolving against the just-registered repos.
4. **One combined summary** dialog — e.g. `Repos x/12 · Apps a/b · Video v/w`.
5. **One restart prompt** — _"Setup complete — restart now?"_ (needed because the binary
   IPTV client wants Kodi to settle; covers the whole run).
6. **Self-uninstall** the base Setup add-on. Leave `script.module.tony7bones` installed
   (invisible library). The standalone video add-on is NOT involved in this flow (base does
   the video step inline via the module).

If "include video" = **No** → behaviour is exactly today's base setup (just now sourced from
the shared module).

## Standalone Video Add-ons Setup (unchanged UX)

Still installable from the repo and runnable on an already-set-up box: multiselect → install
via the shared module → self-uninstall. Same as today, just calling shared code.

## Restart & self-uninstall handling

- **Exactly one** restart, at the end of the whole run.
- Self-uninstall: only the user-facing **base Setup** removes itself in the one-shot flow
  (and the standalone video add-on removes itself in its own flow). The **shared module
  stays** — it's a dependency Kodi manages, invisible on home, and keeping it avoids a
  re-download if a Setup is run again later.

## Edge cases

- Cancel the video multiselect → treat as "no video"; run base only; normal restart.
- "Include video" = No → today's exact base behaviour.
- Base install partially fails → still proceed to the video step; resolve from whatever
  repos succeeded; the combined summary reports honest counts.
- A source repo for a chosen video app missing → graceful skip + report (already handled).
- Offline / `mirrors.kodi.tv` 429 → report counts, never hang. (Good moment to also add the
  resolver **retry/backoff** that's on the TODO list.)
- Shared-module version skew (an old Setup + newer module, or vice-versa) → keep the public
  function signature stable; bump the module's version and the Setups' `<requires>` minimum
  together when the contract changes.

## Build / migration steps (ordered)

1. Create `repo/script.module.tony7bones/` — `addon.xml` (`xbmc.python.module`, library,
   no executable), `lib/` with the shared functions moved out of the two current default.py
   files, version 1.0.0.
2. Refactor `script.tony7bones.video/default.py` to import + call the module; add the
   `<requires>` import; bump its version. Verify standalone still works on real Kodi.
3. Refactor `script.tony7bones.bootstrap/default.py` to import + call the module; add the
   `<requires>` import; add the two front-loaded prompts, the inline video step, the
   combined summary; bump its version.
4. `generate_repo.py` → the module appears in `repo/addons.xml`; confirm idempotent.
5. Tests: a new `_tools/test_module.py` (or fold into existing) for the shared lib;
   update `test_bootstrap.py` (one-shot prompts, requires-import, combined summary) and
   `test_video.py` (requires-import, calls shared lib). Keep all green; ruff clean.
6. Real-Kodi verification (below). Then orchestrator commits + pushes (normal path; three
   add-ons, each version-bumped per the gate).

## Versioning & release

- New: `script.module.tony7bones` 1.0.0.
- Bump: `script.tony7bones.bootstrap` and `script.tony7bones.video`.
- All ship via generate → commit → push; the pre-push gate requires each changed add-on to
  bump. The module becomes a `<requires>` of both, auto-installed from the repo.

## Verification plan (real Kodi — our standard)

- Fresh profile, base with **include video = Yes**, defaults → confirm: base apps AND
  POV/Loop/Sports HD installed + _functional_ (launch each, no ImportError); a **single**
  restart; the base Setup add-on **gone**; `script.module.tony7bones` present but **not** on
  home / not under Program add-ons; clean home.
- Base with **include video = No** → identical to today.
- Standalone **Video Add-ons Setup** still works on an already-set-up box.
- Confirm Kodi auto-installs the shared module when a Setup is installed from the repo.
- Verify on macOS and, ideally, the **Fire Stick** (binary + restart path).

## Risks / notes

- Moving logic into a module is a mechanical refactor; the behaviour is already proven, so
  risk is mostly in the wiring (imports, `<requires>`, dependency resolution) — all
  verifiable on real Kodi before release.
- Keep the module's public API small and stable so the two Setups never break on a module
  bump.

## Done-when

A fresh box: install "Tony.7.Bones Setup" from the repo → run → answer two quick prompts
(opt in to video, pick apps) → walk away → return to a fully configured, self-restarted box
with EZ Maintenance+ / RealDebrid / video apps in place, **no** Setup tiles on the home
screen, and the shared library quietly installed out of sight.
