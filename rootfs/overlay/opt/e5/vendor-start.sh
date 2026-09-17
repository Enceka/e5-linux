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
# modem_control takes the slot from the *current* boot slot, so a slot-b trial loads
# slot b's modem firmware and NV (nr_phy_b, nr_fixnv1_b, nr_deltanv_b).  Android runs
# from slot a, and slot a is where its RIL configured the modem -- including whatever
# NR/5G settings exist.  Point the _b names at the _a devices unless
# /etc/e5/modem-slot says "current".
modem_slot=$(cat /etc/e5/modem-slot 2>/dev/null || echo a)
if [ "$modem_slot" = "a" ]; then
  for p in nr_modem nr_phy nr_deltanv nr_fixnv1 nr_fixnv2; do
    if [ -e "/dev/block/by-name/${p}_a" ] && [ -e "/dev/block/by-name/${p}_b" ]; then
      ln -sfn "/dev/block/by-name/${p}_a" "/dev/block/by-name/${p}_b"
    fi
  done
  echo "stage=modem-slot a (Android's own images; _b names remapped)"
fi
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
# LK's bootargs carry the slot as Unisoc spells it -- sprdboot.slot_suffix=_b -- and
# this is also what modem_control reads: with _b it loads the *other* slot's modem
# images and NV (nr_phy_b, nr_fixnv1_b, nr_deltanv_b) instead of the ones Android
# itself runs.  Rewrite both spellings, and add them if the source has neither.
src=/proc/cmdline
grep -qE '(android|sprd)boot\.slot_suffix' /proc/cmdline ||
    [ ! -r /proc/device-tree/chosen/bootargs ] || src=/proc/device-tree/chosen/bootargs
tr -d '\000' < "$src" |
    sed -e 's/sprdboot\.slot_suffix=_b/sprdboot.slot_suffix=_a/' \
        -e 's/androidboot\.slot_suffix=_b/androidboot.slot_suffix=_a/' \
    > /run/e5-cmdline.android
grep -qE '(android|sprd)boot\.slot_suffix' /run/e5-cmdline.android ||
    printf ' androidboot.slot_suffix=_a sprdboot.slot_suffix=_a\n' >> /run/e5-cmdline.android
chmod 0666 /sys/devices/platform/soc/*/*sipa-dele*/sipa_dele_reset 2>/dev/null || true
mountpoint -q "$A/proc/cmdline" || mount --bind /run/e5-cmdline.android "$A/proc/cmdline"

echo "stage=exec"
unset LD_PRELOAD
export LD_LIBRARY_PATH=/apex/com.android.runtime/lib64/bionic:/system/lib64:/vendor/lib64
exec chroot "$A" /vendor/bin/modem_control
