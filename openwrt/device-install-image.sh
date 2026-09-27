#!/bin/sh
# Install (or update) OpenWrt's own root image, e5linux/openwrt.ext4 on
# userdata, which boot/init starts when it is chosen (e5-os openwrt) or is the
# only system there.  Runs on the device as root, in whatever Linux it runs:
# Debian, OpenWrt in the Debian image's /openwrt, or the standalone OpenWrt
# itself; openwrt/install-standalone.sh sends it.
#
#   device-install-image.sh IMAGE.ext4.gz|URL [--try|--switch]
#
# The image is unpacked next to the installed one (openwrt.ext4.part) and
# renamed at the end.  The running standalone OpenWrt cannot be replaced under
# itself: its update goes to openwrt.ext4.new, which the initramfs swaps in at
# the next boot (the old one stays as openwrt.ext4.old until the next update).
#
# The new image keeps the configuration of an installed OpenWrt -- the running
# one, else the installed image, else the Debian image's /openwrt -- as
# openwrt/device-install.sh does (/etc/config, passwords, SSH keys, /etc/e5,
# the traffic records); packages added with apk are not carried over.  With no
# OpenWrt before it, it takes Debian's APN and hotspot for the first boot.
# Linux as the default boot and the misc blocks come along either way.
#
# --try boots OpenWrt once, --switch makes it the default; both reboot.
set -eu
SRC=${1:?image}
MODE=${2:-}
case "$MODE" in ''|--try|--switch) ;; *) echo "unknown option $MODE" >&2; exit 2 ;; esac

D=/mnt/e5-data
# userdata: the initramfs leaves it at /mnt/e5-data; one that predates that
# keeps it to itself, and the partition is mounted a second time (the same
# f2fs, not a copy)
if ! grep -qs " $D " /proc/mounts; then
    dev=
    for u in /sys/class/block/mmcblk*p*/uevent; do
        grep -qx PARTNAME=userdata "$u" 2>/dev/null && dev=/dev/$(basename "$(dirname "$u")")
    done
    [ -n "$dev" ] || { echo "no userdata partition" >&2; exit 1; }
    mkdir -p "$D"
    mount -t f2fs -o noatime "$dev" "$D"
    echo "== mounted userdata ($dev) at $D"
fi
DIR=$D/e5linux IMG=$D/e5linux/openwrt.ext4
PART=$IMG.part NEW_ROOT=/tmp/e5-img.new OLD_ROOT=/tmp/e5-img.old
mkdir -p "$DIR"

# the running root: the image itself when OpenWrt runs from it
running_image=
if [ -f /etc/openwrt_release ] && [ "$(cat /etc/e5/image-form 2>/dev/null)" = standalone ]; then
    running_image=1
fi

cleanup() {
    umount "$NEW_ROOT" 2>/dev/null || true
    umount "$OLD_ROOT" 2>/dev/null || true
    rm -f "$PART"
}
trap cleanup EXIT

avail=$(df -Pk "$D" | awk 'NR == 2 { print $4 }')
[ "$avail" -gt 1572864 ] || { echo "less than 1.5 GiB free on userdata" >&2; exit 1; }
rm -f "$DIR/openwrt.ext4.old"

echo "== unpacking into $PART"
rm -f "$PART" "$PART.fail"
case "$SRC" in
    http://*|https://*) { wget -q -O - "$SRC" || touch "$PART.fail"; } | gunzip -c > "$PART" ;;
    *) gunzip -c "$SRC" > "$PART" ;;
esac
[ ! -e "$PART.fail" ] || { rm -f "$PART.fail"; echo "download failed" >&2; exit 1; }

mkdir -p "$NEW_ROOT" "$OLD_ROOT"
mount -t ext4 -o loop "$PART" "$NEW_ROOT"
[ -x "$NEW_ROOT/sbin/init" ] && [ -f "$NEW_ROOT/etc/openwrt_release" ] ||
    { echo "not an OpenWrt image" >&2; exit 1; }

# the OpenWrt whose configuration the new image keeps
from=
if [ -f /etc/openwrt_release ]; then
    from=/
elif [ -f "$IMG" ] && mount -t ext4 -o loop,ro "$IMG" "$OLD_ROOT" 2>/dev/null; then
    from=$OLD_ROOT
elif [ -d /openwrt/etc/config ]; then
    from=/openwrt
fi

N=$NEW_ROOT
if [ -n "$from" ]; then
    echo "== keeping the configuration of $from"
    # (the new image's own, not the kept ones)
    for f in image-version image-form; do
        cp "$N/etc/e5/$f" "/tmp/e5-img.$f" 2>/dev/null || rm -f "/tmp/e5-img.$f"
    done
    for p in etc/config etc/shadow etc/passwd etc/group etc/dropbear etc/e5 etc/e5linux \
             etc/uhttpd.crt etc/uhttpd.key etc/vnstat; do
        [ -e "$from/$p" ] || continue
        if [ -d "$from/$p" ] && [ -d "$N/$p" ]; then
            cp -a "$from/$p/." "$N/$p/"
        else
            rm -rf "$N/$p"
            cp -a "$from/$p" "$N/$p"
        fi
    done
    for f in image-version image-form; do
        rm -f "$N/etc/e5/$f"
        [ -f "/tmp/e5-img.$f" ] && mv "/tmp/e5-img.$f" "$N/etc/e5/$f"
    done
