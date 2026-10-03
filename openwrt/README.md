# OpenWrt on the Rongyue E5

> 中文：[`README.zh-CN.md`](README.zh-CN.md)

OpenWrt 25.12 as a second Linux on the E5, next to the Debian image this
repository builds, in the way [mu300-linux](https://github.com/dikeckaan/mu300-linux)
offers OpenWrt next to Ubuntu on the ZTE F50 / MU300: the same kernel and
initramfs (slot b's boot image), OpenWrt's own userspace, and the E5's hardware
support around it.  A router: the 5G modem as WAN, the USB port and the hotspot
as one LAN, LuCI, SSH.  No graphical interface on the panel (see the end).

## How it fits

* **No kernel, no firmware image.**  The E5 boots its vendor kernel from
  `boot_b`; the initramfs (`boot/init`) mounts userdata and starts the system
  named in `e5linux/boot-os` there (`e5linux/boot-os-next` for one boot only;
  `e5-os` writes both).  OpenWrt comes in two forms:
  * **standalone**: a root image of its own, `/data/e5linux/openwrt.ext4`,
    with no Debian needed.  Without a Debian image next to it
    (`/data/e5linux/rootfs.ext4`) it is what boots; with one, `e5-os` chooses.
  * **in the Debian image**: a directory of the Debian root image, `/openwrt`.
* **The hardware files.**  The Wi-Fi/BT firmware, the Debian-signed
  `regulatory.db` this kernel wants, the Android vendor subset that boots the
  baseband (`/opt/e5/android`) and the kernel's modem modules were pulled from
  this device.  The standalone image carries them, and Noto Sans CJK for the
  info screen.  The directory form binds the Debian root's in at boot from
  `/mnt/e5-disk` (the image, which the initramfs leaves mounted there) instead
  of carrying a second copy.  The initramfs copies Debian's overlay (systemd
  units, NetworkManager profiles) only into Debian.
* **userdata** is at `/mnt/e5-data` in the running system (the initramfs
  moves its mount there): the root images, `e5linux/boot-os`.
* **The modem is ModemManager, as on Debian** -- OpenWrt's own package, rebuilt
  with the unisoc plugin (`rootfs/deb-patches/modemmanager-0*.patch`, the same
  patches), and OpenWrt's netifd protocol for it: `wan` is `proto
  modemmanager` on the modem `unisoc-sipc`.  `mmcli` (SMS, cell info,
  `--command`) is the same program as on Debian.
* **Everything else is OpenWrt's**: netifd (`br-lan` = USB + hotspot), the
  firewall (fw4), dnsmasq, odhcpd, hostapd (wpad), LuCI, dropbear.

and what OpenWrt needed from the rest of the repository: the kernel option
`CONFIG_BRIDGE_VLAN_FILTERING` (netifd's bridges), ModemManager patch `06` (the
initial EPS bearer on a context the modem has not defined yet), and the
`boot/init` changes above.  `docs/FINDINGS.md` section 39 has the reasons.

What the E5 needs besides, in `overlay/`:

| | |
|---|---|
| `lib/preinit/05_e5_debian_root` | binds the Debian root's firmware and vendor subset in (the directory form) |
| `etc/init.d/e5-hw` | USB gadget guard, the regulatory database |
| `etc/init.d/e5-vendor` | the baseband: `modem_control`, `cp_diskserver`, `refnotify` in the vendor chroot |
| `etc/init.d/e5-sipc-wwan` | the modem's AT port, once the CP is up, for the SIM card `/etc/config/e5-sim` names |
| `usr/sbin/e5-sim`, `etc/config/e5-sim` | the SIM card that carries data: `e5-sim` lists both cards and their band locks, `e5-sim 0\|1` switches (the port to the other card, ModemManager again, the card's APN, wan up; also ModemManager's SIM slots and the info screen) -- FINDINGS 47 |
| `etc/init.d/e5-modemd`, `usr/sbin/e5-modemd` | answers the CP's asserts for `modem_control` (a reset in seconds, not 300 s); `e5-modemd blocked` resets the CP on demand |
| `etc/init.d/e5-telnetd` | telnet for recovery, USB port only |
| `etc/init.d/e5-boot-ok` | re-arms slot b after a good boot (`e5-next-boot`) |
| `etc/hotplug.d/wwan/26-e5-sipa-eth`, `lib/udev/rules.d/78-mm-e5-sipc.rules` | ModemManager without udev: the data port once the AT port exists, no tty probing |
| `etc/hotplug.d/iface/10-e5-usb0` | puts `usb0` into `br-lan` without netifd touching it: the NCM gadget must never go down |
| `etc/uci-defaults/90-e5`, `91-e5-wireless`, `92-e5-default-boot` | first boot: LAN, WAN, DHCP, the bearer's IPv6 /64 on the LAN, hotspot; Linux as the default boot for an install from Android |
| `etc/init.d/e5-bt`, `etc/config/e5-bluetooth`, `usr/libexec/e5-bt-connect`, `etc/uci-defaults/94-e5-bluetooth` | Bluetooth: `btattach` holds the WCN chip's BT core as hci0 (the kernel does the vendor setup), bluetoothd from our patched BlueZ (`build-bluez.sh`: the SDP MTU), the adapter "E5" and always pairable; `e5-bt-connect MAC` pairs, trusts and connects headphones in the order this chip needs |
| `etc/init.d/e5-pulseaudio`, `etc/pulse/system.pa` | PulseAudio for the speaker and Bluetooth audio (A2DP), started by `e5-audio` once the DSP runs; a connecting headset becomes the output, its disconnection falls back to the speaker |
| `etc/init.d/e5-audio`, `usr/libexec/e5-volume`, `etc/config/e5-audio` | the speaker: the sound card and the audio DSP at boot (`e5-audio-dsp start`: the 24 vendor modules by insmod, the AGDSP image, the profile selects with `e5-ctl-raw`, the UCM route applied with amixer), then the saved volume -- 16 levels on the speaker's digital gain, level 15 = Android's media gain; `e5-volume play beep` |
| `etc/init.d/e5-luci`, `usr/libexec/e5-luci-revision` | LuCI's Cellular Network page shows the modem's revision one row per line (Platform Version, Project Version, BASE Version, HW Version, Build) instead of run together; applied by the build and again at boot |
| `usr/libexec/e5-ttyd-bind`, `etc/hotplug.d/iface/90-e5-ttyd` | Optional ttyd: `interface '@lan'` binds netifd's primary LAN address, rather than the bridge's older rescue address; follows LAN address changes. The package is not preinstalled. |
| `etc/uci-defaults/93-e5-luci` | first boot: LuCI in Chinese with the Argon theme (both preinstalled; Argon from its release's packages, pinned in `build-rootfs.sh`) |
| `etc/init.d/e5-apn-auto`, `usr/libexec/e5-apn-auto` | the APN from the SIM's operator (MCC+MNC) when none was given (`network.wan.apn_auto=1`), at every boot |
| `etc/init.d/e5-sms-notify`, `usr/libexec/e5-sms-notify` | a new SMS vibrates (`e5-vibrate`, `/etc/config/e5-notify`) and is counted unread (`/tmp/run/e5-sms/unread`, `e5-sms-notify read`) |
| `etc/init.d/e5-charge`, `usr/libexec/e5-charge` | charge control: stop at an upper limit, resume at a lower one, charge to full once (`/etc/config/e5-charge`, through charger-manager's `stop_charge`) |
| `usr/libexec/e5-sysupgrade` | replaces `sysupgrade`: a firmware image would overwrite the eMMC |

and the scripts the two systems share come from `rootfs/overlay/opt/e5`
(`vendor-start.sh`, `e5-next-boot`, `e5-os`, ...).

## Build

The maintained SD-card install checks the complete layout before writing, then
updates the inactive registered root and boots it as a trial. The current layout
can hold OpenWrt beside a Debian A/B pair (`e5boot` 32 MiB plus 4 GiB per Debian
slot); routine updates alternate between the roots and failed trials roll back.
The registry and selection details are in [`MULTIBOOT.md`](MULTIBOOT.md).

On the host (Docker, arm64 -- native on Apple silicon):

```sh
openwrt/build-modemmanager.sh   # ModemManager with the unisoc plugin -> out/openwrt/*.apk
openwrt/build-bluez.sh          # BlueZ with rootfs/deb-patches/bluez-0*.patch -> out/openwrt/*.apk
openwrt/build-rootfs.sh         # -> out/openwrt/e5-openwrt-25.12.5-rootfs.tar.gz (the directory form)
E5_STANDALONE=1 openwrt/build-rootfs.sh   # -> out/openwrt/e5-openwrt-25.12.5.ext4.gz (standalone)
```

`build-modemmanager.sh` builds from OpenWrt's source tree at the release tag,
with the release's feeds and configuration, so the package matches the
repository packages it is installed with.  The first run builds OpenWrt's
host tools and toolchain (kept in the Docker volume `e5-openwrt-src`); later
runs rebuild ModemManager only.

`build-rootfs.sh` takes OpenWrt's `armsr/armv8` root filesystem, installs the
packages (hostapd, iw, bash, LuCI's ModemManager protocol, ModemManager from
`out/openwrt/`), adds `overlay/`, the shared scripts, a full static busybox for
the applets OpenWrt's leaves out, `logdw` (`src/logdw.c`, from mu300-linux) and
`e5-vibrate` (`src/e5-vibrate.c`, the PMIC's vibrator).  If the info screen's
repository is next to this one (`../e5-infoscreen`, or `E5_INFOSCREEN=<dir>`;
`E5_INFOSCREEN=` leaves it out), its packages and files go into the tree too.

`E5_STANDALONE=1` adds what the directory form takes from the Debian root:
the firmware (`rootfs/overlay/lib/firmware`: `rootfs/pull-wcn-firmware.sh`,
`pull-audio-firmware.sh`), the vendor subset (`work/android-subset`:
`rootfs/extract-android-vendor.sh`), `wwan.ko` and `sipc_wwan.ko` of the
kernel build (`out_linux`, so the same build as the boot image's kernel), and
Noto Sans CJK from Debian's `fonts-noto-cjk`; then packs the tree into a
1 GiB ext4 image (`E5_IMAGE_MB`; about 330 MB used with the info screen).
The firmware and the vendor subset are this device's own files, not the
repository's: build the image for your own device.

## Install

### Standalone

The boot image must know OpenWrt images (`boot/init` from 2026-09-27,
native18 or later).  From Linux on the device (Debian, or OpenWrt in either
form), over the USB LAN:

```sh
openwrt/install-standalone.sh            # install /data/e5linux/openwrt.ext4
openwrt/install-standalone.sh --try      # install, boot OpenWrt once
openwrt/install-standalone.sh --switch   # install, make OpenWrt the default
```

The device fetches the image and runs `device-install-image.sh`, which
unpacks it next to the installed one and keeps the configuration of the
OpenWrt already there (the running one, else the installed image, else
`/openwrt`): `/etc/config`, passwords, SSH keys, the traffic records.
Packages added with `apk` are not carried over.  From Debian with no OpenWrt
yet, it takes Debian's APN and hotspot, as `install.sh` does.  Run from the
standalone OpenWrt itself, the new image is staged as `openwrt.ext4.new` and
the initramfs swaps it in at the next boot, keeping the previous one as
`openwrt.ext4.old`.

From rooted Android (Magisk), over adb, for a device that never ran Linux:

```sh
openwrt/install-standalone.sh --adb --apn <APN> --wifi-key <key>
boot/flash-trial.sh work/boot-linux-slotb-<name>.img
```

The APN and the hotspot (`--ssid`, default `E5-Linux`) go to
`e5linux/openwrt-install.conf` on userdata, for the first boot; without a key
the hotspot stays off.  Once OpenWrt is up, `e5-next-boot linux` keeps the
device booting it.  Debian can go afterwards: remove
`/mnt/e5-data/e5linux/rootfs.ext4` and OpenWrt is the system there is.

### A flash package for others

```sh
openwrt/make-flash-bundle.sh   # -> out/openwrt/e5-openwrt-flash-<version>-<date>-<git>.tar.gz
```

One archive, unpacked and run as `./flash.sh` on macOS or Linux with adb:
it installs OpenWrt on an E5 with an unlocked bootloader and Magisk, from
Android, and later updates it over the USB LAN (`--update`, settings kept)
or boots it again from Android (`--boot-openwrt`).  `bundle/README.md` is its
manual.  It carries the generic image (`E5_DEVICE_FILES=0`) and a boot image
without the Debian overlay -- no file of this device: its firmware and vendor
files are proprietary and carry its identity (the BT address in the pskey, the
serial number among the Android properties), and the overlay holds its MAC
addresses and hotspot profile.  `flash.sh` pulls each device's own with
`rootfs/pull-wcn-firmware.sh`, `pull-audio-firmware.sh` and
`extract-android-vendor.sh`, packed as `e5linux/device-files.tar` on
userdata, which boot/init unpacks into the image.  The APN comes from the
SIM (`e5-apn-auto`) unless one is given.

### In the Debian image

The E5 runs Debian, and is reachable over the USB LAN (192.168.9.1):

```sh
openwrt/install.sh            # install /openwrt
openwrt/install.sh --try      # install, boot OpenWrt once
openwrt/install.sh --switch   # install, make OpenWrt the default
```

The device fetches the tarball from the host and runs `device-install.sh`,
which unpacks it into `/openwrt` and takes from Debian what OpenWrt has to
match: the APN of NetworkManager's `Mobile`, the SSID, key and channel of
`Hotspot`, the default boot.  A reinstall keeps OpenWrt's configuration.
The boot image must be one with the current `boot/init` (native13 or later).

## Using it

* LuCI: `http://192.168.9.1` (Chinese, Argon theme; System -> System ->
  Language and Style changes either), SSH: `ssh root@192.168.9.1`, telnet from the
  USB port.  The password is `root` until you change it (`passwd`), as on the
  Debian image.
