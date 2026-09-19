# Status

_Last updated 2026-09-19._

Reasoning, evidence and dead ends live in `docs/FINDINGS.md`.  This file is only the
work list.  Done work is removed from it once its result is in the table at the
bottom.

## Now (目前要做)

- **Baseband: rewritten as a straight port of mu300-linux, aligned with upstream
  `ccc9bb9` (2026-09-19).**
  The Python `atd.py` + `cp-watchdog` pair is gone; what is in the tree now is the
  upstream MU300 design with the E5's names, and its units are installed and
  enabled again:
  * `opt/e5/e5-atd` + `opt/e5/e5-at` -- the `mu300-atd`/`mu300-at` port.  A sh
    daemon owns `/dev/stty_nr1` for the whole boot, serves `/run/e5-at/cmd` (fifo,
    "SECONDS /answer-file AT+CMD") with an atomic answer file and a mkdir lock per
    client, drains before each command, applies `stty` to the open descriptor, and
    closes + reopens the device after two unanswered commands.  That is what makes
    the SIPC channel's "one reader only" rule hold, and an AT command costs one
    open per boot instead of one per call.
  * `opt/e5/mobile-data` -- the `mu300` script ported: `at`/`up [APN]`/`down`/
    `status`/`signal`/`at "CMD"`/`sim-reset`/`watch`, the bring-up lock in
    `/run/e5-mobile-data-up.lock` (`up` -> `up_locked "$@"`), `tty_setup` (never
    `stty -F` while the daemon owns the tty), the 30 s watchdog with its two-strike
    rule, `radio_on` (CFUN -> SFUN=4 -> SFUN=2/4), and `down`'s "system is stopping"
    exit with the short `E5_AT_LOCK_WAIT=5`.  AT goes through `e5-atd` when its
    fifo exists and only opens the tty itself when the daemon is absent.
    The five differences from upstream, all of them E5-shaped: the `E5_AT_*`
    variable names (upstream hardcodes `/run/mu300-at`, `/dev/stty_nr1`), no
    netifd/OpenWrt branch (this image is systemd-only), the APN read from
    `/etc/e5/mobile-data.conf` when `up` is called without an argument, a
    `/etc/resolv.conf` fallback where upstream only uses `resolvectl`, and the NAT
    table named `e5_nat`.  `E5_AT_CLIENT` exists so `mobile-data` can be pointed at
    a non-`/opt/e5` copy of `e5-at` (the offline self-test uses it).
  * `opt/e5/android-run` + `e5-cp_diskserver.service` / `e5-refnotify.service` --
    the two Android vendor daemons mu300 runs and this port did not, so modem NV
    writes (fixed by Android's RIL) are persisted now.
  * Units: `e5-atd`, `e5-mobile-data` (After/Wants `e5-atd`, `TimeoutStopSec=15`),
    `e5-mobile-data-watch`, `e5-cp_diskserver` (`Before=e5-vendor.service` and no
    start delay: `android-run` waits for the chroot itself), `e5-refnotify`, plus
    `e5-vendor` -- enabled in `rootfs/configure-rootfs.sh` and
    `rootfs/device-finalize.sh`.  They gate on `|/dev/modem` only: upstream also
    writes `|/dev/pmsys`, a node this board does not have.
  What the port dropped, on purpose: the CP watchdog, the `nr0` URC log, the
  `/run/e5-atd.state` file, the SIM-storm cooldown and the `sim-reset` avoidance
  of `SFUN=5/3`.  Those were our own answers to the `CP assert ... queue was full`
  and the barred IoT card of 2026-09-18/19 (`docs/FINDINGS.md` 22) and the mu300
  design has no place for them -- so those two problems are, as of now, unhandled.
  **Not yet on the device:** nothing here has been booted, let alone soaked.
  The AT layer is checked offline on a pseudo-terminal (`work/atd-selftest.py`).
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
| baseband | mu300-linux's design, ported: `e5-atd` owns `/dev/stty_nr1` and brokers AT over `/run/e5-at/cmd`, `e5-mobile-data.service` + `e5-mobile-data-watch.service` drive the bearer, `cp_diskserver`/`refnotify` persist the NV; not booted or soaked yet |
| wifi | `sprd_wlan_combo` on the WCN chip: scans 2.4 and 5 GHz APs out of the box; MAC is random per boot |
| hotspot | `hostapd` 2.10, `AP-ENABLED` on 5 GHz ch149 at **80 MHz VHT80 (centre 155)**; the old `HT_SCAN` stall was the missing `country CN`, not the width; no AP+STA concurrency |
| bluetooth | attaches and scans (LE + BR/EDR have both found devices), but an attach can fail unrecoverably and the chip later stops answering scan commands; BD address is the chip's default |
| keys | 9-key keypad works; volume/power/KEY_F1 events verified; confirm = KP_Enter, back = back+delete; power = logind (short press locks and the lock screen blanks the panel, a tap wakes it; long press powers off) |
| disk | 4.4 GiB used, 1.2 GiB free |
| apt | Nanjing University mirror over http (TLS handshakes hang on this bearer) |

## Committed on 2026-09-19

- The baseband rewrite (`b36e86b`): `opt/e5/{e5-atd,e5-at,android-run}` are new,
  `opt/e5/mobile-data` is rewritten, `opt/e5/{atd.py,cp-watchdog,e5-at.sh}` and
  `etc/e5/cp-watchdog.conf` are deleted, five units are back and the two build
  scripts enable them.  (The previous baseband bullet in this file is history.)
- `opt/e5/e5-next-boot`, the `mu300-next-boot` port: `linux` records
  `/etc/e5linux/default-boot=linux` and arms slot b, `android` records the other
  choice and writes the recorded slot-a block back, `--rearm` is what
  `/usr/local/sbin/e5-boot-ok` now execs (one implementation of "which slot comes
  next"), and it acts only when the recorded default is linux, so a one-off trial
  boot does not re-arm itself.  `status` prints the recorded default and the misc
  block for both slots; the byte layout was re-checked against `dumps/misc-head.bin`
  (slot a at byte 12, `9f` = prio 15/tries 9/successful 1) and the trial block
  (slot b at byte 14, `2f` = prio 15/tries 2/successful 0).  The image ships
  `default-boot=linux`, so a fresh install behaves as before and this is the scripted
  way back to Android from a running Linux (`e5-next-boot android`, then reboot).
- `opt/e5/rootfs-fixups` + `e5-fixups.service`, the `mu300-fixups` port: restores
  ping's `cap_net_raw` (tar/docker export drops xattrs) and links
  `e5-next-boot`/`mobile-data`/`e5-at` into `/usr/local/bin`, which is what makes
  `sudo e5-next-boot android` work at all.  Enabled in both build scripts.
- `tools/verify-device.py`: the read-only audit described below.
- `boot/init`: the comment that still named the removed `e5-adbd.service` now points
  at `docs/FINDINGS.md` 21.
- `.gitignore` takes `out/` (the 8 GiB `rootfs.ext4`) and `.DS_Store`; the tracked
  `rootfs/.DS_Store` is gone.

### What the device is actually running (audit, 2026-09-19)

`tools/verify-device.py` mounts `/data/e5linux/rootfs.ext4` read-only on the (rooted)
Android side, compares it file by file with the tree, and reads the flashed image's own
overlay list out of the initramfs.  On this unit:

    boot image   device boot_b head56m == boot-linux-slotb.img (99d9d453...), so the
                 image being audited is the one the device boots
    overlay      70 files in the tree, 3 not in the image: tonight's e5-next-boot,
                 rootfs-fixups and e5-fixups.service
    rootfs       77 files checked, 4 wrong: those 3 plus usr/local/sbin/e5-boot-ok
    leftovers    etc/e5/cp-watchdog.conf and e5-cp-watchdog.service -- the Python CP
                 watchdog, deleted in b36e86b; the overlay only ever adds, so nothing
                 on the device removes them
    units        e5-hotspot, e5-regdb-load and e5-gadget-guard are enabled by the build
                 scripts but neither linked nor pulled in on this device: this install
                 predates that part of configure-rootfs.sh (its comment says the same).
                 e5-telnetd is pulled in by the NetworkManager drop-in, and e5-atd,
                 e5-mobile-data(+watch), e5-cp_diskserver, e5-refnotify, e5-vendor,
                 e5-boot-ok and e5-zram all have their *.wants/ links.

The device is on Android (slot a) as of this audit.

## Open questions

- **`packages.list` still installs the Plasma half of the session.**  The comment above
  it now describes reality (phosh is the session, panfrost does the rendering), but the
  list still pulls in `plasma-mobile`, `plasma-workspace`, `kwin-wayland`,
  `kwin-x11` and `xdg-desktop-portal-kde`, and `etc/sddm.conf.d/10-e5.conf` says the
  X11/KDE session "is purged".  Either drop those five (a fresh install is then
  phosh-only) or keep Plasma selectable and fix that comment -- it is a decision, not a
  bug, and it is the last thing in the fresh-install path that still carries the old
  design.

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

### 2026-09-18, late night (the 80 MHz hotspot round, and the modem going out of service)

* **Channel 149 at 80 MHz is done and verified end to end.**  The "40/80 hangs in
  HT_SCAN" conclusion was wrong: with `country CN: DFS-FCC` (the regdb reflash of
  section 20) the driver advertises `5725-5850 @ 80 MHz` and hostapd sets the AP up
  itself (`Set freq 5745 ... bandwidth=80 MHz, cf1=5775`), beacon VHT Operation
  `width=1, seg0=155`; 4/4 start orders reached `AP-ENABLED`.  A phone connected to
  `E5-Linux` and **reported 80 MHz** (*user-verified*).  `etc/hostapd/e5.conf` is the
  80 MHz profile and `hotspot-start.sh` no longer pre-sets the channel; it now fails
  loudly (and retries once) when hostapd does not come up.  See FINDINGS 20.4/20.5.
* **The overlay-restore trap bit us, and the fix is the flashed image.**  Pushing
  `etc/hostapd/e5.conf`, `opt/e5/hotspot-start.sh` or `opt/e5/mobile-data` is undone by
  the next boot (the initramfs overlay is copied over them; files that are *not* in the
  baked overlay, like the new `atd.py`, survive).  That is why the hotspot came up
  trying **2.4 GHz channel 6** after a reboot and why the watcher lost its fix.  The
  image has now been rebuilt (`boot/build-boot-image.py`, busybox recovered from the
  device's own `/usr/local/bin/busybox`) and written into a boot slot; the tree is the
  single source of truth again.
* **Both slots held Linux images -- Android's boot image was gone.**  `boot_a` sha was
  byte-identical to the previous Linux image and `boot_b` to an older one, so every BCB
  "switch to Android" landed in Linux (LK logged `ANDROID: Booting slot_a`).  Fixed:
  `boot_b` now carries the new Linux image and `boot_a` the Android image the user
  supplied (`/Volumes/Projects/e5/spd_dump-macos/b.img`, sha256 `3ff27449...`), so
  Android is the fallback again and a switch back to Linux is one `dd` of `boot_b`
  over `boot_a` (or arming slot b, tries=2).
* **The modem went out of service at 23:07, on both systems.**  The URC log caught the
  network throwing us off -- `+CGEV: NW PDN DEACT 1`, `+CGEV: NW DETACH`,
  `+SPERROR: 14,27,"46001"` -- and after that neither Linux (`+CGATT: 0`,
  `AT+CGATT=1 -> +CME ERROR: 0`, `AT+CGACT=1,1 -> +CME ERROR: 28`, `+COPS: 46001` but
  no PS attach) nor **Android** can register: `mDataRegState=1(OUT_OF_SERVICE)`,
  `mIsEmergencyOnly=true`, while `mCellInfo` still shows a healthy LTE band 1 cell
  (rsrp -90, mRegistered=YES).  So the RF and the cell are fine and the network is
  refusing service -- most likely the SIM was barred after the repeated abnormal
  detaches.  Not a Linux-side bug; test the SIM in another phone / reseat it.
* **Shutdown was slow because of `btattach`, not just NetworkManager.**
  `e5-bt-attach.service` sat in `final-sigterm timed out` and then reported
  "Processes still around after final SIGKILL"; it now has `KillSignal=SIGKILL` and
  `TimeoutStopSec=2`, and a `system.conf.d` drop-in caps `DefaultTimeoutStopSec` at
  5 s (`DefaultTimeoutStopUSec=5s` verified after a daemon-reload).  A watchdog reboot
  must not wait on vendor teardown.
* **`mobile-data` fixes from this round:** `radio_on()` no longer trusts `+CFUN` (a cold
  CP can read 1 with the stack off -- the modem sat at `+CEREG: 2,0` until SFUN=2/4 were
  sent), `wait_registered` accepts this modem's `+CEREG` stat 8 and is bounded,
  `watch()` keeps separate interface and PDP-context counters (the one reset by the other
  hid the 23:07 deactivation for half an hour), and `sim-reset` drops `SFUN=5/3`, which
  leaves this modem's SIM undetected until a reboot.
* **The reconnect storm barred the user's IoT SIM -- the guard is in now.**
  Evidence: the network detached us at 23:07:12; after that
  `e5-mobile-data.service` (`Restart=on-failure`, `RestartSec=30`) and
  `e5-mobile-data-watch.service` (`Restart=always`, `RestartSec=15`) restarted the
  bring-up over and over -- every attempt sending `AT+SFUN=2`/`AT+SFUN=4`, polling
  `+CEREG` and trying `+CGACT`/`+CGCONTRDP` -- amplified by `sim-reset` (SFUN=5/3)
  and by manual `AT+CGATT=1`/`AT+CGACT=1,1`/`CFUN` pokes.  The card (ICCID
  **89860626690008016183**, China Unicom, an IoT/M2M SIM) stopped being accepted:
  Android now shows the same emergency-only state with a healthy LTE band 1 cell
  (rsrp -90) and `Uni-DNC-0: not allowed - PS is rejected`.  Fixes: `up()` records
  failures in `/run/e5-mobile-data-fails` and refuses to try again after **5 in
  30 min**; the watcher runs `up` in a subshell and backs off 60 s -> 30 min on
  failure (a failing `up` used to `exit`, which took the watcher down and let
  systemd restart it every 15 s); `e5-mobile-data.service` no longer has
  `Restart=on-failure`; the watch unit's `RestartSec` is 60; `sim-reset` no longer
  sends SFUN=5/3 (it left the SIM undetected until a reboot).  Lifting the bar is up
  to the operator.


* **wlan0 is currently NetworkManager-unmanaged**
  (`/etc/NetworkManager/conf.d/20-e5-wlan0-unmanaged.conf` was added so hostapd can own
  the interface) and `wpa_supplicant.service` is masked.  Remove both to go back to
  station mode.


### 2026-09-19, early morning (audio: the sound stack works, the AGDSP power domain does not)

The audio modules were missing from the image entirely (`out_modules` had no
`snd_soc_*`), which is why the port had no sound card.  With the vendor set added
(`sound/soc/sprd/unisoc/*` + `drivers/unisoc_platform/sprd_audio/*`, 24 modules, the
same set Android loads) the Linux side comes up with the full stack:

* `/proc/asound/cards` -> `sprdphone-sc2730`, codec `ump9620`, and the AW87xxx
  smart PA probing on i2c 6-0058 and parsing its profile
  (`aw87xxx_fw_load_work: acf parse succeed`, products `aw87390`, profiles
  Music/Receiver/Off) from `/vendor/firmware/aw87xxx_acf.bin` (now in
  `rootfs/overlay/lib/firmware/`);
* the speaker path controls were identified: `VBC_SYSTEM_DEV_CHANGE` /
  `VBC_CUSTM_DEV_CHANGE` = `TYPE_SPK`, `Speaker Function` = 1, `Speaker Mute` = 0 and the
  FE->BE DAPM switches `S_NORMAL_AP01_P_*` (the routing driver's
  `sprd_pcm_routing_intercon[]`); without them a plain PCM open fails with
  `FE_NORMAL_AP01: ASoC: no backend DAIs enabled`.

**The blocker is `agdsp_pd.ko`**, the vendor AGDSP (audio DSP) power-domain module:

* as shipped, loading it takes the board down within seconds -- no oops survives, the
  reset comes from the PMIC watchdog (docs/FINDINGS.md 9);
* with its SIPC kthread and its `pm_genpd_init()`/`of_genpd_add_provider_simple()`
  skipped, the board survives but the sound card defers **forever**:
  `vbc-rxpx-codec-sc27xx sound@0: asoc_sprd_card_parse_of: Parsing dai link 0
  failed(-517)` (the codec and the VBC dai take that domain as their
  `power-domains` provider);
* with the genpd registered but `sprd_agdsp_pw_on/off` made no-ops, the same `-517`
  loop still floods the console and the board resets again after a few minutes.

So the AGDSP must be *powerable* for the card to bind, and powering it is what kills
the board -- the same "bring up a DSP that our port never boots" class of problem as
the modem CP.  The patch (three `if (0)` cuts: kthread, and the two power callbacks)
is kept in `work/agdsp-patch/agdsp_pd.patch` and is applied in the vendor tree; the
last known-good image is `work/boot-noaudio-stable.img` (78 modules, no audio,
sddm masked).  Next ideas: give the codec its own power domain via DT, or find what the
card's dai link 0 is actually waiting for (`/sys/firmware/devicetree/base/sound@0/`).

### 2026-09-19, AGDSP hybrid genpd test

The first Linux-style AGDSP port is now in the kernel tree. `agdsp_pd` no longer
uses the legacy PSCP `smsg` kthread or PSCP shared-memory handshake. It keeps the
PMU/mailbox wake path, reads the PMU state before sending the wake command, and
leaves AP access and the DSP awake across runtime-PM idle instead of executing the
vendor power-off sequence.

The test image loaded all 91 modules. `audio_sipc` created the AGDSP ring, DSP
commands received replies, UMP9620/VBC/TDM and AW87390 all probed, and the ASoC
route setup completed without the earlier `-517` storm. Repeated logical
`power_on`/`power_off` cycles did not reset the board.

The test was then followed by an unexpected reboot after `switch-root`, despite
no user action. The device automatically returned to Android slot A. The
available `sysdumpdb` report is still the earlier `systemd-shutdow` fault
(`device_shutdown -> _dev_info -> page fault`), while this boot's persistent log
ends at `switch-root`; therefore the post-switch-root trigger is not yet proven
to be the old shutdown callback or an AGDSP fault. The test image was
`work/boot-linux-slotb-agdsp-test3.img`; initialization success is not yet a
stability claim.

The follow-up test disabled the CP watchdog reboot action (`ACTION=log`) and
cleared `sysdumpdb`, pstore, last-kmsg and the boot persistent-log area first.
It still returned to Android after `switch-root`. No new sysdump report survived,
but that is not evidence against a kernel panic: this device's reset path clears
the ramoops/sysdump area before the next boot. The fresh boot log ends at
`switch-root`; audio initialization is proven, while the post-systemd panic
needs live serial or vendor minidump capture.
