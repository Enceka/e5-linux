# Status

_Last updated 2026-10-01._

Reasoning, evidence and dead ends live in `docs/FINDINGS.md`; traps found the hard
way are collected in its sections 24.8 and 28.  This file is only the work list.
Done work is removed from it once its result is in the table at the bottom or in
FINDINGS.

## Now (目前要做)

- **The SD card install's update** (FINDINGS 49): `flash.py --update` refuses a card
  system.  The proposed way (2026-10-01), all of it on the card, nothing on userdata:
  1. **A second root partition on the card**, written while the first one runs:
     `device-install-image.sh` on a card system writes the new image into the card's
     other root partition (created in the free space the first time --
     `/usr/libexec/e5-gpt`, a GPT editor in ucode, since OpenWrt has no sgdisk; tested
     on a copy of the card's table, `sgdisk -v` clean), through the whole disk at its
     offset (the kernel cannot re-read a table whose partition is mounted), then the
     settings and the device's files as now, then the marker last.
  2. **boot/init picks the newest**: every marked partition carries a generation
     (`/etc/e5/sd-gen`); the highest wins.  A new one comes with `/etc/e5/sd-trial`:
     boot/init sets it to 0 as it boots it, `e5-boot-ok` removes it once the system is
     up, and a partition still at 0 is skipped -- the previous one boots again, with
     its settings as they were.
  3. `flash.py --update`: the card path instead of the refusal, no `boot-os` write.
  Needs: the image rebuilt (e5-boot-ok, e5-gpt), a boot image (boot/init), a device
  test (update, trial confirmed; a broken trial falls back).
- **Userdata's F2FS is damaged across power cycles under mainline (four times,
  2026-09-29; FINDINGS 48)** -- metadata blocks of the last checkpoints came back
  older after a reset or power off, the fourth time after a clean unmount.  The SD
  card install moves the root off userdata, **but boot/init still mounts userdata
  read-write for the whole session** (to read `e5linux/boot-os`, then moved to
  `/mnt/e5-data` with `discard`), so the risk is smaller, not gone.  For a card
  system: mount it read-only, or only for the moment of reading and writing
  `boot-os`.  The cause itself: not lost flushes (48.2: 10 power cycles, every block
  intact) and not a fresh F2FS under load (30 cycles clean).  Still to try, one at a
  time: Android writing the filesystem in between Linux boots (it had in all four
  cases), an aged filesystem filled to 80-90 %, runs of 20+ minutes, `discard` off;
  only then the eMMC path of 48.4 (cache, shutdown, HSQ vs swcq, discard
  granularity).
- **Two SIM cards of one operator: only one is recognised** (reported 2026-09-29,
  no test setup yet).  To look into in the unisoc plugin's two-card bring-up and
  `e5-sim` (FINDINGS 47): whether both are brought up when their IMSI prefix is the
  same, and what the CP reports for the second.
- **One `boot/flash-from-linux.sh` run rebooted straight into Android (2026-09-25).**
  The image verified on `boot_b` and slot b was armed, yet after the reboot `misc`
  held the slot-a block again.  Unexplained.  Recovery that works: from Android,
  write `*.misc-slot-b-trial.bin` into `misc` and reset with sysrq (FINDINGS 24.5).
- **Find out what takes AGCP access away under an open stream** (FINDINGS 32):
  since `0016` it no longer crashes the device, but the position then freezes.
- Audio leftovers: the earpiece routed as on 5.15 was silent (the E5 may have none);
  the AP capture FE (hw:N,0) stalls after one period; `VBC_*_DEV_CHANGE=TYPE_SPK`
  fails at boot (Android plays with both at `TYPE_INIT`).  The card's rebind in
  `e5-audio-dsp` logs two `WARNING`s at `drivers/regulator/core.c:2478` (headset
  regulators put while enabled; harmless).
