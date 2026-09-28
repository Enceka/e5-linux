#!/bin/sh
# upstream/out/root-modules.tar: the modules of upstream/root-modules.txt as lib/modules/<release>/<dir>/, for a
# root filesystem (the trial scripts unpack it into the trial root; a mainline flash package's image carries it)
# E5_UPSTREAM_OUT: another build's output (default upstream/out; the package's is upstream/out-release)
set -eu
HERE=$(cd "$(dirname "$0")" && pwd)
OUT=${E5_UPSTREAM_OUT:-$HERE/out}
R=$(cat "$OUT/kernel.release")
T=$(mktemp -d)
trap 'rm -rf "$T"' EXIT
grep -v '^#' "$HERE/root-modules.txt" | while read -r m; do
    [ -n "$m" ] || continue
    mkdir -p "$T/lib/modules/$R/$(dirname "$m")"
    cp "$OUT/modules/$(basename "$m")" "$T/lib/modules/$R/$m"
done
tar -C "$T" -cf "$OUT/root-modules.tar" lib
echo "$OUT/root-modules.tar: $(tar -tf "$OUT/root-modules.tar" | grep -c '\.ko$') modules for $R"
