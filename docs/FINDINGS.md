# Findings: booting Linux on the Rongyue E5

Everything here was measured on the device or read out of the stock images; items
that are still assumptions are marked **UNVERIFIED**. Device: Rongyue E5,
`ro.product.device=ums9158_1h10`, `ro.board.platform=ums9621`, model `E5`,
Android 13, stock kernel `5.15.119-android13-8-00018-ga78ea39db117-ab10710420`,
build `TS305_V03_20260113_2322`.

## 1. Boot chain

The E5 is a normal Android A/B device with an unlocked bootloader
(`ro.boot.verifiedbootstate=orange`) and the Android 13 GKI split:

| partition | contents | size |
|---|---|---|
| `boot_a` / `boot_b` | header v4; kernel (arm64 Image, EFI stub); ramdisk | 64 MiB |
| `init_boot_a` / `init_boot_b` | header v4, kernel_size 0, generic ramdisk | 8 MiB |
| `vendor_boot_a` / `vendor_boot_b` | VNDRBOOT v4, DTB in the kernel field, vendor ramdisk (~80 MiB) | 100 MiB |
| `dtbo_a` / `dtbo_b` | the device tree the bootloader actually passes | 8 MiB |
| `dtb_a` / `dtb_b` | all zero | 8 MiB |
| `misc` | `bootloader_control` at offset 0x800 | 1 MiB |
| `super` | logical partitions (system, vendor, product, …, vendor_dlkm) | 5.47 GiB |
| `userdata` | f2fs, mounted directly (no metadata encryption) | 21.86 GiB |

### Which ramdisk does LK use? boot.img wins

This decided the whole design, and the stock bootloader log (`uboot_log`
partition, 16 MiB) answers it directly:

    bootimage: generic ramdisk size is 360840
    bootimage: generic ramdisk offset is 0x2c98000
    ...
    bootimage: generic ramdisk size is zero, maybe ramdisk in init_boot image side!
    init_bootimage: generic ramdisk size is 1907183

LK takes the **generic ramdisk from boot.img**, and only falls back to
`init_boot` when boot.img's `ramdisk_size` is zero (which is the stock state:
stock `boot_a`/`boot_b` carry kernel only). The same log shows the two ramdisks
being loaded to separate addresses, so they are not simply concatenated either:

    vendor_boot_a ramdisk read OK, size = 80668385, locate to 0xc0000000!
    boot_a ramdisk read OK, size = 360840, locate to 0xc4cee6e1!

**Consequence:** the Linux kernel *and* the Linux initramfs both go into slot b's
`boot` image. `init_boot_b` and `vendor_boot_b` stay stock — which also
matters because LK AVB-verifies `init_boot` (`verify boot check init_boot`,
`partion init_boot, verify_ret:0x0`).

### Ramdisk compression must be LZ4 *legacy*

The stock and Magisk ramdisks both start with `02 21 4c 18` (LZ4 legacy frame,
not the modern `04 22 4d 18`). `boot/build-boot-image.py` compresses with
`lz4 -l` accordingly.

### AVB is not enforced

`ro.boot.verifiedbootstate=orange`, and the device currently boots a
Magisk-patched `boot_a` (`ramdisk_size=360840` where stock is 0) whose digest
cannot match the stock descriptor. The boot image builder therefore keeps the
stock header, the stock vbmeta blob and the stock `AVBf` footer byte for byte
and only repoints `original_image_size`/`vbmeta_offset` — the safe path, since
regenerated descriptors have produced `invalid vbmeta header` /
`ERROR_INVALID_METADATA` failures on this device before.

### Slots and `misc`

Live `misc` at offset 0x800 (32 bytes, CRC-valid):

    5f 61 00 00 42 43 41 42 01 02 00 00 9f 00 1e 00 ...
    "_a\0\0"  "BCAB"     v1 n2        a     b

This is the same AOSP `bootloader_control` structure mu300-linux documents for
the UMS9620: `slot_suffix[4]`, magic `BCAB`, version, `nb_slot`,
`recovery_tries`, `merge_status`, `slot_info[4]`, then a CRC32 over the first
28 bytes. `slot_info` bits are priority (4) | tries_remaining (3) |
successful_boot (1):

* slot a = `0x9f` → priority 15, tries 1, successful
* slot b = `0x1e` → priority 14, tries 1, **not** successful

`flash-trial.sh` writes a slot-b trial block derived from these live values:
slot a keeps a slightly lower priority and stays successful, slot b gets priority
15 with tries=2. LK decrements to 1 on the next boot, and — exactly as
mu300-linux found for this bootloader family — treats `tries==1 && !successful`
as an already-failed boot, so a Linux attempt that never completes rolls back to
Android. **UNVERIFIED on this device**: that the E5's LK implements the identical
decrement/rollback rule. The trial path is one-shot by construction, and
`boot/init` also restores the slot-a block explicitly before it reboots.

## 2. There is no free eMMC space — the rootfs lives in `/data`

mu300-linux puts its root filesystem in the unallocated region after `userdata`.
On the E5 there is no such region: `userdata` (partition 70) ends at LBA
61075455, exactly the GPT's `last_usable_lba` — **zero bytes free**.

    p70  first=15241216  last=61075455  size=21.86 GiB  userdata
    gpt  last_usable_lba=61075455  ->  free after last partition: 0 bytes

Rather than rewrite the partition table, e5-linux keeps mu300-linux's "do not
touch the GPT" property and stores the root filesystem as a file inside Android's
`/data`: **`/data/e5linux/rootfs.ext4`**. `/data` is f2fs mounted straight
from `mmcblk0p70` (no `dm-default-key` metadata encryption), so the Linux
kernel mounts it with the in-tree f2fs driver and attaches the file to a loop
device. Android's per-file encryption means the file itself is stored in the
clear — which is fine, it is expected to be readable by root only.

Trade-offs worth knowing: a factory reset or `fastboot -w` erases it, and
mounting f2fs read-write from Linux is only as safe as the last Android
shutdown. Both are acceptable for a bring-up that must not touch the partition
table; a later revision can shrink `userdata` and carve a real partition.

## 3. Module load order is not alphabetical

The stock Android first-stage list in `vendor_boot` is a hand-tuned 83-entry
subset of the kernel's modules, with ADI/PMIC/clock layers first and
`ump9620-regulator.ko` at position 18. Loading an alphabetical list puts
`ump9620-regulator.ko` first, where `dev_get_regmap()` returns NULL and the
driver dereferences it — first-stage init dies with no log at all. e5-linux ships
that exact order in `boot/module-order.stock` and `boot/stage-modules.sh`
filters it down to the modules this kernel actually built, so the initramfs
`insmod` order always matches the order the stock first-stage init used.

`sprd_wdt_fiq.ko` is at position 10 of that list and matters more than the rest:
it is the SoC watchdog, it feeds itself from its FIQ handler, and the bootloader
hands over with the watchdog armed (`sprdboot.wdten=e551`,
`androidboot.dswdten=enabled`). This model exposes **no `/dev/watchdog`** even
on stock, so there is no userspace way to pet it.

## 4. Log capture

A Linux boot attempt that fails gives no adb, no network and no ylog (Android
only archives ylog after a *successful* boot). Three channels are used:

1. **`boot/init` writes every stage to `/dev/kmsg` and `/dev/pmsg0`**, which
   land in `/sys/fs/pstore/console-ramoops-0` / `pmsg-ramoops-0`. The boot
   command line also registers ramoops early
   (`ramoops.mem_address=0xfff80000 ramoops.mem_size=0x40000 …`, the region the
   stock DT reserves at `ramoops@fff80000`), so output from a boot that dies
   before the DT-based initcall is not lost. This mirrors the mitigation recorded
   in `artifacts_e5/diagnostics_2026-09-09.md`.
2. **A 4 MiB persistent log at 56 MiB inside `boot_b`**, written by `boot/init`.
   Unlike pstore this survives a cold power cycle and is not overwritten by the
   next successful Android boot. `boot/build-boot-image.py` refuses to build an
   image that would overlap it.
