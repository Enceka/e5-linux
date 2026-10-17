#!/system/bin/sh
# Shared TF target and offline filesystem growth for desktop and Magisk installs.
# Never modify the partition table. Only an explicitly selected TF target is erased.
set -eu
tf_fail() { echo "TF: $*" >&2; exit 1; }
case ${1:-} in
    target)
        disk=${2:?TF disk}; node=${disk##*/}
        echo "$node" | grep -Eq '^mmcblk[0-9]+$' || tf_fail 'invalid TF disk'
        emmc=$(readlink -f /dev/block/by-name/misc)
        emmc=${emmc##*/}; emmc=${emmc%p*}
        echo "$emmc" | grep -Eq '^mmcblk[0-9]+$' || tf_fail 'cannot identify internal storage'
        [ "$node" != "$emmc" ] || tf_fail 'refusing internal storage'
        [ "$(cat /sys/class/block/$node/device/type)" = SD ] || tf_fail 'not an SD card'
        [ -b "$disk" ] && [ "$(cat /sys/class/block/$node/ro)" = 0 ] || tf_fail 'missing/read-only TF disk'
        if [ -b "${disk}p1" ]; then
            echo "${disk}p1"
        else
            # A missing p1 does not imply an unpartitioned disk: never overwrite
            # a card containing p2 or later partitions through its whole device.
            for p in /sys/class/block/"$node"p*; do
                [ ! -e "$p" ] || tf_fail 'partitions exist but p1 is missing'
            done
            echo "$disk"
        fi
        ;;
    grow)
        dev=${2:?target}; archive=${3:?ext4 tools}; work=${4:?temporary directory}
        [ -b "$dev" ] || tf_fail 'missing target'
        mkdir "$work"
        tar -xf "$archive" -C "$work"
        (cd "$work" && sha256sum -c SHA256SUMS) || tf_fail 'ext4 tools checksum'
        loader=$work/lib/ld-musl-aarch64.so.1
        libs=$work/lib:$work/usr/lib
        rc=0
        "$loader" --library-path "$libs" "$work/usr/sbin/e2fsck" -pf "$dev" || rc=$?
        case $rc in 0|1) ;; *) tf_fail 'filesystem check failed';; esac
        "$loader" --library-path "$libs" "$work/usr/sbin/resize2fs" "$dev"
        "$loader" --library-path "$libs" "$work/usr/sbin/e2fsck" -fn "$dev"
        # Keep geometry checks shared with the internal-partition installer.
        sectors=$(blockdev --getsz "$dev")
        . "$work/ext4-geometry.sh"
        ext4_verify_grown "$dev" "$sectors" || tf_fail 'filesystem geometry does not fill target'
        ;;
    *) tf_fail 'expected target or grow';;
esac
