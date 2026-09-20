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
# image.  NetworkManager is the one that matters: still installed, still enabled
# by an older configure-rootfs, autoconnecting on sipa_dummy0 and holding
# network-online.target for minutes -- which is what timed the hotspot out.
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
    for p in network-manager network-manager-l10n plasma-nm plasma-welcome; do
        if dpkg-query -W -f "${Status}" "$p" 2>/dev/null | grep -q "install ok installed"; then
            echo "purging $p"
            apt-get -o APT::Sandbox::User=root -y purge "$p" 2>&1 | tail -2
        fi
    done
    apt-get -o APT::Sandbox::User=root -y --purge autoremove 2>&1 | tail -2
    rm -f /etc/systemd/system/multi-user.target.wants/NetworkManager.service \
          /etc/systemd/system/dbus-org.freedesktop.NetworkManager.service \
          /etc/systemd/system/dbus-org.freedesktop.nm-dispatcher.service
    rm -rf /etc/NetworkManager
' || echo "warn: purge stage failed"
echo "PURGE-DONE rc=$?"
