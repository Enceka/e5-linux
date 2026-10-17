# Shared by the offline TF and internal-partition installers.
# Call only after successful resize2fs and read-only e2fsck. A tiny final
# block group cannot always hold its metadata; resize2fs may omit that group.
ext4_verify_grown() {
    ext4_dev=$1 ext4_sectors=$2
    case "$ext4_sectors" in ''|0|*[!0-9]*) return 1;; esac
    ext4_magic=$(od -An -tx2 -j 1080 -N 2 "$ext4_dev" | tr -d ' \n')
    ext4_blocks=$(od -An -tu4 -j 1028 -N 4 "$ext4_dev" | tr -d ' \n')
    ext4_high=$(od -An -tu4 -j 1360 -N 4 "$ext4_dev" | tr -d ' \n')
    ext4_shift=$(od -An -tu4 -j 1048 -N 4 "$ext4_dev" | tr -d ' \n')
    ext4_group=$(od -An -tu4 -j 1056 -N 4 "$ext4_dev" | tr -d ' \n')
    [ "$ext4_magic" = ef53 ] && [ "$ext4_shift" = 2 ] && [ "$ext4_high" = 0 ] || return 1
    case "$ext4_blocks:$ext4_group" in *[!0-9:]*|:*|*:) return 1;; esac
    [ "$ext4_group" -gt 0 ] && [ "$ext4_group" -le 32768 ] || return 1
    [ "$((ext4_group & (ext4_group - 1)))" = 0 ] || return 1
    ext4_want=$((ext4_sectors / 8))
    [ "$ext4_blocks" -gt 0 ] && [ "$ext4_blocks" -le "$ext4_want" ] || return 1
    # Still reject an old 2 GiB filesystem on a much larger target. Only the
    # exact requested size or its last complete block group is admissible.
    if [ "$ext4_blocks" != "$ext4_want" ]; then
        [ "$ext4_blocks" = "$((ext4_want / ext4_group * ext4_group))" ] || return 1
    fi
    printf 'EXT4 geometry verified: %s/%s blocks; unused tail %s blocks\n' \
        "$ext4_blocks" "$ext4_want" "$((ext4_want - ext4_blocks))"
}
