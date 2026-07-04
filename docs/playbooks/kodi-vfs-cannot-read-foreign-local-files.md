# Playbook - Kodi's VFS can silently fail to read a local file it didn't create

> **The bug:** on some Kodi ports (confirmed: tvOS/Apple TV), `xbmcvfs.File(path,
"r").readBytes()` - AND the native `xbmcvfs.copy()`, which goes through the
> exact same internal read path - can return **completely empty** for a local
> file that a **different process wrote via plain OS-level I/O** (Python's own
> `open()`/`zipfile`, not `xbmcvfs`), even seconds after that file was fully and
> correctly written and closed. `xbmcvfs.Stat()` on the same path reports the
> **correct size** the whole time - only the read is broken, and it never
> raises; it just yields nothing, chunk after chunk, forever.
>
> Read this before trusting `xbmcvfs` to read back ANY file this add-on built
> with plain Python I/O, especially on tvOS/iOS Kodi ports.

---

## How this was found (script.ezmaintenanceplusplus, 2026-07-04)

A 142 MB backup-to-NFS copy failed on a real Apple TV with "size mismatch (0 !=
total)" on every attempt. The chunked copy loop read the source (a zip built
moments earlier in `special://temp` via plain `zipfile`/`open()`, per
`CreateZip()` in `wiz.py`) with `xbmcvfs.File(src, "r").readBytes()`. The
device log showed `copied=0 total=142444751 actual=0` on all 3 retries, each
completing in ~1.6s - far too fast to be a genuine failed 142 MB transfer, and
`xbmcvfs.Stat(src)` had already reported the correct 142444751-byte size before
the read was even attempted.

The first fix shipped fell back to the native, opaque `xbmcvfs.copy(src, dst)`
on a chunked-read failure - the mechanism this add-on used **before** a
progress-bar rewrite replaced it with the chunked loop. A second live retest
showed the **exact same failure** from the native copy: `copied=0 total=142438765
actual=0`. That's what proved this isn't about _which_ `xbmcvfs` entry point is
used - both go through the same underlying VFS read, and it's broken for this
class of file on this device, full stop.

The actual fix: read a **local** source path (no `"://"`) with plain Python
`open()`/`.read()`, bypassing `xbmcvfs` entirely for that direction. This
add-on's own `CreateZip()` already writes that exact file with plain Python
I/O, and `wiz.py`'s own staged-zip validation (`os.path.getsize()` +
`zipfile.is_zipfile()`) already reads it back the same way elsewhere in this
same add-on - so plain Python I/O was already proven to work for this class of
path on this device; only Kodi's own VFS read of it was broken. A **remote**
source (`nfs://`, `smb://`) still has to go through `xbmcvfs` - plain Python
can't open a VFS URL - and there's no evidence that direction has the same bug.

Code: `_open_reader()` / `_LocalReader` / `_stream_copy()` in
`addons/script.ezmaintenanceplusplus/resources/lib/modules/ui.py`. Tests:
`_tools/test_ezmaintenanceplusplus_ui.py` -
`test_copy_once_reads_a_local_source_without_going_through_vfs` proves it by
deliberately poisoning what the fake `xbmcvfs.File` would return for the exact
source path and confirming the real fix never calls it.

## The suspected mechanism (unconfirmed, doesn't need to be to apply the fix)

Most likely a tvOS/iOS App Sandbox quirk: a file created via Kodi's own VFS/
`CFile` write path is "known" to whatever security-scoped-resource bookkeeping
the OS sandbox requires; a file created by a **different** write path (plain
Python, bypassing Kodi's C++ VFS layer entirely) may not be, so Kodi's own read
of it silently comes up empty even though basic filesystem metadata (`stat()`,
which is what `xbmcvfs.Stat()` ultimately calls) is still visible to any
process with ordinary sandbox access. This did **not** reproduce on macOS
(two local Kodi tests, 63MB and ~141MB, both succeeded cleanly) - consistent
with a sandbox-specific restriction, not a generic Kodi VFS bug.

Do not spend time confirming this mechanism before applying the fix pattern
below - the empirical fact (proven on two separate real-device attempts) is
sufficient justification on its own.

## The fix pattern - read local files locally

```python
def _open_reader(path):
    if "://" in path:
        return xbmcvfs.File(path, "r")   # remote/VFS-only path - no alternative
    return _LocalReader(path)             # local path - bypass xbmcvfs entirely


class _LocalReader:
    """Adapts plain Python file I/O to the xbmcvfs.File readBytes/close shape."""

    def __init__(self, path):
        self._f = open(path, "rb")

    def readBytes(self, n):
        return self._f.read(n)

    def close(self):
        self._f.close()
```

- Route every **read** of a path through this, never `xbmcvfs.File(path, "r")`
  directly, for any code that might be handed a local, plain-Python-written
  file.
- The **write** side is unaffected - `xbmcvfs.File(dst, "w")` is fine and is
  the only way to reach a remote destination anyway. There's no evidence the
  write direction has this bug.
- `xbmcvfs.Stat()` is unaffected too - it has correctly reported the real size
  in every observed log. Don't "fix" the size check; the read is the only
  broken part.
- A fallback/retry path must ALSO use `_open_reader` for its own read, not the
  opaque `xbmcvfs.copy()` - that call goes through the identical broken
  internal read for a local source and will fail exactly the same way (this is
  the mistake the first fix attempt made, and why it needed a second pass).

## Decision guide

1. **Did THIS add-on write the file being read, using plain Python I/O
   (`open()`, `zipfile`, etc.), not `xbmcvfs`?** If yes, and the read also goes
   through `xbmcvfs`, that's the shape of this bug - even if it hasn't failed
   for you yet, it's the same risk on tvOS/iOS.
2. **Does `xbmcvfs.Stat()` report a value that never matches what
   `xbmcvfs.File(...).readBytes()` (or `xbmcvfs.copy()`) can produce?** That
   split (correct stat, broken read) is the signature of this bug specifically
   - a genuinely short/corrupt file would usually show a _wrong_ stat too.
3. **Is the source path local (no `"://"`) or remote?** Only local paths can
   use the plain-Python bypass; a remote source has no alternative to
   `xbmcvfs` and this fix doesn't help it (see the residual gap below).

## Known residual gap (flagged by adversarial review, not yet observed)

`script.ezmaintenanceplusplus`'s **restore** direction stages a **remote**
(`nfs://`/`smb://`) backup zip down to a local temp path - the source there is
remote, so it still goes through `xbmcvfs.File`, unfixed by this pattern. If
the same class of bug ever affects a remote read (unobserved so far), restore
would fail - but safely: `wiz.py`'s restore path catches the resulting
`VfsCopyError` and falls through to its own `os.path.getsize() == 0` /
`zipfile.is_zipfile()` check, reporting "not a valid zip" with no wipe and no
corruption. Worth a real-device restore-from-NFS test at some point; not
blocking.

> **Related but different:** this is not the `Skin.SetBool`/instance-settings
> clobber class in `kodi-settings-clobber.md` - that's a live component's
> in-memory state overwriting a file Kodi itself owns. This is Kodi's own VFS
> failing to read a file a **different, non-VFS writer** produced. Same
> family trait (a Kodi subsystem quietly not doing what it looks like it did),
> different mechanism.
