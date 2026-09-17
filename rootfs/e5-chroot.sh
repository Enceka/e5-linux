#!/bin/bash
# e5-chroot.sh -- run a command inside an arm64 root filesystem, unprivileged.
#
# There is no container runtime and no root on the build host, so this uses a
# user namespace plus the static qemu-aarch64.  Three things make it work:
#
#   * binfmt_misc is registered *inside* the namespace.  The kernel allows a
#     user namespace to mount its own binfmt_misc, and the registration covers
#     our children, so dpkg's #!/bin/sh maintainer scripts execute too.  Without
#     it only the top-level command would run and apt could not install anything.
#   * /proc is bind mounted (a fresh procfs mount is denied in a user namespace).
#   * /dev is built from single-file binds.  Binding the whole devtmpfs is
#     denied and mknod is filtered, but binding /dev/null, /dev/zero and friends
#     individually works.
#
# /sys is not available here.  dpkg and apt do not need it; anything that does
# has to run on the device instead.
#
# usage: e5-chroot.sh '<shell command>'
set -e
HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="${E5_ROOT:-$HERE/../work/rootfs-build/rootfs}"
QEMU="${QEMU_AARCH64:-$HERE/../work/qemu/e2/usr/bin/qemu-aarch64-static}"

[ -d "$ROOT" ] || { echo "e5-chroot: no rootfs at $ROOT" >&2; exit 1; }
[ -x "$QEMU" ] || { echo "e5-chroot: no qemu-aarch64-static at $QEMU" >&2; exit 1; }

cp -f "$QEMU" "$ROOT/qemu-aarch64-static"
mkdir -p "$ROOT/proc" "$ROOT/sys" "$ROOT/dev/pts" "$ROOT/dev/shm" "$ROOT/run"
for d in null zero urandom random tty full ptmx; do
    [ -e "$ROOT/dev/$d" ] || touch "$ROOT/dev/$d"
done
[ -f /etc/resolv.conf ] && cp -f /etc/resolv.conf "$ROOT/etc/resolv.conf"

export E5_ROOT="$ROOT" E5_QEMU="$QEMU" E5_INNER="$*"
exec unshare -Ur -m --propagation private /bin/bash -c '
set -e
mount --bind /proc "$E5_ROOT/proc"
for d in null zero urandom random tty full ptmx; do
    mount --bind "/dev/$d" "$E5_ROOT/dev/$d" 2>/dev/null || true
done
mount --bind /dev/pts "$E5_ROOT/dev/pts" 2>/dev/null || true

# arm64 ELF (e_machine == 0xb7, 64-bit LSB) -> qemu-aarch64-static
if mount -t binfmt_misc binfmt_misc /proc/sys/fs/binfmt_misc 2>/dev/null; then
    if [ -w /proc/sys/fs/binfmt_misc/register ]; then
        # The interpreter is named by its *host* path and registered with F, which
        # makes binfmt_misc open it now and keep the descriptor: the path is
        # validated against the host root at registration (naming the in-chroot
        # path fails with ENOENT) and stays usable after the chroot.
        printf "%s" ":qemu-aarch64:M::\x7fELF\x02\x01\x01\x00\x00\x00\x00\x00\x00\x00\x00\x00\x02\x00\xb7\x00:\xff\xff\xff\xff\xff\xff\xff\x00\xff\xff\xff\xff\xff\xff\xff\xff\xfe\xff\xff\xff:$E5_QEMU:F" > /proc/sys/fs/binfmt_misc/register
    fi
fi
chroot "$E5_ROOT" /bin/sh -c "$E5_INNER"
'
