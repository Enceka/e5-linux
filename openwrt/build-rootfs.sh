#!/bin/bash
# Build the E5's OpenWrt tree: out/openwrt/e5-openwrt-<version>-rootfs.tar.gz
#
#   openwrt/build-modemmanager.sh      (once, and after a ModemManager patch changes)
#   openwrt/build-rootfs.sh
#
# The tree is OpenWrt's own armsr/armv8 root filesystem (arm64, musl) with the
# E5's parts added -- no kernel, no kmods: the E5 boots its vendor kernel from
# slot b's boot image, and the initramfs starts this tree from a directory of
# the Debian root image (/openwrt, see README.md).  Added:
#
#  * packages from OpenWrt's repository: the access point (wpad-basic-mbedtls,
#    wifi-scripts, iw), bash, util-linux mount, ip-full, LuCI's ModemManager
#    protocol; and ModemManager itself from out/openwrt/, built with the unisoc
#    plugin by build-modemmanager.sh;
#  * openwrt/overlay/: the procd services for the hardware, the first-boot
#    configuration, the ModemManager glue, the sysupgrade guard;
#  * from the Debian image's overlay (rootfs/overlay/opt/e5): the scripts both
#    systems share -- the baseband's vendor chroot, the regulatory database,
#    the USB gadget guard, e5-next-boot, e5-os, e5-at;
#  * a full static busybox (the boot image's own) for the applets OpenWrt's
#    leaves out, and logdw (openwrt/src/logdw.c) for the vendor chroot's log.
#
# The firmware and the Android vendor subset are not in the tarball: they are
# the Debian root's, bound in at boot (overlay/lib/preinit/05_e5_debian_root).
# Needs Docker with arm64 (native on Apple silicon).
set -euo pipefail
VER=${E5_WRT_VER:-25.12.5}
HERE="$(cd "$(dirname "$0")" && pwd)"
TOP="$(cd "$HERE/.." && pwd)"
WORK="$TOP/work/openwrt"
OUT="$TOP/out/openwrt"
URL=https://downloads.openwrt.org/releases/$VER/targets/armsr/armv8
TARBALL=openwrt-$VER-armsr-armv8-rootfs.tar.gz
BUSYBOX=${E5_BUSYBOX:-$TOP/work/busybox/ext/usr/bin/busybox}
NAME=e5-openwrt-$VER-rootfs.tar.gz
mkdir -p "$WORK" "$OUT"

ls "$OUT"/modemmanager-1*.apk >/dev/null 2>&1 || {
    echo "no ModemManager package in $OUT -- run openwrt/build-modemmanager.sh first" >&2; exit 1; }
[ -x "$BUSYBOX" ] || { echo "no static busybox at $BUSYBOX (E5_BUSYBOX=...)" >&2; exit 1; }

if [ ! -f "$WORK/$TARBALL" ]; then
    curl -fL -o "$WORK/$TARBALL.part" "$URL/$TARBALL"
    mv "$WORK/$TARBALL.part" "$WORK/$TARBALL"
fi
want=$(curl -fsSL "$URL/sha256sums" | sed -n "s/^\([0-9a-f]*\) \*$TARBALL$/\1/p")
have=$(shasum -a 256 "$WORK/$TARBALL" 2>/dev/null || sha256sum "$WORK/$TARBALL")
[ -n "$want" ] && [ "${have%% *}" = "$want" ] || { echo "checksum mismatch for $TARBALL" >&2; exit 1; }

# logdw, static: OpenWrt has no compiler of its own
docker run --rm --platform linux/arm64 -v "$HERE/src":/src:ro -v "$WORK":/out alpine:3.22 \
    sh -euc 'apk add -q gcc musl-dev >/dev/null && gcc -static -Os -s -o /out/logdw /src/logdw.c'

docker import --platform linux/arm64 "$WORK/$TARBALL" e5-openwrt-base:$VER >/dev/null
VERSION=$(git -C "$TOP" describe --always --dirty 2>/dev/null || echo dev)

docker run --rm --platform linux/arm64 \
    -v "$HERE/overlay":/in/overlay:ro -v "$TOP/rootfs/overlay/opt/e5":/in/opt-e5:ro \
    -v "$OUT":/in/apk:ro -v "$BUSYBOX":/in/busybox:ro -v "$WORK/logdw":/in/logdw:ro \
    -v "$OUT":/out -e NAME="$NAME" -e VERSION="$VERSION" \
    e5-openwrt-base:$VER /bin/sh -euc '
