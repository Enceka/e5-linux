# Status

_Last updated 2026-09-18._

Reasoning, evidence and dead ends live in `docs/FINDINGS.md`.  This file is only the
work list.

## Now (目前要做)

- **GPU: panfrost drives the G57 -- compositor *and* clients (2026-09-18).**
  `docs/FINDINGS.md` section 20.7.  phoc renders with wlroots' GLES2 renderer on
  `Mali-G57 (Panfrost)` and a client now gets the same renderer through the
  Wayland platform, where it used to be llvmpipe -- which is the thing the blob
  hunt in 20.1-20.6 could never reach.  The blob path is retired with it: no
  `/opt/mali` blob, no `/usr/bin/phoc` wrapper, `/etc/environment` no longer
  forces software rendering, and `rootfs/overlay/opt/e5/gpu-mali-setup` is gone.
  kbase is a module that nothing loads (`CONFIG_MALI_MIDGARD=m` in
  `kernel/e5-linux.fragment`); `modprobe mali_kbase` (or putting it back to `=y`)
  is the way back to the blob.  Open, in the order I would pick them up:
  * the output scale stays at `phoc.ini`'s 0.9.  Section 21 picked it for
    sharpness and in-system text size, and the GPU does not argue against it --
    the panel is what it should be, so this is settled rather than pending.  (The
    "still scales to 0.75" this list used to carry was stale: 0.75 was the option
    section 21 rejected as visibly soft.)
  * the scanout buffers are still the vendor KMS driver's dumb buffers, because
    wlroots allocates the swapchain on the *display* device (section 20.7); that
    is why `DUMB_CREATE_TIMES_LIMIT` had to be raised from 10 to 64.  If the GPU
    ever looks slow, the fix is to allocate on panfrost instead -- and
    `WLR_DRM_DEVICES` is not it, because libseat refuses the list on this
    device (20.7 records the log).
  * the frequency is pinned at DVFS index 3 (384 MHz): devfreq is skipped on this
    board (20.7), so watch thermals and GPU throughput under a real load before
    deciding whether that needs a hand.
  * PanVK stays out of reach -- Mesa has no Valhall v9 backend for it -- so this
    is GLES 3.1 and there is no Vulkan on this GPU either way.
- **Bluetooth: the HCI link is live, `hciconfig hci0 up` is not (2026-09-18).**
  `docs/FINDINGS.md` sections 8.5 and 8.6.  Wi-Fi works: the firmware lives in the
  initramfs's *early* overlay (or the GNSS half of the chip boot fails with
  `-ENOENT` and takes the whole WCN core down with it), and the WCN drivers are
  built as the vendor's production (*user*) variant (or one missed `loopcheck`
  answer dumps the chip's memory and condemns the SDIO card for the rest of the
  boot).  With both in place a freshly flashed device scans 18 APs on 2.4 and
  5 GHz with no manual step.  Bluetooth gets as far as a live link -- the chip
  answers the whole HCI init sequence, `hci0` exists with a real BD address and
  sane ACL/SCO MTUs, `MARLIN_BLUETOOTH` powers on cleanly -- but
  `hciconfig hci0 up` ends in `Can't init device hci0: Invalid argument`.  Next:
  the vendor-side init Android performs from its BT HAL, i.e. the
  `bt_configure_pskey*.ini` / `bt_configure_rf*.ini` pair (the vendor's board set
  for this exact board is `connconfig/marlin3_lite/ums9621_1h10/`, and it is *not*
  what `rootfs/pull-wcn-firmware.sh` copies today), or a baud-rate switch that
  `btattach` does not do.  Then the two older items: association and DHCP measured
  12.4 Mbit/s over 5 GHz against 199 Mbit/s over the USB LAN (~3 % of the
  433 Mbit/s negotiated), and `wlan0` comes up on a per-boot random MAC while
  `/mnt/vendor/wifimac.txt` is readable.
