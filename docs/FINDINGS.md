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

