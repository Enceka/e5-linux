#!/bin/sh
# One LAN for the USB port and the hotspot: br0, 192.168.9.1/24.
#
# usb0 (the NCM gadget) is enslaved here; wlan0 is not -- hostapd owns it and
# places it in the bridge itself (bridge=br0 in etc/hostapd/*.conf), which it
# only does when br0 already exists when it starts.  hotspot-start.sh waits for
# this unit's bridge, and checks afterwards that the port is really there.
#
# Built with ip, not systemd-networkd: networkd's rtnl requests time out on
# this SoC's sprd pseudo-interfaces, and a bridge it failed to finish was an
# empty shell -- no ports, no address, no DHCP (the 2026-09-21 attempt,
# FINDINGS 28).  networkd leaves usb0, wlan0 and br0 alone now
# (etc/systemd/network/*.network say Unmanaged=yes).
#
# br0 takes usb0's MAC (the gadget's fixed dev_addr), so a host that knew the
# device on usb0 keeps a valid ARP entry, and 192.168.77.1 stays on br0 as a
# second address: the initramfs hands the host a 192.168.77.x lease (its rescue
# mode keeps that subnet), and the host keeps it until it renews.
#
# Idempotent: re-running it re-asserts the addresses and the usb0 port.
#
# Never take usb0 down (ip link set usb0 down / up, or a rebuild that deletes
# it): the NCM function loses its framing with the host -- "configfs-gadget
# gadget: Wrong NTH SIGN" for every frame, the link dead until the cable is
# re-plugged or the device reboots (2026-09-26).  Enslaving it, and moving
# addresses on and off it, are harmless.
set -u
BR=br0

for _ in $(seq 30); do
    [ -e "/sys/class/net/$BR" ] && break
    ip link add name "$BR" type bridge stp_state 0 forward_delay 0 2>/dev/null
    sleep 1
done
[ -e "/sys/class/net/$BR" ] || { echo "net-bridge: $BR could not be created" >&2; exit 1; }

for _ in $(seq 30); do
    [ -e /sys/class/net/usb0 ] && break
    sleep 1
done
if [ -e /sys/class/net/usb0 ]; then
    mac=$(cat /sys/class/net/usb0/address)
    [ "$(cat /sys/class/net/$BR/address)" = "$mac" ] || ip link set "$BR" address "$mac"
fi

# The router's own IPv6 is on br0 (e5-ipv6-share); the ports carry none.
sysctl -qw "net.ipv6.conf.$BR.accept_ra=0"
ip link set "$BR" up
for a in 192.168.9.1/24 192.168.77.1/24; do
    ip -4 addr show dev "$BR" | grep -q " ${a} " || ip addr add "$a" dev "$BR" 2>/dev/null
done

if [ -e /sys/class/net/usb0 ]; then
    # the initramfs (and an older networkd config) put 192.168.77.1 on usb0 itself
    ip -4 addr flush dev usb0
    sysctl -qw net.ipv6.conf.usb0.disable_ipv6=1
    [ -e "/sys/class/net/$BR/brif/usb0" ] || ip link set usb0 master "$BR"
    ip link set usb0 up
fi

echo "net-bridge: ports=$(ls "/sys/class/net/$BR/brif/" 2>/dev/null | tr '\n' ' ')addr=$(ip -4 -o addr show dev "$BR" | awk '{printf "%s ", $4}')"
[ -e "/sys/class/net/$BR/brif/usb0" ] || { echo "net-bridge: usb0 is not in $BR" >&2; exit 1; }
