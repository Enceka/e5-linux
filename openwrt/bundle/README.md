Detailed user guide: open **START-HERE.md** in the package root. Start **OpenWrt-Installer.exe** or **OpenWrt-Installer.py** and select the menu action.

# OpenWrt for E5 / T551M / VIPME M8 -- one-click flash package

The complete ZIP supports native Magisk TF deployment and extraction for desktop installation.
Read **`START-HERE.md` at the package root** first (detailed Chinese guide). Shortcut scripts live in `launchers/`,
images/checksums in `files/`, and supporting files in `scripts/`, `docs/` and `extras/`.
Installing this firmware ZIP in Magisk erases the selected TF partition (or unpartitioned card); it is not the separate switch-only module.
Native deployment prepares this device's firmware before erasing, verifies root and boot readback, and never reboots automatically.
The new native path still requires per-model hardware validation.


> 中文：[`README.zh-CN.md`](README.zh-CN.md)

Use the package matching your device. `files/device-profile.json` identifies
the target; installation and upgrades check it. Legacy packages without that
file are for E5 only. Never flash a different model's package.

Installs OpenWrt 25.12 (5G WAN, hotspot, LuCI and the info screen on the
panel) next to Android: Android stays as it is, OpenWrt
goes onto the **SD card** (the existing first partition, or the whole unpartitioned card, used in full) and boots from `boot_b`.  Android is always one step away.  Without a
card, `install-part` installs to a partition of the phone's own storage
instead (userdata is shrunk; Android keeps its files).

Public entry names are descriptive English names. Use `.cmd` on Windows or `.sh` on Linux/macOS:

| Entry | Action |
| --- | --- |
| `OpenWrt-Installer.exe` / `start-installer` | Choose an action; the Windows exe needs no separate Python |
| `install-to-tf-card` | First install, erasing the selected TF target |
| `install-to-userdata-image` | Configurable image on unencrypted userdata |
| `install-to-internal-storage` | Shrink userdata and create an independent root partition |
| `reinstall-internal-system` | Rewrite an existing e5root without shrinking or wiping Android data |
| `resume-internal-install` | Resume using the saved transaction.json |
| `switch-to-openwrt` | Switch from Android to an existing OpenWrt installation |
| `update-openwrt` | Update the running OpenWrt system |

`scripts/installer` contains internal helpers, not user entrypoints. Existing command-line options remain available.

## You need

* a matching device with an **unlocked bootloader** and Android rooted with **Magisk, KernelSU or KSUNext**; the package supplies its own static ARM64 BusyBox, independently of the root manager;
* Android running from slot a (as it comes from the factory);
* an **SD card of 4 GB or more**: the selected target is erased and used in full,
  without repartitioning or OTA reserve space -- or run
  `launchers/install-to-internal-storage.cmd` / `bash launchers/install-to-internal-storage.sh` and no card is needed;
* a Windows, macOS or Linux computer with:
  * **Python 3.8 or newer** (unnecessary on Windows when `OpenWrt-Installer.exe` is included);
  * **adb** (Android platform-tools, https://developer.android.com/tools/releases/platform-tools:
    add its directory to PATH, or put the `platform-tools` folder into the package's);
  * on Windows the device's USB driver (usually installed by Windows itself);
* a USB data cable.

## Flash

1. Turn on USB debugging on the E5, connect it, allow debugging on the phone.
2. Grant **Shell** superuser access in your root manager (the phone asks the first time).
3. Unpack the package and run, in its directory:

   * **Windows**: double-click `launchers/start-installer.cmd` (or run `launchers/start-installer.cmd` in a command prompt);
   * **macOS / Linux**: `./launchers/start-installer.sh`

   To see first that the device is fine, with nothing written: `launchers/start-installer.cmd --check` /
   `./launchers/start-installer.sh --check`.

   It asks for the APN, the hotspot's name and key.  For the APN just press
   Enter: OpenWrt picks it from the SIM's operator (China Mobile `cmnet`,
   Unicom `3gnet`, Telecom `ctnet`, Broadnet `cbnet`; the network's default
   for others), again after a SIM change.  Enter for the key: a random one,
   shown at the end.  Or give them on the command line:

   ```sh
   launchers/start-installer.cmd --ssid E5-OpenWrt --wifi-key 12345678 -y        (Windows)
   ./launchers/start-installer.sh --ssid E5-OpenWrt --wifi-key 12345678 -y       (macOS / Linux)
   ```

   It asks once more before it formats the selected **SD target** -- type
   `yes`.  Anything else, or no answer, stops it with the card untouched.  (-y
   skips the questions.)

