#!/system/bin/sh
# Build the e5-linux root filesystem on the device itself.
#
# The device is aarch64, so a chroot into an arm64 Debian tree runs at native
# speed -- which is the whole point.  Doing this install on the build host means
# emulating every dpkg maintainer script with qemu-user, and there apt's
# dependency resolver alone burned twenty minutes of CPU for ~1450 packages
# without unpacking a single one.  Here it is just apt/dpkg on eight ARM cores.
#
# The tree arrives as an ext4 image and is loop mounted, not extracted: Android's
# toybox tar turned Debian's usrmerge symlinks (/bin -> usr/bin, /lib -> usr/lib)
# into real directories full of duplicated files, and the chroot could then not
# execute anything.  A filesystem image preserves them exactly, and it doubles as
# the final rootfs.ext4.
#
# Needs root.  Run as:  adb shell su -c 'sh /data/local/tmp/device-build.sh'
set -e
# Android's PATH points at /system/bin and /apex/*, none of which exist inside the
# Debian tree, so every lookup in the chroot fails with "not found" -- including
# dpkg.  chroot inherits the environment, so fixing PATH here fixes it inside.
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin

IMG=/data/local/tmp/payload.ext4
ROOT=/data/e5build/root
LOG=/data/local/tmp/device-build.log

echo "=== selinux ==="
setenforce 0 2>/dev/null || true
getenforce 2>/dev/null

echo "=== loop mount ==="
mkdir -p "$ROOT"
umount "$ROOT" 2>/dev/null || true
if ! mount -t ext4 -o loop,rw "$IMG" "$ROOT" 2>/dev/null; then
    echo "mount -o loop failed, trying losetup"
    LOOP=$(losetup -f 2>/dev/null)
    echo "loop device: $LOOP"
    losetup "$LOOP" "$IMG"
    mount -t ext4 -o rw "$LOOP" "$ROOT"
fi
echo "mounted: $(mount | grep e5build | head -1)"

echo "=== kernel filesystems ==="
mkdir -p "$ROOT/proc" "$ROOT/sys" "$ROOT/dev/pts" "$ROOT/run"
mount -t proc proc "$ROOT/proc" 2>/dev/null || mount -o bind /proc "$ROOT/proc"
mount -t sysfs sysfs "$ROOT/sys" 2>/dev/null || mount -o bind /sys "$ROOT/sys"
mount -o bind /dev "$ROOT/dev"
mount -t devpts devpts "$ROOT/dev/pts" 2>/dev/null || true
mount -t tmpfs tmpfs "$ROOT/run" 2>/dev/null || true

echo "=== chroot sanity ==="
chroot "$ROOT" /bin/sh -c 'uname -m; head -1 /etc/os-release; dpkg --version | head -1; ls /var/cache/apt/archives/*.deb | wc -l'

echo "=== unpack (native, no apt resolver) ==="
chroot "$ROOT" /bin/sh -c 'dpkg --unpack /var/cache/apt/archives/*.deb 2>&1 | grep -vE "^(Selecting|Preparing|Unpacking)" | tail -40'
echo "unpacked: $(ls $ROOT/var/lib/dpkg/info/*.list 2>/dev/null | wc -l)"

echo "=== configure (native) ==="
chroot "$ROOT" /bin/sh -c 'export DEBIAN_FRONTEND=noninteractive; dpkg --force-confold --configure -a 2>&1 | tail -60'
echo "configured: $(grep -c "^Status: install ok installed" $ROOT/var/lib/dpkg/status 2>/dev/null)"

echo "=== apt dependency check ==="
chroot "$ROOT" /bin/sh -c 'DEBIAN_FRONTEND=noninteractive apt-get -o APT::Sandbox::User=root -f install -y 2>&1 | tail -25' || true

echo "=== ownership ==="
# The tree was packed on the build host by a non-root user, and mkfs.ext4 -d
# preserves those uid/gid numbers verbatim: a base system whose /bin/sh is
# owned by uid 1000 only works by luck.  On the device the chroot runs as real
# root, so give the build user's files to root (-xdev keeps the bind-mounted
# /proc /sys /dev out).
#
# Only the build user's: a blanket chown root:root also wiped every legitimate
# group (shadow, utmp, messagebus, ...) of what dpkg just installed as real root,
# and chown clears set-id bits -- su and passwd lost setuid, unix_chkpwd lost
# setgid shadow and the phosh lock screen accepted no password.  The base
# image's own ownership comes back from the list fetch-debian-rootfs.py took
# from its tar headers (e5-base-perms, run again at every boot by rootfs-fixups).
B=$(stat -c %u "$ROOT/etc/debian_version")
BG=$(stat -c %g "$ROOT/etc/debian_version")
if [ "$B" != 0 ]; then
    chroot "$ROOT" /bin/sh -c "find / -xdev -uid $B -exec chown -h root {} +" 2>&1 | tail -3 || true
fi
if [ "$BG" != 0 ]; then
    chroot "$ROOT" /bin/sh -c "find / -xdev -gid $BG -exec chgrp -h root {} +" 2>&1 | tail -3 || true
fi
echo "owner fixed: build uid $B gid $BG handed to root"
if [ -f "$ROOT/var/lib/e5linux/base-perms" ] && [ -f /data/local/tmp/overlay/opt/e5/e5-base-perms ]; then
    sh /data/local/tmp/overlay/opt/e5/e5-base-perms "$ROOT"
fi

echo "DEVICE-BUILD-DONE"