3. **The bootloader log** in `uboot_log`, which is the only place that shows
   slot selection, ramdisk sizes and AVB results.

`tools/collect-logs.sh` pulls all three after the device is back in Android.

**In the switch_root path the block deliberately ends at `stage=switch-root`, and
that is not a bug.** The writer is the initramfs `init`; `switch_root` replaces
PID 1 and the initramfs goes away with it, so there is nothing left to write the
block. A block whose last stage is `stage=switch-root` therefore says the session got
all the way into the real root filesystem — which is exactly what the last run
recorded (`uptime=14.74`, `loaded=60 failed=0`, `default-boot-linux (slot a restore
skipped)`, `switch-root root=/disk init=/lib/systemd/systemd`). The last line
`boot/init` writes before handing over, `stage=switch-root-jobs-killed`, is only in
`/run/stages` inside the running system (`cat /run/stages`), never in this block.
Anything that happens after switch_root has to be logged from userspace: the block
cannot see it, so it cannot diagnose a session that dies later (see §9).

**In the standalone path — no root filesystem, `init` keeps running — the block used
to stop after its first successful write.** `persist()` takes a `/run/persist.lock`
directory so the periodic loop cannot race the caller, and it recorded the timestamp
*inside* that directory (`/run/persist.lock/stamp`) and released it with
`rmdir /run/persist.lock`. `rmdir` cannot remove a directory that holds a file, so
the release always failed; from then on every call either returned because the lock
looked younger than the two-minute staleness limit or, past that limit, failed to
re-create it. The lock-expiry logic could not save it either — the age test reads the
lock *path* itself (`cat /run/persist.lock`, a directory, always empty), and the
expiry's `rmdir` fails for the same reason. `boot/init` now keeps the stamp beside the
lock (`/run/persist.stamp`) and releases both with `rm -rf`. Note the contrast with
the campaign's run 1, which used an older `init` with no locking at all and did keep
writing every fifteen seconds right up to `uptime=276.28`.

## 5. Device-alive risks specific to this hardware

* ~~**Charging has no driver path.**~~ **Superseded — see §7.2.** The E5 charges
  through `aw322xx_chg` on i2c2 address 0x6a. There is no file called
  `aw322xx_charger.c` in any of the trees used for this port, which is where
  this section originally stopped, but `drivers/power/supply/aw32257_charger.c`
  *is* that driver: it matches `compatible = "awinic,aw322xx_chg"` and registers
  the power supply literally named `aw322xx_charger`. It was never loaded.
  With it loaded the kernel reports `battery/status = Charging`. A Linux session
  still should not be left unattended, because of the two risks below.
* **No `/dev/watchdog`.** See §3.
* **The modem and PM co-processor are not brought up.** mu300-linux needs
  Android's `modem_control` in a chroot to disarm the PM watchdog; nothing
  equivalent has been attempted here. Anything that depends on the modem (mobile
  data, and on some Unisoc parts the PM watchdog) is out of scope for now.

## 6. USB gadget

Stock exposes a single UDC, `musb-hdrc.1.auto`, with an Android-shaped gadget
(`ffs.adb`, `sprdgser.gs0/1/2`, `idVendor=0x18d1 idProduct=0x4ee8`).
e5-linux builds its own gadget through configfs from the initramfs: ECM
(`usb0`, the `192.168.77.0/24` management LAN) plus a CDC-ACM console on
`ttyGS0`. `CONFIG_USB_F_ACM`/`CONFIG_USB_F_ECM` and the two `USB_CONFIGFS_*`
options are built in rather than modular so the console does not depend on module
load order; musb itself stays a module and is loaded at its stock position.

Known open issue inherited from the kernel port: the gadget bind-to-enable path
was a few seconds slower than stock, and the four `musb_sprd` fixes
(DMA channel programming, `dr_mode`, the PHY platform-name race, the
`hops.host_start` NULL deref) were compile-verified only.

**VERIFIED** (§7): `/sys/class/udc/musb-hdrc.1.auto/state` reads `configured`,
the host enumerates `0525:a4a1 Linux-USB Ethernet Gadget`, the initramfs udhcpd
hands out `192.168.77.4/24`, and telnet to `192.168.77.1` gives a root shell.

### 6.1 NCM instead of ECM, and a DHCP server that actually runs

The gadget originally spoke CDC-ECM.  macOS does bind it (it shows up as an
Ethernet interface), but nothing served DHCP on a normal boot: the initramfs udhcpd
only runs on the standalone path, and on the switch_root path init just does
ifconfig usb0 up, so the host sat on a 169.254 link-local address forever.  Two
changes:

* the configfs function is now **ncm.usb0** (the kernel already had
  CONFIG_USB_CONFIGFS_NCM=y and CONFIG_USB_F_NCM=y; only the initramfs script named
  ecm.usb0), which is also the protocol macOS handles best.  The CDC-ACM console is
  unchanged, and it is still the channel this work is driven over.
* usb0 is configured by systemd-networkd -- Address=192.168.77.1/24 plus
  DHCPServer=yes, in /etc/systemd/network/10-e5-usb0.network, with NetworkManager
  told to leave the interface alone.  networkd is pulled in by a drop-in on
  NetworkManager.service rather than by enabling it, because the overlay travels
  into the initramfs as plain files and cannot carry symlinks.

Result on hardware: the device reports usb0 UP 192.168.77.1/24 with networkd active
and State: routable (configured), the Mac gets 192.168.77.92 by DHCP, and
ping 192.168.77.1 is 0% loss.  (There is no sshd in the image, so the LAN is ICMP/HTTP
for now; the serial console is still the shell.)

### 6.2 The power key used to power the device off

Symptom: the screen goes dark and pressing power does not bring it back -- and the
device disappears from USB entirely.  Cause: systemd-logind's default
HandlePowerKey=poweroff.  Plasma Mobile drives the key itself, but logind saw it
first, so "wake the screen" was executed as "power off".

/etc/systemd/logind.conf.d/10-e5-power.conf now sets HandlePowerKey,
HandlePowerKeyLongPress, HandleSuspendKey, HandleHibernateKey, HandleLidSwitch and
IdleAction all to ignore -- this port has no usable suspend/resume either, so nothing
should try.  Verified with busctl get-property: HandlePowerKey = "ignore",
IdleAction = "ignore".

### 6.3 Session, keys, and which kernel Image to flash

Three symptoms turned out to be one cause, and one of them was self-inflicted:

* The panel showed the SDDM **greeter** (its theme is what looks like a boot logo)
  instead of Plasma Mobile, and the **power and volume keys did nothing**.  Both are
  the same failure: when the autologin session fails, SDDM falls back to the greeter,
  and in an X11 greeter the keys go nowhere -- they are wired to gpio-keys, not to the
  console.  The kernel does deliver them: /proc/bus/input/devices shows gpio-keys with
  KEY_VOLUMEDOWN (114), KEY_VOLUMEUP (115) and KEY_POWER (116).
* The autologin session was failing because **KWin could not keep /dev/dri/card0**.
  With the Image this work had rebuilt (Homebrew clang 23, plus CONFIG_DEVMEM for a
  watchdog experiment that turned out to be a dead end) the log reads
  "kwin_wayland_drm: failed to open drm device at /dev/dri/card0 / No suitable DRM
  devices have been found", and KWin's clients then abort with
  "no Qt platform plugin could be initialized".

So the boot image now carries the **original Image** again (work/Image, sha256
c1ab1905...) with the new ramdisk: 64 modules, the NCM gadget, and the overlay.  The
same three checks then pass: kwin_wayland + plasmashell run, /sys/kernel/debug/dri/0/state
says allocated by = kwin_wayland, and the keys have a compositor to talk to.
CONFIG_DEVMEM stays in the fragment only because boot/init logs the SoC watchdog
registers; without it that log line is just skipped.

### 6.4 Telnet on the management LAN

