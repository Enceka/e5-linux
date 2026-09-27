#!/bin/bash
# 荣悦 E5 OpenWrt 一键刷入 / one-click flash of OpenWrt on the Rongyue E5.
#
#   ./flash.sh                  first install, from rooted Android over adb
#   ./flash.sh --update         update, from the running e5-linux over the USB LAN
#                               (OpenWrt's settings kept)
#   ./flash.sh --boot-openwrt   from Android back to the installed OpenWrt (adb)
#
# Options for the first install (asked for when not given):
#   --apn APN            the carrier's APN (default: automatic, from the SIM)
#   --ssid SSID          the hotspot's name (default E5-OpenWrt)
#   --wifi-key KEY       the hotspot's WPA2 key, 8-63 characters (default: random)
#   -y                   no questions: the defaults for what is not given
#
# Needs macOS or Linux with adb and python3.  See README.md.
set -euo pipefail
cd "$(dirname "$0")"
B=$PWD F=$PWD/files
MODE=install APN= APN_SET= SSID=E5-OpenWrt KEY= YES=
while [ $# -gt 0 ]; do
    case "$1" in
        --update) MODE=update ;;
        --boot-openwrt) MODE=boot ;;
        --apn) APN=${2?}; APN_SET=1; shift ;;
        --ssid) SSID=${2:?}; shift ;;
        --wifi-key) KEY=${2:?}; shift ;;
        -y) YES=1 ;;
        -h|--help) sed -n 2,17p "$0"; exit 0 ;;
        *) echo "unknown option $1" >&2; exit 2 ;;
    esac
    shift
done

say() { printf '\n== %s\n' "$*"; }
die() { printf '\n错误 / error: %s\n' "$*" >&2; exit 1; }
sha() { { shasum -a 256 "$1" 2>/dev/null || sha256sum "$1"; } | cut -d' ' -f1; }
fsize() { stat -f %z "$1" 2>/dev/null || stat -c %s "$1"; }
jget() { python3 -c "import json,sys;print(json.load(open(sys.argv[1]))[sys.argv[2]])" "$F/boot.json" "$1"; }

command -v python3 >/dev/null || die "python3 not found"
say "检查刷机包 / checking the package"
(cd "$B" && while read -r h f; do
    [ "$(sha "$f")" = "$h" ] || { echo "$f: damaged" >&2; exit 1; }
done < SHA256SUMS) || die "the package is damaged, download it again"
echo "   $(cat "$F/VERSION")"

# ------------------------------------------------------------------ update
if [ "$MODE" = update ]; then
    HOST=${E5_HOST:-192.168.9.1}
    export E5_TELNET_HOST=$HOST
    [ -n "${E5_TELNET_PASS:-}" ] || { read -r -s -p "root password of the E5 [root]: " p; echo; export E5_TELNET_PASS=${p:-root}; }
    LOCAL_IP=$(ifconfig 2>/dev/null | awk '/inet 192\.168\.9\./{print $2; exit}')
    [ -n "$LOCAL_IP" ] || LOCAL_IP=$(ip -4 addr 2>/dev/null | awk '/inet 192\.168\.9\./{sub("/.*","",$2); print $2; exit}')
    [ -n "$LOCAL_IP" ] || die "no address on the E5's USB LAN (192.168.9.x): is it connected and running Linux?"
    PORT=${E5_HTTP_PORT:-8793}
    S=$(mktemp -d)
    trap 'kill $SRV 2>/dev/null; rm -rf "$S"' EXIT
    MB=$(( $(jget persist_log_offset) / 1048576 ))
    dd if="$F/boot.img" of="$S/boot-head.img" bs=1048576 count="$MB" 2>/dev/null
    ln -s "$F/openwrt.ext4.gz" "$S/openwrt.ext4.gz"
    cp "$F/device-install-image.sh" "$F/device-flash-boot.sh" "$S/"
    python3 -m http.server "$PORT" --bind "$LOCAL_IP" -d "$S" >/dev/null 2>&1 &
    SRV=$!
    sleep 1
    U=http://$LOCAL_IP:$PORT
    say "更新 / updating $HOST"
    E5_TELNET_WAIT=1800 python3 "$B/scripts/tools/e5-telnet.py" \
        "cd /tmp && wget -q -O dfb.sh $U/device-flash-boot.sh && wget -q -O dii.sh $U/device-install-image.sh && sh dfb.sh $U/boot-head.img $(jget sha256_head56m) $MB && sh dii.sh $U/openwrt.ext4.gz && d=/mnt/e5-data/e5linux && rm -f \$d/boot-os-next && echo openwrt > \$d/boot-os && echo E5-UPDATE-\$((1+1)) && sync && (sleep 2; reboot &)" \
        | tee "$S/log" | grep -E '^(==|installed|WARNING|E5-UPDATE)' || true
    grep -q E5-UPDATE-2 "$S/log" || { tail -20 "$S/log"; die "the update did not finish (the log is above)"; }
    say "完成，设备正在重启 / done, the E5 is rebooting"
    exit 0
fi

