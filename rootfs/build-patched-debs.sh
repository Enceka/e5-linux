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
#
# modemmanager (docs/FINDINGS.md 37):
#   01  the unisoc plugin: the baseband over the kernel's sipc_wwan AT port
#       and sipa_eth, without the commands that silence its AT server
#   02  +CREG/+CGREG/+CEREG with a two-digit AcT (NR SA reports 11) parse
#   03  +CMGL PDU listings with an empty line before each PDU parse
#   04  AT commands over D-Bus (mmcli --command) without --debug: e5-at and
#       UFI-TOOLS reach the modem through ModemManager
#   05  new contexts may take the ids below the first defined one: context 1
#       is the one routed to sipa_eth0, and the CP boots with only IMS at 11
set -eu
HERE="$(cd "$(dirname "$0")" && pwd)"
PKG=${1:?package}
OUT="$HERE/../out/debs-patched"
mkdir -p "$OUT"
# E5_DEB_CHECK=1 runs the package's test suite too (dpkg-buildpackage without
# nocheck) -- worth it when a patch touches code the suite covers.
exec docker run --rm --platform linux/arm64 \
    -v "$HERE/deb-patches:/patches:ro" -v "$OUT:/out" \
    -e PKG="$PKG" -e CHECK="${E5_DEB_CHECK:-0}" debian:trixie bash -euc '
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
OPTS="parallel=$(nproc)"; [ "$CHECK" = 1 ] || OPTS="nocheck $OPTS"
DEB_BUILD_OPTIONS="$OPTS" dpkg-buildpackage -b -uc -us >/build/log 2>&1 || { tail -60 /build/log; exit 1; }
[ "$CHECK" = 1 ] && grep -E "^(Ok|Fail|Expected Fail|Unexpected Pass|Skipped|Timeout|ERROR):" /build/log | tail -8
for d in ../*.deb; do rm -f /out/"$(basename "$d" | cut -d_ -f1)"_*.deb; done
cp ../*.deb /out/
ls -la /out
'