fi
umount "$OLD_ROOT" 2>/dev/null || true

if [ ! -f "$N/etc/e5/install.conf" ] && command -v nmcli >/dev/null 2>&1; then
    echo "== settings from Debian"
    # nmcli -g escapes ":" and "\\" in what it prints
    get() { nmcli "$@" 2>/dev/null | sed 's/\\\(.\)/\1/g' || true; }
    apn=$(get -g gsm.apn connection show Mobile)
    ssid=$(get -g 802-11-wireless.ssid connection show Hotspot)
    key=$(get -s -g 802-11-wireless-security.psk connection show Hotspot)
    chan=$(get -g 802-11-wireless.channel connection show Hotspot)
    q() { printf "'%s'" "$(printf '%s' "$1" | sed "s/'/'\\\\''/g")"; }
    mkdir -p "$N/etc/e5"
    (
        umask 077
        echo "# from the Debian image's NetworkManager profiles at install (openwrt/device-install-image.sh)"
        echo "E5_APN=$(q "$apn")"
        echo "E5_WIFI_SSID=$(q "${ssid:-E5-Linux}")"
        echo "E5_WIFI_KEY=$(q "$key")"
        echo "E5_WIFI_CHANNEL=$(q "${chan:-149}")"
    ) > "$N/etc/e5/install.conf"
    chmod 600 "$N/etc/e5/install.conf"
    echo "   apn=${apn:-(none)} ssid=${ssid:-E5-Linux} channel=${chan:-149} key=$([ -n "$key" ] && echo set || echo none)"
fi

# An image built without the device's files (E5_DEVICE_FILES=0) takes them
# from userdata's device-files.tar, which boot/init unpacks as well; made here
# from this system's own when there is none yet (every form of e5-linux has
# them at /lib/firmware and /opt/e5/android)
DFT=$DIR/device-files.tar
if [ ! -f "$N/lib/firmware/wcnmodem.bin" ]; then
    if [ ! -f "$DFT" ] && [ -f /lib/firmware/wcnmodem.bin ] && [ -x /opt/e5/android/vendor/bin/modem_control ]; then
        echo "== the device's files from this system -> $DFT"
        list=$(cd / && for f in lib/firmware/wcnmodem.bin lib/firmware/gnssmodem.bin \
                   lib/firmware/wifi_board_config*.ini lib/firmware/tsx_data lib/firmware/l_agdsp_a.img \
                   lib/firmware/audio_structure lib/firmware/dsp_vbc lib/firmware/cvs \
                   lib/firmware/aw87xxx_acf.bin lib/firmware/sprd opt/e5/android; do
                   [ -e "$f" ] && echo "$f"; done)
        (cd / && tar -cf "$DFT.part" $list) && mv "$DFT.part" "$DFT"
    fi
    if [ -f "$DFT" ]; then
        tar -xf "$DFT" -C "$N"
        sha256sum "$DFT" | cut -d' ' -f1 > "$N/etc/e5/device-files.stamp"
        echo "== the device's files unpacked into the image"
    else
        echo "WARNING: the image has no firmware or vendor subset, and there is no $DFT" >&2
    fi
fi

mkdir -p "$N/etc/e5linux"
[ -f /etc/e5linux/default-boot ] && [ ! -f "$N/etc/e5linux/default-boot" ] &&
    cp /etc/e5linux/default-boot "$N/etc/e5linux/default-boot"
cp /run/e5linux/misc-bc-slot-a.bin /run/e5linux/misc-bc-slot-b-trial.bin "$N/etc/e5linux/" 2>/dev/null || true
ver=$(cat "$N/etc/e5/image-version" 2>/dev/null || echo "?")
umount "$NEW_ROOT"

if [ -n "$running_image" ]; then
    mv "$PART" "$IMG.new"
    echo "installed: $IMG.new ($ver), swapped in at the next boot"
else
    mv "$PART" "$IMG"
    echo "installed: $IMG ($ver)"
fi
sync

grep -qs openwrt-image /run/e5linux/init-features || {
    echo "the boot image in use predates OpenWrt images of their own: flash a newer one" >&2
    echo "(boot/flash-from-linux.sh) before booting it" >&2
    exit 0
}
case "$MODE" in
    --try)    echo openwrt > "$DIR/boot-os-next"; sync; reboot ;;
    --switch) rm -f "$DIR/boot-os-next"; echo openwrt > "$DIR/boot-os"; sync; reboot ;;
    '')       [ -n "$running_image" ] && echo "reboot to start it" ||
                  echo "boot it with: e5-os openwrt --once (one boot) or e5-os openwrt, then reboot" ;;
esac
