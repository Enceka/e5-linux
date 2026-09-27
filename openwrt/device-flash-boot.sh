#!/bin/sh
# Write an e5-linux boot image into boot_b from the running Linux (Debian or
# OpenWrt, either form) and arm slot b for the next boot -- what
# boot/flash-from-linux.sh does over telnet, as one script the flash package
# (openwrt/make-flash-bundle.sh) runs on the device.
#
#   device-flash-boot.sh URL SHA256_OF_THE_HEAD HEAD_MB
#
# Only the first HEAD_MB MiB are written (boot/build-boot-image.py keeps the
# image inside them; the rest of the partition is boot/init's persistent log).
# A write that does not verify arms nothing: LK keeps booting what it booted,
# and a half-written boot_b only costs its two tries before Android.
set -eu
URL=${1:?url} WANT=${2:?sha256} MB=${3:?MiB}

part() {
    for u in /sys/class/block/mmcblk*p*/uevent; do
        grep -qx "PARTNAME=$1" "$u" 2>/dev/null && { echo "/dev/$(basename "$(dirname "$u")")"; return; }
    done
}
BOOTB=$(part boot_b)
MISC=$(cat /run/e5linux/misc-dev 2>/dev/null || part misc)
BC_B=/run/e5linux/misc-bc-slot-b-trial.bin
[ -b "$BOOTB" ] && [ -b "$MISC" ] || { echo "boot_b or misc not found" >&2; exit 1; }

echo "== writing boot_b ($BOOTB)"
T=/tmp/e5-boot-head.img
wget -q -O "$T" "$URL"
[ "$(sha256sum "$T" | cut -d' ' -f1)" = "$WANT" ] || { rm -f "$T"; echo "download hash mismatch" >&2; exit 1; }
dd if="$T" of="$BOOTB" bs=1M conv=fsync 2>/dev/null
rm -f "$T"
sync
got=$(dd if="$BOOTB" bs=1M count="$MB" 2>/dev/null | sha256sum | cut -d' ' -f1)
[ "$got" = "$WANT" ] || { echo "boot_b verify failed; slot b not armed" >&2; exit 1; }
echo "   verified"

# the block the running initramfs recorded: the new image's is the same, for
# the same stock header (boot/build-boot-image.py)
[ -f "$BC_B" ] || { echo "no $BC_B" >&2; exit 1; }
dd if="$BC_B" of="$MISC" bs=1 seek=2048 conv=notrunc 2>/dev/null
sync
echo "== slot b armed"