# ------------------------------------------------------------------ install
command -v adb >/dev/null || die "adb not found (Android platform-tools)"
say "连接设备 / looking for the E5 (Android, USB debugging on)"
n=$(adb devices | awk 'NR > 1 && $2 == "device"' | wc -l | tr -d ' ')
[ "$n" = 1 ] || die "need exactly one device in 'adb devices' (found $n; allow USB debugging on the phone)"
sh_() { adb shell "$1" | tr -d '\r'; }
SU=
for s in su /debug_ramdisk/su /sbin/su; do
    sh_ "$s -c id" 2>/dev/null | grep -q 'uid=0' && { SU=$s; break; }
done
[ -n "$SU" ] || die "no root: install Magisk and grant Shell superuser access"
export E5_SU=$SU
su_() { adb shell "$SU -c '$1'" | tr -d '\r'; }
[ "$(sh_ 'getprop ro.boot.slot_suffix')" = _a ] || die "Android is not running from slot a"
[ "$(sh_ 'getprop ro.boot.verifiedbootstate')" = orange ] || die "the bootloader is locked (verifiedbootstate is not orange)"
su_ '[ -e /dev/block/by-name/boot_b ] && [ -e /dev/block/by-name/l_agdsp_a ] && echo ok' | grep -q ok ||
    die "no boot_b or l_agdsp_a partition: not an E5?"
echo "   ok ($(sh_ 'getprop ro.product.model'), root via $SU)"

arm_slot_b() {
    adb push "$F/boot-misc-slot-b.bin" /data/local/tmp/e5-bc-b.bin >/dev/null
    su_ 'dd if=/data/local/tmp/e5-bc-b.bin of=/dev/block/by-name/misc bs=1 seek=2048 conv=notrunc && sync' >/dev/null 2>&1
    [ "$(su_ 'dd if=/dev/block/by-name/misc bs=1 skip=2048 count=32 2>/dev/null | od -An -tx1 -v' | tr -d ' \n')" = \
      "$(od -An -tx1 -v "$F/boot-misc-slot-b.bin" | tr -d ' \n')" ] || die "arming slot b failed"
    su_ 'rm -f /data/local/tmp/e5-bc-b.bin'
}

if [ "$MODE" = boot ]; then
    su_ '[ -f /data/e5linux/openwrt.ext4 ] && echo ok' | grep -q ok || die "OpenWrt is not installed: run ./flash.sh"
    MB=$(( $(jget persist_log_offset) / 1048576 ))
    head=$(su_ "dd if=/dev/block/by-name/boot_b bs=1048576 count=$MB 2>/dev/null | sha256sum" | cut -d' ' -f1)
    [ "$head" = "$(jget sha256_head56m)" ] || die "boot_b holds another boot image: use the package it was flashed with, or ./flash.sh"
    arm_slot_b
    say "正在重启进 OpenWrt / rebooting into OpenWrt"
    adb reboot
    exit 0
fi

live=$(su_ 'dd if=/dev/block/by-name/misc bs=1 skip=2048 count=32 2>/dev/null | od -An -tx1 -v' | tr -d ' \n')
[ "$live" = "$(jget misc_slot_a_hex)" ] || die "the boot control block is not the one this package expects ($live): boot Android normally once, then try again"
avail=$(su_ 'df -k /data | tail -1' | awk '{print $4}')
[ "${avail:-0}" -gt 2621440 ] || die "less than 2.5 GiB free on the phone's storage"

# settings for OpenWrt's first boot
if [ -z "$YES" ]; then
    [ -n "$APN_SET" ] || read -r -p "APN [自动识别 / automatic, from the SIM]: " APN
    read -r -p "热点名称 / hotspot name [$SSID]: " s; SSID=${s:-$SSID}
    [ -n "$KEY" ] || { read -r -p "热点密码 / hotspot key, 8-63 characters [random]: " KEY; }
