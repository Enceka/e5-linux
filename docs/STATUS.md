# Status

_Last updated 2026-09-25._

Reasoning, evidence and dead ends live in `docs/FINDINGS.md`; traps found the hard
way are collected in its sections 24.8 and 28.  This file is only the work list.
Done work is removed from it once its result is in the table at the bottom or in
FINDINGS.

## Now (目前要做)

- **Audio: the speaker plays through plain ALSA and PipeWire (2026-09-25).**
  FINDINGS 24.8 has the chain (kernel `0012`-`0014`, UCM route, profile selects,
  WirePlumber rule).  The flashed image (`work/boot-linux-slotb-load2.img`) carries
  the current overlay; `wpctl status` shows one Speaker sink.  What is left:
  1. **Four rebuilt audio modules were installed on the device by hand** (originals
     as `*.ko.orig` in `/usr/lib/modules/<rel>/audio/`, and `/root/agdsp_pd.ko.bak`):
     `snd-soc-sprd-card` (0012), `sprd-dmaengine-pcm` (0013),
     `snd-soc-sprd-codec-ump9620` (0014), `agdsp_pd` (0010 without its retry).  A
     fresh rootfs gets them from `out_linux` via `configure-rootfs.sh`, which now
     holds the current build.
  2. **Capture does not work**: the capture DMA never moves (hw_ptr stays 0,
     `arecord` EIO), on FE_NORMAL_AP01 and on the DSP capture FE alike.  The UCM
     profile has no capture device until it does.
  3. `VBC_*_DEV_CHANGE=TYPE_SPK` fails at boot (the DSP is not answering yet at
     that point); Android plays with both at `TYPE_INIT`, so the route leaves them
     alone.  Revisit only if a scene switch needs them.
- **One `boot/flash-from-linux.sh` run rebooted straight into Android (2026-09-25).**
  The image verified on `boot_b` and slot b was armed, yet after the reboot `misc`
  held the slot-a block again and LK never tried slot b.  Two earlier runs the same
  evening worked.  Unexplained; something on the Linux shutdown path may be writing
  the slot-a block.  Recovery that works: from Android, write
  `*.misc-slot-b-trial.bin` into `misc` and reset with sysrq (FINDINGS 24.5).
- **G2: `unisoc-cpd` has taken the RIL's seat on the handset (2026-09-20, Android
  side).**  It holds both SIPC channels, serves capabilities on a unix socket,
  decodes the URC stream, re-arms the SMS surface, reads MT SMS and re-established
  the data bearer over `cbnet`; MO SMS works too (FINDINGS 25.7).  Still open: the
  72 h soak.  On the Linux side it now owns the CP at boot too: `unisoc-cpd` and
  `e5-bearer-up` come up active (5G SA registered, bearer on `sipa_eth0`), and its web
  page answers on `http://192.168.77.1:7887` (management LAN only; no auth).  The page
  is slow on first open: the daemon serves one request at a time (2-6 s each) and the
  page fires about seven at once.
- **Bluetooth: the attach race and the dead scans (open, 2026-09-18).**
  `docs/FINDINGS.md` section 8.7.  What works: the controller initialises, `hci0`
  comes up with the chip's own BD address, bluez reports `Powered: yes`, and scans
  really did find devices (7 LE devices at 14:22, 4 BR/EDR at 15:47).  What does
  not:
  1. **One attach can fail and never recover.**  On the 15:36 boot the first HCI
     Reset went out while the chip's BT channel was still coming up
     (`mtty_sdio_write sprdwcn_bus_push_list failed: -ENODEV`); btattach then held
     the tty with `hci0` at `00:00:00:00:00:00` and zero events, and
     `Restart=always` cannot help because the process never exits.  A self-healing
     wrapper was written and then discarded on request; the tree carries the plain
     `ExecStart=/usr/bin/btattach`.
  2. **After repeated BT power cycles the chip stops answering new HCI commands.**
     `command 0x2041/0x2042 tx timeout` (LE scan parameters and scan enable),
     `hcitool inq` -> `Connection timed out`, `Discovering: no`: a scan finds
     nothing while the adapter still reads `UP RUNNING`, and the init sequence
     right after an attach *is* answered.  Wi-Fi on the same chip keeps working at
     the same moment.
  The vendor BT configuration Android's HAL uses is in the image
  (`bt_configure_pskey.ini`, `bt_configure_rf.ini` in `rootfs/overlay/lib/firmware/`),
  but nothing reads it yet -- Android's BT HAL is what sends it to the chip.  First
  step is still the clean-boot test (fresh boot, one attach, scan immediately, then
  again after ten minutes idle) to decide whether the death is our attach sequence
  or the chip's state.
- **Shutdown time is unmeasured since NetworkManager went (2026-09-20).**  The last
  measurement (FINDINGS 23) had everything stopped in 1.3 s and then ~32 s of NM
  waiting on WCN device teardown; NM is no longer installed, so measure again before
  believing either number.
- **The hotspot needs one client test.**  `hotspot-start.sh` is back to its pre-bridge
  form and no longer makes the `wcnmodem` loop device (FINDINGS 29); on load2 wlan0
  comes up with 192.168.9.1.  Check that a client associates and gets a lease.
