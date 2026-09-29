# Mainline (LTS) kernel on the E5

The E5's own kernel is Unisoc's android13-5.15 GKI tree (`kernel_sprd_ums9158`, `kernel/build-linux.sh`). This
directory brings up **mainline Linux 6.18.y** (the current longterm series) instead, with the aim of the same
features: the modelled layout and most of the method are mu300-linux's (`mu300-linux/upstream`, mainline 6.18
on the ZTE MU300, UMS9620 -- the E5's UMS9621 is the "lite" member of the same qogirn6 family).

* **Kernel:** `linux-lts-e5/`, a repository of its own (https://github.com/Enceka/linux-lts-e5), branch
  `e5-6.18` on top of the stable tag (`v6.18.54`, remote `stable` = kernel.org's stable tree). The port is
  commits there, not a patch series here: a vendor driver comes in as one commit, a fix to it as another.
* **This directory:** how it is built, configured, booted and checked.

| file | what |
|---|---|
| `Dockerfile` | the build container (Ubuntu 26.04, gcc 15, native arm64) |
| `build.sh` | builds `linux-lts-e5` in the container: `out/Image`, `out/Image.lk`, `out/config`, `System.map`, `modules.builtin*`, `modules/`; `E5_RELEASE=1`: the kernel of a flash package, without `e5.openwrt=`, into `out-release/` |
| `e5-mainline.config` | the config fragment, merged on top of `allnoconfig`; an option Kconfig does not take stops the build (`config-ignored.txt` for known exceptions) |
| `wrap-image.py` | LK copies the kernel to 0x80080000; the stub moves the entry to 0x80200000 (2 MiB aligned) |
| `init-bringup` | a probe init: logs devices, drivers, deferrals to kmsg and pmsg, warm-reboots |
| `make-boot.sh` | a slot-b boot image of the kernel and an init (`boot/build-boot-image.py`); `E5_UPSTREAM_OUT` for `out-release/` |
| `module-order.txt` | the modules `boot/init` loads from the initramfs, in the 5.15 order |
| `root-modules.txt`, `root-modules.sh` | the modules OpenWrt loads from its root (`sipc_wwan`, the audio stack): `out/root-modules.tar`, which the trial scripts put into the trial root and a flash package's image carries |
| `audio-diag.sh` | on the device: the card, the PA, the mixer, the PCM's pointer, DAPM and the interrupts while a tone plays |
| `trial-from-openwrt.sh` | the next trial, flashed from a running OpenWrt trial over the USB LAN (no Android round trip) |
| `trial-from-android.sh` | the same from Android: `sipc_wwan.ko` into the trial root, then `boot/flash-trial.sh` |

```sh
docker build -t e5-mainline-build upstream/
upstream/build.sh                            # ~3 min from clean
upstream/make-boot.sh                        # work/boot-mainline.img
boot/flash-trial.sh work/boot-mainline.img   # from Android: one trial boot on slot b
# back in Android: /sys/fs/pstore/console-ramoops-0 and pmsg-ramoops-0 (tools/collect-logs.sh)
```

A flash package of this kernel -- OpenWrt on 6.18 as the installed system, not a trial -- is
`E5_RELEASE=1 upstream/build.sh` and then `E5_MAINLINE=1 openwrt/make-flash-bundle.sh` (see "Release" below).

A trial boot is safe by construction: slot b is armed with tries=2 and never marked successful, so the next
boot after it is Android's; a boot that hangs is reset by the PMIC watchdog LK arms (~295 s, FINDINGS 9).
The OpenWrt boot image that `boot_b` held before is kept as `/data/e5linux/boot_b-openwrt.img` on the phone.

## How it boots

* **Device tree:** the one LK builds (`ums9621-base` + the `ums9158_1h10` overlay from `dtbo`), unchanged;
  `/sys/firmware/fdt` of a running system is the reference (`work/mainline/e5-live.dts`).
* **Load address:** `boot_b kernel read OK, page size = 0x202c000, locate to 0x80080000` in `uboot_log`, the
  same as the MU300's LK: `wrap-image.py` unchanged. 0x80002000-0x87800000 is free RAM (sipc-mem follows).
* **Command line:** the kernel's own (`CONFIG_CMDLINE_FORCE`); LK's is Android's.
* **Reset:** through the UMP9620 PMIC (commit "spi: sprd-adi: add UMS9620 (UMP9620 PMIC) support with restart
  handler", from mu300-linux; the E5's 5.15 driver has the same register offsets).
* **Log:** ramoops@fff80000 from the stock DT (console, pmsg, dmesg records); it survives the warm reset.

## Status

| milestone | state |
|---|---|
| M1: the kernel boots on the vendor DTB, reaches /init, resets through the PMIC, leaves its log | **done 2026-09-27** (first try: userspace at 1.58 s, 8 CPUs, 1.5 GB, back in Android) |
| M2: clocks, PMIC + regulators, PMIC watchdog, eMMC, USB gadget (musb): `boot/init` starts OpenWrt | **done 2026-09-27** (pinctrl and the SD card slot are still to come) |
| M3: Wi-Fi and Bluetooth (marlin3lite over SDIO: wcn_bsp, sprd_wlan_combo, sprdbt_tty) | **done 2026-09-27** (hotspot on 5745 MHz beaconing, hci0 up with the factory address at boot) |
| M4: the modem (SIPC, SIPA, modem loader, Trusty) with ModemManager as on 5.15 | **done 2026-09-28** (5G NR, connected, data on sipa_eth0) |
| M5: display (sprd DRM, DSI panel), touch, keypad, vibrator | **mostly done 2026-09-28** (panel, fbcon, backlight, touch, keypad, gpio-keys, vibrator, RGB LED; not yet: DPU DVFS, GSP) |
| M6: charger, fuel gauge, thermal, cpufreq | **done 2026-09-28**: `aw322xx_charger` charging at 496 mA over USB, `sc27xx-fgu` reads the battery, charger-manager telemetry every 15 s; **25 thermal zones as on 5.15** (the SoC's 21 sensors, `soc-thmzone` with its 110 C trip, board/PA/charger, battery; below); cpufreq not ported (not loaded on 5.15 Linux either) |
| M7: audio (AGDSP, VBC, UMP9620 codec, aw87xxx PA) | **the DSP boots again (2026-09-28)**: the 24 modules load, the card `sprdphone-sc2730` registers, and the AGDSP image is written and started through `audiocp_boot` -- the first full trial had panicked there (`memset_io` on NULL+0x400): `audio_mem_vmap()` vmapped memory without pages (the DSP's IRAM, its no-map DDR) and returned NULL plus the page offset; it ioremaps it now (`8048e353a`, the class of `ce632be0c`). **The speaker plays (2026-09-28, heard)**: it had been silent because the DMA engine was not built (`CONFIG_DMADEVICES`: the vendor sprd-dma of `0015e503b` never compiled, every `hw_params` failed with -ENODEV); built in now, as on 5.15. **Capture works** (2026-09-28): the main mic on `hw:0,2`, mono S16, picks up the speaker's 880 Hz beep (97-345 against 0.1-0.3 of the room). The earpiece: routed as on 5.15, silent to the ear and to the mic -- the E5 may not have one; skipped. Call audio: not on 5.15 either |
| M8: GPU (Mali G57) | **done 2026-09-28**, brought forward (panfrost, as on 5.15; the info screen's cog renders through it) |

The target is what works on 5.15 today (`docs/STATUS.md`, `boot/module-order.txt`). Of that, not on 6.18 yet:
pinctrl (the DT's pin states are left as LK set them), the SD card slot (its controller waits for a cd-gpio), the
DPU's DVFS and the GSP 2D engine, and the USB/UART/JTAG pin mux (left out: the one trial with it built in lost
USB). Not on either kernel: call audio, cpufreq (5.15 Linux does not load it), the earpiece.

## Release (2026-09-28)

The flash package's kernel is the trial's with one difference: its command line has no `e5.openwrt=`, so
`boot/init` starts the installed `openwrt.ext4`, OpenWrt can be the default boot, and `e5-next-boot linux` and
the info screen's "默认启动" accept it. `E5_RELEASE=1 upstream/build.sh` builds it into `out-release/`, which the
trial scripts never read. `E5_MAINLINE=1 openwrt/make-flash-bundle.sh` then makes
`out/openwrt/e5-openwrt-flash-<version>-mainline-<date>-<git>.{tar.gz,zip}`: the boot image with `module-order.txt`'s
modules, and the generic OpenWrt image rebuilt with `root-modules.txt` in it (`build-rootfs.sh E5_ROOT_MODULES`,
next to the 5.15 modules, so the same image runs on either kernel). The package refuses a kernel with
`e5.openwrt=` in it and root modules of another build. It installs and updates like the 5.15 one (`flash.py`,
`--update` keeps the settings): first installed on the test E5 on 2026-09-28 by `--update` from 5.15, with
data, hotspot, modem, info screen, audio, Bluetooth and charging up after the first boot.

A boot that fails still falls back to Android (slot b is armed with two tries, marked successful by
`e5-boot-ok` once the system is up), as with the 5.15 packages.

### M1 (2026-09-27)

`logs/mainline-1`: 6.18.54-e5-00001-gaa5c239dfc44 reached userspace at 1.58 s with all 8 CPUs and
1,516,708 kB, ramoops and the ADI probed (the three PMIC slaves appeared as spi4.0-4.2), and the warm reset
through the PMIC returned to Android with the record intact. Deferred, as expected without a clock driver:
the four UARTs and the hwspinlock ("get hwspinlock clock failed").

### M2 (2026-09-27)

`linux-lts-e5` has the UMS9621 clocks (resets, frequency-table PLLs), the UMP9620/9621/9622 PMICs with their
regulators and eFuses, the PMIC watchdog, the r11p3 SDHCI (DLL phase, the eMMC at the 3.0 V of
"voltage-ranges", no polling of the SDIO-only WCN controller), the PMIC's Type-C controller, the USB2 PHY with
BC1.2 detection and the MUSB glue with its DMA. Measured on the device:

* eMMC in HS400ES at 200 MHz, 1.8 V signalling, 3.0 V supply: 500 MiB read in 1.69 s (~296 MB/s);
* the USB gadget at high speed: NCM + ACM, the Mac at 192.168.9.2;
* the PMIC watchdog taken over (a probe init stayed up for 797 s, LK's watchdog would have reset it at 295 s);
* **`boot/init` starts OpenWrt 25.12 on 6.18.54**: userdata (f2fs with quota, compression, encryption) mounted,
  the image loop-mounted, br-lan on 192.168.9.1, dnsmasq, dropbear, uhttpd/LuCI, rpcd, fw4 (the ruleset passes
  `fw4 check`); 94 MB used. What fails is what later milestones bring: the display (cage finds no DRM device),
  the modem, Wi-Fi, audio.

A trial boots a copy of the OpenWrt image: the kernel's command line has `e5.openwrt=openwrt-mainline.ext4`, and
`boot/init` then starts that file (and nothing else), with its default boot set to android, so that a
half-working system neither writes to the image in use nor makes itself the default. Make the copy in Android:
`cp /data/e5linux/openwrt.ext4 /data/e5linux/openwrt-mainline.ext4`, then
`upstream/make-boot.sh boot/init work/boot-mainline-openwrt.img` and `boot/flash-trial.sh` as before.
`boot_b`'s OpenWrt boot image goes back with `dd if=/data/e5linux/boot_b-openwrt.img of=/dev/block/by-name/boot_b`
and `flash.sh --boot-openwrt`.

Traps met on the way (the commits have the details): 6.x no longer puts DT interrupts into platform resources
(the MUSB child found no "mc" IRQ); the vendor DT names two eFuse cells alike, which 6.x's nvmem sysfs refuses;
`wakeup_source_register()` is a NULL stub without PM_SLEEP; userdata cannot be mounted read-write without QUOTA;
reading an unclocked peripheral through /dev/mem is an SError (boot/init's SoC watchdog diagnostic, now without
DEVMEM).

### M3 (2026-09-27)

The WCN drivers are Unisoc's 5.15 ones in `linux-lts-e5/drivers/unisoc_platform/` (the vendor's paths and symbols,
so each file still diffs against its origin), built as modules that `boot/init` loads from the initramfs in the
order of `module-order.txt`, `wcn_bsp.ko` after it copied the device's WCN firmware from userdata: `unisoc-mailbox`,
`sprd_power_manager`, `sipc-core` (the WCN core carries the integrated chips' SIPC transport, so the modem's IPC
comes first), `wcn_bsp`, `sprd_wlan_combo`, `sprdbt_tty`. `tools/port-api.py` does the mechanical part of the
5.15-to-6.18 move (renames, wakeup sources, void remove, headers 5.15 included through others); the rest is in
each driver's commit.

On the device: the chip's firmware boots (MARLIN3_20A_RLS2_W24.17.7), OpenWrt's hostapd runs the hotspot on channel
149/VHT80 (seen from a Mac at -40 dBm), and bluetoothd powers hci0 with the factory address (the vendor setup of
kernel/patches/0018 applies to 6.18 as it is; mu300-linux's link policy commit instead of 0008); a scan finds
devices. Two traps: `RFKILL_INPUT` (on by default, off on 5.15) lets the WCN tty's persistent, blocked switch block
every bluetooth switch, so hci0 refused to come up (ERFKILL) -- off, under EXPERT like the GKI config; and the
tool's first cut dropped `wakeup_source_remove()` where the vendor code has no destroy after it.

### M4 (2026-09-28)

The modem stack is Unisoc's 5.15 one, as modules in `module-order.txt`'s order (time sync, TSHM and the Trusty
log, the power manager, mailbox, SIPC with its ports and bridges, SIPA with sipa_eth and sipa_usb, the modem
loader, CP dump, IQ, URSP), and `sipc_wwan` loaded by OpenWrt's `e5-sipc-wwan` from the root's
`/lib/modules/<release>/modem` once the CP's AT channel exists; the CP is booted by Android's `modem_control` in
the vendor chroot, as on 5.15. On the device: `modem run = 1`, `CH Alive`/`Modem Alive`, ModemManager on
`wwan0at0` + `sipa_eth0`, connected on 5G NR; ping, DNS and HTTP over `sipa_eth0` (~16 Mbit/s from a mirror,
the RPS switch to the middle cores under load), fw4 masquerading the LAN onto it.

What it took besides the drivers:

* **Trusty.** `modem_control` has the TEE unlock the CP's DDR (`/dev/trusty-ipc-dev0`) before it loads anything:
  drivers/trusty of the same tree, built in as on 5.15 (log, TSHM, TUI modules), plus mu300-linux's fix -- the
  Android PSCI hooks that keep Trusty's CPU awake do not exist on mainline, so trusty-core polls it with NOPs
  while requests are in flight. Virtio's ID 13 is the balloon on mainline and Trusty IPC on Android.
* **The slot suffix** comes from LK's bootconfig behind the initrd (`androidboot.slot_suffix`), not the command
  line: `BOOT_CONFIG` + `BOOT_CONFIG_FORCE` (the forced command line lacks LK's `bootconfig`). Without it
  `modem_control` asked for `nr_fixnv1` with no suffix and retried forever.
* **The CP's region is no-map:** `vmap()` refuses its pfns on 6.x; smem ioremaps such regions.
* `PM_WAKELOCKS` (`/sys/power/wake_lock`), and SIPA's RPS switch looked for rx-0's `rps_cpus` in the ktype's
  default groups, which 6.18 keeps in the queue: a panic at the first burst of data, before the fix.

Both SIM cards (FINDINGS 47): `sipc_wwan card=<n>` puts `AT+SPACTCARD=<n>;` in front of every command the port
sends and takes that card's rings (`9ec968c3b`), and drains the other card's URC ring, without which the CP's AT
server stops answering within minutes (`cfbb848c9`); the second card's data is on `sipa_eth8`.

A trial's root is a copy, so its `sipc_wwan.ko` has to be put into the copy's `/lib/modules/<release>/modem`:
`trial-from-openwrt.sh img upstream/out/modules/sipc_wwan.ko:/lib/modules/<release>/modem/sipc_wwan.ko` does it
on the way; from Android, loop-mount the copy (SELinux has to be permissive for the loop mount).

### M5 and M8 (2026-09-28)

The display is Unisoc's KMS driver of the 5.15 tree (`drivers/unisoc_platform/sprd_disp`: DPU r6p1, the
qogirn6lite DSI host and PHY, the generic MIPI panel driver with the st7365p's timings from the DT, backlight, the
OCP2131 LCD bias), with its power domain (`drivers/soc/sprd/domain`, "sprd,vpu-pd") and IOMMU; the backlight's PWM
is mainline's pwm-sprd, which learned the UMS9620's channel stride and counter lengths. On the device: the panel
lights with fbcon on it (320x480 XR24, `/dev/fb0` as on 5.15), and OpenWrt's info screen -- cage running cog --
scans out its own buffer. The GPU is mainline panfrost with e5-linux's platform glue of 5.15 (`sprd,mali-natt`: the
kbase power-on sequence replayed from the DT's syscon triples, no devfreq, the vendor's upper-case IRQ names), which
cog's EGL needed: `mali-g57 id 0x9091`, `/dev/dri/renderD128`. Input as on 5.15: the gpio-keys (power, volume,
smart voice), the matrix keypad, the tlsc6x touch panel (on I2C, which mainline's i2c-sprd drives through the
DT's "sprd,sc9860-i2c" fallback), the PMIC vibrator (mainline, plus UMP9620); the PMIC's RGB LED is mainline's
leds-sc27xx-bltc plus UMP9620, with 5.15's names (`sc27xx:blue`).

The panel used to light only at ~32 s: the DPU's `iommus` points at the vendor's display IOMMU, whose driver
never calls `iommu_device_register()`, so `of_iommu_configure()` deferred the DPU until the deferred-probe
timeout ("ignoring dependency", pushed on by every module load). `aab3f8f6d` has `of_iommu` take the vendor's
`unisoc,iommu*` nodes as no IOMMU (the drivers map through the vendor's own API): `sprd_drm_bind()` at 6.9 s,
fbcon on the panel at 7.0 s, so the boot's kernel log scrolls on it.

What 6.18 broke on the way, besides the renames `port-api.py` does: `drm_open()` refuses fops without
`FOP_UNSIGNED_OFFSET` (the vendor's own fops: every open of card0 was EINVAL, and seatd could not hand it to cage);
fw_devlink lets the panel attach before the DSI binds (an e5-linux work item initialised in bind was then queued
uninitialised: a panic); genpd registers a device per domain name, and all the vendor's nodes are `power-domain`;
the panel created its proc entry again on every deferred probe.

### M6: thermal (2026-09-28)

The SoC's four sensor blocks (`sprd,thermal_r5p0`, 21 zones: the cores, cluster, GPU, MM, LTE/NR, the PHYs)
stayed deferred without a word: their calibration (`thm*-ratio`, `thm*-sen*`) is in the SoC's AON eFuse
(`sprd,qogirn6lite-efuse`), which had no driver -- mainline's sprd-efuse with the vendor's QogirN6Lite geometry
(`2671fb482`: 51 blocks from 53, double). The board, PA and charger zones are mainline's generic-adc-thermal on the
PMIC ADC. `soc-thmzone` (the vendor's virtual_thermal, the hottest of the SoC's sensors, critical at 110 C) is a
module loaded from the initramfs, as on 5.15: built in it probes before the zones it is made of and gives up.
On the device at room temperature: the SoC 38-41 C, board 38-40 C, `soc-thmzone` 40 C; the info screen shows
`soc-thmzone`. As on 5.15: the PMIC tsensor works in calibration mode only (its probe ends with -22), the shell
zones front/back read nothing ("fail to get virt temp diff"), and `chg-thmzone` reads ~85 C -- channel 4 of the
ADC gives 134 mV where the board's and PA's give ~485 mV, with the same driver, scale and table as 5.15.

### Durability test (FINDINGS 48)

Does the eMMC keep what mainline flushed, across a power off or a reset?  `upstream/init-durability` is an init
that never mounts userdata: each boot it verifies the `blackbox` partition with `upstream/tools/blkgen` (every
4 KiB block tagged with its number and a generation, a pattern derived from both), then writes the next
generation to every block in a random order, `fdatasync`s (the block layer's cache flush), records the
generation as done, flushes again, and ends the boot the way its plan says -- `poweroff -f` (with the cable in
the PMIC powers the E5 up again, in charger mode), `poweroff -f -n` with 4000 blocks written after the last
flush, `reboot -f`, or SysRq-B.  Slot b is re-armed each cycle; after the plan (or `touch /tmp/stop` over
telnet in a boot's first 25 s) slot a is restored and the E5 is back in Android.  A block older than the done
generation is a flushed write lost; newer ones (written after the flush) are allowed.

```sh
# blkgen, static arm64, in the build container:
docker run --rm -v "$PWD/upstream/tools":/src:ro -v "$PWD/work/durability":/out e5-mainline-build \
    gcc -O2 -Wall -static -o /out/blkgen /src/blkgen.c
mkdir -p work/durability/overlay && cp work/durability/blkgen work/durability/overlay/
: > work/durability/no-modules.txt
python3 boot/build-boot-image.py --stock-boot dumps/boot_b.img --misc-head dumps/misc-head.bin \
    --kernel upstream/out/Image.lk --modules upstream/out/modules --module-order work/durability/no-modules.txt \
    --init upstream/init-durability --overlay work/durability/overlay \
    --busybox work/busybox/ext/usr/bin/busybox --cmdline "" --out work/durability/boot-durability.img
boot/flash-trial.sh work/durability/boot-durability.img      # from Android; back up blackbox first
# the results, in Android: blkgen /dev/block/by-name/blackbox showlog (or its log area, the last MiB)
```

### What the vendor DT asks for

`upstream/tools/compat-map.py <dts> linux-lts-e5 kernel_sprd_ums9158` lists every enabled node's compatible
with the tree that has a driver for it. Mainline has the UART, SPI, I2C, DMA, SDHCI (r11), GPIO, EIC, timer
and hwspinlock drivers; the rest -- clocks (`ums9621-clk.c`), pinctrl (qogirn6lite), the UMP9620/9621/9622
PMICs, the USB controller (musb) and its PHY, and everything above them -- is vendor-only.
