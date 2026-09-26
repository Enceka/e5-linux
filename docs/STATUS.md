# Status

_Last updated 2026-09-25._

Reasoning, evidence and dead ends live in `docs/FINDINGS.md`; traps found the hard
way are collected in its sections 24.8 and 28.  This file is only the work list.
Done work is removed from it once its result is in the table at the bottom or in
FINDINGS.

## Now (目前要做)

- **Audio: the speaker plays through plain ALSA and PipeWire, every stream (2026-09-26).**
  FINDINGS 24.8 has the chain (kernel `0012`-`0014`, UCM route, profile selects,
  WirePlumber rule); FINDINGS 34 the three faults that left only the first sound after
  boot audible, and at the wrong pitch (modprobe `softdep` for the codec regulators,
  `0019` FE_FAST_P S16 only, `0020` MCDT FEs interleaved only).  Confirmed by ear with
  Amberol.  `wpctl status` shows one Speaker sink.  What is left:
  1. **Four rebuilt audio modules were installed on the device by hand** (originals
     as `*.ko.orig` in `/usr/lib/modules/<rel>/audio/`, and `/root/agdsp_pd.ko.bak`):
     `snd-soc-sprd-card` (0012), `sprd-dmaengine-pcm` (0013),
     `snd-soc-sprd-codec-ump9620` (0014), `agdsp_pd` (0010 without its retry);
     since then also `sprd-dmaengine-pcm` (0016) and `snd-soc-sprd-vbc-fe` (0017,
     0019, 0020; previous copies as `*.pre-guard`, `*.pre-s16`, `*.pre-fast16`).  A
     fresh rootfs gets them from `out_linux` via `configure-rootfs.sh`, which now
     holds the current build.
  2. **Speaker and mic confirmed in use (2026-09-26); the earpiece is routed, not yet
     heard** (FINDINGS 33, 34): the "Internal Microphone" source records voice
     (GNOME Sound Recorder).  Still to do: listening to the earpiece
     (`alsaucm -c hw:0 set _verb HiFi set _disdev Speaker set _enadev Earpiece`).
     The AP capture FE (hw:N,0) still stalls after one period.
  3. `VBC_*_DEV_CHANGE=TYPE_SPK` fails at boot (the DSP is not answering yet at
     that point); Android plays with both at `TYPE_INIT`, so the route leaves them
     alone.  Revisit only if a scene switch needs them.
- **One `boot/flash-from-linux.sh` run rebooted straight into Android (2026-09-25).**
  The image verified on `boot_b` and slot b was armed, yet after the reboot `misc`
  held the slot-a block again and LK never tried slot b.  Two earlier runs the same
  evening worked.  Unexplained; something on the Linux shutdown path may be writing
  the slot-a block.  Recovery that works: from Android, write
  `*.misc-slot-b-trial.bin` into `misc` and reset with sysrq (FINDINGS 24.5).
- **The baseband is native on Linux since 2026-09-26** (FINDINGS 36, 37):
  `sipc_wwan` (kernel 0022/0023) puts the AT channel on a WWAN port, ModemManager
  1.24 with the `unisoc` plugin (`rootfs/deb-patches/modemmanager-0[1-5]`) drives it,
  NetworkManager's `Mobile` connection brings context 1 up on `sipa_eth0` (IPv4
  static from `+CGCONTRDP`, IPv6 SLAAC, the /64 passed to `br0`).  Phosh shows the
  signal, Chatty lists the SIM's SMS (and deletes them from the SIM once imported),
  UFI-TOOLS reads ModemManager and toggles the `Mobile` connection, `e5-at` goes
  through `mmcli --command`.  Still open: voice calls (and their audio route),
  sending SMS from Chatty, a real CP reset (a module reload recovers).  The CP boot
  is still `modem_control` in the chroot.
