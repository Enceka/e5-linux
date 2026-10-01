#!/bin/sh
# Install (or update) OpenWrt's own root image, e5linux/openwrt.ext4 on
# userdata, which boot/init starts when it is chosen (e5-os openwrt) or is the
# only system there.  Runs on the device as root, in whatever Linux it runs:
# Debian, OpenWrt in the Debian image's /openwrt, or the standalone OpenWrt
# itself; openwrt/install-standalone.sh sends it.
#
#   device-install-image.sh IMAGE.ext4.gz|URL [--try|--switch]
#
# On an SD card system (flash.py's default install, /etc/e5/sd-root) the update
# goes onto the card instead, and userdata is not touched: the new image is
# written into another root partition of the card (made in the card's free space
# the first time, /usr/libexec/e5-gpt), the configuration and the device's files
# copied in as below, and it is marked with the next generation and a trial --
# boot/init boots the highest generation, and a trial that does not come up
# leaves the next boot to the one before it.  E5_IMAGE_SIZE (bytes, unpacked) is
# needed with a URL.  --try and --switch do not apply there.
#
# The image is unpacked next to the installed one (openwrt.ext4.part) and
# renamed at the end.  The running standalone OpenWrt cannot be replaced under
# itself: its update goes to openwrt.ext4.new, which the initramfs swaps in at
# the next boot (the old one stays as openwrt.ext4.old until the next update).
#
# The new image keeps the configuration of an installed OpenWrt -- the running
# one, else the installed image, else the Debian image's /openwrt -- as
# openwrt/device-install.sh does (/etc/config, passwords, SSH keys, /etc/e5,
# the traffic records); packages added with apk are not carried over.  With no
# OpenWrt before it, it takes Debian's APN and hotspot for the first boot.
# Linux as the default boot and the misc blocks come along either way.
#
# --try boots OpenWrt once, --switch makes it the default; both reboot.
set -eu
SRC=${1:?image}
MODE=${2:-}
case "$MODE" in ''|--try|--switch) ;; *) echo "unknown option $MODE" >&2; exit 2 ;; esac

# The configuration of the OpenWrt at $1 into the new root $2 (/etc/config,
# passwords, SSH keys, /etc/e5, the traffic records, the info screen's apps),
# the new image's own version files kept.
keep_config() {
    local from=$1 N=$2 f p
    echo "== keeping the configuration of $from"
    for f in image-version image-form build-time; do
        cp "$N/etc/e5/$f" "/tmp/e5-img.$f" 2>/dev/null || rm -f "/tmp/e5-img.$f"
    done
    for p in etc/config etc/shadow etc/passwd etc/group etc/dropbear etc/e5 etc/e5linux \
             etc/uhttpd.crt etc/uhttpd.key etc/vnstat etc/e5-infoscreen; do
        [ -e "$from/$p" ] || continue
        if [ -d "$from/$p" ] && [ -d "$N/$p" ]; then
            cp -a "$from/$p/." "$N/$p/"
        else
            rm -rf "$N/$p"
            cp -a "$from/$p" "$N/$p"
        fi
    done
    for f in image-version image-form build-time; do
        rm -f "$N/etc/e5/$f"
        [ -f "/tmp/e5-img.$f" ] && mv "/tmp/e5-img.$f" "$N/etc/e5/$f"
    done
}

# The device's own files (firmware, the Android vendor subset) as a tar on
# stdout, read through a plain (non-recursive) bind of the root that has them --
# the Debian image for the directory form, / otherwise: the vendor chroot has
# /proc, /sys and /dev mounted inside it while the baseband runs, and a tar of
# the live tree walked into those.  Nothing (and false) when this system has none.
VIEW=/tmp/e5-img.view
device_files_tar() {
    local src=/ list rc=1
    [ -f /mnt/e5-disk/usr/lib/firmware/wcnmodem.bin ] && src=/mnt/e5-disk
    mkdir -p "$VIEW" && mount --bind "$src" "$VIEW"
    if [ -f "$VIEW/lib/firmware/wcnmodem.bin" ] && [ -x "$VIEW/opt/e5/android/vendor/bin/modem_control" ]; then
        list=$(cd "$VIEW" && for f in lib/firmware/wcnmodem.bin lib/firmware/gnssmodem.bin \
                   lib/firmware/wifi_board_config*.ini lib/firmware/tsx_data lib/firmware/l_agdsp_a.img \
                   lib/firmware/audio_structure lib/firmware/dsp_vbc lib/firmware/cvs \
                   lib/firmware/aw87xxx_acf.bin lib/firmware/sprd opt/e5/android; do
                   [ -e "$f" ] && echo "$f"; done)
        (cd "$VIEW" && tar -cf - $list) && rc=0
    fi
    umount "$VIEW"
    return $rc
}

