# Playbook - Mac mini media/share server (`Mini`)

The Mac mini `Mini` is the LAN host that serves the Kodi boxes and the owner's
Macs. It serves the same folders two ways at once: NFS for the Kodi appliances,
SMB for the Macs. This playbook records the final working setup and the macOS
quirks learned the hard way, so nobody relives the multi-hour thrash it took to
land here.

---

## Device facts (confirmed 2026-07-07, re-verified 2026-08-16)

| Field         | Value                                                          |
| ------------- | -------------------------------------------------------------- |
| Computer Name | **Mini**                                                       |
| Bonjour       | **Mini.local** (`LocalHostName` = `Mini`)                      |
| LAN IP        | **192.168.7.2** (gateway 192.168.7.1, `en0`)                   |
| Tailnet       | node **mini**, offers exit node (`tailscale status` for IP)    |
| Model / OS    | Mac16,10 (M4-class), macOS 26.5.2                              |
| Shell access  | `ssh mini` (key-based, no password)                            |
| Admin access  | passwordless `sudo` for `moquette` (`/etc/sudoers.d/moquette`) |
| FileVault     | **Off** (so it boots + mounts + serves with no login)          |

> `192.168.7.2` is a **confirmed DHCP reservation** on the Eero (MAC
> `d0:11:e5:7a:05:ec` -> `192.168.7.2`), verified by forcing a lease renewal. Kodi
> stores paths literally (`nfs://192.168.7.2/...`) and its scraped library keys off
> that IP, so the pinned address is what keeps every box and Mac mount valid. Do
> not remove the reservation.

---

## The rule that ends the confusion: NFS for appliances, SMB for Macs

The mini serves the **same two roots** over **both** protocols at once. NFS
and SMB are two doors into the identical directories, not separate copies.

| Folder on `Mini`         | Over NFS (Kodi) | Over SMB (Macs) |
| ------------------------ | --------------- | --------------- |
| `/Users/moquette/Kodi`   | Kodi            | Kodi            |
| `/Users/moquette/Public` | Public          | Public          |
| `/Users/moquette` (home) | **never**       | moquette        |

`Share/` and `Backup/` are now **subdirectories of the one `Kodi` share**, not
separate shares. Consolidated 2026-08-16: mounting Kodi assets used to take two
connections, which was pure friction for no benefit.

- **Kodi boxes mount over NFS** (`nfs://192.168.7.2/Users/moquette/Kodi/Share`,
  `.../Kodi/Backup`, `.../Public`). Those deep paths still work unchanged after
  the consolidation, because the export carries `-alldirs`. No box needed
  reconfiguring, and none should be reconfigured now.
- **Macs mount over SMB** (`smb://Mini`, authenticate as `moquette`, save to
  Keychain). SMB is the ONLY protocol that shows a browsable share list in Finder.
  One mount of `Kodi` now yields both `Share/` and `Backup/`.
- The two protocols do not interfere: a Mac using SMB and a Kodi box using NFS hit
  the same files on the mini simultaneously.

### `~/Kodi` holds Kodi assets ONLY

This is a rule, not an observation. Until 2026-08-16 that directory also held
`iptv-repo/` (a working checkout of the private `moquette/iptv` repo) and
`backups/` (13 historical copies of `providers.yaml`). Both have been moved out,
to `~/Code/iptv` and `~/Library/Application Support/iptv/config-backups`.

Nothing that is not meant for every Kodi box may live under `~/Kodi` again. The
export is unauthenticated and read-write to the whole LAN, and `-mapall=moquette`
makes every client the owner, so a mode 0600 file in there is readable by anything
that gets a `192.168.7.x` lease. Worse, the IPTV daemon executes its Python
package from its checkout, so while that checkout sat under `~/Kodi` any LAN
device could have rewritten code that then ran as `moquette`. Keep code and
credentials out.

### NFS config (`/etc/exports`) - for Kodi

```
/Users/moquette/Kodi -alldirs -mapall=moquette -network 192.168.7.0 -mask 255.255.255.0
/Users/moquette/Kodi -alldirs -ro -mapall=moquette -network 100.64.0.0 -mask 255.192.0.0
/Users/moquette/Public -mapall=moquette -network 192.168.7.0 -mask 255.255.255.0
```

`-mapall=moquette` makes every client write land as `moquette:staff` regardless of
the client's uid, so writes just work. `nfs.server.require_resv_port = 0` and
`nfs.server.mount.require_resv_port = 0` in `/etc/nfs.conf` allow non-root clients.
Validate with `sudo nfsd checkexports`, apply with `sudo nfsd update`.

**`-alldirs` is what makes the consolidation invisible to the fleet.** It lets a
client mount at any point inside the exported tree, so the boxes keep mounting
`/Users/moquette/Kodi/Share` exactly as before while a Mac mounts the `Kodi` root.
Verified by mounting both paths after the change, not assumed.

