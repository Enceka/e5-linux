#!/bin/sh
# upstream/out/root-modules.tar: the modules of upstream/root-modules.txt as lib/modules/<release>/<dir>/, for a
# root filesystem (the trial scripts unpack it into the trial root)
set -eu
HERE=$(cd "$(dirname "$0")" && pwd)
R=$(cat "$HERE/out/kernel.release")
T=$(mktemp -d)
trap 'rm -rf "$T"' EXIT
grep -v '^#' "$HERE/root-modules.txt" | while read -r m; do
    [ -n "$m" ] || continue
    mkdir -p "$T/lib/modules/$R/$(dirname "$m")"
    cp "$HERE/out/modules/$(basename "$m")" "$T/lib/modules/$R/$m"
done
tar -C "$T" -cf "$HERE/out/root-modules.tar" lib
echo "$HERE/out/root-modules.tar: $(tar -tf "$HERE/out/root-modules.tar" | grep -c '\.ko$') modules for $R"