# ------------------------------------------------------------ the SD card
card_update() {
    local rootdev disk curn cur gpt size need t n start end name g best bestgen lo next tries
    rootdev=$(awk '$2 == "/" && $1 ~ /^\/dev\/mmcblk[0-9]+p[0-9]+$/ { d = $1 } END { print d }' /proc/mounts)
    [ -n "$rootdev" ] || { echo "the card's root partition is not mounted as /" >&2; exit 1; }
    disk=${rootdev%p*} curn=${rootdev##*p}
    gpt=$(dirname "$0")/e5-gpt
    [ -f "$gpt" ] || gpt=/usr/libexec/e5-gpt
    [ -f "$gpt" ] || { echo "no e5-gpt (the card's partition table)" >&2; exit 1; }
    cur=$(cat /etc/e5/sd-gen 2>/dev/null || :); case "$cur" in ''|*[!0-9]*) cur=0 ;; esac
    # On a registered card this updater owns OpenWrt's slots only. Verify the
    # running partition's registration before changing any table or root.
    local meta=/mnt/e5-boot current_uuid registry_slot= registry_target=
    if [ -f "$meta/format" ]; then
        . /opt/e5/e5-sd-registry
        sd_registry_valid "$meta" || { echo "invalid SD system registry" >&2; exit 1; }
        [ "$(cat /etc/e5/sd-system 2>/dev/null || echo openwrt)" = openwrt ] || {
            echo "the OpenWrt updater cannot update a foreign system" >&2; exit 1;
        }
        current_uuid=$(ucode "$gpt" uuid "$disk" "$curn") || exit 1
        for registry_slot in a b; do
            [ "$(cat "$meta/systems/openwrt/$registry_slot" 2>/dev/null)" = "$current_uuid" ] || continue
            [ "$registry_slot" = a ] && registry_target=b || registry_target=a
            break
        done
        [ -n "$registry_target" ] || { echo "the current OpenWrt root is not registered" >&2; exit 1; }
    fi
    size=${E5_IMAGE_SIZE:-}
    if [ -z "$size" ]; then
        case "$SRC" in
            http://*|https://*) echo "E5_IMAGE_SIZE (the unpacked size) is needed with a URL" >&2; exit 2 ;;
        esac
        # (gzip's last four bytes: the unpacked size, modulo 4 GiB)
        size=$(tail -c 4 "$SRC" | od -An -tu4 | tr -d ' ')
    fi
    need=$(( (size + 511) / 512 ))
    echo "== the card: $disk, running from partition $curn (generation $cur), the image $((size >> 20)) MiB"

    # The partition to write: another root of the card (e5root*) that holds the
    # image -- the oldest generation, a failed trial or an unmarked one first;
    # never the running one, never a partition of another name.
    lo=$(losetup -f)
    best= bestgen=
    gen_at() {
        losetup -r -o $(($1 * 512)) "$lo" "$disk" 2>/dev/null || { echo -1; return; }
        mkdir -p "$OLD_ROOT"
        if mount -t ext4 -o ro,noload "$lo" "$OLD_ROOT" 2>/dev/null; then
            if [ -f "$OLD_ROOT/etc/e5/sd-system" ] &&
               [ "$(cat "$OLD_ROOT/etc/e5/sd-system")" != openwrt ]; then
                echo foreign
            elif [ ! -f "$OLD_ROOT/etc/openwrt_release" ]; then
                echo foreign
            elif [ ! -f "$OLD_ROOT/etc/e5/sd-root" ] || [ "$(cat "$OLD_ROOT/etc/e5/sd-trial" 2>/dev/null)" = 0 ]; then
                echo -1
            else
                g=$(cat "$OLD_ROOT/etc/e5/sd-gen" 2>/dev/null || :); case "$g" in ''|*[!0-9]*) g=0 ;; esac
                echo "$g"
            fi
            umount "$OLD_ROOT"
        else
            echo -1
        fi
        losetup -d "$lo"
    }
    t=$(ucode "$gpt" list "$disk") || exit 1
    while read -r n start end name; do
        [ "$n" = "$curn" ] && continue
        case "$name" in e5root*) ;; *) continue ;; esac
        [ $((end - start + 1)) -ge "$need" ] || continue
        g=$(gen_at "$start")
        [ "$g" != foreign ] || { echo "   partition $n ($name): foreign system, skipped"; continue; }
        echo "   partition $n ($name, $(( (end - start + 1) >> 11 )) MiB): generation $g"
        if [ -z "$best" ] || [ "$g" -lt "$bestgen" ]; then best="$n $start $end" bestgen=$g; fi
    done <<EOT
