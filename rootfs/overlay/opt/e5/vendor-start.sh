#!/bin/sh
# Boot the CP (baseband) by running Android's modem_control in a chroot.
#
# Every line here was found by failure, and the order matters:
#   * /dev/__properties__ must be owned by root:root -- bionic's
#     PropertyInfoAreaFile::LoadPath() rejects a property_info whose st_uid/st_gid
#     is not 0, and then the *whole* property system stays uninitialised, so
#     modem_control cannot read ro.vendor.radio.modemtype and never boots the CP.
#   * liblog wants a logd writer socket; without /dev/socket/logdw modem_control
#     spins on connect() forever.
#   * modem_control drops to uid system (1000), so the device nodes need the
#     ownership Android's ueventd.rc gives them, and /dev/block/by-name must exist
#     (Android's ueventd creates it; devtmpfs does not).
#   * sprd_modem_loader only accepts a task whose comm is exactly "modem_control",
#     so the binary is exec'd directly instead of through linker64.
set -u
A=/opt/e5/android
[ -x "$A/vendor/bin/modem_control" ] || { echo "no Android vendor subset in $A" >&2; exit 4; }

echo "stage=ownership"
chown -R root:root "$A/apex" "$A/system" "$A/vendor" 2>/dev/null || true
chown -R root:root "$A/dev/__properties__" 2>/dev/null || true
chmod 0444 "$A/dev/__properties__"/* 2>/dev/null || true

echo "stage=dev-nodes"
mkdir -p /dev/block/by-name /dev/socket
for u in /sys/class/block/mmcblk0p*/uevent; do
  d=$(basename "$(dirname "$u")"); n=$(sed -n 's/^PARTNAME=//p' "$u")
  ln -sfn "/dev/$d" "/dev/block/$d"
  [ -n "$n" ] && ln -sfn "/dev/$d" "/dev/block/by-name/$n"
done
/opt/e5/node-perms.sh 2>/dev/null || true
chmod 0666 /sys/power/wake_lock /sys/power/wake_unlock 2>/dev/null || true

echo "stage=logd"
mkdir -p /dev/__properties__
mountpoint -q /dev/__properties__ 2>/dev/null ||
    mount --bind "$A/dev/__properties__" /dev/__properties__ 2>/dev/null
if [ ! -S /dev/socket/logdw ]; then
  nohup python3 /opt/e5/logdw.py /dev/socket/logdw >> /var/log/e5-android-log.txt 2>&1 &
  sleep 1
fi

echo "stage=mounts"
for m in proc sys tmp data/vendor mnt system/bin linkerconfig; do mkdir -p "$A/$m"; done
ln -sfn /apex/com.android.runtime/bin/linker64 "$A/system/bin/linker64"
: > "$A/linkerconfig/ld.config.txt"
mountpoint -q "$A/proc" || mount -t proc proc "$A/proc"
mountpoint -q "$A/sys" || mount -t sysfs sysfs "$A/sys"
mountpoint -q "$A/dev" || mount --rbind /dev "$A/dev"

echo "stage=cmdline"
src=/proc/cmdline
grep -q androidboot.slot_suffix /proc/cmdline ||
    [ ! -r /proc/device-tree/chosen/bootargs ] || src=/proc/device-tree/chosen/bootargs
tr -d '\000' < "$src" | sed 's/androidboot.slot_suffix=_b/androidboot.slot_suffix=_a/' \
    > /run/e5-cmdline.android
mountpoint -q "$A/proc/cmdline" || mount --bind /run/e5-cmdline.android "$A/proc/cmdline"

echo "stage=exec"
unset LD_PRELOAD
export LD_LIBRARY_PATH=/apex/com.android.runtime/lib64/bionic:/system/lib64:/vendor/lib64
exec chroot "$A" /vendor/bin/modem_control