fi
[ -n "$KEY" ] || KEY=$(LC_ALL=C tr -dc 'a-km-np-z2-9' < /dev/urandom | head -c 10)
[ ${#KEY} -ge 8 ] && [ ${#KEY} -le 63 ] || die "the hotspot key must have 8-63 characters"

W=$(mktemp -d)
trap 'rm -rf "$W"' EXIT
say "从这台设备提取固件和基带文件 / the firmware and baseband files of this device"
E5_OVERLAY=$W/ovl bash "$B/scripts/rootfs/pull-wcn-firmware.sh" > "$W/wcn.log" 2>&1 ||
    { tail "$W/wcn.log"; die "pulling the Wi-Fi/BT firmware failed"; }
E5_OVERLAY=$W/ovl bash "$B/scripts/rootfs/pull-audio-firmware.sh" > "$W/audio.log" 2>&1 ||
    { tail "$W/audio.log"; die "pulling the audio firmware failed"; }
sh "$B/scripts/rootfs/extract-android-vendor.sh" "$W/android" > "$W/vendor.log" 2>&1 ||
    { tail "$W/vendor.log"; die "pulling the Android vendor files failed"; }
python3 - "$W" <<'EOF'
import os, sys, tarfile
w = sys.argv[1]
need = ['ovl/lib/firmware/wcnmodem.bin', 'ovl/lib/firmware/sprd/marlin3lite_pskey.bin',
        'ovl/lib/firmware/l_agdsp_a.img', 'android/vendor/bin/modem_control',
        'android/dev/__properties__/property_info']
for n in need:
    if not os.path.exists(os.path.join(w, n)):
        sys.exit('missing ' + n)
def root(t):
    t.uid = t.gid = 0; t.uname = t.gname = 'root'
    return t
with tarfile.open(os.path.join(w, 'device-files.tar'), 'w', format=tarfile.GNU_FORMAT) as tar:
    tar.add(os.path.join(w, 'ovl/lib/firmware'), 'lib/firmware', filter=root)
    tar.add(os.path.join(w, 'android'), 'opt/e5/android', filter=root)
EOF
echo "   device-files.tar: $(du -h "$W/device-files.tar" | cut -f1)"

push() {  # local remote -- in pieces, each checked (adb push has no resume)
    local src=$1 dst=$2 p n size
    mkdir -p "$W/chunks" && rm -f "$W/chunks/"*
    split -b 64m "$src" "$W/chunks/p"
    su_ "rm -f $dst"
    for p in "$W/chunks/"p*; do
        n=$(basename "$p") size=$(fsize "$p")
        for _ in 1 2 3; do
            adb push "$p" "/data/local/tmp/$n" >/dev/null 2>&1 || true
            [ "$(su_ "stat -c %s /data/local/tmp/$n")" = "$size" ] && break
        done
        [ "$(su_ "stat -c %s /data/local/tmp/$n")" = "$size" ] || die "pushing $(basename "$src") failed"
        su_ "cat /data/local/tmp/$n >> $dst; rm -f /data/local/tmp/$n"
        printf '.'
    done
    [ "$(su_ "sha256sum $dst" | cut -d' ' -f1)" = "$(sha "$src")" ] || die "$(basename "$src") arrived damaged"
    echo " ok"
}

D=/data/e5linux
say "写入 OpenWrt / OpenWrt -> $D/openwrt.ext4"
su_ "mkdir -p $D"
push "$F/openwrt.ext4.gz" /data/local/tmp/openwrt.ext4.gz
su_ "gzip -dc /data/local/tmp/openwrt.ext4.gz > $D/openwrt.ext4.part && mv $D/openwrt.ext4.part $D/openwrt.ext4; rm -f /data/local/tmp/openwrt.ext4.gz $D/openwrt.ext4.new $D/openwrt.ext4.old"
su_ "ls -l $D/openwrt.ext4" | awk '{print "   " $5 " bytes"}'
push "$W/device-files.tar" "$D/device-files.tar"
q() { printf "'%s'" "$(printf '%s' "$1" | sed "s/'/'\\\\''/g")"; }
{
    echo "# the flash package (flash.sh), for OpenWrt's first boot"
    echo "E5_APN=$(q "$APN")"
    echo "E5_WIFI_SSID=$(q "$SSID")"
    echo "E5_WIFI_KEY=$(q "$KEY")"
    echo "E5_WIFI_CHANNEL='149'"
    echo "E5_DEFAULT_BOOT='linux'"
} > "$W/install.conf"
adb push "$W/install.conf" /data/local/tmp/e5-install.conf >/dev/null
su_ "mv /data/local/tmp/e5-install.conf $D/openwrt-install.conf && chmod 600 $D/openwrt-install.conf"
# OpenWrt from now on, also when an e5-linux Debian is installed as well
su_ "rm -f $D/boot-os-next; echo openwrt > $D/boot-os"

say "写入启动镜像 / boot image -> boot_b"
adb push "$F/boot.img" /data/local/tmp/e5-boot.img >/dev/null
[ "$(su_ 'sha256sum /data/local/tmp/e5-boot.img' | cut -d' ' -f1)" = "$(jget sha256)" ] || die "the boot image arrived damaged"
su_ 'dd if=/data/local/tmp/e5-boot.img of=/dev/block/by-name/boot_b bs=4M && sync' >/dev/null 2>&1
[ "$(su_ 'sha256sum /dev/block/by-name/boot_b' | cut -d' ' -f1)" = "$(jget sha256)" ] || die "boot_b did not verify; Android stays as it is"
su_ 'rm -f /data/local/tmp/e5-boot.img'
arm_slot_b

say "完成，正在重启进 OpenWrt / done, rebooting into OpenWrt"
adb reboot
cat <<EOT

  第一次启动约 2 分钟 / the first boot takes about 2 minutes.
  热点 / hotspot:  $SSID   密码 / key:  $KEY
  管理 / admin:    http://192.168.9.1  (LuCI, root / root -- 请改密码 / change it)
  回 Android:      屏幕 高级 -> 系统 -> 下次启动 Android, or: e5-next-boot android; reboot
  若启动失败，设备会在两次尝试后自动回到 Android。
  If the boot fails, the E5 falls back to Android after two tries.
EOT