mkdir -p /var/lock /var/run /tmp
apk update >/dev/null
# ModemManager first, from its local file (unsigned): its release is above the
# repository one, so what depends on it takes this one and apk upgrade keeps it
apk add --allow-untrusted /in/apk/modemmanager-1*.apk /in/apk/modemmanager-rpcd-*.apk >/dev/null
apk add wpad-basic-mbedtls wifi-scripts iwinfo iw ip-full bash mount-utils luci-proto-modemmanager >/dev/null
# attended sysupgrade flashes whole-disk images: that would overwrite the eMMC
apk del luci-app-attendedsysupgrade attendedsysupgrade-common owut >/dev/null 2>&1 || true
# (apk info <name> describes the repository'"'"'s package; the installed one is here)
echo "modemmanager $(sed -n "/^P:modemmanager$/{n;s/^V://p}" /lib/apk/db/installed) installed"

R=/build/root; mkdir -p $R
# the live filesystem of this container (OpenWrt and the packages), without the runtime mounts
for e in /*; do
    case "$e" in /proc|/sys|/dev|/build|/in|/out|/tmp) continue ;; esac
    cp -a "$e" $R/
done
mkdir -p $R/proc $R/sys $R/dev $R/tmp $R/mnt/e5-disk $R/opt/e5/android $R/opt/e5/bin $R/etc/e5linux
# Docker bind-mounts these into the container, so the copy has the build host versions
ln -sf /tmp/resolv.conf $R/etc/resolv.conf
printf "127.0.0.1\tlocalhost\n\n::1\tlocalhost ip6-localhost ip6-loopback\nff02::1\tip6-allnodes\nff02::2\tip6-allrouters\n" > $R/etc/hosts
printf "E5\n" > $R/etc/hostname

cp -a /in/overlay/. $R/
for f in vendor-start.sh android-run node-perms.sh regdb-load.sh gadget-guard.sh e5-next-boot e5-os e5-at; do
    cp /in/opt-e5/$f $R/opt/e5/$f; chmod 755 $R/opt/e5/$f
done
cp /in/logdw $R/opt/e5/bin/logdw && chmod 755 $R/opt/e5/bin/logdw
cp /in/busybox $R/opt/e5/bin/busybox && chmod 755 $R/opt/e5/bin/busybox
# the applets the shared scripts use that OpenWrt'"'"'s busybox leaves out --
# the ones the full busybox really has
have=$(/in/busybox --list)
for a in mountpoint timeout seq stat chroot od losetup telnetd cut tr basename dirname \
         find xargs head tail wc sort uniq awk readlink; do
    chroot $R /bin/sh -c "command -v $a" >/dev/null 2>&1 && continue
    if printf "%s\n" "$have" | grep -qx "$a"; then
        ln -sf /opt/e5/bin/busybox $R/usr/bin/$a; echo "busybox applet: $a"
    else
        echo "WARNING: no $a in OpenWrt or the static busybox"
    fi
done
# device nodes as udev makes them on Debian: 0660 root:root unless a rule
# says otherwise.  procd creates the rest 0600, and the vendor daemons, which
# drop to uid system but keep group root, then cannot open theirs --
# modem_control failed on /dev/chsys and the CP never booted.
sed -i "s|\[ \"makedev\", \"/dev/%DEVNAME%\", \"0600\" \]|[ \"makedev\", \"/dev/%DEVNAME%\", \"0660\" ]|" $R/etc/hotplug.json
grep -q "\"/dev/%DEVNAME%\", \"0660\" \]" $R/etc/hotplug.json || { echo "hotplug.json: default node mode not found" >&2; exit 1; }
for c in e5-os e5-next-boot e5-at; do ln -sf /opt/e5/$c $R/usr/bin/$c; done
# the USB serial console: in the image, not at first boot -- procd reads
# inittab before uci-defaults run, and the console is the way in when the
# network is not up
grep -q "^ttyGS0:" $R/etc/inittab || echo "ttyGS0::askfirst:/usr/libexec/login.sh" >> $R/etc/inittab
mv $R/sbin/sysupgrade $R/sbin/sysupgrade.openwrt
mv $R/usr/libexec/e5-sysupgrade $R/sbin/sysupgrade
# enable the services ("rc.common enable" wants ubus, which is not running here)
for s in e5-hw e5-vendor e5-sipc-wwan e5-telnetd e5-boot-ok dbus modemmanager; do
    n=$(sed -n "s/^START=//p" $R/etc/init.d/$s)
    ln -sf ../init.d/$s $R/etc/rc.d/S$n$s
done
# no kernel of its own
rm -rf $R/lib/modules/* $R/boot
mkdir -p $R/etc/e5 && printf "%s\n" "$VERSION" > $R/etc/e5/image-version
cd $R && tar -czf /out/$NAME .
ls -la /out/$NAME
'