The full system had no remote shell (the initramfs telnetd only exists on the
standalone path, and there is no sshd in the image).  The initramfs now copies its
static arm64 busybox into the real root as /usr/local/bin/busybox, and
e5-telnetd.service runs busybox telnetd -p 23 -l /bin/login from it -- no package has
to exist in the Debian image.  The unit is pulled in by the same NetworkManager
drop-in as systemd-networkd (the overlay cannot carry enable symlinks).  Verified from
the host: 192.168.77.1:23 answers with a telnet banner and the host holds a DHCP lease
on 192.168.77.92.

## 7. What actually happened: the boot campaign

Five trial boots on 2026-09-17. Each one flashes `boot_b` plus the 32-byte
`bootloader_control` in `misc`, reboots, and reads the results back either from
Android afterwards or, once the gadget worked, from the running Linux itself.

### 7.1 The kernel boots and the slot mechanism works

Run 1 (slot b, 42 modules) settled it. `uboot_log` shows LK honouring the armed
slot — `boot_b ramdisk read OK, size = 1800450` followed by
`fixup androidboot.slot_suffix=_b` — and the persistent block inside `boot_b`
records our kernel running our init for 276 s:

```
E5-PERSIST-BEGIN uptime=276.28 release=5.15.211-g94401422a7df
1.74 stage=devfs-ready
5.08 stage=modules-done loaded=31 failed=11
5.32 stage=partitions misc=/dev/mmcblk0p3 boot_b=/dev/mmcblk0p37
45.32 stage=udc udc=none available=
45.72 stage=misc-restored-slot-a dev=/dev/mmcblk0p3
45.87 stage=ready standalone
```

The device then rebooted itself back into Android, which means the rollback rule
this project depends on holds on this device: a slot-b boot that never reaches
userspace ends up on slot a.

### 7.2 Two drivers existed but were never loaded

Both failures had the same shape, and neither is visible in the source tree.

**The charger blocked USB.** The first run had no UDC at all, and `dmesg` said
why once the deferral was traced:

```
platform 64a00000.usb: DEFERDBG: supplier 2-006a not ready
probe of 64a00000.usb returned -517
```

`2-006a` is the AW322xx charger. On the live device the USB controller lists it
as a devicetree supplier, because the charger node declares the `vddvbus`
regulator that `musb_sprd` requests when it switches to host mode:

```
$ ls /sys/bus/platform/devices/64a00000.usb/ | grep supplier
supplier:i2c:2-006a -> .../i2c:2-006a--platform:64a00000.usb
```

`fw_devlink` checks suppliers *before* entering a probe function, so while
`2-006a` has no driver the USB controller can never probe — and the only
symptom is an empty `/sys/class/udc`. Loading `aw32257_charger.ko` fixes it
properly. `fw_devlink=permissive` also unblocks it, but it was tried and
rejected: with every driver free to probe out of order the kernel died before
the initramfs wrote its first log line.

**The display was missing its power domain.** `/dev/dri` did not exist and
`/sys/class/drm` contained only `version`, because `sprd_vpu_pw_domain.ko` —
the genpd provider for the VPU/display domain — was never loaded, so
`31000000.dpu`, `31300000.dsi` and `30130000.sprd-gsp` never probed. This is
the same gap `artifacts_e5/diagnostics_2026-09-10.md` works through on the
Android port. Loading it, plus `sprd-gsp.ko` and `sprd-drm.ko`, gives
`/dev/dri/card0` and a `card0-DSI-1` connector.

The lesson generalises: Android's first-stage `modules.load` is not a
description of what the hardware needs, it is a description of what Android's
*second* stage has not loaded yet. Anything the initramfs needs and Android
defers is missing from it, and the failure mode is silent.

### 7.3 The final state

```
Linux e5-linux 5.15.211-g94401422a7df aarch64
1.76 stage=devfs-ready
11.57 stage=modules-done loaded=56 failed=0
11.86 stage=partitions misc=/dev/mmcblk0p3 boot_b=/dev/mmcblk0p37
12.00 stage=udc udc=musb-hdrc.1.auto available=musb-hdrc.1.auto,
12.13 stage=usb-bind-done rc=0
12.58 stage=data-mounted
13.41 stage=rootfs-unavailable err=
13.44 stage=misc-restored-slot-a dev=/dev/mmcblk0p3
13.47 stage=ready standalone
```

All 56 modules load, `/sys/kernel/debug/devices_deferred` is empty (nothing is
waiting on anything), the UDC is `configured`, the device tree is a working
network, and:

```
/ # cat /sys/class/power_supply/battery/status
Charging
/ # cat /sys/class/power_supply/battery/capacity
50
/ # ls /dev/dri
card0
```

Also worth recording because it cost a boot: the initramfs used to locate
`misc`/`boot_b` *after* the module pass. Moving that earlier, so an early crash
still leaves a log, does not work on this platform — the eMMC partitions are not
in `/sys/class/block` yet and the discovery came up empty for twenty seconds.
The authoritative attempt stays after the module pass; the early one is best
effort. `boot/init` now does both.

## 8. Wi-Fi: the driver is in the tree and builds, but nothing ships it

`lsmod` under Linux has no Wi-Fi module and there is no `wlan0` — not because the
hardware has no driver, but because the driver was never put into the initramfs.

The hardware is a Unisoc WCN combo chip (sc2332/sc2355 family); the board's own DT
wires it up over SDIO as `sprd,sc2355-sdio-wifi`. Both halves of the driver are in
the kernel tree e5-linux builds from:

| module | source | config in `e5_rongyue_defconfig` |
|---|---|---|
| `wcn_bsp.ko` | `drivers/unisoc_platform/sprdwcn/` — sprdwcn bus plus the `sdio/sdiohal_*` glue | `CONFIG_UNISOC_WCN_BSP=m` (line 758) |
| `sprd_wlan_combo.ko` | `drivers/unisoc_platform/sprd_wlan_combo/` — fullmac cfg80211 WLAN driver | `CONFIG_UNISOC_WLAN_COMBO=m` (line 762) |

The Kconfig is reachable — `drivers/unisoc_platform/Kconfig` sources both
sub-Kconfigs and `drivers/Kconfig` sources that file — so `make Image modules dtbs`
really does build both `.ko` files, and `CONFIG_CFG80211=m` is present for the
fullmac glue. The `.ko` files are in the kernel build output; they are simply not in
`boot/module-order.txt`, which is the only list `boot/stage-modules.sh` packs into
the initramfs.

That they are second-stage on Android is visible on the running device:

    # ls /vendor/lib/modules | grep -iE "wcn|wlan|cfg80211"
    cfg80211.ko
    sprd_wlan_combo.ko
    wcn_bsp.ko

and a first-stage device check says the rest of the path is intact: the SDIO
controllers inside the SoC (`22200000.sdio`, `22210000.sdio`) *do* defer early on
their PMIC power domain -- `probe of 22210000.sdio returned -517` at 1.33 s, before
any module is loaded -- but by `uptime=14.74`, when the initramfs writes its last log
block, `/sys/kernel/debug/devices_deferred` is empty, so the PMIC driver from the
module pass is what unblocks them. Wi-Fi is missing its driver, not its bus.

**Why they were missing is the same story as section 7.2.** `module-order.stock` is
Android's *first-stage* `modules.load`. Android brings Wi-Fi up from its second stage
(`modprobe`, out of `/vendor/lib/modules`), so the WCN modules are not in that
83-entry list — and because the initramfs uses `insmod` with a fixed order, there is
no modprobe afterwards to pull them in either. The result is a silent gap: the
modules are built, nothing loads them, and the only symptom is that Wi-Fi does not
exist. The charger (`aw32257_charger.ko`, section 7.2) and the display power domain
(`sprd_vpu_pw_domain.ko`) were the same shape of bug.

The fix is two lines in `boot/module-order.extra`:

    wcn_bsp.ko
    sprd_wlan_combo.ko

