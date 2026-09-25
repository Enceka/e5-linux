#!/bin/sh
# Wi-Fi hotspot on the E5: 5 GHz, channel 149, 80 MHz (VHT80), DHCP+DNS from dnsmasq,
# NATed out through the baseband (etc/e5/nat.nft).
#
# The AP is a port of br0, the one LAN it shares with the USB port (192.168.9.1/24,
# opt/e5/net-bridge.sh).  hostapd places wlan0 in the bridge itself (bridge=br0),
# and only if br0 exists when it starts -- otherwise it brings the AP up anyway and
# every client associates and never gets a lease.  An interface hostapd owns cannot
# be enslaved afterwards (silently refused), and iw cannot change the type of an
# enslaved one ("Interface wlan0 wasn't started").  So: wait for br0, take wlan0 out
# before the type/up dance, and do not call it a success unless the port is there.
#
# hostapd configures the 80 MHz channel itself.  What it needs from this script is only
# that wlan0 is in AP mode and that the regulatory domain is set: with a country and the
# upstream-signed regulatory.db in the initramfs the driver advertises "5725-5850 @
# 80 MHz" and hostapd reaches AP-ENABLED.  Without it, hostapd used to sit in HT_SCAN
# forever (that was never about the width -- see etc/hostapd/e5.conf).
set -u
CONF=${1:-/etc/hostapd/e5.conf}
# No loop device over /lib/firmware/wcnmodem.bin for the DT's
# /dev/block/by-name/wcnmodem.  The driver's partition reader is compiled out
# (FIRMWARE_PARTITION_DEBUG_EN is never defined), so request_firmware() is its
# only source -- and a read-write loop over the file makes that fail with
# ETXTBSY (-26).  After one failure the driver never asks the loader again, so
# a WCN power-on that landed after the losetup (Bluetooth's, usually) cost
# Wi-Fi for the whole boot: "buff is NULL", "marlin download timeout".
# (networkd no longer manages wlan0; the DNS drop-in older versions wrote is dead)
rm -rf /etc/systemd/network/20-e5-wlan0.network.d
# The WCN SDIO chip takes its time on a cold boot: on one boot wlan0 did not
# exist until ~100 s in, so "ip link set wlan0 up" failed with "RTNETLINK
# answers: No such device" while the service's own start timeout was already
# running.  Wait for the interface rather than race it.
for _ in $(seq 60); do
    [ -e /sys/class/net/wlan0 ] && break
    sleep 2
done
[ -e /sys/class/net/wlan0 ] || { echo "hotspot: wlan0 never appeared" >&2; exit 1; }
for _ in $(seq 60); do
    [ -e /sys/class/net/br0/brif/usb0 ] && break
    sleep 1
done
[ -e /sys/class/net/br0 ] || { echo "hotspot: br0 never appeared (e5-net-bridge)" >&2; exit 1; }
up() { pgrep -x hostapd >/dev/null && [ -e /sys/class/net/br0/brif/wlan0 ]; }
# Already up (this script also runs from e5-hotspot-retry.timer): leave it alone.
if up; then
    echo "hotspot: hostapd is already running, wlan0 in br0"
    exit 0
fi
iw reg set CN 2>/dev/null || true
sleep 1
systemctl stop wpa_supplicant 2>/dev/null || true
pkill -x hostapd 2>/dev/null || true
sleep 1
ip link set wlan0 nomaster 2>/dev/null || true
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
while ! up && [ "$attempt" -lt 4 ]; do
    attempt=$((attempt + 1))
    pkill -x hostapd 2>/dev/null || true
    sleep 3
    ip link set wlan0 nomaster 2>/dev/null || true
    ip link set wlan0 down 2>/dev/null || true
    iw dev wlan0 set type __ap 2>/dev/null || true
    ip link set wlan0 up 2>/dev/null || true
    hostapd -B "$CONF"
    sleep 8
    echo "hotspot: attempt $attempt, hostapd=$(pgrep -c hostapd), br0 ports: $(ls /sys/class/net/br0/brif | tr '\n' ' ')" >&2
done
echo "hostapd: $(pgrep -c hostapd) process(es)"
[ "$(pgrep -c hostapd)" != 0 ] || { echo "hotspot: hostapd is not running" >&2; exit 1; }
[ -e /sys/class/net/br0/brif/wlan0 ] || { echo "hotspot: wlan0 is not in br0, clients would get no lease" >&2; exit 1; }
# the router's addresses are on br0; the port itself carries none
sysctl -qw net.ipv6.conf.wlan0.disable_ipv6=1
iw reg get | head -2
iw dev wlan0 info | grep -E 'type|ssid' | head -2
# Bounded on purpose: these restart jobs queue behind other units, and during a
# boot with network-online.target still unreached the blocking form of this call
# never returned -- the script was killed by its own start timeout with hostapd
# already running, and the SIGKILL left wlan0 powered down.  The AP is up by
# now; DHCP must not be able to hang this script.
timeout 20 systemctl restart dnsmasq || true
/opt/e5/e5-ipv6-share
sleep 2
echo "br0 ports: $(ls /sys/class/net/br0/brif | tr '\n' ' ')"
ip -br addr show br0
