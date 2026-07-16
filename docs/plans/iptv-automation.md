# Plan - Automate IPTV setup from `.env`

> Status: **PROPOSED - for review, nothing built.** Decisions in the "Open
> decisions" section must be confirmed before any code. No repo changes yet.

## Goal

Drive the whole IPTV setup from the (gitignored) `.env` instead of hand-built
files. `.env` provides:

| var             | meaning                                               |
| --------------- | ----------------------------------------------------- |
| `IPTV_NAME`     | provider/display name (e.g. the group/instance label) |
| `IPTV_USER`     | provider account username                             |
| `IPTV_PASSWORD` | provider account password                             |
| `IPTV_M3U`      | the provider M3U URL (usually embeds user/pass)       |
| `IPTV_EPG`      | the provider EPG/XMLTV URL                            |

From those, generate the curated playlist + the Kodi `pvr.iptvsimple` config
automatically, so adding/refreshing IPTV is one command, not manual file
surgery.

## ⚠️ The hard constraint: these are SECRETS

`IPTV_M3U` / `IPTV_EPG` (and therefore the generated playlist and
`instance-settings-1.xml`) contain your provider credentials. **None of them may
be committed to this public repo or served from GitHub Pages** - that would leak
your account to the world.

- `.env` is already gitignored (just fixed). It stays local only.
- Every secret-bearing OUTPUT (the curated m3u, `instance-settings-1.xml`) must
  be written to a **gitignored** local/staging location, never under `repo/` or
  `dropbox/`.
- Only **non-secret** IPTV data may live in the repo: the channel-**group names**
  (`customTVGroups-*.xml` - already public in `dropbox/iptv/`) and the curation
  logic (`make_custom_m3u.py`).

This is the single most important rule in this plan.

## Current state (what exists today)

- `_tools/make_custom_m3u.py` - reads a **local** `network24_plus.m3u` (hand-
  downloaded, kept OUTSIDE the repo at the parent dir) and writes a curated
  `network24_custom.m3u` (parent dir, not committed). It filters to 3 groups
  (`USA ENTERTAINMENT`, `USA NEWS/WEATHER`, `PPV EVENTS`), relabels them, fixes
  caps/abbreviations, alpha-sorts two of them.
- `dropbox/iptv/customTVGroups-Network24.xml` - the custom channel groups
  (public, just names) the bootstrap installs.
- `repo/script.tony7bones.bootstrap/default.py` - on install, **copies** user-
  placed device files into Kodi userdata:
  - device `…/tony.7.bones/iptv/instance-settings-1.xml` → `addon_data/pvr.iptvsimple/instance-settings-1.xml`
  - device `…/tony.7.bones/iptv/customTVGroups-Network24.xml` → `addon_data/pvr.iptvsimple/channelGroups/…`
    Then `_ensure_iptv_custom_tv_groups()` patches `tvGroupMode=2` (custom) +
    `customTvGroupsFile` in instance-settings (pvr.iptvsimple instance settings
    **can't** be set via JSON-RPC - they live only in that XML).

So today the human: downloads the m3u, runs the curator, hand-writes
instance-settings, drops both on the device; the bootstrap installs them.

## Proposed automation

A new `_tools/build_iptv.py` that reads `.env` and produces everything:

1. **Fetch** the provider M3U from `IPTV_M3U` (auth via the URL / `IPTV_USER` +
   `IPTV_PASSWORD`).
2. **Curate** it through the existing `make_custom_m3u.py` logic (refactored to
   accept an input path/stream + output path instead of the hardcoded
   `network24_*` filenames) → the curated m3u.
3. **Generate** `instance-settings-1.xml` from a template, filling in the m3u
   source + `IPTV_EPG` + `tvGroupMode=2` + `customTvGroupsFile` (so the bootstrap
   no longer needs a hand-written one).
4. **Reuse** the public `customTVGroups-*.xml` for group names (no secret).
5. **Write all secret outputs to a gitignored staging dir** (e.g. `iptv-build/`,
   added to `.gitignore`), never into `repo/`/`dropbox/`.

Then the generated files reach the device by the SAME mechanism as today (the
bootstrap's device-file copy) - or, optionally, pushed straight to the box over
ADB via `_tools/firetv.sh`.

```
.env  ──build_iptv.py──▶  iptv-build/ (gitignored, secret)
                            ├─ <name>_custom.m3u          (curated playlist)
                            └─ instance-settings-1.xml    (m3u + EPG + groups)
                          + repo/dropbox customTVGroups   (public group names)
                                   │
                                   ▼  (device copy or ADB push)
                          Kodi pvr.iptvsimple on the box
```

## Open decisions (confirm before building)

1. **Curated playlist vs. raw provider URL.** Two ways for Kodi to get channels:
   - **(a) Curated, on-device file** - run `build_iptv.py`, get the relabeled/
     filtered m3u, place it on the box; instance-settings points at the local
     file. Keeps your nice grouping/relabeling. (Matches today's intent.)
   - **(b) Raw live URL** - instance-settings points `m3uUrl` directly at
     `IPTV_M3U`; Kodi fetches the provider list live, grouping via
     `customTVGroups` only (no relabel/filter). Simpler, always fresh, but loses
     the curation. → **Which do you want?** (I lean (a), since you built a curator.)
2. **EPG: live URL vs. cached file.** Point `epgUrl` at `IPTV_EPG` directly
   (live), or download/cache it alongside the m3u? (Live is simpler.)
3. **How files reach the device.** Keep today's manual device-drop + bootstrap
   copy, or add an ADB push (`firetv.sh`) so `build_iptv.py` can deploy to a box
   directly? (Manual is zero new surface; ADB is more "automated".)
4. **Vault vs. .env.** Your global setup keeps secrets in `~/.dotfiles/VAULT.md`
   and generates `.env` via the `env-init` skill. Should `build_iptv.py` read
   `.env` (this plan), or pull from the vault directly? (`.env` is simpler and
   already in place.)
5. **Generalize beyond Network24?** `IPTV_NAME` suggests one provider. Keep it
   single-provider, or support multiple `.env` profiles later? (Start single.)

## Phased build (once decisions are locked)

- **Phase 1 - refactor the curator.** Make `make_custom_m3u.py` a reusable
  function (input path/stream → output path); keep its CLI behavior. Tests for
  the curation stay green. _No secrets, no behavior change._
- **Phase 2 - `build_iptv.py`.** Read `.env`, fetch the provider m3u, curate,
  emit the curated m3u + `instance-settings-1.xml` into the gitignored
  `iptv-build/`. Unit-test with a fake `.env` + fixture m3u (no real creds).
- **Phase 3 - deploy path.** Wire the generated files into the device-copy flow
  (and/or ADB push per decision #3). Document the one-command refresh.
- **Phase 4 - verify on a real box.** Confirm channels + groups + EPG load in
  Kodi (honest verification, per the local-Kodi / firetv playbooks).

## Safety / acceptance

- `.env` and every secret output (`iptv-build/`, the curated m3u,
  instance-settings) are gitignored - a negative test asserts none appear in
  `git status` / the committed tree.
- No provider URL, username, or password ever lands under `repo/`, `dropbox/`,
  or on GitHub Pages.
- Existing tests + the generate/consistency gates stay green.
