#!/bin/sh
# Wi-Fi hotspot on the E5 (2.4 GHz), NATed out through the baseband by e5-mobile-data.
#
# Three things this needs, all now in the image (docs/FINDINGS.md section 20):
#   * the DT's /dev/block/by-name/wcnmodem, which this device does not have as a
#     partition -- a loop device over the firmware the image carries satisfies it;
#   * regulatory.db signed by *upstream* (sforshee/wens) keys in the initramfs -- Debian's
#     own-signed build is rejected by the vendor kernel as "malformed or signature is
#     missing/invalid", and without a database every channel is NO-IR;
#   * the country set explicitly, because cfg80211 starts in the world domain even when
#     the database loads.
set -u
CONF=${1:-/etc/hostapd/e5.conf}
FW=/lib/firmware/wcnmodem.bin
if [ ! -e /dev/block/by-name/wcnmodem ] && [ -f "$FW" ]; then
    LO=$(losetup -f --show "$FW" 2>/dev/null)
    [ -n "$LO" ] && ln -sfn "$LO" /dev/block/by-name/wcnmodem
fi
iw reg set CN 2>/dev/null || true
sleep 1
systemctl stop wpa_supplicant 2>/dev/null || true
pkill -f hostapd 2>/dev/null || true
sleep 1
iw reg get | head -1
iw dev wlan0 set type __ap
ip link set wlan0 up
hostapd -B "$CONF"
sleep 6
echo "hostapd: $(pgrep -c hostapd) process(es)"
iw dev wlan0 info | grep -E 'type|ssid|channel'
systemctl restart systemd-networkd
sleep 5
ip -br addr show wlan0
