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

**Correction (2026-09-18): the partition path is a fallback, and it is not what was
wrong.**  `wcn_boot.c` tries the firmware loader first:

```c
    if (marlin_dev->is_btwf_in_sysfs) {
        err = marlin_download_from_partition();
        return err;
    }
    pr_info("marlin %s from /system/etc/firmware/ start!\\n", __func__);
    err = request_firmware(&firmware, "wcnmodem.bin", NULL);
    if (err < 0) {
        pr_err("no find wcnmodem.bin errno:(%d)(ignore!!)\\n", err);
        marlin_dev->is_btwf_in_sysfs = true;
        err = marlin_download_from_partition();
        return err;
    }
```

`marlin_download_from_partition()` is the `/dev/block/by-name/wcnmodem` path; it only
runs once `request_firmware()` has already failed.  The `from /system/etc/firmware/`
line is a hardcoded string naming a directory that does not exist in this root
filesystem at all, which is what made the log look like a partition read.

On the live system `dmesg` shows

    WCN BASEmarlin btwifi_download_firmware from /system/etc/firmware/ start!
    WCN BASEmarlin btwifi_download_firmware successfully!

with **no** `no find wcnmodem.bin` line anywhere, and

    WCN BASEgnss_download_firmware successfully through request_firmware!

for the GNSS half.  So the real requirement is the one section 8.1 already states --
`wcnmodem.bin` present in `/lib/firmware` -- and the loop device was never necessary.
The chip comes up because the initramfs overlay materialises the firmware before the
module pass.

### 8.4 What to look at when it is tried

    dmesg | grep -iE "wcn|wlan|sdio"      # probe, firmware load, chip boot
    lsmod | grep -E "wcn_bsp|sprd_wlan_combo"
    ip link                               # wlan0 should appear
    cat /sys/class/net/wlan0/address      # factory MAC, or random if unset

### 8.5 The chip boots now -- and the driver kills it 20 s later

Everything above was measured before the kernel could boot the chip's *GNSS* half,
which is fatal and silent: the WCN core downloads BT/Wi-Fi firmware first, then
GNSS, and only then comes up.

**The trap: the GNSS half has no filesystem wait.**  `gnss_download_firmware()`
calls `request_firmware("gnssmodem.bin")` **once** and treats `-ENOENT` as a
fallback trigger:

```c
	if (marlin_dev->is_gnss_in_sysfs) {
		err = gnss_download_from_partition();
		return err;
	}
	err = request_firmware(&firmware, "gnssmodem.bin", NULL);
	if (err < 0) {
		pr_err("%s no find gnssmodem.bin err:%d(ignore)\n", __func__, err);
		marlin_dev->is_gnss_in_sysfs = true;      /* sticky, for the whole boot */
		err = gnss_download_from_partition();
```

`gnss_download_from_partition()` reads the DT's `sprd,gnss-file-name`
(`/vendor/firmware/gnssmodem.bin`), which does not exist in this rootfs, so it
returns NULL -- and the `is_gnss_in_sysfs` flag stays set, so every later retry
skips the firmware loader entirely.  Measured (modules loading from the
initramfs, where `/lib/firmware` does not exist yet):

    [15.621] gnss_download_firmware start from /system/etc/firmware/
    [15.629] (NULL device *): Direct firmware load for gnssmodem.bin failed with error -2
    [15.655] gnss_download_from_partition gnss buff is NULL
    [25.823] GNSS download timeout
    [38.4  ] marlin chip en pull down ... sprd-wlan: failed to power on WCN!
    [38.4  ] probe of sprd-marlin3:wlan returned 19 after 12534326 usecs

The BT/Wi-Fi half does not have this problem because
`marlin_download_from_partition()`/`btwifi_download_firmware()` waits up to 80 s
for a filesystem ("keep waiting for file system ready"), which is why Wi-Fi used
to come up in some sessions and GNSS never did.  The fix is the one
`rootfs/pull-wcn-firmware.sh` was written for: the firmware has to be in the
initramfs's *early* overlay, not just in the root filesystem, so that
`/lib/firmware` exists before the module pass (`boot/init` materialises
`e5-overlay/lib/` first).  With `wcnmodem.bin`, `gnssmodem.bin` and
`wifi_board_config*.ini` in `rootfs/overlay/lib/firmware/`:

    [1.766] E5-LINUX: stage=overlay-early files=45 firmware=6
    [13.907] gnss_download_firmware successfully through request_firmware!
    [16.516] marlin btwifi_download_firmware successfully!
    [17.214] sprd-wlan: sprd_wlan_probe sprd,sc2355-sdio-wifi 2.
    [17.343] sprd-wlan: sprd_iface_set_power Power on WCN (0 time)

and `phy0` + `wlan0` + `p2p-dev-wlan0` appear, with both rfkill switches
unblocked.  Bluetooth gets further too: `sprdbt_tty.ko` (in
`boot/module-order.extra`, it was never in the stock first-stage list either)
brings up `/dev/ttyBT0` plus a bt rfkill, and `btattach -B /dev/ttyBT0 -S
3000000` does create `hci0` (`Bus: UART`) -- bluez is installed and
`bluetooth.service` is already running.

**The blocker: the driver's own hang detector dumps the card.**  20 seconds
after the chip comes up, `loopcheck` (an `AT+loopcheck` ping the driver runs to
detect a stuck WCN core) decides the chip is dead and sets the SDIO card's dump
flag, after which **every** power-on is refused:

    [28.574] WCN BASE: start_loopcheck
    [30.6]   rx:loopcheck_ack:ap_send=30591,cp2_bootup=28055,cp2_send=30613   <- chip answers
    [34.758] WCN SDIO: carddump flag set[1]
    [38.507] WCN BASEstop_marlin SDIO card dump
    [38.627] WCN BASEstart_marlin [MARLIN_WIFI] ... start_marlin SDIO card dump
    [62.661] WCN BASEstart_marlin [MARLIN_BLUETOOTH] ... start_marlin SDIO card dump

`start_marlin()` (wcn_boot.c) refuses when `get_loopcheck_status() >= 2`, so the
symptoms downstream are exactly what was reported -- Wi-Fi present but every
scan `-EIO` with `sc2355_send_cmd_recv_rsp CP2 assert` (`hif->cp_asserted` is set
by the reset notifier the dump triggers), and Bluetooth's `mtty_open power on
state ret = -1!` / `sprdwcn_bus_push_list failed: -19`:

    $ sudo iw dev wlan0 scan
    command failed: Input/output error (-5)
    $ sudo hciconfig -a
    hci0: Type: Primary  Bus: UART   BD Address: 00:00:00:00:00:00   DOWN INIT RUNNING

That is the state to pick up from: the chip is alive and both transports exist,
so what is left is either to work out why `loopcheck` trips (its first round
succeeds, the later ones apparently do not -- `loopcheck.o` in `wcn_bsp`, and
`get_loopcheck_status()` at `boot/wcn_integrate_boot.c:3596`) or to stop it from
condemning a working card (`sdiohal_main.c:762`,
`sdiohal_set_carddump_status()`).

Two smaller facts worth keeping: the vendor's board-level WCN set for this exact
board (UM9621_1h10) is in `connconfig/marlin3_lite/ums9621_1h10/` -- and it
contains `bt_configure_pskey*.ini`, `bt_configure_rf*.ini` and
`fm_board_config*.ini`, which the *device* does not carry (the earlier pull only
took `wifi_board_config*.ini` and the two MACs; nothing in the kernel reads the
`bt_configure_*` files, so they are for a userspace BT HAL rather than for
`btattach`).  And `wcn_wifi_driver.conf`, whose absence fills a line in dmesg,
is optional tuning: `sprd_parse_wifi_driver_config()` returns silently when the
file is missing.

### 8.6 Solved: the driver was built as the "userdebug" variant

The card dump in 8.5 is not a hang.  It is a compile-time policy, and this
repository was building the wrong one.

Android's Kbuild picks part of this driver's behaviour from its build variant:

    ifeq ($(TARGET_BUILD_VARIANT),user)
    ccflags-y += -DFLAG_WCN_USER
    endif

and a hand-run `make` sets no `TARGET_BUILD_VARIANT`, so `FLAG_WCN_USER` was
never defined and the driver took every `#else` branch.  One of them is the
assert policy:

```c
#ifdef FLAG_WCN_USER
	atomic_set(&sysfs_info.is_reset, 0x1);      /* WCN_ASSERT_ONLY_RESET */
#else
	atomic_set(&sysfs_info.is_reset, 0x0);      /* WCN_ASSERT_ONLY_DUMP  */
#endif
```

`__wcn_assert_interface()` reads that value and then either dumps the chip's
memory and leaves the SDIO card dead, or resets the chip and carries on.  Since
the loopcheck treats one missed `at+loopcheck` round (4 s to answer) as an
assert, the userdebug default turns a single late answer into a radio that is
dead for the rest of the boot.  The same `#ifdef` also adds a reset-pad priority
write for qogirl6 in `btwf_sys_poweron()` -- the user variant is not just the
policy.

It is settable at runtime, which is how it was pinned down: the whole
difference is one sysfs write.

    $ cat /sys/class/misc/wcn/devices/reset_dump          # dump   (before)
    $ echo reset > /sys/class/misc/wcn/devices/reset_dump # switch to the user policy
    $ echo manual_dump > /sys/class/misc/wcn/devices/reset_dump   # force an assert
    WCN SDIO: carddump flag set[0]            <- cleared
    WCN BASE: wcn_reset_process reset end     <- chip reset, no dump
    $ sudo iw dev wlan0 scan | grep -c SSID:
    18

so the radio came back inside an already-booted device, and `reset_dump`'s
three accepted values (`dump`, `reset`, `reset_dump`) are exactly the three
policies of the `if`/`else` chain above.

The fix is the vendor's own production switch, brought out as a Kconfig symbol so
that the choice is visible and lives in `kernel/e5-linux.fragment` rather than in
a Makefile:

    CONFIG_UNISOC_WCN_BSP_USER_VARIANT=y

Verified on a freshly flashed boot with no sysfs writes of any kind:
`reset_dump` reports `reset`, the loopcheck answers every round, no
`carddump flag set` line appears at all, and Wi-Fi scans 18 APs on both bands on
its own.  Bluetooth gets one step further with it too -- the chip answers the
whole HCI init sequence and `hci0` comes up with a real BD address
(`27:93:31:14:22:11`) and sane ACL/SCO MTUs, where before the policy change its
power-on returned -1.

**What that leaves is a second, unrelated failure**, which the carddump flag had
been hiding the whole time: 8.7.


### 8.7 Bluetooth: one rejected HCI command was all of it

With the carddump trap out of the way the controller initialized completely and
then refused to be powered on, and btmon says why:

    < HCI Command: Write Default Link Policy Settings (0x02|0x000f) plen 2
            Link policy: 0x000f   (Role Switch + Hold + Sniff + Park)
    > HCI Event: Command Complete
          Status: Invalid HCI Command Parameters (0x12)
    Can't init device hci0: Invalid argument (22)