`boot/gen-module-order.py` resolves the closure, so `cfg80211.ko` is pulled in
automatically and the SDIO/MMC core the bus needs is built in (`CONFIG_MMC=y`,
`CONFIG_MMC_SDHCI=y`). The kernel modules then have to be rebuilt and restaged
(`kernel/build-linux.sh`, `boot/stage-modules.sh`, then the boot image). No `.ko`
files were on the macOS host used for this session, so the entries are in place but
**UNVERIFIED on hardware**.

### 8.1 Loading the modules is necessary, not sufficient

`drivers/unisoc_platform/sprdwcn/boot/wcn_boot.c` and `wcn_integrate_boot.c` take the
WCN core out of reset with `request_firmware()`, so the chip only boots if these are
where the Linux firmware loader looks (`/lib/firmware` in the root filesystem):

    wcnmodem.bin
    gnssmodem.bin
    wifi_board_config*.ini
    connectivity_configure*.ini
    connectivity_calibration*.ini
    tsx_data

and the driver additionally reads factory data from Android paths that have no
Debian equivalent:

    /mnt/vendor/wifimac.txt                              (factory MAC)
    /mnt/vendor/wcn/connectivity_calibration_bak.ini
    /productinfo/wcn/tsx_bt_data.txt
    /data/vendor/wifi/wifimac_temp.txt

Read out of the running Android, these are the files that actually exist on this
device and where they live:

| file | location on Android | note |
|---|---|---|
| `wcnmodem.bin` | `/odm/firmware/wcnmodem.bin` | 947 KiB, the WCN firmware |
| `gnssmodem.bin` | `/odm/firmware/gnssmodem.bin` | 596 KiB, requested during WCN boot too |
| `wifi_board_config*.ini` | `/odm/firmware/` and `/odm/etc/` | `.ini`, `.xpe.ini`, `_aa.ini`, `_aa.xpe.ini` — the board variants all ship |
| `tsx_data` | `/vendor/firmware/tsx_data` | the only `tsx`-ish file on the vendor image |
| factory MAC | `/mnt/vendor/wifimac.txt` | `fc:b5:85:d0:9d:47` on this unit |
| calibration dir | `/mnt/vendor/wcn/` | empty on Android too; the driver *writes* `connectivity_calibration_bak.ini` there, so it has to exist and be writable |

`/odm` is an `erofs` logical partition inside `super` (`/dev/block/dm-0`) and
`/vendor` likewise, so the blobs cannot just be mounted from Linux the way
`userdata` can. They have to be pulled off the device from Android and shipped inside
the `rootfs.ext4` (put them in `/lib/firmware`) — the same reasoning as section 2,
just for firmware rather than the root filesystem. `/mnt/vendor` is different: that is
plain **`/dev/block/mmcblk0p1`, ext4, 5.3 MiB**, so a Linux boot can mount it
read-only at `/mnt/vendor` directly and get `wifimac.txt` (and `btmac.txt`) from the
real partition instead of a copy. The `calinv` partition (`mmcblk0p69`) mounts too,
but it is empty — it is not where the calibration lives.

One thing works in our favour: the same code waits for a filesystem to appear before
giving up ("request_firmware keep waiting for file system ready, the max waiting time
is 80s"), which is why loading the WCN modules from the initramfs — where
`/lib/firmware` does not exist yet — is still workable: the driver retries until the
Debian root filesystem is mounted.

`rootfs/pull-wcn-firmware.sh` does the copy: it stages `/odm/firmware`'s WCN set,
`/vendor/firmware/tsx_data` and the `/mnt/vendor` factory files into
`rootfs/overlay/lib/firmware/` and `rootfs/overlay/mnt/vendor/` (which
`device-finalize.sh` then applies like any other overlay file), skipping paths that
do not exist. They are vendor blobs and stay out of the repository. On this unit
`tsx_data` is skipped: `/vendor/firmware/tsx_data` is a symlink to
`/mnt/vendor/productinfo/wcn/tsx_bt_data.txt` and that target is a dangling link even
under Android, whose Wi-Fi works regardless -- so it is not fatal, but it also cannot
be copied.

### 8.2 Verified on the device

The packaging fix works.  Built from the tree and listed in
boot/module-order.extra, the WCN stack loads on a real boot:

    stage=modules-done loaded=63 failed=0
    sprd_wlan_combo      2510848  0
    cfg80211              888832  1 sprd_wlan_combo
    wcn_bsp               430080  1 sprd_wlan_combo

and the driver probes the chip: marlin_probe: device node name: sprd-marlin3, the DT
supplies (avdd12, avdd33, dcxo18) resolve, and the WCN bus channels come up.  The
firmware is reachable because the initramfs now carries the rootfs overlay and
materialises it *before* the module pass
(stage=overlay-early files=21 firmware=6), so request_firmware() finds wcnmodem.bin
without waiting for the real root filesystem.

### 8.3 The next blocker: the driver reads its firmware from a partition

The chip still does not come up, and this is why.  The WCN base driver takes the
BT/Wi-Fi firmware from a path in the device tree, not from the firmware loader:

    /proc/device-tree/sprd-marlin3/sprd,btwf-file-name  = /dev/block/by-name/wcnmodem
    /proc/device-tree/sprd-marlin3/sprd,gnss-file-name  = /vendor/firmware/gnssmodem.bin

and this device has **no partition named wcnmodem** -- the GPT has no wcn* name at
all.  wcn_boot.c opens that path with filp_open() and reads the firmware out of it,
so the boot ends with the chip being powered back down

    WCN BASEwifipa 3v3 0 ... avdd12 power disable ... marlin chip en pull down
    sprd-wlan: failed to power on WCN!
    probe of sprd-marlin3:wlan returned 19 after 60553796 usecs

i.e. -ENODEV after the driver's 80-second retry window.  (supply dvdd12 not found,
using dummy regulator is benign; the other three supplies resolve.)

The path is what has to be satisfied, and it can be satisfied from userspace: point
/dev/block/by-name/wcnmodem at a loop device backed by the wcnmodem.bin this image
already carries, and provide /vendor/firmware/gnssmodem.bin.  Both belong in the
overlay, which boot/init already knows how to apply.

### 8.4 What to look at when it is tried

    dmesg | grep -iE "wcn|wlan|sdio"      # probe, firmware load, chip boot
    lsmod | grep -E "wcn_bsp|sprd_wlan_combo"
    ip link                               # wlan0 should appear
    cat /sys/class/net/wlan0/address      # factory MAC, or random if unset


## 9. The five-minute reset: the PMIC watchdog, not a panic

**Solved.** A Linux session used to die about five minutes in, silently, and it looked
like a panic.  It never was one: the bootloader arms the *PMIC* watchdog as well as the
SoC one, and the driver that feeds it was built but never staged into the initramfs.

Measured on the device with the host doing *nothing at all* -- no serial console
opened, no adb, no reads -- using only the bootloader log:

    LK hands over to Linux      21:21:27
    LK runs again (the reset)   21:26:22       295 s

and the reset leaves no console output, no pstore record and is classified by LK as a
reset (ANA_REG_GLB_POR_OFF_FLAG:0x0).  With nobody reading the serial port a real panic
would look identical, which is why this stayed a mystery.

The answer is in the PMIC watchdog driver's own probe message, once it is loaded:

    [   13.489569] calling  init_module+0x0/0xfe8 [sprd_pmic_wdt]
    [   13.490350] sprd pmic wdt:pmic_timeout 300,feed 250
    [   13.501574] probe of 64400000.spi:pmic@0:watchdog@40 returned 0

pmic_timeout 300 -- a 300 second timeout, matching the ~295 s observed -- and Android
binds that same driver to that same device
(64400000.spi:pmic@0:watchdog@40 under /sys/bus/platform/drivers/sprd-pmic-wdt), which
is why Android survives an armed PMIC watchdog and Linux did not.  Our initramfs had
sprd_pmic_wdt.ko built (out_linux/drivers/watchdog/sprd_pmic_wdt.ko) but never listed
in boot/module-order.txt, so nothing ever loaded it and nothing fed the watchdog LK
had armed.

