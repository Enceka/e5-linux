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
| `build.sh` | builds `linux-lts-e5` in the container: `out/Image`, `out/Image.lk`, `out/config`, `System.map`, `modules.builtin*` |
| `e5-mainline.config` | the config fragment, merged on top of `allnoconfig`; an option Kconfig does not take stops the build (`config-ignored.txt` for known exceptions) |
| `wrap-image.py` | LK copies the kernel to 0x80080000; the stub moves the entry to 0x80200000 (2 MiB aligned) |
| `init-bringup` | a probe init: logs devices, drivers, deferrals to kmsg and pmsg, warm-reboots |
| `make-boot.sh` | a slot-b boot image of the kernel and an init (`boot/build-boot-image.py`) |

```sh
docker build -t e5-mainline-build upstream/
upstream/build.sh                            # ~3 min from clean
upstream/make-boot.sh                        # work/boot-mainline.img
boot/flash-trial.sh work/boot-mainline.img   # from Android: one trial boot on slot b
# back in Android: /sys/fs/pstore/console-ramoops-0 and pmsg-ramoops-0 (tools/collect-logs.sh)
```

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
| M4: the modem (SIPC, SIPA, modem loader) with ModemManager as on 5.15 | |
| M5: display (sprd DRM, DSI panel), touch, keypad, vibrator | |
| M6: charger, fuel gauge, thermal, cpufreq | |
| M7: audio (AGDSP, VBC, UMP9620 codec, aw87xxx PA) | |
| M8: GPU (Mali G57) | |

The target is what works on 5.15 today (`docs/STATUS.md`, `boot/module-order.txt`).

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

### What the vendor DT asks for

`upstream/tools/compat-map.py <dts> linux-lts-e5 kernel_sprd_ums9158` lists every enabled node's compatible
with the tree that has a driver for it. Mainline has the UART, SPI, I2C, DMA, SDHCI (r11), GPIO, EIC, timer
and hwspinlock drivers; the rest -- clocks (`ums9621-clk.c`), pinctrl (qogirn6lite), the UMP9620/9621/9622
PMICs, the USB controller (musb) and its PHY, and everything above them -- is vendor-only.
