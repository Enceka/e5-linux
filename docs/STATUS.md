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
  Next steps, in order:
  1. **A durability test that can see it** (`work/mmctest/tagwrite.c` could not: an
     older generation of the same block passed): on `blackbox` (backed up), write
     every block, flush, power off through the normal path (with the cable in, the
     PMIC powers the E5 up again by itself), then every block must hold the last
     generation.  Variants: a hard PMIC power off right after the flush, without
     the mmc shutdown; writes after the last flush (then: no block older than the
     flush).  About 10 cycles; boot/init must not mount userdata meanwhile.
  2. If flushed data is lost: compare the vendor's eMMC path (FINDINGS 48.4) -- the
     cache (turn it off as a test: `CACHE_CTRL` 0), the shutdown sequence (a delay
     or CMD5 sleep before the PMIC cuts power), HSQ vs the vendor's swcq, discard.
  3. If it is not lost there: the F2FS side -- mount options as Android's
     (`fsync_mode=nobarrier` is not safer; `discard` off to test), a loop image on
     top.
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

Written and committed, not yet run on the device.

## Next (后续要做)

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
