#!/bin/bash
# Copy the root filesystem image onto the device and arm slot b.
#
# The image goes to /data/e5linux/rootfs.ext4 inside Android's userdata, because
# the E5 has no unallocated eMMC space (see docs/FINDINGS.md section 2).  boot/init
# mounts userdata, loops the file and switch_roots into it.
#
# Run from the host, with the device in Android and adb working.
set -e
HERE="$(cd "$(dirname "$0")" && pwd)"
TOP="$(cd "$HERE/.." && pwd)"
IMG="${1:-$TOP/out/rootfs.ext4}"
[ -f "$IMG" ] || { echo "no image at $IMG -- run rootfs/build-rootfs.sh pack" >&2; exit 1; }

echo "== image: $(du -h "$IMG" | cut -f1)  sha256 $(sha256sum "$IMG" | cut -c1-16)..."
echo "== free space on /data"
adb shell "su -c 'df -h /data'" | tail -2

echo "== pushing (this is several GB over USB, it takes a while)"
adb push "$IMG" /data/local/tmp/rootfs.ext4

echo "== installing into /data/e5linux"
adb shell "su -c 'mkdir -p /data/e5linux && mv /data/local/tmp/rootfs.ext4 /data/e5linux/rootfs.ext4 && chmod 0644 /data/e5linux/rootfs.ext4 && ls -la /data/e5linux/ && df -h /data'"

echo "== arming slot b and rebooting"
adb shell "su -c 'dd if=/data/local/tmp/misc-bc-slot-b-trial.bin of=/dev/block/by-name/misc bs=1 seek=2048 conv=notrunc'" 2>/dev/null || {
    echo "   (pushing the misc block first)"
    adb push "$TOP/out/misc-bc-slot-b-trial.bin" /data/local/tmp/misc-bc-slot-b-trial.bin
    adb shell "su -c 'dd if=/data/local/tmp/misc-bc-slot-b-trial.bin of=/dev/block/by-name/misc bs=1 seek=2048 conv=notrunc'"
}
adb shell "su -c 'sync; reboot'"
echo "== rebooting; Linux should come up with the root filesystem in place"
