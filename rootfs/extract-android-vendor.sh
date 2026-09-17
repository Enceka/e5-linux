#!/bin/sh
# Pull the Android vendor runtime modem_control needs from a rooted E5, and build
# the chroot subset that rootfs/overlay/opt/e5/vendor-start.sh uses.
#
# The E5's Android is a *production* build (ro.build.type=user, ro.debuggable=0):
# there is no "su" in PATH and "adb root" is refused.  Magisk is installed though,
# which is what makes this possible: /debug_ramdisk/su -c id -> uid=0.
#
# These files are proprietary (Unisoc/Google) and are deliberately NOT part of
# this repository; only this recipe is.  Result is ~49 MiB, of which
# /dev/__properties__ is 1.4 MiB and /system/lib64 86 MiB uncompressed.
set -eu
OUT=${1:-work/android-subset}
SU=/debug_ramdisk/su

adb shell "$SU -c id" | grep -q 'uid=0' || {
    echo "need root on Android (Magisk's $SU); the device must be running Android" >&2
    exit 1
}

TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
tar -cf "$TMP/raw.tar" -C "$TMP" --files-from /dev/null 2>/dev/null || true

adb push /dev/stdin/ /dev/null 2>/dev/null || true
cat > "$TMP/extract.sh" <<'EOS'
#!/system/bin/sh
OUT=/data/local/tmp/e5-vendor.tar
rm -f $OUT
cd /
tar -chf $OUT \
  /apex/com.android.runtime /system/lib64 \
  /vendor/bin/modem_control /vendor/bin/cp_diskserver /vendor/bin/refnotify \
  /vendor/bin/sh /vendor/bin/toybox_vendor /vendor/bin/getprop \
  /vendor/lib64/libkernelbootcp.trusty.so /vendor/lib64/lib_crypto.so \
  /vendor/etc/modem_cp_info.xml /vendor/etc/modem_sp_info.xml /vendor/etc/modem_ch_info.xml \
  /vendor/etc/cp_dump_info.xml /vendor/etc/ueventd.rc \
  /dev/__properties__
ls -l $OUT
EOS
adb push "$TMP/extract.sh" /data/local/tmp/ >/dev/null
adb shell "$SU -c 'sh /data/local/tmp/extract.sh'" | tail -1

mkdir -p "$OUT-raw"
adb pull /data/local/tmp/e5-vendor.tar "$OUT-raw/" >/dev/null
rm -rf "$OUT"
mkdir -p "$OUT"
tar -xf "$OUT-raw/e5-vendor.tar" -C "$OUT" \
  apex/com.android.runtime/bin/linker64 apex/com.android.runtime/lib64/bionic \
  system/lib64/libcutils.so system/lib64/libexpat.so system/lib64/liblog.so \
  system/lib64/libhardware_legacy.so system/lib64/libc++.so system/lib64/libbase.so \
  system/lib64/libbinder.so system/lib64/libbinder_ndk.so system/lib64/libhidlbase.so \
  system/lib64/libutils.so system/lib64/libtrusty.so system/lib64/libvndksupport.so \
  system/lib64/libz.so system/lib64/libcrypto.so system/lib64/libselinux.so \
  system/lib64/libpcre2.so system/lib64/libpackagelistparser.so \
  system/lib64/libprocessgroup.so system/lib64/libcgrouprc.so \
  system/lib64/libandroid_runtime_lazy.so system/lib64/android.system.suspend-V1-ndk.so \
  vendor/lib64/libkernelbootcp.trusty.so vendor/lib64/lib_crypto.so \
  vendor/bin/modem_control vendor/bin/cp_diskserver vendor/bin/refnotify \
  vendor/bin/sh vendor/bin/toybox_vendor vendor/bin/getprop \
  vendor/etc/modem_cp_info.xml vendor/etc/modem_sp_info.xml vendor/etc/modem_ch_info.xml \
  vendor/etc/cp_dump_info.xml vendor/etc/ueventd.rc \
  dev/__properties__
rm -rf "$OUT-raw"
# bionic refuses to parse a property_info that is not root:root (see docs/FINDINGS.md
# section 13), so the subset has to be installed root-owned on the device:
#   tar -C / -xf ...  (as root)  ->  /opt/e5/android
du -sh "$OUT"
