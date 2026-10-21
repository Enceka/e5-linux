#!/bin/sh
# Inner half of build-landscape.sh: runs in landscape.Dockerfile.
#
# Checks out the pinned upstream commit, verifies its tree hash, applies the
# E5's patches and builds the static aarch64 daemon with upstream's own
# scripts/build_musl_static.sh (cargo-zigbuild + Alpine sysroot).
set -eu
: "${LS_COMMIT:?}" "${LS_TREE:?}" "${OUT_NAME:?}" "${BUILD_ID:?}"
mkdir -p /work && cd /work
rm -rf src
git init -q src
cd src
git remote add origin https://github.com/ThisSeanZhang/landscape.git
# The commit id is the pin (a SHA-1 over the tree); the tree hash below is the
# same content checked again, so a moved or rewritten commit fails here rather
# than in a silently different daemon.
git fetch -q --depth 1 origin "$LS_COMMIT"
git checkout -q FETCH_HEAD
tree=$(git rev-parse 'HEAD^{tree}')
[ "$tree" = "$LS_TREE" ] || { echo "landscape source tree $tree is not the pinned $LS_TREE" >&2; exit 1; }
for p in /src/patches/landscape-*.patch; do
    git apply --check "$p"
    git apply "$p"
    echo "applied $(basename "$p")"
done
export PATH=/usr/local/cargo/bin:$PATH
# The sysroot is assembled from the Alpine mirror on a fresh container; keep it
# out of the source tree so a rebuild starts from a clean checkout.
export SYSROOT_BASE=/sysroot STATIC=1 GATEWAY=1
bash scripts/build_musl_static.sh aarch64-unknown-linux-musl
out=output/landscape-webserver-aarch64-static
[ -x "$out" ] || { echo "no daemon at $out" >&2; exit 1; }
cp "$out" "/out/$OUT_NAME.part"
mv "/out/$OUT_NAME.part" "/out/$OUT_NAME"
sha256sum "/out/$OUT_NAME" | cut -d' ' -f1 > "/out/$OUT_NAME.sha256"
printf '%s\n' "$BUILD_ID" > "/out/$OUT_NAME.build-id"
file "/out/$OUT_NAME"
