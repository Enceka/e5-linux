#!/bin/sh
# If something leaves the E5's USB gadget unbound (a UDC write that fails, or VID/PID
# being changed while bound, which is exactly what happened once), the board loses its
# network, its serial console and adb all at once.  This runs early and puts the gadget
# back if the UDC is empty.
set -u
G=/sys/kernel/config/usb_gadget/linux
[ -d "$G" ] || exit 0
UDC=${ADBD_GADGET_UDC:-musb-hdrc.1.auto}
cur=$(cat "$G/UDC" 2>/dev/null)
if [ -n "$cur" ]; then
    echo "gadget bound to $cur"
    exit 0
fi
echo "gadget unbound -- rebinding to $UDC"
mkdir -p /dev/usb-ffs/adb
mountpoint -q /dev/usb-ffs/adb || mount -t functionfs adb /dev/usb-ffs/adb 2>/dev/null
echo "$UDC" > "$G/UDC" 2>/dev/null
sleep 2
echo "UDC=$(cat "$G/UDC")"
