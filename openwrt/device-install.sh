#!/bin/sh
# Install (or update) the OpenWrt tree into /openwrt of the Debian root image.
# Runs on the device, in Debian, as root; openwrt/install.sh sends it.
#
#   device-install.sh TARBALL [--try|--switch]
#
# The new tree is unpacked next to the old one and swapped in at the end, so
# an interrupted install leaves the old tree (or none) in place.  A reinstall
# keeps OpenWrt's configuration and the files a router keeps across an upgrade
# (/etc/config, passwords, SSH keys, /etc/e5); the first-boot settings then do
# not run again.  From Debian it takes what OpenWrt has to match:
#
#  * the carrier's APN (NetworkManager's "Mobile"), the hotspot's SSID, key
#    and channel ("Hotspot") -> /etc/e5/install.conf, read at first boot;
#  * Linux as the default boot, if Debian has it (/etc/e5linux/default-boot),
#    and the two misc blocks e5-next-boot writes.
#
# --try boots OpenWrt once (e5-os openwrt --once), --switch makes it the
# default (e5-os openwrt); both reboot.  Without either, nothing else changes.
set -eu
T=${1:?tarball}
MODE=${2:-}
DEST=/openwrt NEW=/openwrt.new OLD=/openwrt.old

[ -f /etc/debian_version ] || { echo "run this in the E5's Debian" >&2; exit 1; }
avail=$(df -Pk / | awk 'NR == 2 { print $4 }')
[ "$avail" -gt 307200 ] || { echo "less than 300 MiB free on the root image" >&2; exit 1; }

echo "== unpacking into $NEW"
rm -rf "$NEW" && mkdir -p "$NEW"
tar -xzf "$T" -C "$NEW"

if [ -d "$DEST/etc/config" ]; then
    echo "== keeping the configuration of the installed tree"
    for p in etc/config etc/shadow etc/passwd etc/group etc/dropbear etc/e5 etc/e5linux etc/uhttpd.crt etc/uhttpd.key; do
        [ -e "$DEST/$p" ] || continue
        if [ -d "$DEST/$p" ] && [ -d "$NEW/$p" ]; then
            # merged: the installed files win, and a file only the new tree
            # has (a new package's /etc/config/<name>) is kept
            cp -a "$DEST/$p/." "$NEW/$p/"
        else
            rm -rf "$NEW/$p"
            cp -a "$DEST/$p" "$NEW/$p"
        fi
    done
    # the new image's version and build time, not the kept ones
    for f in image-version build-time; do
        tar -xzf "$T" -C "$NEW" ./etc/e5/$f 2>/dev/null || true
    done
fi

if [ ! -f "$NEW/etc/e5/install.conf" ]; then
    echo "== settings from Debian"
    # nmcli -g escapes ":" and "\\" in what it prints
    get() { nmcli "$@" 2>/dev/null | sed 's/\\\(.\)/\1/g' || true; }
    apn=$(get -g gsm.apn connection show Mobile)
    ssid=$(get -g 802-11-wireless.ssid connection show Hotspot)
    key=$(get -s -g 802-11-wireless-security.psk connection show Hotspot)
    chan=$(get -g 802-11-wireless.channel connection show Hotspot)
    # single-quoted for the shell that sources the file
    q() { printf "'%s'" "$(printf '%s' "$1" | sed "s/'/'\\\\''/g")"; }
    mkdir -p "$NEW/etc/e5"
    umask 077
    {
        echo "# from the Debian image's NetworkManager profiles at install (openwrt/device-install.sh)"
        echo "E5_APN=$(q "$apn")"
        echo "E5_WIFI_SSID=$(q "${ssid:-E5-Linux}")"
        echo "E5_WIFI_KEY=$(q "$key")"
        echo "E5_WIFI_CHANNEL=$(q "${chan:-149}")"
    } > "$NEW/etc/e5/install.conf"
    umask 022
    echo "   apn=${apn:-(none)} ssid=${ssid:-E5-Linux} channel=${chan:-149} key=$([ -n "$key" ] && echo set || echo none)"
fi

mkdir -p "$NEW/etc/e5linux"
[ -f /etc/e5linux/default-boot ] && [ ! -f "$NEW/etc/e5linux/default-boot" ] &&
    cp /etc/e5linux/default-boot "$NEW/etc/e5linux/default-boot"
cp /run/e5linux/misc-bc-slot-a.bin /run/e5linux/misc-bc-slot-b-trial.bin "$NEW/etc/e5linux/" 2>/dev/null || true

echo "== swapping in"
rm -rf "$OLD"
[ -d "$DEST" ] && mv "$DEST" "$OLD"
mv "$NEW" "$DEST"
rm -rf "$OLD"
sync
echo "installed: $DEST ($(cat "$DEST/etc/e5/image-version" 2>/dev/null), $(du -sh "$DEST" | cut -f1))"

case "$MODE" in
    # the tree's own e5-os: this Debian may predate it
    --try)    sh "$DEST/opt/e5/e5-os" openwrt --once && sync && reboot ;;
    --switch) sh "$DEST/opt/e5/e5-os" openwrt && sync && reboot ;;
    '')       echo "boot it with: e5-os openwrt --once (one boot) or e5-os openwrt, then reboot" ;;
    *)        echo "unknown option $MODE" >&2; exit 2 ;;
esac
