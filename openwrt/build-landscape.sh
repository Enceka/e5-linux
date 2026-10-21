#!/bin/sh
# Build the E5's Landscape daemon: upstream's static aarch64 binary plus the
# E5's patches, from a pinned commit.
#
#   openwrt/build-landscape.sh   -> out/openwrt/landscape-webserver-aarch64-static
#
# build-rootfs.sh uses this artifact when it is there and takes the upstream
# release's own binary only otherwise.  The release has no IPv6 on a WAN link
# that has no bound IPv6 address (openwrt/patches/landscape-v6-nat-without-
# wan-binding.patch), which is the E5's modem uplink, so the image must not
# ship it unpatched.
#
# The source is upstream's repository at a fixed commit, not a release asset:
# the pin is the commit id and its tree hash, and the E5's patches are applied
# to it in the container.  `openwrt/patches/landscape-*.patch` is the whole
# set -- adding or editing one changes the build id and forces a rebuild.
set -eu
TOP=$(cd "$(dirname "$0")/.." && pwd)
OUT=${1:-$TOP/out/openwrt/landscape-webserver-aarch64-static}
# 0.26.3, the version /etc/landscape-router/landscape_init.toml declares, plus
# the eBPF tree rename (src/bpf/test -> src/bpf/tests) the E5's patches are
# written against.
LS_VER=0.26.3
LS_COMMIT=e9f019b5ff3b5306a7b336ee36693ca374618480
LS_TREE=9dd7bf0cb8cd53128a76765c0a52305abc287daf
[ "$(sed -n 's/^version = "\(.*\)"$/\1/p' "$TOP/openwrt/landscape/etc/landscape-router/landscape_init.toml")" = "$LS_VER" ] || {
    echo "build-landscape: landscape_init.toml is not at $LS_VER" >&2; exit 1;
}
mkdir -p "$(dirname "$OUT")"
OUT=$(cd "$(dirname "$OUT")" && pwd)/$(basename "$OUT")
# shasum is macOS's, sha256sum the containers'; the script runs on either.
sha() { shasum -a 256 "$@" 2>/dev/null || sha256sum "$@"; }
stamp=$(cat "$TOP/openwrt/landscape.Dockerfile" "$TOP/openwrt/build-landscape.sh" \
    "$TOP/openwrt/build-landscape-inner.sh" "$TOP"/openwrt/patches/landscape-*.patch |
    { shasum -a 256 2>/dev/null || sha256sum; } | cut -d' ' -f1)
if [ -s "$OUT" ] && [ -s "$OUT.build-id" ] && [ -s "$OUT.sha256" ] &&
   [ "$(cat "$OUT.build-id")" = "$stamp" ] &&
   [ "$(sha "$OUT" | cut -d' ' -f1)" = "$(cat "$OUT.sha256")" ]; then
    echo "landscape: verified patched daemon cache"
    exit 0
fi
docker build --platform linux/arm64 -t e5-landscape-build -f "$TOP/openwrt/landscape.Dockerfile" "$TOP/openwrt"
# The registry cache is separate from the build tree so a rebuild of one patch
# does not download the crates again.
docker run --rm --platform linux/arm64 \
    -v "$TOP/openwrt:/src:ro" -v "$(dirname "$OUT"):/out" \
    -v e5-landscape-cargo:/usr/local/cargo/registry \
    -e "LS_COMMIT=$LS_COMMIT" -e "LS_TREE=$LS_TREE" -e "OUT_NAME=$(basename "$OUT")" \
    -e "BUILD_ID=$stamp" e5-landscape-build sh /src/build-landscape-inner.sh
[ -s "$OUT" ] && [ -s "$OUT.sha256" ] || { echo "build-landscape: no artifact at $OUT" >&2; exit 1; }
echo "landscape $LS_VER + E5 patches -> $OUT ($(cat "$OUT.sha256"))"
