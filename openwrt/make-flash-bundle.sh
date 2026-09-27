#!/bin/bash
# Build the flash package for other people's E5s:
# out/openwrt/e5-openwrt-flash-<version>-<git>.tar.gz, unpacked and run as
# ./flash.sh (openwrt/bundle/README.md is its manual).
#
#   openwrt/make-flash-bundle.sh
#
# What goes in, and what does not:
#
#  * the generic OpenWrt image (openwrt/build-rootfs.sh with E5_STANDALONE=1
#    E5_DEVICE_FILES=0, built here when out/openwrt has none): none of this
#    device's files -- no vendor firmware, no Android vendor subset, which are
#    proprietary and carry the unit's identity (BT address, serial number);
#  * a boot image without the Debian overlay (boot/build-boot-image.py with no
#    --overlay): the overlay is Debian's, and holds this device's firmware,
#    MAC addresses and hotspot profile;
#  * the scripts that pull the recipient's own firmware and vendor files off
#    their Android (rootfs/pull-*-firmware.sh, extract-android-vendor.sh, and
#    the tools they need); boot/init unpacks those into the image at boot
#    (e5linux/device-files.tar);
#  * the device-side installers for updates over the USB LAN.
#
# Both images are checked for the files that must not be there before the
# package is written.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
TOP="$(cd "$HERE/.." && pwd)"
VER=${E5_WRT_VER:-25.12.5}
OUT="$TOP/out/openwrt"
WORK="$TOP/work/openwrt"
IMG="$OUT/e5-openwrt-$VER-generic.ext4.gz"
KERNEL=${E5_KERNEL:-$TOP/work/Image-bt2}
GIT=$(git -C "$TOP" describe --always --dirty 2>/dev/null || echo dev)
NAME=e5-openwrt-flash-$VER-$GIT

if [ ! -f "$IMG" ] || [ -n "${E5_REBUILD:-}" ]; then
    E5_STANDALONE=1 E5_DEVICE_FILES=0 bash "$HERE/build-rootfs.sh"
fi
echo "== checking the image for device files"
bad=$(tar -tzf "$WORK/e5-openwrt-$VER-generic-rootfs.tar.gz" |
      grep -E 'lib/firmware/(wcnmodem|gnssmodem|l_agdsp|wifi_board|sprd/)|opt/e5/android/.|etc/e5/install\.conf|mnt/vendor/.' || true)
[ -z "$bad" ] || { echo "the generic image carries device files:" >&2; echo "$bad" | head >&2; exit 1; }

echo "== boot image without the overlay"
BOOT="$TOP/work/boot-linux-slotb-bundle"
python3 "$TOP/boot/build-boot-image.py" --stock-boot "$TOP/dumps/boot_b.img" \
    --misc-head "$TOP/dumps/misc-head.bin" --kernel "$KERNEL" --modules "$TOP/out_modules" \
    --busybox "$TOP/work/busybox/ext/usr/bin/busybox" --out "$BOOT.img" | tail -1
[ "$(python3 -c "import json,sys;print(json.load(open(sys.argv[1]))['overlay_files'])" "$BOOT.json")" = 0 ] ||
    { echo "the boot image has an overlay" >&2; exit 1; }
# the kernel and the image's modem modules have to be one build
rel=$(strings "$TOP/out_linux/drivers/net/wwan/wwan.ko" | sed -n 's/^vermagic=\([^ ]*\).*/\1/p' | head -1)
# (not "strings | grep -q": grep leaves early, and pipefail counts the SIGPIPE)
grep -q "Linux version $rel " < <(strings "$KERNEL") ||
    { echo "the kernel ($KERNEL) is not the build of out_linux ($rel)" >&2; exit 1; }

S=$(mktemp -d)
trap 'rm -rf "$S"' EXIT
P=$S/$NAME
mkdir -p "$P/files" "$P/scripts/rootfs" "$P/scripts/tools"
cp "$HERE/bundle/flash.sh" "$P/" && chmod 755 "$P/flash.sh"
cp "$HERE/bundle/README.md" "$HERE/bundle/README.zh-CN.md" "$P/"
cp "$TOP/LICENSE" "$P/LICENSE"
cp "$IMG" "$P/files/openwrt.ext4.gz"
cp "$BOOT.img" "$P/files/boot.img"
cp "$BOOT.json" "$P/files/boot.json"
cp "$BOOT.misc-slot-b-trial.bin" "$P/files/boot-misc-slot-b.bin"
cp "$HERE/device-install-image.sh" "$HERE/device-flash-boot.sh" "$P/files/"
cp "$TOP/rootfs/pull-wcn-firmware.sh" "$TOP/rootfs/pull-audio-firmware.sh" \
   "$TOP/rootfs/extract-android-vendor.sh" "$P/scripts/rootfs/"
cp "$TOP/tools/e5-telnet.py" "$TOP/tools/sprd-bt-config.py" "$P/scripts/tools/"
cp -R "$TOP/tools/vbc-profile" "$P/scripts/tools/"
find "$P" \( -name .DS_Store -o -name __pycache__ \) -prune -exec rm -rf {} +
printf "e5-openwrt-flash %s (OpenWrt %s, e5-linux %s, kernel %s)\n" \
    "$(date +%Y-%m-%d)" "$VER" "$GIT" "$rel" > "$P/files/VERSION"
(cd "$P" && find files scripts flash.sh -type f | sort | while read -r f; do
    printf "%s  %s\n" "$({ shasum -a 256 "$f" 2>/dev/null || sha256sum "$f"; } | cut -d' ' -f1)" "$f"
done > SHA256SUMS)

tar -C "$S" -czf "$OUT/$NAME.tar.gz.part" "$NAME"
mv "$OUT/$NAME.tar.gz.part" "$OUT/$NAME.tar.gz"
echo "== $OUT/$NAME.tar.gz ($(du -h "$OUT/$NAME.tar.gz" | cut -f1))"
