# Status

_Last updated 2026-09-17._

## Where the port stands

Linux boots on the Rongyue E5 and is reachable.  Verified on the device:

| | |
|---|---|
| kernel | `5.15.211-g94401422a7df`, from `e5_rongyue_defconfig` + `kernel/e5-linux.fragment` |
| boot | slot b, armed through the 32-byte `bootloader_control` in `misc`; falls back to Android when it fails |
| initramfs | 60 modules, dependency-ordered, `loaded=60 failed=0`, nothing left in `devices_deferred` |
| USB | gadget enumerates as `0525:a4a1`, `usb0` = 192.168.77.1, root shell over telnet |
| power | `battery/status = Charging` (`aw32257_charger` + `sc27xx-fgu` + `sprd-charger-manager`) |
| display | `/dev/dri/card0` + `card0-DSI-1` (480x320 ST7365P panel); needs a compositor to modeset |

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

1. **Wait for `device-finalize.sh`** to finish and confirm
   `/data/e5linux/rootfs.ext4` exists.  It is in its shrink step (deleting the
   1.2 GiB apt cache on f2fs) and then copies the 6 GiB image into place.
2. **Boot it.**  `boot/install-rootfs.sh` (or `work/doflash.sh`) arms slot b and
   reboots.  `boot/init` finds the image, loop mounts it, and `switch_root`s.
   Expect `stage=switch-root` in the persistent log.
3. **See whether Plasma Mobile comes up.**  This is the open risk: the UMS9621
   GPU has no mainline Mesa driver, so everything renders with llvmpipe.  If the
   session fails, the fallbacks to try, in order:
   * `KWIN_COMPOSE=Q` / a software scene backend,
   * `QT_QUICK_BACKEND=software`,
   * and if KWin simply will not composite without GL, Phosh instead -- its
     wlroots compositor has a **pixman (pure CPU) renderer** (`WLR_RENDERER=pixman`)
     and would avoid GL completely.
4. **Touch.**  `tlsc6x.ko` loads but has not been exercised; the device has no
   keyboard, so touch is the only input.
5. **Re-arm behaviour.**  `e5-boot-ok.service` is gated on `graphical.target`:
   until a session actually starts, slot b is not re-armed and the try counter
   runs out, so the device returns to Android by itself.
6. **The 300 s mystery.**  An earlier Linux session rebooted with no record in the
   persistent block after 14 s.  The block stopped because `persist()`'s lock can
   wedge (`boot/init` now expires it after two minutes) and the timer is now ten
   minutes and logs its decision to `/dev/kmsg`.  Worth confirming that a Linux
   session now survives unattended.
