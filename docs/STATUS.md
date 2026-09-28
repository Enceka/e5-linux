# Status

_Last updated 2026-09-28._

Reasoning, evidence and dead ends live in `docs/FINDINGS.md`; traps found the hard
way are collected in its sections 24.8 and 28.  This file is only the work list.
Done work is removed from it once its result is in the table at the bottom or in
FINDINGS.

## Now (目前要做)

- **Android no longer boots: it stays on the logo (found 2026-09-28, after the mainline
  M6 trial).  A full stock-system reflash is planned; the failure requires investigation.**
  What is known (evidence in `logs/android-stuck-20260928/`):
  1. Timeline: the last Android boot seen working was ~02:05 on 2026-09-28 (the DSI-fix
     trial was flashed from it).  Six mainline trials followed, all flashed from the
     running OpenWrt trial (`upstream/trial-from-openwrt.sh`), never through Android;
     the sixth (M6: charger manager, UMP96xx fuel gauge, AW32257, vendor thermal, the
     USB pin mux built in) never came back on USB or adb.  The device then stood on the
     Android logo -- with its own `boot_a`, with a stock boot, and after a userdata wipe.
  2. Recovery/fastbootd from slot a works; normal boot does not.  LK is not the
     difference: in `uboot_log` the stuck boot and a good one from before get the same
     slot, `androidboot.mode=normal` (not calibration or factory mode) and the same
     `androidboot.*` fixups; LK hands over to the kernel both times.  So it hangs in
     the Android kernel or init.
  3. Slot a vs slot b, read from the 5.15 rescue system: equal -- `vendor_boot`, `dtb`,
     `dtbo`, all `vbmeta*`, `uboot`, `sml`, `trustos`, `teecfg`, `l_agdsp`, `ch_sys`,
     `pm_sys`, `nr_modem`, `nr_phy`, `nr_deltanv`, `avbmeta_rs`, `common_rs2`,
     `hypervsior`, and `mmcblk0boot0`/`boot1` (the two SPLs).  Different -- `boot`
     (b is Linux; a is the existing Magisk-patched boot), `init_boot` (a is
     Magisk-patched, as it has long been), `nr_fixnv1`, `nr_fixnv2`, `common_rs1`.
     The NV pair is the prime suspect of what the Linux side writes: the mainline
     trials ran `modem_control`/`cp_diskserver` with `androidboot.slot_suffix=_b` from
     the bootconfig (vendor-start rewrites only `/proc/cmdline`), the `_b` by-name
     links pointing at `_a`.  Whether a/b NV differ on a healthy device is not known.
     Other candidates: PMIC/charger state left by the M6 drivers (persists while the
     battery is connected), `prodnv`/`miscdata`, Trusty's RPMB storage.  Not the
     cause: userdata (wiped, same hang), `boot_a`/`init_boot_a` (the previously working images).
  4. No Android kernel log yet: a long press is a cold reset and pstore came back
     empty.  After the reflash, before anything Linux touches the device: dump every
     partition (above all `nr_fixnv*`, `nr_runtimenv*`, `prodnv`, `miscdata`,
     `common_rs1`) so a later difference can be pinned, and get Android's log of a
     stuck boot some other way (adb if it comes up, or a warm reset).
  5. This LK's A/B rules, learned on the way: a slot that is not successful and has
     1 try left is taken as failed at once ("slot 0 booted fail, rolling back spl and
     reboot into normal", "exchange boot slot!!!" -- it swaps the eMMC boot partition;
     harmless while boot0 = boot1); with 2 tries it is attempted.  One such swap
     happened on 2026-09-28, from a misc block written by hand; the log shows no other.
  State left: slot a active, `misc` bootloader_control the original slot-a block
  (`5f61...0be17146`), `boot_b` = `work/boot-linux-slotb-bundle.img` (5.15; with no
  root image it runs the standalone rescue on 192.168.77.1, telnet, and restores slot
  a itself), userdata wiped.
- **Android is back (2026-09-28, later): a full stock-system reflash restored Android.**  It
  now reports Android 13 (was 14), adb + Magisk root work, slot a, `misc` back at the
  slot-a block; userdata was wiped by the reflash, so the root images,
  `device-files.tar` and the WCN firmware copies on it are gone -- reinstalled from
  the repository and the flash bundle the same day (see the mainline bullet).
