#!/bin/sh
# One-shot trial boot of an e5-linux image on slot b, from rooted Android (adb + su).
#
# Writes ONLY boot_b and the 32-byte bootloader_control inside misc. boot_a,
# init_boot_*, vendor_boot_*, the GPT and userdata are never touched.
#
# usage: boot/flash-trial.sh boot-linux-slotb.img
#        (expects .json and .misc-slot-b-trial.bin next to the image)
set -eu
IMG=$1
BASE=${IMG%.img}
EXP=$(python3 -c "import json,sys;print(json.load(open(sys.argv[1]))['sha256'])" "$BASE.json")
BC_B=$BASE.misc-slot-b-trial.bin
A_HEX=$(python3 -c "import json,sys;print(json.load(open(sys.argv[1]))['misc_slot_a_hex'])" "$BASE.json")
su_do() { adb shell "su -c '$1'" | tr -d '\r'; }

sha() { sha256sum "$1" | cut -d' ' -f1; }

[ "$(sha "$IMG")" = "$EXP" ] || { echo "local image hash mismatch" >&2; exit 1; }
[ "$(adb shell getprop ro.boot.slot_suffix | tr -d '\r')" = "_a" ] || { echo "device is not running slot a" >&2; exit 1; }
[ "$(adb shell getprop ro.boot.verifiedbootstate | tr -d '\r')" = "orange" ] || echo "warning: verifiedbootstate is not orange; AVB may be enforced" >&2

live=$(su_do 'dd if=/dev/block/by-name/misc bs=1 skip=2048 count=32 2>/dev/null | od -An -tx1 -v' | tr -d ' \n')
[ "$live" = "$A_HEX" ] || { echo "misc bootloader_control is not the expected slot-a state: $live" >&2; exit 1; }

adb push "$IMG" /data/local/tmp/e5-boot.img
adb push "$BC_B" /data/local/tmp/e5-bc-b.bin
[ "$(su_do 'sha256sum /data/local/tmp/e5-boot.img' | cut -d' ' -f1)" = "$EXP" ] || { echo "pushed image hash mismatch" >&2; exit 1; }

echo "writing boot_b ($(wc -c < "$IMG") bytes)"
su_do 'dd if=/data/local/tmp/e5-boot.img of=/dev/block/by-name/boot_b bs=4M && sync'
got=$(su_do 'sha256sum /dev/block/by-name/boot_b' | cut -d' ' -f1)
[ "$got" = "$EXP" ] || { echo "boot_b verify failed ($got); slot a is still active" >&2; exit 1; }

su_do 'dd if=/data/local/tmp/e5-bc-b.bin of=/dev/block/by-name/misc bs=1 seek=2048 conv=notrunc && sync'
new=$(su_do 'dd if=/dev/block/by-name/misc bs=1 skip=2048 count=32 2>/dev/null | od -An -tx1 -v' | tr -d ' \n')
[ "$new" = "$(od -An -tx1 -v "$BC_B" | tr -d ' \n')" ] || { echo "misc verify failed: $new" >&2; exit 1; }

echo "slot b armed (one-shot, tries=2). Rebooting; a failed Linux boot falls back to Android."
adb reboot
