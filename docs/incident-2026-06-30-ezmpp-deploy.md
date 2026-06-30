# Incident 2026-06-30: a one-line manifest bug turned a deploy into a 2-hour ordeal

Honest record, written by the agent responsible, so it is never repeated. Deploying a new
add-on (EZ Maintenance++) to this repo took **~2 hours** and multiple wrong diagnoses. The
actual bug was a **single missing line** in the add-on manifest. Almost all of the lost time
was self-inflicted: chasing a wrong theory instead of reproducing what the server served.

## Impact

- The owner could not see their newly released add-on under Program add-ons for ~2 hours.
- Trust damage from repeated confident-but-wrong "it's the cache, just refresh" guidance.
- Several avoidable extra pushes (empty commits, version churn `.12 -> .13 -> .14`).

## Root cause (the real one)

`addons/script.ezmaintenanceplusplus/addon.xml` did **not** declare
`<import addon="xbmc.python" version="3.0.0"/>` in its `<requires>`. **Kodi 19+/Omega
silently hides any add-on that does not declare `xbmc.python` compatibility** - it is
treated as incompatible, with no error and no log line the owner would see. No cache
refresh, restart, or re-release could ever surface it. The sibling add-on that _did_ show
(`script.tony7bones.modv2plus`) declares `xbmc.python 3.0.0`; ours did not. Fix: add the
import, bump version, re-ship. Done in `2026.06.30.13`.

## Contributing factors (why a one-line bug cost 2 hours)

1. **The proxy self-updates from GitHub Pages, and Pages silently did not build.**
   `release.py --proxy` pushed + tagged, then tried to force a Pages build; the owner's
   token lacks `pages: write` (403), and GitHub did not auto-fire a build for the push. The
   proxy zip stayed 404 on Pages, so boxes could not update the proxy at all ("Update
   failed" / retry loop). ~40 minutes. Fixed by re-triggering Pages with an empty-commit
   push, then codified in `publish-gate.sh`.
2. **raw.githubusercontent CDN lag.** After each fix, raw served the _old_ manifest for a
   few minutes, which looked like the fix had not landed.
3. **The real failure: diagnosing by theory instead of by reproduction.** The agent
   asserted "Kodi cached the old list, just refresh" repeatedly **without ever reproducing
   what the proxy actually serves.** The moment it did - a ~15-line script that replicates
   the proxy's `addons.xml` generation from live data - the `xbmc.python` difference was
   obvious in one run. That reproduction should have been step one, not step ten.

## Resolution

- `2026.06.30.13`: added `<import addon="xbmc.python" version="3.0.0"/>`; the add-on
  appeared under Program add-ons.
- `2026.06.30.14`: separately, removed the upstream authors from the app `provider-name`
  (credited in the README instead).

## Action items

- [x] **Deploy skill + `publish-gate.sh`** (`.claude/skills/deploy/`): runs the release and
      then guarantees Pages actually published (re-triggers until live). Prevents factor 1.
- [x] **`xbmc.python` pre-flight check** documented in the deploy skill: a served add-on
      whose `addon.xml` omits `<import addon="xbmc.python" ...>` will be invisible on Kodi
      19+. Lint: `grep -L 'addon="xbmc.python"' addons/*/addon.xml` must be empty.
- [ ] **Recommended:** point the proxy's own zip at raw in `repository.json` so proxy
      releases never depend on a Pages build (kills factor 1 at the source).

## The rule that would have prevented this

**When something you deployed is not visible, reproduce the server's actual served output
before theorizing about client-side caches.** One faithful reproduction of the proxy's
generated `addons.xml` would have found this in minutes. Theories are not evidence.
