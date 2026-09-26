#!/bin/bash
# Stage 2 of the rootfs build: install packages into the arm64 rootfs.
set -e
HERE="$(cd "$(dirname "$0")" && pwd)"
PKGS=$(grep -vE '^\s*(#|$)' "$HERE/packages.list" | tr '\n' ' ')
echo "installing: $PKGS"
DEBIAN_FRONTEND=noninteractive bash "$HERE/e5-chroot.sh" \
  "export DEBIAN_FRONTEND=noninteractive; apt-get -o APT::Sandbox::User=root -y --no-install-recommends install $PKGS"
echo "INSTALL-DONE rc=$?"

# Debian packages rebuilt with fixes (rootfs/deb-patches/, built into
# out/debs-patched/ by build-patched-debs.sh), installed over the archive's and
# held so a later apt upgrade does not undo them:
#   network-manager 1.52.1+e5: trixie's computes the VHT80 centre of channels
#     149-161 wrong and the hotspot cannot run 149 at 80 MHz (FINDINGS 35.2);
#   modemmanager 1.24.0+e5: the unisoc plugin, without which ModemManager
#     cannot drive the baseband at all (FINDINGS 37);
#   phosh 0.46.0+e5 and gnome-control-center 48.4+e5: the hotspot switch and
#     the Wi-Fi panel recognise the bridged "Hotspot"; phone mode keeps the
#     window close button.
ROOT="${E5_ROOT:-$HERE/../work/rootfs-build/rootfs}"
D="$HERE/../out/debs-patched"
install_patched() {  # <build-patched-debs.sh package> <binary packages...>
    local src=$1; shift
    local debs="" p
    for p in "$@"; do debs="$debs $(ls "$D"/${p}_*+e5*_arm64.deb 2>/dev/null)"; done
    if [ -z "${debs// }" ]; then
        echo "warn: no patched $src in out/debs-patched -- run rootfs/build-patched-debs.sh $src"
        return
    fi
    rm -rf "$ROOT/tmp/e5-debs"; mkdir -p "$ROOT/tmp/e5-debs"
    cp $debs "$ROOT/tmp/e5-debs/"
    DEBIAN_FRONTEND=noninteractive bash "$HERE/e5-chroot.sh" "
        dpkg -i /tmp/e5-debs/*.deb && apt-mark hold $*
        rm -rf /tmp/e5-debs" || echo "warn: patched $src failed to install"
}
install_patched network-manager network-manager libnm0 gir1.2-nm-1.0
install_patched modemmanager modemmanager libmm-glib0 gir1.2-modemmanager-1.0
install_patched phosh phosh phosh-common
install_patched gnome-control-center gnome-control-center gnome-control-center-data

# The build tree is kept between builds and apt never removes a package that
# stopped being asked for, so anything dropped from packages.list stays in the
# image; the list below purges what was dropped.  (NetworkManager used to be on
# it: an unconfined NM autoconnected on sipa_dummy0 and held
# network-online.target for minutes.  It is back, managing wlan0 only --
# etc/NetworkManager/conf.d/50-e5.conf -- so it is not purged any more; hostapd,
# which it replaced for the hotspot, is.)
#
# The list is written literally, not interpolated: a "$DROPPED" in the middle of
# the single-quoted chroot block splits the quoting, and the ${Status} below then
# gets expanded (to nothing) by the *outer* shell, so the filter matches no
# package and the stage reports success while purging nothing.
#
# ttyd is deliberately absent: it is not in trixie at all, and apt-get purge
# aborts the whole command on an unknown name.
echo "purging dropped packages"
DEBIAN_FRONTEND=noninteractive bash "$HERE/e5-chroot.sh" '
    for p in hostapd plasma-nm plasma-welcome; do
        if dpkg-query -W -f "${Status}" "$p" 2>/dev/null | grep -q "install ok installed"; then
            echo "purging $p"
            apt-get -o APT::Sandbox::User=root -y purge "$p" 2>&1 | tail -2
        fi
    done
    apt-get -o APT::Sandbox::User=root -y --purge autoremove 2>&1 | tail -2
    rm -f /etc/systemd/system/multi-user.target.wants/hostapd.service
' || echo "warn: purge stage failed"
echo "PURGE-DONE rc=$?"
