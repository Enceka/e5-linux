#!/bin/bash
# e5-linux: build a general-purpose Linux kernel for the Rongyue E5.
#
# Base: the device's own Android defconfig (arch/arm64/configs/e5_rongyue_defconfig)
#       from the kernel_sprd_ums9158 tree, merged with kernel/e5-linux.fragment.
# Out:  $O/arch/arm64/boot/Image, $O/**/*.ko, $O/arch/arm64/boot/dts/sprd/*.dtb
#
# Env:  KERNEL_TREE  path to the kernel_sprd_ums9158 checkout
#       O            output directory (default out_linux)
#       JOBS         make parallelism (default: nproc)
set -e
HERE="$(cd "$(dirname "$0")" && pwd)"
cd "$HERE"

KERNEL_TREE="${KERNEL_TREE:-$HERE/../kernel_sprd_ums9158}"
O="${O:-$HERE/../out_linux}"
JOBS="${JOBS:-$(nproc)}"

[ -d "$KERNEL_TREE" ] || { echo "kernel tree not found: $KERNEL_TREE (set KERNEL_TREE)"; exit 1; }
case "$O" in /*) ;; *) O="$PWD/$O" ;; esac

cd "$KERNEL_TREE"

export ARCH=arm64
export LLVM=1
export LLVM_IAS=1

# The E5 DT overlay is built the same way the Android build does it (qogirn6l family).
export BSP_BUILD_DT_OVERLAY=y
export BSP_BUILD_ANDROID_OS=y
export BSP_BUILD_FAMILY=qogirn6l
export CONFIG_DTB_ORIGINAL=y

# clang here is much newer than the kernel's reference compiler; -Werror turns
# the new warnings into build failures.
KCFLAGS="-Wno-frame-larger-than -Wno-deprecated-declarations -Wno-constant-conversion -Wno-uninitialized-const-pointer -Wno-unused-function"

DECONF=arch/arm64/configs/e5_rongyue_defconfig
[ -f "$DECONF" ] || { echo "defconfig not found: $DECONF"; exit 1; }

# $O must exist before the first copy: "cp x $O/.config" fails silently when it
# does not, and olddefconfig then quietly falls back to Kconfig defaults (this
# is how MALI_PLATFORM_NAME ended up as "devicetree" instead of "qogirn6l").
mkdir -p "$O"
cp "$DECONF" "$O/.config"

echo "== merging e5-linux.fragment =="
./scripts/kconfig/merge_config.sh -m -O "$O" "$O/.config" "$HERE/e5-linux.fragment"

echo "== olddefconfig =="
make O="$O" olddefconfig

# Fail loudly if a symbol the initramfs depends on did not survive.
missing=""
for sym in DEVTMPFS DEVTMPFS_MOUNT CONFIGFS_FS USB_F_ACM USB_F_ECM USB_CONFIGFS_ACM USB_CONFIGFS_ECM EXT4_FS BLK_DEV_LOOP F2FS_FS; do
    grep -q "^CONFIG_$sym=y" "$O/.config" || missing="$missing $sym"
done
[ -z "$missing" ] && echo "config check: ok" || { echo "config check FAILED:$missing"; exit 1; }

echo "== building Image + modules + dtbs (jobs=$JOBS) =="
make O="$O" -j"$JOBS" KCFLAGS="$KCFLAGS" Image modules dtbs

echo
echo "== build summary =="
cat "$O/include/generated/utsrelease.h"
ls -la "$O/arch/arm64/boot/Image"
echo "modules: $(find "$O" -name '*.ko' | wc -l) .ko"
echo "sprd dtbs:"
ls "$O/arch/arm64/boot/dts/sprd/" 2>/dev/null | grep -E "e5|ums9621|ums9158" || true