- **Mainline 6.18 M6 runs on the device (2026-09-28, evening): charging, fuel gauge
  and the charger manager are live; M7 audio panicked at first, fixed the same day.**  Built on
  the new host (x86_64 Fedora, no docker: `upstream/build-native.sh` with a Bootlin
  aarch64 gcc 15.3 toolchain; `6.18.54-e5-g03e89ea23e7e`, zero warnings) and trialled
  from the reflashed Android through `upstream/trial-from-android.sh` (probe first:
  `logs/mainline-probe-20260928`; then the full trial: `logs/mainline-full-20260928`)
  on an OpenWrt root from the c4360f9 flash bundle plus `device-files.tar`:
  * M6 seen working: `aw322xx_charger` online and **Charging at 496 mA** over USB,
    `sc27xx-fgu` reads the battery (100 %, 4.35 V, 31.8 C), charger-manager logs its
    telemetry every 15 s (vbat/vbus/ibat/soc, Tboard 25.0 C, Tbatt 31.9 C) -- snapshots
    in `logs/mainline-full2-20260928/`.
  * M6 thermal: the battery zone works; the SoC/board sensors register no zones
    (`virtual_thermal` probe -22, missing `board-thmzone`) -- to check by hand, which
    is what the modules were for.
  * M4 re-verified without a SIM (none inserted): CP booted by the vendor chroot, SIPC
    up, `sipc_wwan` loads by hand and gives `/dev/wwan0at0`, ModemManager lists the
    modem.  (`e5-sipc-wwan` not loading it by itself was the trial root's old script:
    it insmodded `wwan.ko`, which mainline builds in -- FINDINGS 47.7.)
  * **The panel lights at 7 s** instead of 32 s (linux-lts-e5 `aab3f8f6d`: `of_iommu`
    no longer waits for the vendor's display IOMMU), so fbcon shows the boot's log.
  * **Both SIM cards, switchable (FINDINGS 47)**: `sipc_wwan card=` (`cfbb848c9`,
    `9ec968c3b`), the unisoc plugin's two-card bring-up, `+SPSWDATA` and SIM slots
    (OpenWrt E5REV 5), `e5-sim`, the info screen's "SIM 卡" and status-bar card; data
    on `sipa_eth0`/`sipa_eth8`.  Every card needs its band lock, or the CP asserts
    (`DRM_SPR_RF`, Android too).  `e5-modemd` answers the CP's asserts: a reset in
    4-5 s instead of 300.  All on the trial root by hand so far: the next rootfs build
    (and flash bundle) carries it.
  * **M7: the DSP boots again** (linux-lts-e5 `8048e353a`): the first full trial had
    panicked in e5-audio-dsp's write into `audiocp_boot` (`memset_io` on NULL+0x400,
    `logs/mainline-full-20260928`): `audio_mem_vmap()` vmapped memory that has no pages
    -- the DSP's IRAM (SRAM) and its no-map DDR -- and handed back NULL plus the page
    offset.  It ioremaps such memory now, as `ce632be0c` did for sipc.  On the device:
    24/24 modules, the card registers, image written, `start` accepted, no panic; the
    audio modules are back in `upstream/root-modules.txt`.  Then `/etc/init.d/e5-audio`
    ran in full on the trial (profiles, speaker route, volume 10/15, PulseAudio up), no
    oops; **playback requires on-device listening validation** with the info screen's 声音 -> 播放测试音
    (`e5-volume play beep`) -- result to note here.  Seen on the way: the card's rebind
    in `e5-audio-dsp` logs two `WARNING`s at `drivers/regulator/core.c:2478`
    (`sprd_headset_remove` -> `sprd_headset_power_deinit` puts the headset regulators
    still enabled); harmless, a disable before the put would silence it.
  * `console=tty0` added (commit `f964cfa`): kernel messages on the panel once the
    display modules load.
  `linux-lts-e5` is on GitHub after all (the fresh clone of 2026-09-28 came from
  `Enceka/linux-lts-e5` with `e5-6.18` at the M7 commit) -- rooted, shallow history.
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
  1.24 with the `unisoc` plugin (`rootfs/deb-patches/modemmanager-0[1-6]`) drives it,
  NetworkManager's `Mobile` connection brings context 1 up on `sipa_eth0` (IPv4
  static from `+CGCONTRDP`, IPv6 SLAAC, the /64 passed to `br0`).  Phosh shows the
  signal, Chatty lists the SIM's SMS (and deletes them from the SIM once imported),
  UFI-TOOLS reads ModemManager and toggles the `Mobile` connection, `e5-at` goes
  through `mmcli --command`.  SMS and calls work both ways in Chatty and Calls
  (verified on the device, 2026-09-26; the plugin writes the SMSC back once per
  boot, FINDINGS 37.4); still open: call audio (see Next), a real CP reset (a
  module reload recovers).  The CP boot is still `modem_control` in the chroot.
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
- **The hotspot can be joined again** (FINDINGS 38, `kernel/patches/0027`): the
  P2P Device NetworkManager's wpa_supplicant added next to wlan0 made the
  firmware answer no station; the driver offers no P2P now.  Checked with a Mac;
  a phone to confirm.  Also open: the beacon's bogus Extended Supported Rates
  (HT rates in the legacy tables), and a `cancel_work_sync` WARNING in
  `sprd_dpu_stop` when the panel blanks.
