#!/bin/bash
# Build the flash package for other people's E5s:
# out/openwrt/e5-openwrt-flash-<version>-<date>-<git>.tar.gz, unpacked and run as
# ./flash.sh (openwrt/bundle/README.md is its manual).
#
#   openwrt/make-flash-bundle.sh
#   E5_MAINLINE=1 openwrt/make-flash-bundle.sh    the mainline 6.18 kernel instead of 5.15:
#       e5-openwrt-flash-<version>-mainline-<date>-<git>; the kernel of E5_RELEASE=1 upstream/build.sh
#       (upstream/out-release: no e5.openwrt=, so it is no trial), the boot modules of
#       upstream/module-order.txt, and an image rebuilt with upstream/root-modules.txt in it
#   E5_IMAGE_FROM=<openwrt.ext4.gz> (with E5_MAINLINE=1)   no image rebuilt (build-rootfs.sh needs docker):
#       that one, a flash package's files/openwrt.ext4.gz, with this kernel's root modules written in
#       (openwrt/image-add-modules.sh) -- only for an image whose sources did not change since
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
#  * the flasher, flash.py (Python: Windows, macOS, Linux; flash.cmd and
#    flash.sh start it), which pulls the recipient's own firmware off their
#    Android and converts it (tools/sprd-bt-config.py, vbc-profile), and has
#    the vendor subset collected and packed on the device itself
#    (bundle/collect-device-files.sh) -- some of those files have ":" in their
#    names, which Windows cannot store; boot/init unpacks the archive into the
#    image at boot (e5linux/device-files.tar);
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
DATE=$(date +%Y%m%d)
NAME=e5-openwrt-flash-$VER-$DATE-$GIT
MAINLINE=${E5_MAINLINE:-}
KOUT=$TOP/upstream/out-release
if [ -n "$MAINLINE" ]; then
    NAME=e5-openwrt-flash-$VER-mainline-$DATE-$GIT
    KERNEL=$KOUT/Image.lk
    [ -f "$KERNEL" ] || { echo "no $KERNEL: E5_RELEASE=1 upstream/build.sh" >&2; exit 1; }
    # (grep -c, not grep -q: see the kernel check below)
    [ "$(strings "$KERNEL" | grep -c 'e5\.openwrt=' || true)" = 0 ] ||
        { echo "$KERNEL has e5.openwrt= on its command line: a trial kernel" >&2; exit 1; }
    E5_UPSTREAM_OUT=$KOUT sh "$TOP/upstream/root-modules.sh"
    if [ -n "${E5_IMAGE_FROM:-}" ]; then
        bash "$HERE/image-add-modules.sh" "$E5_IMAGE_FROM" "$KOUT/root-modules.tar" "$IMG"
    else
        # the image always again: it has to carry this kernel's root modules
        E5_ROOT_MODULES=$KOUT/root-modules.tar E5_STANDALONE=1 E5_DEVICE_FILES=0 bash "$HERE/build-rootfs.sh"
    fi
elif [ ! -f "$IMG" ] || [ -n "${E5_REBUILD:-}" ]; then
    E5_STANDALONE=1 E5_DEVICE_FILES=0 bash "$HERE/build-rootfs.sh"
fi
echo "== checking the image for device files"
S0=$(mktemp -d)
trap 'rm -rf "$S0"' EXIT
image_files() {
    if [ -n "${E5_IMAGE_FROM:-}" ]; then
        # (the image itself: there is no rootfs tarball of it here)
        local d; d=$(mktemp -d)
        zcat "$IMG" > "$d/img"
        mkdir "$d/r" && debugfs -R "rdump / $d/r" "$d/img" >/dev/null 2>&1
        (cd "$d/r" && find . | sed 's|^\./||')
        rm -rf "$d"
    else
        tar -tzf "$WORK/e5-openwrt-$VER-generic-rootfs.tar.gz"
    fi
}
image_files > "$S0/files"
grep -qx 'sbin/init' "$S0/files" || grep -qx './sbin/init' "$S0/files" || { echo "no listing of the image" >&2; exit 1; }
bad=$(cat "$S0/files" |
      grep -E 'lib/firmware/(wcnmodem|gnssmodem|l_agdsp|wifi_board|sprd/)|opt/e5/android/.|etc/e5/install\.conf|mnt/vendor/.|attendedsysupgrade' || true)
[ -z "$bad" ] || { echo "the generic image carries what it must not (device files, attended sysupgrade):" >&2; echo "$bad" | head >&2; exit 1; }

echo "== boot image without the overlay"
BOOT="$TOP/work/boot-linux-slotb-bundle"
if [ -n "$MAINLINE" ]; then
    # (the kernel's command line is its own, CONFIG_CMDLINE_FORCE: upstream/make-boot.sh)
    BOOT="$TOP/work/boot-linux-slotb-bundle-mainline"
    python3 "$TOP/boot/build-boot-image.py" --stock-boot "$TOP/dumps/boot_b.img" \
        --misc-head "$TOP/dumps/misc-head.bin" --kernel "$KERNEL" --modules "$KOUT/modules" \
        --module-order "$TOP/upstream/module-order.txt" --cmdline "" \
        --busybox "$TOP/work/busybox/ext/usr/bin/busybox" --out "$BOOT.img" | tail -1
