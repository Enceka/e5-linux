# Status

_Last updated 2026-09-18._

Reasoning, evidence and dead ends live in `docs/FINDINGS.md`.  This file is only the
work list.

## Now (目前要做)

- **GPU: the compositor is on the Mali GPU; the apps are not (2026-09-18).**
  phoc comes up with wlroots' GLES2 renderer on `Mali-G57`
  (`docs/FINDINGS.md` section 20), but every *client* is still llvmpipe -- `About`
  and `fastfetch` are right.  Measured: the working blob is GBM-only
  (`EGL_KHR_platform_gbm`, no Wayland platform, zero `wl_display` references), so a
  Wayland client cannot even create an EGL display on it (section 20.7); Mesa has
  no kbase driver, so removing the software-forcing `/etc/environment` variables
  would not help either.  Getting apps on the GPU needs a **Wayland-WSI** Mali
  userspace the kernel accepts: the published r44p0 wayland blob is exactly that
  and kbase r41p0 refuses it, i.e. port kbase to r44p0, or run the Android blob
  through libhybris / a bionic chroot.  Remaining polish for what works today:
  * the blob that works is Allwinner's r32p0 **GBM** build, a vendor artifact that
    is *not* in this repository: `/opt/mali/libMali-r32p0-sunxi.so`, installed by
    `rootfs/overlay/opt/e5/gpu-mali-setup` (it also wraps `/usr/bin/phoc` and
    depends on the `/dev/dma_heap/*` udev rule).  A fresh rootfs needs that script
    run once; the next flash bakes in the udev rule.
  * `phoc.ini` still scales the output to 0.75 because the CPU could not afford
    1.0.  That reason is gone -- try 0.85 and 1.0 again and compare.
  * watch GPU DVFS, thermals and buffer churn under a real load (the panel is the
    only load so far; the vendor DRM driver's `DUMB_CREATE_TIMES_LIMIT` is a
    one-shot failure at the 11th dumb buffer).
- **Wi-Fi throughput.**  Association, DHCP and a 100 MB transfer work; the data path
  does not: 12.4 Mbit/s over 5 GHz against 199 Mbit/s for the same file over the USB
  LAN -- ~3 % of the 433 Mbit/s the link negotiates.  Profile the SDIO transport /
  the fullmac RX path.  Also `wlan0` comes up on a random MAC while
  `/mnt/vendor/wifimac.txt` is readable.
- **Baseband stability.**  On the last session the modem stopped answering AT
  (`AT+CSQ` empty, `sipa_eth0` up with no address) and dmesg showed
  `sipa_delegate ... Modem assert ... MN_AL Task PS CP assert ... The queue was
  full`; earlier boots had a working NR SA bearer at ~50 Mbit/s.  Reproduce, then
  decide whether `mobile-data`'s retry path should reset the modem (`AT+SFUN`)
  instead of only re-activating the context.
- **Power key, pending verification.**  `e5-powerkey.service` toggles the panel on
  `KEY_POWER`; the lock call was removed because the screen could no longer be
  woken while locked.  Confirm the wake path before adding anything back.


### Traps found the hard way

- **`systemctl restart sddm` takes the screen away and only a reboot gives it back.**
  SDDM's default `DisplayServer` is x11; X is not installed on this image any more, so
  the restart tries `/usr/bin/X` three times, fails, and exports `DISPLAY=:0` into the
  session environment.  phosh then exits with `cannot open display: :0`, and
  `mobi.phosh.Shell.service` hits "Start request repeated too quickly".  The
  `DisplayServer=wayland` line in `rootfs/overlay/etc/sddm.conf.d/10-e5.conf` is the
  fix; a plain reboot is the recovery.
- **The device's initramfs overlay is baked into the flashed image.**  Editing
  `rootfs/overlay/...` changes nothing until the image is rebuilt and flashed, and
  until then the *old* overlay is copied over `/etc` on every single boot.  The
  device's `/etc/sddm.conf.d/10-e5.conf` still said `plasma-mobile.desktop` for
  exactly this reason.  `/etc/sddm.conf` currently wins over `/etc/sddm.conf.d/`, which
  is the only reason autologin kept working.

## Next (后续要做)

- **Calls and SMS** need a RIL: this port drives the modem over raw AT
  (`e5-vendor.service` + `mobile-data`), so `gnome-calls`/`chatty` would have nothing to
  talk to.
- **IPv6** is live but unrouted: the carrier hands out `2408:893a:...` with an RA default
  route and nothing uses it.
- **Audio** is unverified (the MU300 port found its amplifier silent on I2C).
- **Suspend is unusable** while the modem data path refuses it
  (`sipa 25220000.sipa: thread prepare suspend err`), which is why the power key cannot
  mean "suspend".
- **Wi-Fi hotspot** (`hostapd`) after the station test, and Wi-Fi at 5 GHz if the firmware
  allows it.
- **Battery, charging and thermals** under the 5G link have only been observed in passing.

## Where things stand (短状态)

| | |
|---|---|
| board | Rongyue E5 (`ums9158_1h10`, UMS9621/qogirn6lite), 1450 MB RAM |
| kernel | rebuilt `Image` (sha256 `7356c756...`): fbdev + ION + `kernel/patches/0001-0003`; slot-b trial boot |
| rootfs | Debian 13 (trixie) arm64, a loop file inside Android's `/data/e5linux/` |
| session | Phosh 0.46.0, `phoc` on the **Mali-G57** via the Allwinner r32p0 GBM UMD; kernel log on the panel |
| gpu | kbase r41p0 + ARM fbdev UMD (handshake) and the r32p0 GBM UMD (compositor); r44p0 blobs are refused |
| baseband | 5G NR SA (n78), `mobile-data` + nftables NAT for the USB LAN, ~50 Mbit/s (modem asserted once, see above) |
| keys | 9-key keypad works; volume/power/KEY_F1 events verified; power key = panel toggle |
| disk | 4.4 GiB used, 1.2 GiB free |
| apt | Nanjing University mirror over http (TLS handshakes hang on this bearer) |
