#!/bin/bash
# Install OpenWrt as a system of its own on an E5 -- its root image,
# out/openwrt/e5-openwrt-<version>.ext4.gz (openwrt/build-rootfs.sh with
# E5_STANDALONE=1), as e5linux/openwrt.ext4 on userdata, where boot/init
# starts it.  No Debian needed: with no Debian image (e5linux/rootfs.ext4)
# next to it, OpenWrt is what boots; with one, e5-os chooses.
#
# From Linux on the device (Debian, or OpenWrt in either form), over the USB
# LAN; the configuration of an installed OpenWrt is kept, a reinstall from the
# running standalone OpenWrt swaps in at the next boot:
#
#   openwrt/install-standalone.sh [--try|--switch] [IMAGE]
#
# From rooted Android, over adb (the way rootfs/install-rootfs.sh puts the
# Debian image there); the settings for the first boot come from the options
# (no APN: from the SIM), Wi-Fi stays off without a key:
#
#   openwrt/install-standalone.sh --adb [--apn APN] [--ssid SSID] [--wifi-key KEY] [IMAGE]
#
# The boot image has to be one that knows OpenWrt images (boot/init after
# 2026-09-27): boot/flash-trial.sh from Android, boot/flash-from-linux.sh from
# Linux.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
TOP="$(cd "$HERE/.." && pwd)"
MODE= ADB= APN= SSID=E5-Linux KEY=
while [ $# -gt 0 ]; do
    case "$1" in
        --try|--switch) MODE=$1 ;;
        --adb) ADB=1 ;;
        --apn) APN=${2:?}; shift ;;
        --ssid) SSID=${2:?}; shift ;;
        --wifi-key) KEY=${2:?}; shift ;;
        -*) echo "unknown option $1" >&2; exit 2 ;;
        *) break ;;
    esac
    shift
done
IMG=${1:-$(ls -t "$TOP"/out/openwrt/e5-openwrt-*.ext4.gz 2>/dev/null | head -1)}
[ -f "$IMG" ] || { echo "no image -- run E5_STANDALONE=1 openwrt/build-rootfs.sh first" >&2; exit 1; }
[ -z "$KEY" ] || [ ${#KEY} -ge 8 ] || { echo "a WPA2 key has at least 8 characters" >&2; exit 1; }
echo "== $(basename "$IMG") ($(du -h "$IMG" | cut -f1))"

if [ -z "$ADB" ]; then
    IP=${E5_HOST_IP:-192.168.9.2}
    PORT=${E5_HTTP_PORT:-8791}
    SERVE=$(mktemp -d)
    trap 'kill $SRV 2>/dev/null; rm -rf "$SERVE"' EXIT
    ln -s "$IMG" "$SERVE/openwrt.ext4.gz"
    cp "$HERE/device-install-image.sh" "$SERVE/device-install-image.sh"
    python3 -m http.server "$PORT" --bind "$IP" -d "$SERVE" >/dev/null 2>&1 &
    SRV=$!
    sleep 1
    E5_TELNET_WAIT=${E5_TELNET_WAIT:-1200} python3 "$TOP/tools/e5-telnet.py" \
        "wget -q -O /tmp/e5-install-image.sh http://$IP:$PORT/device-install-image.sh && sh /tmp/e5-install-image.sh http://$IP:$PORT/openwrt.ext4.gz $MODE"
    exit 0
fi

# ---- from Android
[ -z "$MODE" ] || { echo "--try/--switch need Linux running; from Android flash the boot image next" >&2; exit 2; }
su_do() { adb shell "su -c '$1'" | tr -d '\r'; }
su_do id | grep -q 'uid=0' || { echo "need root on Android (Magisk)" >&2; exit 1; }
DIR=/data/e5linux REMOTE=/data/local/tmp/openwrt.ext4.gz
avail=$(su_do 'df -k /data | tail -1' | awk '{print $4}')
[ "${avail:-0}" -gt 2097152 ] || { echo "less than 2 GiB free in /data" >&2; exit 1; }

want=$(shasum -a 256 "$IMG" 2>/dev/null | cut -d' ' -f1 || sha256sum "$IMG" | cut -d' ' -f1)
# (in pieces, each checked: adb push has no resume -- rootfs/install-rootfs.sh)
chunks=$(mktemp -d)
trap 'rm -rf "$chunks"' EXIT
split -b 128m "$IMG" "$chunks/p"
su_do "rm -f $REMOTE"
for f in "$chunks"/p*; do
    n=$(basename "$f") size=$(stat -f %z "$f" 2>/dev/null || stat -c %s "$f")
    for try in 1 2 3; do
        adb push "$f" /data/local/tmp/ >/dev/null 2>&1 || true
        [ "$(su_do "stat -c %s /data/local/tmp/$n")" = "$size" ] && break
    done
    [ "$(su_do "stat -c %s /data/local/tmp/$n")" = "$size" ] || { echo "push of $n failed" >&2; exit 1; }
    su_do "cat /data/local/tmp/$n >> $REMOTE; rm -f /data/local/tmp/$n"
    echo "  $n ok"
done
[ "$(su_do "sha256sum $REMOTE" | awk '{print $1}')" = "$want" ] || { echo "hash mismatch on the device" >&2; exit 1; }

su_do "mkdir -p $DIR && gzip -dc $REMOTE > $DIR/openwrt.ext4.part && mv $DIR/openwrt.ext4.part $DIR/openwrt.ext4 && chmod 644 $DIR/openwrt.ext4; rm -f $REMOTE; sync"
su_do "ls -l $DIR/openwrt.ext4"

# the first boot's settings, taken in by the image's uci-defaults (90-e5)
q() { printf "'%s'" "$(printf '%s' "$1" | sed "s/'/'\\\\''/g")"; }
conf=$(mktemp)
{
    echo "# openwrt/install-standalone.sh --adb"
    echo "E5_APN=$(q "$APN")"
    echo "E5_WIFI_SSID=$(q "$SSID")"
    echo "E5_WIFI_KEY=$(q "$KEY")"
    echo "E5_WIFI_CHANNEL='149'"
    echo "E5_DEFAULT_BOOT='linux'"
} > "$conf"
adb push "$conf" /data/local/tmp/openwrt-install.conf >/dev/null
rm -f "$conf"
su_do "mv /data/local/tmp/openwrt-install.conf $DIR/openwrt-install.conf && chmod 600 $DIR/openwrt-install.conf"

if su_do "[ -f $DIR/rootfs.ext4 ] && echo yes" | grep -q yes; then
    # Debian is there too: OpenWrt from now on (e5-os debian switches back)
    su_do "echo openwrt > $DIR/boot-os"
    echo "Debian is installed as well: boot-os set to openwrt (e5-os debian switches back)"
fi
echo "installed. next: flash the boot image, boot/flash-trial.sh work/boot-linux-slotb-<name>.img,"
echo "(OpenWrt makes Linux the default boot at its first start)"
