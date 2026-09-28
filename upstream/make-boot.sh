#!/bin/bash
# A slot-b boot image of the mainline kernel (upstream/build.sh's out/Image.lk) with a bring-up init:
#
#   upstream/make-boot.sh [init] [out.img]     (default: upstream/init-bringup, work/boot-mainline.img)
#   boot/flash-trial.sh work/boot-mainline.img (from Android: one trial boot, then back to Android)
#   tools/collect-logs.sh                      (the pstore record, back in Android)
#
# The kernel's command line is its own (CONFIG_CMDLINE_FORCE).  The modules of upstream/module-order.txt come
# from out/modules (boot/init loads them in that order; wcn_bsp.ko after the device's WCN firmware); the
# probe init gets none.  E5_UPSTREAM_OUT: another build's output (default upstream/out; a flash package's kernel
# is upstream/out-release, E5_RELEASE=1 upstream/build.sh).
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
TOP="$(cd "$HERE/.." && pwd)"
KOUT=${E5_UPSTREAM_OUT:-$HERE/out}
INIT=${1:-$HERE/init-bringup}
OUT=${2:-$TOP/work/boot-mainline.img}
[ -f "$KOUT/Image.lk" ] || { echo "no $KOUT/Image.lk: run upstream/build.sh" >&2; exit 1; }
empty=$(mktemp)
trap 'rm -f "$empty"' EXIT
order=$empty
[ "$(basename "$INIT")" = init-bringup ] || order=$HERE/module-order.txt
python3 "$TOP/boot/build-boot-image.py" --stock-boot "$TOP/dumps/boot_b.img" --misc-head "$TOP/dumps/misc-head.bin" \
    --kernel "$KOUT/Image.lk" --modules "$KOUT/modules" --module-order "$order" --init "$INIT" \
    --busybox "$TOP/work/busybox/ext/usr/bin/busybox" --cmdline "" --out "$OUT" | tail -2
echo "$OUT: $(cat "$KOUT/kernel.release"), init $(basename "$INIT"), $(grep -c . "$order") modules"
