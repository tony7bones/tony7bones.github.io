# Playbook - Mac mini media/share server (`Mini`)

The Mac mini `Mini` is the LAN host that serves the Kodi boxes and the owner's
Macs. It serves the same folders two ways at once: NFS for the Kodi appliances,
SMB for the Macs. This playbook records the final working setup and the macOS
quirks learned the hard way, so nobody relives the multi-hour thrash it took to
land here.

---

## Device facts (confirmed 2026-07-07)

| Field         | Value                                                          |
| ------------- | -------------------------------------------------------------- |
| Computer Name | **Mini**                                                       |
| Bonjour       | **Mini.local** (`LocalHostName` = `Mini`)                      |
| LAN IP        | **192.168.7.2** (gateway 192.168.7.1, `en0`)                   |
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

The mini serves the **same three folders** over **both** protocols at once. NFS
and SMB are two doors into the identical directories, not separate copies.

| Folder on `Mini`              | Over NFS (Kodi) | Over SMB (Macs) |
| ----------------------------- | --------------- | --------------- |
| `/Users/moquette/Kodi/Share`  | KodiShare       | KodiShare       |
| `/Users/moquette/Kodi/Backup` | KodiBackup      | KodiBackup      |
| `/Users/moquette/Public`      | Public          | Public          |
| `/Users/moquette` (home)      | **never**       | moquette        |

- **Kodi boxes mount over NFS** (`nfs://192.168.7.2/Users/moquette/Kodi/Share`,
  `.../Kodi/Backup`, `.../Public`). This is how Kodi has always read them; it is
  unaffected by anything the Macs do.
- **Macs mount over SMB** (`smb://Mini`, authenticate as `moquette`, save to
  Keychain). SMB is the ONLY protocol that shows a browsable share list in Finder.
- The two protocols do not interfere: a Mac using SMB and a Kodi box using NFS hit
  the same files on the mini simultaneously.

### NFS config (`/etc/exports`) - for Kodi

```
/Users/moquette/Kodi/Share  -mapall=moquette -network 192.168.7.0 -mask 255.255.255.0
/Users/moquette/Kodi/Backup -alldirs -mapall=moquette -network 192.168.7.0 -mask 255.255.255.0
/Users/moquette/Public      -mapall=moquette -network 192.168.7.0 -mask 255.255.255.0
```

`-mapall=moquette` makes every client write land as `moquette:staff` regardless of
the client's uid, so writes just work. `nfs.server.require_resv_port = 0` and
`nfs.server.mount.require_resv_port = 0` in `/etc/nfs.conf` allow non-root clients.
Validate with `sudo nfsd checkexports`.

### SMB config - for Macs

- `smbd` runs at boot. Share points (`sharing -l`): `KodiShare`, `KodiBackup`,
  `Public`, `moquette` (home). Guest is OFF (see lessons); auth as `moquette`.
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
ssh mini 'sharing -l | grep name:'                                        # SMB shares present
ssh mini 'fdesetup status'                                                # FileVault Off
```

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
   enabled guest account are BOTH ignored (`smbd_detect_sg_mode: NOT enabling super
   guest mode`); guest mounts fail even on loopback. SMB requires auth as
   `moquette`. Reverted; do not retry.
3. **Never NFS-export the home directory.** `/-mapall=moquette -network
   192.168.7.0/24` on `/Users/moquette` would give any device that grabs a
   `192.168.7.x` address unauthenticated read/write to `~/.ssh`, `~/Library/
   Keychains`, and `~/Code/moquette/vault` (the plaintext credential vault). Home
   is SMB-only (authenticated); for full-home access from another machine use
   `sftp://mini` / `sshfs`.
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

## The T7 (external 4 TB SSD) - currently UNPLUGGED

The Samsung T7 is an empty 4 TB external SSD, **set aside and physically unplugged**
as of 2026-07-07. It is out of `/etc/exports` and out of `sharing -l`; nothing on
the mini references it. It was never load-bearing: Kodi's content lives on the
internal SSD.

To bring it back later: plug it in, then decide the protocol. For Kodi (NFS) it
needs `/sbin/nfsd` Full Disk Access; for Macs (SMB) it needs `smbd` Full Disk
Access (System Settings -> Privacy & Security -> Full Disk Access -> enable the
daemon). Add the export/share, and give any irreplaceable data on it a second copy
(a single external SSD is a single point of failure).

---

## Other services on the box

- `/Library/LaunchDaemons/com.tony7bones.iptv2.plist` - root LaunchDaemon running
  the IPTV service (created 2026-07-02). Runs at boot regardless of login.

---

## Kodi clients that depend on this box (5 boxes)

Bedroom Fire TV (`192.168.7.84`), Office Fire TV, Shield, and two Travelsticks.
They mount `KodiShare` / `KodiBackup` / `Public` over NFS from `192.168.7.2` for
addon/IPTV/RSS content.