- Bluetooth leftovers (FINDINGS 8.7, 38): an attach can fail (the first HCI Reset
  before the chip's BT channel is up) -- since 2026-09-30 `e5-bt-check` brings hci0 up
  or attaches again; after repeated BT power cycles the chip stopped answering new
  HCI commands; a BT power cycle brings hci0 back without its vendor configuration
  (`HCI_QUIRK_NON_PERSISTENT_SETUP` the candidate).
- **`/dev/null` and friends come up 0660 on some boots** (Debian, FINDINGS 37.3):
  `rootfs-fixups` restores 0666 and logs it; the culprit is not found.
- The hotspot: a phone reaching an IPv6-only site, and the management ports closed
  from its side, are unchecked; the beacon's bogus Extended Supported Rates; a
  `cancel_work_sync` WARNING in `sprd_dpu_stop` when the panel blanks.
- GPU: scanout buffers are still the vendor KMS driver's dumb buffers, and the
  frequency is pinned at DVFS index 3 (384 MHz): watch thermals under real load.
- `unisoc-cpd` (the fallback baseband owner on Debian): the 72 h soak is open.

## To test (待测试)

In the installed image (`218d47e`, flashed 2026-09-30), not yet checked -- most of
it needs a SIM card.

- **Text messages** (e5-linux `b90eead`, e5-infoscreen `7834ba8`):
  `/usr/libexec/e5-sms` (list, send, delete, forward), LuCI 服务 -> 短信, the info
  screen's `POST /api/sms-send` and `e5.sms.send()`.  To check:
  1. LuCI lists the messages of the card in use, the header naming the card and
     operator; delete and 回复 work.
  2. Sending from the card in use, then from the other card: LuCI switches first
     (`e5-sim`), waits for the registration (up to 2 min), then sends; the message
     arrives, long ones in parts.
  3. The forward: a preset, the test button, then a real message: forwarded once all
     its parts are in, `{text}` with quotes, newlines and Chinese intact in JSON
     and in a form body; a failing URL is tried three times and logged.
  4. `e5-sms-notify` still vibrates, and forwards only with the forward on.
  5. A plugin's `e5.sms.send(number, text)`.
  Known limit: ModemManager has one modem, the card in use; the other card's new
  messages are not seen (its URC ring is drained, FINDINGS 47.1) until it is
  switched to.  Real dual-card messaging needs the other card's ring as a second
  AT port (sipc_wwan) and a reader of its own.
- **Bluetooth 开机启动** (`e5-bluetooth.main.autostart` -> bluetoothd's AutoEnable):
  off in 高级 -> 蓝牙 (or LuCI 服务 -> 蓝牙), reboot: `bluetoothctl show` says
  `Powered: no`; on in 高级 -> 蓝牙 works and a headset connects; on again, reboot:
  powered at boot.
- **USB replug** (`e5-usb-watch`): a real unplug and replug from a computer's port
  (SDP/CDP) -- the gadget enumerates again.  Tested only by disconnecting it by hand
  (connected again after 2 s).  It may also be the 2026-09-28 trial boot that showed
  no gadget on the host at all.

## Deployment validation (发布验证)

- Push the repositories (nothing is pushed: e5-linux, e5-infoscreen,
  infoscreen-plugins).
- **App store**: create `Enceka/infoscreen-plugins` on GitHub from
  `../infoscreen-plugins`, push, Pages from Actions.  The screen's 应用商店 reads
  `https://enceka.github.io/infoscreen-plugins/index.json`.
- **The screen's online update**: upload the release in e5-infoscreen's `dist/`
  (v1.1.0, `latest.json` and the tarball) to `Enceka/e5-infoscreen`.

## Next (后续要做)

- **An idle blank does not lock the session** (Debian/Phosh, FINDINGS 18).
- **Call audio.**  Calls work in both directions under ModemManager (FINDINGS
  37.4), but nothing routes the codec into the CP's VoLTE voice path.
- **The CP's 300 s dump wait after an assert** (FINDINGS 30): answered on OpenWrt by
  `e5-modemd` (FINDINGS 47.6); the Debian root has no such client yet.
- **SIM hot plug** (FINDINGS 47.7): the plugin drops the CP's `+ECIND: 3,<v>`.
- **The info screen's "默认频段" unlocks NR**, which this baseband cannot take
  (FINDINGS 47.2): use the validated device band lock as the default (b1+b41, n41+n78) or drop it.
- **Suspend is unusable** while the modem data path refuses it
  (`sipa 25220000.sipa: thread prepare suspend err`).
- **The hotspot's own uplink:** with no AP+STA concurrency the only uplink an AP can
  share is the modem.
- **Battery, charging and thermals** under the 5G link have only been observed in
  passing.
- Builds: `openwrt/build-rootfs.sh` and `upstream/build.sh` run in arm64 containers
  (OrbStack on this host, native -- `orbctl start` first if `docker` cannot connect).

## Where things stand (短状态)

| | |
|---|---|
| board | Rongyue E5 (UMS9621/qogirn6lite, CPU T158), 4 GiB RAM, Android 13 on slot a |
| mainline | 6.18.54 in `linux-lts-e5` (branch `e5-6.18`), the installed system under OpenWrt (`E5_MAINLINE=1 openwrt/make-flash-bundle.sh`, `flash.py`): display, touch, keys, USB gadget, Wi-Fi, BT, both SIM cards (FINDINGS 47), charging and fuel gauge, thermal as on 5.15, speaker and mic; the PMIC power off; filesystems read-only before a reset (FINDINGS 48.3); no eMMC reliable writes |
| power | `poweroff` is a real one without the cable; with a charger in, the PMIC powers the E5 up again and it boots (charger mode is logged, not a charging screen) |
| openwrt | OpenWrt 25.12.5 standalone, on the SD card's partition (the install's default since 2026-09-30; `--data` keeps the image in `/data/e5linux/openwrt.ext4` -- FINDINGS 49) with its own firmware, vendor subset, modem modules and fonts (FINDINGS 39, 43); WAN by ModemManager, LAN `br-lan` = usb0 + AP, IPv6 /64 on the LAN; the info screen (e5-infoscreen) on the panel |
| kernel 5.15 | rebuilt `Image` (`kernel/patches/0001-0028`), the Debian root's; still the fallback flash package |
| rootfs (Debian) | Debian 13 (trixie) arm64 with Phosh 0.46, a loop file inside `/data/e5linux/` |
| baseband | ModemManager 1.24.0+e5 (`unisoc` plugin) on `wwan0at0` (`sipc_wwan`), data on `sipa_eth0`/`sipa_eth8` by card; CP booted by `modem_control` in the vendor chroot; every card needs its band lock (FINDINGS 47) |
| wifi | `sprd_wlan_combo` on the WCN chip: AP for the hotspot, station mode on Debian |
| bluetooth | configured by the kernel like the vendor HAL (factory address, pskey/RF); headphones play under OpenWrt (FINDINGS 45); a failed attach retried (`e5-bt-check`) |
| disk | the SD card can hold the system (FINDINGS 49); the eMMC's userdata (F2FS) holds the images of the `--data` form -- see Now |

## Open questions

- **`xdg-desktop-portal` has no backend in a fresh install** (Debian): decide which
  backend the phosh session wants: `xdg-desktop-portal-gtk` or
  `xdg-desktop-portal-wlr`.
