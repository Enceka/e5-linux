#!/bin/sh
# Wi-Fi hotspot on the E5: 5 GHz, channel 149, 80 MHz (VHT80), DHCP+DNS from dnsmasq,
# NATed out through the baseband by e5-mobile-data.
#
# hostapd configures the 80 MHz channel itself.  What it needs from this script is only
# that wlan0 is in AP mode and that the regulatory domain is set: with a country and the
# upstream-signed regulatory.db in the initramfs the driver advertises "5725-5850 @
# 80 MHz" and hostapd reaches AP-ENABLED.  Without it, hostapd used to sit in HT_SCAN
# forever (that was never about the width -- see etc/hostapd/e5.conf).
set -u
CONF=${1:-/etc/hostapd/e5.conf}
FW=/lib/firmware/wcnmodem.bin
if [ ! -e /dev/block/by-name/wcnmodem ] && [ -f "$FW" ]; then
    LO=$(losetup -f --show "$FW" 2>/dev/null)
    [ -n "$LO" ] && ln -sfn "$LO" /dev/block/by-name/wcnmodem
fi
mkdir -p /etc/systemd/network/20-e5-wlan0.network.d
{
    echo "[Network]"
    awk '/^nameserver[ \t]/{print "DNS="$2}' /etc/resolv.conf | head -4
} > /etc/systemd/network/20-e5-wlan0.network.d/10-dns.conf
iw reg set CN 2>/dev/null || true
sleep 1
systemctl stop wpa_supplicant 2>/dev/null || true
pkill -f hostapd 2>/dev/null || true
sleep 1
ip link set wlan0 down 2>/dev/null || true
iw dev wlan0 set type __ap 2>/dev/null || true
ip link set wlan0 up
hostapd -B "$CONF"
sleep 8
echo "hostapd: $(pgrep -c hostapd) process(es)"
iw dev wlan0 info | grep -E 'type|ssid' | head -2
systemctl restart systemd-networkd
systemctl restart dnsmasq
sleep 5
ip -br addr show wlan0