**The second line is the tailnet export, and it is easy to lose.** A rebuild that
copies only the LAN line silently drops remote access while everything on the LAN
keeps working. `100.64.0.0/10` is the CGNAT range Tailscale allocates from, so that
one line covers every tailnet node without naming any of them. It is **`-ro`**:
remote nodes read, never write. The IPTV daemon is the only writer and it runs
locally on the mini.

**You cannot scope the tailnet more tightly than the LAN.** macOS refuses to
export a directory and its own subdirectory at the same time, even to different
networks:

```
exports:3: /Users/moquette/Kodi/Share conflicts with existing export /Users/moquette/Kodi
```

So exporting the `Kodi` root to the LAN forces the tailnet line to the same root.
That was a deliberate trade accepted on 2026-08-16: remote nodes gained read-only
visibility of `Backup/` in exchange for the single mount. Exporting the same path
on two lines with different networks and options is legal and is what makes it
work at all.

### SMB config - for Macs

- `smbd` runs at boot. Share points (`sharing -l`): `Kodi`, `Public`, `moquette`
  (home). Guest is OFF (see lessons); auth as `moquette`. The old `KodiShare` and
  `KodiBackup` share points were removed 2026-08-16; re-add with `sharing -a` only
  if you deliberately want the split back.
- Any Mac: Finder -> Connect to Server (Cmd K) -> `smb://Mini` -> log in as
  `moquette`, tick "Remember in my keychain". Shares appear as mountable volumes
  under a `Mini` entry in the sidebar. No per-machine config files needed.

---

## Always-on server config (the original bug + fix)

The mini shipped as a **desktop** (`pmset sleep 1` = sleep after 1 idle minute), so
shares vanished the moment nobody was logged in. Fixed 2026-07-07:

```
sudo pmset -a sleep 0 disksleep 0 autorestart 1 womp 1
```

`sleep 0` (never sleep) is THE fix; `disksleep 0` keeps disks spun up;
`autorestart 1` auto-reboots after power loss; `womp 1` is wake-on-LAN. With
FileVault off, the box boots and starts `nfsd` + `smbd` with no login.

### Regression check

```
ssh mini 'pmset -g custom | grep -E " sleep|disksleep|autorestart|womp"'  # sleep 0, disksleep 0, autorestart 1, womp 1
ssh mini 'nfsd status && showmount -e localhost'                          # NFS exports present
ssh mini 'grep -c 100.64.0.0 /etc/exports'                                # 1 = tailnet export intact
ssh mini 'sharing -l | grep name:'                                        # Kodi, Public, moquette
ssh mini 'ls ~/Kodi'                                                      # ONLY Share and Backup
ssh mini 'fdesetup status'                                                # FileVault Off
```

`showmount -e localhost` collapses the three export lines into two, one per path,
and `/Users/moquette/Kodi` must list BOTH networks:

```
/Users/moquette/Public              192.168.7.0
/Users/moquette/Kodi                100.64.0.0 192.168.7.0
```

If `Kodi` shows only `192.168.7.0`, the tailnet export was lost. If you see
`Kodi/Share` and `Kodi/Backup` as separate entries, someone reverted the
2026-08-16 consolidation.

---

## Management access (passwordless sudo)

`ssh mini` is key-based (that is SSH login, not sudo). Passwordless sudo was added
fail-safe (stage a dotted file so sudo ignores it, `visudo -cf` validate, then
rename to activate):

```
printf 'moquette ALL=(ALL) NOPASSWD: ALL\n' | sudo tee /etc/sudoers.d/moquette.stage >/dev/null \
  && sudo visudo -cf /etc/sudoers.d/moquette.stage \
  && sudo chown root:wheel /etc/sudoers.d/moquette.stage \
  && sudo chmod 0440 /etc/sudoers.d/moquette.stage \
  && sudo mv /etc/sudoers.d/moquette.stage /etc/sudoers.d/moquette
```

Verify: `sudo -n -l` (no prompt) and `sudo visudo -c` (parses OK). The mini's admin
password is not in the vault.

---

## macOS lessons learned the hard way (do NOT relearn these)

1. **NFS is for appliances, SMB is for Macs.** On a Mac, an NFS server shows up in
   Finder as a useless `Connected as: NFS` entry that **never lists any shares**
   (NFS does not advertise shares to Finder), and it leaves sticky ghost sessions
   you can only clear with Disconnect or a `killall Finder`. Do not mount NFS on a
   Mac for browsing. Kodi uses NFS because that is what Kodi speaks; Macs use SMB.
2. **SMB guest access is dead on macOS 26.** `AllowGuestAccess -bool true` + an
   enabled guest account are BOTH ignored; the giveaway in the log is
   `smbd_detect_sg_mode: NOT enabling super guest mode`. Guest mounts fail even
   on loopback. SMB requires auth as `moquette`. Reverted; do not retry.
