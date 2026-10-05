#!/bin/bash
# Build OpenWrt's modemmanager package with the E5's unisoc plugin.
#
#   openwrt/build-modemmanager.sh        -> out/openwrt/modemmanager-*.apk
#
# OpenWrt 25.12 ships ModemManager 1.24.0, the version rootfs/deb-patches/
# modemmanager-0[1-6]-*.patch are written against, so the Debian image and the
# OpenWrt one run the same plugin (docs/FINDINGS.md 37).  The patches go into
# the feed package's patches/ after OpenWrt's own (0001-0004, which they stack
# on cleanly), and patches/modemmanager-package-*.patch adjusts the package's
# OpenWrt glue (its hotplug helpers drop virtual netdevs, and sipa_eth0 is one).
#
# Built from OpenWrt's source tree at the release tag, in a container of the
# host's own architecture: the release SDK exists only as an x86_64 program,
# which Docker on an arm64 host can run only emulated -- far too slow (hours,
# for glib2 alone).  The buildroot builds its cross toolchain on any host, so
# it is set up exactly as the release was built -- the tag, the feeds pinned in
# the release's feeds.buildinfo, its config.buildinfo -- and the package comes
# out for the same toolchain (gcc, musl) as the repository's packages it is
# installed with.
#
# The tree lives in the Docker volume e5-openwrt-src and is kept between runs:
# the first run builds the host tools and the toolchain (tens of minutes), a
# later one only ModemManager.  `docker volume rm e5-openwrt-src` starts over.
#
# Configuration: no QMI, MBIM or QRTR (this modem speaks AT only, and without
# them the package does not pull libqmi/libmbim/libqrtr in); AT commands over
# D-Bus on, as in the Debian build (mmcli --command, e5-at).
#
# The release is OpenWrt's plus 900 (1.24.0-r11 -> r911): the repository's
# package never looks newer, so `apk upgrade` does not replace this one with a
# modemmanager that has no unisoc plugin.  Plus E5REV, the revision of the E5
# patches: raised whenever one of them changes, so that apk takes the rebuilt
# package for a new one (it does not reinstall a version it has).
set -euo pipefail
# 1: +IMSREGADDR/+SPNRINDICATE among the ignored unsolicited reports
# 2: context 1 is the modem's net port (sipa_eth8 for the second SIM card)
# 3: +SPSWDATA in the power-up from +CFUN: 0 (the port's card as the data card)
# 4: both cards up from +CFUN: 0, and +SPSWDATA before every dial (SIM card switch)
# 5: the work modes (+SPTESTMODEM) in that power-up, no stop on the other card's errors,
#    and the SIM slots (both cards listed; a switch through e5-sim)
# 6: rebuild legacy cached APKs and require a source/checksum manifest.
# 7: card-addressed SMS submit through the existing AT command owner.
# 8: native per-call SIM slot and dual-card voice tracking.
# 9: discard snapshots taken before a dial completed; retain undecodable calls.
E5REV=9
VER=${E5_WRT_VER:-25.12.5}
HERE="$(cd "$(dirname "$0")" && pwd)"
TOP="$(cd "$HERE/.." && pwd)"
WORK="$TOP/work/openwrt"
OUT="$TOP/out/openwrt"
URL=https://downloads.openwrt.org/releases/$VER/targets/armsr/armv8
mkdir -p "$WORK" "$OUT"

for f in config.buildinfo feeds.buildinfo; do
    curl -fsSL --retry 5 --retry-all-errors -o "$WORK/$f" "$URL/$f"
done

# the source patches, numbered after OpenWrt's own
rm -rf "$WORK/patches" && mkdir -p "$WORK/patches/src" "$WORK/patches/pkg"
cp "$HERE/tests/voice-identity.py" "$WORK/voice-identity.py"
n=900
for p in "$TOP"/rootfs/deb-patches/modemmanager-0*.patch; do
    cp "$p" "$WORK/patches/src/$n-e5-$(basename "$p" | sed 's/^modemmanager-//')"
    n=$((n + 1))
done
cp "$HERE"/patches/modemmanager-package-*.patch "$WORK/patches/pkg/"

# the container is the host's architecture (the buildroot cross-compiles for the target either way);
# E5_DOCKER=podman on a host without docker (SELinux wants the bind mounts relabelled, :z)
DOCKER=${E5_DOCKER:-docker}
case "$(uname -m)" in x86_64) PLAT=linux/amd64;; *) PLAT=linux/arm64;; esac
Z=; [ "$DOCKER" = podman ] && Z=,z
$DOCKER run --rm --platform $PLAT -v e5-openwrt-src:/build \
    -v "$WORK":/work:ro$Z -v "$OUT":/out${Z:+:z} -e VER="$VER" -e E5REV="$E5REV" \
    -e JOBS="${E5_JOBS:-$(sysctl -n hw.ncpu 2>/dev/null || nproc)}" \
    debian:trixie bash -euc '
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq --no-install-recommends build-essential ca-certificates clang file flex bison \
    gawk gettext git libncurses-dev libssl-dev python3 python3-setuptools rsync swig unzip wget \
    xz-utils zlib1g-dev zstd >/dev/null
