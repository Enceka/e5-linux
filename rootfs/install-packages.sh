#!/bin/bash
# Stage 2 of the rootfs build: install packages into the arm64 rootfs.
set -e
HERE="$(cd "$(dirname "$0")" && pwd)"
PKGS=$(grep -vE '^\s*(#|$)' "$HERE/packages.list" | tr '\n' ' ')
echo "installing: $PKGS"
DEBIAN_FRONTEND=noninteractive bash "$HERE/e5-chroot.sh" \
  "export DEBIAN_FRONTEND=noninteractive; apt-get -o APT::Sandbox::User=root -y --no-install-recommends install $PKGS"
echo "INSTALL-DONE rc=$?"
