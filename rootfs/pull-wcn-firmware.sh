#!/bin/bash
# Pull the WCN (Wi-Fi/BT combo) firmware and factory data off Android into the
# rootfs overlay, so the next image carries what wcn_bsp.ko needs to boot the chip.
#
# Why a pull script and not a mount: the blobs live on /odm and /vendor, which are
# erofs logical partitions inside `super` (/dev/block/dm-*), and a Linux boot cannot
# mount those the way it mounts userdata.  They have to be copied across once, from
# Android with adb, and then travel inside rootfs.ext4 -- the same reasoning as
# docs/FINDINGS.md section 2, just for firmware instead of the root filesystem.
#
# /mnt/vendor is the exception: that is plain /dev/block/mmcblk0p1 (ext4), so a Linux
# boot *can* mount it.  Its wifimac.txt is still copied here so the rootfs is
# self-contained, and device-finalize.sh puts it in /mnt/vendor.
#
# The pulled files are vendor blobs: .gitignore keeps them out of the repository.
#
# usage: rootfs/pull-wcn-firmware.sh   (device in Android, adb + su working)
set -e
HERE="$(cd "$(dirname "$0")" && pwd)"
OVL="$HERE/overlay"
STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT

pull() {  # pull SRC_IN_ANDROID  NAME
    # Not every path exists on every unit: /vendor/firmware/tsx_data is a symlink
    # into the factory-data partition, and on this device that target is a dangling
    # link (Android's own Wi-Fi works anyway, so it is not fatal).  Skip, do not die.
    if ! adb shell "su -c 'cp -f $1 /data/local/tmp/$2'" >/dev/null 2>&1; then
        echo "  skip $1: not a copyable file on this unit"
        return 0
    fi
    adb pull "/data/local/tmp/$2" "$STAGE/$2" >/dev/null
    adb shell "su -c 'rm -f /data/local/tmp/$2'" >/dev/null
    echo "  $1 -> $STAGE/$2 ($(wc -c < "$STAGE/$2") bytes)"
}

echo "== WCN firmware and board configs (/odm/firmware) =="
pull /odm/firmware/wcnmodem.bin wcnmodem.bin
pull /odm/firmware/gnssmodem.bin gnssmodem.bin
for f in $(adb shell "su -c 'ls /odm/firmware/'" | tr -d '\r' | grep '^wifi_board_config.*\.ini$'); do
    pull "/odm/firmware/$f" "$f"
done

echo "== tsx_data (/vendor/firmware) =="
pull /vendor/firmware/tsx_data tsx_data

echo "== factory data (/mnt/vendor, mmcblk0p1) =="
pull /mnt/vendor/wifimac.txt wifimac.txt
pull /mnt/vendor/btmac.txt btmac.txt

echo "== install into the rootfs overlay =="
mkdir -p "$OVL/lib/firmware" "$OVL/mnt/vendor/wcn"
cp "$STAGE"/*.bin "$STAGE"/wifi_board_config*.ini "$OVL/lib/firmware/"
[ -f "$STAGE/tsx_data" ] && cp "$STAGE/tsx_data" "$OVL/lib/firmware/tsx_data"
cp "$STAGE"/wifimac.txt "$OVL/mnt/vendor/wifimac.txt"
[ -f "$STAGE/btmac.txt" ] && cp "$STAGE/btmac.txt" "$OVL/mnt/vendor/btmac.txt"
# The driver dumps its calibration backup here, so the directory has to exist.
touch "$OVL/mnt/vendor/wcn/.keep"
ls -la "$OVL/lib/firmware" "$OVL/mnt/vendor"
echo "PULL-WCN-DONE"
