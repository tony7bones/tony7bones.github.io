# Plan — One `.env` → per-device config (consolidate all personal box settings)

> Status: **APPROVED FOR BUILD** after QA review (SOUND-WITH-CHANGES) + owner
> decisions. Supersedes `iptv-automation.md` (the laptop-generates-files model) —
> this is the consolidated, on-box-injection model. Branch:
> `feature/env-config-consolidation`.

## Goal

Collapse every **personal / per-box** setting into **one** gitignored master
`.env` (synced from the vault), and have the box configure itself from it — no
more multiple hand-placed device files, no hardcoded Sacramento. Secrets never
touch the public repo.

## The cascade

```
~/.dotfiles/VAULT.md ─(env-init)→ ./.env  (gitignored master, all personal settings)
        │
        │  provisioner reads ./.env, resolves what it can (e.g. Yahoo geocode of
        │  WEATHER_LOCATIONS → loc1–5), substitutes per-box DEVICE_NAME, and writes
        │  a per-device tony7bones.env to the box (NO connection metadata like
        │  DEVICE_IP — that stays laptop-side).  Re-pushed every run = "in sync".
        ▼
   box: bootstrap reads tony7bones.env (if present) → INJECTS each value into the
        existing idempotent settings writers.  Absent → built-in non-secret
        defaults (keyless-Yahoo weather, no IPTV provider, stock RSS).
```

**Key architectural choice (per QA): INJECT values, do NOT generate whole files.**
We reuse the bootstrap's existing, proven, "write-only-on-change" writers and feed
them per-box values — instead of synthesizing Kodi config files from scratch.

## What the `.env` holds (owner decision: keep ALL knobs)

We keep every knob in the file — even the ones that are fixed today — because it
costs nothing, makes the file self-documenting, and turns each into a ready knob
(the day a box wants Standard level or a real web password). Knobs that are
"rarely changed" get a comment saying so.

| Section               | Keys                                                                   | Per-box? | Secret?                                    |
| --------------------- | ---------------------------------------------------------------------- | -------- | ------------------------------------------ |
| Identity / connection | `DEVICE_NAME`, `DEVICE_IP`                                             | yes      | no (`DEVICE_IP` laptop-only, never pushed) |
| Remote control        | `KODI_WEB_USER/PASS/PORT`, `KODI_REMOTE_CONTROL`                       | rarely   | pass = weak secret                         |
| UI                    | `SETTINGS_LEVEL`                                                       | rarely   | no                                         |
| Weather               | `WEATHER_LOCATIONS` (≤5), `WEATHERBIT_API_KEY`, `OWM_API_KEY`          | yes      | keys = yes                                 |
| IPTV                  | `IPTV_NAME`, `IPTV_M3U`, `IPTV_EPG`, `IPTV_GROUPS`, `IPTV_GROUPS_ONLY` | yes      | m3u/epg = yes                              |
| RSS                   | `RSS_INTERVAL`, `RSS_FEEDS`                                            | yes      | no                                         |

What stays **fixed in code** (NOT in `.env` — same on every box): curated repos +
video add-ons, the MOD V2 skin + MOD V2+ patch, the home-menu trim/POV/widgets,
the file-manager sources, the weather **provider** choice (`weather.multi`), and
the IPTV `tvGroupMode` enforcement logic.

## QA-mandated guardrails (all must land before/with the code)

1. **Fix the leaky `.gitignore` FIRST + a negative test.** Today `.gitignore`
   matches `.env`/`.env.*` but NOT `tony7bones.env`, `iptv-build/`,
   `*_custom.m3u` (all resolve as TRACKED). Add: `*.env`, `tony7bones.env`,
   `/iptv-build/`, `*_custom.m3u`. Add a test (in the `_tools` suite) asserting
   none of these — nor any string matching the provider host / an API key — ever
   appears in `git ls-files` / `git status --porcelain`.
2. **Never log secret values.** The bootstrap logs every config step. The new
   reader/injector logs **"key present / file written"**, never the value. Unit
   test: run the injector against a fake env and assert no secret substring lands
   in captured log output.
3. **Don't generate `instance-settings-1.xml`.** Keep copying/staging it; inject
   only `m3uPathType/m3uPath`(=`IPTV_M3U`) + `epgPathType/epgPath`(=`IPTV_EPG`)
   via the existing `_ensure_iptv_custom_tv_groups()` / `_set_instance_setting()`
   path (it already owns `tvGroupMode`/`customTvGroupsFile`/`tvChannelGroupsOnly`).
4. **Clean no-`.env` fallback.** A GUI / no-env install must not set
   `tvGroupMode=2` pointing at a groups file that isn't there (→ empty channels).
   Gate IPTV-custom enforcement on the groups file actually existing (or on env
   presence); otherwise leave `tvGroupMode` at the all-channels default.
