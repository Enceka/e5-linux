#!/bin/bash
# e5-at.sh [-t secs] cmd... : talk to the E5 modem AT channel (MU300-style).
DEV=${E5_AT_DEV:-/dev/stty_nr1}
T=${E5_AT_TIMEOUT:-5}
stty -F "$DEV" raw -echo 2>/dev/null
exec 3<>"$DEV"
while IFS= read -r -t 0.3 line <&3; do :; done
for c in "$@"; do
  printf '%s\r' "$c" >&3
  end=$(( $(date +%s) + T ))
  while [ "$(date +%s)" -lt "$end" ]; do
    IFS= read -r -t 1 line <&3 || continue
    line=${line%$'\r'}
    [ -z "$line" ] && continue
    echo "$line"
    case "$line" in OK|ERROR|+CME\ ERROR*|+CMS\ ERROR*|CONNECT*) break ;; esac
  done
done
exec 3>&-
