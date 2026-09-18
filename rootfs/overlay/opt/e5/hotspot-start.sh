#!/bin/sh
# Wi-Fi hotspot on the E5.  hostapd needs the regulatory database cfg80211 loads from
# firmware, which the image now carries in the initramfs (docs/FINDINGS.md section 20):
# without it the domain is world/00, every channel is NO-IR, and hostapd dies with
# "Failed to set beacon parameters".  wlan0 must also be free of wpa_supplicant/
# NetworkManager (the overlay marks it unmanaged for that reason).
set -u
CONF=${1:-/etc/hostapd/e5.conf}
systemctl stop wpa_supplicant 2>/dev/null || true
pkill -f hostapd 2>/dev/null || true
sleep 1
iw reg get | head -1
iw dev wlan0 set type __ap
ip link set wlan0 up
hostapd -B "$CONF"
sleep 6
pgrep -c hostapd
iw dev wlan0 info | grep -E 'type|ssid|channel'
systemctl restart systemd-networkd
sleep 5
ip -br addr show wlan0
