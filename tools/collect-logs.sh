#!/bin/sh
# Collect the evidence of an e5-linux boot attempt from rooted Android, after the
# device has fallen back to Android.
#
# Two independent logs are read:
#   * pstore console-ramoops / pmsg-ramoops: whatever reached the kernel console
#     (our init logs every stage to /dev/kmsg, and the boot image registers
#     ramoops from the command line so early output is not lost)
#   * the 4 MiB persistent block at 56 MiB inside boot_b, written by boot/init;
#     unlike pstore this survives a cold power cycle
#
# usage: tools/collect-logs.sh [outdir]
set -eu
OUT=${1:-logs}
mkdir -p "$OUT"
su_do() { adb shell "su -c '$1'" | tr -d '\r'; }

adb shell 'su -c "cat /proc/version"' | tr -d '\r' | tee "$OUT/version.txt"
echo

echo "== pstore =="
su_do 'ls -la /sys/fs/pstore/' | tee "$OUT/pstore-list.txt"
for f in console-ramoops-0 pmsg-ramoops-0; do
    su_do "cat /sys/fs/pstore/$f" > "$OUT/$f.txt" 2>/dev/null || true
    printf '%-20s %s bytes\n' "$f" "$(wc -c < "$OUT/$f.txt" 2>/dev/null || echo 0)"
done

echo "== boot_b persistent log =="
# 4 MiB at 56 MiB into boot_b (block 14336, 1024 blocks of 4096)
su_do 'dd if=/dev/block/by-name/boot_b bs=4096 skip=14336 count=1024 2>/dev/null' > "$OUT/boot_b-persist.txt" 2>/dev/null || true
sz=$(wc -c < "$OUT/boot_b-persist.txt" 2>/dev/null || echo 0)
echo "boot_b-persist.txt $sz bytes"
grep -a -n 'E5-PERSIST-BEGIN\|E5-LINUX: stage=' "$OUT/boot_b-persist.txt" 2>/dev/null | head -60 || true

echo
echo "== bootloader log (slot, ramdisk, avb) =="
su_do 'dd if=/dev/block/by-name/uboot_log of=/data/local/tmp/uboot.log 2>/dev/null; echo ok' >/dev/null
adb pull /data/local/tmp/uboot.log "$OUT/uboot.log" >/dev/null 2>&1 || true
strings -n 6 "$OUT/uboot.log" 2>/dev/null | grep -iE 'generic ramdisk|slot|verify_ret|avb_slot_verify result|start linux|decompress' | tail -40 || true

echo
echo "logs written to $OUT"