3. **Never NFS-export the home directory.** An export line reading
   `/Users/moquette -mapall=moquette -network 192.168.7.0/24` would give any
   device that grabs a `192.168.7.x` address unauthenticated read/write to
   `~/.ssh`, `~/Library/Keychains`, and `~/Code/moquette/vault` (the plaintext
   credential vault). Home is SMB-only (authenticated); for full-home access
   from another machine use `sftp://mini` / `sshfs`.
4. **External volumes are painful to share; avoid unless needed.** NFS-exporting an
   external drive fails `checkexports` (`sandbox_check ... nfsd has no read access`)
   until `/sbin/nfsd` is granted **Full Disk Access** (GUI only). Serving one over
   SMB needs the same Full Disk Access grant for `smbd`. Both are GUI TCC grants no
   script can do. See the T7 note below.
5. **The Finder sidebar server label is the Bonjour `LocalHostName`,** not the
   Computer Name and not the string you connect with. To display `Mini` (capital):
   `sudo scutil --set LocalHostName "Mini"` then `killall Finder`. macOS accepts the
   capital here even though mDNS is usually lowercased.
6. **One server config change owner at a time.** Two actors editing `/etc/exports`
   and mount state concurrently (a human plus a background agent) race and undo each
   other. Pick one owner for mutations.

---

## The T7 (external 4 TB SSD) - REMOVED

The Samsung T7 was an empty 4 TB external SSD. It was unplugged and set aside on
2026-07-07, then **removed entirely by owner decision** (confirmed 2026-08-16).
It is out of `/etc/exports` and out of `sharing -l`, `/Volumes` holds only
`Macintosh HD`, and nothing on the mini references it. It was never load-bearing:
Kodi's content lives on the internal SSD and totals well under a gigabyte
(`Share` 19M, `Backup` 120M, `Public` 4K as of 2026-08-16).

Do not plan around it, and do not treat any older note describing a T7 SMB share
as current. If an external volume is ever added back, the macOS tax is unchanged:
for Kodi (NFS) it needs `/sbin/nfsd` Full Disk Access, and for Macs (SMB) it needs
`smbd` Full Disk Access (System Settings -> Privacy & Security -> Full Disk Access
-> enable the daemon). Both are GUI-only TCC grants no script can perform. Give
any irreplaceable data on it a second copy, since a single external SSD is a
single point of failure.

---

## Other services on the box

The full `/Library/LaunchDaemons` inventory as of 2026-08-16:

- `com.tony7bones.iptv.plist` - the IPTV service (created 2026-07-02, label
  renamed from `com.tony7bones.iptv2` on 2026-08-16). A
  LaunchDaemon, so it runs regardless of login, but `UserName` is `moquette`, not
  root. It fires 16 times a day at 7 minutes past the hour and writes into
  `~/Kodi/Share/iptv/`, the export every Kodi box reads. This is the only process
  that writes the share. Its moving parts, all relocated 2026-08-16:

  | Key | Value |
  | ------------------ | ------------------------------------------------- |
  | `WorkingDirectory` | `~/Code/iptv/mini` |
  | `--config` | `~/Code/iptv/mini/iptv/providers.yaml` |
  | stdout / stderr | `~/Library/Logs/iptv/populate.{log,err.log}` |

  `python3 -m iptv` resolves the package out of `WorkingDirectory`, so that path
  IS the running code. The tracked template at
  `mini/iptv/deploy/com.tony7bones.iptv.plist` in the `moquette/iptv` repo must
  be kept in step with the live plist, or the next redeploy reinstates dead paths.
- `homebrew.mxcl.tailscale.plist` - the Tailscale daemon that puts the mini on
  the tailnet. The read-only tailnet export above is worthless without it.
- `com.adguard.mac.adguard.helper.plist` and `us.zoom.ZoomDaemon.plist` - vendor
  helpers, unrelated to serving.

### Retired (do not describe as live)

The mini-infra services that once ran here are **deleted**: `com.mini.shared` (a
Filebrowser 2.63.14 instance serving a household folder at `mini.local:8080`) and
`com.mini.wifi-keepalive`. Removed by owner decision; verified gone 2026-08-16
with no `com.mini.*` job in either launchd domain, nothing listening on port 8080,
no filebrowser binary, and no `~/mini`, `~/mini-data`, `~/mini-services` or
`~/opt` on disk. Do not re-provision them. Household file sharing on this box now
happens only through the SMB and NFS share points above.

---

## Kodi clients that depend on this box (5 boxes)

Bedroom Fire TV (`192.168.7.84`), Office Fire TV, Shield, and two Travelsticks.
They mount the server paths `/Users/moquette/Kodi/Share`,
`/Users/moquette/Kodi/Backup` and `/Users/moquette/Public` over NFS from
`192.168.7.2` for addon, IPTV and RSS content. Kodi stores those paths literally,
so they are a contract: the 2026-08-16 share consolidation deliberately left every
one of them working rather than asking five boxes to be reconfigured.