5. **Robust parser, not hand-rolled.** Laptop side: source the file in bash
   (it's already shell syntax). On-box Python: strip quotes, strip inline
   `#`-comments only when unquoted, split `;`-lists then `.strip()` each item,
   skip empty/unknown keys (never emit an empty XML field). Tests: inline comment,
   value-with-`;`, empty value, missing key, blank line, CRLF.
6. **Idempotent re-sync.** Reuse the "write only if changed" pattern; generate to
   temp + compare before replacing; never clobber on a no-op run.
7. **Per-device env location on the box.** Push `tony7bones.env` to a path the
   file-manager sources do NOT expose and that is NOT under `userdata/`; the
   bootstrap reads then it can be removed. Never leave creds in a served/temp path.

## What the bootstrap injects (mapping)

| `.env` key(s)                                                        | Injected into                             | Mechanism                                                        |
| -------------------------------------------------------------------- | ----------------------------------------- | ---------------------------------------------------------------- |
| `WEATHER_LOCATIONS` (provisioner resolves → loc1–5 name/url/lat/lon) | `weather.multi/settings.xml`              | extend `_set_weather_location` (loc1 → loc1–5)                   |
| `WEATHERBIT_API_KEY` / `OWM_API_KEY`                                 | `weather.multi/settings.xml`              | same writer: `WAdd=true`+`API`, `WMaps=true`+`MAPAPI`            |
| `IPTV_M3U` / `IPTV_EPG`                                              | `pvr.iptvsimple/instance-settings-1.xml`  | extend `_ensure_iptv_custom_tv_groups` (`_set_instance_setting`) |
| `IPTV_GROUPS`                                                        | `channelGroups/customTVGroups-<name>.xml` | small-file generation (group names only — not secret)            |
| `IPTV_GROUPS_ONLY`                                                   | instance-settings `tvChannelGroupsOnly`   | already enforced; value from env                                 |
| `RSS_FEEDS` / `RSS_INTERVAL`                                         | `userdata/RssFeeds.xml`                   | small-file generation                                            |
| `DEVICE_NAME`                                                        | `services.devicename`                     | provisioner prompt + guisettings (today)                         |
| `KODI_WEB_*` / `KODI_REMOTE_CONTROL`                                 | guisettings `services.*`                  | provisioner seed (today), values from env                        |
| `SETTINGS_LEVEL`                                                     | guisettings `<general><settinglevel>`     | provisioner sed (today), value from env                          |

## Phased build

- **Phase 0 — Safety preconditions.** `.gitignore` fix + the secret-leak negative
  test. Nothing else starts until this is green.
- **Phase 1 — `.env` reader.** A small, well-tested parser (laptop bash + on-box
  Python) with the robustness tests above. No behavior change yet.
- **Phase 2 — Weather injection.** `_set_weather_location` → up to 5 locations +
  the two keys (provisioner resolves the city names via Yahoo). Test + verify.
- **Phase 3 — IPTV/RSS injection.** m3u/epg into instance-settings; generate
  customTVGroups + RssFeeds from env. Clean no-env fallback. Test + verify.
- **Phase 4 — Identity/UI from env.** device name, web creds, settings level read
  from env (provisioner prompt still overrides `DEVICE_NAME` per box).
- **Phase 5 — Provisioner per-device sync.** Read `./.env`, derive + push
  `tony7bones.env`; re-sync each run. Honest verify on the bedroom TV + QA.

Each phase keeps the full test suite + ruff + the generate/consistency gates
green, and verifies on the real box per the local-Kodi / firetv playbooks.

## Safety / acceptance

- `./.env`, `tony7bones.env`, `iptv-build/`, `*_custom.m3u` are gitignored — a
  negative test asserts none appear in `git status` / the committed tree, and no
  provider host / API-key string appears anywhere under the repo.
- No secret value is ever `xbmc.log`'d (unit-tested).
- No-`.env` GUI install is a first-class supported mode (keyless weather, no IPTV
  provider, stock RSS) — tested.
- Existing tests + gates stay green.

## QA final review — GO, with binding acceptance criteria

Plan passed final QA (**GO**). Three items are binding for the build (refinements,
not re-plan):

- **A. No-env IPTV contract (regression that ships TODAY).**
  `_ensure_iptv_custom_tv_groups()` currently sets `tvGroupMode=2` +
  `customTvGroupsFile` + `tvChannelGroupsOnly=true` **unconditionally** — on a
  no-env / no-groups-file box that means "custom groups" pointing at a missing
  file → an **empty channel list**. Phase 3 MUST: when neither the env nor a
  groups file is present, write NONE of those three keys (leave the all-channels
  default); and reconcile the hardcoded `customTVGroups-Network24.xml` constant
  with the env-driven `customTVGroups-<IPTV_NAME>.xml` mapping so the enforced
  path and the generated file agree. Ship a regression test.
- **B. Yahoo-geocode failure behavior (Phase 2).** Resolving `WEATHER_LOCATIONS`
  → loc1–5 is a new laptop-side network call. Spec: timeout + retry; on failure
  fall back to last-good or the existing hardcoded Sacramento defaults; **never**
  push an empty `loc*_url` (empty url = no weather).
- **C. Negative-test mechanism (Phase 0, re-run after Phase 5).** The secret-leak
  test scans `git ls-files` ONLY (tracked files, not a dev's local gitignored
  `.env`), sources the forbidden host/key strings from the gitignored env/vault
  at runtime (never hardcodes them), and is re-asserted after Phase 5 (the first
  phase producing a real secret-bearing `tony7bones.env`).

## Out of scope (tracked separately)

- **TiviMate backup.** `dropbox/iptv/TiviMate_backup_*.tmb` is committed and
  served at `https://tony7bones.github.io/iptv/` (HTTP 200, 6.5 MB) — a restorable
  IPTV-account backup. **Owner is keeping it for now** pending a storage decision.
  When ready: `git rm` from the served tree, add `*.tmb` to `.gitignore`, and
  rotate the provider password (it has been public). Not part of this feature.
