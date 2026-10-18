#!/bin/sh
# Install OpenWrt on a real ext4 partition of the internal eMMC, in space taken
# from userdata.  userdata is only ever handled by raw tools here (fsck.f2fs,
# resize.f2fs, e5-gpt): a system on its own partition keeps userdata unmounted
# at boot, so mainline never writes that F2FS (docs/FINDINGS.md 48) -- the
# reason the card system leaves it read-only.  Runs as root inside a running
# OpenWrt of this device (a card system typically).
#
#   device-install-part.sh IMAGE.ext4.gz|URL [--size MiB] [--commit]
#
# Without --commit nothing is written: the sizes, the exact commands and the
# e5-gpt plan simulation are printed and it exits.  With --commit: fsck.f2fs
# the unmounted userdata, resize.f2fs -s it to the target, e5-gpt resize the
# userdata partition and add e5root after it, write the image into that
# partition at its offset (the kernel's table for the disk is not re-read),
# mount it there, keep the running configuration and the device's files, mark
# /etc/e5/part-root with part-trial (the first boot is a trial: boot/init falls
# back to the card or image when it never comes up), and record boot-os=part on
# userdata -- a brief read-write mount, as boot/init itself takes for one-boot
# choices.  Reboot to enter it.
#
# --size is the new partition's MiB (default: the unpacked image + 1 GiB); the
# leftover userdata must keep at least 1 GiB free.  E5_IMAGE_SIZE (bytes,
# unpacked) is needed with a URL.
set -eu
SRC=${1:?image (.ext4.gz or URL)}
[ "$SRC" != "" ] || { echo "usage: device-install-part.sh IMAGE.ext4.gz|URL [--size MiB] [--commit]" >&2; exit 2; }
shift
SIZE=
COMMIT=
while [ $# -gt 0 ]; do
    case "$1" in
        --size) shift; SIZE=${1:?--size needs MiB} ;;
        --size=*) SIZE=${1#--size=} ;;
        --commit) COMMIT=1 ;;
        *) echo "unknown option $1" >&2; exit 2 ;;
    esac
    shift
done
[ -z "$SIZE" ] || case "$SIZE" in ''|*[!0-9]*) echo "--size must be whole MiB" >&2; exit 2 ;; esac

[ "$(id -u)" = 0 ] || { echo 'installation requires root' >&2; exit 1; }
# The boot image in use must know the partition system: without the token the
# initramfs would boot the card or image straight past it.
grep -qs part-root /run/e5linux/init-features 2>/dev/null || {
    echo 'the boot image in use does not know internal partition systems;' >&2
    echo "flash this package's boot image first (device-flash-boot.sh)" >&2
    exit 1
}
GPT=$(dirname "$0")/e5-gpt
[ -f "$GPT" ] || GPT=/usr/libexec/e5-gpt
[ -f "$GPT" ] || { echo 'no e5-gpt (the partition table tool)' >&2; exit 1; }
for c in ucode losetup gunzip dd df od awk wget mount umount; do
    command -v "$c" >/dev/null 2>&1 || { echo "$c is required" >&2; exit 1; }
done
for c in fsck.f2fs resize.f2fs; do
    command -v "$c" >/dev/null 2>&1 || { echo "$c is required: apk add f2fs-tools" >&2; exit 1; }
done

DATA=
for u in /sys/class/block/mmcblk*p*/uevent; do
    grep -qx PARTNAME=userdata "$u" 2>/dev/null && DATA=/dev/$(basename "$(dirname "$u")")
done
[ -n "$DATA" ] && [ -b "$DATA" ] || { echo 'no userdata partition' >&2; exit 1; }
DISK=${DATA%p*}
[ -b "$DISK" ] || { echo "$DISK is not a block device" >&2; exit 1; }

