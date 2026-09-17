#!/bin/bash
# Build the e5-linux root filesystem image.
#
#   rootfs/build-rootfs.sh fetch      download the Debian arm64 base
#   rootfs/build-rootfs.sh install    install the package set
#   rootfs/build-rootfs.sh configure  overlay, user, services
#   rootfs/build-rootfs.sh pack       write out/rootfs.ext4
#   rootfs/build-rootfs.sh all        all of the above
#
# The result is copied to the device as /data/e5linux/rootfs.ext4, which is where
# boot/init looks for it -- the E5 has no unallocated eMMC space, so the root
# filesystem is a loop file inside Android's /data rather than a partition.
set -e
HERE="$(cd "$(dirname "$0")" && pwd)"
TOP="$(cd "$HERE/.." && pwd)"
ROOT="$TOP/work/rootfs-build/rootfs"
OUT="$TOP/out"

stage_fetch() {
    if [ -x "$ROOT/bin/sh" ]; then
        echo "== base already present ($(du -sh "$ROOT" | cut -f1))"
    else
        mkdir -p "$ROOT"
        python3 "$HERE/fetch-debian-rootfs.py" trixie "$ROOT"
    fi
}

stage_install()   { bash "$HERE/install-packages.sh"; }
stage_configure() { bash "$HERE/configure-rootfs.sh"; }

stage_pack() {
    mkdir -p "$OUT"
    # The bind-mounted /dev nodes only exist inside the chroot session; outside it
    # they are the empty placeholder files, and systemd mounts devtmpfs over
    # /dev at boot anyway, so drop them rather than shipping 7 useless files.
    rm -f "$ROOT"/dev/null "$ROOT"/dev/zero "$ROOT"/dev/urandom "$ROOT"/dev/random \
          "$ROOT"/dev/tty "$ROOT"/dev/full "$ROOT"/dev/ptmx "$ROOT/binfmt_misc" 2>/dev/null || true
    rm -rf "$ROOT/proc/"* "$ROOT/sys/"* "$ROOT/run/"* 2>/dev/null || true

    used=$(du -sm "$ROOT" | cut -f1)
    size=$((used + used / 4 + 512))
    echo "== rootfs is ${used} MiB, image will be ${size} MiB"
    rm -f "$OUT/rootfs.ext4"
    truncate -s "${size}M" "$OUT/rootfs.ext4"
    mkfs.ext4 -F -q -L e5linux -d "$ROOT" "$OUT/rootfs.ext4"
    tune2fs -m 1 "$OUT/rootfs.ext4" >/dev/null
    e2fsck -f -y "$OUT/rootfs.ext4" >/dev/null 2>&1 || true
    ls -la "$OUT/rootfs.ext4"
    sha256sum "$OUT/rootfs.ext4"
}

case "${1:-all}" in
    fetch)     stage_fetch ;;
    install)   stage_install ;;
    configure) stage_configure ;;
    pack)      stage_pack ;;
    all)       stage_fetch; stage_install; stage_configure; stage_pack ;;
    *) echo "usage: $0 [fetch|install|configure|pack|all]" >&2; exit 2 ;;
esac