$t
EOT
    if [ -z "$best" ]; then
        # (room for a larger image later: 256 MiB past this one)
        n=2; while echo "$t" | grep -q " e5root$n\$"; do n=$((n + 1)); done
        best=$(ucode "$gpt" add "$disk" "e5root$n" $((need + 524288))) || exit 1
        echo "== a new root partition on the card: e5root$n ($best)"
    fi
    set -- $best
    n=$1 start=$2 end=$3
    [ $((start % 2048)) = 0 ] || { echo "partition $n does not start on a MiB" >&2; exit 1; }

    # the partition is not bootable while it is written: its superblock goes first
    echo "== writing the image into partition $n"
    dd if=/dev/zero of="$disk" bs=1048576 seek=$((start / 2048)) count=4 conv=fsync 2>/dev/null
    rm -f /tmp/e5-img.fail
    case "$SRC" in
        http://*|https://*) { wget -q -O - "$SRC" || touch /tmp/e5-img.fail; } | gunzip -c ;;
        *) gunzip -c "$SRC" ;;
    esac | dd of="$disk" bs=1048576 seek=$((start / 2048)) conv=fsync 2>/tmp/e5-img.dd ||
        { cat /tmp/e5-img.dd >&2; echo "writing the card failed" >&2; exit 1; }
    [ ! -e /tmp/e5-img.fail ] || { rm -f /tmp/e5-img.fail; echo "download failed" >&2; exit 1; }

    losetup -o $((start * 512)) "$lo" "$disk"
    mkdir -p "$NEW_ROOT"
    mount -t ext4 "$lo" "$NEW_ROOT" ||
        { losetup -d "$lo"; echo "the written partition does not mount" >&2; exit 1; }
    N=$NEW_ROOT
    trap 'umount "$NEW_ROOT" 2>/dev/null; losetup -d "$lo" 2>/dev/null' EXIT
    [ -x "$N/sbin/init" ] && [ -f "$N/etc/openwrt_release" ] || { echo "not an OpenWrt image" >&2; exit 1; }
    keep_config / "$N"
    if [ -n "$registry_target" ]; then
        # The new image may predate SD selection; keep the shared selector
        # until all released images carry registry format 1 support.
        cp /opt/e5/e5-os /opt/e5/e5-sd-registry "$N/opt/e5/"
        cp "$gpt" "$N/usr/libexec/e5-gpt"
    fi
    # (marked last, below: until then the partition is no candidate)
    rm -f "$N/etc/e5/sd-root" "$N/etc/e5/sd-trial"
    if [ ! -f "$N/lib/firmware/wcnmodem.bin" ]; then
        if device_files_tar > /tmp/e5-img.dft; then
            tar -xf /tmp/e5-img.dft -C "$N"
            sha256sum /tmp/e5-img.dft | cut -d' ' -f1 > "$N/etc/e5/device-files.stamp"
            echo "== the device's files copied in"
        else
            rm -f /tmp/e5-img.dft
            echo "the image has no firmware or vendor subset, and this system has none to give" >&2
            exit 1
        fi
        rm -f /tmp/e5-img.dft
    fi
    mkdir -p "$N/etc/e5linux"
    cp /run/e5linux/misc-bc-slot-a.bin /run/e5linux/misc-bc-slot-b-trial.bin "$N/etc/e5linux/" 2>/dev/null || true
    next=$((cur + 1))
    echo "$next" > "$N/etc/e5/sd-gen"
    echo 1 > "$N/etc/e5/sd-trial"
    cp /etc/e5/sd-root "$N/etc/e5/sd-root"
    echo openwrt > "$N/etc/e5/sd-system"
    ver=$(cat "$N/etc/e5/image-version" 2>/dev/null || echo "?")
    sync
    umount "$NEW_ROOT" && losetup -d "$lo"
    trap - EXIT
    if [ -n "$registry_target" ]; then
        uuid=$(ucode "$gpt" uuid "$disk" "$n") || exit 1
        printf '%s\n' "$uuid" > "$meta/systems/openwrt/.$registry_target.tmp"
        sync
        mv "$meta/systems/openwrt/.$registry_target.tmp" "$meta/systems/openwrt/$registry_target"
    fi
    sync
    echo "installed: card partition $n ($ver, generation $next), started at the next boot"
    echo "   (its first boot is a trial: one that does not come up returns to partition $curn)"
    grep -qs sd-gen /run/e5linux/init-features ||
        echo "   the boot image in use predates card updates: flash this package's boot image too"
    exit 0
}

