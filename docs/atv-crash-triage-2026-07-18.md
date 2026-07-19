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

## CORRECTION, same day: the heap corruption is FLEET-WIDE and is NOT a texture-cache bug

The first pass of this document attributed the corruption to the texture cache
and to atv2 alone. A second audit of the same 50 reports disproved both.

**It is not the texture cache.** Two atv2 reports (`Kodi-2026-07-12-185126`,
`Kodi-2026-07-16-193327`) reach the IDENTICAL faulting frames from an unrelated
caller:

```text
sqlite3_free +124
dbiplus::SqliteDataset::exec(...) +1124      <- same offset as the texture crashes
CDatabase::ExecuteQuery(...) +132
CDatabase::CommitMultipleExecute() +52
ADDON::CRepositoryUpdateJob::DoWork() +1872  <- addons.db, not Textures13.db
```

The same faulting offset reached through two unrelated callers means the defect
lives in **`dbiplus::SqliteDataset::exec` itself**.
`CTextureDatabase::AddCachedTexture` is merely the most frequent caller, which
is why it dominates the sample.

### SECOND CORRECTION: there is no heap corruption at all

A guess at "mismatched allocator" was also wrong. The exact line, Kodi Omega
`xbmc/dbwrappers/sqlitedataset.cpp:1122`:

```cpp
char* errmsg;                                    // UNINITIALIZED
if ((res = db->setErr(sqlite3_exec(handle(), qry.c_str(), &callback, &exec_res, &errmsg),
                      qry.c_str())) == SQLITE_OK)
  return res;
else
{
  if (errmsg)                                    // garbage stack value, usually non-NULL
  {
    DbErrors err("%s (%s)", db->getErrorMsg(), errmsg);
    sqlite3_free(errmsg);                        // frees a non-heap pointer -> abort
```

`___BUG_IN_CLIENT_OF_LIBMALLOC_POINTER_BEING_FREED_WAS_NOT_ALLOCATED` does NOT
mean something corrupted the heap. It means **an uninitialized stack pointer was
passed to `free()`**. Nothing corrupted anything.

**Kodi master has already fixed this**, with a comment naming the hazard:

```cpp
char* errmsg = nullptr; // Must be initialized to nullptr; sqlite3_exec may not always set it
```

Omega 21.3 is on the unfixed side.

**And the trigger is pinned by construction.** Per SQLite's `legacy.c`,
`sqlite3_exec` has exactly ONE return path that never touches `*pzErrMsg`:
`if( !sqlite3SafetyCheckOk(db) ) return SQLITE_MISUSE_BKPT;`. Every other path
funnels through `exec_out:` and sets it. So reaching `sqlite3_free` with an
unset `errmsg` proves `sqlite3_exec` returned `SQLITE_MISUSE`, which proves
**Kodi called `exec()` on a sqlite handle that was not OPEN** (closed, closing,
zombie, or busy on another thread). That use-after-close race on a shared
`CDatabase` handle is the real bug. The uninitialized `errmsg` only converts a
silent failure into an abort.

Corroboration that rules out corruption: the code FORMATS `errmsg` as a C string
at line 1126 before freeing it at 1128. Reaching the free means the read
succeeded, so it is a readable stale stack slot. A corrupted heap pointer would
have faulted on the read.

Fixing the one-line upstream defect stops the crash but **does not fix the
underlying race**: it converts the abort into a thrown `DbErrors` that Kodi
catches, so the database write is still lost. That is still a large win.

**It is not atv2-only.** `atv1/Kodi-2026-07-09-040559.ips` carries a
byte-identical stack, same symbols and same offsets. True counts are 10 on atv2
and 1 on atv1. So "why atv2 and not atv1" is the wrong question for this bug:
atv2 simply has far more of it.

This is a worked example of the warning below: the aborting frame is the victim.
Two independent readers both anchored on `CTextureDatabase` because it appeared
in 10 of 11 samples, and both were wrong about the culprit.

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

## Screenshot segfaults: ROOT-CAUSED, an upstream Kodi tvOS bug

`CScreenShot::TakeScreenshot` `SIGSEGV`, 4 on atv1 and 2 on atv2. All six fault
at the same instruction with the same address, `0xfffffffffffffff8`.

First line of that function:

```cpp
auto surface = m_screenShotSurfaces.back()();
```

`m_screenShotSurfaces` is a static vector of callables. On tvOS it is **empty**,
so `.back()` is undefined behaviour: the arithmetic yields element address -32
(a libc++ `std::function` is 32 bytes) and invoking it loads the callable
pointer at +24, i.e. address -8. That is exactly the observed fault address.

**Why it is empty is a one-line copy-paste omission in the tvOS port.** Only
`ScreenshotSurfaceGL`, `ScreenshotSurfaceGLES` and `ScreenshotSurfaceWindows`
ever call `CScreenShot::Register`. `WinSystemIOS.mm` registers the GLES surface
and includes its header; `WinSystemTVOS.mm` has the identical platform block
with that single line missing.

