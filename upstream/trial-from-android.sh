#!/bin/sh
# The next mainline trial, from Android: the kernel's sipc_wwan.ko into the trial root's
# /lib/modules/<release>/modem (OpenWrt's e5-sipc-wwan loads it from there), then boot/flash-trial.sh.
#
#   upstream/trial-from-android.sh [work/boot-mainline-openwrt.img]
#
# The trial root is the copy /data/e5linux/openwrt-mainline.ext4, never the image in use.  Loop-mounting a
# file on userdata needs SELinux permissive for the moment of the mount; the previous mode is restored.
set -eu
TOP=$(cd "$(dirname "$0")/.." && pwd)
IMG=${1:-$TOP/work/boot-mainline-openwrt.img}
R=$(cat "$TOP/upstream/out/kernel.release")
COPY=/data/e5linux/openwrt-mainline.ext4
MNT=/data/local/tmp/e5mnt
su_do() { adb shell "su -c '$1'" | tr -d '\r'; }

[ "$(adb shell getprop ro.boot.slot_suffix | tr -d '\r')" = _a ] || { echo "device is not running Android (slot a)" >&2; exit 1; }
adb push "$TOP/upstream/out/modules/sipc_wwan.ko" /data/local/tmp/sipc_wwan.ko >/dev/null
out=$(su_do "e=\$(getenforce); setenforce 0; mkdir -p $MNT; mount -t ext4 -o loop $COPY $MNT && \
    mkdir -p $MNT/lib/modules/$R/modem && cp /data/local/tmp/sipc_wwan.ko $MNT/lib/modules/$R/modem/ && \
    ls $MNT/lib/modules/$R/modem/sipc_wwan.ko; umount $MNT; [ \$e = Enforcing ] && setenforce 1; \
    rmdir $MNT; rm /data/local/tmp/sipc_wwan.ko; echo selinux=\$(getenforce)")
echo "$out"
echo "$out" | grep -q "modem/sipc_wwan.ko" || { echo "could not put sipc_wwan.ko into the trial root" >&2; exit 1; }
exec sh "$TOP/boot/flash-trial.sh" "$IMG"
