#!/bin/sh
# Install out/rootfs.ext4 on the device as /data/e5linux/rootfs.ext4, which is
# where boot/init looks for the root filesystem (the E5 has no unpartitioned eMMC
# space, so the rootfs is a loop file inside Android's /data).
#
# Runs from rooted Android over adb -- the same side boot/flash-trial.sh needs --
# and does not touch the boot slots: flash the boot image separately.
#
#   rootfs/install-rootfs.sh out/rootfs.ext4
#
# The 8 GiB image is pushed in 1 GiB chunks and every chunk is size-checked before
# the next one: a single `adb push` of the whole file died with "failed to read
# copy response: EOF" after 2.4 GiB, and adb has no resume.  The chunk is appended
# on the device and removed again, so peak usage stays one chunk above the image.
set -eu
IMG=${1:-out/rootfs.ext4}
REMOTE=/data/local/tmp/payload.ext4
DST=/data/e5linux/rootfs.ext4
CHUNK_MB=${CHUNK_MB:-1024}

[ -f "$IMG" ] || { echo "no such image: $IMG" >&2; exit 1; }
size=$(stat -f %z "$IMG" 2>/dev/null || stat -c %s "$IMG")
want=$(shasum -a 256 "$IMG" 2>/dev/null | cut -d' ' -f1 || sha256sum "$IMG" | cut -d' ' -f1)
echo "image: $IMG ($size bytes, sha256 ${want%${want#????????}})"

su_do() { adb shell "su -c '$1'" | tr -d '\r'; }

[ "$(adb shell getprop ro.boot.verifiedbootstate | tr -d '\r')" = "orange" ] ||
    echo "warning: verifiedbootstate is not orange" >&2

# Refuse to start without room for the image plus one chunk.
avail=$(su_do 'df -k /data | tail -1' | awk '{print $4}')
need=$(( size / 1024 + CHUNK_MB * 1024 ))
if [ "${avail:-0}" -lt "$need" ]; then
    echo "not enough room in /data: have ${avail}K, need ${need}K" >&2
    echo "the previous rootfs ($DST) is the usual reason; remove it first" >&2
    exit 1
fi
if su_do "[ -f $DST ] && echo yes" | grep -q yes; then
    echo "removing the installed rootfs ($DST) to make room"
    su_do "rm -f $DST; sync"
fi

chunks=$(mktemp -d)
trap 'rm -rf "$chunks"' EXIT
split -b "${CHUNK_MB}m" "$IMG" "$chunks/p"
su_do "rm -f $REMOTE"

for f in "$chunks"/p*; do
    want_c=$(stat -f %z "$f" 2>/dev/null || stat -c %s "$f")
    adb push "$f" /data/local/tmp/ >/dev/null 2>&1 || true
    got=$(su_do "stat -c %s /data/local/tmp/$(basename "$f")")
    if [ "$got" != "$want_c" ]; then
        echo "$(basename "$f"): $got of $want_c bytes, retrying"
        adb push "$f" /data/local/tmp/ >/dev/null 2>&1 || true
        got=$(su_do "stat -c %s /data/local/tmp/$(basename "$f")")
    fi
    [ "$got" = "$want_c" ] || { echo "FAILED $(basename "$f")" >&2; exit 1; }
    su_do "cat /data/local/tmp/$(basename "$f") >> $REMOTE; rm -f /data/local/tmp/$(basename "$f")" >/dev/null
    echo "  $(basename "$f") ok ($got bytes)"
done

echo "verifying on the device..."
got=$(su_do "sha256sum $REMOTE" | awk '{print $1}')
[ "$got" = "$want" ] || { echo "HASH MISMATCH: $got != $want" >&2; exit 1; }

su_do "mkdir -p /data/e5linux; mv $REMOTE $DST; chown root:root $DST; chmod 644 $DST; sync"
echo "installed $DST ($(su_do "stat -c %s $DST") bytes)"
echo "next: boot/flash-trial.sh boot-linux-slotb.img   (or boot/android-boot-linux.sh to re-arm slot b)"