# the buildroot refuses to run as root unless told otherwise; it lives in the
# volume, which is case-sensitive (a macOS bind mount is not)
export FORCE_UNSAFE_CONFIGURE=1
cd /build
[ -d openwrt/.git ] || git clone -q --depth 1 --branch v$VER https://git.openwrt.org/openwrt/openwrt.git openwrt
cd openwrt
# the feeds at the commits the release was built from
cp /work/feeds.buildinfo feeds.conf
# (a feed whose clone failed leaves only its index behind: update until every feed has its tree)
for try in 1 2 3 4 5; do
    missing=$(awk "/^src-/{print \$2}" feeds.conf | while read -r f; do [ -d feeds/$f/.git ] || echo $f; done)
    [ -z "$missing" ] && break
    echo "feeds to update: "$missing
    for f in $missing; do rm -rf feeds/$f feeds/$f.*; ./scripts/feeds update $f >/dev/null || true; done
done
[ -z "$missing" ] || { echo "feeds not cloned: $missing"; exit 1; }
./scripts/feeds install modemmanager >/dev/null
P=feeds/packages/net/modemmanager
# the package directory back to the feed state, then the E5 changes on top
git -C feeds/packages checkout -q -- net/modemmanager
git -C feeds/packages clean -qfd -- net/modemmanager
for p in /work/patches/pkg/*.patch; do patch -p1 -d $P < "$p"; done
cp /work/patches/src/*.patch $P/patches/
rel=$(sed -n "s/^PKG_RELEASE:=//p" $P/Makefile)
sed -i "s/^PKG_RELEASE:=.*/PKG_RELEASE:=$((rel + 900 + E5REV))/" $P/Makefile
echo "modemmanager release $rel -> $((rel + 900 + E5REV)); patches:"; ls $P/patches/
# the release configuration, reduced to what is needed here
{
    # (not CONFIG_BUILDBOT: on the release builders it also builds LLVM for
    # BPF, which nothing here needs)
    grep -E "^CONFIG_(TARGET_|GCC_|LIBC|MUSL|BINUTILS|KERNEL_|USE_|PKG_|SIGNED)" /work/config.buildinfo || true
    echo "CONFIG_BPF_TOOLCHAIN_NONE=y"
    echo "# CONFIG_BPF_TOOLCHAIN_BUILD_LLVM is not set"
    echo "CONFIG_PACKAGE_modemmanager=m"
    echo "CONFIG_PACKAGE_modemmanager-rpcd=m"
    echo "CONFIG_MODEMMANAGER_WITH_NETIFD=y"
    echo "# CONFIG_MODEMMANAGER_WITH_MBIM is not set"
    echo "# CONFIG_MODEMMANAGER_WITH_QMI is not set"
    echo "# CONFIG_MODEMMANAGER_WITH_QRTR is not set"
    echo "CONFIG_MODEMMANAGER_WITH_AT_COMMAND_VIA_DBUS=y"
} > .config
make defconfig >/dev/null
grep -E "^CONFIG_(GCC_VERSION|LIBC_VERSION|TARGET_ARCH_PACKAGES)=|^(# )?CONFIG_MODEMMANAGER" .config
if [ ! -f staging_dir/.e5-toolchain-ok ]; then
    echo "== host tools and toolchain (first run)"
    make tools/install toolchain/install -j"$JOBS" >/build/log 2>&1 || { tail -60 /build/log; exit 1; }
    touch staging_dir/.e5-toolchain-ok
fi
# the kernel, for the kmod packages the dependencies ask for (ppp wants
# kmod-ppp); none of them is installed -- the E5 runs its vendor kernel
if [ ! -f staging_dir/.e5-kernel-ok ]; then
    echo "== kernel (first run)"
    make target/linux/compile -j"$JOBS" >/build/log 2>&1 || { tail -60 /build/log; exit 1; }
    touch staging_dir/.e5-kernel-ok
fi
echo "== modemmanager"
make package/modemmanager/clean >/dev/null 2>&1 || true
make package/modemmanager/compile -j"$JOBS" >/build/log 2>&1 || { tail -80 /build/log; exit 1; }
voice_source=$(find build_dir -path "*/modemmanager-*/src/mm-iface-modem-voice.c" -print -quit)
[ -n "$voice_source" ] || { echo "missing patched voice source" >&2; exit 1; }
python3 /work/voice-identity.py "$(dirname "$voice_source")"
rm -f /out/modemmanager*.apk
find bin/packages -name "modemmanager*-r$((rel + 900 + E5REV)).apk" -exec cp {} /out/ \;
ls -la /out/modemmanager*.apk
'
python3 "$TOP/tools/openwrt-package-state.py" write "$VER"
