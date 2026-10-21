#!/bin/bash
# Another kernel's root modules written into an OpenWrt image built before, without root or docker (debugfs):
# for a flash package whose kernel changed but whose image sources did not, on a host that cannot run
# openwrt/build-rootfs.sh (openwrt/make-flash-bundle.sh E5_IMAGE_FROM=).
#
#   openwrt/image-add-modules.sh IN.ext4.gz ROOT-MODULES.tar OUT.ext4.gz
#   E5_REPLACE_MODULES=1 replaces an existing tree for the same kernel release
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
[ "$(printf '%s\n' "$rel" | wc -l | tr -d ' ')" = 1 ] || { echo "$MODS: not one release: $rel" >&2; exit 1; }
if debugfs -R "stat /lib/modules/$rel" "$T/img" 2>/dev/null | grep -q '^Inode:'; then
    [ "${E5_REPLACE_MODULES:-0}" = 1 ] ||
        { echo "the image has /lib/modules/$rel already (set E5_REPLACE_MODULES=1 to replace it)" >&2; exit 1; }
    mkdir "$T/old"
    debugfs -R "rdump /lib/modules/$rel $T/old" "$T/img" >"$T/old.log" 2>&1
    (
        if [ -d "$T/old/lib/modules" ]; then cd "$T/old/lib/modules"; else cd "$T/old"; fi
        find "$rel" -depth \( -type f -o -type l \) | while read -r f; do
            echo "rm /lib/modules/$f"
        done
        find "$rel" -depth -type d | while read -r f; do
            echo "rmdir /lib/modules/$f"
        done
    ) > "$T/remove"
    debugfs -w -f "$T/remove" "$T/img" > "$T/remove.log" 2>&1
    ! grep -iE 'error|not found|cannot|failed' "$T/remove.log" || {
        cat "$T/remove.log" >&2; echo 'debugfs failed while removing the old modules' >&2; exit 1;
    }
    ! debugfs -R "stat /lib/modules/$rel" "$T/img" 2>/dev/null | grep -q '^Inode:' || {
        echo "could not remove the old /lib/modules/$rel completely" >&2; exit 1;
    }
fi
(
    cd "$T/m"
    find "lib/modules/$rel" -type d | sort | while read -r d; do
        echo "mkdir /$d"; echo "sif /$d uid 0"; echo "sif /$d gid 0"; echo "sif /$d mode 040755"
    done
    find "lib/modules/$rel" -type f | sort | while read -r f; do
        echo "write $T/m/$f /$f"; echo "sif /$f uid 0"; echo "sif /$f gid 0"; echo "sif /$f mode 0100644"
    done
    # The complete module package keeps hardware-service paths as aliases to
    # the flat .ko files required by OpenWrt's kmodloader.
    find "lib/modules/$rel" -type l | sort | while read -r f; do
        echo "symlink /$f $(readlink "$f")"
        echo "sif /$f uid 0"; echo "sif /$f gid 0"
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
