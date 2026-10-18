#!/system/bin/sh
# Run as root on the E5's Android by flash.py: the device's own files for
# OpenWrt, packed as the archive boot/init unpacks into the image
# (e5linux/device-files.tar).
#
#   collect-device-files.sh OUT.tar FIRMWARE.tar
#
# The Android vendor subset the baseband's modem_control needs (the list of
# e5-linux's rootfs/extract-android-vendor.sh) goes to opt/e5/android, the
# firmware the host converted (FIRMWARE.tar: lib/firmware/...) next to it.
# Collected here, not on the computer: some of these files have ":" in their
# names (the property area), which Windows cannot store.  Everything owned by
# root: bionic refuses a property area that is not.
umask 022
OUT=${1:?out} FW=${2:?firmware}
S=${E5_COLLECT_WORK:-/data/local/tmp/e5-devfiles}
rm -rf "$S"
mkdir -p "$S/opt/e5/android" "$S/lib/firmware" || exit 1
elf_class=$(od -An -tu1 -j4 -N1 /vendor/bin/modem_control | tr -d ' \n')
case "$elf_class" in
  1) android_lib=lib; android_linker=linker ;;
  2) android_lib=lib64; android_linker=linker64 ;;
  *) echo "E5-COLLECT-FAIL invalid modem_control ELF class"; exit 1 ;;
esac
for p in \
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
do
  # Android may be a 32-bit userspace on the same arm64 SoC (T551M).
  p=$(echo "$p" | sed "s@/lib64@/$android_lib@g; s@/bin/linker64@/bin/$android_linker@g")
  d="$S/opt/e5/android/$(dirname "$p")"
  mkdir -p "$d"
  cp -rL "/$p" "$d/" 2>/dev/null || { echo "E5-COLLECT-FAIL missing /$p"; exit 1; }
done
tar -xf "$FW" -C "$S" || { echo "E5-COLLECT-FAIL firmware archive"; exit 1; }
chown -R 0:0 "$S" || exit 1
find "$S/opt/e5/android" -type d -exec chmod 755 {} + || exit 1
find "$S/opt/e5/android" -type f -exec chmod 644 {} + || exit 1
find "$S/opt/e5/android" -type f -path '*/bin/*' -exec chmod 755 {} + || exit 1
find "$S/opt/e5/android/dev/__properties__" -type f -exec chmod 444 {} + || exit 1
for f in lib/firmware/wcnmodem.bin lib/firmware/l_agdsp_a.img lib/firmware/sprd/marlin3lite_pskey.bin \
         opt/e5/android/vendor/bin/modem_control opt/e5/android/dev/__properties__/property_info; do
  [ -s "$S/$f" ] || { echo "E5-COLLECT-FAIL no $f"; exit 1; }
done
mkdir -p "$(dirname "$OUT")"
(cd "$S" && tar -cf "$OUT.part" lib opt) || { echo "E5-COLLECT-FAIL tar"; exit 1; }
mv "$OUT.part" "$OUT"
rm -rf "$S" "$FW"
echo "E5-COLLECT-OK $(ls -l "$OUT" | awk '{print $5}')"
