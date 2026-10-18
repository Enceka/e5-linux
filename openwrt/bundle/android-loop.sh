# Android stores block nodes under /dev/block, whereas BusyBox losetup -f
# prints /dev/loopN. Source this helper before attaching an image.
desktop_loop_is_block() { [ -b "$1" ]; }
desktop_loop_sysdev() { cat "/sys/class/block/$1/dev"; }

desktop_free_loop() {
    local candidate name index devno major minor node tries=0
    candidate=$(losetup -f) || return 1
    case "$candidate" in /dev/loop[0-9]*|/dev/block/loop[0-9]*) name=${candidate##*/} ;;
        *) echo 'cannot identify a free loop device' >&2; return 1 ;;
    esac
    index=${name#loop}
    case "$index" in ''|*[!0-9]*|0[0-9]*) echo 'invalid loop index' >&2; return 1 ;; esac
    [ "${#index}" -le 6 ] && [ "$index" -le 131071 ] || return 1
    # A new kernel loop can precede its ueventd node. /data is nodev, so
    # never create a fallback there: use only the canonical Android /dev node.
    while :; do
        if desktop_loop_is_block "/dev/block/$name"; then
            echo "/dev/block/$name"; return 0
        elif desktop_loop_is_block "$candidate"; then
            echo "$candidate"; return 0
        fi
        [ "$tries" -lt 10 ] || break
        tries=$((tries + 1)); sleep 0.1
    done
    devno=$(desktop_loop_sysdev "$name") || return 1
    major=${devno%:*}; minor=${devno#*:}
    [ "$major" = 7 ] && [ "$minor" = "$((index * 8))" ] || {
        echo 'invalid loop device identity' >&2; return 1;
    }
    node=/dev/block/$name
    [ -d /dev/block ] || { echo 'Android /dev/block is unavailable' >&2; return 1; }
    [ ! -e "$node" ] && [ ! -L "$node" ] || {
        desktop_loop_is_block "$node" && { echo "$node"; return 0; }
        echo 'loop node path is occupied by a non-block entry' >&2; return 1;
    }
    # ueventd may win this creation race. Leave canonical nodes to Android;
    # they are not per-install aliases and are removed normally on reboot.
    mknod -m 600 "$node" b "$major" "$minor" 2>/dev/null || desktop_loop_is_block "$node" || return 1
    desktop_loop_is_block "$node" || return 1
    if command -v restorecon >/dev/null 2>&1; then restorecon "$node" || return 1; fi
    echo "$node"
}
