# Linux on the Rongyue E5 (Unisoc UMS9621)

A Linux bring-up for the Rongyue E5 5G handset/hotspot (`ums9158_1h10`,
Unisoc UMS9621 / qogirn6lite, Android 13), built the way
[mu300-linux](https://github.com/dikeckaan/mu300-linux) does it for the ZTE F50 /
MU300: a custom kernel from the device's own GPL kernel tree plus an initramfs
that brings up a USB gadget and switches into a full Linux root filesystem,
installed **next to Android** on slot b, without rewriting the partition table.

The kernel source is [`kernel_sprd_ums9158`](https://github.com/Enceka/kernel_sprd_ums9158)
(Google android13-5.15 GKI + the Unisoc UMS9621 platform, with the E5 device
support in it), rebuilt as a general-purpose Linux kernel by
`kernel/build-linux.sh` on top of the device's own `e5_rongyue_defconfig`.

> **Warning.** This writes to `boot_b` and to 32 bytes of `misc`. It relies on
> the bootloader falling back to slot a, which is the mechanism mu300-linux
> documents for this bootloader family but which has **not** been verified on
> this exact device. You can brick or lose data. Nothing here is endorsed by
> Unisoc or by Rongyue.
>
> **Battery.** Charging works, but only because `aw32257_charger.ko` is loaded.
> The driver does not share a name with the hardware it drives, and while it is
> missing the charger also blocks USB entirely — `fw_devlink` inspects the USB
> controller's devicetree suppliers before its probe function runs, and the
> charger is one of them (`docs/FINDINGS.md` section 7.2). A real session also has
> to be kept alive: `boot/init` reboots back to Android after ten minutes unless you
> create `/run/stay`, and a session currently dies on its own after roughly five
> minutes in a silent reset (`docs/FINDINGS.md` section 9). Do not leave a Linux
> session unattended — the modem is not brought up and nothing is watching the PM.

## Why this is not a copy of mu300-linux

Four things are materially different on the E5, and each one changed the design:

| | MU300 (UMS9620) | Rongyue E5 (UMS9621) |
|---|---|---|
| free eMMC | unpartitioned space after `userdata` | **none** — `userdata` ends exactly at the GPT's last usable LBA |
| where the ramdisk comes from | `boot` | `boot` (LK falls back to `init_boot` only if `boot`'s is empty) |
| kernel | 5.4.254 from ZTE GPL source | 5.15.211 GKI + Unisoc platform from the E5 tree |

Because there is no free space, the root filesystem lives in a loop file inside
Android's `/data` (`/data/e5linux/rootfs.ext4`) rather than in a partition of
its own. That keeps the "never touch the GPT" property the project inherited.

Read [`docs/FINDINGS.md`](docs/FINDINGS.md) for the measurements behind every
one of these claims — the bootloader log that shows which ramdisk LK picks, the
live `misc` `bootloader_control`, the exact GPT arithmetic, and the log
channels that survive a failed boot.

## Status

| Feature | State |
|---|---|
| Custom Linux kernel (5.15.211, `e5_rongyue_defconfig` + Linux fragment) | ✅ builds |
| Boot image builder (slot b, stock header/vbmeta/footer preserved) | ✅ |
| Ramdisk in boot.img (LK's generic ramdisk path) | ✅ verified in the stock LK log |
| `boot_b` trial + one-shot slot arming in `misc` | ✅ **boots** |
| Rollback to Android when Linux never reaches userspace | ✅ verified — the device lands back on slot a |
| Initramfs: 67 dependency-ordered modules, USB ECM + ACM console | ✅ |
| **Linux boots on the device** | ✅ **67/67 modules load, nothing left deferred** |
| USB gadget network (NCM, 192.168.77.1, DHCP via systemd-networkd) | ✅ verified live: host gets 192.168.77.x, ping 0% loss |
| Battery charging under Linux | ✅ **verified — `battery/status = Charging`** |
| DRM/KMS display (480x320 DSI panel, now `card1` -- panfrost takes `card0`) | ✅ phoc modesets it (active plane `320x480`, `allocated by = phoc.orig`) |
| Debian 13 + Phosh root filesystem | ✅ SDDM autologins `phosh.desktop` |
| Phosh session (phoc, wlroots' GLES2 renderer on the Mali-G57) | ✅ **verified** — `GL renderer: Mali-G57 (Panfrost)`, and the clients are on it too; docs/FINDINGS.md section 20.7 |
| Re-arm from inside Linux (`e5-boot-ok`) | ✅ verified, `misc` byte-compared |
| Touch panel under Linux | ✅ **works** — `tlsc6x_touch` on `event1`, udev tags it `ID_INPUT_TOUCHSCREEN=1`, and phoc takes its events |
| Wi-Fi | ✅ **verified on the device** — `sprd_wlan_combo` + `wcn_bsp` on the WCN chip, scans 2.4 and 5 GHz APs out of the box (needs the firmware in the initramfs overlay and the vendor's *user* build variant); docs/FINDINGS.md sections 8.5-8.6 |
| Bluetooth | ⏳ **open** — the controller attaches and `hci0` comes up (`e5-bt-attach.service` holds `/dev/ttyBT0`), bluez reports `Powered: yes`, and scans have found devices (7 LE, 4 BR/EDR); but one attach can fail and never recover, and after repeated BT power cycles the chip stops answering the scan commands (`0x2041`/`0x2042 tx timeout`), so a scan can come up empty. Pairing/connecting untested (one settings-app attempt: `Page Timeout`). BD address is the chip's default, not the factory MAC -- docs/STATUS.md "open" list and docs/FINDINGS.md section 8.7 |
| Session lifetime | ✅ fixed: the ~295 s silent reset was the PMIC watchdog; staging sprd_pmic_wdt.ko (which feeds it) gives sessions that run 10+ min -- docs/FINDINGS.md section 9 |
| Modem / audio | ✗ not attempted, no UCM port |

## Repository layout

| Path | Contents |
|---|---|
| `kernel/` | `e5-linux.fragment` (Linux additions on top of the device defconfig), `build-linux.sh` |
| `boot/` | `init` (initramfs), `build-boot-image.py`, `module-order.stock`, `stage-modules.sh`, `flash-trial.sh`, `android-boot-linux.sh` |
| `rootfs/` | `fetch-debian-rootfs.py`, `e5-chroot.sh`, `install-packages.sh`, `packages.list`, `build-rootfs.sh` |
| `tools/` | `collect-logs.sh` and device helpers |
| `docs/` | `FINDINGS.md` |

**Not included**: stock firmware, Android vendor binaries, device dumps. The
scripts read those from *your* device.

## Requirements

* A Rongyue E5 with an unlocked bootloader (`ro.boot.verifiedbootstate=orange`),
  rooted Android with working `adb` + `su`, and a way to recover (SPD download
  mode or a known-good stock image).
* Linux build host with `clang`/`lld` (LLVM), `make`, `python3`, `lz4`.
* Dumps you make yourself: a stock slot-b boot image and the first 4 KiB of
  `misc` (see below).

## Build and run

### 0. Dumps

```sh
mkdir -p dumps
adb shell 'su -c "dd if=/dev/block/by-name/boot_b of=/data/local/tmp/boot_b.img"'
adb pull /data/local/tmp/boot_b.img dumps/boot_b.img
adb shell 'su -c "dd if=/dev/block/by-name/misc of=/data/local/tmp/misc.bin bs=4096 count=1"'
adb pull /data/local/tmp/misc.bin dumps/misc-head.bin
```

### 1. Kernel

```sh
git clone https://github.com/Enceka/kernel_sprd_ums9158
KERNEL_TREE=$PWD/kernel_sprd_ums9158 kernel/build-linux.sh
```

This merges `kernel/e5-linux.fragment` into
`arch/arm64/configs/e5_rongyue_defconfig` (the E5's own defconfig), fails loudly
if a symbol the initramfs depends on did not survive, and builds
`Image` + modules + DTBs into `out_linux/`.

### 2. Modules and initramfs

```sh
boot/stage-modules.sh          # -> out_modules/, boot/module-order.txt
```

The initramfs `insmod`s those modules in the **stock first-stage order**, not
alphabetically; see `docs/FINDINGS.md` §3 for why that is not a nitpick.

A static arm64 busybox is needed for the initramfs:

```sh
curl -O http://ports.ubuntu.com/ubuntu-ports/pool/main/b/busybox/busybox-static_1.36.1-6ubuntu3.1_arm64.deb
ar x busybox-static_*.deb && tar --zstd -xf data.tar.zst ./usr/bin/busybox
```

### 3. Boot image

```sh
boot/build-boot-image.py \
  --stock-boot dumps/boot_b.img --misc-head dumps/misc-head.bin \
  --kernel out_linux/arch/arm64/boot/Image --modules out_modules \
  --busybox work/busybox/ext/usr/bin/busybox --overlay rootfs/overlay \
  --out boot-linux-slotb.img
```

It writes `boot-linux-slotb.img`, a `.json` manifest and a
`.misc-slot-b-trial.bin` slot-arming block.

**`--overlay` is not optional.**  Without it the initramfs carries no
`e5-overlay/` at all: no `wcnmodem.bin`, no systemd units, no `/etc/environment` --
the device boots, but as a bare system with no Wi-Fi firmware and no services.
The builder packs the overlay with `a+r` (and `a+rx` for executables) rather than
whatever mode the checkout happens to have; a 0600 `phoc.ini` from a build host
with a strict umask once cost the `e5` user its entire session.

### 4. Trial boot

```sh
boot/flash-trial.sh boot-linux-slotb.img
```

Writes **only** `boot_b` and the 32-byte `bootloader_control` in `misc`;
`boot_a`, `init_boot_*`, `vendor_boot_*`, the GPT and `userdata` are never
touched. The script verifies the image hash locally, on the device, and on the
partition before it arms the slot, and refuses to run if the live `misc` block
is not the expected slot-a state.

With no root filesystem installed yet, the device comes up as a standalone Linux:
telnet `192.168.77.1` (or the USB CDC-ACM console) — and reboots back to Android
after ten minutes (the safety timer, which a real session stops), or if the kernel
panics. To boot the Linux image already in
`boot_b` again without reflashing:

```sh
boot/android-boot-linux.sh boot-linux-slotb.img
```

### 5. Read the result

```sh
tools/collect-logs.sh logs
```

Pulls `/sys/fs/pstore/*`, the 4 MiB persistent log inside `boot_b` and the
bootloader log. `E5-LINUX: stage=…` lines in the pstore console are the
initramfs reporting progress.

## Credits and licenses

* Kernel source: Google android13-5.15 GKI and the Unisoc UMS9621 platform, as
  published in `Enceka/kernel_sprd_ums9158` — GPL-2.0.
* The approach, repository layout and several scripts are derived from
  [`dikeckaan/mu300-linux`](https://github.com/dikeckaan/mu300-linux) (MIT).
* Scripts, tools and documentation in this repository: MIT (see `LICENSE`).
* Stock firmware, Android vendor components and bootloaders belong to their
  owners and are not distributed here.
