#!/system/bin/sh
# No boot hooks: only an explicit Magisk action or root-shell invocation.
set -eu
MODDIR=$(cd "${0%/*}" && pwd)
case "${1:-check}" in check|reboot) ;; *) echo 'usage: switch.sh check|reboot' >&2; exit 2 ;; esac
fail() { echo "错误 / Error: $*" >&2; exit 1; }
[ "$(id -u)" = 0 ] || fail '需要 root / Root is required'
[ "$(getprop ro.boot.slot_suffix)" = _a ] || fail '当前不是 Android slot A / Android must be running from slot A'
for p in boot_b misc l_agdsp_a; do [ -b "/dev/block/by-name/$p" ] || fail "缺少分区 / Missing partition: $p"; done
"$MODDIR/e5-bootctl" check || exit 1
MB=/data/adb/magisk/magiskboot
[ -x "$MB" ] || fail '缺少 magiskboot'
umask 077
WORK=$(mktemp -d "$MODDIR/.check.XXXXXX")
cleanup() { umount "$WORK/root" 2>/dev/null || true; rm -rf "$WORK"; }
trap cleanup EXIT
# Extract only to temporary files. Neither boot slot is written or repacked.
(cd "$WORK" && "$MB" unpack /dev/block/by-name/boot_b >/dev/null 2>&1 &&
 "$MB" cpio ramdisk.cpio 'extract init linux-init' >/dev/null 2>&1) || fail '无法解析 boot_b / Cannot unpack boot_b'
grep -q 'ROOT_FILE=/data/e5linux/rootfs.ext4' "$WORK/linux-init" &&
 grep -q 'misc-bc-slot-b-trial.bin' "$WORK/linux-init" || fail 'boot_b 不是 e5-linux；请先安装 Linux / boot_b is not e5-linux'
# Validate an installed root without changing SD metadata, default/next or
# mounting userdata. This matches the current initramfs registry selection.
. "$MODDIR/sd-registry.sh"
mkdir "$WORK/root"
emmc=$(readlink -f /dev/block/by-name/misc); emmc=${emmc##*/}; emmc=${emmc%%p*}
registered=0
wanted=
for u in /sys/class/block/mmcblk*p*/uevent; do
 [ -f "$u" ] || continue
 grep -qx PARTNAME=e5boot "$u" || continue
 dev=${u%/uevent}; dev=/dev/block/${dev##*/}
 # Android normally exposes GPT PARTNAME in sysfs just as Linux does.
 if mount -t ext4 -o ro,noload "$dev" "$WORK/root" 2>/dev/null; then
  sd_registry_valid "$WORK/root" || fail 'SD 多系统注册表损坏 / Invalid SD registry'
  wanted=$(cat "$WORK/root/default")
  once=$(cat "$WORK/root/next" 2>/dev/null || true)
  if sd_id_valid "$once" && [ -d "$WORK/root/systems/$once" ]; then wanted=$once; fi
  cp -R "$WORK/root/systems/$wanted" "$WORK/slots"
  cp "$WORK/root/kernel-release" "$WORK/kernel-release"
  kernel=$(strings "$WORK/kernel" | sed -n 's/^Linux version \([^ ]*\).*/\1/p' | head -1)
  [ "$kernel" = "$(cat "$WORK/kernel-release")" ] || fail 'SD 注册内核与 boot_b 不匹配 / SD kernel does not match boot_b'
  registered=1
  umount "$WORK/root"
 fi
done
root_found=0
for d in /sys/class/block/mmcblk*; do
 n=${d##*/}; case "$n" in *p[0-9]*|*boot*|"$emmc") continue ;; esac
 for part in /dev/block/"$n" /dev/block/"${n}"p*; do
  [ -b "$part" ] || continue
  if [ "$registered" = 1 ]; then
   uuid=$(sed -n 's/^PARTUUID=//p' "/sys/class/block/${part##*/}/uevent")
   grep -qx "$uuid" "$WORK/slots/"* 2>/dev/null || continue
  fi
  mount -t ext4 -o ro,noload "$part" "$WORK/root" 2>/dev/null || continue
  if { [ -x "$WORK/root/sbin/init" ] || [ -x "$WORK/root/lib/systemd/systemd" ]; } && [ -f "$WORK/root/etc/e5/sd-root" ]; then
   identity=$(cat "$WORK/root/etc/e5/sd-system" 2>/dev/null || true)
   [ -n "$identity" ] || { [ ! -f "$WORK/root/etc/openwrt_release" ] || identity=openwrt; }
   failed=$(cat "$WORK/root/etc/e5/sd-trial" 2>/dev/null || true)
   if { [ "$registered" = 0 ] || [ "$identity" = "$wanted" ]; } && [ "$failed" != 0 ]; then root_found=1; fi
  fi
  umount "$WORK/root"
 done
done
if [ "$root_found" = 0 ] && [ "$registered" = 0 ]; then
 # Android owns the already-mounted /data. No image or selection is rewritten.
 for image in /data/e5linux/rootfs.ext4 /data/e5linux/openwrt.ext4; do
  [ -s "$image" ] || continue
  mount -t ext4 -o loop,ro,noload "$image" "$WORK/root" 2>/dev/null || continue
  for base in "$WORK/root" "$WORK/root/ubuntu" "$WORK/root/openwrt"; do
   if [ -f "$base/etc/os-release" ] &&
      { [ -x "$base/sbin/init" ] || [ -x "$base/lib/systemd/systemd" ] || [ -x "$base/usr/lib/systemd/systemd" ]; }; then root_found=1; fi
  done
  umount "$WORK/root"
 done
fi
[ "$root_found" = 1 ] || fail '未找到可启动的 Linux；检查 SD 卡或先安装 / No bootable Linux root; check the SD card or install Linux first'
echo "Linux 已安装 / Linux is installed${wanted:+: $wanted}"
[ "${1:-check}" = reboot ] || exit 0
backup="$MODDIR/boot-control-$(date +%Y%m%d-%H%M%S)-$$.bin"
"$MODDIR/e5-bootctl" arm "$backup" || exit 1
sync
cleanup
trap - EXIT
echo '正在切回 Linux / Rebooting into Linux'
/system/bin/reboot
