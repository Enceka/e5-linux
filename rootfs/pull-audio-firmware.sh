#!/bin/bash
# Pull the audio DSP firmware and the VBC parameter set off Android, and build
# what the kernel-side profile loader needs, into the rootfs overlay.
#
# What this grabs and why (docs/FINDINGS.md section 24):
#
#   * the AGDSP image.  This device has what the ZTE F50 (mu300-linux) lacks:
#     real l_agdsp_a / l_agdsp_b partitions (mmcblk0p26/p27).  The image is
#     6 MiB with the header "SharkL5_AUDCP_2023Y_VER_3029", and audiocp_boot's
#     ldinfo on the live device reads back 0xafa00000 / 0x600000 -- the image
#     is exactly the reserved audiodsp-mem region, so it is the right binary
#     for this SoC, not a donor.  sprd_audcp_boot has no request_firmware():
#     userspace writes the image into /sys/devices/platform/audiocp_boot/agdsp
#     between "stop" and "start", which is what /opt/e5/e5-audio-dsp does.
#
#   * the native UMS9621 parameter XMLs from /odm/etc/audio_params/sprd.
#     On Android the proprietary audio HAL parses these and hands blobs to the
#     driver; on Linux the kernel loads them itself from /lib/firmware under
#     the bare names audio_structure, dsp_vbc and cvs, so they are converted
#     here with tools/vbc-profile (ported from mu300-linux).
#
# The pulled files are vendor blobs: .gitignore keeps them out of the repository.
#
# usage: rootfs/pull-audio-firmware.sh   (device in Android, adb working)
set -e
HERE="$(cd "$(dirname "$0")" && pwd)"
OVL="$HERE/overlay"
STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT

# This device's adbd restarts as root with `adb root`; fall back to the su -c
# path the older scripts use when that is not available.
if [ "$(adb shell id 2>/dev/null | tr -d '\r' | grep -c 'uid=0')" -ge 1 ]; then
    dev() { adb shell "$1" | tr -d '\r'; }
else
    dev() { adb shell "su -c '$1'" | tr -d '\r'; }
fi

echo "== AGDSP image (l_agdsp_a, 6 MiB) =="
IMG="$STAGE/l_agdsp_a.img"
dev 'dd if=/dev/block/by-name/l_agdsp_a of=/data/local/tmp/l_agdsp_a.img' >/dev/null
adb pull /data/local/tmp/l_agdsp_a.img "$IMG" >/dev/null
dev 'rm -f /data/local/tmp/l_agdsp_a.img' >/dev/null
sz=$(wc -c < "$IMG")
[ "$sz" -ge 6291456 ] || { echo "l_agdsp_a pulled short: $sz bytes" >&2; exit 1; }
# the header every build of this firmware carries; a donor image from another
# board would still pass this, so the size check above is the one that matters
head -c 11 "$IMG" | grep -q '^SharkL5_AUD' || { echo "l_agdsp_a has no SharkL5_AUDCP header" >&2; exit 1; }
echo "  l_agdsp_a.img: $sz bytes, $(head -c 27 "$IMG")"

echo "== VBC parameter XMLs (/odm/etc/audio_params/sprd) =="
for f in audio_structure.xml dsp_vbc.xml cvs.xml; do
    dev "cp -f /odm/etc/audio_params/sprd/$f /data/local/tmp/$f" >/dev/null
    adb pull "/data/local/tmp/$f" "$STAGE/$f" >/dev/null
    dev "rm -f /data/local/tmp/$f" >/dev/null
    echo "  $f ($(wc -c < "$STAGE/$f") bytes)"
done

echo "== converting the profile blobs =="
python3 "$HERE/../tools/vbc-profile/vbc-profile.py" \
    "$STAGE/dsp_vbc.xml" "$STAGE/audio_structure.xml" "$STAGE/cvs.xml" \
    -o "$STAGE"

echo "== install into the rootfs overlay =="
mkdir -p "$OVL/lib/firmware"
cp "$IMG" "$OVL/lib/firmware/l_agdsp_a.img"
cp "$STAGE/audio_structure" "$STAGE/dsp_vbc" "$STAGE/cvs" "$OVL/lib/firmware/"
ls -la "$OVL/lib/firmware" | grep -E 'l_agdsp|audio_structure|dsp_vbc|cvs'
echo "PULL-AUDIO-DONE"