45 commands and their events had crossed `/dev/ttyBT0` before it.  The value comes
from the LMP features the controller itself reported (`lmp_hold_capable()` and
friends) and the command is only sent because `hdev->commands[5] & 0x10` claims
support, so this firmware advertises hold/sniff/park and then refuses to enable
them.  `hci_req_cmd_complete()` turns that status into a request error -- and the
request is the one that brings the controller up, so a controller that answers
`0x12` here can never be powered on, with the controller sitting there fully
initialized.  Android never meets this: Bluedroid does not send this command at
all, so the firmware was never asked.

`kernel/patches/0008` (`3bd2464a8`) makes that one command non-fatal: it warns
(`Bluetooth: hci0: controller rejected the default link policy (0x12)`) and clears
the status, which is exactly how `hci_cc_write_def_link_policy()` already treats
a rejection.  With it, `hciconfig hci0 up` succeeds, bluez reports
`Controller 27:93:31:14:22:11` with `Powered: yes`, and an inquiry lists nearby
devices.

`rootfs/overlay/etc/systemd/system/e5-bt-attach.service` keeps it that way.  It
has to be btattach rather than nothing at all because *opening* `/dev/ttyBT0` is
what powers MARLIN_BLUETOOTH on (`mtty_open` -> `start_marlin`), and the tty has
to stay open for the controller to exist.  The unit is deliberately not ordered
against `bluetooth.service`: bluetoothd hot-plugs the adapter whenever it appears,
and a wedged BT core must not be able to hold up the boot (section 9 is what that
costs).  systemd wants a `*.wants/` *link* to consider a unit enabled, and neither
`boot/build-boot-image.py` nor the overlay staging loop in `boot/init` can carry a
symlink, so `boot/init` makes that one link while it materialises the overlay.

Two things are still open on Bluetooth, and neither is a blocker:

* the BD address is the chip's own default (`27:93:31:14:22:11`), not the factory
  one in `/mnt/vendor/btmac.txt`.  Android's BT HAL writes it with a vendor
  command; bluez 5.82 no longer has `hciconfig hci0 bdaddr` and the kernel's
  `HCISETBDADDR` ioctl is gone as well, so setting it means a small tool driving
  the vendor command, or accepting an address that is stable but wrong (a peer
  that paired with the Android BT stack will not recognise this device).
* pairing and a data transfer have not been exercised -- an inquiry only proves
  the radio, the stack and the HCI transport work.  The one attempt so far (the
  settings app at 14:26, to the peer bluez has in its cache as "Enceka SE",
  `80:04:5F:76:78:0C`) came back
  `org.bluez.Error.ConnectionAttemptFailed: Page Timeout`: the page went out and
  the peer never answered it.  That is what a peer that is off, out of range or
  refusing connections looks like, and it is not evidence either way about
  paging itself -- nothing has been connected successfully yet.

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

### 12.1 The confirm key is KEY_SELECT: what it broke, and the remap that fixes it

The keypad's devicetree keymap (`/proc/device-tree/soc/aon/keypad@641B0000/linux,keymap`,
20 entries of `(row << 24) | (col << 16) | keycode`) decodes to:

| row,col | keycode | name |
|---|---|---|
| 1,0 | 0x161 (353) | **KEY_SELECT** -- the confirm key |
| 0,0 | 0x9e (158) | KEY_BACK |
| 0,4 | 0x20b (523) | KEY_PHONE |
| 0,5 / 0,6 / 1,1 / 1,2 | 0x6a / 0x67 / 0x69 / 0x6c | RIGHT / UP / LEFT / DOWN |
| 3,0 / 3,1 | 0x8b / 0xa9 | KEY_MENU / KEY_NEXT |
| 3,3..3,5, 1,3..1,6, 0,1..0,3 | 2..11 | KEY_1 .. KEY_0 |
| 3,6 | 0x37 | KEY_KPASTERISK |

Nothing in the session handles KEY_SELECT, so on the phosh lock screen the PIN could be
typed but never submitted.  What the lock screen does want was measured by injecting
keys with `tools/key-inject.py`, on a locked session:

    tools/key-inject.py 1 2 3 4 5 6 enter     -> LockedHint stays yes
    tools/key-inject.py 1 2 3 4 5 6 kpenter   -> LockedHint: no    (unlocked)

phosh's lock screen unlocks on **KP_Enter**, not on Return, and the PIN is checked by
PAM -- a wrong one leaves `phosh[..]: pam_unix(phosh:auth): authentication failure`
in the journal (that is how the "123" typed by an earlier test showed up).

The fix is the ordinary one -- a udev/hwdb key remap, applied by udev's `keyboard`
builtin at device-add time, so it is in the kernel's scancode table and costs no
latency at all:

    # rootfs/overlay/etc/udev/hwdb.d/61-e5-keypad.hwdb
    evdev:input:b0000v0000p0000e0000*
     KEYBOARD_KEY_8=kpenter

The subtlety is the *scancode*: it is the matrix scan code, not the keycode the key
produces.  The keypad is a 4x7 matrix, so `row_shift = 3` and the confirm key
(row 1, col 0) is `(1 << 3) | 0 = 8`.  evdev's `EVIOCSKEYCODE` indexes
`input_dev->keycode[]`, whose size is `rows * cols = 28`; an index of 353 (the
keycode) is out of range and comes back `EINVAL` -- which is exactly the mistake that
made an earlier version of this section claim the device "cannot be remapped at all".
It can, and `tools/keycode-query.py` shows it (`--from`/`--to`-style read and write,
with `INPUT_KEYMAP_BY_INDEX`):

    tools/keycode-query.py /dev/input/event2 0x0 0x8 0x9
      0x000 -> 158 (BACK)
      0x008 -> 353 (SELECT)      <- the confirm key
      0x009 -> 105 (LEFT)
    tools/keycode-query.py /dev/input/event2 0x8=96
      set 0x008 -> 96 (KP_ENTER)
    # after udevadm hwdb --test / systemd-hwdb update / udevadm trigger:
      0x008 -> 96 (KP_ENTER)

`systemd-hwdb-update.service` (WantedBy=sysinit.target) recompiles
`/etc/udev/hwdb.bin` at boot when the file is newer, so this survives without an
explicit `systemd-hwdb update`.  A userspace uinput re-emitter was the working plan
before this; it is not needed, and it would have added a process and a second
keyboard device to the session.

**Why the key had to change at all** is worth looking at, because it is not obvious
from the phone: phosh 0.46's lock screen has **no unlock key**.  Its on-screen keypad
is 3x4 with the bottom row `[OSK toggle] [0] [backspace]`, and the lock screen itself
opens on the clock and has to be swiped (or tapped) before the keypad appears:

    lock screen (355x533 at scale 0.9)          after a swipe
    "10:35  Friday, September 18"               "Enter Passcode" + dots + 1..9 0 [keypad] [<-]

