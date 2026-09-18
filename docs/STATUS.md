# Status

_Last updated 2026-09-18._

Reasoning, evidence and dead ends live in `docs/FINDINGS.md`.  This file is only the
work list.  Done work is removed from it once its result is in the table at the
bottom.

## Now (目前要做)

- **Baseband: RIL-shaped AT channel + CP watchdog deployed, soak running (2026-09-18).**
  The empty run proved the `MN_AL Task PS CP assert ... The queue was full` is our
  own AT usage, so the fix is to give the CP what Android's RIL gives it:
  `opt/e5/atd.py` (`e5-atd.service`) opens `/dev/stty_nr0` (the URC channel) and
  `/dev/stty_nr1` (the command channel) once and keeps them open, drains the URC
  stream continuously, serialises commands with a minimum gap, and publishes
  `/run/e5-atd.state`; `mobile-data` now asks it for AT and the watcher's context
  poll dropped from every 30 s to every 5 min.  `opt/e5/cp-watchdog`
  (`e5-cp-watchdog.service`) treats "no AT answer for 120 s" as CP death, logs
  the evidence, re-arms the boot slot and reboots, with a 900 s guard against a
  boot loop.  Deployed on the device and measured for 31 minutes (watcher up for
  17): `CP assert` = 0, `+COPS: 0,2,"46001",11`, `wget` fine -- against the ~9.5
  minutes the old regime survived.  **Still to do:** a longer soak (an hour, and
  one with hotspot clients), then bake `opt/e5` into the next image.
  Full reasoning: `docs/FINDINGS.md` section 22.
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
     wrapper for that was written, found to have a fatal `exec wait` bug of its
     own, fixed -- and then **discarded on request**; the tree carries the plain
     `ExecStart=/usr/bin/btattach`, and the device still runs an image whose
     wrapper is the buggy one.
  2. **After repeated BT power cycles the chip stops answering new HCI commands.**
     `command 0x2041/0x2042 tx timeout` (LE scan parameters and scan enable),
     `hcitool inq` -> `Connection timed out`, `Discovering: no`: a scan finds
     nothing while the adapter still reads `UP RUNNING`, and the init sequence
     right after an attach *is* answered.  Wi-Fi on the same chip keeps working at
     the same moment.
  The vendor BT configuration Android's HAL uses is **now in the image**:
  `bt_configure_pskey.ini` and `bt_configure_rf.ini` were pulled out of
  `/odm/firmware` into `rootfs/overlay/lib/firmware/` (the `_aa`/`.xpe` variants
  are still on the device; `.gitignore` keeps vendor blobs out of git).  Nothing
  in our kernel or userspace reads them yet, so the open question is who sends
  them to the chip -- Android's BT HAL does.  The first thing to do is still the
  clean-boot test (fresh boot, one attach, scan immediately, then scan again after
  ten minutes idle) to decide whether the death is our attach sequence or the
  chip's state.
- **Wi-Fi hotspot: ch149 at 80 MHz is up (2026-09-18).**  The `HT_SCAN` stall was
  never the width -- it was the regulatory domain, the same missing country as
  `docs/FINDINGS.md` section 20.  With `country CN: DFS-FCC` the driver
  advertises `5725-5850 @ 80 MHz`; `etc/hostapd/e5.conf` now runs channel 149,
  VHT80 with centre 155, and hostapd logs `Set freq 5745 ... bandwidth=80 MHz,
  cf1=5775` with the beacon's VHT Operation at `width=1, seg0=155`.  4/4 start
  attempts reached `AP-ENABLED` (with/without a prior scan, with/without a
  pre-set channel), so `hotspot-start.sh` no longer configures the channel.
  Still open: confirm 80 MHz from a real client's link rate (the beacon's VHT
  *Capabilities* IE says 20/40 because the driver's own `hw vht capab` has that
  bit clear), the `#{ managed, AP } <= 1` limit means an AP drops the Wi-Fi
  uplink, and guests still get out only through the (now watchdogged) modem.
- **Shutdown takes ~32 s and it is all NetworkManager (deferred).**  Everything
  else stops inside 1.3 s (`bluetooth.service` in 0.25 s); the journal is then
  silent from NM's `modem-manager: ModemManager no longer available` at
  14:57:01.108 to its own `exiting (success)` at 14:57:33.001, i.e. NM's shutdown
  path waits on device teardown that does not complete here (the WLAN is on the
  WCN chip, whose firmware does not answer a disconnect promptly).
  `NetworkManager.service.d/20-e5-shutdown-timeout.conf` (`TimeoutStopSec=5`) is
  in the tree and did **not** shorten the total in the one test since -- NM's
  stop is issued late in the sequence, so the time is spent *before* it, not
  inside it.  Measure again with the drop-in in a booted image before believing
  anything here.
- **GPU: the two open ends left by panfrost.**  The backport itself is done
  (`kernel/patches/0005`, `MALI_MIDGARD=m`, `docs/FINDINGS.md` 20.7) and clients
  now render on `Mali-G57 (Panfrost)`; what is left is (a) the scanout buffers are
  still the vendor KMS driver's dumb buffers, which is why
  `DUMB_CREATE_TIMES_LIMIT` sits at 64, and (b) the frequency is pinned at DVFS
  index 3 (384 MHz) because devfreq is skipped on this board -- watch thermals
  under real load.  PanVK stays out of reach: Mesa has no Valhall v9 backend.