D=/mnt/e5-data
DIR=$D/e5linux IMG=$D/e5linux/openwrt.ext4
PART=$IMG.part NEW_ROOT=/tmp/e5-img.new OLD_ROOT=/tmp/e5-img.old
[ -f /etc/e5/sd-root ] && [ -f /etc/openwrt_release ] && card_update

# userdata: the initramfs leaves it at /mnt/e5-data; one that predates that
# keeps it to itself, and the partition is mounted a second time (the same
# f2fs, not a copy)
if ! grep -qs " $D " /proc/mounts; then
    dev=
    for u in /sys/class/block/mmcblk*p*/uevent; do
        grep -qx PARTNAME=userdata "$u" 2>/dev/null && dev=/dev/$(basename "$(dirname "$u")")
    done
    [ -n "$dev" ] || { echo "no userdata partition" >&2; exit 1; }
    mkdir -p "$D"
    mount -t f2fs -o noatime "$dev" "$D"
    echo "== mounted userdata ($dev) at $D"
fi
mkdir -p "$DIR"

# the running root: the image itself when OpenWrt runs from it
running_image=
if [ -f /etc/openwrt_release ] && [ "$(cat /etc/e5/image-form 2>/dev/null)" = standalone ]; then
    running_image=1
fi

cleanup() {
    umount "$NEW_ROOT" 2>/dev/null || true
    umount "$OLD_ROOT" 2>/dev/null || true
    rm -f "$PART"
}
trap cleanup EXIT

avail=$(df -Pk "$D" | awk 'NR == 2 { print $4 }')
[ "$avail" -gt 1572864 ] || { echo "less than 1.5 GiB free on userdata" >&2; exit 1; }
rm -f "$DIR/openwrt.ext4.old"

echo "== unpacking into $PART"
rm -f "$PART" "$PART.fail"
case "$SRC" in
    http://*|https://*) { wget -q -O - "$SRC" || touch "$PART.fail"; } | gunzip -c > "$PART" ;;
    *) gunzip -c "$SRC" > "$PART" ;;
esac
[ ! -e "$PART.fail" ] || { rm -f "$PART.fail"; echo "download failed" >&2; exit 1; }

mkdir -p "$NEW_ROOT" "$OLD_ROOT"
mount -t ext4 -o loop "$PART" "$NEW_ROOT"
[ -x "$NEW_ROOT/sbin/init" ] && [ -f "$NEW_ROOT/etc/openwrt_release" ] ||
    { echo "not an OpenWrt image" >&2; exit 1; }

# the OpenWrt whose configuration the new image keeps
from=
if [ -f /etc/openwrt_release ]; then
    from=/
elif [ -f "$IMG" ] && mount -t ext4 -o loop,ro "$IMG" "$OLD_ROOT" 2>/dev/null; then
    from=$OLD_ROOT
elif [ -d /openwrt/etc/config ]; then
    from=/openwrt
fi