So for someone typing on the *physical* keypad there was nothing to press: the PIN
could be typed and never submitted, which is exactly the report ("the confirm key
cannot confirm, the back key cannot go back, there is no unlock button").  With
`KP_ENTER` the confirm key submits, and that is confirmed working on the device.

The back key (scan code 0) was briefly remapped to `BackSpace` with hwdb and then
reverted, because `KEY_BACK` is what the session uses for "back" -- but a keypad-only
phone also has no delete key, so `kernel/patches/0004` makes the *driver* report
BackSpace next to KEY_BACK for that one key.  One key, both jobs, and nothing in
userspace: entries ignore KEY_BACK, navigation ignores BackSpace.  The capability is
visible in the device's key bitmap once the patched module is loaded:

    /proc/bus/input/devices, sprd-keypad:  BACKSPACE(14) yes  KP_ENTER(96) yes  BACK(158) yes

The hwdb rule therefore still carries only `KEYBOARD_KEY_8=kpenter`.  So the two
keys of this section are implemented in two different layers: the confirm key is a
**userspace** udev/hwdb remap of a matrix scan code, the back key is a **kernel**
change in `drivers/input/keyboard/sprd_keypad.c` (committed as `678d2409`, see
section 20.2 for the table of kernel commits).

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

> **The conclusion in the sentence above is wrong**, and so is the "no AT-side
> switch" half of the paragraph that closes this section: the switch is
> `AT+SPLBAND`, a command that search never tried.  Corrected in 14.1 below.

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

### 14.1 The old "no AT-side RAT switch" note, corrected

The last two sentences above are half wrong, and one search is to blame.  The search was
for `AT+SPRAT=<n>`, `NSACFG`, `SNRCFG`, `SBAND`, `MODE`, `SYSMODE`, `E5GOPT` and `WS46`;
all of those really do fail (`AT+SPRAT=<n>` is `+CME ERROR: 4`, the rest do not exist),
and from that the conclusion "nothing user-space can flip the RAT over AT" was drawn.
The commands that do exist were simply never tried:

    AT+SPLBAND=0                        -> +SPLBAND: <49-64>,<33-48>,<17-32>,<1-16>,<65-80>
    AT+SPLBAND=1,0,256,0,5,0            -> OK          (LTE: bands 1, 3 and 41)
    AT+SPLBAND=3                        -> +SPLBAND: <v1>,<0>,<v3>,<super>
    AT+SPLBAND=2,1,0,256,4              -> OK          (NR: n1, n78, n80)
    AT+SPLBAND=1,0,0,0,0,0              -> OK          (LTE: no band lock)
    AT+SPLBAND=2,0,0,0,0                -> OK          (NR: no band lock)
    AT+SPFORCEFRQ=16,6,627264,5         -> OK          (lock to one NR cell)
    AT+SPFORCEFRQ=12,3                  -> +SPFORCEFRQ: 12,3,<freq>,<pci>

`AT+SPLBAND` is the band lock: one bit per band inside its 16-band group on LTE, and
three tables (`value1`, `value3`, and the "super" bands n75/76/80-84/86) on NR.
`AT+SPFORCEFRQ` is the cell lock, with 12 = LTE and 16 = NR as its RAT selector -- the
627264 in the example is the n78 ARFCN from the NR SA measurement above.  The same source
settled the neighbours that were also missing here: 5G SA/NSA is
`AT+SP5GRAN?`/`AT+SP5GRAN=<0|1>`, 5G registration is `AT+C5GREG?`, VoLTE is `AT+CAVIMS?`,
and the UE usage setting is `AT+CEUS`/`AT+CEMODE`.

What was right above, and still is: the RAT the modem *camps* on at boot comes from modem
NV written by Android's RIL, so booting slot a's images is what decides it, and
`persist.vendor.modem.nr.enable` remains a property, not a switch.  A band lock is an
additional constraint on top of that, not a replacement for it.

Provenance, stated plainly: these shapes came out of researching the modem's own AT
surface, not from vendor documentation and not from this handset.  **They have not been
sent to the handset yet**, so treat them as the shape to try first rather than as measured
behaviour.  Whoever tries them should read the lock back after writing it, because "the
modem accepted the command" and "the lock took" are two different claims.

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

### What runs now: logind alone, no userspace daemon

`/opt/e5/powerkey.py` is gone (2026-09-18).  It listened on `/dev/input/event0`, forced
`idle-delay` to 0 so that its own `bl_power` toggle stayed coherent, and opened the
Power Off dialog on a 1.5 s hold.  All of that was either redundant or actively fighting
the compositor:

* waking from a blanked panel never needed help.  phoc uses wlroots' idle protocol and
  owns DPMS through the DRM connector: once it blanked, `bl_power` alone could not
  bring the CRTC back, and any input event -- key or touch -- unblanks it.  The script
  was writing `bl_power` underneath a compositor that was already doing it;
* `idle-delay=0` was the price of that arrangement, and it is a bad price on a phone:
  it means the panel *never* blanks on its own;
* logind implements the long press in the kernel-facing path already
  (`HandlePowerKeyLongPress`, whose default is `ignore` -- that default, not a missing
  handler, is what made a held key do nothing).

So the key is now logind's, via
`rootfs/overlay/etc/systemd/logind.conf.d/20-e5-pwrkey.conf`:

| press | action | who |
|---|---|---|
| short | `lock` -- phosh's lock screen | systemd-logind |
| long | `poweroff` -- immediate, no dialog | systemd-logind's own long-press timer |
| (panel dark) | any key or touch wakes it | phoc (wlroots idle) |

`HandlePowerKey=suspend` is not an option on this board and neither is gsd's
`power-button-action=suspend` (bullet 3 above); `lock` is what is left that is both
instant and safe.

### Verification (measured on the device)

**A real short press locks, and phosh then blanks the panel itself** -- the press does
*not* just sit there waiting for the idle timer.  One press, logged at 1 Hz (the panel
had been blanked by idle beforehand):

| t | `LockedHint` (logind) | `card0-DSI-1/dpms` | `sprd_backlight/bl_power` | what happened |
|---|---|---|---|---|
| 11:22:26 | no | Off | 4 | idle blank: panel off, session *not* locked |
| 11:22:27 | no | **On** | 4 -> 0 | press wakes the panel |
| 11:22:31 | **yes** | **Off** | **4** | logind locks; the lock screen blanks the panel |
| 11:22:34 | yes | **On** | 0 | a tap wakes it, straight to the lock screen |

`org.gnome.ScreenSaver.ActiveChanged` fires on the session bus at the same moment as
`LockedHint` flips, so the dark screen after a press *is* the locked state, not a
missing one.  `sm.puri.phosh.lockscreen require-unlock=true`, so getting back in needs
the unlock gesture on the lock screen.

**Idle blanking alone does not lock.**  With `idle-delay` at 15 s and the session left
alone:

| t | `LockedHint` | `dpms` | `bl_power` |
|---|---|---|---|
| 5 s ... 20 s | no | On | 0 |
| 25 s ... 50 s | **no** | **Off** | **4** |
| after one injected `KEY_WAKEUP` | no | **On** | **0** |

The compositor's idle blank is a DPMS blank and nothing else: the session stays
unlocked behind a dark panel, so the only thing that locks this device is the power key.
`idle-delay` is back at 300 s afterwards.

That is not a phosh default we can flip: `org.gnome.desktop.screensaver` already has
`lock-enabled=true` (set here while testing), `idle-activation-enabled=true` and
`lock-delay=0`, and the session still does not lock on idle.  The piece that is missing
is the idle *activator*: GNOME does that in gsd-screensaver, which this gnome-settings-daemon
does not ship and the phosh session does not start (the running plugins are a11y-settings,
color, datetime, housekeeping, keyboard, media-keys, power, print-notifications, rfkill,
**screensaver-proxy**, sharing, smartcard, sound, usb-protection, wacom, wwan).  Locking
on idle would therefore need something that reacts to the idle transition -- an autostart
helper, i.e. the kind of process this section just removed -- or logind's
`IdleAction=lock`, which needs the session to report an idle hint and phoc does not
(`IdleHint` stayed `no` through every blank above).

The long press is also no longer the "Power Off" dialog with its countdown and Cancel
(that came from `gnome-session-quit --power-off`, i.e. from the script).  It powers off
at once.

The long press is also no longer the "Power Off" dialog with its countdown and Cancel
(that came from `gnome-session-quit --power-off`, i.e. from the script).  It powers off
at once.

## 19. Phosh needs GNOME apps -- purging KDE took the only settings app with it

Phosh ships no applications of its own beyond the shell, the OSK and the compositor, so
after the KDE purge the app grid held little more than a terminal: the only "Settings" on
the device had been KDE's `plasma-settings`, and it went with the rest of Plasma.

The phone-shaped set that belongs with Phosh was installed with `--no-install-recommends`
(`/` went to 4.4 GiB used, 1.2 GiB free):

| package | what it is |
|---|---|
| `phosh-mobile-settings` | Phosh's own phone settings (`mobi.phosh.MobileSettings`) |
| `gnome-control-center` | the general GNOME settings app (`org.gnome.Settings`) |
| `gnome-calculator`, `gnome-clocks`, `gnome-characters` | the usual small GNOME apps |
| `foot` | terminal (already there) |

Deliberately **not** installed, with reasons worth writing down:

* `gnome-calls` / `chatty` (calls and SMS) need ModemManager and a RIL on top of the
  modem.  This port drives the modem directly over AT (`docs` sections 13/14); there is
  no RIL, so a dialer would have nothing to talk to.
* `epiphany-browser` (WebKit) and `nautilus` are the obvious next apps when there is
  space and appetite; the baseband gives them a working network, unlike Wi-Fi
  (section 8, still blocked).
* anything that plays audio is questionable until the amplifier path is verified -- the
  MU300 port found its AW883xx silent on I2C, and this board has not been checked.

### Default passwords

`e5` / **123456** and `root` / `root` (`e5` has NOPASSWD sudo).  The user password is
numeric on purpose: the 9-key keypad is the only keyboard on the device and it types
digits, so that is what unlocks phosh's lock screen.  The root one is unchanged, and
`rootfs/device-finalize.sh` -- which creates both accounts when a rootfs is built -- now
writes 123456 as well, so a rebuilt image matches the running device.  Verified by
logging in over telnet as `e5`/`123456`.

## 20. GPU: the UMD/kbase handshake, the panel console, and what still blocks a compositor

Everything in this section was measured on the device on 2026-09-18, on the kernel
this repository builds (`5.15.211-g94401422a7df #4`, 66 modules).

### 20.1 The handshake: ARM's glibc UMD and kbase r41p0 do talk

The kernel side was never in doubt (vendor kbase is built in and reports
`Kernel DDK version r41p0-01eac0`, `GPU identified as 0x1 arch 9.0.9 r0p1`).
What was unknown is whether a *userspace* Mali driver exists that this kernel
accepts.  One does: CoreELEC's `opengl-meson` packages ARM's Linux UMD, and the
r41p0 arm64 build is `r41p0-fbdev-g57-aarch64-8a6d38656-b5` -- glibc, aarch64,
Valhall G57, and built against the same kbase major version this kernel reports.

Installed in the rootfs at `/opt/mali` (`libMali.so` plus
`libEGL.so.1`/`libGLESv2.so.2`/`libGLESv1_CM.so.1` symlinks) and driven by
`tools/egl-probe.py` -- ctypes only, so the target needs no compiler:

    libEGL   : /opt/mali/libEGL.so.1
    eglGetDisplay(DEFAULT) -> 0xfe4aa80
    eglInitialize -> OK, EGL 1.4
    EGL_VENDOR      : ARM
    EGL_VERSION     : 1.4 Valhall-"r41p0-fbdev-g57-aarch64-8a6d38656-b5"
    EGL_CLIENT_APIS : OpenGL_ES
    eglChooseConfig(pbuffer) -> 5 config(s)
    eglCreateContext -> 0x100765a0
    pbuffer surface + current -> OK
    GL_VENDOR                   : ARM
    GL_RENDERER                 : Mali-G57
    GL_VERSION                  : OpenGL ES 3.2 v1.r41p0-fbdev-g57-aarch64-8a6d38656-b5.fc0fdda618d58b1ff293a1730bc57b91
    GL_SHADING_LANGUAGE_VERSION : OpenGL ES GLSL ES 3.20
    GL_NUM_EXTENSIONS           : 101
    glClear + glFinish -> OK

kbase says the same thing from its own side -- the first UMD context makes it
power the GPU up through its platform hook:

    [  136.577129] mali GPU_set_DVFS_table kbase_platform_set_DVFS_table
                   gpu_power_state = 1 gpu_clock_state = 1,gpu_temperature = 39840

Two details worth keeping:

* **This does not need `/dev/fb0`.**  The extension list contains
  `EGL_KHR_surfaceless_context`, and the handshake succeeds on a kernel with no
  fbdev at all -- the "handshake needs fbdev" assumption was wrong.
* **The UMD is not installed as the system `libEGL.so.1`.**  It is a *fbdev*
  build: it has no `EGL_KHR_platform_gbm`/`EGL_MESA_platform_gbm`, so a wlroots
  compositor (phoc) could not use it, and swapping Mesa's libEGL out for it would
  cost the session its renderer for nothing.

### 20.2 `/dev/fb0` needed two driver patches, and it was worth it for the console

The vendor KMS driver in `drivers/unisoc_platform/sprd_disp` never called
`drm_fbdev_generic_setup()`, so `CONFIG_DRM_FBDEV_EMULATION=y` on its own produces
no framebuffer.  `kernel/patches/0001` adds the call at the end of
`sprd_drm_bind()`.  That alone is not enough either, and the reason is a probe
order: the MIPI panel is a *child* device of the DSI host, and it attaches after
`drm_dev_register()`:

    [   11.836695] [drm] sprd_dsi_connector_detect()          <- before the panel exists
    [   11.850052] [drm:sprd_panel_probe] create cabc Succeed!
    [   11.930868] [drm] sprd_dsi_host_attach()
    ...
    [   12.428273] WCN BASEcrystal ... (12 s later, boot continues)

`sprd_dsi_connector_detect()` returns connected only when `dsi->panel` is set, so
the fbdev client probed a "disconnected" connector and gave up.  Patch `0002`
schedules a `drm_kms_helper_hotplug_event()` from a delayed workqueue in
`sprd_dsi_host_attach()` -- from a workqueue, not inline, because the hotplug ends
in a modeset that walks the same panel/DSI paths the probe is still holding.  The
inline version was tried first and made the boot take minutes (the initramfs loads
`sprd-drm.ko`), which is how that was learned.

**These patches live in two places on purpose.**  `kernel/patches/*.patch` in this
repository is the canonical form -- `kernel/build-linux.sh` applies them to a fresh
clone -- and the same four changes are now also *commits* in the kernel tree itself
(`kernel_sprd_ums9158`, branch `linux-staging`):

| patch | commit | what it touches |
|---|---|---|
| `0001-sprd-drm-fbdev-emulation` | `c7b95f5f` | `sprd_drm.c`: `drm_fbdev_generic_setup()` |
| `0002-sprd-dsi-hotplug-on-panel-attach` | `4ab5ac3d` | `sprd_dsi.c/.h`: deferred client re-probe |
| `0003-ion-for-the-fbdev-umd` | `7b42f508` | `staging/android` Kconfig + Makefile |
| `0004-sprd-keypad-backspace-next-to-back` | `678d2409` | `sprd_keypad.c`: back + BackSpace |

The build script recognises the committed state (`git apply --reverse --check` passes,
so it prints "already applied") and the working tree is byte-identical before and after
those commits.  `.scmversion` stays frozen at `-g94401422a7df`, so the release string
-- and with it `/lib/modules/5.15.211-g94401422a7df` -- does not move when the tree
gains commits.

With both DRM patches `/dev/fb0` is there on every boot (`0 sprddrmfb`,
320x480, 32bpp XRGB8888) -- and so is a **console on the panel**.  That second
part needed one more fix: LK merges the boot image's command line with its own
bootargs and *its* parameters win on duplicate keys, so the `console=tty0
loglevel=7` that `build-boot-image.py` has always put in the header never took
effect.  `/proc/consoles` showed only `ttyS1` and `ramoops-1`, the VT never
received a printk, and the panel showed an empty console with a blinking cursor.
The kernel now carries it itself:

    CONFIG_CMDLINE="console=tty0 loglevel=6"
    CONFIG_CMDLINE_EXTEND=y

which is appended after the bootloader's string, and after that:

    ttyS1                -W- (EC    )  235:1
    ramoops-1            -W- (E  p a)
    tty0                 -WU (E  p  )    4:1

The kernel log now scrolls on the panel from the moment fbcon binds.

### 20.3 A window surface still fails, with or without ION

`tools/fbdev-info.py` (new, same ctypes trick) shows what the UMD sees:

    /dev/fb0   smem_start 0x0   smem_len 614400   line_length 1280
               xres x yres 320 x 480   virtual 320 x 480   32bpp
               red/green/blue 16:8 / 8:8 / 0:8   capabilities 0x0

`eglCreateWindowSurface()` with ARM's `fbdev_window {u16 width, height}` fails:

    eglCreateWindowSurface(fbdev 320x480) -> EGL_NO_SURFACE
    FAIL: glCreateWindowSurface failed (EGL_BAD_ALLOC (0x3003))

-- at 320x480 and at 64x64, 160x160, 240x240 and 320x320 (so it is not a size or
a format mismatch), and both before and after ION was enabled.  The blob's
strings contain `/dev/ion` and `query ion heap failed ret=%#x`, i.e. it predates
dma-buf heaps; this kernel has dma-heap but the Android build never enables the
vendor ION that is still sitting in the tree, so `kernel/patches/0003` wires its
Kconfig/Makefile back up and the fragment sets `CONFIG_ION`+`CONFIG_ION_SYSTEM_HEAP`
+`CONFIG_ION_CMA_HEAP`.  `/dev/ion` now exists and the window surface still fails,
so ION was not the (only) blocker and the fbdev path was not pursued further --
it cannot serve a compositor anyway.

### 20.4 A newer UMD is rejected by this kernel

CoreELEC's newer package (`opengl-meson-r44p0`) has exactly the variant that is
missing: `valhall/r44p0/wayland/libMali_g57_dmaheap.so`,
`r44p0-wayland-drm-g57-dmaheap-aarch64`, glibc, linking
`libwayland-client/server` and using GBM.  Run as the session user with the
running phoc's socket:

    libEGL   : /opt/mali/libMali-r44p0-wayland.so
    eglGetDisplay(DEFAULT) -> 0x26da97e0
    FAIL: eglInitialize failed (EGL_NOT_INITIALIZED (0x3001)) -- the UMD did not accept kbase

So kbase r41p0 refuses an r44p0 UMD.  The version check is not advisory: a UMD
from a different DDK major version cannot be used against this kernel, which
rules out "just take CoreELEC's newest blob".

### 20.5 What that leaves

A GPU-composited session needs a **glibc aarch64 GBM (or wayland) UMD built
against kbase r41p0**.  The alternatives, in order of effort:

1. Find that blob.  The r41p0 arm64 package publishes fbdev only, so this means
   another vendor's BSP (Amlogic/Unisoc/Rockchip trees that ship a Linux libmali),
   an ARM DDK build, or a CoreELEC/LibreELEC tree that built the wayland variant
   for an r41p0 kernel.
2. Port the kernel side to the DDK version that *is* published (r44p0) -- a
   kbase replacement plus the vendor platform integration (DVFS, power domains),
   which is a real kernel port, not a config change.
3. libhybris around the device's own Android blob (bionic + the graphics
   allocator/mapper HIDL services) -- how Ubuntu Touch and Sailfish do it.
