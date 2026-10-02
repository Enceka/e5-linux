#!/bin/bash
# Another kernel's root modules written into an OpenWrt image built before, without root or docker (debugfs):
# for a flash package whose kernel changed but whose image sources did not, on a host that cannot run
# openwrt/build-rootfs.sh (openwrt/make-flash-bundle.sh E5_IMAGE_FROM=).
#
#   openwrt/image-add-modules.sh IN.ext4.gz ROOT-MODULES.tar OUT.ext4.gz
#
# ROOT-MODULES.tar is upstream/root-modules.sh's (lib/modules/<release>/...); the image's other lib/modules
# directories are left, as build-rootfs.sh leaves the 5.15 one.
set -euo pipefail
IN=$1 MODS=$2 OUT=$3
T=$(mktemp -d)
trap 'rm -rf "$T"' EXIT
gzip -dc "$IN" > "$T/img"
mkdir "$T/m"
tar -xf "$MODS" -C "$T/m"
rel=$(ls "$T/m/lib/modules")
[ "$(echo "$rel" | wc -l)" = 1 ] || { echo "$MODS: not one release: $rel" >&2; exit 1; }
if debugfs -R "stat /lib/modules/$rel" "$T/img" 2>/dev/null | grep -q '^Inode:'; then
    echo "the image has /lib/modules/$rel already" >&2; exit 1
fi
(
    cd "$T/m"
    find "lib/modules/$rel" -type d | sort | while read -r d; do
        echo "mkdir /$d"; echo "sif /$d uid 0"; echo "sif /$d gid 0"; echo "sif /$d mode 040755"
    done
    find "lib/modules/$rel" -type f | sort | while read -r f; do
        echo "write $T/m/$f /$f"; echo "sif /$f uid 0"; echo "sif /$f gid 0"; echo "sif /$f mode 0100644"
    done
) > "$T/cmds"
debugfs -w -f "$T/cmds" "$T/img" > "$T/log" 2>&1
! grep -iE 'error|not found|cannot|failed' "$T/log" || { echo "debugfs failed (above)" >&2; exit 1; }
e2fsck -fn "$T/img" > "$T/fsck" 2>&1 || { cat "$T/fsck" >&2; exit 1; }
n=0
for d in $(cd "$T/m" && find "lib/modules/$rel" -type d); do
    n=$((n + $(debugfs -R "ls /$d" "$T/img" 2>/dev/null | { grep -o '[^ ]*\.ko' || true; } | wc -l)))
done
[ "$n" = "$(find "$T/m" -name '*.ko' | wc -l)" ] || { echo "$n modules in the image, not all of $MODS" >&2; exit 1; }
gzip -9 -c "$T/img" > "$OUT.part"
mv "$OUT.part" "$OUT"
echo "== $OUT: $n modules for $rel written in"
