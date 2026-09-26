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
  `boot_b`; the initramfs (`boot/init`) mounts the Linux root image
  (`/data/e5linux/rootfs.ext4`) and starts the system named in
  `e5linux/boot-os` on it -- Debian, which *is* the image, or a system in a
  directory of the image: OpenWrt lives in `/openwrt`.  `e5linux/boot-os-next`
  does the same for one boot only.
* **The hardware files are Debian's.**  The Wi-Fi/BT firmware, the Debian-signed
  `regulatory.db` this kernel wants, the Android vendor subset that boots the
  baseband (`/opt/e5/android`) and the kernel's modem modules were pulled from
  this device into the Debian root.  OpenWrt binds them in at boot from
  `/mnt/e5-disk` (the image, which the initramfs leaves mounted there) instead
  of carrying a second copy.  The initramfs no longer copies Debian's overlay
  (systemd units, NetworkManager profiles) into a root that is not Debian.
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
| `lib/preinit/05_e5_debian_root` | binds the Debian root's firmware and vendor subset in |
| `etc/init.d/e5-hw` | USB gadget guard, the regulatory database |
| `etc/init.d/e5-vendor` | the baseband: `modem_control`, `cp_diskserver`, `refnotify` in the vendor chroot |
| `etc/init.d/e5-sipc-wwan` | the modem's AT port, once the CP is up |
| `etc/init.d/e5-telnetd` | telnet for recovery, USB port only |
| `etc/init.d/e5-boot-ok` | re-arms slot b after a good boot (`e5-next-boot`) |
| `etc/hotplug.d/wwan/26-e5-sipa-eth`, `lib/udev/rules.d/78-e5-mm-sipc.rules` | ModemManager without udev: the data port once the AT port exists, no tty probing |
| `etc/hotplug.d/iface/10-e5-usb0` | puts `usb0` into `br-lan` without netifd touching it: the NCM gadget must never go down |
| `etc/uci-defaults/90-e5`, `91-e5-wireless` | first boot: LAN, WAN, DHCP, the bearer's IPv6 /64 on the LAN, hotspot |
| `usr/libexec/e5-sysupgrade` | replaces `sysupgrade`: a firmware image would overwrite the eMMC |

and the scripts the two systems share come from `rootfs/overlay/opt/e5`
(`vendor-start.sh`, `e5-next-boot`, `e5-os`, ...).

## Build

On the host (Docker, arm64 -- native on Apple silicon):

```sh
openwrt/build-modemmanager.sh   # ModemManager with the unisoc plugin -> out/openwrt/*.apk
openwrt/build-rootfs.sh         # -> out/openwrt/e5-openwrt-25.12.5-rootfs.tar.gz
```

`build-modemmanager.sh` builds from OpenWrt's source tree at the release tag,
with the release's feeds and configuration, so the package matches the
repository packages it is installed with.  The first run builds OpenWrt's
host tools and toolchain (kept in the Docker volume `e5-openwrt-src`); later
runs rebuild ModemManager only.

`build-rootfs.sh` takes OpenWrt's `armsr/armv8` root filesystem, installs the
packages (hostapd, iw, bash, LuCI's ModemManager protocol, ModemManager from
`out/openwrt/`), adds `overlay/`, the shared scripts, a full static busybox for
the applets OpenWrt's leaves out, and `logdw` (`src/logdw.c`, from mu300-linux).

## Install

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

* LuCI: `http://192.168.9.1`, SSH: `ssh root@192.168.9.1`, telnet from the
  USB port.  The password is `root` until you change it (`passwd`), as on the
  Debian image.
* Switch: `e5-os debian` or `e5-os openwrt`, then `reboot`
  (`e5-os openwrt --once` for one boot; `e5-os status`).  The same command
  exists on Debian.
* Android: `e5-next-boot android`, then `reboot`.
* APN: LuCI -> Network -> Interfaces -> wan, or
  `uci set network.wan.apn=...; uci commit network; ifup wan`.
* The modem: `mmcli -m unisoc-sipc`, `e5-at 'AT+CSQ'`.
* **Never** flash an OpenWrt firmware image or run `sysupgrade` with one: it
  is disabled, because an armsr image is a whole-disk image and would
  overwrite the partition table, Android and the bootloaders.  Update
  packages with `apk upgrade`; rebuild and reinstall the tree from the host.

## Status

Verified on the device (2026-09-27, from a fresh install with `--try`):

| | |
|---|---|
| boot | from `/openwrt` in the root image, once (`boot-os-next`) or by default; the boot after a one-shot returns to Debian; slot b re-armed at the end of the boot |
| LAN | `br-lan` 192.168.9.1/24 = `usb0` + `wlan0`; the USB host gets 192.168.9.2 (no default route, as on Debian), other clients .10-.200 |
| baseband | CP booted by `modem_control` in the vendor chroot; ModemManager's unisoc plugin on `wwan0at0` + `sipa_eth0`, context 1 with the APN from Debian |
| WAN | `proto modemmanager`: IPv4 with the default route on `sipa_eth0`, NAT for the LAN; IPv6 on the device and, with the bearer's /64, on every LAN client (SLAAC, no NAT) |
| hotspot | hostapd, 5 GHz ch149 / 80 MHz, WPA2-PSK with Debian's SSID and key; a phone joins and gets its lease |
| management | telnet (USB port only), SSH, LuCI; `e5-os`, `e5-next-boot`, `e5-at` |

Not verified yet: LuCI's ModemManager pages, SMS from OpenWrt, `--switch` as
the default for many boots.

## Not here

* **A graphical interface on the panel.**  OpenWrt's feeds do have a Wayland
  stack (the `video` feed: wayland, wlroots, weston, cage, gtk, mesa), but not
  Phosh or a phone shell; left out for now.
* **Bluetooth.**  `btattach` is not started; the BT core stays off (which,
  since kernel `0026`, cannot disturb Wi-Fi).
* **Audio, calls with sound.**  As on Debian, call audio is open; the audio
  modules are not loaded.
