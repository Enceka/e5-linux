#!/bin/sh
# Runs under Magisk BusyBox ash, after stock Android has recreated /data.
# Writes only the pre-created e5root block device; never changes GPT/userdata.
set -eu
dev=${1:?} sectors=${2:?} raw=${3:?} grow=${4:?} token=${5:?}
case "$dev" in /dev/block/mmcblk[0-9]p[0-9]*) ;; *) exit 2 ;; esac
node=${dev##*/}
case "$node" in *[!a-z0-9]*) exit 2 ;; esac
for n in "$sectors" "$raw"; do case "$n" in ''|0*|*[!0-9]*) exit 2 ;; esac; done
case "$grow" in 0|1) ;; *) exit 2 ;; esac
case "$token" in *[!0-9a-f]*) exit 2 ;; esac
[ "${#token}" = 32 ]
[ -b "$dev" ]
grep -qx PARTNAME=e5root /sys/class/block/$node/uevent
[ "$(cat /sys/class/block/$node/size)" = "$sectors" ]
[ -z "$(ls -A /sys/class/block/$node/holders)" ]
number=$(cat /sys/class/block/$node/dev)
for mounts in /proc/self/mountinfo /proc/1/mountinfo; do
    if awk -v n="$number" '$3 == n {yes=1} END {exit !yes}' "$mounts"; then
        echo 'root partition is mounted; refusing to write' >&2; exit 1
    fi
done
[ "$raw" -gt 0 ] && [ "$raw" -le "$((sectors * 512))" ]
lock=/data/local/tmp/e5-part-write.lock
mkdir "$lock" || { echo 'another installation or stale lock exists' >&2; exit 1; }
stage=
mounted=0 devbound=0 procbound=0
cleanup() {
    rc=$?; trap - EXIT
    [ "$mounted" = 0 ] || umount "$stage/view" || exit 1
    [ "$procbound" = 0 ] || umount "$stage/proc" || exit 1
    [ "$devbound" = 0 ] || umount "$stage/dev" || exit 1
    [ -z "$stage" ] || rm -rf "$stage"
    rmdir "$lock"
    exit "$rc"
}
trap cleanup EXIT
trap 'exit 1' INT TERM HUP
stage=$(mktemp -d /data/local/tmp/e5-part-tools.XXXXXX)
tar -xf /data/local/tmp/e5-ext4-tools.tar -C "$stage"
(cd "$stage" && sha256sum -c SHA256SUMS)
mkdir "$stage/dev" "$stage/proc" "$stage/etc" "$stage/view"
mount --bind /dev "$stage/dev"; devbound=1
mount --bind /proc "$stage/proc"; procbound=1
ln -s /proc/mounts "$stage/etc/mtab"
tools() { name=$1; shift; chroot "$stage" "/usr/sbin/$name" "$@"; }
image=/data/local/tmp/openwrt.ext4.gz
gzip -t "$image"
[ "$(gzip -dc "$image" | wc -c | tr -d ' ')" = "$raw" ]
want=$(gzip -dc "$image" | sha256sum | cut -d' ' -f1)
echo '1/4 writing root image'
gzip -dc "$image" > "$dev"
sync
[ "$(head -c "$raw" "$dev" | sha256sum | cut -d' ' -f1)" = "$want" ]
echo '2/4 checking and growing filesystem'
tools e2fsck -f -p "$dev" || { rc=$?; [ "$rc" = 1 ] || exit "$rc"; }
if [ "$grow" = 1 ]; then
    tools resize2fs "$dev" "$((sectors / 8))"
fi
tools e2fsck -f -n "$dev"
if [ "$grow" = 1 ]; then
    . "$stage/ext4-geometry.sh"
    ext4_verify_grown "$dev" "$sectors" || { echo 'filesystem geometry does not fill target' >&2; exit 1; }
fi
echo '3/4 installing device firmware and settings'
mount -t ext4 "$dev" "$stage/view"; mounted=1
tar -xf /data/local/tmp/e5-device-files.tar -C "$stage/view"
test -s "$stage/view/lib/firmware/wcnmodem.bin"
test -x "$stage/view/sbin/init"
test -s "$stage/view/etc/openwrt_release"
mkdir -p "$stage/view/etc/e5" "$stage/view/etc/e5linux"
echo linux > "$stage/view/etc/e5linux/default-boot"
cp /data/local/tmp/e5-install.conf "$stage/view/etc/e5/install.conf"
chmod 600 "$stage/view/etc/e5/install.conf"
rm -f "$stage/view/etc/e5/sd-root" "$stage/view/etc/e5/sd-trial"
printf 'e5root /dev/%s\n' "${node%p*}" > "$stage/view/etc/e5/part-root"
echo 1 > "$stage/view/etc/e5/part-trial"
echo "$token" > "$stage/view/etc/e5/part-install-token"
test -x "$stage/view/opt/e5/android/vendor/bin/modem_control"
chroot "$stage/view" /bin/busybox find /lib/firmware /opt/e5/android -type f \
    -exec /bin/busybox sha256sum '{}' \; > "$stage/root-files.sha256"
chroot "$stage/view" /bin/busybox sha256sum /sbin/init /etc/e5/install.conf \
    /etc/e5/part-root /etc/e5/part-trial /etc/e5/part-install-token >> "$stage/root-files.sha256"
test -s "$stage/root-files.sha256"
sync
umount "$stage/view"; mounted=0
blockdev --flushbufs "$dev"
echo '4/4 verifying installed root read-only'
mount -t ext4 -o ro,noload "$dev" "$stage/view"; mounted=1
chroot "$stage/view" /bin/busybox sha256sum -c < "$stage/root-files.sha256"
test "$(cat "$stage/view/etc/e5/part-install-token")" = "$token"
test -s "$stage/view/lib/firmware/wcnmodem.bin"
test -x "$stage/view/sbin/init"
umount "$stage/view"; mounted=0
echo "ROOT-VERIFIED $dev filesystem_blocks=$(od -An -tu4 -j 1028 -N 4 "$dev")"
