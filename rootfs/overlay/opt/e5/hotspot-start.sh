#!/bin/sh
# Wi-Fi hotspot on the E5 (2.4 GHz), NATed out through the baseband by e5-mobile-data.
#
# Needs, all in the image (docs/FINDINGS.md sections 20-20.3):
#   * /dev/block/by-name/wcnmodem faked with a loop device over the firmware;
#   * regulatory.db with *upstream* signatures in the initramfs, plus iw reg set CN;
#   * dnsmasq for DHCP *and* DNS on wlan0 -- networkd's DHCPServer can hand out an
#     address but cannot answer queries, which is what "got an address, no internet"
#     turned out to be (etc/dnsmasq.d/e5-hotspot.conf advertises 192.168.9.1 and
#     forwards to the resolvers /etc/resolv.conf has).
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
systemctl restart dnsmasq
sleep 6
ip -br addr show wlan0
systemctl is-active dnsmasq
