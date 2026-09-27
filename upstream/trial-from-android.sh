#!/bin/sh
# The next mainline trial, from Android: the modules OpenWrt loads from the root (upstream/root-modules.txt,
# upstream/root-modules.sh) into the trial root's /lib/modules/<release>, then boot/flash-trial.sh.
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
"$TOP/upstream/root-modules.sh" >/dev/null
adb push "$TOP/upstream/out/root-modules.tar" /data/local/tmp/e5-root-modules.tar >/dev/null
out=$(su_do "e=\$(getenforce); setenforce 0; mkdir -p $MNT; mount -t ext4 -o loop $COPY $MNT && \
    tar -xf /data/local/tmp/e5-root-modules.tar -C $MNT && ls $MNT/lib/modules/$R/modem/sipc_wwan.ko; \
    umount $MNT; [ \$e = Enforcing ] && setenforce 1; rmdir $MNT; rm /data/local/tmp/e5-root-modules.tar; \
    echo selinux=\$(getenforce)")
echo "$out"
echo "$out" | grep -q "modem/sipc_wwan.ko" || { echo "could not unpack the root modules into the trial root" >&2; exit 1; }
exec sh "$TOP/boot/flash-trial.sh" "$IMG"
