#!/system/bin/sh
# E5/T551M/M8 native Magisk TF deployment. Use the existing first partition
# or an unpartitioned whole card, at full capacity. No OTA partition reserve.
# Android loop resolution follows MU300's desktop/android-loop.sh pattern,
# MIT, Copyright (c) 2026 dikeckaan; see docs/MU300-INSTALLER-LICENSE in packages.
set -eu
fail() { echo "E5-TF-ERROR: $*" >&2; exit 1; }
sha() { local result; result=$(sha256sum "$1") || return 1; printf '%s\n' "${result%% *}"; }
free_loop() { . "$P/files/android-loop.sh"; desktop_free_loop; }
stage() {
    printf '%s\n' "$1" > "$STATE/stage"
    echo "[TF] $1"
    shift
    "$@"
}
preflight() {
    cd "$P"
    sha256sum -c files/SHA256SUMS > "$STATE/package-check.log"
    . "$P/files/tf-install.env"
    [ "$(id -u)" = 0 ] || fail 'root required'
    [ "$(getprop ro.product.model)" = "$ANDROID_MODEL" ] || fail 'wrong device model for this package'
    [ "$(getprop ro.boot.slot_suffix)" = _a ] || fail 'Android A / OpenWrt B only'
    [ "$(getprop ro.boot.verifiedbootstate)" = orange ] || fail 'bootloader must be unlocked'
    [ -s "$P/files/ext4-tools.tar" ] || fail 'missing bundled ext4 tools'
    tar -tf "$P/files/ext4-tools.tar" > "$STATE/ext4-tools.list"
    for tool in lib/ld-musl-aarch64.so.1 usr/sbin/e2fsck usr/sbin/resize2fs ext4-geometry.sh SHA256SUMS; do
        grep -qx "$tool" "$STATE/ext4-tools.list" || fail "missing ext4 tool: $tool"
    done
    [ ! -L /data/e5linux ] || fail 'unsafe boot selector directory'
    for selector in boot-os boot-os-next openwrt-default-boot; do
        [ ! -L "/data/e5linux/$selector" ] || fail 'unsafe boot selector'
    done
    [ -b /dev/block/by-name/boot_b ] && [ -b /dev/block/by-name/misc ] || fail 'missing boot partitions'
    [ "$(blockdev --getsize64 /dev/block/by-name/boot_b)" = "$BOOT_BYTES" ] || fail 'boot partition size mismatch'
    "$P/files/e5-bootctl" check
    sh "$P/files/android-bootchain.sh" check
    command -v mount >/dev/null
    emmc=$(readlink -f /dev/block/by-name/misc); emmc=${emmc##*/}; emmc=${emmc%p*}
    cards=
    for sysdev in /sys/class/block/mmcblk*; do
        node=${sysdev##*/}
        echo "$node" | grep -Eq '^mmcblk[0-9]+$' || continue
        [ "$node" != "$emmc" ] || continue
        [ -b "/dev/block/$node" ] && cards="$cards $node"
    done
    set -- $cards
    [ "$#" = 1 ] || fail 'expected exactly one removable TF card'
    SD=/dev/block/$1
    [ "$(cat /sys/class/block/$1/ro)" = 0 ] || fail 'TF card is read-only'
    PART=$(sh "$P/files/android-tf.sh" target "$SD")
    [ "$(blockdev --getsize64 "$PART")" -ge "$RAW_BYTES" ] || fail 'TF target is too small'
    free=$(df -Pk "$STATE" | awk 'END {print $4}')
    [ "$free" -ge $((RAW_BYTES / 1024 + BOOT_BYTES / 1024 + 262144)) ] || fail 'insufficient Android temporary space (raw image + boot backup + 256 MiB required)'
    echo "[TF] Model $ANDROID_MODEL, target $PART; SELECTED TF TARGET WILL BE ERASED (no repartitioning)"
}
prepare_firmware() {
    gzip -dc "$P/files/openwrt.ext4.gz" > "$STATE/convert.ext4"
    [ "$(stat -c %s "$STATE/convert.ext4")" = "$RAW_BYTES" ] || fail 'image size mismatch'
    [ "$(sha "$STATE/convert.ext4")" = "$RAW_SHA256" ] || fail 'image hash mismatch'
    mkdir "$STATE/view"
    LOOP=$(free_loop)
    losetup "$LOOP" "$STATE/convert.ext4"
    LOOP_ATTACHED=1
    mount -t ext4 "$LOOP" "$STATE/view"
    VIEW_MOUNTED=1
    view=$STATE/view
    [ "$(cat "$view/etc/e5/device-profile")" = "$PROFILE" ] || fail 'rootfs profile mismatch'
    [ -x "$view/usr/bin/python3" ] || fail 'rootfs Python is required for local firmware conversion'
    mkdir -p "$view/tmp/e5-convert/raw" "$view/tmp/e5-convert/tools"
    raw=$view/tmp/e5-convert/raw
    for name in wcnmodem.bin bt_configure_pskey.xpe.ini bt_configure_rf.xpe.ini; do
        cp "/odm/firmware/$name" "$raw/$name"
    done
    cp /mnt/vendor/btmac.txt "$raw/"
    cp /odm/firmware/wifi_board_config*.ini "$raw/"
    for name in audio_structure.xml dsp_vbc.xml cvs.xml; do
        cp "/odm/etc/audio_params/sprd/$name" "$raw/"
    done
    for entry in /odm/firmware/gnssmodem.bin /vendor/firmware/aw87xxx_acf.bin /vendor/firmware/tsx_data /odm/etc/audio_params/sprd/codec.xml; do
        [ ! -f "$entry" ] || cp -L "$entry" "$raw/"
    done
    dd if=/dev/block/by-name/l_agdsp_a of="$raw/l_agdsp_a.img" bs=1048576 count=6
    for entry in /data/misc/apexdata/com.android.wifi/WifiConfigStoreSoftAp.xml /data/misc/wifi/WifiConfigStoreSoftAp.xml; do
        if [ -s "$entry" ]; then cp "$entry" "$raw/android-hotspot.xml"; break; fi
    done
    cp "$P/scripts/tools/sprd-bt-config.py" "$view/tmp/e5-convert/tools/"
    cp -R "$P/scripts/tools/vbc-profile" "$view/tmp/e5-convert/tools/"
    cp "$P/files/magisk-firmware.py" "$view/tmp/e5-convert/convert.py"
    chroot "$view" /usr/bin/python3 /tmp/e5-convert/convert.py /tmp/e5-convert/raw /tmp/e5-convert/firmware /tmp/e5-convert/tools "$DEFAULT_SSID"
    cp "$view/tmp/e5-convert/firmware/install.conf" "$STATE/install.conf"
    . "$STATE/install.conf"
    echo "[TF] Hotspot / 热点：$E5_WIFI_SSID; key / 密码：$E5_WIFI_KEY"
    (cd "$view/tmp/e5-convert/firmware" && tar -cf "$STATE/firmware.tar" lib)
    umount "$view"
    VIEW_MOUNTED=0
    losetup -d "$LOOP"
    LOOP_ATTACHED=0
    LOOP=
    rm "$STATE/convert.ext4"
    E5_COLLECT_WORK="$STATE/collect" sh "$P/files/collect-device-files.sh" "$STATE/device-files.tar" "$STATE/firmware.tar"
    [ -s "$STATE/device-files.tar" ] || fail 'device firmware was not collected'
    # Preserve the old Linux/Android B boot before any destructive TF operation.
    dd if=/dev/block/by-name/boot_b of="$STATE/boot_b.before.img" bs=1048576
    [ "$(stat -c %s "$STATE/boot_b.before.img")" = "$BOOT_BYTES" ] || fail 'incomplete boot backup'
    saved_boot=$(sha "$STATE/boot_b.before.img")
    live_boot=$(sha /dev/block/by-name/boot_b)
    [ "$saved_boot" = "$live_boot" ] || fail 'boot backup readback mismatch'
}
release_card() {
    numbers=$STATE/card-devices
    : > "$numbers"
    name=${SD##*/}
    for node in /sys/class/block/"$name" /sys/class/block/"$name"p*; do
        [ ! -r "$node/dev" ] || cat "$node/dev" >> "$numbers"
    done
    [ -s "$numbers" ] || fail 'missing TF device numbers'
    sm list-volumes all > "$STATE/volumes"
    while read -r volume status rest; do
        [ "$status" = mounted ] || continue
        case $volume in public:[0-9]*,[0-9]*|private:[0-9]*,[0-9]*) ;; *) continue ;; esac
        number=${volume#*:}; number=$(echo "$number" | tr ',' ':')
        if grep -qx "$number" "$numbers"; then sm unmount "$volume"; fi
    done < "$STATE/volumes"
    cat /proc/self/mountinfo /proc/1/mountinfo > "$STATE/mounts"
    while read -r id parent number rest; do
        if grep -qx "$number" "$numbers"; then fail 'Android still mounts this TF card; no partition was changed'; fi
    done < "$STATE/mounts"
    for holder in /sys/class/block/"$name"/holders/* /sys/class/block/"$name"p*/holders/*; do
        [ ! -e "$holder" ] || fail 'TF card still has active mapped devices; no partition was changed'
    done
    # Snapshot both GPT regions as recovery evidence. The partition table is unchanged;
    # these copies are diagnostic evidence, not a backup of the erased target.
    sectors=$(blockdev --getsz "$SD")
    dd if="$SD" of="$STATE/tf-first.bin" bs=512 count=34
    dd if="$SD" of="$STATE/tf-last.bin" bs=512 skip=$((sectors-33)) count=33
}
write_root() {
    sh "$P/files/android-bootchain.sh" sync
    [ "$(sh "$P/files/android-tf.sh" target "$SD")" = "$PART" ] || fail 'TF target changed'
    part=$PART
    gzip -dc "$P/files/openwrt.ext4.gz" > "$part"
    sync
    blockdev --flushbufs "$part"
    dd if="$part" of="$STATE/root.readback" bs=1048576 count=$(( (RAW_BYTES + 1048575) / 1048576 ))
    [ "$(stat -c %s "$STATE/root.readback")" -ge "$RAW_BYTES" ] || fail 'short TF readback'
    truncate -s "$RAW_BYTES" "$STATE/root.readback"
    [ "$(sha "$STATE/root.readback")" = "$RAW_SHA256" ] || fail 'TF image readback mismatch'
    rm "$STATE/root.readback"
    sh "$P/files/android-tf.sh" grow "$part" "$P/files/ext4-tools.tar" "$STATE/ext4-tools"
    mount -t ext4 "$part" "$STATE/view"
    VIEW_MOUNTED=1
    tar -xf "$STATE/device-files.tar" -C "$STATE/view"
    mkdir -p "$STATE/view/etc/e5"
    cp "$STATE/install.conf" "$STATE/view/etc/e5/install.conf"
    chmod 600 "$STATE/view/etc/e5/install.conf"
    echo "e5-openwrt-sd $BOOT_SHA256" > "$STATE/view/etc/e5/sd-root"
    sha "$STATE/device-files.tar" > "$STATE/view/etc/e5/device-files.stamp"
    chroot "$STATE/view" /bin/busybox find /lib/firmware /opt/e5/android -type f -exec /bin/busybox sha256sum '{}' \; > "$STATE/firmware.sha256"
    for file in /etc/e5/install.conf /etc/e5/sd-root; do
        chroot "$STATE/view" /bin/busybox sha256sum "$file" >> "$STATE/firmware.sha256"
    done
    sync
    umount "$STATE/view"
    VIEW_MOUNTED=0
    blockdev --flushbufs "$part"
    mount -t ext4 -o ro,noload "$part" "$STATE/view"
    VIEW_MOUNTED=1
    chroot "$STATE/view" /bin/busybox sha256sum -c < "$STATE/firmware.sha256" > "$STATE/root-check.log"
    for file in /sbin/init /opt/e5/android/vendor/bin/modem_control; do
        chroot "$STATE/view" /bin/busybox test -x "$file"
    done
    chroot "$STATE/view" /bin/busybox true
    umount "$STATE/view"
    VIEW_MOUNTED=0
}
write_boot() {
    # Current Android A and NV are never written. Misc is committed only after
    # root + firmware + complete boot readback validation.
    dd if="$P/files/boot.img" of=/dev/block/by-name/boot_b bs=1048576 conv=fsync
    blockdev --flushbufs /dev/block/by-name/boot_b
    [ "$(sha /dev/block/by-name/boot_b)" = "$BOOT_SHA256" ] || fail 'boot_b verification failed; do not boot Linux'
}
arm_linux() {
    mkdir -p /data/e5linux
    [ ! -L /data/e5linux ] || fail 'unsafe boot selector directory'
    for name in boot-os openwrt-default-boot; do
        [ ! -L "/data/e5linux/$name" ] || fail 'unsafe boot selector'
    done
    echo sd > /data/e5linux/boot-os
    rm -f /data/e5linux/boot-os-next
    echo linux > /data/e5linux/openwrt-default-boot
    sync
    "$P/files/e5-bootctl" arm "$STATE/boot-control.before.bin"
}
install_tf() {
    stage 'Package, model, boot chain and capacity checks / 预检' preflight
    stage 'Prepare and convert this device firmware / 提取并转换本机固件' prepare_firmware
    stage 'Release TF card / 释放 TF 卡' release_card
    stage 'Install and reopen root read-only / 写系统并只读复验' write_root
    stage 'Write and verify boot_b / 写入并校验内核' write_boot
    stage 'Select OpenWrt / 设置启动目标' arm_linux
    echo complete > "$STATE/stage"
    echo 'E5-TF-INSTALL-OK: reboot manually / 请手动重启'
}
if [ "${E5_TF_LIB:-0}" = 1 ]; then return 0; fi
P=${E5_PACKAGE:?}
BASE=/data/adb/e5-tf-install
BB=$P/files/busybox
[ -x "$BB" ] && [ ! -L "$BB" ] || fail 'missing bundled installer BusyBox'
[ ! -L "$BASE" ] || fail 'unsafe installer directory'
mkdir -p "$BASE"
chmod 700 "$BASE"
lock=$BASE/install-$(cat /proc/sys/kernel/random/boot_id).lock
mkdir "$lock" || fail 'another install is active, or a previous failed install needs inspection'
STATE=$(mktemp -d "$BASE/run.XXXXXX")
chmod 700 "$STATE"
mkdir "$STATE/bin"
"$BB" --install -s "$STATE/bin"
export PATH="$STATE/bin:/system/bin:$PATH"
heartbeat=
LOOP=
LOOP_ATTACHED=0
VIEW_MOUNTED=0
cleanup() {
    result=$?
    trap - EXIT HUP INT TERM
    [ -z "$heartbeat" ] || { kill "$heartbeat" 2>/dev/null || true; wait "$heartbeat" 2>/dev/null || true; }
    if [ "$VIEW_MOUNTED" = 1 ]; then umount "$STATE/view" || exit 1; fi
    [ "$LOOP_ATTACHED" = 0 ] || losetup -d "$LOOP" || exit 1
    if [ "$result" = 0 ]; then
        rm -f "$STATE/device-files.tar" "$STATE/install.conf"
        rmdir "$lock"
    else
        echo "[TF] FAILED: log/backup $STATE; do not retry until checking device state" >&2
    fi
    exit "$result"
}
trap cleanup EXIT
trap 'exit 130' HUP INT TERM
echo "[TF] Logs and backups / 日志和备份：$STATE"
owner=$$
(elapsed=0; while sleep 10; do kill -0 "$owner" 2>/dev/null || exit 0; elapsed=$((elapsed+10)); echo "[TF] $(cat "$STATE/stage" 2>/dev/null): ${elapsed}s elapsed"; done) &
heartbeat=$!
install_tf