4. Panfrost, which turned out to need a driver backport rather than a DT port --
   done since, see section 20.7.

### 20.6 The compositor runs on the GPU: an *older* GBM UMD, and a 0600 dma-heap

The missing piece in 20.1-20.5 was a glibc GBM/wayland UMD.  It does not have to be
r41p0: the version check is not what the kernel enforces -- the UMD is the one that
bails out, and only when the kernel is *older* than it.  Allwinner's A523 (also a
G57) userspace, taken from TrimUI Smart Pro S firmware, is one blob with the whole
GBM API in it:

    /opt/mali/libMali-r32p0-sunxi.so
    49,377,264 B, ELF aarch64, glibc
    version string: 1.4 Valhall-"r32p0-01eac1"
    exports gbm_create_device / gbm_bo_create / gbm_surface_create[_with_modifiers]
    EGL client extensions: EGL_EXT_platform_base EGL_KHR_platform_gbm

Against this kernel it initialises on the *compositor* platform rather than the
fbdev one:

    gbm_create_device(/dev/dri/card0) -> 0x4dc1490
    eglGetPlatformDisplayEXT(EGL_PLATFORM_GBM_KHR) -> 0x4f965a0
    eglInitialize -> OK, EGL 1.4
    EGL_VERSION : 1.4 Valhall-"r32p0-01eac1"
    GL_RENDERER : Mali-G57
    GL_VERSION  : OpenGL ES 3.2 v1.r32p0-01eac1.3634895aa082dda7c3407d9f3e199919

(`tools/egl-probe.py` grew an `EGL_PLATFORM=gbm` mode for this; the platform
entry point is only reachable through `eglGetProcAddress` -- it is not a dynamic
symbol in this build.)

`gbm_surface_create(..., SCANOUT|RENDERING)` returns NULL, but the modifier-aware
entry point works, and that is the one wlroots uses:

    gbm_surface_create_with_modifiers(XR24, LINEAR) -> 0x4d61530
    eglCreateWindowSurface(gbm surface) -> 0xac62130
    eglSwapBuffers -> ok (three times)
    gbm_surface_lock_front_buffer -> 0xac62740   stride=1280 format=0x34325258

Then phoc, with the dynamic loader pointed at the blob **for the compositor only**:

    /lib/ld-linux-aarch64.so.1 --library-path /opt/mali/gbm:/usr/lib/aarch64-linux-gnu \
        /usr/bin/phoc.orig -v -S -C /etc/phosh/phoc.ini ...

...failed at first, and the reason is worth remembering:

    [render/egl.c:205] Supported EGL client extensions: ... EGL_KHR_platform_gbm
    [render/egl.c:555] Failed to create GBM device
    [render/pixman/renderer.c:328] Creating pixman renderer
    phoc[7208]: open /dev/dma_heap/system failed

**`/dev/dma_heap/*` is created 0600 root:root.**  The session user cannot open it,
ARM's GBM allocates its buffers from a dma-buf heap, `gbm_create_device()` returns
NULL, and wlroots quietly falls back to the CPU renderer instead of failing.  One
udev rule later (`rootfs/overlay/etc/udev/rules.d/60-e5-dma-heap.rules`,
`SUBSYSTEM=="dma_heap", MODE="0666"`) the same boot reports:

    [render/egl.c:354] Using EGL 1.4
    [render/egl.c:359] EGL vendor: ARM
    [render/gles2/renderer.c:538] Creating GLES2 renderer
    [render/gles2/renderer.c:539] Using OpenGL ES 3.2 v1.r32p0-01eac1...
    [render/gles2/renderer.c:541] GL renderer: Mali-G57

with the GPU actually busy (`SPRDDEBUG gpu core power on polling SUCCESS`), the
shell up ("Phosh ready after 0.85s"), and `grim` capturing the composited output.

Two details keep the rest of the session working:

* the blob has **no Wayland platform** in its EGL client extensions, so GTK apps
  must keep Mesa's software EGL.  That is why phoc gets the blob through an
  explicit `--library-path` on the loader rather than `LD_LIBRARY_PATH`, which
  its session child (`gnome-session`) would inherit;
* `WLR_RENDERER=pixman` from `/etc/environment` is unset for phoc by the same
  wrapper, so wlroots gets to choose its GLES2 renderer.

All of it is installed by `rootfs/overlay/opt/e5/gpu-mali-setup`: the
`/opt/mali/gbm/*` symlinks, the `/usr/bin/phoc` wrapper (the real binary stays as
`/usr/bin/phoc.orig`), and the chmod that makes the current boot work before udev's
rule is in place.

### 20.7 Panfrost on the device: what it took, and what runs now

Sections 20.1-20.6 are the search for a blob this kernel accepts.  This is the
other route, and it is the one that works: panfrost drives the Mali-G57, the
compositor renders on it, and -- for the first time on this device -- so do the
clients.  Everything below was measured on the device, image `bf347253`,
kernel `97082a76`.

**The driver was not there.**  The tree's `drivers/gpu/drm/panfrost` is upstream
v5.15 with a couple of ACK backports and stops at Bifrost -- its model table ends
at `GPU_MODEL(g31, 0x7003)` and there is no `hw_features_g57` -- so upstream
6.0's job-manager Valhall series was carried back: `2e87309e0660`,
`382435709516`, `a17775a1af59`, `0c0af438345e`, `892e7fb7c254`, `5b9afc161ea5`,
`d8e53d8a4e0a`, `5ba99fca1de0`, `952cd9745092`.  That is the G57 model entry
(its ARM codename is "Natt", which is also what the vendor DT calls the node),
its feature and issue sets, three errata bits and the two register writes that go
with them.

**The platform side was nobody's.**  There is no power domain for this GPU in
the device tree, and the sequence that switches it on lived only in kbase's
platform code.  What makes it portable is that the DT already carries every one
of those registers as an opaque `<&syscon REG MASK>` triple, so a driver needs
the *order*, not the addresses: `panfrost_sprd.c` is
`mali_kbase_config_qogirn6l.c`'s `mali_freq_init()` plus
`mali_power_on()`/`mali_clock_on()` with the DVFS governance dropped.  First
boot with it:

    panfrost 23140000.gpu: clock rate = 26000000
    panfrost 23140000.gpu: Unisoc GPU powered on (DVFS index 3)
    panfrost 23140000.gpu: mali-g57 id 0x9091 major 0x0 minor 0x1 status 0x0
    panfrost 23140000.gpu: features: 00000000,67c00007, issues: 00000001,80000400
    panfrost 23140000.gpu: Features: L2:0x07120206 Shader:0x00000000 Tiler:0x00000809 ...
    panfrost 23140000.gpu: shader_present=0x5 l2_present=0x1
    [drm] Initialized panfrost 1.2.0 20180908 for 23140000.gpu on minor 0

`0x9091` is the G57 ID (`panfrost_model_cmp()` masks it to `0x9001` to match the
model table) and `0x5` is two shader cores, non-contiguous -- the same value an
independent G57 MC2 bring-up reports.

Three details that each cost an hour:

* `dcdc_gpu_pd` points at `&pmu_apb_regs`, but kbase replaces the regmap
  underneath it with the PMIC's (`sprd,ump962x-syscon`) before using it; the DT
  comment calls the address fake.  `sprd_pmic_regmap()` does the same and keeps
  the parsed register/mask pair.
