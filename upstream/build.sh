#!/bin/bash
# Build the E5's mainline kernel (linux-lts-e5) in the e5-mainline-build container:
# upstream/out/Image, Image.lk (for LK), modules.builtin*, config, System.map.
#
#   docker build -t e5-mainline-build upstream/     (once)
#   upstream/build.sh                                (from the host; runs itself in the container)
#
# E5_KERNEL_TREE  the kernel repository (default: linux-lts-e5 next to upstream/)
# The objects stay in the docker volume e5-mainline-out (a bind mount would be slower), per kernel release.
set -eo pipefail
if [ -z "${E5_IN_CONTAINER:-}" ]; then
    HERE="$(cd "$(dirname "$0")" && pwd)"
    K="${E5_KERNEL_TREE:-$HERE/../linux-lts-e5}"
    K="$(cd "$K" && pwd)"
    exec docker run --rm -e E5_IN_CONTAINER=1 -v "$K":/src/linux -v e5-mainline-out:/out -v "$HERE":/work \
        e5-mainline-build bash /work/build.sh "$@"
fi

cd /src/linux
KV=$(make -s kernelversion)
O=/out/$KV
mkdir -p "$O"
echo "== linux-lts-e5 $KV, $(git log --oneline -1)"
[ -z "$(git status --porcelain --untracked-files=no)" ] || echo "   (the tree has uncommitted changes: the release gets -dirty)"

make O="$O" ARCH=arm64 allnoconfig >/dev/null
./scripts/kconfig/merge_config.sh -m -O "$O" "$O/.config" /work/e5-mainline.config >/dev/null
make O="$O" ARCH=arm64 olddefconfig >/dev/null
# options Kconfig did not take: known ones are listed in config-ignored.txt, any other stops the build
# (mu300-linux: a silently dropped option has cost a working feature before)
bad=
while IFS= read -r l; do
    case "$l" in CONFIG_*=*)
        k=${l%%=*} v=${l#*=}
        g=$(grep -E "^$k=" "$O/.config" | cut -d= -f2- || true)
        if [ "$v" = n ]; then
            grep -q "^$k=[ym]" "$O/.config" && bad="$bad\nNOT DISABLED: $k"
            continue
        fi
        [ "$g" = "$v" ] || grep -qx "$k" /work/config-ignored.txt 2>/dev/null || bad="$bad\nNOT SET: $k want $v got ${g:-unset}";;
    esac
done < /work/e5-mainline.config
[ -z "$bad" ] || { printf "config options not taken:$bad\n" >&2; exit 1; }

# on failure, the compiler's own messages (a plain grep for "error" also matches object names)
make O="$O" ARCH=arm64 -j"$(nproc)" Image > "$O/build.log" 2>&1 || {
    grep -n -E ": (fatal )?error: |-Werror|treated as errors|undefined reference|No such file|Killed|internal compiler error|\*\*\*" -A3 "$O/build.log" | head -80 || true
    echo "--- end of build.log:"; tail -25 "$O/build.log"
    exit 1
}
mkdir -p /work/out
cp "$O/arch/arm64/boot/Image" "$O/System.map" "$O/modules.builtin" "$O/modules.builtin.modinfo" /work/out/
cp "$O/.config" /work/out/config
python3 /work/wrap-image.py /work/out/Image /work/out/Image.lk
cat "$O/include/config/kernel.release" > /work/out/kernel.release
echo "== $(cat /work/out/kernel.release): $(ls -la /work/out/Image.lk | awk '{print $5}') bytes"
