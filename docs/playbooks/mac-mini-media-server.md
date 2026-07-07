# Playbook - Mac mini media/share server (`mini`)

The Mac mini `mini` is the LAN host that serves the Kodi boxes. Every Fire TV,
Shield, and Travelstick mounts its shares off this box. It was originally set up
as a **desktop**, not a server, and that mis-config caused the shares to
disappear whenever no one was logged in. This playbook records what it serves,
how it is configured, and the always-on fix, so the regression is never relearned
the hard way.

---

## Device facts (confirmed 2026-07-07)

| Field        | Value                                                          |
| ------------ | -------------------------------------------------------------- |
| Hostname     | `mini` (ComputerName / LocalHostName / HostName all `mini`)    |
| Bonjour      | `mini.local`                                                   |
| LAN IP       | **192.168.7.2** (gateway 192.168.7.1, interface `en0`)         |
| Model        | Mac16,10 (M4-class Mac mini)                                   |
| macOS        | 26.5.2 (build 25F84)                                           |
| Shell access | `ssh mini` (key-based, no password)                            |
| Admin access | passwordless `sudo` for `moquette` (see below)                 |
| FileVault    | **Off** (required so it boots and mounts drives with no login) |

> Confirm IP is a DHCP reservation on the router. Kodi boxes point at
> `192.168.7.2`; if that lease ever moves, every box loses its shares.

---

## What it actually serves (two share systems, two different drives)

This is the non-obvious part. NFS and SMB on this box export **different drives**:

| System  | Path exported                   | Lives on            | Who uses it              |
| ------- | ------------------------------- | ------------------- | ------------------------ |
| **NFS** | `/Users/moquette/Kodi/Share`    | internal 245 GB SSD | **all 5 Kodi boxes**     |
| **NFS** | `/Users/moquette/Kodi/Backup`   | internal 245 GB SSD | Kodi backups             |
| **SMB** | `/Volumes/T7` (share name `T7`) | external 4 TB T7    | notebook / ad hoc access |

**The Kodi boxes mount over NFS, and NFS serves the internal SSD, not the T7.**
The 4 TB Samsung T7 is exported over SMB only and is intentionally empty (spare
storage). Do not assume "the external drive" is in the Kodi path: it is not.

### NFS config (`/etc/exports`)

```
/Users/moquette/Kodi/Share  -mapall=moquette -network 192.168.7.0 -mask 255.255.255.0
/Users/moquette/Kodi/Backup -alldirs -mapall=moquette -network 192.168.7.0 -mask 255.255.255.0
```

- `nfsd` is enabled and running; validate exports with `sudo nfsd checkexports`.
- The served content is **small and not video**: `Share` is about 23 MB (IPTV EPG
  `.xml.gz`, addon repository zips, RSS, splash), `Backup` about 433 MB. There is
  no large media library on this box.

### SMB config

- `smbd` runs as a system daemon (enabled at boot). Shares: `KodiShare`,
  `KodiBackup`, the `moquette` home, `Public`, and `T7` (guest, read-write).
- The `T7` volume is APFS, SMART Verified, not encrypted, mounted `noowners`
  (`Owners: Disabled`) - fine for a guest share.

---

## The always-on fix (root cause + correction)

**Symptom:** the shares worked while someone was logged in, then vanished from
every device minutes after logout.

**Root cause:** power management was set to sleep after **1 idle minute**
(`pmset sleep 1`). While logged in, transient sleep assertions from
`nfsd`/`powerd`/`screensharingd` held the box awake; the moment those released
(logout, no active NFS I/O), the mini slept, dropped off the LAN, and unmounted
the shares. A sleeping Mac serves nothing.

**Fix applied 2026-07-07:**

```
sudo pmset -a sleep 0 disksleep 0 autorestart 1 womp 1
```

| Setting       | Before | After | Why                                            |
| ------------- | ------ | ----- | ---------------------------------------------- |
| `sleep`       | `1`    | `0`   | never system-sleep - THE fix                   |
| `disksleep`   | `10`   | `0`   | never spin down drives (keeps NFS/SMB instant) |
| `autorestart` | `0`    | `1`   | auto-reboot after a power blip (headless box)  |
| `womp`        | `1`    | `1`   | wake-on-LAN (already set)                      |

**Why it is now solid 24/7:** FileVault is off and `autorestart` is on, so after a
reboot or power loss the mini boots, mounts its drives, and starts `nfsd` + `smbd`
with **no login required**. The internal SSD is always mounted, so the NFS shares
are always present.

### Verify always-on (regression check)

```
ssh mini 'pmset -g custom | grep -E " sleep|disksleep|autorestart|womp"'
# expect: sleep 0, disksleep 0, autorestart 1, womp 1
ssh mini 'nfsd status && showmount -e localhost'   # exports present
ssh mini 'fdesetup status'                          # FileVault is Off
```

If `sleep` is ever back to a non-zero value, the "shares vanish after logout"
symptom is back. Re-apply the `pmset` line above.

---

## Management access (passwordless sudo)

`ssh mini` is key-based (no password), but that is **SSH login, not sudo**. To let
automation run privileged commands, a fail-safe passwordless-sudo rule was
installed:

```
# stage with a dotted name (sudo ignores files containing a dot in sudoers.d),
# validate BEFORE activating, then rename to go live - cannot lock you out:
printf 'moquette ALL=(ALL) NOPASSWD: ALL\n' | sudo tee /etc/sudoers.d/moquette.stage >/dev/null \
  && sudo visudo -cf /etc/sudoers.d/moquette.stage \
  && sudo chown root:wheel /etc/sudoers.d/moquette.stage \
  && sudo chmod 0440 /etc/sudoers.d/moquette.stage \
  && sudo mv /etc/sudoers.d/moquette.stage /etc/sudoers.d/moquette
```

Result: `/etc/sudoers.d/moquette` = `moquette ALL=(ALL) NOPASSWD: ALL`, perms
`0440 root:wheel`. Verify with `sudo -n -l` (lists privileges with no prompt) and
`sudo visudo -c` (parses OK). The mini's admin password is not stored in the vault.

---

## The T7 (spare drive - when to promote it)

The T7 is a 4 TB external SSD sized for a video library that does not currently
exist. Serving Kodi's tiny config content from an external drive would only add a
failure point (an unplugged cable would take the addon/IPTV content down), so the
config shares deliberately stay on the always-mounted internal SSD.

**Promote the T7 to an NFS media drive only if a real movie/TV library appears.**
Then: create `/Volumes/T7/Media`, add a line to `/etc/exports`
(`/Volumes/T7/Media -mapall=moquette -network 192.168.7.0 -mask 255.255.255.0`),
`sudo nfsd update`, point Kodi at it, and confirm the boxes remount. Give any
irreplaceable library a second copy - a single external SSD is a single point of
failure.

---

## Other services on the box

- `/Library/LaunchDaemons/com.tony7bones.iptv2.plist` - a root LaunchDaemon running
  the IPTV service (created 2026-07-02). Runs at boot regardless of login.

---

## Kodi clients that depend on this box (5 boxes)

Bedroom Fire TV (`192.168.7.84`), Office Fire TV, Shield, and two Travelsticks.
All are provisioned per the main Kodi provisioner flow; they consume this box's
NFS shares for addon/IPTV/RSS content.