* the vendor DT names its interrupts `"JOB"`, `"MMU"` and `"GPU"` -- all three on
  the same GIC line -- and `of_irq_get_byname()` is case sensitive, so a mainline
  driver finds no interrupts at all.  `panfrost_irq_get()` walks
  `interrupt-names` case-insensitively as a fallback, quietly: the first version
  asked with `platform_get_irq_byname()` and printed three "IRQ x not found"
  lines per boot for lookups that then succeeded.
* the frequency is set by writing a DVFS *index* into a syscon, and the clocks in
  the node are shared PLL parents, so `clk_set_rate()` must not be used on them:
  devfreq is skipped for this board through a new
  `panfrost_compatible.no_devfreq`.

**Userspace is stock Debian.**  Nothing was installed for this -- Mesa 25.0.7
already carries panfrost.  The session only had to stop being told not to use
it (`/etc/environment` forced `llvmpipe`) and wlroots had to be told to look:

    [render/gles2/renderer.c:538] Creating GLES2 renderer
    [render/gles2/renderer.c:539] Using OpenGL ES 3.1 Mesa 25.0.7-2+deb13u1
    [render/gles2/renderer.c:541] GL renderer: Mali-G57 (Panfrost)

and a *client* gets hardware too, which is what the blob could never do (20.6):
`eglinfo` on the Wayland platform now reports
`OpenGL ES profile renderer: Mali-G57 (Panfrost)` where it used to report
llvmpipe.  The display is being scanned out from a compositor buffer as well:

    plane[31]: crtc=dispc0  fb=121  format=XR24  size=320x480
            allocated by = phoc.orig
            imported=no

**Two traps, both found the hard way.**

* `sprd_gem_dumb_create()` counts every `DRM_IOCTL_MODE_CREATE_DUMB` in a static
  variable that is never reset, and refuses the 11th request of each boot with
  `-EINVAL`.  wlroots allocates its primary swapchain through exactly that
  ioctl -- the KMS state above is the proof: Mesa's kmsro renders on panfrost,
  but the *display* device allocates the buffer (`imported=no`) -- so a second
  session in the same boot dies with

      MESA: error: Failed to create scanout resource
      DRM_IOCTL_MODE_CREATE_DUMB failed: Invalid argument
      [render/allocator/gbm.c:116] gbm_bo_create failed
      [render/swapchain.c:110] Failed to allocate buffer
      [types/output/swapchain.c:109] Swapchain for output 'DSI-1' failed test

  and the panel stays black until the next reboot, because a compositor that
  cannot build a swapchain does not modeset at all.  The cap is 64 now
  (kernel patch 0006).
* splitting the two devices explicitly -- which is the shape this hardware wants
  -- does not work with libseat/logind here:

      Opening fixed list of KMS devices from WLR_DRM_DEVICES: /dev/dri/card0:/dev/dri/renderD128
      Unable to open /dev/dri/card0 as KMS device
      [libseat] Could not take device: No such device
      Failed to open device: '/dev/dri/renderD128': Resource temporarily unavailable
      Found 0 GPUs, cannot create backend

  wlroots opens each entry from the list as a KMS device through libseat, logind
  refuses both, and the session never starts at all.  Worth remembering anyway:
  panfrost registers first and takes `card0`, so **the display is `card1`** and
  the GPU is `card0` -- the opposite of the way 20.1-20.6 refer to them, and a
  `WLR_DRM_DEVICES` list written from those notes would name the wrong device.

**What the blob path leaves behind.**  It is retired, not because it broke but
because panfrost makes it pointless: `rootfs/overlay/opt/e5/gpu-mali-setup` is
gone, the session no longer installs a `/usr/bin/phoc` wrapper (an overlay copy
of it would have to carry a copy of the binary), and the dma-heap udev rule is
kept only because opening those heaps is not specific to Mali.
`CONFIG_MALI_MIDGARD=m` with nothing loading the module is what keeps kbase off
the node (`modprobe mali_kbase` is the way back).

**What it does not get you: PanVK.**  Mesa has no Valhall v9 backend for it, by
design -- `src/panfrost/vulkan/meson.build` builds `jm_archs = [6, 7]` and its
arch loop skips 9, because the `jm/` command-buffer code is Bifrost-only.  The
only v9 Vulkan that exists is a reverse-engineering bring-up with compute and
offscreen draws working and no WSI/present, i.e. no swapchain and therefore no
compositor.  So G57 gets OpenGL/GLES 3.1 from panfrost and no Vulkan at all --
which is enough for the actual problem (the clients stuck on llvmpipe are a
GL/EGL problem, not a Vulkan one), but Vulkan is off the table either way.

## 21. Display scaling on a 320x480 panel: what fits, and what the resampling costs

The panel is 320x480 at ~166 DPI while phosh lays its UI out for something closer to
360x720, so `[output:DSI-1] scale` in phoc.ini is a three-way compromise between the
on-screen keyboard, the lock screen and text size.  All five options were measured on
the device (grim captures; the "logical" column is exactly the capture size):

| scale | logical | resample | on-screen keyboard | lock screen | text-scaling |
|---|---|---|---|---|---|
| 1.0 | 320x480 | 0 % | cut on the right | unlock button off-screen | 0.85 |
| **0.9** | **355x533** | **10 %** | fits | unlock button half off | **0.85** (set) |
| 0.85 | 376x565 | 15 % | fits | unlock button just cut | 0.90 |
| 0.8 | 400x600 | 20 % | fits | fits | 0.85 (text too small) |
| 0.75 | 426x640 | 25 % | fits | fits | 1.0 (visibly soft) |

* A Wayland output scale below 1 is *fractional*: the compositor renders the output at
  `mode/scale` (grim reports 426x640 at 0.75 and 355x533 at 0.9) and the display
  controller scales that down to 320x480.  Both GTK 4.18.6 and wlroots 0.18.2 *do*
  implement `wp_fractional_scale_v1` (grepping the libraries directly for
  `wp_fractional_scale[a-z_]*` hits in both; `strings` is not installed on the
  device, which is what made an earlier check report zero), so the softness is the
  resampling itself, not a missing protocol.
* Physical text size is roughly `text-scaling-factor * scale`, and the keyboard
  constraint caps that product at about 0.8 whatever the split is: the OSK's layout is
  ~339 logical px wide at ts 0.85, so `320/scale >= 339 * ts/0.85`.
* The lock screen needs ~575 logical px of height, i.e. `scale <= ~0.84`; above that
  its unlock button sits half below the screen.  That no longer matters -- the keypad's
  confirm key submits the PIN (section 12.1) and the arrow keys can move the focus to
  the button -- so 0.9 was chosen, for the sharpest text whose keyboard still fits and
  for the in-system text size that was found comfortable.
* `sm.puri.phoc scale-to-fit = true` makes phoc scale down windows that are larger than
  the output, which is what keeps apps written for >=360 px usable.

**The system font size is the user's call, and the toggle is built in.**  Everything
above is about the *output* scale; the *font* is
`org.gnome.desktop.interface text-scaling-factor`, which phosh exposes as
Settings -> Accessibility -> "Large Text" (and which renders at the chosen size, so it
stays sharp).  That is the control to reach for -- the panel ends up at 1.25 here,
which is 47 % larger text than the 0.85 this started with, with nothing but the
on-screen keyboard and the lock screen caring.

Trying to widen that budget by replacing the OSK did not work: Debian's
`squeekboard` ships (its layouts are compiled into the binary) and it starts,
registers as a gnome-session client and connects to Wayland -- and then exits with

    DEBUG: Registered client at '/org/gnome/SessionManager/Client25'
    WARNING: DBus unavailable, unclear how to continue. Is Squeekboard already running?

even when nothing owns `sm.puri.OSK0` (verified with `GetNameOwner`: NameHasNoOwner),
through D-Bus activation from a service file as well as by hand.  phosh's
`phosh-osk-stub --allow-replacement` is what runs, and its layout is a fixed width --
which is why the keyboard itself is the thing that suffers from a large font.



## 20. The hotspot needed the regulatory database in the initramfs

`hostapd` installs and `wlan0` does switch to AP mode (`iw dev wlan0 set type __ap`),
but hostapd refused to start: `Failed to set beacon parameters` on 2.4 GHz, and on 5 GHz
`Frequency 5180 (primary) not allowed for AP mode, flags: 0x853 NO-IR`.  `iw reg get`
answered `country 00: DFS-UNSET`, and `iw reg set CN` never changed that: **cfg80211 loads
`regulatory.db` from firmware when it initialises**, and here it initialises in the
initramfs -- before the root filesystem, and therefore before `/lib/firmware`, exists.
The request is one-shot: it waits in the sysfs firmware fallback (the trick MU300's
`regdb-load` uses) and times out long before a systemd service could feed it.  Without
the database cfg80211 cannot apply CN's rules, so every channel stays NO-IR and hostapd
cannot transmit beacons -- which is what "client cannot join" looked like.

Feeding it late cannot work either, and neither can reloading the modules: the running
rootfs has no `/lib/modules` at all (the vendor modules live only in the initramfs), so
`sprd_wlan_combo`/`wcn_bsp`/`cfg80211` cannot be unloaded and re-inserted to re-issue the
request.

The fix is in the image: `regulatory.db` and `regulatory.db.p7s` (from `wireless-regdb`,
6 KiB together) now sit in `rootfs/overlay/lib/firmware/`, and `boot/init` copies the
overlay's `lib/` to `/lib` *before* loading the WCN modules (`stage=overlay-early`), so
cfg80211 finds them the moment it asks.  **The hotspot therefore needs a reflash** of the
rebuilt image; the device currently runs the previous one.

