#!/bin/bash
# e5-linux: collect the built modules and derive the initramfs load order.
#
# Two things come out of this:
#   out_modules/           flat, stripped .ko files -> packed into the initramfs
#   boot/module-order.txt  the modules the initramfs insmods, in load order
#
# The order is not alphabetical. Android's stock first-stage list puts
# ADI/PMIC/clock layers first and ump9620-regulator at position 18; an
# alphabetical list loads ump9620-regulator first, where dev_get_regmap()
# returns NULL and the driver dereferences it, killing first-stage init with no
# log at all. On top of that Android relies on modprobe to pull dependencies in,
# while the initramfs uses insmod, so the dependency closure is resolved here
# with depmod + boot/gen-module-order.py and emitted in dependency-first order.
set -e
HERE="$(cd "$(dirname "$0")" && pwd)"
O="${O:-$HERE/../out_linux}"
DEST="${DEST:-$HERE/../out_modules}"
STOCK="$HERE/module-order.stock"
EXTRA="$HERE/module-order.extra"

[ -d "$O" ] || { echo "kernel build output not found: $O"; exit 1; }

REL=$(sed -n 's/^#define UTS_RELEASE "\(.*\)"$/\1/p' "$O/include/generated/utsrelease.h")
[ -n "$REL" ] || { echo "cannot read UTS_RELEASE from $O"; exit 1; }
echo "kernel release: $REL"

# 1. a real module tree so depmod can work out the dependencies
rm -rf "$DEST"
MODDIR="$DEST/.depmod/lib/modules/$REL"
TREE="$MODDIR/kernel"
mkdir -p "$TREE"
n=0
while IFS= read -r f; do
    rel="${f#$O/}"
    mkdir -p "$TREE/kernel/$(dirname "$rel")"
    cp "$f" "$TREE/kernel/$rel"
    n=$((n + 1))
done < <(find "$O" -name '*.ko' -type f)
echo "staged $n modules into the depmod tree"

for f in modules.builtin modules.builtin.modinfo modules.order; do
    if [ -f "$O/$f" ]; then cp "$O/$f" "$MODDIR/$f"; fi
done
depmod -b "$DEST/.depmod" "$REL" 2>&1 | head -5 || true

# 2. dependency closure, dependency-first
python3 "$HERE/gen-module-order.py" "$MODDIR/modules.dep" \
        "$STOCK" "$EXTRA" > "$HERE/module-order.txt"

# 3. flat, stripped copies of exactly the modules the initramfs will insmod
mkdir -p "$DEST"
loaded=0
while read -r m; do
    [ -n "$m" ] || continue
    f=$(find "$TREE" -name "$m" -print -quit)
    if [ -n "$f" ]; then
        cp "$f" "$DEST/$m"
        llvm-strip --strip-debug "$DEST/$m" 2>/dev/null || true
        loaded=$((loaded + 1))
    else
        echo "warning: $m listed in module-order.txt but not found" >&2
    fi
done < "$HERE/module-order.txt"
rm -rf "$DEST/.depmod"

echo "initramfs load list: $(grep -c . "$HERE/module-order.txt") modules ($loaded staged)"
du -sh "$DEST"