else
    python3 "$TOP/boot/build-boot-image.py" --stock-boot "$TOP/dumps/boot_b.img" \
        --misc-head "$TOP/dumps/misc-head.bin" --kernel "$KERNEL" --modules "$TOP/out_modules" \
        --busybox "$TOP/work/busybox/ext/usr/bin/busybox" --out "$BOOT.img" | tail -1
fi
[ "$(python3 -c "import json,sys;print(json.load(open(sys.argv[1]))['overlay_files'])" "$BOOT.json")" = 0 ] ||
    { echo "the boot image has an overlay" >&2; exit 1; }
# the kernel and the image's modem modules have to be one build
if [ -z "$MAINLINE" ]; then
    rel=$(strings "$TOP/out_linux/drivers/net/wwan/wwan.ko" | sed -n 's/^vermagic=\([^ ]*\).*/\1/p' | head -1)
else
    rel=$(cat "$KOUT/kernel.release")
    grep -qx "lib/modules/$rel/modem/sipc_wwan.ko" < <(tar -tf "$KOUT/root-modules.tar") ||
        { echo "$KOUT/root-modules.tar is not of $rel" >&2; exit 1; }
fi
# (not "strings | grep -q": grep leaves early, and pipefail counts the SIGPIPE)
grep -q "Linux version $rel " < <(strings "$KERNEL") ||
    { echo "the kernel ($KERNEL) is not the build of out_linux ($rel)" >&2; exit 1; }

S=$(mktemp -d)
trap 'rm -rf "$S0" "$S"' EXIT
P=$S/$NAME
mkdir -p "$P/files" "$P/scripts/tools"
# the flasher: flash.py (Windows, macOS, Linux), started by flash.cmd / flash.sh
cp "$HERE/bundle/flash.py" "$HERE/bundle/flash.sh" "$HERE/bundle/flash.cmd" "$P/"
chmod 755 "$P/flash.py" "$P/flash.sh"
cp "$HERE/bundle/README.md" "$HERE/bundle/README.zh-CN.md" "$P/"
cp "$TOP/LICENSE" "$P/LICENSE"
cp "$IMG" "$P/files/openwrt.ext4.gz"
cp "$BOOT.img" "$P/files/boot.img"
cp "$BOOT.json" "$P/files/boot.json"
cp "$BOOT.misc-slot-b-trial.bin" "$P/files/boot-misc-slot-b.bin"
cp "$HERE/device-install-image.sh" "$HERE/device-flash-boot.sh" "$HERE/bundle/collect-device-files.sh" \
   "$HERE/overlay/usr/libexec/e5-gpt" "$P/files/"
cp "$TOP/tools/e5-telnet.py" "$TOP/tools/sprd-bt-config.py" "$P/scripts/tools/"
cp -R "$TOP/tools/vbc-profile" "$P/scripts/tools/"
find "$P" \( -name .DS_Store -o -name __pycache__ \) -prune -exec rm -rf {} +
printf "e5-openwrt-flash %s (OpenWrt %s, e5-linux %s, kernel %s)\n" \
    "$(date +%Y-%m-%d)" "$VER" "$GIT" "$rel" > "$P/files/VERSION"
(cd "$P" && find files scripts flash.py flash.sh flash.cmd -type f | sort | while read -r f; do
    printf "%s  %s\n" "$({ shasum -a 256 "$f" 2>/dev/null || sha256sum "$f"; } | cut -d' ' -f1)" "$f"
done > SHA256SUMS)

tar -C "$S" -czf "$OUT/$NAME.tar.gz.part" "$NAME"
mv "$OUT/$NAME.tar.gz.part" "$OUT/$NAME.tar.gz"
# and a .zip for Windows (its Explorer opens it without anything installed)
rm -f "$OUT/$NAME.zip"
(cd "$S" && python3 - "$NAME" "$OUT/$NAME.zip.part" <<'PY'
import os, sys, zipfile
top, out = sys.argv[1], sys.argv[2]
with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED) as z:
    for d, _, files in os.walk(top):
        for f in sorted(files):
            p = os.path.join(d, f)
            i = zipfile.ZipInfo.from_file(p, p)
            i.external_attr = (os.stat(p).st_mode & 0xFFFF) << 16
            with open(p, 'rb') as fh:
                z.writestr(i, fh.read(), zipfile.ZIP_STORED if f.endswith('.gz') else zipfile.ZIP_DEFLATED)
PY
)
mv "$OUT/$NAME.zip.part" "$OUT/$NAME.zip"
echo "== $OUT/$NAME.tar.gz ($(du -h "$OUT/$NAME.tar.gz" | cut -f1)), $OUT/$NAME.zip ($(du -h "$OUT/$NAME.zip" | cut -f1))"
