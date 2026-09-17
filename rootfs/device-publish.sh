#!/system/bin/sh
# Detach the build image and publish it as the root filesystem boot/init looks for.
set -e
ROOT=/data/e5build/root
SRC=/data/local/tmp/payload.ext4
DST=/data/e5linux/rootfs.ext4

echo "=== last cache entries ==="
rm -rf "$ROOT/var/cache/apt/archives/"* 2>/dev/null || true

echo "=== unmount ==="
for m in run dev/pts dev sys proc; do umount "$ROOT/$m" 2>/dev/null || true; done
umount "$ROOT" 2>/dev/null || echo "umount said: $?"
mount | grep e5build || echo "(nothing left mounted)"

echo "=== publish ==="
mkdir -p /data/e5linux
cp "$SRC" "$DST"
sync
ls -la "$DST"
echo "PUBLISH-DONE"
