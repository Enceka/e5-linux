#!/bin/sh
set -eu
export FORCE_UNSAFE_CONFIGURE=1
cd /build
exec 9>/build/unisoc-hostapd.lock
flock 9
[ -d openwrt/.git ] || git clone -q --depth 1 --branch "v$VER" \
    https://git.openwrt.org/openwrt/openwrt.git openwrt
cd openwrt
[ "$(git rev-parse HEAD)" = "$(git rev-parse "v$VER^{commit}")" ] || {
    echo 'Unisoc WPA3: build tree differs from the requested release' >&2; exit 1;
}
H=package/network/services/hostapd
W=package/network/config/wifi-scripts
grep -q 'PKG_SOURCE_VERSION:=ca266cc24d8705eb1a2a0857ad326e48b1408b20' "$H/Makefile"
grep -q 'PKG_MIRROR_HASH:=59ac677093f524ff98588abd9f33805a336a6e929d6814222f0d784c854f2343' "$H/Makefile"
# Keep APK upgrades from replacing just one half of the driver/daemon ABI.
sed -i 's/^PKG_RELEASE:=.*/PKG_RELEASE:=1001/' "$H/Makefile" "$W/Makefile"
python3 /src/patch-hostapd-sae.py wifi "$W/files"
python3 /src/patch-hostapd-sae.py reload "$H/files"
# Preserve the rest of an existing cross-build configuration and its feeds.
if [ ! -s .config ]; then
    printf '%s\n' 'CONFIG_TARGET_armsr=y' 'CONFIG_TARGET_armsr_armv8=y' 'CONFIG_TARGET_armsr_armv8_DEVICE_generic=y' 'CONFIG_ALL_KMODS=n' 'CONFIG_ALL_NONSHARED=n' > .config
fi
sed -i -E '/^CONFIG_PACKAGE_(wpad[^=]*|hostapd[^=]*)=/d' .config
printf '%s\n' 'CONFIG_PACKAGE_wpad-basic-mbedtls=m' 'CONFIG_PACKAGE_hostapd-common=m' \
    'CONFIG_PACKAGE_wifi-scripts=m' 'CONFIG_WIFI_SCRIPTS_UCODE=y' \
    'CONFIG_SIGNED_PACKAGES=n' >> .config
make defconfig
# Out-of-tree Unisoc modules do not select OpenWrt kmod-mac80211 options.
# Preserve the official daemon's AC/AX/BE config parser and PHY support.
hostapd_make() {
    make CONFIG_DRIVER_11AC_SUPPORT=y CONFIG_DRIVER_11AX_SUPPORT=y \
        CONFIG_DRIVER_11BE_SUPPORT=y "$@"
}
hostapd_make "$H/clean"
hostapd_make "$H/prepare" V=s
source_dir=$(find build_dir/target-* -mindepth 2 -maxdepth 2 -type d -path '*/hostapd-wpad-basic-mbedtls/hostapd-*')
[ -n "$source_dir" ] && [ "$(printf '%s\n' "$source_dir" | wc -l)" = 1 ] || {
    echo 'Unisoc WPA3: expected one prepared basic-mbedtls source' >&2; exit 1;
}
python3 /src/patch-hostapd-sae.py source "$source_dir"
hostapd_make -j"$JOBS" "$H/compile" V=s
make "$W/clean"
make -j"$JOBS" "$W/compile" V=s
stage=$(mktemp -d /out/.wifi-sae.XXXXXX)
trap 'rm -rf "$stage"' EXIT
for pkg in wpad-basic-mbedtls hostapd-common wifi-scripts; do
    apk=$(find bin -type f -name "$pkg-*-r1001.apk")
    [ -n "$apk" ] && [ "$(printf '%s\n' "$apk" | wc -l)" = 1 ] || {
        echo "Unisoc WPA3: expected exactly one $pkg APK" >&2; exit 1;
    }
    cp "$apk" "$stage/"
done
(cd "$stage" && sha256sum ./*.apk > SHA256SUMS)
printf '%s\n' "$BUILD_ID" > "$stage/build-id"
printf '%s\n' "OpenWrt $VER" "hostapd ca266cc24d8705eb1a2a0857ad326e48b1408b20" \
    'Unisoc SAE: firmware authentication + hostapd four-way handshake' > "$stage/source-info"
cp "$stage/"*.apk "$stage/SHA256SUMS" "$stage/source-info" /out/
# Publish the success marker after every APK and its checksum is in place.
mv "$stage/build-id" /out/build-id
