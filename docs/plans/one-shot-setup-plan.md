# One-Shot Setup - Plan: chaining "Video Add-ons Setup" from the base "Tony.7.Bones Setup"

> **STATUS: DONE / IMPLEMENTED (historical).** This was the options-discussion
> draft. The path actually built is the one in `one-shot-option-b-plan.md`
> (Option B: shared library module + front-loaded prompts + inline video step).
> Kept for context only - see `../playbooks/one-shot-and-architecture.md` for how
> the shipped system works, and the live code in `repo/script.tony7bones.bootstrap/`
> and `repo/script.tony7bones.video/`.

Status: PROPOSAL for review (no code written). Author note: internal planning doc.

## The goal

Let the base **Tony.7.Bones Setup** optionally trigger **Video Add-ons Setup** in the
same run, so a fresh box can be configured - base essentials + chosen video apps - in a
single, mostly-unattended pass that ends with **one** restart and **no** leftover tiles.
A "one-shot": tick a box, walk away, come back to a finished box.

## Where things stand today (the two pieces we're joining)

- `script.tony7bones.bootstrap` ("Tony.7.Bones Setup") - installs the 12 repos +
  EZ Maintenance+ + RealDebrid + Multi Weather + IPTV Simple (binary, platform-correct).
  Prompt-free. Shows a summary, **self-uninstalls**, offers a **restart** (needed because
  the binary IPTV client wants Kodi to settle).
- `script.tony7bones.video` ("Video Add-ons Setup") - **multiselect** (POV / The Loop /
  Sports HD pre-checked, Umbrella unchecked) → installs the selected apps + full
  dependency closure **resolved from the installed repos** → **self-uninstalls**. No
  restart (pure-python plugins).
- Both are independent, self-contained, self-uninstalling Program add-ons in our repo.

## What a clean "hook" has to get right

1. **Opt-in control** - the checkbox.
2. **Ordering** - the base repos must be installed _and registered_ before the video step
   runs, because the video resolver reads the installed repos to find POV/Loop/etc.
3. **Exactly one restart**, at the very end (the base's binary IPTV is what needs it; the
   video apps don't). No double-restart, no restart firing mid-install.
4. **Both pieces still self-uninstall cleanly** - no leftover home/Program tiles.
5. **The video add-on must be available** to run at hook time.
6. Ideally a **true walk-away**: all human interaction happens up front, then unattended.

## Options

### Option A - "Launch the script" hook (lightest touch)

Base setup gains a start-of-run prompt: _"Also set up Video Add-ons?"_. If yes, base does
its normal install, then as its final step **installs `script.tony7bones.video`**
(direct-extract from our Pages, the same way it used to fetch the MOD V2 patch) and
**launches it** via `RunScript(..., chained)`; base then **suppresses its own restart** and
self-uninstalls. The video add-on, seeing the "chained" flag, runs its multiselect →
install → self-uninstall → and **owns the single final restart**.

- Pros: minimal change; keeps the two add-ons separate; reuses the video add-on almost
  as-is.
- Cons: a cross-script handoff (who launches whom, who owns the restart) - more timing
  edge cases; and the video multiselect appears _after_ base finishes, so it's not a pure
  walk-away unless we also pass the selection up front as launch args.

### Option B - Shared library module + inline step ★ recommended

Refactor the common machinery (repo discovery, index build/merge with highest-version
wins, closure resolve, download+extract, enable, self-uninstall, restart) into a new
**`script.module.tony7bones`** library add-on in our repo. Both setup add-ons declare it
as a `<requires>` import, so **Kodi auto-installs it** when either Setup is installed from
the repo (native dependency resolution - no chicken-and-egg).
Then the base setup, when "include video" is checked, **front-loads both prompts** (the
yes/no + the video multiselect) at the very start, runs base install + video install
**inline in one script execution**, then **one** restart, then self-uninstall. The
standalone Video Add-ons Setup calls the same shared functions.

- Pros: a **single control flow** → no cross-script timing; trivially correct single
  restart + single clean-up; a **true walk-away** one-shot (all interaction up front); no
  duplicated logic; cleaner to maintain long-term.
- Cons: more upfront work - a new shared module, refactor both add-ons onto it, and three
  add-ons to version/release; Kodi dependency wiring.

### Option C - Merge into one add-on (rejected)

Fold video into the base setup as an optional section. Rejected: you like the
two-installer separation (base = bare essentials; video = separate), and a standalone
video installer stays useful on already-set-up boxes.

## Recommendation

**Option B** for the cleanest, least-fragile _true_ one-shot - with **Option A** available
as a faster interim if you want the hook sooner with less refactoring.

## Proposed UX (Option B - the ideal one-shot)

Running **Tony.7.Bones Setup**:

1. Prompt: _"Also install Video Add-ons after setup?"_ - Yes / No.
2. If **Yes** → immediately show the video **multiselect** (POV / The Loop / Sports HD
   pre-checked, Umbrella unchecked).
3. Then fully unattended: base install → video install (selected) → one combined summary
   → single _"Setup complete - restart now?"_ → self-uninstall(s) → restart.

You answer at most two quick prompts up front, walk away, and return to a configured,
restarted box with a clean home screen.

## Restart & self-uninstall handling

- **One** restart, after both phases (the binary IPTV client is the reason a restart is
  warranted; video apps are pure-python and don't need it).
- The user-facing Setup add-on(s) self-uninstall. **Leave the shared module installed**
  (it's a tiny dependency Kodi manages; removing it would force a re-download if a Setup is
  ever re-run). Decision point - see open questions.

## Edge cases to handle

- User cancels the video multiselect → run base only, normal restart.
- "Include video" unchecked → today's exact base behaviour, untouched.
- Base install partially fails → still proceed to video; the video step resolves from
  whatever repos succeeded; honest combined summary.
- A source repo for a chosen video app is missing → graceful skip + report (the video
  add-on already does this).
- Offline / `mirrors.kodi.tv` HTTP 429 → report counts, never hang. (Worth pairing with
  the known TODO: add retry/backoff to the resolver.)

## Verification plan (real Kodi - the standard we've held to)

- Fresh profile, base with **include video = Yes**, default selection → confirm base apps
  **and** POV/Loop/Sports HD installed + _functional_ (launch each, no ImportError), a
  **single** restart, **both** Setup add-ons gone, clean home.
- Base with **include video = No** → behaviour identical to today.
- Standalone **Video Add-ons Setup** still works on an already-set-up box.
- Verify on macOS and, ideally, the **Fire Stick** (binary + restart path).

## Release impact

- Option B introduces **`script.module.tony7bones`** (new) and bumps **bootstrap** and
  **video**. All ship via the normal generate → commit → push path; each changed add-on
  must version-bump (pre-push gate). The shared module becomes a `<requires>` of both, so
  Kodi pulls it from the repo automatically.
- Option A bumps only **bootstrap** (and reuses video unchanged, or a tiny "chained" flag
  bump).

## Open questions for you (answer on return)

1. **Default of the "include video" checkbox** - opt-in (unchecked) or pre-checked?
2. **Front-load** the video multiselect (true walk-away, Option B) - or show it after base
   finishes (Option A style)?
3. **Option B (shared module) now**, or **Option A** lighter hook first and refactor later?
4. **One combined summary** at the end, or a separate summary per phase?
5. **Leave the shared module installed** (recommended) or also remove it on cleanup?