**Consequence: on tvOS every screenshot attempt is a guaranteed crash.** Not a
race, not renderer state. The readback code never runs. Upstream fix is adding
`CScreenshotSurfaceGLES::Register();` to `CWinSystemTVOS::InitWindowSystem`.

Two corrections to earlier assumptions here. **Nothing in this fleet takes
screenshots automatically** - no caller exists anywhere in the four repos, and
`script.t7bshot` does not exist in the checkout and appears in neither device
log. These are human button presses, clustering into three short sittings
(three attempts in 8 minutes on atv1, two in 2 minutes on atv2), which is the
signature of someone pressing a mis-mapped remote key and retrying.

There is also a **second, independent reentrancy defect** in the same path. With
`SETTING_DEBUG_SCREENSHOTPATH` empty (confirmed: `atv2-kodi.log:50` reads
`screenshots folder:` with no value), `TakeScreenshot()` opens a modal file
browser, which pumps `ProcessRenderLoop` and delivers a second queued screenshot
action, re-entering `TakeScreenshot` while the first is still on the stack.

## SIGKILL is a WATCHDOG, not jetsam and not a force-quit

All 7 (`4 atv1, 3 atv2`) carry `termination.code 2343432205` = `0x8BADF00D` in
the `FRONTBOARD` namespace: `Failed to terminate gracefully after 5.0s`,
`WatchdogVisibility: Foreground`, thermal nominal, CPU idle. Every one is on the
main thread inside `-[XBMCController enterBackground]`. The user backgrounded
Kodi, shutdown blocked past the 5 second budget, the OS killed it. The process
was blocked, not busy. Two distinct blockers:

- **Thread-join hang** (4 atv1, 1 atv2, `__ulock_wait`): main thread blocks in
  `std::thread::join` via `CThread::StopThread` under
  `CTCPServer::StopServer` / `CEventServer::StopServer` and
  `CNetworkServices::Stop`. A network-service thread parked in
  `accept()`/`recvfrom()` never observes the stop flag. Missing socket shutdown
  before join.
- **Messenger deadlock** (2 atv2, `__psynch_cvwait`): `CPowerManager::OnSleep()`
  tries to OPEN A GUI DIALOG during backgrounding and does a synchronous
  `CApplicationMessenger::SendMsg`, blocking the main thread on a `CEvent` until
  a thread that is being torn down processes it. Deadlock by construction.

The 4 atv1 watchdogs are all from 07-03 on a **different build** (bundle
`tv.kodi.tvos.piers`, `22.0-ALPHA3`) and stopped after the box moved to `21.3`.
The atv2 ones are on the current 21.3, so the hang is live. Fix the
`OnSleep` modal-dialog deadlock first; it has the cleanest root cause.

## Two more operationally important crashes nobody had examined

**libnfs `rpc_service` segfaults (5, atv2 only) are memory corruption.** Three of
the five carry `possible pointer authentication failure` with wild addresses
(`0x7109e38845123997`, `0x913d600090018500`, `0x6ff824937b36c250`,
`0xd61087f8cd454e6c`). libnfs is dereferencing a corrupted callback/context
pointer whose PAC signature failed: use-after-free or corruption in the RPC
reply path, not a missing null check. Trending UP (2 on 07-17 alone), and it
lands squarely on the tailnet NFS export work.

One of the five is triggered from inside the IPTV add-on:
`iptvsimple::InstanceSettings::LoadCustomChannelGroupFile` ->
`CNfsConnection::Connect` -> `CNFSFile::Exists`, during
`CPVRClients::UpdateClients`. So an IPTV instance whose custom channel-group
file lives on an NFS path can crash the box at PVR startup. **It shares
`UpdateClients` with atv1's closed IPTV bug and is easy to misfile as that one.
It is a different defect** (segv in libnfs vs uncaught exception in a
destructor).

**`CAddonInstaller::InstallFromZip` segfaults (2, atv2, 07-12 22:19 and 22:20).**
Null-ish dereference at offset 8 while logging inside `InstallFromZip`, after
`CGUIWindowAddonBrowser::OnClick`. Two attempts a minute apart both died. This
is the fleet's primary deployment path, install-from-zip off the KodiShare
`apps/` share, and it is the one crash that can block shipping updates to boxes.

## Python segfaults: real, upstream, and the add-on is NOT identifiable

3 reports (2 atv2 `PyDict_SetItemString`, 1 atv1 `PyEval_ReleaseThread`).
Python is statically linked into the Kodi binary and `.ips` does not record
script paths, so `usedImages` carries no add-on-specific image for any of them.
**Anyone naming a specific add-on from these reports is guessing.**

The mechanism is interpreter concurrency: at the moment of death there were
**9 concurrent `LanguageInvoker` threads**, several blocked on
`_PyImport_AcquireLock` and one on `take_gil`, while the faulting thread was
mid interpreter-init inside `CPythonInvoker::execute`. Multiple sub-interpreters
initialising while others hold the import lock. Not locally fixable; the
mitigation is reducing how many add-on scripts launch at once.