* Switch: `e5-os debian` or `e5-os openwrt`, then `reboot`
  (`e5-os openwrt --once` for one boot; `e5-os status` lists what is
  installed).  The same command exists on Debian; the info screen offers
  Android once, and Debian is left to the command line.
* Android: `e5-next-boot android`, then `reboot`.
* APN: LuCI -> Network -> Interfaces -> wan, or
  `uci set network.wan.apn=...; uci commit network; ifup wan`.
* The modem: `mmcli -m unisoc-sipc`, `e5-at 'AT+CSQ'`.
* **Never** flash an OpenWrt firmware image or run `sysupgrade` with one: it
  is disabled, because an armsr image is a whole-disk image and would
  overwrite the partition table, Android and the bootloaders.  Update
  packages with `apk upgrade`; rebuild and reinstall the image (or the tree)
  from the host.

## Status

Verified on the device (2026-10-03, including the mainline 6.18 release bundle):

| | |
|---|---|
| boot | from `/openwrt` in the root image, once (`boot-os-next`) or by default; the boot after a one-shot returns to Debian; slot b re-armed at the end of the boot |
| LAN | `br-lan` 192.168.9.1/24 = `usb0` + `wlan0`; the USB host gets 192.168.9.2 (no default route, as on Debian), other clients .10-.200 |
| baseband | CP booted by `modem_control` in the vendor chroot; ModemManager's unisoc plugin on `wwan0at0` + `sipa_eth0`, context 1 with the APN from Debian |
| WAN | `proto modemmanager`: IPv4 with the default route on `sipa_eth0`, NAT for the LAN; IPv6 on the device and, with the bearer's /64, on every LAN client (SLAAC, no NAT) |
| hotspot | hostapd, 5 GHz ch149 / 80 MHz, WPA2-PSK with Debian's SSID and key; a phone joins and gets its lease |
| management | telnet (USB port only), SSH, LuCI; `e5-os`, `e5-next-boot`, `e5-at` |
| standalone | installed from Debian with `--try`: booted from `openwrt.ext4` (loop), kept the configuration and traffic records of `/openwrt`, and brought up modem, WAN, hotspot, Bluetooth, audio, info screen and Phone app; an update staged inside it swaps at the next boot |

Not verified yet: LuCI's ModemManager pages, SMS from OpenWrt, `--switch` as
the default for many boots.

## Not here

* **A graphical interface on the panel.**  No phone shell (OpenWrt's `video`
  feed has wayland, wlroots, weston, cage, cog, gtk and Mesa's panfrost, but
  not Phosh).  The panel runs an info screen instead -- cage + cog on
  panfrost, status pages driven by touch and the keypad -- kept in its own
  repository, `e5-infoscreen`, and installed on top of this tree.
* **A full desktop.** The panel runs the separate info screen rather than Phosh.
  OpenWrt still provides LuCI, SSH and the Phone app over the network.
