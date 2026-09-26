#!/bin/bash
# Rebuild a Debian package with the fixes in rootfs/deb-patches/, for the cases
# where trixie's package has a bug that upstream has already fixed and the fix
# matters on the E5.  Runs Debian's own source package in a debian:trixie arm64
# container (native on an Apple-silicon host), adds each patch to its quilt
# series (in file-name order), gives the version a local "+e5.<patch count>"
# suffix and builds binaries only.
#
#   rootfs/build-patched-debs.sh network-manager    -> out/debs-patched/*.deb
#
# network-manager (docs/FINDINGS.md 35.2):
#   01  the VHT80 centre of channels 149-161 (backport of upstream "supplicant:
#       fix center channel calculation") -- 149 at 80 MHz failed to start
#   02  an AP with PMF disabled advertises WPA-PSK only, not also
#       WPA-PSK-SHA256 (AKM 6 without MFPC) -- phones could not join
set -eu
HERE="$(cd "$(dirname "$0")" && pwd)"
PKG=${1:?package}
OUT="$HERE/../out/debs-patched"
mkdir -p "$OUT"
exec docker run --rm --platform linux/arm64 \
    -v "$HERE/deb-patches:/patches:ro" -v "$OUT:/out" \
    -e PKG="$PKG" debian:trixie bash -euc '
export DEBIAN_FRONTEND=noninteractive
sed -i "s/^Types: deb$/Types: deb deb-src/" /etc/apt/sources.list.d/debian.sources
apt-get update -qq
apt-get install -y -qq --no-install-recommends build-essential devscripts quilt fakeroot >/dev/null
apt-get build-dep -y -qq "$PKG" >/dev/null
mkdir -p /build && cd /build
apt-get source -qq "$PKG"
cd "$(find . -maxdepth 1 -mindepth 1 -type d | head -1)"
for p in /patches/"$PKG"-*.patch; do
    cp "$p" debian/patches/
    echo "$(basename "$p")" >> debian/patches/series
done
export QUILT_PATCHES=debian/patches
quilt push -a >/dev/null
quilt pop -a >/dev/null
N=$(ls /patches/"$PKG"-*.patch | wc -l)
DEBEMAIL="e5-linux@localhost" DEBFULLNAME="e5-linux" \
    dch -v "$(dpkg-parsechangelog -SVersion)+e5.$N" "E5: $(cd /patches && ls "$PKG"-*.patch | tr "\n" " ")"
DEB_BUILD_OPTIONS="nocheck parallel=$(nproc)" dpkg-buildpackage -b -uc -us >/build/log 2>&1 || { tail -40 /build/log; exit 1; }
rm -f /out/*.deb
cp ../*.deb /out/
ls -la /out
'