- **`/dev/null` and friends come up 0660 on some boots** (FINDINGS 37.3):
  `rootfs-fixups` restores 0666 and logs it ("rootfs-fixups: /dev/null was mode
  660"); the culprit is not found.
- **G2, historical: `unisoc-cpd` took the RIL's seat on the handset (2026-09-20,
  Android side); on Linux it was the owner until 2026-09-26.**  It holds both SIPC channels, serves capabilities on a unix socket,
  decodes the URC stream, re-arms the SMS surface, reads MT SMS and re-established
  the data bearer over `cbnet`; MO SMS works too (FINDINGS 25.7).  Still open: the
  72 h soak.  It stays installed on Linux as the fallback (`systemctl start
  unisoc-cpd` stops `e5-sipc-wwan` and ModemManager), with its web page on
  `http://192.168.9.1:7887` while it runs.
- **Bluetooth: configured natively since 2026-09-26** (FINDINGS 33.3, kernel 0018:
  factory address, manufacturer 0x01ec).  Pairing, A2DP and HFP are untested; the two
  older problems below predate the configuration and need re-checking with it.
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
  (The vendor configuration these were measured without is sent by the kernel
  now; re-test before chasing either.)
- **Shutdown: 2.7 s (2026-09-26, FINDINGS 35).**  The ~20-30 s that used to be blamed
  on NetworkManager was the BT core being closed without its disable command:
  `stop_marlin(MARLIN_BLUETOOTH)` waited 30 s with the WCN power lock held and
  Wi-Fi's teardown queued behind it.  `kernel/patches/0021` sends the disable from
  `mtty_close`; the USB link now drops 8 s after `systemctl reboot`.
- **Phosh's hotspot switch does not see the bridged hotspot as on.**  It starts the
  `Hotspot` connection (the first AP-mode profile), but only counts a connection
  with `ipv4.method=shared` as a hotspot, and a bridge port has no IP settings, so
  the switch shows off and cannot stop it (Phosh 0.46 and main, `wifi-manager.c`
  `is_active_connection_hotspot_master`).  UFI-TOOLS and `nmcli` control it fine.
- **The hotspot needs one real client check over the bridge.**  usb0 and the AP are
  one LAN since 2026-09-26 (`br0`, FINDINGS 31): a phone associated and got
  192.168.9.41 plus a SLAAC address in the bearer's /64 during the live change, and
  the USB host has IPv6 through it; still to confirm that a phone reaches an
  IPv6-only site and that the management ports are closed from its side (tested
  only from a namespace port).
- **UFI-TOOLS** reads its modem fields from ModemManager now (5G RSRP included);
  login is `admin` until changed (`ufi-tools set-token` or the web UI; it survives
  reboots).
- **GPU: the two open ends left by panfrost.**  The backport itself is done
  (`kernel/patches/0005`, `MALI_MIDGARD=m`, `docs/FINDINGS.md` 20.7) and clients
  render on `Mali-G57 (Panfrost)`; what is left is (a) the scanout buffers are still
  the vendor KMS driver's dumb buffers, which is why `DUMB_CREATE_TIMES_LIMIT` sits
  at 64, and (b) the frequency is pinned at DVFS index 3 (384 MHz) because devfreq
  is skipped on this board -- watch thermals under real load.  PanVK stays out of
  reach: Mesa has no Valhall v9 backend.

- **Find out what takes AGCP access away under an open stream** (FINDINGS 32).  Since
  `0016` it no longer crashes the device, but the position then freezes; look for
  `AGCP not accessible` in the kernel log, and what powered the domain down just
  before.

## Next (后续要做)

- **An idle blank does not lock the session.**  After `idle-delay` (300 s) the panel
  goes off (`dpms=Off`, `bl_power=4`) and `LockedHint` stays `no`, so a dark phone is
  still unlocked; only the power key locks.  Not a settable default: `lock-enabled` and
  `idle-activation-enabled` are both `true` and still nothing activates the screen
  saver on idle, because this gnome-settings-daemon ships no `gsd-screensaver` and the
  phosh session does not start one; `logind`'s `IdleAction=lock` would need an idle
  hint that phoc never sets (`docs/FINDINGS.md` section 18).
- **Calls and sending SMS** through ModemManager (Calls, Chatty).  SMS over MO was
  proven through `unisoc-cpd` (FINDINGS 25.7: mind the PDU first octet); voice rides
  IMS/VoLTE here and needs the call audio route (UCM "Voice Call", callaudiod).
