# Status

_Last updated 2026-09-17._

## Where the port stands

Linux boots on the Rongyue E5 and is reachable.  Verified on the device:

| | |
|---|---|
| kernel | `5.15.211-g94401422a7df`, from `e5_rongyue_defconfig` + `kernel/e5-linux.fragment` |
| boot | slot b, armed through the 32-byte `bootloader_control` in `misc`; falls back to Android when it fails |
| input | **the 9-key keypad works.** `sprd-keypad` is input2/event2 with KEY_1..KEY_9, KEY_0, `*` `#`; power and volume keys are in `gpio-keys` (input0) -- docs/FINDINGS.md section 12 |
| swap | 4 GiB zram with zstd (was 768 MB lzo-rle), `swappiness=100`, `page-cluster=0` |
| initramfs | 66 modules, dependency-ordered, `loaded=60 failed=0`, nothing left in `devices_deferred` |
| USB | gadget is **NCM + CDC-ACM** (0525:a4a1); usb0 = 192.168.77.1/24 with a DHCP server (systemd-networkd), so the host gets a lease -- docs/FINDINGS.md section 6.1 |
| power | `battery/status = Charging` (`aw32257_charger` + `sc27xx-fgu` + `sprd-charger-manager`) |
| display | /dev/dri/card0 + card0-DSI-1 (480x320 ST7365P); KWin modesets it (plane allocated by = kwin_wayland) |
| session | SDDM autologins `e5` into **`phosh.desktop`**: phoc (`WLR_RENDERER=pixman`, DRM owner) + phosh + phosh-osk-stub. `plasma-mobile.desktop` is still installed and selectable -- docs/FINDINGS.md section 16 |
| NAT | `mobile-data up` installs an nftables `masquerade` on `sipa_eth0` plus MSS clamping, so USB LAN clients share the bearer; verified from a network namespace (10.99.0.2 -> internet) -- docs/FINDINGS.md section 15 |
| re-arm | `e5-boot-ok.service` refills slot b's try counter from inside Linux (`misc` byte-verified) |
| baseband | **mobile data works, on 5G NR SA.** Android's `modem_control` runs in a chroot (`e5-vendor.service`, ~50 MiB vendor subset at `/opt/e5/android`), then AT on `/dev/stty_nr1` + `sipa_eth0` takes it online; `+CEREG: ...,11` (NR SA) after the user camped n78 from Android, and the bearer does ~50 Mbit/s -- docs/FINDINGS.md sections 13 and 14 |
| apt | the image points at the Nanjing University mirror over **http** (TLS handshakes hang on this bearer): ~8 MB/s, which is what makes installing Phosh practical |
| Wi-Fi | driver packaged and **loading on the device** (63/63 modules incl. sprd_wlan_combo, wcn_bsp, cfg80211); the chip still fails to power on because its DT firmware path is a wcnmodem partition this device does not have -- docs/FINDINGS.md section 8 |
| session cost | **Phosh is ~200 MB lighter than the trimmed Plasma Mobile**: 723 used / 727 available, against 926 / 524 for Plasma (which itself came down from 1288 / 162 before section 11's trim) |
| session lifetime | **fixed.** The ~295 s silent reset was the PMIC watchdog; staging sprd_pmic_wdt.ko (which feeds it, pmic_timeout 300) took a session from 295 s to 10+ min and stable -- docs/FINDINGS.md section 9 |

Root filesystem: Debian 13 (trixie) arm64 with **Plasma Mobile 6.3.6**, 1518
packages installed and configured.  `plasma-mobile.desktop` and
`plasma.desktop` are both present in `/usr/share/wayland-sessions`.

## How the root filesystem is built

Not on the build host.  Installing an arm64 package set there means running every
`dpkg` maintainer script under `qemu-user`, and apt's dependency resolver for
~1450 packages burned twenty minutes of CPU without unpacking a single one.

Instead the device does it, natively, because the device is aarch64:

1. `rootfs/fetch-debian-rootfs.py` pulls the Debian trixie arm64 userland from
   the Docker registry (no container runtime needed, and no `mknod`, which an
   unprivileged user namespace cannot do on the host filesystem).
2. That tree goes into a 6 GiB ext4 image, built with `mkfs.ext4 -d` **inside a
   user namespace** so the files come out root-owned rather than owned by the
   build user.
3. The image is pushed and loop mounted on the device, then
   `rootfs/device-build.sh` runs `dpkg --unpack` and `dpkg --configure -a`
   inside a chroot there -- native speed, minutes instead of hours.
4. `rootfs/device-finalize.sh` applies `rootfs/overlay/`, creates the `e5` user,
   enables the services and publishes the image as `/data/e5linux/rootfs.ext4`.

Three things bite in that chroot, all of them environment leakage from Android:

* `tar` on Android is toybox's, and it turned Debian's usrmerge symlinks
  (`/bin -> usr/bin`) into real directories.  Mounting a filesystem image avoids
  the problem entirely -- and the image doubles as the final `rootfs.ext4`.
* `PATH` is Android's, so nothing resolves inside the chroot, not even `dpkg`.
* `TMPDIR=/data/local/tmp` (plus `ANDROID_*` and `LD_LIBRARY_PATH`) leaks in, and
  maintainer scripts that call `mktemp` fail.  `env -i` fixes it; without it
  `dpkg --configure -a` aborts with "too many errors".

## Next steps

1. **Wi-Fi: satisfy the DT firmware path.**  The packaging half is done and verified:
   the WCN modules are in boot/module-order.extra, stage-modules.sh stages 63 of them,
   they load into the flashed kernel (stage=modules-done loaded=63 failed=0) and the
   driver probes sprd-marlin3.  It then powers the chip back down and returns -ENODEV
   because sprd,btwf-file-name in the DT is /dev/block/by-name/wcnmodem, and this
   device has no such partition.  Next: create that path (a loop device backed by the
   wcnmodem.bin the image already carries) and provide
   /vendor/firmware/gnssmodem.bin, both from the overlay; then watch dmesg for the
   chip booting and ip link for wlan0.
2. **The five-minute reset is fixed** by staging sprd_pmic_wdt.ko (PMIC watchdog,
   pmic_timeout 300 with the driver feeding it); a session now runs 10+ minutes where
   it used to die at 295 s (docs/FINDINGS.md section 9).  Two loose ends worth
   remembering: the feed is inside the driver, not systemd, so there is still no
   /dev/watchdog and the RuntimeWatchdogSec drop-in stays inert; and if a future
   change makes that driver fail to probe, the 295 s reset comes straight back.
3. **Verify the standalone path's logging.**  In the switch_root path the persistent
   block always ends at `stage=switch-root` by design -- the writer is the initramfs
   `init`, and `switch_root` replaces it (the last run's block reads `uptime=14.74`,
   `loaded=60 failed=0`, `switch-root root=/disk init=/lib/systemd/systemd`, which is
   as far as it can go).  In the *standalone* path `init` keeps running, and there the
   block used to stop after its first write: `persist()`'s stamp lived *inside* the
   lock directory, so `rmdir` could not release it and every later call returned early
   (`docs/FINDINGS.md` §4).  `boot/init` now keeps the stamp beside the lock and
   releases both with `rm -rf`, and stops the persist loop and the safety timer by pid
   (`jobs -p` does list them in busybox ash -- checked -- but two explicit pids say
   what is meant).  Check it with a boot that has no root filesystem available (rename
   `rootfs.ext4`): the block should keep getting rewritten every fifteen seconds until
   the ten-minute timer fires, and `cat /run/stages` inside the session should show
   `stage=timer-reboot` before it does.
4. **Touch, and pixels.**  `tlsc6x_touch` is registered as an input device (`event1`)
   and the panel is modeset, but nothing has been touched -- the device has no
   keyboard, so touch is the only input.  There is also no pixel-level proof of what
   the panel shows: `spectacle` inside the session, dumped over the serial console,
   would settle both at once.
5. **The session's memory.**  After section 11's trimming, Plasma Mobile leaves
   524 MB available, which works but is not comfortable: plasmashell and kwin still
   spend a CPU core on software rasterisation.  If the device is to be pleasant, the
   next step is a wlroots/GTK4 shell (Phosh, or Sxmo if the odd interaction is
   acceptable) with `WLR_RENDERER=pixman`, keeping Plasma Mobile as the fallback
   session in `/usr/share/wayland-sessions`.  Packages come from the host, which has
   the network the device does not.
6. **The keypad driver is in the initramfs now** (`boot/module-order.extra`,
   66 modules), but the running device gets it from the root filesystem
   (`/lib/modules/.../sprd_keypad.ko` + `/etc/modules-load.d/e5-keypad.conf`), so the
   new `boot-linux-slotb.img` has to be flashed only for a machine that has never been
   through this.  A press test from the user is the one thing left to confirm: the
   device registers the events, the shell has to act on them.
7. **Sharing the baseband with the host, and IPv6.**  `sipa_eth0` carries the
   device's own traffic; the USB LAN clients still cannot route through it because
   neither `nft` nor `iptables` is installed on the image (fetch the packages, add
   the masquerade/MSS rules MU300 uses, or install `nftables` -- the device has a
   route to the internet of its own now).  The carrier also hands out a
   `2408:893a:...` IPv6 address that is not routed yet.
8. **Phosh** is being installed now (the baseband gives the device the internet it
   never had, and the NJU mirror makes it fast).  It will be selected as the SDDM
   autologin session once it has been started by hand and verified; `plasma-mobile.desktop`
   stays in `/usr/share/wayland-sessions` as the fallback.  Earlier note: the baseband gives the device
   the internet it never had, so the 100+ package mobile shell no longer needs the
   host as a proxy.  Keep `plasma-mobile.desktop` as the fallback session.
9. **Wi-Fi is the one thing still blocked**, and the next steps for it are unchanged:
   the DT wants `/dev/block/by-name/wcnmodem`, which this device does not have, so the
   chip powers back down.  A loop device backed by the `wcnmodem.bin` the image already
   carries is the plan (docs/FINDINGS.md section 8).
10. **IPv6** is live but unrouted: the carrier hands out a `2408:893a:...` address and
   there is an RA default route, yet nothing is configured to prefer or use it.
11. **Physical keys under Phosh**: the 9-key pad and the power/volume keys produce input
   events (section 12); which of them phosh acts on is worth checking with the user, now
   that a session that understands KEY_POWER/KEY_BACK is running.
12. **Re-arm behaviour** is verified: `e5-boot-ok` wrote the slot-b trial block back
   into `misc` from inside the running system (byte-compared), so rebooting returns
   to Linux instead of Android.

Operationally, the recipe that works from a macOS host with no network on the device
is: rebuild the boot image locally with `boot/build-boot-image.py` (stock `boot_b`
dump + the kernel `Image` and modules taken from the ramdisk already on the device),
flash with `boot/flash-trial.sh`, and drive the running system over the USB CDC-ACM
console (`/dev/cu.usbmodemE5LINUX3`, `115200`, login `root`/`root`) -- or telnet to
`192.168.77.1` once the gadget is up on Linux.  A slot-b trial is one attempt: the
counter runs out, and the next reset lands back in Android.
