# Status

_Last updated 2026-09-18._

Reasoning, evidence and dead ends live in `docs/FINDINGS.md`.  This file is only the
work list.

## Now (目前要做)

- **Wi-Fi association.** `wlan0` is up and `iw dev wlan0 scan` returns real APs on
  2.4 and 5 GHz — no loop device is involved and none is needed.  The partition theory
  was wrong: `btwifi_download_firmware()` in `wcn_boot.c` calls
  `request_firmware("wcnmodem.bin")` **first** and only falls back to the DT's
  `/dev/block/by-name/wcnmodem` when that fails.  The `from /system/etc/firmware/`
  line it logs is a misleading hardcoded string — that path does not exist on this
  root filesystem at all.  What actually fixed it was getting `wcnmodem.bin` into
  `/lib/firmware` early enough, which the initramfs overlay does; `no find
  wcnmodem.bin` never appears in `dmesg`, so the fallback was never taken.
  The scan also confirms the factory MAC is being ignored (`wlan0` comes up on a
  random address while `/mnt/vendor/wifimac.txt` is readable) — worth chasing later.

  **Associated, on DHCP, and transferring (2026-09-18).**  `nmcli device wifi connect`
  against a 5 GHz AP: `Connected to ... freq: 5745.0`, signal -39 dBm, both directions
  at `433.3 MBit/s VHT-MCS 9 80MHz`, DHCP lease `192.168.137.113/24` plus a link-local
  address, and NetworkManager saved the profile to
  `/etc/NetworkManager/system-connections/` (mode 0600) so it autoconnects.
  A 100 MB fetch from the host ran end to end: `http=200 bytes=104857600 time=67.7s
  speed=1548242 B/s` — **12.4 Mbit/s, about 3 % of the 433 Mbit/s the link
  negotiates**.  The control settles where the loss is: the *same* file from the *same*
  server over the USB LAN takes 4.2 s, `speed=24932851 B/s` (24.9 MB/s, 199 Mbit/s).
  So the host, the file and the TCP stack are all fine and the ~16x gap is the
  Wi-Fi/SDIO data path — the SDIO transport or the fullmac driver's RX, not the radio
  and not the network stack.  That is the thing to profile before calling Wi-Fi done.

  Credentials live in `/etc/e5/wifi.conf` (0600) **and** in the NetworkManager profile
  on the device only — never in this repository and never in a log.
- **Power key.** `e5-powerkey.service` toggles the panel (`bl_power`) on `KEY_POWER` and
  restores it on any touch or other key; suspend is not an option (see below).  The
  logind/ScreenSaver lock call was removed again after the user found the screen could no
  longer be woken while it was in -- confirm waking before adding anything back.

  **Why it cannot be woken (2026-09-18).**  The script decides with `locked()`, which
  reads `/sys/class/backlight/*/bl_power` and calls the panel locked when it is not
  `0`.  That state and the compositor's are **independent**: phoc owns DPMS and blanks
  the output on its own idle timer, while `bl_power` stays `0` the whole time.  So after
  phoc blanks, `locked()` reports "panel is on", the power key calls `panel(True)` --
  i.e. *off* -- and the `elif locked()` branch that is supposed to wake it on any other
  key can never fire.  The result is a screen that only ever goes darker.  Confirmed
  from the DRM side: `crtc[109]: dispc0 enable=0`, `connector[117]: DSI-1 crtc=(null)`,
  `dpms=Off`, while the script's own journal says `panel on`.

  The fix is to stop fighting the compositor: either drive phosh's own blank/unblank
  (it already blanks on idle and wakes on touch, so the panel writes can simply go), or
  have `locked()` consult the DRM DPMS state instead of `bl_power`.  Do **not** reach
  for `systemctl restart sddm` while debugging this -- see the trap below.

- **Screen size.** The panel is 49x74 mm at 320x480, i.e. ~166 DPI, and GTK lets that
  grow the UI past the screen ("some buttons are off-screen").  First attempt:
  `org.gnome.desktop.interface text-scaling-factor 0.75`.  If buttons are still
  unreachable, use phosh's per-app `scale-to-fit`, then `phoc.ini`'s `[output:DSI-1]`
  `scale`/`rotate` (the output reports `Enabled: no` in `wlr-randr` while phosh drives it,
  which is worth understanding before trusting either).
  **The virtual keyboard is the concrete failure (2026-09-18), and it is measured.**
  With the display healthy, `grim` works after all -- the earlier
  `failed to copy output DSI-1` was just the symptom of the panel being off
  (`crtc enable=0`, `dpms=Off`), not a broken screencopy.  `tools/png2ascii.py`
  turns the capture into a character map so it can be read without an image viewer,
  and it shows the OSK clipped at the right edge: the top row ends mid-key
  (`...:*******++` against 10-12 character keys elsewhere) and the indented home row,
  which should have roughly half a key of margin on each side, starts with six
  characters of blank on the left and is still cut off on the right.  The layout wants
  around 355 px of logical width and the output only offers 320, so no amount of
  `text-scaling-factor` will help --
  `wlr-randr` confirms `Transform: normal`, `Scale: 1.000000`, mode `320x480`.

  Next to try, in order: `phoc.ini`'s `[output:DSI-1] scale` below 1, which buys
  logical width directly (if phoc only accepts integers, this needs squeekboard or a
  patched layout instead); then `squeekboard`, whose layouts are built for narrow
  phones; then phosh's per-app `scale-to-fit`.
- **Reflash when convenient.** The device still runs the *old* flashed image (64 modules,
  25-file overlay).  The keypad modules and the 4 GiB zram work from the rootfs, but the
  initramfs overlay rewrites `/usr/local/sbin/e5-zram` and `/etc/environment` on every
  boot, which is why the zram size lives in a drop-in.  `boot-linux-slotb.img` in the
  repository is already the fixed one (66 modules, 26 overlay files).

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
| kernel | the original flashed `Image` (sha256 `c1ab1905...`), slot-b trial boot |
| rootfs | Debian 13 (trixie) arm64, a loop file inside Android's `/data/e5linux/` |
| session | Phosh 0.46.0 (`phoc` with pixman); KDE purged; `e5`/`123456`, `root`/`root` |
| baseband | 5G NR SA (n78), `mobile-data` + nftables NAT for the USB LAN, ~50 Mbit/s |
| keys | 9-key keypad works; volume/power/KEY_F1 events verified; power key = panel toggle |
| disk | 4.4 GiB used, 1.2 GiB free |
| apt | Nanjing University mirror over http (TLS handshakes hang on this bearer) |