if [ -z "$SIZE" ]; then
    case "$SRC" in
        http://*|https://*)
            [ -n "${E5_IMAGE_SIZE:-}" ] || { echo "E5_IMAGE_SIZE (the unpacked size) is needed with a URL" >&2; exit 2; }
            imgsz=$E5_IMAGE_SIZE ;;
        *) imgsz=$(tail -c 4 "$SRC" | od -A n -t u4 | tr -d ' ') ;;
    esac
    SIZE=$(( (imgsz + 1048575) / 1048576 + 1024 ))
fi
need=$((SIZE * 2048))

set -- $(ucode "$GPT" list "$DISK" | awk '$4 == "userdata" { print $1, $2, $3 }')
[ $# = 3 ] || { echo 'userdata is not in the partition table' >&2; exit 1; }
un=$1 ustart=$2 uend=$3
ulen=$((uend - ustart + 1))
# Keep 2 MiB of alignment slack past the new partition; the shrink target must
# be 1 MiB aligned and keep the filesystem's own margin (checked below).
utarget=$(( (ulen - need - 4096) / 2048 * 2048 ))
[ "$utarget" -ge 2048 ] || { echo "no room: userdata is $((ulen >> 11)) MiB, the image partition wants $SIZE MiB" >&2; exit 1; }

# The free-space guard needs userdata readable: a card system has it mounted
# read-only; the plan below is checked against it before anything is written.
used_kib=
for m in /data /mnt/e5-data; do
    grep -q " $DATA $m " /proc/mounts 2>/dev/null && used_kib=$(df -k "$m" | awk 'NR == 2 { print $3 }')
done
[ -z "$COMMIT" ] || [ -n "$used_kib" ] || {
    echo 'userdata is not mounted; mount it read-only so the free space can be checked' >&2; exit 1
}
if [ -n "$used_kib" ] && [ "$((utarget / 2 - used_kib))" -lt 1048576 ]; then
    echo "the shrink would leave userdata under 1 GiB free (used ${used_kib} KiB, target $((utarget / 2)) KiB); use a smaller --size" >&2
    exit 1
fi

plan=$(ucode "$GPT" plan "$DISK" "resize:userdata:$utarget" "e5root:$need") || exit 1
set -- $(echo "$plan" | awk '$1 == "e5root" { print $2, $3, $4 }')
[ $# = 3 ] || { echo 'the plan has no e5root partition' >&2; exit 1; }
pn=$1 pstart=$2 pend=$3
[ $((pstart % 2048)) = 0 ] || { echo "the new partition would not start on a MiB" >&2; exit 1; }

echo "== the disk: $DISK, userdata $un ($((ulen >> 11)) MiB) -> $((utarget >> 11)) MiB, new e5root $pn ($SIZE MiB) at $pstart"
echo "$plan" | awk '{ printf "   partition %s: sectors %s-%s (%s MiB)\n", $2, $3, $4, ($4 - $3 + 1) / 2048 }'
if [ -z "$COMMIT" ]; then
    cat <<EOF
== this is a dry run; with --commit it would, in order:
   1. umount userdata (must not be mounted)
   2. fsck.f2fs -f $DATA
   3. resize.f2fs -s -t $utarget $DATA   (then verify the raw superblock's block count)
   4. ucode $GPT resize $DISK userdata $utarget   (then verify both GPT copies agree)
   5. ucode $GPT add $DISK e5root $need
   6. write the image into sectors $pstart-$pend of $DISK (through the whole disk:
      the kernel's table for it is not re-read), unmounting is not needed
   7. mount it (losetup -o $((pstart * 512))), keep this system's configuration
      and the device's files, mark /etc/e5/part-root with part-trial
   8. mount userdata read-write once to record boot-os=part, then umount
   The first boot is a trial: one that never comes up falls back to the card or
   image on the next boot.  Android's userdata keeps its files, $((utarget >> 11)) MiB big.
EOF
    exit 0
fi

# ------------------------------------------------------------ commit
[ -n "$used_kib" ] || { echo 'userdata is not mounted; mount it read-only first' >&2; exit 1; }
echo "== unmounting userdata"
for m in /data /mnt/e5-data; do
    grep -q " $m " /proc/mounts 2>/dev/null && umount "$m"
done
grep -q "$DATA" /proc/mounts && { echo 'userdata is still mounted' >&2; exit 1; }

echo "== fsck.f2fs -f $DATA"
fsck.f2fs -f "$DATA" || { echo 'fsck.f2fs failed; nothing else was changed' >&2; exit 1; }

echo "== resize.f2fs -s -t $utarget $DATA"
resize.f2fs -s -t "$utarget" "$DATA" || { echo 'resize.f2fs failed; the partition table is untouched' >&2; exit 1; }
# The raw superblock is the check: magic at 1024, the 4 KiB block count at
# 1060 (low) and 1064 (high) -- exactly what boot/init reads from it.
[ "$(od -A n -t u4 -j 1024 -N 4 "$DATA" | tr -d ' ')" = 4076150800 ] ||
    { echo 'the superblock magic moved; stopping' >&2; exit 1; }
[ "$(od -A n -t u4 -j 1060 -N 4 "$DATA" | tr -d ' ')" = "$((utarget / 8))" ] &&
    [ "$(od -A n -t u4 -j 1064 -N 4 "$DATA" | tr -d ' ')" = 0 ] ||
    { echo "the shrink did not land (expected $((utarget / 8)) 4 KiB blocks)" >&2; exit 1; }
sync

echo "== e5-gpt resize + add"
ucode "$GPT" resize "$DISK" userdata "$utarget" || exit 1
# (both GPT copies were rewritten; re-reading them is what the next command does)
set -- $(ucode "$GPT" add "$DISK" e5root "$need") || exit 1
pn=$1 pstart=$2 pend=$3
[ $((pstart % 2048)) = 0 ] || { echo 'the new partition does not start on a MiB' >&2; exit 1; }

echo "== writing the image into sectors $pstart-$pend"
dd if=/dev/zero of="$DISK" bs=1048576 seek=$((pstart / 2048)) count=4 conv=fsync 2>/dev/null
rm -f /tmp/e5-part.fail
case "$SRC" in
    http://*|https://*) { wget -q -O - "$SRC" || touch /tmp/e5-part.fail; } | gunzip -c ;;
    *) gunzip -c "$SRC" ;;
esac | dd of="$DISK" bs=1048576 seek=$((pstart / 2048)) conv=fsync 2>/tmp/e5-part.dd ||
    { cat /tmp/e5-part.dd >&2; echo "writing the partition failed" >&2; exit 1; }
[ ! -e /tmp/e5-part.fail ] || { rm -f /tmp/e5-part.fail; echo "download failed" >&2; exit 1; }

lo=$(losetup -f)
losetup -o $((pstart * 512)) "$lo" "$DISK"
N=/tmp/e5-part.new
rm -rf "$N" && mkdir -p "$N"
mount -t ext4 "$lo" "$N" ||
    { losetup -d "$lo"; echo "the written partition does not mount" >&2; exit 1; }
trap 'umount "$N" 2>/dev/null; losetup -d "$lo" 2>/dev/null' EXIT
[ -x "$N/sbin/init" ] && [ -f "$N/etc/openwrt_release" ] || { echo 'not an OpenWrt image' >&2; exit 1; }

# BEGIN keep-config (device-install-image.sh)
keep_config() {
    local from=$1 O=$2 f p phone
    echo "== keeping the configuration of $from"
    phone=$(mktemp -d /tmp/e5-part.phone.XXXXXX)
    if [ -f "$O/etc/e5-infoscreen/plugins/phone/manifest.json" ]; then
        cp -a "$O/etc/e5-infoscreen/plugins/phone/." "$phone/"
    fi
    for f in image-version image-form build-time; do
        cp "$O/etc/e5/$f" "/tmp/e5-part.$f" 2>/dev/null || rm -f "/tmp/e5-part.$f"
    done
    for p in etc/config etc/shadow etc/passwd etc/group etc/dropbear etc/e5 etc/e5linux \
             etc/uhttpd.crt etc/uhttpd.key etc/vnstat etc/e5-infoscreen etc/e5-sms; do
        [ -e "$from/$p" ] || continue
        if [ -d "$from/$p" ] && [ -d "$O/$p" ]; then
            cp -a "$from/$p/." "$O/$p/"
        else
            rm -rf "$O/$p"
            cp -a "$from/$p" "$O/$p"
        fi
    done
    for f in image-version image-form build-time; do
        rm -f "$O/etc/e5/$f"
        [ -f "/tmp/e5-part.$f" ] && mv "/tmp/e5-part.$f" "$O/etc/e5/$f"
    done
    if [ -f "$phone/manifest.json" ]; then
        mkdir -p "$O/etc/e5-infoscreen/plugins/phone"
        cp -a "$phone/." "$O/etc/e5-infoscreen/plugins/phone/"
    fi
    rm -rf "$phone"
}
# END keep-config

# BEGIN device-files-tar (device-install-image.sh)
VIEW=/tmp/e5-part.view
device_files_tar() {
    local src=/ list rc=1
    [ -f /mnt/e5-disk/usr/lib/firmware/wcnmodem.bin ] && src=/mnt/e5-disk
    mkdir -p "$VIEW" && mount --bind "$src" "$VIEW"
    if [ -f "$VIEW/lib/firmware/wcnmodem.bin" ] && [ -x "$VIEW/opt/e5/android/vendor/bin/modem_control" ]; then
        list=$(cd "$VIEW" && for f in lib/firmware/wcnmodem.bin lib/firmware/gnssmodem.bin \
                   lib/firmware/wifi_board_config*.ini lib/firmware/tsx_data lib/firmware/l_agdsp_a.img \
                   lib/firmware/audio_structure lib/firmware/dsp_vbc lib/firmware/cvs \
                   lib/firmware/aw87xxx_acf.bin lib/firmware/sprd opt/e5/android; do
                   [ -e "$f" ] && echo "$f"; done)
        (cd "$VIEW" && tar -cf - $list) && rc=0
    fi
    umount "$VIEW"
    return $rc
}
# END device-files-tar

keep_config / "$N"
if [ ! -f "$N/lib/firmware/wcnmodem.bin" ]; then
    if device_files_tar > /tmp/e5-part.dft; then
        tar -xf /tmp/e5-part.dft -C "$N"
        sha256sum /tmp/e5-part.dft | cut -d' ' -f1 > "$N/etc/e5/device-files.stamp"
        echo "== the device's files copied in"
    else
        rm -f /tmp/e5-part.dft
        echo 'the image has no firmware, and this system has none to give' >&2
        exit 1
    fi
    rm -f /tmp/e5-part.dft
fi
mkdir -p "$N/etc/e5linux"
cp /run/e5linux/misc-bc-slot-a.bin /run/e5linux/misc-bc-slot-b-trial.bin "$N/etc/e5linux/" 2>/dev/null || true
# (only one root marker: this system lives on its own partition, not on the card)
rm -f "$N/etc/e5/sd-root" "$N/etc/e5/sd-trial"
printf 'e5root %s\n' "$DISK" > "$N/etc/e5/part-root"
echo 1 > "$N/etc/e5/part-trial"
ver=$(cat "$N/etc/e5/image-version" 2>/dev/null || echo "?")
sync
umount "$N" && losetup -d "$lo"
trap - EXIT

echo "== recording boot-os=part on userdata"
mp=/tmp/e5-part.data
rm -rf "$mp" && mkdir -p "$mp"
mount -t f2fs -o noatime,nodiratime "$DATA" "$mp"
mkdir -p "$mp/e5linux"
echo part > "$mp/e5linux/boot-os"
sync
umount "$mp"

sync
echo "installed: internal partition $pn (sectors $pstart-$pend, $ver)"
echo "   boot-os=part recorded; the first boot is a trial: one that never comes"
echo "   up leaves the next boot to the card or the image on userdata."
echo "   back to the previous system: rm /data/e5linux/boot-os there, or re-install."
