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
# The WCN SDIO chip takes its time on a cold boot: on one boot wlan0 did not
# exist until ~100 s in, so "ip link set wlan0 up" failed with "RTNETLINK
# answers: No such device" while the service's own start timeout was already
# running.  Wait for the interface rather than race it.
for _ in $(seq 60); do
    [ -e /sys/class/net/wlan0 ] && break
    sleep 2
done
[ -e /sys/class/net/wlan0 ] || { echo "hotspot: wlan0 never appeared" >&2; exit 1; }
# Already up (this script also runs from e5-hotspot-retry.timer): leave it alone.
if pgrep -x hostapd >/dev/null; then
    echo "hotspot: hostapd is already running"
    exit 0
fi
iw reg set CN 2>/dev/null || true
sleep 1
systemctl stop wpa_supplicant 2>/dev/null || true
pkill -f hostapd 2>/dev/null || true
sleep 1
ip link set wlan0 down 2>/dev/null || true
iw dev wlan0 set type __ap 2>/dev/null || true
ip link set wlan0 up
# The WCN firmware can refuse the first beacon right after a boot ("Failed to
# set beacon parameters", or "sprd-wlan: failed to power on WCN!" when the chip
# is still settling); re-doing the type/up dance has always worked, and on some
# boots it takes more than one round.  Do not report success when the AP did not
# come up -- e5-hotspot-retry.timer tries again later, and a green unit with no
# hotspot is how this stayed invisible for days.
attempt=0
while [ "$(pgrep -c hostapd)" = 0 ] && [ "$attempt" -lt 4 ]; do
    attempt=$((attempt + 1))
    pkill -f hostapd 2>/dev/null || true
    sleep 3
    ip link set wlan0 down 2>/dev/null || true
    iw dev wlan0 set type __ap 2>/dev/null || true
    ip link set wlan0 up 2>/dev/null || true
    hostapd -B "$CONF"
    sleep 8
    echo "hotspot: attempt $attempt, hostapd=$(pgrep -c hostapd)" >&2
done
echo "hostapd: $(pgrep -c hostapd) process(es)"
[ "$(pgrep -c hostapd)" != 0 ] || { echo "hotspot: hostapd is not running" >&2; exit 1; }
iw reg get | head -2
iw dev wlan0 info | grep -E 'type|ssid' | head -2
# Bounded on purpose: these restart jobs queue behind other units, and during a
# boot with network-online.target still unreached the blocking form of this call
# never returned -- the script was killed by its own start timeout with hostapd
# already running, and the SIGKILL left wlan0 powered down.  The AP is up by
# now; DHCP must not be able to hang this script.
timeout 20 systemctl restart systemd-networkd || true
timeout 20 systemctl restart dnsmasq || true
sleep 5
ip -br addr show wlan0
