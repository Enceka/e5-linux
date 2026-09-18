#!/bin/sh
# Put ADB into the E5's Linux gadget, in the only order that works.
#
# FunctionFS demands a daemon that has already opened ep0 and written its descriptors
# when the gadget is bound, which rules out both obvious approaches:
#   * creating ffs.adb in the initramfs and binding there fails the composite bind
#     outright -- the board is then left with no USB at all (no network, no console);
#   * adding ffs.adb to an already-bound configuration is accepted, but musb does not
#     refresh the descriptors, so the host keeps seeing NCM+ACM and adb never appears.
# Hence: create the function, start adbd (it opens ep0 and writes the descriptors), and
# only then rebind the UDC.  adbd stays alive across the rebind, which is what makes it
# succeed.
set -u
G=/sys/kernel/config/usb_gadget/linux
ADBD=/usr/lib/android-sdk/platform-tools/adbd
[ -d "$G" ] || { echo "no gadget $G"; exit 1; }

mkdir -p "$G/functions/ffs.adb"
ln -sfn "$G/functions/ffs.adb" "$G/configs/c.1/f3"
mkdir -p /dev/usb-ffs/adb
mountpoint -q /dev/usb-ffs/adb || mount -t functionfs adb /dev/usb-ffs/adb

pkill -f platform-tools/adbd 2>/dev/null || true
nohup "$ADBD" > /var/log/e5-adbd.log 2>&1 &
for n in $(seq 1 20); do
    [ -e /dev/usb-ffs/adb/ep0 ] && break
    sleep 0.5
done
echo "adbd=$(pgrep -c adbd) ep0=$([ -e /dev/usb-ffs/adb/ep0 ] && echo yes || echo no)"

# Google's ids are only writable while unbound, and only help hosts recognise the device
cur=$(cat "$G/UDC" 2>/dev/null)
echo "" > "$G/UDC" 2>/dev/null || true
sleep 1
[ -z "$cur" ] && { echo 0x18d1 > "$G/idVendor"; echo 0x4ee7 > "$G/idProduct"; }
echo "${cur:-musb-hdrc.1.auto}" > "$G/UDC"
sleep 3
if [ -z "$(cat "$G/UDC" 2>/dev/null)" ]; then
    echo "rebind did not take -- retrying"
    echo musb-hdrc.1.auto > "$G/UDC"
    sleep 3
fi
echo "UDC=$(cat "$G/UDC") functions=$(ls "$G/functions/" | tr '\n' ' ')"
