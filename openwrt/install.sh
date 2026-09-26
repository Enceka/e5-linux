#!/bin/bash
# Install the OpenWrt tree on an E5 that is running Debian, over the USB LAN.
#
#   openwrt/install.sh [--try|--switch] [TARBALL]
#
#   (none)     install only
#   --try      install, then boot OpenWrt once (the boot after returns to Debian)
#   --switch   install, then make OpenWrt the default and boot it
#
# The device fetches the tarball and openwrt/device-install.sh from a
# short-lived HTTP server on this host (E5_HOST_IP, default 192.168.9.2: the
# address the E5 gives the USB host) and runs the script over telnet
# (tools/e5-telnet.py, the Debian image's root/root login).
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
TOP="$(cd "$HERE/.." && pwd)"
MODE=
case "${1:-}" in --try|--switch) MODE=$1; shift ;; esac
T=${1:-$(ls -t "$TOP"/out/openwrt/e5-openwrt-*-rootfs.tar.gz 2>/dev/null | head -1)}
[ -f "$T" ] || { echo "no tarball -- run openwrt/build-rootfs.sh first" >&2; exit 1; }
IP=${E5_HOST_IP:-192.168.9.2}
PORT=${E5_HTTP_PORT:-8791}

SERVE=$(mktemp -d)
trap 'kill $SRV 2>/dev/null; rm -rf "$SERVE"' EXIT
ln -s "$T" "$SERVE/rootfs.tar.gz"
cp "$HERE/device-install.sh" "$SERVE/device-install.sh"
python3 -m http.server "$PORT" --bind "$IP" -d "$SERVE" >/dev/null 2>&1 &
SRV=$!
sleep 1

echo "== installing $(basename "$T") ($(du -h "$T" | cut -f1))"
E5_TELNET_WAIT=${E5_TELNET_WAIT:-900} python3 "$TOP/tools/e5-telnet.py" \
    "wget -q -O /tmp/e5-openwrt.tar.gz http://$IP:$PORT/rootfs.tar.gz && wget -q -O /tmp/e5-openwrt-install.sh http://$IP:$PORT/device-install.sh && sh /tmp/e5-openwrt-install.sh /tmp/e5-openwrt.tar.gz $MODE; rm -f /tmp/e5-openwrt.tar.gz"