4. When it says done, reboot manually into OpenWrt. Installation does not
   automatically reboot; the first boot takes about two minutes.

What it does:

* checks the package, the device (root, slot a, unlocked, the boot control
  block's live BCAB format/CRC and fallback state) and the free space;
* **pulls this device's own** Wi-Fi/BT/audio firmware and the vendor files
  that boot the baseband off its Android, as `/data/e5linux/device-files.tar`.
  The package carries no device's firmware: those files are the vendor's, and
  they carry each unit's identity (BT address, serial number), so every
  device uses its own. Collection, conversion and payload uploads finish before
  erasing the card;
* after Android releases the card, backs up differing `uboot/sml/teecfg/trustos/vbmeta`
  images from both slots under `/data/adb/e5-bootchain/`, then copies A to B and
  verifies readback. Identical images are not rewritten. On failure it attempts
  to restore changed B images and stops without switching slots. NV is excluded;
* uses the existing first SD partition, or the whole card only when no
  partitions exist. Writes the root image and grows its filesystem to the
  target's full capacity. The partition table is unchanged; no OTA space is
  reserved. A card with other partitions but no first partition is rejected;
* unpacks this device's files into it and writes the first boot's settings to
  its `/etc/e5/install.conf`. Unmounts, flushes and remounts read-only to check
  critical files and firmware hashes before writing boot;
* writes the boot image to `boot_b`, verifies it, and points the next boot at
  slot b. **Slot a's Android is not touched.** It also saves the boot target in
  `e5linux/boot-os` on userdata. Finally it backs up the live 32-byte misc boot
  control block, derives B's trial state from it and verifies the bounded write;

## Using it

* Hotspot: the name and key set while flashing; or the USB cable (USB network).
* LuCI (Aurora theme; System -> System -> Language and Style): `http://192.168.9.1`, user `root`, password `root` -- **change it**
  (LuCI -> System -> Administration, or `passwd` over SSH).
* SSH: `ssh root@192.168.9.1`.
* The panel: left/right turn the pages, confirm presses, back goes back; 高级
  (Settings) has the network mode, bands, APN, charge control and more.

### Without an SD card (`install-part`)

`launchers/install-to-internal-storage.cmd` (Windows) or `bash launchers/install-to-internal-storage.sh` installs OpenWrt onto a
partition of the phone's own storage: it shows the partition size range and
asks for one (default: the image plus 1 GiB), then whether the system should
**use the whole partition** (default: yes; choose no to retain the image's ~2 GiB allocation),
then asks **three times** before staging anything. On the next boot the boot image shrinks userdata by that
much, creates the `e5root` partition and writes OpenWrt into it; userdata is
not formatted and Android keeps its files. The first boot is a trial: one that
never comes up falls back. Back to Android: `e5-next-boot android` from the
screen or a shell, or delete `/data/e5linux/boot-os`, and reboot. Later
reinstalls or resizes of that partition run from the running OpenWrt:
`device-install-to-internal-storage.sh`.

## Back to Android

* On the panel: 高级 -> 系统 -> 下次启动 Android (Settings -> System -> Boot Android once);
* or over SSH: `e5-next-boot android && reboot`.

To temporarily boot installed OpenWrt from Android, without reinstalling,
mounting its root filesystem or changing persistent defaults, connect and run

```sh
launchers/start-installer.cmd --boot-openwrt          (Windows; macOS / Linux: ./launchers/start-installer.sh --boot-openwrt)
```

A failed OpenWrt boot falls back to Android on its
own after two tries.

The desktop `--boot-openwrt` checks the installed boot image and boot chain, then
writes and verifies only the 32-byte misc boot-control block. It never mounts or
repairs a root filesystem, updates root selectors/defaults, or synchronizes the
boot chain. OpenWrt retains its existing default-boot policy. The separate Magisk
switch module is a different entry point. Android A/Linux B remains required. The existing
first TF partition (or unpartitioned whole card) is used in full, without OTA
reserve space. Reverse-slot installation is not supported.

If installation fails, keep the complete terminal error. It identifies the
failed stage (partitioning, writing, mounting, extracting device files or
verifying content), the device's error/exit code and relevant SD/ext4 kernel
messages. Content verification lists the missing, empty or non-executable
files. Capacity and write protection are checked before writing; a mounted
Android volume stops installation. The TF partition table is never changed.

## Encrypted userdata: two-stage internal partition installation

`install-part` keeps the legacy preserve-and-shrink path for unencrypted data.
Encrypted data requires explicit consent to erase Android user data. The PC
saves a transaction and boot backups; initramfs rebuilds the userdata/e5root
layout, then requests a stock recovery factory reset. Stock recovery owns
Android's formatting and encryption initialization, including any on-device
confirmation. This handoff still needs hardware validation for each model.

Complete Android setup, enable/authorize ADB again, and restore Magisk/Shell
root. The PC waits for authorization, then verifies device identity and the
prepared layout before writing directly to the independent e5root partition.
To continue after closing the script, keep the same package and run:

```
launchers/start-installer.cmd --resume-part "backups/part-DATE-ID/transaction.json"
```

Do not repeat stage one. Backups contain device images and hotspot settings;
keep them private. Unattended erasure requires `--part --format-userdata -y`.
The filesystem fills the allocated partition capacity by default; use
`--no-grow-fs` only to retain the initial image size. Growth is offline and size-verified; a failed
resize is no longer reported as a successful installation. Progress is shown
every two seconds, with actual bytes during image writing and elapsed time
during filesystem checks/migration. Rebuild old packages before using this path.

## Re-installing over an existing installation

A device that already has an internal partition system refuses `install-part`
again (so a working partition is never touched by accident). To put a new system
into it while keeping Android's user data, the userdata filesystem and the
partition table, use the rewrite:

```text
launchers/reinstall-internal-system.cmd                       (the same as launchers/start-installer.cmd --reinstall-part; POSIX: ./launchers/reinstall-internal-system.sh)
launchers/start-installer.cmd --reinstall-part          (interactive: prints the geometry and the settings, one confirmation)
launchers/start-installer.cmd --reinstall-part -y       (unattended)
```

It reads the device's current userdata/e5root geometry, pulls this unit's own
firmware from Android, writes the package's image into e5root (e2fsck, grow to
the partition size, keep the existing hotspot/APN settings and the
`part-root`/`part-trial` markers), replaces `boot_b` and arms slot B, then says
to reboot. No repartitioning, no wiping of Android data, no stage one; the
system that was in e5root and its configuration are replaced. The transaction is
recorded under `backups/reinstalls/DATE-ID/transaction.json`.


## Update

With the E5 running OpenWrt and connected over USB, run the new package's:

```sh
launchers/start-installer.cmd --update                (Windows; macOS / Linux: ./launchers/start-installer.sh --update)
```

It updates the boot image and the OpenWrt image over the USB network and
**keeps OpenWrt's settings** (`/etc/config`, passwords, SSH keys, the traffic
records, the info screen's apps); packages added with `apk` are not kept.

On an **SD card install**, updates use this PC installer too. It uploads and
verifies the payload, preserves settings and firmware, and verifies boot before
publishing a request. After reboot, initramfs copies all payloads to RAM, verifies
them, unmounts the root and updates that same target offline. The filesystem
grows back to its original capacity. No GPT changes or alternate roots are made.
Keep power connected: a single root has no second TF root for automatic rollback.
Back up important files; extra packages and files outside the settings backup
are not migrated. Legacy multiple-root cards remain bootable; updating preserves
the running root's generation and leaves other partitions alone. Small existing
partitions are not expanded across adjacent partitions or unallocated space.

## Uninstall

Back in Android, in a root shell: `echo android > /data/e5linux/boot-os` (or
delete that file) so the card is no longer the system to boot, then take the
card out; its partition can be wiped with any partition tool.  The boot image
in `boot_b` does not bother Android, which boots from slot a.

## Disclaimer

Unofficial software, not affiliated with or endorsed by Rongyue or the makers
of the device and its chips.  Flashing needs an unlocked bootloader and root,
and can void the warranty, lose data or leave the device unusable; changing
the network, bands, AT commands or charging can cut the connection or upset
the device.  Provided "as is", without warranty of any kind: **at your own
risk**.  Back up what matters first, and keep to the local rules for the
bands and radio settings you choose.

## Maintainer and licences

Enceka <enceka@yeah.net>.  The scripts and e5-linux's parts are MIT
(`LICENSE`); OpenWrt, the Linux kernel and the other components are under
their own licences (GPL and others), with their sources at OpenWrt and in the
e5-linux repository.


Updates use outbound SSH uploads rather than an HTTP server on the PC. The Windows
installer bundles Paramiko; Python users can install it with `python -m pip install paramiko`.
`update-openwrt` also handles independent e5root installations: stage the image,
settings and device firmware, verify the boot image, then reboot into initramfs.
All payloads are copied into RAM and verified before the unmounted root is replaced.
The filesystem grows back to its existing partition size. Android userdata and GPT
are unchanged, including encrypted userdata. Keep power connected during the write;
a single internal root has no automatic rollback slot. Extra APK packages are not migrated.
