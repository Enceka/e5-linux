#!/bin/sh
# Build the E5's Landscape daemon: upstream's static aarch64 binary plus the
# E5's patches, from a pinned commit.
#
#   openwrt/build-landscape.sh              -> out/openwrt/landscape-webserver-aarch64-static
#   openwrt/build-landscape.sh --build-id   prints the build id and exits (no Docker)
#
# build-rootfs.sh refuses to assemble a Landscape image without this artifact
# unless E5_LANDSCAPE_RELEASE=1.  The release's own daemon has no IPv6 on a WAN
# link that has no bound IPv6 address
# (openwrt/patches/landscape-v6-nat-without-wan-binding.patch), which is the
# E5's modem uplink, so the image must not ship it unpatched.
#
# The source is upstream's repository at a fixed commit, not a release asset:
# the pin is the commit id and its tree hash, and the E5's patches are applied
# to it in the container.  `openwrt/patches/landscape-*.patch` is the whole
# set -- adding or editing one changes the build id and forces a rebuild.
#
# The artifact is accompanied by three files that say what it is:
#   <name>.sha256    the binary's SHA-256
#   <name>.build-id  the stamp of the Dockerfile, the scripts and the patches
#   <name>.patches   the pinned commit and the patches it was built with (CI
#                    compares this against the tree before it ships an image)
set -eu
TOP=$(cd "$(dirname "$0")/.." && pwd)
# 0.26.3, the version /etc/landscape-router/landscape_init.toml declares, plus
# the eBPF tree rename (src/bpf/test -> src/bpf/tests) the E5's patches are
# written against.
LS_VER=0.26.3
LS_COMMIT=e9f019b5ff3b5306a7b336ee36693ca374618480
LS_TREE=9dd7bf0cb8cd53128a76765c0a52305abc287daf
[ "$(sed -n 's/^version = "\(.*\)"$/\1/p' "$TOP/openwrt/landscape/etc/landscape-router/landscape_init.toml")" = "$LS_VER" ] || {
    echo "build-landscape: landscape_init.toml is not at $LS_VER" >&2; exit 1;
}
# shasum is macOS's, sha256sum the containers'; the script runs on either.
sha() { shasum -a 256 "$@" 2>/dev/null || sha256sum "$@"; }
patch_list() { ls "$TOP"/openwrt/patches/landscape-*.patch; }
# The build id covers everything that can change the binary: the image recipe,
# both halves of the script and every patch.
stamp=$(cat "$TOP/openwrt/landscape.Dockerfile" "$TOP/openwrt/build-landscape.sh" \
    "$TOP/openwrt/build-landscape-inner.sh" $(patch_list) |
    { shasum -a 256 2>/dev/null || sha256sum; } | cut -d' ' -f1)
if [ "${1:-}" = --build-id ]; then
    printf '%s\n' "$stamp"
    exit 0
fi
OUT=${1:-$TOP/out/openwrt/landscape-webserver-aarch64-static}
mkdir -p "$(dirname "$OUT")"
OUT=$(cd "$(dirname "$OUT")" && pwd)/$(basename "$OUT")
# What the binary was built from, for the image check: a build that silently
# fell back to another source cannot produce this file.
write_provenance() {
    {
        echo "landscape $LS_VER"
        echo "commit $LS_COMMIT"
        echo "tree $LS_TREE"
        for p in $(patch_list); do echo "patch $(basename "$p") $(sha "$p" | cut -d' ' -f1)"; done
    } > "$OUT.patches.part"
    mv "$OUT.patches.part" "$OUT.patches"
}
if [ -s "$OUT" ] && [ -s "$OUT.build-id" ] && [ -s "$OUT.sha256" ] &&
   [ "$(cat "$OUT.build-id")" = "$stamp" ] &&
   [ "$(sha "$OUT" | cut -d' ' -f1)" = "$(cat "$OUT.sha256")" ]; then
    write_provenance
    echo "landscape: verified patched daemon cache"
    exit 0
fi
docker build --platform linux/arm64 -t e5-landscape-build -f "$TOP/openwrt/landscape.Dockerfile" "$TOP/openwrt"
# The registry cache is separate from the build tree so a rebuild of one patch
# does not download the crates again.  A bare name is a Docker volume and a
# path is a bind mount: CI points this at work/landscape-cargo so that
# actions/cache can carry the crate downloads across runs, since every run
# starts on a fresh runner.
CARGO_CACHE=${E5_LANDSCAPE_CARGO:-e5-landscape-cargo}
docker run --rm --platform linux/arm64 \
    -v "$TOP/openwrt:/src:ro" -v "$(dirname "$OUT"):/out" \
    -v "$CARGO_CACHE:/usr/local/cargo/registry" \
    -e "LS_COMMIT=$LS_COMMIT" -e "LS_TREE=$LS_TREE" -e "OUT_NAME=$(basename "$OUT")" \
    -e "BUILD_ID=$stamp" e5-landscape-build sh /src/build-landscape-inner.sh
[ -s "$OUT" ] && [ -s "$OUT.sha256" ] || { echo "build-landscape: no artifact at $OUT" >&2; exit 1; }
write_provenance
echo "landscape $LS_VER + E5 patches -> $OUT ($(cat "$OUT.sha256"))"