- **UFI-TOOLS shows no signal on 5G SA.**  `lte_rsrp` is empty and
  `network_signalbar` 0 while registered on NR SA: `modem.py` derives both from
  `AT+CESQ`'s LTE fields only.  Login is `admin` until changed (`ufi-tools set-token`
  or the web UI; it survives reboots now).
- **GPU: the two open ends left by panfrost.**  The backport itself is done
  (`kernel/patches/0005`, `MALI_MIDGARD=m`, `docs/FINDINGS.md` 20.7) and clients
  render on `Mali-G57 (Panfrost)`; what is left is (a) the scanout buffers are still
  the vendor KMS driver's dumb buffers, which is why `DUMB_CREATE_TIMES_LIMIT` sits
  at 64, and (b) the frequency is pinned at DVFS index 3 (384 MHz) because devfreq
  is skipped on this board -- watch thermals under real load.  PanVK stays out of
  reach: Mesa has no Valhall v9 backend.

## Next (后续要做)

- **An idle blank does not lock the session.**  After `idle-delay` (300 s) the panel
  goes off (`dpms=Off`, `bl_power=4`) and `LockedHint` stays `no`, so a dark phone is
  still unlocked; only the power key locks.  Not a settable default: `lock-enabled` and
  `idle-activation-enabled` are both `true` and still nothing activates the screen
  saver on idle, because this gnome-settings-daemon ships no `gsd-screensaver` and the
  phosh session does not start one; `logind`'s `IdleAction=lock` would need an idle
  hint that phoc never sets (`docs/FINDINGS.md` section 18).
- **Calls and SMS** need a RIL -> the daemon is now that RIL (G2): MT **and** MO SMS
  both work through `unisoc-cpd serve` (the MO blockade was a malformed PDU of our
  own -- first octet `0x11` promising an absent TP-VP; FINDINGS 25.7), the control
  plane matches the Android oracle; what remains for the desktop is a
  ModemManager/D-Bus face, and voice (`voice.supported = false` until there is a UCM
  port -- voice, unlike SMS, really does ride IMS/VoLTE).
- **IPv6** is live but unrouted: the carrier hands out `2408:893a:...` with an RA
  default route and nothing uses it.
- **Suspend is unusable** while the modem data path refuses it
  (`sipa 25220000.sipa: thread prepare suspend err`), which is why the power key
  cannot mean "suspend".
- **The hotspot's own uplink:** with no AP+STA concurrency (`#{ managed, AP } <= 1`)
  the only uplink an AP can share is the modem.
- **Battery, charging and thermals** under the 5G link have only been observed in
  passing.

## Where things stand (短状态)

| | |
|---|---|
| board | Rongyue E5 (UMS9621/qogirn6lite, CPU T158), 4 GiB RAM, Android 14 on slot a |
| kernel | rebuilt `Image` (sha256 `17b829a4...`, `kernel/patches/0001-0009`); modules carry `0010-0015`; slot-b boot; console level 4 on the real root (FINDINGS 29) |
| identity | pretty hostname `Rongyue E5` (`etc/machine-info`), `Processor: Unisoc T158` in `/proc/cpuinfo` (`kernel/patches/0009`), `Hardware Model` row deliberately unset |
| rootfs | Debian 13 (trixie) arm64, a loop file inside Android's `/data/e5linux/`; base ownership/set-id bits recorded in `/var/lib/e5linux/base-perms` |
| session | Phosh 0.46.0, `phoc` with wlroots' GLES2 renderer on the **Mali-G57**; the lock screen accepts the password again (`unix_chkpwd` setgid shadow) |
| gpu | **panfrost**: `mali-g57` id `0x9091`, GLES 3.1 via Mesa 25.0.7, driven by `kernel/patches/0005` + the fragment's `MALI_MIDGARD=m`; kbase is a module nothing loads |
| audio | speaker plays through ALSA (`hw:N,3`, UCM verb HiFi / device Speaker) and PipeWire; AGDSP booted from `l_agdsp_a` by `e5-audio.service`; period events from an hrtimer; no capture |
| baseband | `unisoc-cpd` (Rust) owns the CP on both sides (FINDINGS 25); on Linux it starts at boot with the bearer, web page on `192.168.77.1:7887` |
| wifi | `sprd_wlan_combo` on the WCN chip: scans 2.4 and 5 GHz APs; MAC is random per boot |
| hotspot | `hostapd` 2.10, `AP-ENABLED` on 5 GHz ch149 at 80 MHz (VHT80, centre 155), a client reported 80 MHz; no AP+STA concurrency |
| bluetooth | attaches and scans (LE + BR/EDR have both found devices), but an attach can fail unrecoverably and the chip later stops answering scan commands; BD address is the chip's default |
| keys | 9-key keypad works; volume/power/KEY_F1 events verified; confirm = KP_Enter, back = back+delete; power = logind (short press locks, long press powers off) |
| disk | 2.0 GiB used, 1.9 GiB free on the 4 GiB loop file |
| apt | Nanjing University mirror over http (TLS handshakes hang on this bearer) |

## Open questions

- **`xdg-desktop-portal` has no backend in a fresh install.**  The Plasma half of the
  session was dropped on 2026-09-19 (`packages.list` keeps the reasoning), which
  leaves `xdg-desktop-portal` with nothing to hand requests to.  Decide which backend
  the phosh session wants: `xdg-desktop-portal-gtk` (file chooser, notifications) or
  `xdg-desktop-portal-wlr` (screencast -- phoc is wlroots-based).