N=$NEW_ROOT
[ -n "$from" ] && keep_config "$from" "$N"
umount "$OLD_ROOT" 2>/dev/null || true

if [ ! -f "$N/etc/e5/install.conf" ] && command -v nmcli >/dev/null 2>&1; then
    echo "== settings from Debian"
    # nmcli -g escapes ":" and "\\" in what it prints
    get() { nmcli "$@" 2>/dev/null | sed 's/\\\(.\)/\1/g' || true; }
    apn=$(get -g gsm.apn connection show Mobile)
    ssid=$(get -g 802-11-wireless.ssid connection show Hotspot)
    key=$(get -s -g 802-11-wireless-security.psk connection show Hotspot)
    chan=$(get -g 802-11-wireless.channel connection show Hotspot)
    q() { printf "'%s'" "$(printf '%s' "$1" | sed "s/'/'\\\\''/g")"; }
    mkdir -p "$N/etc/e5"
    (
        umask 077
        echo "# from the Debian image's NetworkManager profiles at install (openwrt/device-install-image.sh)"
        echo "E5_APN=$(q "$apn")"
        echo "E5_WIFI_SSID=$(q "${ssid:-E5-Linux}")"
        echo "E5_WIFI_KEY=$(q "$key")"
        echo "E5_WIFI_CHANNEL=$(q "${chan:-149}")"
    ) > "$N/etc/e5/install.conf"
    chmod 600 "$N/etc/e5/install.conf"
    echo "   apn=${apn:-(none)} ssid=${ssid:-E5-Linux} channel=${chan:-149} key=$([ -n "$key" ] && echo set || echo none)"
fi

# An image built without the device's files (E5_DEVICE_FILES=0) takes them
# from userdata's device-files.tar, which boot/init unpacks as well; made here
# from this system's own when there is none yet (device_files_tar).
DFT=$DIR/device-files.tar
if [ ! -f "$N/lib/firmware/wcnmodem.bin" ] && [ ! -f "$DFT" ]; then
    if device_files_tar > "$DFT.part"; then
        echo "== the device's files from this system -> $DFT"
        mv "$DFT.part" "$DFT"
    else
        rm -f "$DFT.part"
    fi
fi
if [ ! -f "$N/lib/firmware/wcnmodem.bin" ]; then
    if [ -f "$DFT" ]; then
        tar -xf "$DFT" -C "$N"
        sha256sum "$DFT" | cut -d' ' -f1 > "$N/etc/e5/device-files.stamp"
        echo "== the device's files unpacked into the image"
    else
        # (no modem and no Wi-Fi without them: better the old system than that)
        echo "the image has no firmware or vendor subset, and there is no $DFT: not installed" >&2
        exit 1
    fi
fi

mkdir -p "$N/etc/e5linux"
[ -f /etc/e5linux/default-boot ] && [ ! -f "$N/etc/e5linux/default-boot" ] &&
    cp /etc/e5linux/default-boot "$N/etc/e5linux/default-boot"
cp /run/e5linux/misc-bc-slot-a.bin /run/e5linux/misc-bc-slot-b-trial.bin "$N/etc/e5linux/" 2>/dev/null || true
ver=$(cat "$N/etc/e5/image-version" 2>/dev/null || echo "?")
umount "$NEW_ROOT"

if [ -n "$running_image" ]; then
    mv "$PART" "$IMG.new"
    echo "installed: $IMG.new ($ver), swapped in at the next boot"
else
    mv "$PART" "$IMG"
    echo "installed: $IMG ($ver)"
fi
sync

grep -qs openwrt-image /run/e5linux/init-features || {
    echo "the boot image in use predates OpenWrt images of their own: flash a newer one" >&2
    echo "(boot/flash-from-linux.sh) before booting it" >&2
    exit 0
}
case "$MODE" in
    --try)    echo openwrt > "$DIR/boot-os-next"; sync; reboot ;;
    --switch) rm -f "$DIR/boot-os-next"; echo openwrt > "$DIR/boot-os"; sync; reboot ;;
    '')       [ -n "$running_image" ] && echo "reboot to start it" ||
                  echo "boot it with: e5-os openwrt --once (one boot) or e5-os openwrt, then reboot" ;;
esac
