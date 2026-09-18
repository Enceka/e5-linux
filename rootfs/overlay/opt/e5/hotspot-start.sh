#!/bin/sh
# Wi-Fi hotspot on the E5 (2.4 GHz), NATed out through the baseband by e5-mobile-data.
#
# Needs, all in the image (docs/FINDINGS.md sections 20/20.1):
#   * /dev/block/by-name/wcnmodem faked with a loop device over the firmware;
#   * regulatory.db with *upstream* signatures in the initramfs, plus iw reg set CN;
#   * the clients' DNS: this box runs no resolver, so the DHCP lease must carry the
#     nameservers /etc/resolv.conf actually has (EmitDNS=no in the .network).  The
#     drop-in goes next to the base file in /etc -- a same-named file under
#     /run/systemd/network would shadow it and wlan0 would lose its address.
set -u
CONF=${1:-/etc/hostapd/e5.conf}
FW=/lib/firmware/wcnmodem.bin
if [ ! -e /dev/block/by-name/wcnmodem ] && [ -f "$FW" ]; then
    LO=$(losetup -f --show "$FW" 2>/dev/null)
    [ -n "$LO" ] && ln -sfn "$LO" /dev/block/by-name/wcnmodem
fi
rm -rf /run/systemd/network/20-e5-wlan0.network.d
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
iw reg get | head -1
iw dev wlan0 set type __ap
ip link set wlan0 up
hostapd -B "$CONF"
sleep 6
echo "hostapd: $(pgrep -c hostapd) process(es)"
iw dev wlan0 info | grep -E 'type|ssid|channel'
systemctl restart systemd-networkd
sleep 6
ip -br addr show wlan0
cat /etc/systemd/network/20-e5-wlan0.network.d/10-dns.conf
