# Apple TV crash triage, 2026-07-18

First time the fleet's Apple TV crash reports have been pulled and read. 50
reports, 25 per box, plus the jetsam event reports. Everything below is from the
devices, not from reasoning.

Method and tooling: `.claude/skills/atv-log-pull/SKILL.md` section 5.

## Headline: the two Apple TVs have DIFFERENT diseases

They were being discussed as one problem ("the ATVs crash"). They are not.

| | atv1 | atv2 |
| --- | --- | --- |
| Reports | 25 | 25 |
| Span | 2026-07-03 to **07-14** | 2026-07-11 to **07-17** |
| Dominant | **14x uncaught C++ exception** | **10x heap corruption** |
| Status | **CLOSED**, historical | **LIVE, unresolved** |

Both dominant bugs surface as `SIGABRT` on a `JobWorker` thread with
`__pthread_kill` on top. **Classifying by signal or top frame merges two
unrelated bugs.** Always walk the stack down to the first Kodi frame.

## Memory pressure is RULED OUT, fleet-wide

This was the leading hypothesis for a day. It is wrong, and the devices say so.

- Neither box's jetsam reports name Kodi as a victim. atv2 has two jetsam events
  (07-10, 07-11) with **zero** Kodi mentions. atv1 has one (07-03) that lists
  Kodi only as a surviving bystander.
- That single listing is the most useful number in the whole investigation:
  Kodi on atv1 was `rpages` 14,293 (**~56 MB resident**) with `lifetimeMax`
  17,574 (**~69 MB peak, ever**), `states: [active, frontmost]`, while
  `largestProcess` was `backboardd`.

**Kodi's all-time peak footprint on an Apple TV is about 69 MB.** Any tuning
argument premised on Kodi approaching a tvOS memory ceiling is unfounded. Note
`filecache.memorysize` is set to 200 on these boxes, so that buffer has clearly
never been allocated in anger.

A jetsam report lists EVERY live process, so the app appearing in one proves
nothing by itself. Read `states` and whether it was actually jettisoned.

## atv1: the 2026-07-08 IPTV brick, now with a mechanism

14 of atv1's 25 are identical, faulting thread `JobWorker`:

```text
abort / __abort_message / demangling_terminate_handler() / std::__terminate / std::terminate
IptvSimple::~IptvSimple()
kodi::addon::CAddonBase::ADDONBASE_DestroyInstance(...)
ADDON::CAddonDll::DestroyInstance(...)
ADDON::IAddonInstanceHandler::DestroyInstance()
PVR::CPVRClient::Destroy()
PVR::CPVRClient::~CPVRClient()
PVR::CPVRClients::UpdateClients(...)
PVR::CPVRClients::Start()
CLambdaJob<PVR::CPVRManager::Init()::$_0>::DoWork()
```

`pvr.iptvsimple`'s destructor throws while the PVR manager is starting and
reconciling its client set. A destructor is `noexcept` by default, so the
exception cannot be caught: it goes straight to `std::terminate` and aborts.

**This is the documented duplicate-instance incident, caught in the act.**
`docs/incident-2026-07-08-ezmpp-iptv-brick.md` says a restore left duplicate
`pvr.iptvsimple` `instance-settings-*.xml` files so the client "loaded the same
IPTV config more than once, which could crash the box". These reports upgrade
"could crash" to a proven mechanism: duplicate instances make `UpdateClients`
tear a client down, and that teardown aborts the process.

Timestamps confirm it. 13 of 14 on **2026-07-08**, in crash-loop bursts (13:15
x2, 13:30, 14:49, 15:12 x2, 15:14, 17:06 x3, 17:41 x2, 18:23), plus one on
**2026-07-14**. Those are exactly the two dates the project records as having
destroyed real user data. **Nothing since 07-14**, consistent with the sweep in
`2026.07.08.4` and the removal of boot automation in `2026.07.08.5`.

atv2 has only **1** of these, so it never suffered atv1's problem.

**Action:** that incident doc is still marked OPEN. Its mechanism is now proven
on-device and its crashes stopped four days after the fix. It can be closed, and
the stack above should be pasted into it.

## atv2: heap corruption, LIVE and unexplained

10 of atv2's 25, faulting thread `JobWorker`:

```text
abort / malloc_vreport / malloc_report
___BUG_IN_CLIENT_OF_LIBMALLOC_POINTER_BEING_FREED_WAS_NOT_ALLOCATED
_xzm_free_not_found
sqlite3_free
dbiplus::SqliteDataset::exec(...)
CTextureDatabase::AddCachedTexture(...)
CTextureCache::OnCachingComplete(bool, CTextureCacheJob*)
CTextureCache::OnJobComplete(unsigned int, bool, CJob*)
CJobManager::OnJobComplete(bool, CJob*)
CJobWorker::Process()
```

libmalloc aborts because a pointer was freed that it never allocated, while the
texture cache writes to `Textures13.db`. Running through **07-17**, the period
the owner reported the box being "temperamental".

Two cautions for whoever picks this up:

- **The aborting frame is the victim, not necessarily the culprit.** Heap
  corruption is detected wherever the next allocator call happens to land.
- This contradicts a line in the log-pull skill that says a `SQLITE_MISUSE`
  storm on `Textures13.db` is "FALLOUT, not the cause". Here SQLite on that
  database is the aborting frame. Treat that guidance as case-specific.

atv2 also carries crashes atv1 does not: 5x `SIGSEGV` in libnfs
(`rpc_service` / `wait_for_nfs_reply` / `nfs_stat64`) under
`CZipFile::Open` -> `CFile::Copy` -> `CFileOperationJob`, i.e. **copying a
backup zip off the NFS share**, plus 2x in `CLog::FormatAndLogInternal` and 2x
in `PyDict_SetItemString`. Those may be independent bugs or collateral from the
corrupted heap; that is under expert review and is NOT yet decided.

## Fleet-wide and unexplained: screenshot segfaults

`CScreenShot::TakeScreenshot` `SIGSEGV`, **4 on atv1 and 2 on atv2**. The only
non-trivial signature present on both boxes, so it is independent of each box's
dominant bug. Nobody has investigated it. Note `script.t7bshot` is installed on
the fleet.

## Crash inventory

| Signature | atv1 | atv2 |
| --- | --- | --- |
| `SIGABRT` uncaught exception, `IptvSimple::~IptvSimple` | **14** | 1 |
| `SIGABRT` heap corruption, texture-cache SQLite | 1 | **10** |
| `SIGSEGV` `CScreenShot::TakeScreenshot` | 4 | 2 |
| `SIGSEGV` libnfs `rpc_service` (zip over NFS) | 0 | 5 |
| `SIGSEGV` `CLog::FormatAndLogInternal` | 0 | 2 |
| `SIGSEGV` Python (`PyDict_SetItemString` / `PyEval_ReleaseThread`) | 1 | 2 |
| `SIGKILL` (`__ulock_wait` / `__psynch_cvwait`) | 4 | 3 |
| `SIGSEGV` `CGUIComponent::GetWindowManager` | 1 | 0 |

## What this replaces

The recorded suspect list for the atv2 problem was entirely skin-side: the
`Home.xml` onload chain, WindowClose animations, the Siri-remote keymap. None of
those appear in any of the 50 reports. The investigation was looking in the
wrong place because the crash reports had never been pulled.
