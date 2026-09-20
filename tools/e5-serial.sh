#!/bin/bash
# Run one command on the E5 as root over its USB gadget serial console.
#
#     tools/e5-serial.sh 'ip -br addr show usb0; systemctl is-active systemd-networkd'
#
# The escape hatch for when the management LAN (or anything else on the device)
# is unreachable over IP: the same USB gadget that carries the NCM netdev the
# host sees as "E5 Linux USB Ethernet" also exposes a CDC-ACM port, macOS names
# it /dev/cu.usbmodemE5LINUX3, and serial-getty@ttyGS0 listens on it.  The
# device's root password is "root".  See docs/FINDINGS.md section 26.
#
# Nothing else may hold the port while this runs (screen, cu, a serial monitor).
set -u
HERE=$(cd "$(dirname "$0")" && pwd)
CMD=$1
[ -n "$CMD" ] || CMD='ip -br addr show usb0; systemctl is-active systemd-networkd; ip route'
exec /usr/bin/python3 "$HERE/e5-serial.py" -s '' -s 'root' -s 'root' -s "$CMD" --gap 4 --read 14
