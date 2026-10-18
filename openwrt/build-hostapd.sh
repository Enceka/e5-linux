#!/bin/sh
# Build all three matching APKs: wpad, hostapd-common and wifi-scripts.
set -eu
TOP=$(cd "$(dirname "$0")/.." && pwd)
VER=${UNISOC_WRT_VER:-25.12.5}
[ "$VER" = 25.12.5 ] || {
    echo 'Unisoc WPA3: update the pinned source/build checks for this OpenWrt version' >&2
    exit 1
}
OUT=${1:-$TOP/work/wifi-sae}
mkdir -p "$OUT"
OUT=$(cd "$OUT" && pwd)
stamp=$(cat "$TOP/openwrt/build-hostapd.sh" "$TOP/openwrt/build-hostapd-inner.sh" \
    "$TOP/openwrt/hostapd.Dockerfile" "$TOP/openwrt/patch-hostapd-sae.py" \
    "$TOP/openwrt/hostapd-unisoc-sae.h" "$TOP/openwrt/hostapd-unisoc.sh" \
    "$TOP/openwrt/hostapd-unisoc.uc" "$TOP/openwrt/wifi-sae-state.py" |
    sha256sum | cut -d' ' -f1)
if [ -s "$OUT/build-id" ] && [ "$(cat "$OUT/build-id")" = "$stamp" ] &&
    [ -s "$OUT/SHA256SUMS" ] && python3 "$TOP/openwrt/wifi-sae-state.py" "$OUT" >/dev/null; then
    echo 'Unisoc WPA3: verified APK cache'
    exit 0
fi
# The buildroot compiles its own host tools and cross toolchain, so the container runs the host's
# architecture, like build-modemmanager.sh's.  It shares the e5-openwrt-src tree with ModemManager and
# BlueZ, and a tree prepared there has host tools for that architecture only: an x86_64 container on
# an arm64 host would find arm64 tools it cannot run (and an emulated rebuild is far slower).
case "$(uname -m)" in x86_64) PLAT=linux/amd64;; *) PLAT=linux/arm64;; esac
docker build --platform "$PLAT" -t unisoc-hostapd-build \
    -f "$TOP/openwrt/hostapd.Dockerfile" "$TOP/openwrt"
docker run --rm --platform "$PLAT" \
    -v "${UNISOC_WRT_CACHE:-e5-openwrt-src}:/build" \
    -v "$TOP/openwrt:/src:ro" -v "$OUT:/out" \
    -e "VER=$VER" -e "BUILD_ID=$stamp" -e "JOBS=${UNISOC_JOBS:-4}" \
    unisoc-hostapd-build sh /src/build-hostapd-inner.sh
python3 "$TOP/openwrt/wifi-sae-state.py" "$OUT" >/dev/null
