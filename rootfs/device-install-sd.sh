#!/bin/sh
# Run from the existing SD OpenWrt root. Adds Debian A/B (4 GiB each) and
# a 32 MiB e5boot registry in unallocated space, preserving every old partition.
# Dependencies e5-gpt, e5-os and e5-sd-registry are fetched from the same URL.
# The shared boot image is flashed separately, after the installed roots verify.
# Usage: device-install-sd.sh BASE_URL RAW_IMAGE_SHA256 KERNEL_RELEASE
set -eu
URL=${1:?base URL} EXPECT=${2:?raw ext4 SHA256} RELEASE=${3:?kernel release}
case "$EXPECT" in *[!a-f0-9]*|'') exit 2 ;; esac
[ "${#EXPECT}" = 64 ] || exit 2
[ "$(uname -r)" = "$RELEASE" ] || { echo "shared kernel version mismatch" >&2; exit 1; }
[ -f /etc/openwrt_release ] && [ -f /etc/e5/sd-root ] || { echo "run from the SD OpenWrt system" >&2; exit 1; }
ROOTDEV=$(awk '$2 == "/" {print $1}' /proc/mounts)
case "$ROOTDEV" in /dev/mmcblk*p*) ;; *) exit 1 ;; esac
DISK=${ROOTDEV%p*} CURN=${ROOTDEV##*p}
[ ! -e /mnt/e5-boot/format ] || { echo "card already registered" >&2; exit 1; }
T=/tmp/e5-sd-install
mkdir -p "$T"
for f in e5-gpt e5-os e5-sd-registry; do
    wget -q -O "$T/$f" "$URL/$f"
done
. "$T/e5-sd-registry"
GPT=$T/e5-gpt
ucode "$GPT" list "$DISK" > "$T/table-before"
for name in e5boot debian-a debian-b; do
    ! grep -q " $name\$" "$T/table-before" || { echo "$name already exists" >&2; exit 1; }
done
# Preflight before the first write, not after partially adding a layout.
awk -v last="$(cat /sys/class/block/${DISK##*/}/size)" '
    BEGIN { at=2048; best=0 }
    { if ($2-at > best) best=$2-at; at=$3+1 }
    END { if (last-33-at > best) best=last-33-at; exit !(best >= 16846848) }
' "$T/table-before" || { echo "no contiguous space for 32 MiB + 2 x 4 GiB" >&2; exit 1; }
LO=$(losetup -f)
M=$T/root
mkdir -p "$M"
trap 'umount "$M" 2>/dev/null || :; losetup -d "$LO" 2>/dev/null || :' EXIT
boot=$(ucode "$GPT" add "$DISK" e5boot 65536)
set -- $boot; BOOTN=$1 BOOTSTART=$2
losetup -o $((BOOTSTART * 512)) "$LO" "$DISK"
mkfs.ext4 -F -q -b 1024 -L e5boot "$LO" 32768
mkdir -p /mnt/e5-boot
mount -t ext4 -o noatime "$LO" /mnt/e5-boot
BOOTLO=$LO
LO=$(losetup -f)
mkdir -p /mnt/e5-boot/systems/openwrt /mnt/e5-boot/systems/debian
printf '%s\n' "$RELEASE" > /mnt/e5-boot/kernel-release
echo openwrt > /mnt/e5-boot/default
ucode "$GPT" uuid "$DISK" "$CURN" > /mnt/e5-boot/systems/openwrt/a
# format is committed after both Debian roots verify, so an interrupted install
# cannot select a partially written root.
for slot in a b; do
    p=$(ucode "$GPT" add "$DISK" "debian-$slot" 8388608)
    set -- $p; n=$1 start=$2 end=$3
    [ $((end-start+1)) = 8388608 ] && [ $((start%2048)) = 0 ] || exit 1
    echo "== Debian $slot: partition $n, 4096 MiB, sector $start"
    # Only the new partition's sectors are written. Full raw-image verification
    # catches download/decompression/short-write failures before registration.
    wget -q -O - "$URL/rootfs.ext4.gz" | gzip -dc |
        dd of="$DISK" bs=1048576 seek=$((start/2048)) conv=fsync
    got=$(dd if="$DISK" bs=1048576 skip=$((start/2048)) count=4096 2>/dev/null | sha256sum | cut -d' ' -f1)
    [ "$got" = "$EXPECT" ] || { echo "image checksum mismatch for Debian $slot" >&2; exit 1; }
    losetup -o $((start*512)) "$LO" "$DISK"
    mount -t ext4 "$LO" "$M"
    [ -f "$M/etc/debian_version" ] && [ -x "$M/sbin/init" ] || exit 1
    [ -d "$M/usr/lib/modules/$RELEASE/audio" ] || exit 1
    [ -x "$M/opt/e5/android/vendor/bin/modem_control" ] || exit 1
    mkdir -p "$M/etc/e5" "$M/etc/e5linux"
    printf 'debian-sd %s\n' "$slot" > "$M/etc/e5/sd-root"
    echo debian > "$M/etc/e5/sd-system"
    echo 0 > "$M/etc/e5/sd-gen"
    echo linux > "$M/etc/e5linux/default-boot"
    cp /run/e5linux/misc-bc-*.bin "$M/etc/e5linux/"
    cp /usr/local/bin/busybox "$M/usr/local/bin/"
    cp "$T/e5-os" "$T/e5-sd-registry" "$M/opt/e5/"
    chmod 0755 "$M/opt/e5/e5-os" "$M/opt/e5/e5-sd-registry"
    sync
    umount "$M"
    losetup -d "$LO"
    ucode "$GPT" uuid "$DISK" "$n" > "/mnt/e5-boot/systems/debian/$slot"
    echo "== Debian $slot: verified and registered"
done
cp "$T/e5-os" "$T/e5-sd-registry" /opt/e5/
chmod 0755 /opt/e5/e5-os /opt/e5/e5-sd-registry
cp "$GPT" /usr/libexec/e5-gpt
echo openwrt > /etc/e5/sd-system
sync
echo 1 > /mnt/e5-boot/format
sync
ucode "$GPT" list "$DISK"
echo "SD-INSTALL-DONE (default OpenWrt; flash the shared boot image next)"
