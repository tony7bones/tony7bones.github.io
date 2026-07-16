# Incident - EZ Maintenance++ Dropbox sign-in barcode blank on Apple TV (2026-07-13)

**Fixed in `script.ezmaintenanceplusplus` 2026.07.13.6.** The Dropbox sign-in QR code
rendered blank (the "Scan with your phone..." text showed, no barcode) on the fleet's
Kodi 21.3 boxes. Three independent bugs were stacked on top of each other; the last one
is the real root cause and is the tvOS/ControlImage face of the already-documented
`kodi-vfs-cannot-read-foreign-local-files.md` playbook.

## Symptom

`Settings -> Backup/Restore -> Sign in to Dropbox` opened the QR window
(`dropbox_remote._QRWindow`, `xbmcgui.WindowDialog`, window id 13000) but the QR image
control was blank - on Fire TV it showed Kodi's broken-image placeholder, on Apple TV
nothing. The sign-in flow itself was fine; only the image would not paint. It had worked
before, on both device types.

## The three stacked bugs (in order of discovery)

1. **8-bit grayscale PNG - Kodi 21.3 refuses to draw it.** `_qrgen._matrix_to_png` emitted
   a grayscale (PNG color type 0) image. Newer Kodi's texture loader will not render
   grayscale; it draws nothing. Fix: emit **32-bit RGBA** (color type 6).
2. **Constant filename + Kodi's per-path texture cache.** The QR was always written to
   `_dbx_qr.png`. Kodi caches textures by path, so the first failed load (the grayscale
   one) was cached as a blank and kept being served for that name even after the file was
   rewritten with a valid 32-bit image - it only cleared on a Kodi restart. Fix: a
   **fresh filename every sign-in** (`_dbx_qr_<epoch>_<seq>.png`) so Kodi always loads
   fresh, no restart needed.
3. **THE root cause - plain `open()` write is unreadable by tvOS's texture loader.**
   `_qr_image` wrote the PNG with plain Python `open()`. On **Apple TV (tvOS)** Kodi's VFS
   - which the texture loader uses to READ - silently reads **empty** for a local file
     written by a _different_ (non-VFS) writer. It's an App Sandbox scoped-resource quirk,
     already documented for the read/copy direction in
     `docs/playbooks/kodi-vfs-cannot-read-foreign-local-files.md`. So on tvOS the valid file
     sat on disk (correct size via `stat`) but ControlImage got nothing. **Fire TV
     (Android) has no such restriction**, which is exactly why the same code worked there
     and not on the ATV. Fix: **write the PNG THROUGH `xbmcvfs.File(path,"w")`** so Kodi
     "knows" the file and its texture loader can read it back.

## Wrong turns (recorded so they are not repeated)

- **"tvOS xbmcvfs/real-path split" as a reflex.** It was reached for first because it is a
  familiar fleet gotcha; the owner correctly rejected it (the QR had worked on tvOS with
  the same code, and the write-vs-read split is a different mechanism).
- **"Wrong special:// folder."** Plausible and owner-suggested, but it is NOT the folder:
  `/storage/emulated/0/...` on Fire TV vs the tvOS container path both resolve fine via
  `translatePath`. The write PATH (plain `open()` vs `xbmcvfs`) is what matters, not the
  folder. Confirmed by the playbook once the right doc was read.
- **Grayscale alone.** Real, but shipping 32-bit (`.4`) still showed blank until a restart
  (bug #2) and still blank on tvOS after a reboot (bug #3) - proving more than one thing
  was wrong.

## How it was proven

- **Fire TV (adb, screenshottable):** triggered `action=authorize` over JSON-RPC, pulled
  the on-device PNG with `adb pull` (valid 32-bit RGBA, correct size), and
  `adb exec-out screencap -p` showed the broken-image placeholder - a load failure of a
  valid file. After a Kodi restart (cache clear) the 32-bit barcode rendered:
  visual proof.
- **Apple TV (no adb/screenshot):** JSON-RPC confirmed the QR window opened (id 13000) and
  the running version; the owner confirmed by eye that `.6` (write-through-xbmcvfs)
  finally painted the barcode and completed the Dropbox login. tvOS verification rests on
  the owner's eyes + the documented mechanism; deeper pulls would use the
  `devicectl`/`pymobiledevice3` path in `atv-kodi-xcode-cli-troubleshooting.md`.

## Rollback used as a diagnostic

To separate "our code" from "the environment", the proxy was rolled back to the known-good
`2026.07.09.1` code (shipped as a bumped version so boxes would pick it up). It showed the
**same** blank barcode - proving the QR code was unchanged and the regression was
environmental (Kodi 21.3 stricter rendering + the tvOS VFS read quirk), not an app-logic
change. The latest code (box-setup + thin labels) was then re-landed with all three fixes
as `.6`.

## The fix (`_qr_image`, `resources/lib/modules/dropbox_remote.py`)

```python
png = _qrgen.make_qr_png_bytes(url)                 # 32-bit RGBA (bug #1)
special = "special://temp/_dbx_qr_%d_%d.png" % (int(time.time()), _qr_seq)  # fresh (bug #2)
f = xbmcvfs.File(special, "w")                      # THROUGH xbmcvfs (bug #3, tvOS)
try:
    f.write(bytearray(png))
finally:
    f.close()
return special                                      # hand ControlImage the special:// path
```

`special://temp` (not `userdata`) so there is no NSUserDefaults mirroring of a binary blob.

## Prevention

Any image an add-on GENERATES at runtime and shows via `xbmcgui.ControlImage` on this fleet
MUST be written through `xbmcvfs`, be a 32-bit PNG, and use a fresh filename per render.
See `docs/playbooks/kodi-vfs-cannot-read-foreign-local-files.md` (the read-side of the same
tvOS sandbox bug) and the memory `tvos-controlimage-write-through-xbmcvfs`.