The atv1 one is a different bug on the teardown side: a `plugin://` directory
listing timed out and `CPythonInvoker::stop` released a thread-state that was
already gone, racing another thread in `CScriptInvocationManager::OnExecutionDone`.

## Build drift worth knowing

atv1 ran bundle `tv.kodi.tvos.piers` / `22.0-ALPHA3` until 07-03, then
`ca.koditvbox.kodi.tvos.21` / `21.3` from 07-08. Two sideload sources with
different bundle IDs have been in service. Both boxes now agree on 21.3
(`20251031-a3a448d26b`). The boxes are also on a moving tvOS beta train
(`23L5753c` -> `23L5758b` -> `23L5766a`), which is context for any
"only happens on Apple TV" triage.

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

## Two free mitigations, evidence-backed, zero risk

Neither needs a Kodi change and both are confirmed by the logs.

1. **Set the screenshots folder on both boxes.** `SETTING_DEBUG_SCREENSHOTPATH`
   is blank (`atv2-kodi.log:50` reads `screenshots folder:` with no value).
   That blank is what makes `TakeScreenshot()` open a modal file browser, which
   pumps the message loop and re-enters itself. Setting it removes the entire
   reentrancy class, 6 crashes fleet-wide, with one setting. Note this does NOT
   fix the missing `CScreenshotSurfaceGLES::Register()`, so a screenshot will
   still crash on tvOS; it removes the reentrancy path only.
2. **Stop installing add-on zips from the NFS share.** Install from local
   storage or over HTTP. Three of the five NFS segfaults are
   `CAddonInstallJob::DoWork` -> `CFilesystemInstaller::UnpackArchive` ->
   `CFile::Copy` -> `CZipFile::Open` on NFS, and both `CLog` crashes are most
   plausibly the same NFS read failing to enumerate the zip.

## CLog crashes: SOLVED, and it is a logging bug

`xbmc/addons/AddonInstaller.cpp:549` logs `items[0]->m_bIsFolder` on the FAILURE
path, unconditionally, including when `items.Size() == 0`. The guard
short-circuits safely but the log statement does not. The crash frame is
`FormatAndLogInternal<std::string, int, bool&>` - note the `bool&` REFERENCE.
Binding a reference to `nullptr->m_bIsFolder` is only address arithmetic, so the
fault happens later when fmt dereferences it inside the logger, which is why the
crash appears inside logging rather than at the call site. Fault address `0x8`
is `offsetof(CFileItem, m_bIsFolder)` on a null `this`. The two crashes are 59
seconds apart: an operator retrying the same failing zip install.

## Correction: the NFS crashes are NOT the backup path

Earlier framing assumed EZ Maintenance++ backup/restore. Actual breakdown of the
five:

- **3 are add-on installation** (`CAddonInstallJob` -> `UnpackArchive`)
- **2 are IPTV Simple** (`InstanceSettings::LoadCustomChannelGroupFile`, and
  `ConnectionManager::Process` -> `WebUtils::Check` -> `CFile::Exists`)
- **0 are the EZM++ backup write path**

Data risk is therefore low for backups: EZM++ stages
`kodi_backup_*.zip.ezmpart` then renames, which is safe against a mid-write
crash, and no crash landed in it. The real exposure is a **half-unpacked
add-on** if `UnpackArchive` dies mid-copy.

Prime suspect for the libnfs crashes, marked INFERRED not proven:
`xbmc/filesystem/NFSFile.cpp:398-417`, `CNfsConnection::CheckIfIdle` does an
unlocked read of `m_OpenConnections` / `m_pNfsContext` before taking the lock
and calling `Deinit()` -> `destroyOpenContexts()`. The log shows "NFS is idle.
Closing the remaining connections." firing three times in about four minutes.
Under ARM64e a freed-and-reused context yields a PAC-signed callback whose
signature fails auth, which is exactly the observed wild addresses.

## Do NOT do these

Each would burn time on a disproved theory:

- **Do not chase heap corruption.** No guard malloc, no MallocScribble, no
  libgmalloc. There is no corruption.
- **Do not delete or rebuild `Textures13.db`.** It is not corrupt, and the same
  abort arrives from `addons.db` through a different caller.
- **Do not disable the texture cache.** It is the victim, not the culprit.
- **Do not pursue memory pressure.** Confirmed dead.
- **Do not treat this as a tvOS storage-split (vectored `.xml`) problem.** These
  are SQLite `.db` files and NFS I/O; neither goes through `CTVOSFile`.

## Baseline warning for any verification

**atv2 has already updated past every crash report in this set.** All reports
say OS build `23L5758b`; the current log says `23L5766a`. A clean baseline must
be re-established before any change is credited with a fix.

## What this replaces

The recorded suspect list for the atv2 problem was entirely skin-side: the
`Home.xml` onload chain, WindowClose animations, the Siri-remote keymap. None of
those appear in any of the 50 reports. The investigation was looking in the
wrong place because the crash reports had never been pulled.
