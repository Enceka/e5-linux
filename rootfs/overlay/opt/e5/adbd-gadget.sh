#!/bin/sh
# Put ADB into the E5's Linux gadget.
#
# The Debian adbd package ships its own gadget helper, but that one builds a *separate*
# gadget ("g1") and binds it to the UDC -- which would displace our NCM+ACM gadget and
# cost the network and the serial console.  So the ffs.adb function is added to *our*
# gadget here instead, and adbd is run directly.
#
# Two details that bit: VID/PID must be set *before* the gadget is bound (changing them
# while bound leaves the gadget half-configured with no network and no adb), and the
# functionfs mount has to exist before adbd starts.
set -u
G=/sys/kernel/config/usb_gadget/linux
UDC_NOW=$(cat "$G/UDC" 2>/dev/null)
[ -e "$G" ] || { echo "no gadget $G"; exit 1; }

echo "" > "$G/UDC" 2>/dev/null || true
sleep 1
# Google's ids so the host's adb matches the device
echo 0x18d1 > "$G/idVendor"
echo 0x4ee7 > "$G/idProduct"
mkdir -p "$G/functions/ffs.adb"
ln -sfn "$G/functions/ffs.adb" "$G/configs/c.1/ffs.adb"
mkdir -p /dev/usb-ffs/adb
mountpoint -q /dev/usb-ffs/adb || mount -t functionfs adb /dev/usb-ffs/adb
echo ${UDC_NOW:-musb-hdrc.1.auto} > "$G/UDC"
sleep 3
echo "UDC=$(cat "$G/UDC") functions=$(ls "$G/functions/" | tr '\n' ' ')"
nohup /usr/lib/android-sdk/platform-tools/adbd > /var/log/e5-adbd.log 2>&1 &
sleep 2
echo "adbd=$(pgrep -c adbd)"
