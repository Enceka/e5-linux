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
