# Incident 2026-07-07: EZ Maintenance++ showed a "Restart now?" prompt on Fire TV, where Kodi cannot restart itself

Honest record. A correctness/UX defect, NOT a hardware burn: nothing was corrupted,
deleted, or bricked. The prompt lied about what would happen, which is misleading and
erodes trust, but the operation underneath (close Kodi) was safe.

Severity: UX/correctness. Misleading prompt only; no data impact.

## Impact

- After a restore on Fire TV / Android, the add-on showed a "Restart now?" prompt. On
  those platforms Kodi cannot restart itself, so choosing it merely closed Kodi. The user
  was told the app would restart and instead it just quit, so a box that needed a manual
  reopen looked like it had hung or failed.

## Root cause (the real one)

The restart prompt used one desktop-centric wording for every platform. On Fire TV /
Android, Kodi's `RestartApp` is desktop-only and the add-on's `restart()` can only issue
a Quit, so the honest action there is "close, then the user reopens," not "restart." The
prompt did not account for this. Per commit `413dba0` ("restart prompt is honest per
platform").

Fix: `ask_restart()` is now platform-aware. On Android it says "Kodi needs to close to
finish. Close Kodi now, then reopen it" with a "Close now" button; on desktop it still
says "Restart". The single caller passes only the status line and `ask_restart()` builds
the platform-correct sentence. Shipped as `2026.07.07.5` in commit `413dba0`. This is the
same honesty lesson the Setup add-on already encodes for its own end-of-run restart on
Fire TV.

## Contributing factors

1. **One wording served two platforms with different restart capabilities.** Desktop Kodi
   self-restarts; Fire TV/Android cannot, so a single "Restart now?" string was wrong on
   half the fleet.
2. **The gap looks like a failure.** On a platform where the app just closes, a prompt
   promising a restart makes a normal close read as a crash or hang, which is exactly the
   confusion the owner has been burned by elsewhere.

## Resolution

- `2026.07.07.5` / commit `413dba0`: `ask_restart()` builds a platform-correct sentence;
  Android gets "close, then reopen," desktop keeps "Restart."

Verification status: the platform branch is a straightforward wording change keyed off
platform detection. The sources do not record a device screenshot confirming the Android
wording, but the behavior it describes (Kodi only quits on Android) is the same documented
Kodi constraint the Setup add-on already handles.

## Action items

- [x] `ask_restart()` made platform-aware; Android says close-and-reopen, desktop says
      Restart (commit `413dba0`).
- [ ] Spot-check the wording on a Fire TV after a restore so the prompt matches what the
      box actually does. Fire TV = adb (`_tools/firetv.sh`).

## The rule that would have prevented this

**A prompt must describe what will actually happen on THIS platform.** When the same
action has different outcomes per platform (self-restart vs quit-and-reopen), the wording
has to branch too; a prompt that promises something the platform cannot do is a defect
even when the underlying action is safe.

Series context (related EZM incidents):
`docs/incident-2026-07-08-ezmpp-repeated-hardware-burns.md`.
