#!/bin/sh
# Re-arm slot b for another Linux trial from rooted Android, without reflashing
# boot_b (the image is already there).
#
# usage: boot/android-boot-linux.sh [boot-linux-slotb.img]
set -eu
BC_B=${1:-boot-linux-slotb.img}
BC_B=${BC_B%.img}.misc-slot-b-trial.bin
su_do() { adb shell "su -c '$1'" | tr -d '\r'; }

[ -f "$BC_B" ] || { echo "missing $BC_B" >&2; exit 1; }

adb push "$BC_B" /data/local/tmp/e5-bc-b.bin >/dev/null
su_do 'dd if=/data/local/tmp/e5-bc-b.bin of=/dev/block/by-name/misc bs=1 seek=2048 conv=notrunc && sync'
new=$(su_do 'dd if=/dev/block/by-name/misc bs=1 skip=2048 count=32 2>/dev/null | od -An -tx1 -v' | tr -d ' \n')
[ "$new" = "$(od -An -tx1 -v "$BC_B" | tr -d ' \n')" ] || { echo "misc verify failed: $new" >&2; exit 1; }
echo "slot b armed (one-shot). Rebooting into the Linux image already in boot_b."
adb reboot
