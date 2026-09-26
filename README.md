# Linux on the Rongyue E5 (Unisoc UMS9621)

> 中文文档：[`README.zh-CN.md`](README.zh-CN.md)

A Linux bring-up for the Rongyue E5 5G handset/hotspot (`ums9158_1h10`,
Unisoc UMS9621 / qogirn6lite, Android 13), built the way
[mu300-linux](https://github.com/dikeckaan/mu300-linux) does it for the ZTE F50 /
MU300: a custom kernel from the device's own GPL kernel tree plus an initramfs
that brings up a USB gadget and switches into a full Linux root filesystem,
installed **next to Android** on slot b, without rewriting the partition table.

The kernel source is [`kernel_sprd_ums9158`](https://github.com/Enceka/kernel_sprd_ums9158),
branch `linux-staging` (Google android13-5.15 GKI + the Unisoc UMS9621 platform, with
the E5 device support in it, plus this project's patches), rebuilt as a general-purpose Linux kernel by
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
> charger is one of them (`docs/FINDINGS.md` section 7.2).
>
> **Which system boots.** Once a root filesystem is installed, Linux is the
> persistent default (`/etc/e5linux/default-boot` says `linux`, and `e5-boot-ok`
> re-arms slot b after every successful boot); `e5-next-boot android` from a
> Linux shell goes back to Android.  A boot that never reaches userspace still
> falls back to slot a on its own.  Without a root filesystem the initramfs stays
> up standalone and reboots to Android after ten minutes unless `/run/stay`
> exists.

## Why this is not a copy of mu300-linux

Three things are materially different on the E5, and each one changed the design:

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
| USB gadget network (NCM) | ✅ usb0 and the hotspot are one LAN, `br0` 192.168.9.1/24 (dnsmasq DHCP; the USB host always gets 192.168.9.2, with no default route); the initramfs rescue mode keeps 192.168.77.1 |
| Battery charging under Linux | ✅ **verified — `battery/status = Charging`** |
| DRM/KMS display (480x320 DSI panel, now `card1` -- panfrost takes `card0`) | ✅ phoc modesets it (active plane `320x480`, `allocated by = phoc.orig`) |
| Debian 13 + Phosh root filesystem | ✅ SDDM autologins `phosh.desktop` |
| Phosh session (phoc, wlroots' GLES2 renderer on the Mali-G57) | ✅ **verified** — `GL renderer: Mali-G57 (Panfrost)`, and the clients are on it too; docs/FINDINGS.md section 20.7 |
| Re-arm from inside Linux (`e5-boot-ok`) | ✅ verified, `misc` byte-compared |
| Touch panel under Linux | ✅ **works** — `tlsc6x_touch` on `event1`, udev tags it `ID_INPUT_TOUCHSCREEN=1`, and phoc takes its events |
| Wi-Fi | ✅ **verified on the device** — `sprd_wlan_combo` + `wcn_bsp` on the WCN chip, scans 2.4 and 5 GHz APs out of the box (needs the firmware in the initramfs overlay and the vendor's *user* build variant); docs/FINDINGS.md sections 8.5-8.6 |
| Bluetooth | ✅ the kernel configures the marlin3 core the way the vendor HAL does (pskey/RF/enable from `request_firmware`, core disable before the tty closes) — factory address `FC:B5:85:D0:85:9B`, scans and connects; kernel `0018`, `0021`, FINDINGS §33.3, §35. ⏳ audio profiles untested |
| Session lifetime | ✅ fixed: the ~295 s silent reset was the PMIC watchdog; staging sprd_pmic_wdt.ko (which feeds it) gives sessions that run 10+ min -- docs/FINDINGS.md section 9 |
| Modem, data | ✅ **native**: `sipc_wwan` puts the AT channel on a WWAN port (kernel `0022`, `0023`), ModemManager's `unisoc` plugin drives it (patched modemmanager, `rootfs/deb-patches/`), NetworkManager's `Mobile` connection brings the data up on `sipa_eth0` (IPv4 + IPv6); 5G SA, signal in Phosh, SMS in Chatty; the Android `modem_control` still boots the CP from a chroot — FINDINGS §36, §37; SMS and VoLTE calls both ways (Chatty, Calls). ⏳ call audio: neither side hears anything yet |
| Modem fallback | [`unisoc-cpd`](https://github.com/Enceka/unisoc-cpd) stays installed, not enabled: `systemctl start unisoc-cpd` takes the modem back from ModemManager (and serves its page on `http://192.168.9.1:7887`) |
| UFI-TOOLS (Linux port) | ✅ `http://<device>:2333`, login `admin` until changed |
| Hotspot | ✅ NetworkManager's `Hotspot` connection (Phosh's switch and Settings' Wi-Fi panel, patched to recognise it; UFI-TOOLS, `nmcli`) on 5 GHz ch149 / 80 MHz (patched network-manager, `rootfs/deb-patches/`), SSID `E5-Linux`, a port of `br0` with the USB port; IPv4 NAT to the bearer, and the bearer's public IPv6 /64 by SLAAC for every LAN client (stateful firewall) — FINDINGS §35 |
| Audio | ✅ speaker and microphone, both confirmed in use (Amberol, GNOME Sound Recorder, the Settings sound test): speaker through ALSA (UCM `HiFi`/`Speaker`, S16 interleaved) and PipeWire, mic as the "Internal Microphone" source (DSP capture, mono S16); `e5-audio.service` boots the AGDSP off `l_agdsp_a`; kernel `0010`-`0014`, `0017`, `0019`, `0020`, FINDINGS §24.8, §33, §34. ⏳ earpiece not yet heard |
| Idle load | ✅ load average ~0 at idle (it read 6+ from vendor threads in `D` and synchronous console output) — kernel `0015`, FINDINGS §29 |

## Repository layout

| Path | Contents |
|---|---|
| `kernel/` | `build-linux.sh`, `e5-linux.fragment` (Linux additions on top of the device defconfig), `patches/0001-0027` (applied by `build-linux.sh`) |
| `boot/` | `init` (initramfs), `build-boot-image.py`, `stage-modules.sh` + `module-order.{stock,extra}`, `flash-trial.sh` / `android-boot-linux.sh` (from Android), `flash-from-linux.sh` (from a running e5-linux) |
| `rootfs/` | `build-rootfs-container.sh` (+ `rootfs-in-container.sh`, the build in a Debian arm64 container), `install-rootfs.sh`, `packages.list`, `configure-rootfs.sh`, `fetch-debian-rootfs.py`, `install-packages.sh`, `pull-wcn-firmware.sh` / `pull-audio-firmware.sh` / `extract-android-vendor.sh` (blobs from your device), `stage-unisoc-cpd.sh`, `overlay/`; the `device-*.sh` and `build-rootfs.sh`/`e5-chroot.sh` paths are the older on-device and qemu builds |
| `tools/` | `collect-logs.sh`, `e5-telnet.py`, `e5-serial.py`, screenshot/key/touch helpers |
| `docs/` | `FINDINGS.md` (measurements, dead ends), `STATUS.md` (the work list) |

**Not included**: stock firmware, Android vendor binaries, device dumps. The
scripts read those from *your* device.

## Requirements

* A Rongyue E5 with an unlocked bootloader (`ro.boot.verifiedbootstate=orange`),
  rooted Android with working `adb` + `su`, and a way to recover (SPD download
  mode or a known-good stock image).
* Linux build host with `clang`/`lld` (LLVM), `make`, `python3`, `lz4`.  On macOS
  that means brew's `make` (the system one is GNU Make 3.81, kbuild wants ≥ 3.82),
  `coreutils` + `gnu-sed` for kbuild's scripts, `llvm` for `llvm-objdump`/`llvm-nm`/
  `llvm-objcopy`, and a directory with `elf.h` for `scripts/mod` (`work/hostinc/`
  in this tree).
* Optional: a Rust toolchain with the `aarch64-unknown-linux-musl` target, only to
  rebuild `unisoc-cpd` (the overlay already carries a static binary).
* Docker, for the root filesystem: `rootfs/build-rootfs-container.sh` runs the
  install inside `debian:trixie` on arm64, where the packages install at native
  speed.  `rootfs/e5-chroot.sh` is the unprivileged qemu path for a Linux host and
  cannot run on macOS.
* Dumps you make yourself: a stock slot-b boot image and the first 4 KiB of
  `misc` (see below).
* For the modem, the Android vendor subset (`rootfs/extract-android-vendor.sh`
  pulls it off the device, ~49 MiB): without it `e5-vendor.service` is skipped and
  there is no CP, no `/dev/stty_nr1` and no baseband.  It is proprietary, so it is
  never in the image and has to be pushed into `/opt/e5/android/` separately.

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
git clone -b linux-staging https://github.com/Enceka/kernel_sprd_ums9158   # inside this checkout
kernel/build-linux.sh
```

`linux-staging` is the branch with the e5-linux changes committed on top of the
device tree (`main` is the vendor tree as published).  `KERNEL_TREE` defaults to
`./kernel_sprd_ums9158` and `O` to `./out_linux`.  The script then checks
`kernel/patches/*.patch` against the tree -- on `linux-staging` every one reports
"already applied"; on a tree without them it applies them -- freezes the release string in `.scmversion` so a patched tree does not
become `-dirty`, merges `kernel/e5-linux.fragment` into
`arch/arm64/configs/e5_rongyue_defconfig`, fails loudly if a symbol the initramfs
depends on did not survive, and builds `Image` + modules + DTBs.

### 2. Modules and initramfs

```sh
boot/stage-modules.sh          # -> out_modules/, boot/module-order.txt
```

The initramfs `insmod`s those modules in the **stock first-stage order**, not
alphabetically; see `docs/FINDINGS.md` §3 for why that is not a nitpick.

A static arm64 busybox is needed for the initramfs:

```sh
mkdir -p work/busybox/ext && cd work/busybox
curl -O http://ports.ubuntu.com/ubuntu-ports/pool/main/b/busybox/busybox-static_1.36.1-6ubuntu3.1_arm64.deb
ar x busybox-static_*.deb && tar --zstd -xf data.tar.zst -C ext ./usr/bin/busybox
cd -    # -> work/busybox/ext/usr/bin/busybox
```

### 2a. Firmware and blobs from your device

The overlay's `lib/firmware/` carries only the regulatory database; the WCN
(Wi-Fi/BT) firmware, the AGDSP image and the audio parameters are vendor blobs and
are pulled off *your* device, with it in Android (adb + su):

```sh
rootfs/pull-wcn-firmware.sh      # wcnmodem.bin, gnssmodem.bin, wifi_board_config*.ini, MACs
rootfs/pull-audio-firmware.sh    # l_agdsp_a.img, audio_structure, dsp_vbc, cvs, aw87xxx_acf.bin
rootfs/extract-android-vendor.sh # -> work/android-subset/ (modem_control and its runtime)
```

The first two land in `rootfs/overlay/` and travel inside the boot image; the
vendor subset is installed on the root filesystem separately (step 3).

### 2b. unisoc-cpd (optional)

The overlay carries a built `unisoc-cpd` (`usr/local/bin/`, `etc/unisoc-cpd/`, the
units).  To update it from a checkout of its own repository:

```sh
git clone https://github.com/Enceka/unisoc-cpd
rootfs/stage-unisoc-cpd.sh       # builds, copies, applies the Linux-side edits
```

The script is the only way that copy should change: it turns off the profile's
Android-only NAT, binds the web page to the LAN (`192.168.9.1`, reachable from the USB port only) and records the commit in
`etc/unisoc-cpd/VERSION`.

### 3. Root filesystem (fresh install)

The rootfs is a loop file inside Android's `/data`, not a partition, so it is built
once, pushed, and does not have to be rebuilt when the boot image changes:

```sh
rootfs/build-rootfs-container.sh            # all stages -> out/rootfs.ext4 (8 GiB)
rootfs/install-rootfs.sh out/rootfs.ext4    # push in 1 GiB chunks, verify, publish
```

`build-rootfs-container.sh` installs `rootfs/packages.list` (phosh -- the only session
since 2026-09-19, Plasma Mobile and its X11 are no longer in the list --,
NetworkManager/`wpasupplicant` for Wi-Fi and the hotspot, `nftables` for NAT, pipewire, ...)
into a Debian trixie arm64 tree, copies `rootfs/overlay/` over it, stages the audio
modules from `out_linux/` (so build the kernel first), creates the `e5` user, enables
the units and packs the result.  The image is **8 GiB by default**
(`E5_IMG_MIB=N` overrides it): the loop file is the only writable filesystem on the
device, and one packed to exactly its own size leaves no room for the first
`apt install`.

Stages can be re-run on their own, which is what a later overlay or package change
actually needs:

```sh
rootfs/build-rootfs-container.sh configure pack           # overlay change only
rootfs/build-rootfs-container.sh install configure pack   # package set changed
```

`install-rootfs.sh` runs against rooted Android (`adb` + `su`): it removes the
previous `/data/e5linux/rootfs.ext4` to make room, pushes the new image in chunks,
compares the sha256 on the device and renames it into place.  The accounts it
creates are `e5`/`123456` and `root`/`root` (autologin is on, so the touchscreen
session never asks).

The modem is the one piece that is **not** in the image.  The Android vendor subset
is proprietary and is neither committed nor packed; install it once the system is up
(it survives, the loop file is writable).  Userdata is not mounted under Linux, so it
goes over the USB LAN:

```sh
tar -C work -cf work/android-subset.tar android-subset
( cd work && python3 -m http.server 8000 --bind 192.168.9.2 )   # the USB host's fixed address
# in the e5-linux shell (telnet 192.168.9.1, or the USB serial console), as root:
cd /tmp && /usr/local/bin/busybox wget http://192.168.9.2:8000/android-subset.tar
mkdir -p /opt/e5 && tar --no-same-owner -xf android-subset.tar -C /opt/e5
mv /opt/e5/android-subset /opt/e5/android && systemctl start e5-vendor e5-sipc-wwan ModemManager
```

`--no-same-owner` matters: bionic refuses a `__properties__` tree that is not
root-owned.  Do not "fix" ownership later with `chown -R` while `e5-vendor` runs --
the chroot has `/dev`, `/proc` and `/sys` bind-mounted, and the recursion rewrites
the live device nodes (FINDINGS §28).  Until the subset is there `e5-vendor.service`
is skipped (`ConditionPathExists=`), `/dev/stty_nr1` returns `ENODEV` and
ModemManager finds no modem.

### 4. Boot image

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
And since `boot/init` copies the overlay over the root filesystem on every boot, the
image's copy wins over anything edited on the device by hand (except `/var/lib`,
which is only seeded) -- change `rootfs/overlay/` and rebuild instead.
The builder packs the overlay with `a+r` (and `a+rx` for executables) rather than
whatever mode the checkout happens to have; a 0600 `phoc.ini` from a build host
with a strict umask once cost the `e5` user its entire session.

### 5. Flash

The first time, from rooted Android:

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
`boot_b` again from Android without reflashing:

```sh
boot/android-boot-linux.sh boot-linux-slotb.img
```

Every later image can be flashed from the running e5-linux over the USB LAN,
with no Android round trip: it serves the image over HTTP, writes and verifies
`boot_b`, arms slot b and reboots.

```sh
boot/flash-from-linux.sh boot-linux-slotb.img
```

### 6. Using it

| | |
|---|---|
| LAN | `br0` = the USB port (NCM) + the hotspot, the device is `192.168.9.1`; the USB host always gets `192.168.9.2` and no default route, hotspot clients get `.10`-`.200`; everyone gets a public IPv6 address from the bearer's /64 |
| shell | `telnet 192.168.9.1` (`root`/`root`, USB port only), or the USB CDC-ACM serial console |
| accounts | `e5`/`123456` (the phosh session autologins), `root`/`root` |
| hotspot | SSID `E5-Linux`, WPA2 `12345678`, clients on 192.168.9.0/24 |
| modem | ModemManager: Phosh's mobile settings, Calls, Chatty, `mmcli -m any`; data is NetworkManager's `Mobile` connection (`nmcli c up/down Mobile`); raw AT with `e5-at 'AT+CSQ'` |
| UFI-TOOLS | `http://192.168.9.1:2333` (USB port only), `admin`; CLI `ufi-tools status`, `ufi-tools set-token` |
| back to Android | `e5-next-boot android && systemctl reboot` |

Change the passwords, the hotspot passphrase and the UFI-TOOLS token before the
device leaves your desk.  Telnet, gotty and UFI-TOOLS are dropped for
frames arriving from the Wi-Fi side of the bridge and for anything from the uplink
(`etc/e5/nat.nft`), so a hotspot client or the internet cannot reach them -- the USB
cable is the management port.

### 7. Read the result

```sh
tools/collect-logs.sh logs
```

After a boot that fell back to Android, this pulls `/sys/fs/pstore/*`, the 4 MiB
persistent log inside `boot_b` and the bootloader log. `E5-LINUX: stage=…` lines in the pstore console are the
initramfs reporting progress.

## Credits and licenses

* Kernel source: Google android13-5.15 GKI and the Unisoc UMS9621 platform, as
  published in `Enceka/kernel_sprd_ums9158` — GPL-2.0.
* The approach, repository layout and several scripts are derived from
  [`dikeckaan/mu300-linux`](https://github.com/dikeckaan/mu300-linux) (MIT).
* Scripts, tools and documentation in this repository: MIT (see `LICENSE`).
* Stock firmware, Android vendor components and bootloaders belong to their
  owners and are not distributed here.
