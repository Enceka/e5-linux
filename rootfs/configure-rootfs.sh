#!/bin/bash
# Stage 3: turn the installed Debian tree into an e5-linux system.
set -e
HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="${E5_ROOT:-$HERE/../work/rootfs-build/rootfs}"

echo "=== overlay ==="
cp -a "$HERE/overlay/." "$ROOT/"

echo "=== locale ==="
bash "$HERE/e5-chroot.sh" '
    grep -q "^en_US.UTF-8" /etc/locale.gen || echo "en_US.UTF-8 UTF-8" >> /etc/locale.gen
    echo "LANG=en_US.UTF-8" > /etc/default/locale
    locale-gen >/dev/null 2>&1 || true
    ln -sf /usr/share/zoneinfo/Asia/Shanghai /etc/localtime
    echo "e5-linux" > /etc/hostname
'

echo "=== user ==="
bash "$HERE/e5-chroot.sh" '
    set -e
    if ! id e5 >/dev/null 2>&1; then
        useradd -m -s /bin/bash -G sudo,video,render,input,audio,netdev e5
    fi
    echo "e5:e5" | chpasswd
    echo "root:root" | chpasswd
    # The device has a touchscreen and no keyboard, so autologin is the only way
    # in; a password that must be typed would make it unreachable.
    printf "e5 ALL=(ALL) NOPASSWD:ALL\n" > /etc/sudoers.d/10-e5
    chmod 0440 /etc/sudoers.d/10-e5
'

echo "=== services ==="
bash "$HERE/e5-chroot.sh" '
    set -e
    systemctl enable sddm.service >/dev/null 2>&1 || echo "warn: sddm enable failed"
    systemctl enable e5-boot-ok.service >/dev/null 2>&1 || echo "warn: e5-boot-ok enable failed"
    systemctl enable NetworkManager.service >/dev/null 2>&1 || echo "warn: NM enable failed"
    systemctl enable e5-zram.service >/dev/null 2>&1 || echo "warn: zram enable failed"
    systemctl enable serial-getty@ttyGS0.service >/dev/null 2>&1 || echo "warn: getty enable failed"
    systemctl set-default graphical.target >/dev/null 2>&1 || true
    echo "enabled:"; ls /etc/systemd/system/graphical.target.wants/ /etc/systemd/system/multi-user.target.wants/ 2>/dev/null | head -30
'

echo "=== sessions available ==="
ls "$ROOT"/usr/share/wayland-sessions/ 2>/dev/null || echo "(none)"

echo "=== cleanup ==="
bash "$HERE/e5-chroot.sh" 'apt-get -o APT::Sandbox::User=root clean >/dev/null 2>&1 || true; rm -rf /var/lib/apt/lists/* /var/cache/apt/archives/*.deb'
rm -f "$ROOT/qemu-aarch64-static"
du -sh "$ROOT"
echo "CONFIGURE-DONE"
