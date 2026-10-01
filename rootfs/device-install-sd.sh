#!/bin/sh
# Run from the existing SD OpenWrt root. Adds Debian A/B (4 GiB each) and
# a 32 MiB e5boot registry in unallocated space, preserving every old partition.
# Dependencies e5-gpt, e5-os and e5-sd-registry are fetched from the same URL.
# The shared boot image is flashed separately, after the installed roots verify.
# Usage: device-install-sd.sh BASE_URL RAW_IMAGE_SHA256 KERNEL_RELEASE [--check]
set -eu
URL=${1:?base URL} EXPECT=${2:?raw ext4 SHA256} RELEASE=${3:?kernel release}
MODE=${4:-}
case "$MODE" in ''|--check) ;; *) echo "unknown option $MODE" >&2; exit 2 ;; esac
case "$EXPECT" in *[!a-f0-9]*|'') exit 2 ;; esac
[ "${#EXPECT}" = 64 ] || exit 2

# One bounded write, with separate download/decompression/write errors.
write_slot_image() {
    local disk=$1 start=$2 blocks=$3 source=$4 rc=0
    local fifo=$T/download
    rm -f "$fifo" "$T/download.rc" "$T/gzip.rc" "$T/excess"
    mkfifo "$fifo"
    # The shell opens the FIFO before wget, including DNS/HTTP failures. This
    # ensures gzip sees EOF rather than waiting forever for a writer to open it.
    ( status=0; wget -O - "$source" >"$fifo" 2>"$T/download.err" || status=$?; echo "$status" > "$T/download.rc" ) &
    fetch_pid=$!
    ( status=0; gzip -dc "$fifo" 2>"$T/gzip.err" || status=$?; echo "$status" > "$T/gzip.rc" ) |
        ( dd of="$disk" bs=1048576 seek=$((start/2048)) count="$blocks" iflag=fullblock conv=fsync,notrunc 2>"$T/write.err" || exit "$?"
          # Consume one extra byte to detect even a small oversized image, and
          # wait for gzip to finish checking the CRC of an exactly sized one.
          dd bs=1 count=1 of="$T/excess" 2>/dev/null || exit "$?"
          [ ! -s "$T/excess" ] || { echo "image exceeds the $blocks MiB slot" >"$T/write.err"; exit 1; }
        ) || rc=$?
    wait "$fetch_pid"
    fetch_pid=
    rm -f "$fifo"
    if [ "$rc" != 0 ]; then cat "$T/write.err" >&2; echo "card write rejected (status $rc)" >&2; return 1; fi
    if [ "$(cat "$T/download.rc")" != 0 ]; then cat "$T/download.err" >&2; echo "image download failed" >&2; return 1; fi
    if [ "$(cat "$T/gzip.rc")" != 0 ]; then cat "$T/gzip.err" >&2; echo "image decompression failed" >&2; return 1; fi
}

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
# Simulate the same aligned allocation used by add, including GPT entries and
# fragmented free regions, before formatting or writing a single card sector.
echo "== capacity check: $DISK; required e5boot 32 MiB + Debian 4096 MiB x 2"
if ! ucode "$GPT" plan "$DISK" e5boot:65536 debian-a:8388608 debian-b:8388608 > "$T/plan"; then
    echo "SD installation aborted before writing the card: allocation check failed (details above)" >&2
    exit 1
fi
cat "$T/plan"
[ "$MODE" != --check ] || { echo "SD-CHECK-DONE; nothing written to the card"; exit 0; }
LO=$(losetup -f)
M=$T/root
mkdir -p "$M"
fetch_pid=
trap '[ -z "$fetch_pid" ] || { kill "$fetch_pid" 2>/dev/null || :; wait "$fetch_pid" 2>/dev/null || :; }; rm -f "$T/download"; umount "$M" 2>/dev/null || :; losetup -d "$LO" 2>/dev/null || :' EXIT
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
    write_slot_image "$DISK" "$start" 4096 "$URL/rootfs.ext4.gz" || { echo "Debian $slot: installation stopped" >&2; exit 1; }
    got=$(dd if="$DISK" bs=1048576 skip=$((start/2048)) count=4096 2>/dev/null | sha256sum | cut -d' ' -f1)
    [ "$got" = "$EXPECT" ] || { echo "Debian $slot: image checksum mismatch (expected $EXPECT, read $got); incomplete/corrupt image or card I/O failure" >&2; exit 1; }
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