- **Baseband stability.**  On the last session the modem stopped answering AT
  (`AT+CSQ` empty, `sipa_eth0` up with no address) and dmesg showed
  `sipa_delegate ... Modem assert ... MN_AL Task PS CP assert ... The queue was
  full`; earlier boots had a working NR SA bearer at ~50 Mbit/s.  Reproduce, then
  decide whether `mobile-data`'s retry path should reset the modem (`AT+SFUN`)
  instead of only re-activating the context.


### Traps found the hard way

- **`systemctl restart sddm` takes the screen away and only a reboot gives it back.**
  SDDM's default `DisplayServer` is x11; X is not installed on this image any more, so
  the restart tries `/usr/bin/X` three times, fails, and exports `DISPLAY=:0` into the
  session environment.  phosh then exits with `cannot open display: :0`, and
  `mobi.phosh.Shell.service` hits "Start request repeated too quickly".  The
  `DisplayServer=wayland` line in `rootfs/overlay/etc/sddm.conf.d/10-e5.conf` is the
  fix; a plain reboot is the recovery.
- **The power-key drop-in exists on the device and in the repo, but not in the image
  the device is running.**  The flashed `boot_b` still carries the old
  `/etc/systemd/logind.conf.d/20-e5-pwrkey.conf` (`HandlePowerKeyLongPress=ignore`), and
  the overlay copies it back over `/etc` on every boot, so a reboot *before* the next
  flash turns the long press back into a no-op (the short press keeps locking).  The
  rebuilt `boot-linux-slotb.img` (sha256 `ee696331...`, kernel unchanged) has it baked;
  flashing is the fix.
- **The device's initramfs overlay is baked into the flashed image.**  Editing
  `rootfs/overlay/...` changes nothing until the image is rebuilt and flashed, and
  until then the *old* overlay is copied over `/etc` on every single boot.  The
  device's `/etc/sddm.conf.d/10-e5.conf` still said `plasma-mobile.desktop` for
  exactly this reason.  `/etc/sddm.conf` currently wins over `/etc/sddm.conf.d/`, which
  is the only reason autologin kept working.

## Next (后续要做)

- **An idle blank does not lock the session.**  After `idle-delay` (300 s) the panel
  goes off (`dpms=Off`, `bl_power=4`) and `LockedHint` stays `no`, so a dark phone is
  still unlocked; only the power key locks.  Not a settable default: `lock-enabled` and
  `idle-activation-enabled` are both `true` and still nothing activates the screen
  saver on idle, because this gnome-settings-daemon ships no `gsd-screensaver` and the
  phosh session does not start one; `logind`'s `IdleAction=lock` would need an idle
  hint that phoc never sets (`docs/FINDINGS.md` section 18).

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
| kernel | rebuilt `Image` (sha256 `97082a76...`): fbdev + ION + `kernel/patches/0001-0006`; slot-b trial boot |
| rootfs | Debian 13 (trixie) arm64, a loop file inside Android's `/data/e5linux/` |
| session | Phosh 0.46.0, `phoc` with wlroots' GLES2 renderer on the **Mali-G57** -- and clients on the same renderer through the Wayland platform |
| gpu | **panfrost**: `mali-g57` id `0x9091`, GLES 3.1 via Mesa 25.0.7, driven by `kernel/patches/0005` + the fragment's `MALI_MIDGARD=m`; kbase is a module nothing loads |
| baseband | 5G NR SA (n78), `mobile-data` + nftables NAT for the USB LAN, ~50 Mbit/s (modem asserted once, see above) |
| wifi | `sprd_wlan_combo` on the WCN chip: scans 2.4 and 5 GHz APs out of the box; MAC is random per boot |
| bluetooth | HCI link live (`hci0` with the chip's own BD address, tty `/dev/ttyBT0`); `hciconfig hci0 up` still fails with EINVAL |
| keys | 9-key keypad works; volume/power/KEY_F1 events verified; confirm = KP_Enter, back = back+delete; power = logind (short press locks and the lock screen blanks the panel, a tap wakes it; long press powers off) |
| disk | 4.4 GiB used, 1.2 GiB free |
| apt | Nanjing University mirror over http (TLS handshakes hang on this bearer) |
