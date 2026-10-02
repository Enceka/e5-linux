#!/bin/sh
exec python3 "$(CDPATH= cd -- "$(dirname "$0")" && pwd)/flash.py" "$@"
