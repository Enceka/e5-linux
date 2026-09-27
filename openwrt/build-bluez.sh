#!/bin/bash
# Build OpenWrt's bluez packages with the E5's patches.
#
#   openwrt/build-bluez.sh        -> out/openwrt/bluez-*.apk
#
# rootfs/deb-patches/bluez-0*.patch, the same patches the Debian image takes:
#  01  the larger SDP MTU for every device.  Headphones (Redmi Buds 6) answer
#      the service search with PDUs over the default 672-byte MTU, the kernel
#      drops them, and no audio profile ever connects (docs/FINDINGS.md 45).
#
# Built like ModemManager (openwrt/build-modemmanager.sh): natively on arm64,
# in OpenWrt's source tree at the release tag, in the Docker volume
# e5-openwrt-src -- run build-modemmanager.sh once first, it sets the tree,
# the host tools and the toolchain up.  The release is OpenWrt's plus 900 plus
# E5REV, so apk never replaces these with the repository's.
set -euo pipefail
VER=${E5_WRT_VER:-25.12.5}
HERE="$(cd "$(dirname "$0")" && pwd)"
TOP="$(cd "$HERE/.." && pwd)"
WORK="$TOP/work/openwrt"
OUT="$TOP/out/openwrt"
URL=https://downloads.openwrt.org/releases/$VER/targets/armsr/armv8
# 1: 01-sdp-large-mtu
E5REV=1
mkdir -p "$WORK" "$OUT"

for f in config.buildinfo feeds.buildinfo; do
    [ -f "$WORK/$f" ] || curl -fsSL -o "$WORK/$f" "$URL/$f"
done
rm -rf "$WORK/bluez-patches" && mkdir -p "$WORK/bluez-patches"
n=900
for p in "$TOP"/rootfs/deb-patches/bluez-0*.patch; do
    cp "$p" "$WORK/bluez-patches/$n-e5-$(basename "$p" | sed 's/^bluez-//')"
    n=$((n + 1))
done

docker run --rm --platform linux/arm64 -v e5-openwrt-src:/build \
    -v "$WORK":/work:ro -v "$OUT":/out -e E5REV="$E5REV" \
    -e JOBS="${E5_JOBS:-$(sysctl -n hw.ncpu 2>/dev/null || nproc)}" \
    debian:trixie bash -euc '
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq --no-install-recommends build-essential ca-certificates clang file flex bison \
    gawk gettext git libncurses-dev libssl-dev python3 python3-setuptools rsync swig unzip wget \
    xz-utils zlib1g-dev zstd >/dev/null
export FORCE_UNSAFE_CONFIGURE=1
cd /build/openwrt 2>/dev/null || { echo "no buildroot in e5-openwrt-src: run openwrt/build-modemmanager.sh first" >&2; exit 1; }
[ -f staging_dir/.e5-toolchain-ok ] || { echo "no toolchain yet: run openwrt/build-modemmanager.sh first" >&2; exit 1; }
./scripts/feeds install bluez-daemon >/dev/null
P=feeds/packages/utils/bluez
git -C feeds/packages checkout -q -- utils/bluez
git -C feeds/packages clean -qfd -- utils/bluez
mkdir -p $P/patches && cp /work/bluez-patches/*.patch $P/patches/
rel=$(sed -n "s/^PKG_RELEASE:=//p" $P/Makefile)
sed -i "s/^PKG_RELEASE:=.*/PKG_RELEASE:=$((rel + 900 + E5REV))/" $P/Makefile
echo "bluez release $rel -> $((rel + 900 + E5REV)); patches:"; ls $P/patches/
# the packages wanted, on top of the configuration build-modemmanager.sh made
for p in bluez-daemon bluez-libs bluez-utils bluez-utils-btmon; do
    grep -q "^CONFIG_PACKAGE_$p=" .config || echo "CONFIG_PACKAGE_$p=m" >> .config
done
make defconfig >/dev/null
echo "== bluez"
make package/bluez/clean >/dev/null 2>&1 || true
make package/bluez/compile -j"$JOBS" >/build/log 2>&1 || { tail -80 /build/log; exit 1; }
rm -f /out/bluez-*.apk
find bin/packages -name "bluez-*-r$((rel + 900 + E5REV)).apk" -exec cp {} /out/ \;
ls -la /out/bluez-*.apk
'
