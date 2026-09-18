#!/bin/sh
# Put ADB into the E5's Linux gadget.
#
# Two things learned the hard way (docs/FINDINGS.md section 21):
#   * the adbd package's own helper builds a *second* gadget and binds it, which costs
#     the network and the serial console -- so the ffs.adb function is added to our
#     gadget here instead, and adbd is run directly;
#   * never unbind/rebind the UDC to add it.  configfs accepts a new function in a
#     configuration that is already bound (the host sees a re-enumeration), whereas an
#     explicit "echo > UDC" followed by a rebind has twice left the gadget
#     half-configured: the ACM console still enumerates, the network never comes back and
#     adb never appears.  Recovery from that is a power cycle.
set -u
G=/sys/kernel/config/usb_gadget/linux
[ -d "$G" ] || { echo "no gadget $G"; exit 1; }

# Google's ids help hosts recognise the device, but they may only be written while the
# gadget is unbound -- if it is already bound, leave them alone.
if [ -z "$(cat "$G/UDC" 2>/dev/null)" ]; then
    echo 0x18d1 > "$G/idVendor"
    echo 0x4ee7 > "$G/idProduct"
fi
mkdir -p "$G/functions/ffs.adb"
ln -sfn "$G/functions/ffs.adb" "$G/configs/c.1/ffs.adb"
mkdir -p /dev/usb-ffs/adb
mountpoint -q /dev/usb-ffs/adb || mount -t functionfs adb /dev/usb-ffs/adb
sleep 1
echo "UDC=$(cat "$G/UDC") functions=$(ls "$G/functions/" | tr '\n' ' ')"
pkill -f platform-tools/adbd 2>/dev/null || true
nohup /usr/lib/android-sdk/platform-tools/adbd > /var/log/e5-adbd.log 2>&1 &
sleep 2
echo "adbd=$(pgrep -c adbd)"