- **The 32 s shutdown is still unexplained, but is written up now.**
  `docs/FINDINGS.md` section 23 has the identity strings and the measurement
  (everything stops in 1.3 s, then NetworkManager sits on device teardown for the
  rest); the `TimeoutStopSec=5` drop-in has not helped in its one test.

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
- **The hotspot's own uplink:** with no AP+STA concurrency the only uplink an AP can
  share is the modem, so it needs the CP problem above solved to be more than an
  isolated LAN.
- **Battery, charging and thermals** under the 5G link have only been observed in passing.

## Where things stand (短状态)

| | |
|---|---|
| board | Rongyue E5 (UMS9621/qogirn6lite, CPU T158), 4 GiB RAM, Android 14 on slot a |
| kernel | rebuilt `Image` (sha256 `7cf0a57f...`): fbdev + ION + `kernel/patches/0001-0009`; slot-b trial boot |
| identity | pretty hostname `Rongyue E5` (`etc/machine-info`), `Processor: Unisoc T158` in `/proc/cpuinfo` (`kernel/patches/0009`), `Hardware Model` row deliberately unset |
| rootfs | Debian 13 (trixie) arm64, a loop file inside Android's `/data/e5linux/` |
| session | Phosh 0.46.0, `phoc` with wlroots' GLES2 renderer on the **Mali-G57** -- and clients on the same renderer through the Wayland platform |
| gpu | **panfrost**: `mali-g57` id `0x9091`, GLES 3.1 via Mesa 25.0.7, driven by `kernel/patches/0005` + the fragment's `MALI_MIDGARD=m`; kbase is a module nothing loads |
| baseband | 5G NR SA (n78); the CP asserted ~10 min into a session that polled AT. `e5-atd.service` (persistent URC drain + serialised commands) + `e5-cp-watchdog.service` are deployed; 31 min soak clean, longer soak pending (`docs/FINDINGS.md` 22) |
| wifi | `sprd_wlan_combo` on the WCN chip: scans 2.4 and 5 GHz APs out of the box; MAC is random per boot |
| hotspot | `hostapd` 2.10, `AP-ENABLED` on 5 GHz ch149 at **80 MHz VHT80 (centre 155)**; the old `HT_SCAN` stall was the missing `country CN`, not the width; no AP+STA concurrency |
| bluetooth | attaches and scans (LE + BR/EDR have both found devices), but an attach can fail unrecoverably and the chip later stops answering scan commands; BD address is the chip's default |
| keys | 9-key keypad works; volume/power/KEY_F1 events verified; confirm = KP_Enter, back = back+delete; power = logind (short press locks and the lock screen blanks the panel, a tap wakes it; long press powers off) |
| disk | 4.4 GiB used, 1.2 GiB free |
| apt | Nanjing University mirror over http (TLS handshakes hang on this bearer) |

## Uncommitted in the working tree (2026-09-18)

- `rootfs/overlay/lib/firmware/bt_configure_{pskey,rf}.ini`: pulled from Android
  (`.gitignore` keeps them out of git, like the other vendor blobs).
- Nothing else: `opt/e5/mobile-data`, the new `opt/e5/atd.py` +
  `opt/e5/cp-watchdog` and their units are committed (see the baseband bullet),
  and the earlier "URC filtering in `at()`" note was a dead edit -- the tree was
  already clean when the AT channel came back.

### 2026-09-18, late (this round)

* **Empty-run verdict (done, and it answers the question):** Linux was booted and left
  alone -- `e5-mobile-data` and its watcher stopped, no AT at all -- and at **uptime
  17 minutes there was no CP assert** (`CP assert` hits = 0), where a session that polls
  AT dies at ~9.5 minutes.  So the `MN_AL Task PS CP assert ... The queue was full` is
  **our AT usage filling the CP's queue**, not the firmware: the fix is to pace AT the way
  Android's RIL does, and to keep a "CP is dead -> reboot" watchdog as the fallback.
  Services were re-enabled afterwards; the bearer came back as `10.133.137.8/8`.
* **Hotspot: blocked by the regulatory domain, fixed in the image** (docs/FINDINGS.md
  section 20).  `regulatory.db` + its signature are now in `rootfs/overlay/lib/firmware/`,
  and the rebuilt image puts them in the initramfs before the WCN modules load.  **After a
  reflash**: `iw reg get` should say `country CN`, then
  `iw dev wlan0 set type __ap; ip link set wlan0 up; hostapd -B /etc/hostapd/e5.conf`
  should reach `AP-ENABLED` (SSID `E5-Linux`, psk `12345678`, DHCP from
  `etc/systemd/network/20-e5-wlan0.network` = 192.168.78.1/24, NAT out via the existing
  `sipa_eth0` masquerade).
* **wlan0 is currently NetworkManager-unmanaged**
  (`/etc/NetworkManager/conf.d/20-e5-wlan0-unmanaged.conf` was added so hostapd can own
  the interface) and `wpa_supplicant.service` is masked.  Remove both to go back to
  station mode.

