# OpenWrt for the Rongyue E5 -- one-click flash package

> 中文：[`README.zh-CN.md`](README.zh-CN.md)

Installs OpenWrt 25.12 (5G WAN, hotspot, LuCI and the info screen on the
panel) on a Rongyue E5, next to its Android: Android stays as it is, OpenWrt
lives in an image file on the phone's storage (userdata) and boots from
`boot_b`.  Android is always one step away.

## You need

* a Rongyue E5 with an **unlocked bootloader** and Android rooted with **Magisk**;
* Android running from slot a (as it comes from the factory);
* at least 2.5 GB free on the phone's storage;
* a macOS or Linux computer with `adb` (Android platform-tools) and `python3`;
* a USB data cable.

## Flash

1. Turn on USB debugging on the E5, connect it, allow debugging on the phone.
2. Grant **Shell** superuser access in Magisk (the phone asks the first time).
3. Unpack the package and run, in its directory:

   ```sh
   ./flash.sh
   ```

   It asks for the APN, the hotspot's name and key.  For the APN just press
   Enter: OpenWrt picks it from the SIM's operator (China Mobile `cmnet`,
   Unicom `3gnet`, Telecom `ctnet`, Broadnet `cbnet`; the network's default
   for others), again after a SIM change.  Enter for the key: a random one,
   shown at the end.  Or give them on the command line:

   ```sh
   ./flash.sh --ssid E5-OpenWrt --wifi-key 12345678 -y
   ```

4. When it says done, the E5 reboots into OpenWrt; the first boot takes about
   two minutes.

What it does:

* checks the package, the device (root, slot a, unlocked, the boot control
  block) and the free space;
* **pulls this device's own** Wi-Fi/BT/audio firmware and the vendor files
  that boot the baseband off its Android, as `/data/e5linux/device-files.tar`.
  The package carries no device's firmware: those files are the vendor's, and
  they carry each unit's identity (BT address, serial number), so every
  device uses its own;
* writes the OpenWrt image to `/data/e5linux/openwrt.ext4` and the first
  boot's settings to `/data/e5linux/openwrt-install.conf`;
* writes the boot image to `boot_b`, verifies it, and points the next boot at
  slot b.  **Slot a's Android is not touched.**

## Using it

* Hotspot: the name and key set while flashing; or the USB cable (USB network).
* LuCI (in Chinese, Argon theme; System -> System -> Language and Style): `http://192.168.9.1`, user `root`, password `root` -- **change it**
  (LuCI -> System -> Administration, or `passwd` over SSH).
* SSH: `ssh root@192.168.9.1`.
* The panel: left/right turn the pages, confirm presses, back goes back; 高级
  (Settings) has the network mode, bands, APN, charge control and more.

## Back to Android

* On the panel: 高级 -> 系统 -> 下次启动 Android (Settings -> System -> Boot Android once);
* or over SSH: `e5-next-boot android && reboot`.

From Android back to OpenWrt, with nothing reinstalled (the settings stay):
connect the E5 and run

```sh
./flash.sh --boot-openwrt
```

A failed OpenWrt boot falls back to Android on its
own after two tries.

## Update

With the E5 running OpenWrt and connected over USB, run the new package's:

```sh
./flash.sh --update
```

It updates the boot image and the OpenWrt image over the USB network and
**keeps OpenWrt's settings** (`/etc/config`, passwords, SSH keys, the traffic
records); packages added with `apk` are not kept.  The new image takes over at
the reboot; the old one stays as `/mnt/e5-data/e5linux/openwrt.ext4.old`.

## Uninstall

Back in Android, in a root shell, delete `/data/e5linux/openwrt.ext4`,
`device-files.tar` and `openwrt-install.conf`.  The boot image in `boot_b`
does not bother Android, which boots from slot a.

## Disclaimer

Unofficial software, not affiliated with or endorsed by Rongyue or the makers
of the device and its chips.  Flashing needs an unlocked bootloader and root,
and can void the warranty, lose data or leave the device unusable; changing
the network, bands, AT commands or charging can cut the connection or upset
the device.  Provided "as is", without warranty of any kind: **at your own
risk**.  Back up what matters first, and keep to the local rules for the
bands and radio settings you choose.

## Maintainer and licences

Enceka <enceka@yeah.net>.  The scripts and e5-linux's parts are MIT
(`LICENSE`); OpenWrt, the Linux kernel and the other components are under
their own licences (GPL and others), with their sources at OpenWrt and in the
e5-linux repository.
