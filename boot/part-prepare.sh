# Destructive first stage, activated by a device-bound boot command line.
# Userdata is never read/mounted. The stock recovery owns formatting/encryption.
part_prepare() {
    local request token cid node start previous target need bc extra dev disk u root_start mark actual rc part_rejected
    request=$(sed -n 's/.* e5.part_prepare=\([^ ]*\).*/\1/p' /proc/cmdline)
    [ -n "$request" ] || return 0
    . /etc/part-progress.sh
    part_progress_start
    echo '1/3 verifying destructive partition plan' > /run/part-status
    # Nothing is written until the plan has passed every check.  A request that
    # fails one is not a failure of this boot: the device must go on and boot
    # what it would have booted without the request at all (Android), instead of
    # parking in the initramfs.  part_reject only marks the failure and stops the
    # progress heartbeat -- a `return` inside it would return from the helper, not
    # from here -- and the gate after the checks is what leaves this function.
    # Only a failure after the first destructive write returns 1, which boot/init
    # turns into part_fail and a wait for inspection.
    part_reject() {
        [ -n "${part_rejected:-}" ] && return 0
        part_rejected=1
        part_stop
        log "stage=part-prepare rejected-request"
        return 0
    }
    # Colon-delimited literals only; never source/eval a request.
    IFS=: read -r token cid node start previous target need bc extra <<EOF
$request
EOF
    [ -z "$extra" ] && [ "${#token}" = 32 ] && [ "${#cid}" = 32 ] && [ "${#bc}" = 64 ] || part_reject
    case "$token$cid$bc" in *[!0-9a-f]*) part_reject ;; esac
    case "$node" in mmcblk[0-9]p[0-9]*) ;; *) part_reject ;; esac
    case "$node" in *[!a-z0-9]*) part_reject ;; esac
    for actual in "$start" "$previous" "$target" "$need"; do
        case "$actual" in ''|0*|*[!0-9]*) part_reject ;; esac
        [ "${#actual}" -le 12 ] || part_reject
    done
    dev=/dev/$node disk=/dev/${node%p*}
    [ -b "$dev" ] && [ -b "$disk" ] && [ -b "$misc" ] || part_reject
    [ "$(cat /sys/class/block/${node%p*}/device/cid)" = "$cid" ] || part_reject
    grep -qx PARTNAME=userdata /sys/class/block/$node/uevent || part_reject
    [ "$(cat /sys/class/block/$node/start)" = "$start" ] || part_reject
    [ "$(cat /sys/class/block/$node/size)" = "$previous" ] || part_reject
    [ -z "$(ls -A /sys/class/block/$node/holders)" ] || part_reject
    awk -v n="$(cat /sys/class/block/$node/dev)" '$3 == n {yes=1} END {exit !yes}' /proc/self/mountinfo && part_reject
    case "$target$need$previous" in
        *[!0-9]*) part_reject ;;
        *) [ "$target" -ge 4194304 ] && [ "$need" -ge 4194304 ] &&
               [ "$((target + need))" -le "$previous" ] || part_reject ;;
    esac
    for u in /sys/class/block/${node%p*}p*/uevent; do
        grep -qx PARTNAME=e5root "$u" && part_reject
    done
    [ -z "$part_rejected" ] || return 0
    # From here on the disk is modified, so the safety timer must not reboot
    # into a half-prepared layout, and a failure below is a real failure.
    touch /run/stay
    # Prepare the stock recovery message before changing geometry.  BCB occupies
    # bytes 0..2047 (AOSP bootloader_message: command 32 + status 32 + recovery
    # 768 + stage 32 + reserved 1184); the A/B boot control at 2048 is preserved
    # separately.  The vendor flashing tool's erase-userdata writes the same
    # block, zeroed in full -- 0x800 bytes with "boot-recovery" at 0 and
    # "recovery\n--wipe_data\n" at 0x40.
    dd if=/dev/zero of=/run/part-bcb bs=2048 count=1 2>/dev/null || return 1
    printf 'boot-recovery' | dd of=/run/part-bcb conv=notrunc 2>/dev/null || return 1
    printf 'recovery\n--wipe_data\n--reason=e5-part-prepare\n' |
        dd of=/run/part-bcb bs=1 seek=64 conv=notrunc 2>/dev/null || return 1
    printf '%b' "$(echo "$bc" | sed 's/../\\x&/g')" > /run/part-android-bc
    [ "$(wc -c < /run/part-android-bc)" = 32 ] || return 1
    echo '2/3 rebuilding userdata and reserving OpenWrt partition' > /run/part-status
    /usr/bin/ucode /usr/share/e5-gpt carve-userdata "$disk" "$target" "$need" "$previous" > /run/part-carve.log 2>&1 || return 1
    root_start=$((start + target))
    actual=$(/usr/bin/ucode /usr/share/e5-gpt list "$disk") || return 1
    [ "$(echo "$actual" | awk '$4 == "e5root" {print $2, $3}')" = "$root_start $((root_start + need - 1))" ] || return 1
    # A durable transaction marker belongs to the new root, not erased /data.
    # A second boot cannot repeat the carve: the old geometry check fails.
    printf 'E5-PART-PREPARED-V2 %s\n' "$token" > /run/part-prepared
    dd if=/dev/zero of="$disk" bs=4096 seek=$((root_start / 8)) count=1 conv=notrunc,fsync || return 1
    dd if=/run/part-prepared of="$disk" bs=512 seek="$root_start" conv=notrunc,fsync || return 1
    echo '3/3 rebooting to stock recovery to format Android data' > /run/part-status
    dd if=/run/part-bcb of="$misc" bs=1 count=2048 conv=notrunc,fsync || return 1
    dd if=/run/part-android-bc of="$misc" bs=1 seek=2048 count=32 conv=notrunc,fsync || return 1
    dd if="$misc" of=/run/part-bcb-check bs=1 count=2048 2>/dev/null
    dd if="$misc" of=/run/part-bc-check bs=1 skip=2048 count=32 2>/dev/null
    cmp -s /run/part-bcb /run/part-bcb-check && cmp -s /run/part-android-bc /run/part-bc-check || return 1
    sync; persist
    sleep 3
    reboot -f
    return 1
}
