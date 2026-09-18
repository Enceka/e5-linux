#!/bin/sh
# If something leaves the E5's USB gadget unbound, the board loses its network and its
# serial console at once.  This runs early and rebinds to the UDC if it is empty.
set -u
G=/sys/kernel/config/usb_gadget/linux
[ -d "$G" ] || exit 0
UDC=${E5_GADGET_UDC:-musb-hdrc.1.auto}
cur=$(cat "$G/UDC" 2>/dev/null)
if [ -n "$cur" ]; then
    echo "gadget bound to $cur"
    exit 0
fi
echo "gadget unbound -- rebinding to $UDC"
echo "$UDC" > "$G/UDC" 2>/dev/null
sleep 2
echo "UDC=$(cat "$G/UDC")"
