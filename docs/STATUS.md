# Status

_Last updated 2026-09-29._

Reasoning, evidence and dead ends live in `docs/FINDINGS.md`; traps found the hard
way are collected in its sections 24.8 and 28.  This file is only the work list.
Done work is removed from it once its result is in the table at the bottom or in
FINDINGS.

## Now (目前要做)

- **Userdata's F2FS is damaged across power cycles under mainline (three times,
  2026-09-29; FINDINGS 48).**  Each time metadata blocks mainline wrote in its last
  checkpoints came back from a reset or power cycle as an *older* content (NAT blocks
  holding old CP/SIT blocks; a SIT block from before its segments were written), the
  checkpoint after them intact.  The third one followed a clean power off (read-only
  remount, `CP_UMOUNT`) with reliable writes already off.  Android's fsck repaired
  it; the vendor kernel never showed it.  Until it is understood, every Linux boot
  that mounts userdata read-write risks Android's data -- the plan is to install on
  the SD card and leave userdata alone (read-only at most).
  **A fourth time on 2026-09-29, 00:29** (`logs/linux-fail-20260929/`): after a clean
  unmount (`data-last-cp flags=0x45 clean-unmount`) the next Linux boot's mount failed
  with -EUCLEAN, boot/init fell to the rescue and then to Android, whose fsck repaired it
  (no fsck log kept).  **Until this is solved, the E5 stays in Android: no Linux boot
  that mounts userdata.**
  Next steps, in order:
  1. ~~A durability test that can see it~~ -- **done 2026-09-29: flushed data is not
     lost** (FINDINGS 48.2): 10 power cycles and resets of every kind over the whole
     `blackbox`, every block held the generation flushed last.  So step 2 (the
     vendor's eMMC path) is not indicated by it.
  2. ~~The F2FS side on a fresh filesystem~~ -- **done 2026-09-29: no damage in 30
     cycles** (FINDINGS 48.2, `upstream/init-f2fstest`): blackbox as userdata (its
     features), boot/init's mount options, a loop ext4 image in it, 90 s of load, then
     reboots and power offs with everything mounted; every fsck and mount clean.
  3. What that test lacked, one at a time: **Android writing the same filesystem in
     between** (a cycle that boots Android and lets it write before Linux mounts again
     -- in all four cases Android had written it first), a filesystem that is **used and
     aged** (fill blackbox to 80-90 % with churn first), **runs of 20+ minutes**.  Also
     `discard` off, to see if the damage needs it at all.
  4. Only if none of that reproduces it: the eMMC path of 48.4 (the cache, the shutdown
     sequence, HSQ vs swcq, discard granularity) under an F2FS load.
  Meanwhile `boot_b` holds the F2FS test image (the release image the E5 had is in
  `work/durability/boot_b-before-durability.img`), and blackbox holds the test's
  filesystem (the original: `logs/durability-20260929/blackbox.img.gz`).
- **To test on the device (written 2026-09-29, not yet run):** see the section
  below.
- **Two SIM cards of one operator: only one is recognised** (reported 2026-09-29,
  no test setup yet).  To look into in the unisoc plugin's two-card bring-up and
  `e5-sim` (FINDINGS 47): whether both are brought up when their IMSI prefix is the
  same, and what the CP reports for the second.
- **One trial boot showed no USB gadget on the host at all** (2026-09-28); the next
  two did, and the silent one's initramfs log had the gadget bound and `usb0` with
  carrier.  Not reproduced -- maybe the replug fault below.
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
- Bluetooth leftovers (FINDINGS 8.7, 38): an attach can fail and never recover (the
  first HCI Reset before the chip's BT channel is up); after repeated BT power cycles
  the chip stopped answering new HCI commands; a BT power cycle brings hci0 back
  without its vendor configuration (`HCI_QUIRK_NON_PERSISTENT_SETUP` the candidate).
  All measured before the kernel sent the vendor configuration: re-test first.
- **`/dev/null` and friends come up 0660 on some boots** (Debian, FINDINGS 37.3):
  `rootfs-fixups` restores 0666 and logs it; the culprit is not found.
- The hotspot: a phone reaching an IPv6-only site, and the management ports closed
  from its side, are unchecked; the beacon's bogus Extended Supported Rates; a
  `cancel_work_sync` WARNING in `sprd_dpu_stop` when the panel blanks.
- GPU: scanout buffers are still the vendor KMS driver's dumb buffers, and the
  frequency is pinned at DVFS index 3 (384 MHz): watch thermals under real load.
- `unisoc-cpd` (the fallback baseband owner on Debian): the 72 h soak is open.

## To test (待测试)

Written and committed, not yet run on the device.  None of it is in a flash
package: the OpenWrt overlay goes into the image (a host with docker or an arm64
binfmt, `openwrt/build-rootfs.sh`), the info screen with it (or copied over by hand).

- **Text messages** (e5-linux `b90eead`, e5-infoscreen `7834ba8`):
  `/usr/libexec/e5-sms` (list, send, delete, forward), LuCI 服务 -> 短信, the info
  screen's `POST /api/sms-send` and `e5.sms.send()`.  To check:
  1. LuCI lists the messages of the card in use, the header naming the card and
     operator; delete and 回复 work.
  2. Sending from the card in use, then from the other card: LuCI switches first
     (`e5-sim`), waits for the registration (up to 2 min), then sends; the message
     arrives, long ones in parts.
  3. The forward: a preset, the test button (needs curl -- in the image from now
     on; `apk add curl` on an older one), then a real message: forwarded once all
     its parts are in, `{text}` with quotes, newlines and Chinese intact in JSON
     and in a form body; a failing URL is tried three times and logged.
  4. `e5-sms-notify` still vibrates, and forwards only with the forward on.
  5. A plugin's `e5.sms.send(number, text)`.
  Known limit: ModemManager has one modem, the card in use; the other card's new
  messages are not seen (its URC ring is drained, FINDINGS 47.1) until it is
  switched to.  Real dual-card messaging needs the other card's ring as a second
  AT port (sipc_wwan) and a reader of its own.
- **Bluetooth 开机启动** (e5-linux, e5-infoscreen `Bluetooth: 开机启动`):
  `e5-bluetooth.main.autostart` -> bluetoothd's AutoEnable
  (`/usr/libexec/e5-bt-autostart`, run by `e5-bt` at start and on a config
  change).  To check: off in 高级 -> 蓝牙 (or LuCI 服务 -> 蓝牙), reboot: the adapter
  is off, `bluetoothctl show` says `Powered: no`; turning it on in 高级 -> 蓝牙
  works and a headset connects; on again, reboot: powered at boot as before.

## Next (后续要做)

- **Done 2026-09-30, to check on the device after a replug and with a SIM / online:**
  1. **USB replug** (`/usr/libexec/e5-usb-watch`, procd `e5-usb-watch`): with a
     cable in from a computer's port (SDP/CDP) and the UDC `not attached` for 4 s, the
     gadget is connected again (`soft_connect`).  Tested by disconnecting it by hand:
     connected again after 2 s, enumerated a second later.  Not yet with a real replug.
     The info screen's 设备 page shows the link as it is (`/api/status` `.usb.link`:
     none, charger, host, enumerated, lease, online).
  2. **The app store**: `Enceka/infoscreen-plugins` (local in `../infoscreen-plugins`,
     **to create on GitHub and push, with Pages from Actions**): `tools/check.py`,
     `tools/build.py`, CI, `bigclock`; on the screen 高级 -> 应用管理 -> 应用商店.
     Tested against a local copy of the store: install, SHA-256 mismatch refused.
  3. **The screen's online update** (e5-infoscreen `3df5807`, VERSION 1.1.0):
     `update fetch | apply | rollback`, 高级 -> 系统; tested against a local release.
     The first real release (v1.1.0 on `Enceka/e5-infoscreen`) is to be uploaded.
  4. **Bluetooth "no adapter"** (`/usr/libexec/e5-bt-check`, from `e5-bt`): hci0 was
     there but DOWN and never reported to bluetoothd -- the attach's failed setup of
     the leftovers below; the check brings it up or attaches again.
- **Install on the SD card**, not in userdata (see Now): the root image and the
  device files on the card, userdata read-only or not mounted at all.
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
- This host has no docker and no arm64 binfmt: `openwrt/build-rootfs.sh` cannot
  run here, so a flash package reuses an image built before
  (`E5_IMAGE_FROM=`, root modules written in with debugfs).  Changes to the OpenWrt
  overlay or packages need a host that can build the image.

## Where things stand (短状态)

| | |
|---|---|
| board | Rongyue E5 (UMS9621/qogirn6lite, CPU T158), 4 GiB RAM, Android 13 on slot a |
| mainline | 6.18.54 in `linux-lts-e5` (branch `e5-6.18`), the installed system under OpenWrt (`E5_MAINLINE=1 openwrt/make-flash-bundle.sh`, `flash.py`): display, touch, keys, USB gadget, Wi-Fi, BT, both SIM cards (FINDINGS 47), charging and fuel gauge, thermal as on 5.15, speaker and mic; the PMIC power off; filesystems read-only before a reset (FINDINGS 48.3); no eMMC reliable writes |
| power | `poweroff` is a real one without the cable; with a charger in, the PMIC powers the E5 up again and it boots (charger mode is logged, not a charging screen) |
| openwrt | OpenWrt 25.12.5 standalone as `/data/e5linux/openwrt.ext4` with its own firmware, vendor subset, modem modules and fonts (FINDINGS 39, 43); WAN by ModemManager, LAN `br-lan` = usb0 + AP, IPv6 /64 on the LAN; the info screen (e5-infoscreen) on the panel |
| kernel 5.15 | rebuilt `Image` (`kernel/patches/0001-0028`), the Debian root's; still the fallback flash package |
| rootfs (Debian) | Debian 13 (trixie) arm64 with Phosh 0.46, a loop file inside `/data/e5linux/` |
| baseband | ModemManager 1.24.0+e5 (`unisoc` plugin) on `wwan0at0` (`sipc_wwan`), data on `sipa_eth0`/`sipa_eth8` by card; CP booted by `modem_control` in the vendor chroot; every card needs its band lock (FINDINGS 47) |
| wifi | `sprd_wlan_combo` on the WCN chip: AP for the hotspot, station mode on Debian |
| bluetooth | configured by the kernel like the vendor HAL (factory address, pskey/RF); headphones play under OpenWrt (FINDINGS 45) |
| disk | the eMMC's userdata (F2FS) holds the images -- see Now |

## Open questions

- **`xdg-desktop-portal` has no backend in a fresh install** (Debian): decide which
  backend the phosh session wants: `xdg-desktop-portal-gtk` or
  `xdg-desktop-portal-wlr`.
