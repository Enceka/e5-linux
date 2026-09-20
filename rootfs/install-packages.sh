#!/bin/bash
# Stage 2 of the rootfs build: install packages into the arm64 rootfs.
set -e
HERE="$(cd "$(dirname "$0")" && pwd)"
PKGS=$(grep -vE '^\s*(#|$)' "$HERE/packages.list" | tr '\n' ' ')
echo "installing: $PKGS"
DEBIAN_FRONTEND=noninteractive bash "$HERE/e5-chroot.sh" \
  "export DEBIAN_FRONTEND=noninteractive; apt-get -o APT::Sandbox::User=root -y --no-install-recommends install $PKGS"
echo "INSTALL-DONE rc=$?"

# The build tree is reused between builds and apt never removes a package that
# stopped being asked for, so anything dropped from packages.list stays in the
# image.  NetworkManager was the one that mattered: still installed, it was also
# still enabled by an older configure-rootfs, and it autoconnects on sipa_dummy0
# -- holding network-online.target for minutes and timing the hotspot's start
# script out.  Purge by name; the autoremove afterwards takes its dependencies.
DROPPED="network-manager network-manager-l10n plasma-nm plasma-welcome ttyd"
echo "purging dropped: $DROPPED"
DEBIAN_FRONTEND=noninteractive bash "$HERE/e5-chroot.sh" \
  "export DEBIAN_FRONTEND=noninteractive; apt-get -o APT::Sandbox::User=root -y purge $DROPPED 2>&1 | tail -3 || true; apt-get -o APT::Sandbox::User=root -y --purge autoremove 2>&1 | tail -2 || true"
echo "PURGE-DONE rc=$?"
