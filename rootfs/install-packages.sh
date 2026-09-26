#!/bin/bash
# Stage 2 of the rootfs build: install packages into the arm64 rootfs.
set -e
HERE="$(cd "$(dirname "$0")" && pwd)"
PKGS=$(grep -vE '^\s*(#|$)' "$HERE/packages.list" | tr '\n' ' ')
echo "installing: $PKGS"
DEBIAN_FRONTEND=noninteractive bash "$HERE/e5-chroot.sh" \
  "export DEBIAN_FRONTEND=noninteractive; apt-get -o APT::Sandbox::User=root -y --no-install-recommends install $PKGS"
echo "INSTALL-DONE rc=$?"

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
