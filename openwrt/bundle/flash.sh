#!/bin/sh
# 荣悦 E5 OpenWrt 一键刷入 (macOS / Linux): the flasher is flash.py.
cd "$(dirname "$0")" || exit 1
command -v python3 >/dev/null || { echo "Python 3 is needed" >&2; exit 1; }
exec python3 flash.py "$@"