- **The CP's 300 s dump wait after an assert** (FINDINGS 30): modem_control waits for
  a "dump complete" that only Android's CP log daemon sends.  Recovery itself should
  be automatic now (the AT port leaves and comes back with the channel, ModemManager
  re-creates the modem, NetworkManager reconnects); the five minutes offline are not.
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
| kernel | rebuilt `Image` (sha256 `17b829a4...`, `kernel/patches/0001-0009`); modules carry `0010-0017`, `0019`-`0023`; `Image` #4 with `0018` (BT); slot-b boot; console level 4 on the real root (FINDINGS 29) |
| identity | pretty hostname `Rongyue E5` (`etc/machine-info`), `Processor: Unisoc T158` in `/proc/cpuinfo` (`kernel/patches/0009`), `Hardware Model` row deliberately unset |
| rootfs | Debian 13 (trixie) arm64, a loop file inside Android's `/data/e5linux/`; base ownership/set-id bits recorded in `/var/lib/e5linux/base-perms` |
| session | Phosh 0.46.0, `phoc` with wlroots' GLES2 renderer on the **Mali-G57**; the lock screen accepts the password again (`unix_chkpwd` setgid shadow) |
| gpu | **panfrost**: `mali-g57` id `0x9091`, GLES 3.1 via Mesa 25.0.7, driven by `kernel/patches/0005` + the fragment's `MALI_MIDGARD=m`; kbase is a module nothing loads |
| audio | speaker plays through ALSA (`hw:N,3`, S16 interleaved, UCM verb HiFi / device Speaker) and PipeWire; mic as "Internal Microphone" (`hw:N,2`, mono S16); earpiece routed, not yet heard; AGDSP booted from `l_agdsp_a` by `e5-audio.service`; period events from an hrtimer |
| baseband | ModemManager 1.24.0+e5 (`unisoc` plugin) on `wwan0at0` (`sipc_wwan`) + `sipa_eth0`, NetworkManager `Mobile` connection (context 1, APN `cbnet`), 5G SA; CP booted by `modem_control` in the chroot; `unisoc-cpd` installed as the fallback (FINDINGS 36, 37) |
| wifi | `sprd_wlan_combo` on the WCN chip, managed by NetworkManager (wlan0 only): station mode from Phosh's Wi-Fi menu, AP for the hotspot; scans 2.4 and 5 GHz APs; MAC is random per boot |
| LAN | `br0` 192.168.9.1/24 = usb0 + the AP; IPv4 NAT + the bearer's public IPv6 /64 (SLAAC, stateful firewall); management ports only from the USB port |
| hotspot | NetworkManager `Hotspot` connection (wpa_supplicant AP mode), port of `br0`, `AP-ENABLED` on 5 GHz ch149 at 80 MHz (centre 5775) with the patched network-manager 1.52.1+e5 (trixie's computes that centre wrong); WPS off (with it the firmware-SME driver let no phone associate); a phone joins, gets 192.168.9.x from dnsmasq on br0; up at boot (autoconnect), SSID/PSK changes survive the overlay; no AP+STA concurrency |
| bluetooth | configured by the kernel like the vendor HAL (0018: pskey/RF/enable; 0021: core disable on close); factory address `FC:B5:85:D0:85:9B`, manufacturer 0x01ec; scans, connects, power-cycles; audio profiles untested |
| keys | 9-key keypad works; volume/power/KEY_F1 events verified; confirm = KP_Enter, back = back+delete; power = logind (short press locks, long press powers off) |
| disk | 2.0 GiB used, 1.9 GiB free on the 4 GiB loop file |
| apt | Nanjing University mirror over http (TLS handshakes hang on this bearer) |

## Open questions

- **`xdg-desktop-portal` has no backend in a fresh install.**  The Plasma half of the
  session was dropped on 2026-09-19 (`packages.list` keeps the reasoning), which
  leaves `xdg-desktop-portal` with nothing to hand requests to.  Decide which backend
  the phosh session wants: `xdg-desktop-portal-gtk` (file chooser, notifications) or
  `xdg-desktop-portal-wlr` (screencast -- phoc is wlroots-based).
