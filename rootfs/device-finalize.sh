#!/system/bin/sh
# Turn the configured Debian tree into an e5-linux system, then publish it as the
# image boot/init looks for.
set -e
ROOT=/data/e5build/root
OVL=/data/local/tmp/overlay
IMG=/data/e5build/rootfs.ext4

run() {
    env -i PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin \
        TMPDIR=/tmp HOME=/root TERM=linux LANG=C.UTF-8 SHELL=/bin/sh \
        DEBIAN_FRONTEND=noninteractive chroot "$ROOT" /bin/sh -c "$1"
}

echo "=== overlay ==="
cp -a "$OVL/." "$ROOT/"

echo "=== locale / machine-id ==="
run 'grep -q "^en_US.UTF-8" /etc/locale.gen || echo "en_US.UTF-8 UTF-8" >> /etc/locale.gen
     locale-gen >/dev/null 2>&1 || true
     echo LANG=en_US.UTF-8 > /etc/default/locale
     ln -sf /usr/share/zoneinfo/Asia/Shanghai /etc/localtime
     echo e5-linux > /etc/hostname
     systemd-machine-id-setup >/dev/null 2>&1 || true
     ls -la /etc/machine-id'

echo "=== user ==="
run 'id e5 >/dev/null 2>&1 || useradd -m -s /bin/bash -G sudo,video,render,input,audio,netdev e5
     # numeric on purpose: the 9-key keypad (docs/FINDINGS.md section 12) is the only
     # keyboard on the device, and it types digits
     echo "e5:123456" | chpasswd
     echo "root:root" | chpasswd
     echo "e5 ALL=(ALL) NOPASSWD:ALL" > /etc/sudoers.d/10-e5
     chmod 0440 /etc/sudoers.d/10-e5
     id e5'

echo "=== services ==="
run 'for s in sddm e5-boot-ok e5-zram systemd-networkd dnsmasq serial-getty@ttyGS0 \
                e5-vendor e5-cp_diskserver e5-refnotify \
                unisoc-cpd e5-bearer-up \
                e5-regdb-load e5-hotspot e5-telnetd e5-gadget-guard e5-fixups; do
        systemctl enable $s.service >/dev/null 2>&1 && echo "enabled $s" || echo "FAILED $s"
     done
     systemctl set-default graphical.target >/dev/null 2>&1
     ls /etc/systemd/system/graphical.target.wants/ 2>/dev/null'

echo "=== sessions ==="
ls "$ROOT/usr/share/wayland-sessions/" 2>/dev/null || echo "(no wayland sessions)"

echo "=== shrink ==="
rm -rf "$ROOT/var/cache/apt/archives/"*.deb "$ROOT/var/lib/apt/lists/"* 2>/dev/null || true
run 'apt-get clean >/dev/null 2>&1 || true'
du -s "$ROOT" 2>/dev/null

echo "=== unmount ==="
for m in run dev/pts dev sys proc; do umount "$ROOT/$m" 2>/dev/null || true; done
umount "$ROOT" 2>/dev/null || true
sync

echo "=== publish ==="
mkdir -p /data/e5linux
cp /data/local/tmp/payload.ext4 "$IMG"
ls -la "$IMG"
echo "FINALIZE-DONE"
