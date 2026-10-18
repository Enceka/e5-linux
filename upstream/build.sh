#!/bin/bash
# Build the E5's mainline kernel (linux-lts-e5) in the e5-mainline-build container:
# upstream/out/Image, Image.lk (for LK), modules/ (flat) and modules.tar (lib/modules), config, System.map.
#
#   docker build -t e5-mainline-build upstream/     (once)
#   upstream/build.sh                                (from the host; runs itself in the container)
#
# E5_KERNEL_TREE  the kernel repository (default: linux-lts-e5 next to upstream/)
# E5_RELEASE=1    the kernel of a flash package (openwrt/make-flash-bundle.sh E5_MAINLINE=1): the command line
#                 without e5.openwrt=, so boot/init starts the installed openwrt.ext4 and it can be the default
#                 boot; into upstream/out-release/, so that the trial scripts (upstream/out/) never take it
# The objects stay in the docker volume e5-mainline-out (a bind mount would be slower), per kernel release.
set -eo pipefail
# An explicit empty value suppresses the SCM fallback + when AUTO is disabled.
export LOCALVERSION=
if [ -z "${E5_IN_CONTAINER:-}" ]; then
    HERE="$(cd "$(dirname "$0")" && pwd)"
    K="${E5_KERNEL_TREE:-$HERE/../linux-lts-e5}"
    K="$(cd "$K" && pwd)"
    KERNEL_MOUNTS=(-v "$K:/src/linux:ro")
    if [ -f "$K/.git" ]; then
        kernel_common_git=$(git -C "$K" rev-parse --path-format=absolute --git-common-dir)
        KERNEL_MOUNTS+=(-v "$kernel_common_git:$kernel_common_git:ro")
    fi
    exec docker run --rm -e E5_IN_CONTAINER=1 -e E5_RELEASE="${E5_RELEASE:-}" \
        -e TZ=CST-8 -e KBUILD_BUILD_TIMESTAMP="${KBUILD_BUILD_TIMESTAMP:-}" \
        -e E5_OUTPUT_UID="$(id -u)" -e E5_OUTPUT_GID="$(id -g)" \
        "${KERNEL_MOUNTS[@]}" -v e5-mainline-out:/out -v "$HERE":/work \
        e5-mainline-build bash /work/build.sh "$@"
fi

# An empty variable overrides kbuild's default, so unset it for local builds.
[ -n "${KBUILD_BUILD_TIMESTAMP:-}" ] || unset KBUILD_BUILD_TIMESTAMP
cd /src/linux
python3 /work/check-kernel-source.py .
KV=$(make -s kernelversion)
O=/out/$KV
mkdir -p "$O"
echo "== linux-lts-e5 $KV, $(git log --oneline -1)"

CFG=/work/e5-mainline.config DEST=/work/out
if [ -n "${E5_RELEASE:-}" ]; then
    CFG=/tmp/e5-mainline-release.config DEST=/work/out-release
    sed 's/ e5\.openwrt=[A-Za-z0-9._-]*//' /work/e5-mainline.config > "$CFG"
    ! grep -q 'e5\.openwrt=' "$CFG" || { echo "e5.openwrt= is still in the release command line" >&2; exit 1; }
    echo "   (release: no e5.openwrt=, into out-release/)"
fi
make O="$O" ARCH=arm64 allnoconfig >/dev/null
# merge_config.sh creates its scratch files in the current directory, which is the read-only source; run it in the
# writable output directory (every argument above and below is an absolute path).
kernel_merge_config="$PWD/scripts/kconfig/merge_config.sh"
(cd "$O" && "$kernel_merge_config" -m -O "$O" "$O/.config" "$CFG" >/dev/null)
# PR #228: NFSv4.1 is a separate prerequisite only on kernels exposing it.
if grep -q '^config NFS_V4_1$' fs/nfs/Kconfig; then
    scripts/config --file "$O/.config" --enable NFS_V4_1
fi
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
done < "$CFG"
[ -z "$bad" ] || { printf "config options not taken:$bad\n" >&2; exit 1; }

# on failure, the compiler's own messages (a plain grep for "error" also matches object names)
make O="$O" ARCH=arm64 -j"$(nproc)" Image modules > "$O/build.log" 2>&1 || {
    grep -n -E ": (fatal )?error: |-Werror|treated as errors|undefined reference|No such file|Killed|internal compiler error|\*\*\*" -A3 "$O/build.log" | head -80 || true
    echo "--- end of build.log:"; tail -25 "$O/build.log"
    exit 1
}
mkdir -p $DEST
cp "$O/arch/arm64/boot/Image" "$O/System.map" "$O/modules.builtin" "$O/modules.builtin.modinfo" $DEST/
cp "$O/.config" $DEST/config
python3 /work/wrap-image.py $DEST/Image $DEST/Image.lk
cat "$O/include/config/kernel.release" > $DEST/kernel.release
python3 /work/check-kernel-source.py . --release-file "$DEST/kernel.release"
# the modules: flat for the boot image (boot/build-boot-image.py --modules), and as lib/modules/<release> for
# a root filesystem
rm -rf "$O/mod" $DEST/modules && mkdir -p $DEST/modules
make -s O="$O" ARCH=arm64 INSTALL_MOD_PATH="$O/mod" INSTALL_MOD_STRIP=1 modules_install
python3 /work/check-kernel-source.py .
find "$O/mod/lib/modules" -name '*.ko' -exec cp {} $DEST/modules/ \;
tar -C "$O/mod" -cf $DEST/modules.tar lib/modules
python3 /work/check-container-support.py "$DEST" --record
# Docker creates these files as root on Linux bind mounts. The host must be
# able to add root-modules.tar and package the outputs after this container exits.
if [ -n "${E5_OUTPUT_UID:-}" ] && [ -n "${E5_OUTPUT_GID:-}" ]; then
    chown -R "$E5_OUTPUT_UID:$E5_OUTPUT_GID" "$DEST"
fi
echo "== modules: $(ls $DEST/modules | wc -l)"
echo "== $(cat $DEST/kernel.release): $(ls -la $DEST/Image.lk | awk '{print $5}') bytes"
