#!/bin/sh
# Wi-Fi hotspot on the E5: 5 GHz, channel 149, 80 MHz, DHCP+DNS from dnsmasq, NATed out
# through the baseband by e5-mobile-data.
#
# Order is the whole trick: hostapd stalls in HT_SCAN and never reaches AP-ENABLED if it
# has to configure an 80 MHz channel itself.  Setting the type and "channel 149 80MHZ" with
# iw *while the interface is down*, then bringing it up and starting hostapd, works.
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
iw dev wlan0 set channel 149 80MHZ 2>/dev/null || true
ip link set wlan0 up
hostapd -B "$CONF"
sleep 8
echo "hostapd: $(pgrep -c hostapd) process(es)"
iw dev wlan0 info | grep -E 'type|ssid' | head -2
systemctl restart systemd-networkd
systemctl restart dnsmasq
sleep 5
ip -br addr show wlan0
