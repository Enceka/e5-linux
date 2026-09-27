#!/bin/sh
# The next mainline trial, flashed from a running OpenWrt trial over the USB LAN: no Android round trip.
#
#   upstream/trial-from-openwrt.sh work/boot-mainline-openwrt.img [file:dest ...]
#
# Only boot_b and misc's bootloader_control are written, as by boot/flash-trial.sh; boot/init keeps the
# slot-b trial state it booted with in /run/e5linux, which re-arms the one-shot slot (tries=2, not successful:
# a kernel that does not come up falls back to Android).  Refused unless the device runs a mainline trial, i.e.
# the root filesystem is the copy (openwrt-mainline.ext4), so that what goes into the root (the modules of
# upstream/root-modules.txt, and extra file:dest pairs) never lands in the image in use.  The device pulls over HTTP from the host.
set -eu
IMG=$1; shift
BASE=${IMG%.img}
TOP=$(cd "$(dirname "$0")/.." && pwd)
HOST=${E5_HOST:-192.168.9.1}
PORT=${E5_HTTP_PORT:-8778}
dev() { python3 "$TOP/tools/e5-telnet.py" "($1) > /tmp/.o 2>&1" 'echo ==BEGIN==; cat /tmp/.o' 2>/dev/null |
        tr -d '\r' | sed -n '/^==BEGIN==$/,$p' | sed 1d | grep -v '^root@'; }
jget() { python3 -c "import json,sys;print(json.load(open(sys.argv[1]))[sys.argv[2]])" "$BASE.json" "$1"; }

HEAD=$(jget sha256_head56m)
MB=$(( $(jget persist_log_offset) / 1048576 ))
[ "$(dev 'cat /sys/block/loop0/loop/backing_file')" = /mnt/e5-data/e5linux/openwrt-mainline.ext4 ] ||
    { echo "$HOST is not running a mainline trial (root is not openwrt-mainline.ext4)" >&2; exit 1; }
BOOTB=$(dev 'for u in /sys/class/block/mmcblk*p*/uevent; do grep -qx PARTNAME=boot_b $u && echo /dev/$(basename $(dirname $u)); done')
MISC=$(dev 'cat /run/e5linux/misc-dev')
case "$BOOTB$MISC" in /dev/mmcblk*/dev/mmcblk*) ;; *) echo "boot_b/misc not found: '$BOOTB' '$MISC'" >&2; exit 1;; esac
LOCAL=$(ifconfig | awk '/inet 192\.168\.9\./{print $2; exit}')
[ -n "$LOCAL" ] || { echo "no address on the device's LAN" >&2; exit 1; }

S=$(mktemp -d)
trap 'kill $P 2>/dev/null; rm -rf "$S"' EXIT
dd if="$IMG" of="$S/head.img" bs=1M count=$MB 2>/dev/null
(cd "$S" && exec python3 -m http.server "$PORT" --bind "$LOCAL") >/dev/null 2>&1 & P=$!
sleep 2
# the modules OpenWrt loads from the root (upstream/root-modules.txt), for this kernel
"$TOP/upstream/root-modules.sh" >/dev/null
cp "$TOP/upstream/out/root-modules.tar" "$S/"
dev "wget -q -O - http://$LOCAL:$PORT/root-modules.tar | tar -xf - -C / && ls /lib/modules/$(cat "$TOP/upstream/out/kernel.release")/*/ | wc -l"
for fd in "$@"; do
    f=${fd%%:*} d=${fd#*:}
    cp "$f" "$S/$(basename "$f")"
    dev "mkdir -p $(dirname "$d") && wget -q -O $d http://$LOCAL:$PORT/$(basename "$f") && ls -l $d"
done
echo "== writing $(basename "$IMG") to $BOOTB"
dev "wget -q -O - http://$LOCAL:$PORT/head.img | dd of=$BOOTB bs=1M conv=fsync; sync" | tail -1
got=$(dev "dd if=$BOOTB bs=1M count=$MB 2>/dev/null | sha256sum" | cut -d' ' -f1)
[ "$got" = "$HEAD" ] || { echo "boot_b verify failed ($got): not armed; the next boot is whatever misc says" >&2; exit 1; }
echo "== boot_b ok; arming slot b (one-shot) and rebooting"
r=$(dev "dd if=/run/e5linux/misc-bc-slot-b-trial.bin of=$MISC bs=1 seek=2048 conv=notrunc 2>/dev/null; sync
         dd if=$MISC bs=1 skip=2048 count=32 2>/dev/null | cmp - /run/e5linux/misc-bc-slot-b-trial.bin && echo armed")
[ "$r" = armed ] || { echo "misc verify failed: $r" >&2; exit 1; }
dev '( (sleep 2; reboot) & )' >/dev/null
echo "== rebooting into the trial"