For reference, the parameters this chip wants (from MU300's `hotspot-start`): 5 GHz
`hw_mode=a channel=36 ht_capab=[HT40+][SHORT-GI-20][SHORT-GI-40] ieee80211ac=1
vht_oper_chwidth=1 vht_oper_centr_freq_seg0_idx=42`, or 2.4 GHz `hw_mode=g channel=6
ht_capab=[SHORT-GI-20]`, with `country_code=CN` and `ieee80211d=1`.

### 20.1 What it took to get `AP-ENABLED`

Four things, in the order they were discovered:

1. **A signed regulatory database, upstream variant.** The kernel's own words were
   `cfg80211: loaded regulatory.db is malformed or signature is missing/invalid`: Debian's
   `wireless-regdb` build (`regulatory.db-debian`) is signed with Debian's key, while this
   vendor kernel only carries the upstream `sforshee`/`wens` certificates.  The
   `-upstream` pair works, and it has to be in the **initramfs** because cfg80211 asks for
   it when the WCN modules load (see section 20 for why a late feed cannot work).
2. **The country has to be set explicitly** even with the database present: cfg80211 starts
   in the world domain (`country 00`).  With a valid database `iw reg set CN` finally takes
   effect -- `country CN: DFS-FCC` with real rules -- and before that it silently did
   nothing, which is why every channel read `NO-IR`.
3. **The DT's `wcnmodem` partition** is still faked with a loop device over
   `/lib/firmware/wcnmodem.bin`; the service gates on that file rather than on the node the
   script creates.
4. `wlan0` must be free: `wpa_supplicant.service` stopped and masked, and the interface
   marked unmanaged in NetworkManager.

Verified on the device:

    iw reg get                     -> country CN: DFS-FCC
    hostapd /etc/hostapd/e5.conf   -> wlan0: interface state COUNTRY_UPDATE->ENABLED
                                      wlan0: AP-ENABLED
    iw dev wlan0 info              -> type AP, ssid E5-Linux
    ip -br addr show wlan0         -> 192.168.78.1/24
    systemctl is-active e5-hotspot.service -> active

clients get a lease from systemd-networkd's DHCPServer
(`etc/systemd/network/20-e5-wlan0.network`, 192.168.78.10-29) and are NATed out through
`sipa_eth0` by the rules `mobile-data up` installs.  SSID `E5-Linux`, password
`12345678`; a 5 GHz profile is in `etc/hostapd/e5-5g.conf` for when the regulatory domain
allows channel 36 (this one did not, `NO-IR`, until the database loaded).

### 20.2 Clients got an address but no internet (two traps)

1. **No resolver behind the address.**  systemd-networkd's `DHCPServer=yes` advertises its
   own address as DNS by default, and this image runs no DNS server at all (no dnsmasq, no
   systemd-resolved), so a client could ping IPs but resolve nothing.  The interface's
   `.network` now sets `EmitDNS=no` and `hotspot-start.sh` writes the nameservers
   `/etc/resolv.conf` actually has into
   `/etc/systemd/network/20-e5-wlan0.network.d/10-dns.conf`, so the lease carries the
   carrier's resolvers.
2. **systemd ignores config files that are not root-owned.**  Files pushed from the host
   keep the host uid (501) and a 0600 mode; hostapd did not care, but networkd silently
   skipped the file -- `networkctl status wlan0` showed `Network File: n/a`, `State:
   unmanaged` and no address, and for a while that looked like the DHCP server had broken.
   Any config file that lands on the device by hand needs
   `chown root:root` + a readable mode.

Verified after both fixes:

    Network File: /etc/systemd/network/20-e5-wlan0.network
                  + .../20-e5-wlan0.network.d/10-dns.conf
    State: routable (configured)   Address: 192.168.78.1
    DNS: 223.5.5.5 119.29.29.29 58.240.57.33 221.6.4.66
    DHCP server listening on 0.0.0.0%wlan0:67

A client that already holds a lease has to reconnect (or let the lease renew) to pick up
the new DNS option.

### 20.3 dnsmasq does the hotspot's DHCP and DNS

`systemd-networkd`'s DHCPServer cannot answer the DNS queries it advertises, and with
`EmitDNS=no` plus a static `DNS=` list the lease carried the carrier's resolvers but the
client still did not resolve (it was the lease renewal that decided it, and a static list
also breaks whenever the carrier changes servers).  `dnsmasq` does both jobs properly:

    /etc/dnsmasq.d/e5-hotspot.conf
      interface=wlan0, interface=usb0, bind-interfaces
      no-dhcp-interface=usb0                 (usb0's leases stay with networkd)
      dhcp-range=192.168.9.10,192.168.9.61,255.255.255.0,12h
      dhcp-option=option:router,192.168.9.1
      dhcp-option=option:dns-server,192.168.9.1

and `wlan0`'s `.network` went back to address-only (`DHCPServer=no`), so nothing competes.
Verified: `dnsmasq --test` OK, `dnsmasq: active` (enabled), listening on
`192.168.9.1:53`, `192.168.77.1:53` and `127.0.0.1:53`, and
`busybox nslookup deb.debian.org 192.168.9.1` resolves -- so a client that renews its
lease gets `192.168.9.x`, gateway `192.168.9.1` and a resolver that actually answers.

### 20.4 Channel 149 at 80 MHz works -- the stall was the regulatory domain

For a while the tree kept the hotspot at 20 MHz because 40 MHz and 80 MHz both left
hostapd in `COUNTRY_UPDATE->HT_SCAN` and never at `AP-ENABLED`.  That was not the width;
it was the same missing country as section 20.  With `country CN: DFS-FCC` the driver's
own regulatory list reads

    nl80211: 5725-5850 @ 80 MHz 33 mBm

and with `ieee80211ac=1`, `ht_capab=[HT40+]`, `vht_oper_chwidth=1` and
`vht_oper_centr_freq_seg0_idx=155` hostapd sets

    nl80211: Set freq 5745 (ht_enabled=1, vht_enabled=1, he_enabled=0, bandwidth=80 MHz, cf1=5775 MHz, cf2=0 MHz)

The beacon (parsed from hostapd's own `-dd` hexdump with `work/parse-beacon.py`) carries
HT Operation primary 149 / secondary offset 1 (HT40+) and **VHT Operation `width=1`
(80 MHz), seg0=155, seg1=0** -- the 149/153/157/161 block.  Four start attempts (with and
without a preceding `iw dev wlan0 scan`; with and without a pre-set
`iw dev wlan0 set channel 149 80MHZ`) all reached `AP-ENABLED`, so
`opt/e5/hotspot-start.sh` no longer configures the channel and
`etc/hostapd/e5.conf` is the 80 MHz profile (the old 20 MHz one is in git history).

Two things to keep in mind:

* The 5 GHz band's own capabilities are fine: `iw phy` says `HT20/HT40`, and the wiphy's
  VHT max width is 80 MHz (`Supported Channel Width: neither 160 nor 80+80`), while the
  driver's regulatory list allows 80 MHz on 5725-5850.
* The VHT *Capabilities* IE still advertises `SupportedChannelWidthSet=0` (20/40) even
  though the operation element says 80 MHz.  That bit is inherited from the driver's
  `hw vht capab: 0x1b07031`, which has it clear -- the vendor driver claims 20/40 in its
  capability IE while running 80 MHz.  A client that trusts the operation element gets
  80 MHz, which is why the acceptance test is a real client's link rate, not the beacon.

### 20.5 The old "HT_SCAN hang" note, corrected

The earlier commits (fdc0494 and a38122d) disagreed about whether pre-setting the channel
while the interface was down helped.  It did not matter either way: what changed between
"hangs in HT_SCAN" and the measurements above is the country.  hostapd's 40 MHz
coexistence scan (`Scan for neighboring BSSes prior to enabling 40 MHz channel`) does run
and complete in the working case; with every 5 GHz channel NO-IR it had nothing to settle
on and never left `HT_SCAN`.


## 22. The baseband CP assert: the URC channel, the RIL-shaped AT channel, the watchdog

### The symptom, and the empty run

A boot brings the bearer up (`+CPIN: READY`, `+CEREG: 2,1,...,11` = NR SA,
`AT+CGDATA="M-ETHER",1`, `sipa_eth0` with its address and a `metric 100` default
route), and at about 9.5 minutes the CP stops answering.  The kernel log then
carries the CP's own words:

    modem cmd Modem Assert: MN_AL Task PS CP assert in file
    MS_System/RTOS/source/src_osa/c/threadx_os_iram.c line 1115
    exp=ASSERT: Error 0xb, The queue was full info=[], [dfs=5]

Trusty restarts the CP (`enter SEC_KBC_START_CP` -> `kbc_start_cp() enter
MODEM_IMG`) and the AT channel does not come back; only a reboot recovers it.  The
empty run settled the trigger: with `e5-mobile-data` and its watcher stopped and
no AT at all, **uptime 17 minutes passed with zero `CP assert` hits**, while a
session that polls AT died at ~9.5 minutes.

### The two channels

Measured on 2026-09-18 with the watcher stopped and nobody holding a channel:

* `/dev/stty_nr0` is the **URC channel**.  Opening it dumps the queue that piled
  up since the last reader: `+SIND: 1`, `+SIND: 10,"SM",1,"FD",1,...`,
  `+ECIND: 3,0,0,1`, `+ECIND: 3,6,1`, `+CMGW: ME is full`, `+PRENWINFU:"46001"`,
  `+CREG: 2`, `+CEREG: 2`, then a periodic `+CSQ: 255,99` / `+CESQ:
  99,99,255,255,255,255,75,67,73` pair (signal fields invalid, ME storage full),
  and later the bearer events `+CGEV: ME PDN ACT 1` / `+SPPCODATA: 1`.  A 45 s
  read produced tens of lines, a later 8 s read 63 lines (~6 lines/s).
* `/dev/stty_nr1` is a **clean command channel**: it stays silent while idle and
  answers `AT`, `AT+CEREG?`, `AT+COPS?` normally.  MU300-linux saw the same
  `nr0`=URC / `nr1`=command split on the same modem family.

Our code never read `nr0` at all, and `mobile-data`'s `at()` opened
`/dev/stty_nr1`, drained 0.2 s of backlog, wrote one command, read to `OK` and
closed the port again -- for every command, every 30 s, from the bearer watcher.
Android's RIL does the opposite: it holds the channel open for the lifetime of
the boot and reads the URC stream continuously (`urild` is the process that does
it on this device).

### A second, different death: AT dies without an assert

On 2026-09-18 22:03-22:09 the AT server was observed dying on its own, with the
watcher stopped and nobody holding either channel:

* 22:03:14 (`uptime 1765`) a bare `AT` on `nr1` answered `OK`, and an `nr0` read
  dumped the URC backlog above;
* by 22:07 both channels returned nothing at all, and at 22:09 a bare `AT`
  produced no `OK`, no `ERROR` and no URC -- no process had the channel open;
* `dmesg` `CP assert` hits = 0, there was no `kbc_start_cp` after boot, and
  `busybox wget` through `sipa_eth0` still worked (the address stayed up).

So "the AT channel is dead" and "the CP has asserted" are not the same event, and
the bearer can keep passing traffic after AT is gone.  A watchdog has to key on
AT's silence, not on the CP assert appearing in dmesg.

### The fix: a persistent, RIL-shaped AT channel

`rootfs/overlay/opt/e5/atd.py` (`e5-atd.service`) is a small daemon that opens
`nr0` and `nr1` **once** and keeps them open for the whole boot:

* it drains `nr0` continuously into `/var/log/e5-atd.urc` (rotated at 256 KiB)
  and never closes the port;
* commands from `mobile-data` arrive on the `/run/e5-atd.sock` unix socket and are
  serialised with a 0.3 s minimum gap, one in flight at a time, with an 8 s
  timeout, so no caller can flood the CP;
* URCs are interleaved with the command's own response rather than being lost;
* when idle for 60 s it sends a bare `AT` and records the answer as the liveness
  signal, and it publishes `/run/e5-atd.state` (JSON: `last_ok`, `last_rx`,
  `urc_lines`, `commands`, `fails`, channel flags) for the watchdog;
* the channels are reopened with backoff if they disappear, so a CP restart no
  longer leaves a dead port behind.

`mobile-data` asks for its AT through the daemon (`at()` falls back to the old
direct path only if `/opt/e5/atd.py` is not installed), and its watcher now
checks the interface every 30 s but asks the modem about `+CEREG?`/`+CGACT?` only
once every five minutes instead of every 30 s.

Measured after deploying it (2026-09-18, uptime 31 min, watcher up for 17 min):
`CP assert` hits = 0, `AT+COPS?` -> `+COPS: 0,2,"46001",11`, `sipa_eth0` still up
and `busybox wget http://mirror.nju.edu.cn/...` fine -- where the previous
regime asserted at ~9.5 minutes.  (Correlation, not proof: the watcher's AT
volume is now ~1.4 commands/min against ~4/min before, so either the persistent
channel or the lower rate may be what helps.  The daemon does both, which is what
the RIL does.)

### The watchdog

There is no userspace modem reset on this board: `/sys/class/misc` has no modem
node and restarting `e5-vendor.service` sends `cmd 0x43c84e06`, which only
re-triggers the same assert 19 s later.  So the honest recovery for a silent AT
channel is a reboot, done by `rootfs/overlay/opt/e5/cp-watchdog`
(`e5-cp-watchdog.service`, `/etc/e5/cp-watchdog.conf`):

* dead = the daemon's `last_ok` is older than `DEAD_AFTER` (default 120 s);
* on death it appends the evidence to `/var/log/e5-cp-watchdog.log` -- uptime,
  the atd state, the last URCs, the `modem`/`CP assert`/`kbc_*` lines from dmesg
  and `ip -s link show sipa_eth0` -- then re-arms the boot slot
  (`/usr/local/sbin/e5-boot-ok`, which matters because `e5-boot-ok.service` is
  disabled on the device right now and a plain reboot would otherwise fall back
  to Android) and runs `systemctl reboot`;
* `GUARD` (900 s) refuses a second watchdog reboot inside the window and only
  logs it, so a CP that dies again immediately cannot turn into a boot loop;
* `ACTION=log` observes without rebooting, and `--simulate` was used to test the
  decision: with a fake state whose `last_ok` was 400 s old, the watchdog
  reported "AT channel has not answered for 415 s" with the evidence block at the
  first check and refused to reboot under `ACTION=log`.

## 23. The two open documentation debts, paid

* **Identity strings.**  `rootfs/overlay/etc/machine-info` sets `PRETTY_HOSTNAME=
  Rongyue E5` (the static hostname cannot contain a space, so the login prompt
  keeps `e5-linux`).  `HARDWARE_VENDOR`/`HARDWARE_MODEL` are deliberately unset --
  they fill the "Hardware Model" row, while the part name belongs in "Processor",
  which is built from `/proc/cpuinfo` and is therefore set in the kernel
  (`kernel/patches/0009` prints `Processor: Unisoc T158`).
* **The 32 s shutdown.**  Measured 2026-09-18: everything stops inside 1.3 s
  (`bluetooth.service` in 0.25 s) and the journal is then silent from
  NetworkManager's `modem-manager: ModemManager no longer available` at
  14:57:01.108 until NM's own `exiting (success)` at 14:57:33.001 -- NM waits on
  device teardown that does not complete here (the WLAN firmware does not answer
  a disconnect promptly).  `NetworkManager.service.d/20-e5-shutdown-timeout.conf`
  (`TimeoutStopSec=5`) did not shorten the total in the one test after it: NM's
  stop is issued late in the sequence, so the time is spent before it is reached.
  Re-measure on a booted image before believing anything else here.


## 24. Audio: the AP path streams, ALSA never sees a period, and the AGDSP is the missing piece

The vendor sound stack does come up on this port -- card `sprdphone-sc2730`, codec
`ump9620`, the AW87xxx smart PA on i2c 6-0058 parsing its profile out of
`aw87xxx_acf.bin` -- but two things must also be true before a PCM can even be
opened, and a third before an ALSA client can finish a buffer.

### 24.1 What the stack needs to load

* The audio modules (`sound/soc/sprd/unisoc/*` + `drivers/unisoc_platform/sprd_audio/*`,
  24 modules) are loaded from the initramfs by a name list, so their *order* is ours.
  `sprd_dmaengine_pcm` failed with `Unknown symbol get_sp_audio_debug_flag /
  sprd_tdm_dai_to_config / sprd_mmap_fd_set (err -2)` because two of those three are
  exported by `snd_soc_sprd_card.ko`, which was listed *after* it; deriving the order
  from real symbol dependencies (`nm -g --defined-only` / `-u`) fixed that, and
  `stage=modules-done loaded=91 failed=0` is the check that it stayed fixed.
* The ASoC card also wants the AGDSP power domain.  With `agdsp_pd.ko` absent or
  neutralised, `asoc_sprd_card_parse_of: Parsing dai link 0 failed(-517)` loops
  forever, because the codec and the VBC DAI name that domain as their
  `power-domains` provider.  The three variants that were tried are in the STATUS
  narrative; the tree carries the hybrid one now (no legacy `smsg` kthread, PMU state
  read before the mailbox wake, no vendor power-off sequence).

### 24.2 The AP path itself works

Two controls turn "the DMA runs one burst and stops" into "the VBC FIFO drains":

* `agdsp_access_en` = 1, which is `REG_AON_APB_AUDCP_CTRL` (0x6490014c) bit 5,
  `MASK_AON_APB_AP_2_AUD_ACCESS_EN`.  It opens AP access to the AGCP domain, and with
  it the `audcp-{vbc,aud,dma-ap,mcdt,icu,tmr-26m,dvfs-aspb,intc}-eb` clocks match
  Android's.  Measured: 0x6490014c reads 0x20 with it, and the DMA pointer then
  advances and wraps instead of stalling after a single 640-byte burst.
* `VBC DAC0 DG Set` must be non-zero (Android runs it at 39,39).  Linux leaves it at
  0, which is digital silence however well the route is wired.

The full list is `/root/e5-spk-recipe.sh` on the device, derived by diffing Android's
mixer state (`/system/bin/tinymix`) while it was playing a ringtone against Linux's
idle state.  With it applied a playback to `hw:0,0` really does stream: with the two
AGCP DMA channels enabled (`GLB_CHN_EN_STS` 0x5665001c = 0x3), the VBC playback FIFO
status (0x56510034) walks 0x29c21 -> 0xd4a1 -> 0x1a0c1 -> 0x17ce1 as the DMA consumes
it.

### 24.3 The blocker: no period boundary ever reaches ALSA

Measured during that playback (`busybox devmem`):

| where | register | value |
| --- | --- | --- |
| AGCP DMA @0x56650000 | `GLB_INT_RAW_STS` 0x10 | 0x3 |
| | `GLB_INT_MSK_STS` 0x14 | 0x3 |
| | `GLB_REQ_STS` 0x18 | 0x0 |
| | `GLB_CHN_EN_STS` 0x1c | 0x3 |
| VBC AP regs @0x56510000 | `AUDPLY_FIFO_CTRL` 0x20 | 0x00f00650 |
| | `AUD_EN` 0x2c | 0x300 |
| | `AUDPLY_FIFO0_STS` 0x34 | moving |
| | `AUD_INT_EN` 0x44 | 0x4 |
| | `AUD_INT_STS` 0x48 | 0x10 (sticky) |
| | `AUD_CHNL_INT_SEL` 0x4c | 0x0000 |
| | `AUD_DMA_EN` 0x50 | 0x3 |

Both interrupt-status registers sit pending and are never cleared, and the
`/proc/interrupts` lines `28: GICv3 251 sprd_dma` (AP DMA) and `40: GICv3 87
sprd_dma` -- the DT's `agcp_dma@56650000`, `interrupts = <GIC_SPI 55>` -- both stay
at 0 for the whole run.  The data path completes, the completion *event* does not:
nothing in the vendor audio tree calls `snd_pcm_period_elapsed()` except the DMA
callback `sprd_pcm_dma_buf_done()`, and that callback never runs.

Two definitions the routing would need are dead code here: `REG_VBC_AUD_CHNL_INT_SEL`
(0x004c, the AP/DSP channel-interrupt selector) and its DSP-window twin
`REG_VBC_CHNL_INT_SEL` (`VBC_DSP_ADDR_BASE + 0x0f74`) are *defined but never
written*, and `REG_VBC_AUD_INT_EN` (0x0044) has no writer either.  On Android that is
the AGDSP firmware's job -- the one piece this port does not run.

What that does to a plain ALSA client:

* `sprd_pcm_pointer()` is not the problem.  It returns
  `dmaengine_tx_status().residue`, and `sprd_dma_tx_status()` reads the *live*
  channel address (`sprd_dma_get_src_addr()` / `sprd_dma_get_dst_addr()`) whenever the
  descriptor is the current one, so the position is accurate without a single
  interrupt.
* ALSA's *cached* `hw_ptr`, however, only moves when the driver calls
  `snd_pcm_period_elapsed()`.  Probe on `hw:0,0`: the first two 4096-frame blocking
  writes return immediately (avail 5504 -> 1408), the third blocks and never returns,
  and `snd_pcm_drain()` then waits forever because its loop only breaks on the state
  change a period tick would have produced.  `aplay` prints `Playing WAVE ...` and
  hangs in exactly the same place.
* Android never sees this because its HAL opens the PCM with `PCM_NOIRQ`
  (`SNDRV_PCM_HW_PARAMS_NO_PERIOD_WAKEUP`): `sprd-dmaengine-pcm.c` then builds the
  link-list node with `SPRD_DMA_FLAGS(0, 0, SPRD_DMA_FRAG_REQ, SPRD_DMA_NO_INT)` and
  registers no callback at all -- it feeds the DMA from a timer and never waits on a
  period.  `p_wakeup = !(params->flags & SNDRV_PCM_HW_PARAMS_NO_PERIOD_WAKEUP)` is the
  whole difference.

### 24.4 The tried fix, reverted, and the two traps in it

A software period ticker calling `snd_pcm_period_elapsed()` (module parameter
`period_timer`, delay `period_size / rate`) was added to `sprd-dmaengine-pcm.c` and
tried as a `timer_list` and then as a `delayed_work`.  Both images panicked within
about a minute of the desktop session opening the PCM, so the change was dropped in
full and the trigger was never isolated.  What the attempt did establish:

* **A softirq cannot be the context.**  `normal_dma_protect_spin_lock()` is
  `spin_lock(&pm_dma->pm_splk_dma_prot)` -- plain `spin_lock()`, no irqsave -- and
  `sprd_pcm_pointer()` takes it for the normal playback streams, as do
  open/hw_params/trigger/hw_free/close.  A timer that lands on a CPU already inside one
  of those sections spins on a lock that CPU can only release after the softirq
  returns: a soft lockup, and this configuration panics on one
  (`CONFIG_BOOTPARAM_SOFTLOCKUP_PANIC=y`, `CONFIG_BOOTPARAM_HUNG_TASK_PANIC=y`).  A
  workqueue removes that self-deadlock, but the second image still died.
* **Do not cancel synchronously where a tick can re-enter.**  A period tick can drive
  `snd_pcm_stop()` into the driver's `trigger(STOP)`, so anything armed there must use
  `cancel_delayed_work()`; only `sprd_pcm_close()` may use the `_sync` form, and ALSA
  does reach it without the stream lock (`snd_pcm_release_substream()` calls
  `do_hw_free()` and `ops->close()` outside the lock).  `sprd_pcm_hw_free()` releases
  the DMA channels and `sprd_pcm_close()` frees `rtd`, so the tick has to be stopped
  before either.

No panic text survived: `sysdump.ko` is not in the image, so `sysdumpdb` still holds
only Android's old reports, and `/sys/fs/pstore` stays empty even though ramoops
registers as a backend.  The one thing that did work is the 4 MiB block at 56 MiB
inside `boot_b` that `boot/init` rewrites every 15 s
(`dd if=/dev/block/by-name/boot_b bs=1M skip=56 count=8` from Android reads it back):
it stops at `switch-root`, so a copy of that loop inside the real rootfs is what
captured the last `dmesg` before a post-switch-root death.

### 24.5 Two boot traps found while chasing the panics

* **`sysctl.kernel.panic_on_oops=0` must stay in the cmdline.**  This config sets
  `CONFIG_PANIC_ON_OOPS=y`, and the image has a pre-existing oops at ~25 s:
  `Unable to handle kernel paging request at virtual address ffffffc00ac1b7d8` with
  `string -> vsnprintf -> add_uevent_var -> kobject_uevent_env -> kobject_synth_uevent
  -> uevent_store`.  An image whose cmdline dropped the parameter panics on that same
  oops; with it, the task dies and the boot continues.  The `_regulator_disable`
  WARNING (`drivers/regulator/core.c:3002`, twice a boot) and the `dev_watchdog`
  TX-timeout WARNING (`net/sched/sch_generic.c:481`) are noise.
* **From Android, arm the slot and reset with sysrq, not `adb reboot`.**  Android's
  init rewrites the A/B metadata on a clean reboot, so a slot-b BCB written just before
  `adb reboot` is lost and the device comes back on slot a.
  `echo 1 > /proc/sys/kernel/sysrq; echo b > /proc/sysrq-trigger` resets without that
  rewrite and boots the armed slot (verified both ways).

### 24.6 What is still open

* Route the completion interrupt to the AP: find who is supposed to write
  `REG_VBC_AUD_CHNL_INT_SEL` / `REG_VBC_AUD_INT_EN`, or whether the AGCP DMA line is
  simply not wired to the GIC on this part.  The AGDSP firmware is the suspect for
  both, and it is not running here.
* Or tick the period from a context that cannot deadlock on `pm_splk_dma_prot` -- a
  kthread with a try-lock, or making that lock irqsave where the process-context paths
  take it -- and stop it before `sprd_pcm_hw_free()` / `sprd_pcm_close()`.
* Or sidestep the question for a first audibility test: open the PCM
  `PCM_NOIRQ`-style (`SNDRV_PCM_HW_PARAMS_NO_PERIOD_WAKEUP`), feed it at a fixed rate
  and listen.  That path needs no interrupt at all, and it is the one Android uses.

## 25. The first on-device takeover: `unisoc-cpd` as the only reader of the AT channel (G2)

_2026-09-20, on the handset booted into Android (slot a), rooted, `urild` the
incumbent owner.  Everything below was done over `adb` with `su`; the binary is
the static `aarch64-unknown-linux-musl` build pushed to
`/data/local/tmp/ucpd/` with the e5 profile beside it.  The whole session ran
with `vendor.modem_control` left alone — the CP stays booted when only the RIL
is stopped._

### 25.1 Who holds the channel, before and after

A `/proc/*/fd` scan for `stty_nr0/nr1` is the honest statement of ownership:

* with Android up: exactly one holder, `/vendor/bin/hw/urild`
  (`init.svc.vendor.ril-daemon`); `slogmodem` runs but holds only `slog_*`;
* after `stop vendor.ril-daemon`: **no holder at all** — the channel is free,
  and the takeover is a plain open, not a race.

### 25.2 What worked, first try

As the only reader, every probe and every capability answered:

* `link --seconds 30 --interval 10`: 3/3 probes OK at ~200 ms, **0 timeouts,
  0 errors**, 16 URC lines with `max_gap 0.0 s`, mailbox IRQ delta 41;
* `sim`: `+CPIN: READY` — matches Android's `gsm.sim.state = LOADED,LOADED`;
* `serve` (100 s) + a client over the socket: `sim` and `register status`
  answered through the daemon, and `state` reported `channels.cmd.opens: 1`,
  `reopens: 0` — one open for the whole window, which is the entire point of
  the resident owner;
* the socket `urc` query returned decoded events: the CP pairs a `+CSQ` and a
  `+CESQ` URC roughly twice a second once registered, and the decoder read
  **50 of 50 lines** (`urc_lines 50, decoded 50` — 100 %, no `urc-other`);
* `band lock lte 1 41` / `band lock nr 41 78` both took and read back exactly
  (`+SPLBAND=0` → `0,256,0,1,0`, `+SPLBAND=3` → `0,0,272`);
* 0 CP asserts from beginning to end of the session.

### 25.3 The one thing that did not work, and what actually brings the stack up

Stopping the RIL does not leave the modem runnable: its shutdown path parks the
radio at **`+CFUN: 0`** (`+CEREG: 2,0`, `+CSQ: 0,99`, every `+CESQ` field 255).
The recovery the contract already carried — `AT+SFUN=2`, `AT+SFUN=4` — sets
`+CFUN: 1` but **does not register**: five minutes of waiting stayed at
`+CEREG: 2,0` with no RF, and band locking (LTE b1/b41, NR n41/n78) changed
nothing.  What did work is the full cold cycle the Linux side's `radio_on`
uses:

    AT+CFUN=0 ; then AT+SFUN=2, AT+SFUN=4   →   75 s later:

    +CEREG: 2,1,"10002B","00592002",11      PS registered, home, AcT 11 = NR SA
    +CGATT: 1                               attached

— which matches the Android oracle for that SIM (46015 广电, NR_SA).  The
measurable conclusion: **after a RIL shutdown, `SFUN=2/4` alone is not stack
bring-up; the `CFUN=0 → SFUN=2/4` cold cycle is.**  (Conversely, a CP that
boots without a RIL at all — the Linux case, FINDINGS §22 — registers after
the plain `SFUN` pair, so it is the *RIL-shutdown state* that needs the cold
cycle, not the generation.)

### 25.4 `255` is "not reported", not "-115 dBm"

The unregistered CP answers `+CESQ: 99,99,255,255,255,255,…`, and the literal
`idx-140` mapping turned 255 into "RSRP 115 dBm" — a nonsense number a reader
will believe.  `decode_cesq` now returns `None` for a 255 field and the
display says `not reported`; a *reported* field still decodes (the same line's
SS-SINR 73 → 26.5 dB).

### 25.5 The procedure error the session made, and the rule it fixes

Restoring the vendor side, `start vendor.ril-daemon` was issued while the
100 s `serve` was still alive: the fd scan then showed **`unisoc-cpd` and
`urild` holding the channels at the same time** — the plan's only red line,
violated by sequencing, not by the code (the flock is advisory and `urild`
never takes it; it only coordinates our own instances).  Nothing broke — and
the session had one clean piece of evidence that the daemon *noticed*: its
idle probe failed exactly once, in that window.  The rule for every future
transfer, in both directions:

> **never `start` the other owner until our daemon has exited and the fd scan
> shows the channel free; never `serve` past the point the other side is told
> to start.**  Verify with the `/proc/*/fd` scan, not with an assumption.

### 25.6 Left changed on the device: nothing

The band experiment was reverted before the RIL came back: LTE re-locked to
the RIL's own set (read back `+SPLBAND: 0,482,2056,213,0` = bands
1,3,5,7,8,20,28,34,38,39,40,41) and NR unlocked (`+SPLBAND=2,0,0,0,0`,
read back `(none)`).  After `start vendor.ril-daemon`: `LOADED,LOADED`,
`46015,46001`, `NR_SA,LTE` — identical to the pre-session baseline — and the
closing `diag asserts` read 0.

### 25.7 Second session: SMS surface, the MT path works, the MO path does not

_2026-09-20, same setup (Android slot a, daemon as the only reader), with
`serve` held open for the whole session and clients on its socket._

* **The SMS surface the RIL leaves behind is hostile, and the daemon now
  re-arms it at start-up.**  Measured: `+CSCS: "HEX"` (under which
  `CMGS="<number>"` is not a phone number) and `+CNMI: 0,0,0,1,0` (mt=0 — new
  messages are stored *without* announcing them, so the `+CMTI:` path never
  starts).  `serve` now sets `CMGF=1`, `CSCS="GSM"` and `CNMI=2,1,0,0,0` once
  and reports all three in its `state`.
* **MT works end to end.**  A message sent to SIM1 announced itself with
  `+CMTI: "SM",1`; the daemon read it between requests with `AT+CMGR=1` and a
  client saw sender, status, service-centre timestamp and body — the body
  arriving as UCS2 hex (`"6D4B8BD5"` = 测试) under `CSCS="GSM"`, which the
  daemon now decodes.  Reading moved the message to `REC READ` and nothing
  was deleted.
* **MO does not work, and the encoding is not why.**  Text-mode submit:
  `+CMS ERROR: 313`.  PDU mode with the carrier SMSC read out of `AT+CSCA?`
  (stored as hex-of-ASCII by the RIL), then re-armed by hand: still
  `+CMS ERROR: 302`, national and international destination alike.  Since the
  same SIM *receives* (NAS SMS inbound), the remaining suspect is the
  SMS-over-IMS/NAS provisioning the vendor RIL performs — on SIPC channels
  other than `nr0`/`nr1`, which this takeover does not hold.  That is W5
  territory and is recorded as such.
* **Registration needed the band recipe, again.**  With the RIL stopped the
  stack came up (`+CFUN: 1`) but would not register until the bands were
  locked to **LTE b1/b41 + NR n41/n78** *and* the `CFUN=0 → SFUN=2/4` cold
  cycle was run — on this unit, an unbounded NR scan (移动/广电 bands) hangs.
  The locks stayed in place for the rest of the session.

### 25.8 The internet, restored under our bearer (G3's AT half)

With the RIL stopped the handset had no data — expected, because nothing
re-establishes the bearer.  What the session established, all measured:

* **The RIL's teardown destroys the internet context.**  `AT+CGACT?` after the
  stop shows only cid 11 active, and `AT+CGCONTRDP=11` names it `ims` — the
  VoLTE context survives, the internet one does not.  (Its interface
  addresses linger on `sipa_eth0`, which reads as "up" and is a lie: a ping
  has no route.)
* **A fresh context works.**  `CGDCONT=1,"IPV4V6","cbnet"` → `CGACT=1,1` →
  `CGCONTRDP` (address 10.x/8, DNS 43.239.172.x) → `CGDATA="M-ETHER",1` →
  `CONNECT` — the same sequence the contracts §4.1 carries, on the 广电 card.
* **Android's policy routing kills unknown bearers, twice.**  Rule
  `32000: from all unreachable` swallows any packet whose lookup does not
  match an earlier table, so a main-table default is not enough; and the
  *return* path of a tethered client looks up the same tables after
  de-NAT.  The working recipe: default route in table **`legacy_system`**
  (matched at priority 18000 by unmarked traffic) *plus* the on-link subnets
  in that table (`10/8` via `sipa_eth0`, the hotspot's `192.168.43.0/24` via
  `wlan0`), so replies reach the client.
* **Tethering needs two more rules.**  `tetherctrl_FORWARD` carries a
  catch-all `DROP` and netd only inserts ACCEPT pairs for uplinks it knows —
  with the RIL stopped `sipa_eth0` is unknown, so 2670 client packets were
  dropped there.  `iptables -I tetherctrl_FORWARD` with the
  `wlan0 ↔ sipa_eth0` ACCEPT pair, plus `-t nat -A POSTROUTING -o sipa_eth0
  -j MASQUERADE`, and hotspot clients reached the internet.
* Client DNS still has to be set statically for now: DHCP advertises the
  upstream DNS netd knows, which is nothing.  All of these are runtime
  fixes; the permanent home is the daemon's `data up` plus the rootfs's own
  NAT (`e5_nat`) on the Linux side, which is the G3 acceptance itself.