The fix is that one entry in boot/module-order.extra, and the result is visible
directly:

    before:  session dead at 295 s, every boot
    after:   uptime 10 min and still running, Plasma Mobile up (load average ~8)

### 9.1 What it was not

* **Not a panic or an oops.**  Nothing reaches ttyGS0 (a kernel console), pstore stays
  empty, and LK reports a reset rather than a power-off.
* **Not the harness or this session's tooling.**  The 295 s figure came from a boot
  with the host doing nothing; the 300 s cap on a host tool call only kills the shell
  on the *host*.
* **Not the initramfs safety timer.**  It sleeps 600 s and is stopped before
  switch_root (a session records stage=switch-root-jobs-killed persist=189 timer=190);
  firing would log stage=timer-reboot first.
* **Not the SoC watchdog driver.**  sprd_wdt_fiq does probe (641e0000.watchdog), but
  reading its registers through /dev/mem shows CTRL = 0x4 -- the counter-enable bit is
  clear, so it was never counting -- and disarming it explicitly changed nothing: the
  session still died at 295 s.  boot/init now only *logs* those registers, as a
  diagnostic, and CONFIG_DEVMEM=y (kernel/e5-linux.fragment) stays for that.
* **Not the PMIC monitor register LK prints.**  ANA_REG_GLB_WDG_RST_MONITOR reads 0x0
  after the reset; that register tracks a different watchdog state than the PMIC
  watchdog driver's own timeout.

## 10. Building the kernel on macOS with clang

The kernel does build on a macOS arm64 host with Homebrew's LLVM, and the result is
loadable on the device: the modules built this way carry the same vermagic as the
ones in the running kernel
(5.15.211-g94401422a7df SMP preempt mod_unload modversions aarch64) and the same
module_layout CRC (0x78fb914d), which is what makes "build the modules only, keep the
flashed kernel" work.

What macOS lacks is the Linux tooling *around* the compiler.  Each gap is a host-side
workaround; the kernel tree is never modified, so setlocalversion still yields
5.15.211-g94401422a7df (no -dirty suffix):