- **BT off no longer kills Wi-Fi** (FINDINGS 38, `kernel/patches/0026`): a
  blocked BT switch at boot hung the shared SDIO bus and asserted the Wi-Fi
  firmware -- the hotspot could not be joined.  Still open: a BT power cycle
  (rfkill, the shell's BT switch) brings hci0 back without its vendor
  configuration (placeholder address 27:93:31:14:22:11) -- the setup runs only at
  attach; `HCI_QUIRK_NON_PERSISTENT_SETUP` is the candidate, untested against an
  already enabled core.
- **The hotspot in Phosh and Settings: patched, to be confirmed in use** (FINDINGS
  38).  Phosh shows the bridged `Hotspot` as on and turns it off (it has no "on"
  of its own in 0.46); Settings' Wi-Fi panel turns the same connection on instead
  of creating a NAT-sharing one.  UFI-TOOLS and `nmcli` control it too.
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
  the vendor KMS driver's dumb buffers (their creation limit is gone since kernel
  `0025`: it had left the panel black after enough screen-off/on cycles, FINDINGS
  38), and (b) the frequency is pinned at DVFS index 3 (384 MHz) because devfreq
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
- **Call audio.**  Calls work in both directions under ModemManager (Calls rings,
  answers, dials, hangs up; FINDINGS 37.4), but neither side hears anything: nothing
  routes the codec (mic, earpiece/speaker) into the CP's VoLTE voice path.  Needs the
  vendor voice route in ALSA (the AGDSP's voice scene, as the Android audio HAL sets
  it up in a call), a UCM "Voice Call" verb, and callaudiod to switch it.
- **The CP's 300 s dump wait after an assert** (FINDINGS 30): answered on OpenWrt by
  `e5-modemd` (FINDINGS 47.6); the Debian root has no such client yet.
- **SIM hot plug** (FINDINGS 47.7): the plugin drops the CP's `+ECIND: 3,<v>`; capture
  what the CP reports on a real plug, then have ModemManager re-read the card.
- **The info screen's "默认频段" unlocks NR**, which this baseband cannot take
  (FINDINGS 47.2): use the validated device band lock as the default (b1+b41, n41+n78) or drop it.
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
| kernel | rebuilt `Image` (sha256 `17b829a4...`, `kernel/patches/0001-0009`); modules carry `0010-0017`, `0019`-`0025`; `Image` #4 with `0018` (BT); slot-b boot; console level 4 on the real root (FINDINGS 29) |
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
| vibrator | `sc27xx-vibra` from the initramfs (native16): a force-feedback device, feedbackd on Debian (FINDINGS 40) |
| touch | `tlsc6x`: Debian via udev; OpenWrt needs `ABS_X`/`ABS_Y` for libudev-zero (kernel `0028`, native17, FINDINGS 42) |
| keys | 9-key keypad works; volume/power/KEY_F1 events verified; confirm = KP_Enter, back = back+delete; power = logind (short press locks, long press powers off) |
| disk | 2.0 GiB used, 1.9 GiB free on the 4 GiB loop file |
| apt | Nanjing University mirror over http (TLS handshakes hang on this bearer) |
| mainline | 6.18.54 in `linux-lts-e5` (branch `e5-6.18`): M1-M6, M8 run on the device under OpenWrt, M7 (audio) loads and boots the DSP, playback untested; both SIM cards (FINDINGS 47) |
| openwrt | OpenWrt 25.12.5 in `/openwrt` of the root image, booted by `boot-os`/`boot-os-next` (`e5-os`); WAN by ModemManager (+ patch `06`), LAN `br-lan` = usb0 + AP, IPv6 /64 on the LAN; `openwrt/README.md`, FINDINGS 39; standalone as `/data/e5linux/openwrt.ext4` with its own firmware, vendor subset, modem modules and fonts, no Debian needed (native18, FINDINGS 43) |

## Open questions

- **`xdg-desktop-portal` has no backend in a fresh install.**  The Plasma half of the
  session was dropped on 2026-09-19 (`packages.list` keeps the reasoning), which
  leaves `xdg-desktop-portal` with nothing to hand requests to.  Decide which backend
  the phosh session wants: `xdg-desktop-portal-gtk` (file chooser, notifications) or
  `xdg-desktop-portal-wlr` (screencast -- phoc is wlroots-based).
