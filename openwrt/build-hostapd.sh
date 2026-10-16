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
docker build --platform linux/amd64 -t unisoc-hostapd-build \
    -f "$TOP/openwrt/hostapd.Dockerfile" "$TOP/openwrt"
docker run --rm --platform linux/amd64 \
    -v "${UNISOC_WRT_CACHE:-e5-openwrt-src}:/build" \
    -v "$TOP/openwrt:/src:ro" -v "$OUT:/out" \
    -e "VER=$VER" -e "BUILD_ID=$stamp" -e "JOBS=${UNISOC_JOBS:-4}" \
    unisoc-hostapd-build sh /src/build-hostapd-inner.sh
python3 "$TOP/openwrt/wifi-sae-state.py" "$OUT" >/dev/null