| gap | workaround |
|---|---|
| /usr/bin/make is GNU 3.81, the build wants 3.82+ | brew install make -> work/bin/make -> gmake 4.4 |
| BSD sed -i and cp -T in merge_config.sh | brew install gnu-sed coreutils, their gnubin dirs first in PATH |
| no <elf.h> | glibc's elf.h in work/hostinc/ (this tree's modpost has its own ELF parser and needs only the header) |
| no <asm/types.h> for host tools (Linux hosts get it from linux-libc-dev) | work/hostinc/asm/* -> symlinks to the kernel's include/uapi/asm-generic/* |
| Darwin declares uuid_t (sys/unistd.h -> sys/_types/_uuid_t.h, used by gethostuuid.h) which collides with the uuid_t in scripts/mod/file2alias.c | both SDK headers stubbed in work/hostinc/ |
| no depmod (kmod is Linux-only) | boot/gen-modules-dep.py: depmod's rule, derived from Module.symvers plus each module's undefined symbols; boot/stage-modules.sh uses it when depmod is missing |

The last one reproduces depmod's answer rather than approximating it -- both find
sprd-drm.ko -> ocp2131.ko, sprd-gsp.ko, and the WCN entry comes out as
sprd_wlan_combo.ko -> wcn_bsp.ko, sipc-core.ko, cfg80211.ko.  CONFIG_DEBUG_INFO and
DEBUG_INFO_BTF are already off in kernel/e5-linux.fragment (so no pahole is needed)
and arm64 needs no objtool.  The exact environment is recorded in work/build6.sh;
a full Image + modules build takes about twenty minutes on an M-series host with -j8.


## 11. What the phone session costs, and what to run instead

Measured on the device (`free -m`, `ps -eo rss,pcpu,comm`), Plasma Mobile 6.3.6 on
llvmpipe with 36 running user units:

| | total | used | free | buff/cache | available | zram |
|---|---|---|---|---|---|---|
| before | 1450 | 1288 | 93 | 387 | 162 | 719 / 767 used |
| after trimming | 1450 | 926 | 354 | 394 | 524 | 590 / 767 used |

The single largest item was not the shell.  `plasma-settings` -- the phone settings
app -- was running as an XDG autostart unit
(`app-org.kde.mobile.plasmasettings@....service`) and held **356 MB**.  Behind it:
plasmashell 228, maliit-keyboard 93, kwin_wayland 62, kded6 45, xwaylandvideobridge
40, powerdevil 38, Discover's notifier 36, kdeconnectd 36, xdg-desktop-portal 36, the
polkit agent 34, kactivitymanagerd 33, gmenudbusmenuproxy 32, xembedsniproxy 32,
ksmserver 32.  (RSS double-counts shared Qt libraries, but the ranking is what
matters.)  zram was 94 % full, so the session was also paying compression CPU for
every page fault -- which is the real symptom: not the number, the thrashing.

What was turned off (live, and therefore already inside the rootfs image, whose
loop file is the persistent root):

| change | how |
|---|---|
| settings app, Discover notifier, KDE Connect | `home/e5/.config/autostart/*.desktop` with `Hidden=true`, carried in the overlay so it survives a re-image |
| gmenudbusmenuproxy, xembedsniproxy, xwaylandvideobridge, kaccess | `systemctl --user mask` -- X11-only helpers on a Wayland phone; the instance already running was killed by pid |

That is ~360 MB released, and more usefully `available` 162 -> 524 MB.  What is left
is the shell itself: plasmashell 254 MB and kwin_wayland 87 MB, with plasmashell at
39 % CPU.  On llvmpipe every Qt Quick frame is rasterised on the CPU, and no Mesa
driver exists for this GPU; the DRM work in section 8 is unrelated to that (the panel
is a plain DSI framebuffer driven through DRM planes).

Lighter shells, all present in trixie for arm64 (checked against
packages.debian.org/trixie/arm64):

| option | shape | note |
|---|---|---|
| Phosh (`phosh`, `phoc`, `squeekboard`) | GTK4 shell + wlroots compositor | the phone stack Debian itself ships for mobile; no KDE/Qt daemon fleet, and phoc can run with `WLR_RENDERER=pixman` |
| Sxmo (`sxmo-utils`) | sway + dmenu-style menus and gestures | smallest sensible phone UX, but a menu-first interaction that has to be learned |
| sway + `wvkbd` + `waybar` | hand-rolled | ~120-200 MB and full control, at the cost of assembling the UX |
| cage / labwc / weston | kiosk or bare wlroots | single-app or bare desktop; useful as a cheap renderer test |
| LXQt (`lxqt-session`) | Qt desktop | lighter than Plasma, but not a touch UI |

The renderer matters more than the shell on this board: every wlroots compositor
(phoc, sway, labwc, cage) runs without GL under `WLR_RENDERER=pixman`, so a
GTK4/wlroots stack is the natural next step -- which is why `docs/STATUS.md` keeps
Plasma Mobile as the fallback rather than the target.

Getting there: the device has no route off itself except the USB LAN, the host does.
For a handful of packages, fetch the arm64 `.deb`s on the host and `dpkg -i` them on
the device (it is aarch64, so the unpack and the maintainer scripts are native).  For
a stack like Phosh (100+ packages) let apt resolve instead: run a small HTTP proxy on
the host, point the device at it with `Acquire::http::Proxy` in
`/etc/apt/apt.conf.d/`, and the dependency walk stays on the device where it is
correct.

zram itself was 768 MB of lzo-rle and 94 % full.  It is now 4 GiB of zstd
(`E5_ZRAM_SIZE` / `E5_ZRAM_COMP` in `rootfs/overlay/usr/local/sbin/e5-zram`), with
`vm.swappiness=100` and `vm.page-cluster=0`
(`rootfs/overlay/etc/sysctl.d/10-e5-zram.conf`): swapping earlier costs less than
letting the anonymous set grow until the session has to reclaim synchronously, and one
page at a time is the cheap case for a random-access device.  4 GiB is an overcommit on
a 1.45 GiB machine and that is fine -- only the *compressed* pages occupy RAM, so what
matters is the ratio (zstd has lz4/zstd selected as active: `[zstd]` in
`/sys/block/zram0/comp_algorithm`), not the nominal size.

## 12. The 9-key keypad: a driver that was never staged

The board is a 5G feature phone, so most of its input is a numeric keypad plus a
back key, not the touch panel.  The keypad is a plain matrix keypad on the SoC's AON
keypad controller, and it is in the running device tree:

    /proc/device-tree/soc/aon/keypad@641B0000
      compatible = "sprd,sc9860-keypad", status = "okay"
      keypad,num-rows / keypad,num-columns / debounce-interval / linux,keymap

and the platform device exists (`641b0000.keypad`).  Nothing was bound to it, and
nothing said so: no dmesg line, no failed probe, no input device.  `waiting_for_supplier`
on the device is stale -- the AON clock gate it waits for probed normally
(`ums9621-clk 64900000.aonapb-gate: clock probe`, and the consumer devlink
`platform:64900000.aonapb-gate--platform:641b0000.keypad` is there).  The reason is the
same one that hid the charger, the display power domain and the WCN drivers:

    CONFIG_KEYBOARD_SPRD=m

and `sprd_keypad.ko` is not in Android's first-stage module list, so neither the
initramfs nor the Debian root filesystem ever loads it.  An unbound platform device is
invisible; loading the driver is what makes it appear.

The fix is two modules, built from the same tree and configuration as the flashed
kernel (section 10's `LLVM=1` invocation, `make M=drivers/input/keyboard modules`),
plus its dependency:

| module | config | why |
|---|---|---|
| `sprd_keypad.ko` | `CONFIG_KEYBOARD_SPRD=m` | the matrix keypad driver |
| `matrix-keymap.ko` | `CONFIG_INPUT_MATRIXKMAP=m` | `depends=matrix-keymap`, parses `linux,keymap` |

`vermagic=5.15.211-g94401422a7df SMP preempt mod_unload modversions aarch64` and the
module CRCs match the flashed kernel, so no kernel change and no reflash are needed.
After `insmod` on the running system, /proc/bus/input/devices goes from two devices to
three:

    N: Name="sprd-keypad"   H: Handlers=kbd event2   B: KEY=...ffc (KEY_1..KEY_9, KEY_0, * #)

The two devices that were already there are worth restating: `gpio-keys` (input0) holds
**the power and volume keys** -- its KEY bitmap decodes to KEY_VOLUMEDOWN, KEY_VOLUMEUP
and KEY_POWER -- and `tlsc6x_touch` is input1.  So the physical keys were always
generating events; what was missing was (a) the keypad driver and (b) anything in the
session that acts on KEY_POWER, which logind was told to ignore (section 6.2).

Persistence is in two places:

* the running rootfs -- `matrix-keymap.ko` and `sprd_keypad.ko` under
  `/lib/modules/$(uname -r)/kernel/drivers/input/`, `depmod -a`, and
  `/etc/modules-load.d/e5-keypad.conf`, so systemd's modules-load stage insmods them
  early on every boot (verified: both listed in `lsmod` after
  `systemctl restart systemd-modules-load`);
* the boot image -- both names are in `boot/module-order.extra`, and
  `boot/stage-modules.sh` picks up every `.ko` in `out_linux`, so a rebuilt
  `boot-linux-slotb.img` carries 66 modules instead of 64 and loads them in
  dependency order (`matrix-keymap.ko` before `sprd_keypad.ko`).

## 13. Baseband internet: Android's modem_control in a chroot

The vendor kernel already carries the whole SIPC/SIPA modem stack: the modules are
loaded (`sipc_core`, `sipa_core`, `sipa_eth`, `sipa_usb`, `sprd_modem_loader`, `sipx`,
`spool`, `spipe`, `unisoc_mailbox`, `trusty_log`, ...), the char devices exist --
`/dev/modem` is char 481 and the AT channels are `/dev/stty_nr0..31`, char 489, as
`/proc/devices` confirms -- and `/sys/class/` has `sipa`, `sipa_eth`, `sprd-sipc`,
`sprd-sipx`, `ext_modem`.  Every one of those channels still fails with ENODEV,
because that is only the *transport*: the CP (baseband) firmware has never been
started.

### Who has to start it, and why it is Android's job

`sprd_modem_loader` (`drivers/unisoc_platform/modem/modem_loader/sprd_modem_loader.c`)
is a char device with `MODEM_START`/`MODEM_STOP`/`MODEM_GET_LOAD_INFO`/... ioctls, and
its ioctl path compares the *calling task's name*:

    if (strcmp(current->comm, modem->rd_lock_name) != 0) { ... return -EPERM; }

so the loader only serves a task literally called `modem_control`.  That is Android's
`/vendor/bin/modem_control`, and it needs more than the binary: bionic (it is an
Android ELF), the property area (it reads `ro.vendor.radio.modemtype` to learn the
modem configuration) and `libkernelbootcp.trusty.so` (it reloads `pm_sys` and the
modem through the Trusty `kernelbootcp` TA).  The E5 therefore gets the same
treatment as the MU300 port: extract the Android vendor subset and run
`modem_control` in a chroot.

### Getting the subset out of a production Android

`rootfs/extract-android-vendor.sh` does it, and the trick is that the E5's Android is
a *production* build: `ro.build.type=user`, `ro.debuggable=0`, no `su` anywhere in
PATH and `adb root` answers "adbd cannot run as root in production builds".  What
saves it is Magisk -- `/debug_ramdisk/su -c id` returns `uid=0(root)` -- which is
what the flashing scripts have been using all along.

49 MiB comes out: `/apex/com.android.runtime` (linker64 + bionic), `/system/lib64`,
`/vendor/bin/{modem_control,cp_diskserver,refnotify}` with their vendor libs, the
`/vendor/etc/modem_*.xml` files `modem_control` parses, `vendor/etc/ueventd.rc`, and
the one thing no partition has: the *live* `/dev/__properties__` area (1.4 MiB of
tmpfs that Android's init builds at boot).

### Four requirements, each discovered by failure

| symptom | cause | fix |
|---|---|---|
| `modem_ctrl_int_modem_type: ro.vendor.radio.modemtype not_find`, then `can't get modem type!`, and nothing else happens | the subset was unpacked from a tarball built on macOS, so `property_info` was owned by uid 501.  bionic's `PropertyInfoAreaFile::LoadPath()` returns false unless `st_uid == 0 && st_gid == 0`, and one false there leaves the *entire* property system uninitialised -- `getprop` then prints nothing at all | `chown -R root:root` in `vendor-start.sh` |
| `modem_control` sleeps in a nanosleep loop and never opens a device | liblog retries `connect(/dev/socket/logdw)` forever; there is no logd on Linux | `logdw.py`: a 40-line Python `SOCK_DGRAM` sink bound at `/dev/socket/logdw` |
| the modem loader still refuses | `modem_control` drops to uid `system` (1000), while devtmpfs hands every node over as `root:root` 0660, and `/dev/block/by-name` does not exist at all | `node-perms.sh` applies Android's own `/vendor/etc/ueventd.rc` (path, mode, user, group) to the nodes that exist, and the by-name links are rebuilt from each partition's `PARTNAME` |
| nothing boots even so | the driver checks the task name | `exec chroot .../android /vendor/bin/modem_control` -- directly, never through `linker64` -- with a bind-mounted copy of `/proc/cmdline` whose `androidboot.slot_suffix` is forced to `_a` (LK passes `_b` for the trial slot, and the `_a` images are the ones Android itself uses) |

With those in place the modem log (through the logdw sink) goes `Modem Alive` /
`CH Alive`, dmesg prints `modem modem@0: modem_control modem run = 1!`, and
`/dev/stty_nr1` stops returning ENODEV and starts blocking on read, which is what an
AT channel is supposed to do.

### The data path: AT on /dev/stty_nr1, data on sipa_eth0

`rootfs/overlay/opt/e5/mobile-data` implements up/down/status/watch/sim-reset with
nothing but shell and the AT channel:

    AT+SFUN=2                        SIM on
    AT+SFUN=4                        protocol stack on;  +CFUN: 0 becomes +CFUN: 1
    AT+CEREG?                        +CEREG: 2,1,"5104","059FA02D",7   (LTE registered)
    AT+COPS?                         46001 (China Unicom), CSQ 52
    AT+CGDCONT=1,"IPV4V6","3gnet"   APN from /etc/e5/mobile-data.conf
    AT+CGACT=1,1                     activate the default bearer
    AT+CGCONTRDP=1                   3gnet.MNC006.MCC460.GPRS,
                                     10.105.136.142/255.0.0.0,
                                     DNS 58.240.57.33 and 221.6.4.66
    AT+CGDATA="M-ETHER",1            -> CONNECT: the bearer lands on sipa_eth0

then `ip link set sipa_eth0 up`, `ip addr add <address>/<prefix from the mask>`
(`sipa_eth0` is raw IP and NOARP), `ip route replace default dev sipa_eth0`, and
`/etc/resolv.conf` gets the two DNS servers (`resolvectl` is not installed on this
image).

Verified on the device: `busybox wget http://deb.debian.org/debian/dists/trixie/Release`
returns the real index (`Origin: Debian`, `Suite: stable`, `Version: 13.7`) with the
USB LAN having no route to the internet -- the traffic left through the baseband.  The
carrier also assigns a `2408:893a:...` IPv6 address; there is no IPv6 default route
configured yet.

Three units carry it: `e5-vendor.service` (`Before=sysinit.target`, runs
`vendor-start.sh`, and `ConditionPathExists=/opt/e5/android/vendor/bin/modem_control`
so a fresh image without the proprietary subset still boots), `e5-mobile-data.service`
(oneshot, `mobile-data up`) and `e5-mobile-data-watch.service` (`mobile-data watch`,
which rebuilds the bearer when a modem reset drops it).  Checked across a reboot:
all three `active`, `sipa_eth0` UP with a fresh address, wget works.

The subset is proprietary and is not in this repository (`work/` is gitignored);
`rootfs/extract-android-vendor.sh` reproduces it from the device, and the overlay
carries everything else.

## 14. 5G NR: what the device does, and what the network is not offering

The modem is the NR variant, and that is visible in three independent places:
`modem_control` logs `modem type is nr` and loads `nr_modem`/`nr_phy`/`nr_fixnv`/
`nr_runtimenv`; Android's property area (which we copy) carries
`ro.vendor.radio.modemtype=nr`; and `AT+SPRAT?` answers `+SPRAT: LTE 16` -- the
camped RAT, not the capability.  That command is read-only on every AT channel this
image exposes (`AT+SPRAT=<n>` is always `+CME ERROR: 4`), and
`NSACFG`/`SNRCFG`/`SBAND`/`MODE`/`SYSMODE`/`E5GOPT`/`WS46` do not exist at all, so
nothing user-space can flip the RAT over AT.

The same SIM in the same spot on Android (fully booted, China Unicom 46001, LTE band 1,
RSRP -90):

    gsm.network.type=LTE,Unknown
    getRilDataRadioTechnology=14(LTE)
    mCellInfo=[CellInfoLte{... mEarfcn=100 mBands=[1] ...}, CellInfoLte{...}, CellInfoLte{...}]
    CellSignalStrengthLte ... CellConfigLte :{ isEndcAvailable = false }

No `CellInfoNr` anywhere, and `isEndcAvailable=false`: at that location the network
offers neither NR SA nor EN-DC, so there is nothing for the modem to camp on.  Android's
own configuration is 5G-ready (`ro.telephony.default_network=26`, i.e.
NR_LTE_TDSCDMA_GSM, and `persist.radio.is_vonr_enabled_0=true`), which is the point: the
Linux side is not missing a switch that would light up 5G here.

What *was* wrong on the Linux side is which slot's modem images get loaded.
`modem_control` takes the slot from the bootloader's slot suffix, and LK spells it
`sprdboot.slot_suffix=_b` -- not `androidboot.slot_suffix`, which is what the MU300
recipe rewrites.  A slot-b Linux trial therefore booted slot b's firmware and NV
(`nr_phy_b`, `nr_fixnv1_b`, `nr_deltanv_b`).  Android runs from slot a, and slot a is
where its RIL configured the modem, so `vendor-start.sh` now rewrites the suffix to `_a`
and, belt and braces, points the `_b` device names at the `_a` partitions.
`/etc/e5/modem-slot` containing `current` opts out.  Whatever Android achieves with NR
(its RIL writes modem NV through `cp_diskserver`) is then the configuration Linux boots
with.

To re-check after the network or the SIM changes, on either system:

* Linux: `mobile-data status` prints `+CEREG: ...` with the AcT decoded --
  `LTE`, `NR (5G SA)` (11) or `LTE+NR (EN-DC/NSA)` (13) -- plus the raw `+SPRAT?`.
* Android: `getprop gsm.network.type` and
  `dumpsys telephony.registry | grep -E 'CellInfoNr|accessNetworkTechnology'`.

### Confirmed: NR SA runs on the Linux side

After the user restarted the baseband from Android and locked it to band n78, Android
reported:

    gsm.network.type=NR_SA
    accessNetworkTechnology=NR
    CellInfoNr ... mRegistered=YES mCellConnectionStatus=1
                 mNrArfcn=627264 mBands=[78] mNrFrequencyRange=3 ssRsrp=-100
    gsm.version.baseband=5G_MODEM_V2_23B_W24.16.1_P1|ums9621_modem
    persist.vendor.modem.nr.enable=1

and after rebooting into Linux the same modem -- booting the slot-a images and NV, per
the remap above -- camped the same way with no further configuration:

    +CEREG: 2,1,"DE0400","005BE001",11      AcT 11 = NR SA
    +COPS: 0,2,"46001",11                    China Unicom, NR
    +SPRAT: LTE 32                            (the numeric field moved 16 -> 32
                                               together with the camped RAT; the name
                                               token stays "LTE", so do not trust it)
    sipa_eth0 UP 10.131.171.189/8             bearer built on the NR link
    busybox wget http://mirror.nju.edu.cn/... 9.6 MB in 1.5 s (~50 Mbit/s)

So the RAT preference lives in the modem NV, written there by Android's RIL, and the
Linux port inherits it as long as it boots slot a's modem firmware and NV.  There is no
AT-side switch to set it (and none is missing): `mobile-data status` now decodes the AcT
so the camped RAT is visible at a glance -- `LTE`, `NR (5G SA)` or `LTE+NR (EN-DC)`.

## 15. Sharing the baseband with the USB LAN (NAT), and why apt uses http

`mobile-data up` now also forwards: `net.ipv4.ip_forward=1` plus an nftables table
(`e5_nat`) with `oifname sipa_eth0 masquerade` and the usual MSS clamp -- this image has
nftables, not iptables, and it had to be installed.

Installing it is where the mirror came in.  The device reaches the internet only through
its own bearer now, and the official `deb.debian.org` index is ~15 MB: apt worked but
crawled, and any **https** fetch hangs (`openssl s_client` to :443 times out at every
MTU from 1500 down to 1200, while :80 is fine), so the sources are the Nanjing
University mirror over **http** (`rootfs/overlay/etc/apt/sources.list.d/debian.sources`)
-- 8 MB/s, which is what made the Phosh install take a minute instead of an hour.

Verification without a second machine: a network namespace with a veth pair
(`10.99.0.2` -> `10.99.0.1` on the E5) exercises forwarding *and* masquerade, because
that source address is not local to the E5.  `busybox wget` from inside the namespace
returns the real Debian `Release` file, so a USB client behind `usb0` gets the same
treatment.  (`ip netns` + `veth` both work in this kernel.)

## 16. Phosh replaces Plasma Mobile as the session

    apt-get install phosh phoc phosh-osk-stub squeekboard foot
    # phosh 0.46.0-3+deb13u1, phoc 0.46.0-1, phosh-osk-stub 0.46.0-1

Phosh's compositor is wlroots, so `/etc/environment` gained `WLR_RENDERER=pixman` --
phoc then never touches GL, which is the point on this board.  SDDM still autologins
`e5`; the session is now `phosh.desktop` and `plasma-mobile.desktop` is untouched, so
switching back is one line.

Three traps, all of them silent:

1. SDDM reads `/etc/sddm.conf` and *then* `/etc/sddm.conf.d/*`, but a value present in
   both is not simply overridden by the drop-in: editing `sddm.conf.d/10-e5.conf` alone
   kept the old session.  The authoritative place turned out to be the main
   `/etc/sddm.conf`.
2. `/var/lib/sddm/state.conf` remembers the *last* session and wins over the
   configuration for autologin (`Session=/usr/share/wayland-sessions/plasma-mobile.desktop`).
   Both files have to agree.
3. Restarting `sddm` does not stop the old session's processes: the Plasma session kept
   running (kscreenlocker_g 173 MB, plasmashell 108 MB, kwin_wayland, kded6, ...)
   alongside phoc.  Only a reboot cleared them -- and the reboot is what proved the
   configuration, so it was the right move anyway.

Measured, same device, same panel, `free -m`:

| session | used | available | notes |
|---|---|---|---|
| Plasma Mobile, after the section 11 trim | 926 | 524 | kwin + plasmashell on llvmpipe |
| Phosh | 723 | 727 | phoc + phosh + phosh-osk-stub, `plasmashell` 0 |

About 200 MB more headroom, and neither session needed the other's daemons: the KDE
helpers stay masked (they are X11-only), and the 240 MB `plasma-settings` process that
showed up in `ps` was phosh launching it *on demand* (its scope says "Application
launched by phosh"), not an autostart leftover -- `systemctl --user unmask` after
checking, so the on-screen Settings button keeps working.

## 17. Removing KDE, and the trap that made the 4 GiB zram keep coming back

With Phosh working, the KDE/Plasma stack was purged (`~n^plasma`, `^kwin`, `^kde`,
`^libkf`, `^kf6`, `^kscreen`, `^maliit`, `^breeze`, `^powerdevil`, `^kactivity`,
`^polkit-kde`, `^ksmserver`, `^systemsettings`, `^kglobalaccel`, `^kio`, then
`apt-get autoremove --purge`).  `/` went from 4.6 GiB used (962 MiB free) to **4.0 GiB
used / 1.6 GiB free**, `plasmashell` is gone, and `/usr/share/wayland-sessions/` now
holds exactly `phosh.desktop`.

Measured on the same rootfs, same panel, `free -m`, three minutes after boot:

| session | used | available | zram used | biggest process |
|---|---|---|---|---|
| Plasma Mobile as found | 1288 | 162 | 719 MB | plasma-settings 356 MB |
| Plasma Mobile, after the section 11 trim | 926 | 524 | 590 MB | plasmashell 254 MB |
| Plasma Mobile, second measurement (section 16, before the purge) | 1032 | 418 | 120 MB | plasmashell 368 MB / 56 % CPU |
| Phosh, before the purge | 732 | 718 | 1 MB | phosh 75 MB, phoc 19 % CPU |
| **Phosh, KDE purged** | **707** | **743** | 6.5 MB | phosh 71 MB, phoc 10.5 % CPU |

So Phosh costs about 325 MB less than the same-rootfs Plasma Mobile, and its
compositor burns about half the CPU (both are software-rendered: `WLR_RENDERER=pixman`
for phoc, llvmpipe for kwin).

### The trap: the initramfs overlay is copied over the rootfs on *every* boot

The 4 GiB zram kept reverting to 768 MB after each reboot, and the reason is structural:
`boot-linux-slotb.img` carries a 25-file overlay that `boot/init` copies into `/newroot`
on every boot, and `/usr/local/sbin/e5-zram` is one of those files.  Editing the rootfs
copy therefore lasts exactly until the next boot -- and the same is true of every path
the overlay mentions (`etc/environment`, `etc/sddm.conf.d/*`, `etc/systemd/system/*`,
the firmware files, ...).  Two ways out, and both are used here:

* put the setting somewhere the overlay does *not* mention -- the zram size now lives in
  `/etc/systemd/system/e5-zram.service.d/10-e5-4g.conf` (a drop-in directory, not a file
  in the overlay), which sets `E5_ZRAM_SIZE=4G` and resets zram0 to zstd before the
  stock script runs;
* or reflash the rebuilt image, which is what `boot-linux-slotb.img` (66 modules, 26
  overlay files including all of the above) is for.

### The power button

Two independent pieces are in play, and only one of them was wrong:

* logind must not touch the key, or the device powers off the moment it is pressed --
  `HandlePowerKey=ignore` / `HandlePowerKeyLongPress=ignore` were already in place
  (section 6.2);
* `gnome-settings-daemon`'s `power-button-action` was `suspend`, and this device has no
  working suspend, so pressing the key did nothing visible.  It is now `nothing`, which
  leaves the key to phosh itself (short press locks/unlocks, long press opens the power
  menu).  Confirming that with a real press is the one open item.

## 18. The power key: the kernel was fine, the session was not

Pressing every key on the device while both `gpio-keys` (event0) and the keypad
(event2) were being logged shows the whole input path works:

| evidence | value |
|---|---|
| `gpio-49` ("Power Key") level samples | 9 of 380 at `lo` -- i.e. it really changes |
| `gpio-52` ("Volume Up Key") | 3 samples at `hi` (idle `lo`) |
| `gpio-191` ("Volume Down Key") | 4 samples at `lo` |
| events on event0 | `KEY_POWER` (116) 12x, `KEY_VOLUMEDOWN` (114) 6x, `KEY_VOLUMEUP` (115) 8x, `KEY_F1` (59) 6x |

and `/sys/kernel/debug/gpio` shows the lines claimed by the driver with interrupts
(`gpio-49 | Power Key | in hi IRQ ACTIVE LOW`, `gpio-52 | Volume Up Key | in lo IRQ`,
`gpio-191 | Volume Down Key | in hi IRQ ACTIVE LOW`), all four marked `wakeup-source` in
the DT.

### Why nothing happened anyway

1. logind must ignore the key, or a press powers the device off -- `HandlePowerKey=ignore`
   (section 6.2).
2. phosh does not act on `KEY_POWER` itself.
3. `gnome-settings-daemon`'s `power-button-action` was `suspend`, and **suspend does not
   work on this board**: `rtcwake -m mem -s 15` returns 0, but the kernel log shows
   `sipa 25220000.sipa: thread prepare suspend err` on every attempt -- the modem's data
   path refuses to suspend, so the PM core aborts and resumes immediately.
4. With gsd set to `nothing` instead (to stop the failing suspends) *nobody* handled the
   key -- which is the state the user found: gsd's 300 s idle blank had turned the panel
   off (`bl_power=4`) and no key could turn it back on.

### What runs now

`e5-powerkey.service` (`/opt/e5/powerkey.py`, 60 lines of Python) reads
`/dev/input/event0` and gives the key phone semantics without suspend:

* short `KEY_POWER` -> panel off (`bl_power=1`) + `loginctl lock-sessions`;
* any other key, or a touch on event1 -> panel on (`bl_power=0`).

alongside two settings: a logind drop-in `HandlePowerKey=lock` (for sessions that do
implement logind locking) and `sleep-inactive-ac-type=nothing` so gsd stops trying to
suspend every idle period.  The panel is `sprd_backlight`, whose `bl_power` and
`brightness` were already opened to the session in `boot/init`.
