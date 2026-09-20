#!/bin/bash
# Stage 3: turn the installed Debian tree into an e5-linux system.
set -e
HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="${E5_ROOT:-$HERE/../work/rootfs-build/rootfs}"

echo "=== overlay ==="
# The base image is usrmerge: /lib is a symlink to usr/lib, and cp refuses to
# replace a symlink with the overlay's real lib/ directory (the firmware files in
# it).  Merge those entries under /usr instead -- on the running system that is
# the same path.  Device-built trees whose tar pass materialised the symlinks
# take the plain branch.
for entry in "$HERE/overlay"/*; do
    [ -e "$entry" ] || continue
    name=$(basename "$entry")
    if [ -L "$ROOT/$name" ] && [ -d "$entry" ]; then
        # Debian's wireless-regdb ships /usr/lib/firmware/regulatory.db as an
        # alternatives symlink, and a tree that never ran update-alternatives has
        # it dangling; cp then refuses to write through it ("not writing through
        # dangling symlink"), so clear the dangling links we are about to replace.
        (cd "$entry" && find . \( -type f -o -type l \) -print) | while read -r f; do
            dest="$ROOT/usr/$name/${f#./}"
            if [ -L "$dest" ] && [ ! -e "$dest" ]; then rm -f "$dest"; fi
        done
        cp -a "$entry/." "$ROOT/usr/$name/"
    else
        cp -a "$entry" "$ROOT/"
    fi
done

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
        # netdev is not in the fresh base tree (a package postinst creates it on
        # a full system), and useradd refuses a group that does not exist.
        getent group netdev >/dev/null || groupadd -r netdev
        useradd -m -s /bin/bash -G sudo,video,render,input,audio,netdev e5
    fi
    echo "e5:123456" | chpasswd
    echo "root:root" | chpasswd
    # The device has a touchscreen and no keyboard, so autologin is the only way
    # in; a password that must be typed would make it unreachable.
    # rm first: the file is 0440, and a build host that maps root onto the host
    # user (Docker Desktop bind mounts) cannot reopen it for writing
    rm -f /etc/sudoers.d/10-e5
    printf "e5 ALL=(ALL) NOPASSWD:ALL\n" > /etc/sudoers.d/10-e5
    chmod 0440 /etc/sudoers.d/10-e5
'

echo "=== services ==="
bash "$HERE/e5-chroot.sh" '
    set -e
    # SDDM, after all.  Its Wayland *greeter* cannot draw on this image
    # (kwin_wayland went with KDE, x11-user was never installed), but the session
    # does not go through the greeter: /etc/sddm/wayland-session execs the session
    # directly and the image's own sddm config carries the WLR_RENDERER=gles2 that
    # phoc needs on this panel.  Autologin takes it from there, both on the
    # display and on the keypad.
    #
    # A getty-based session was tried instead for a day and is a trap: without
    # that env phoc spins at 90% CPU, the session never appears to input, and the
    # physical keys look dead -- they are not, they just never reach the UI.
    systemctl --root=/ enable sddm.service >/dev/null 2>&1 || echo "warn: sddm enable failed"
    # This board has no RTC: without something setting the clock the device comes
    # up years behind and apt refuses the mirror ("Not live until ...").  The
    # bearer is up a couple of minutes into the boot, which is soon enough.
    systemctl --root=/ enable systemd-timesyncd.service >/dev/null 2>&1 || echo "warn: timesyncd enable failed"
    systemctl --root=/ enable e5-boot-ok.service >/dev/null 2>&1 || echo "warn: e5-boot-ok enable failed"
    systemctl --root=/ enable e5-zram.service >/dev/null 2>&1 || echo "warn: zram enable failed"
    # The usb0 management LAN -- its 192.168.77.1 and its DHCP server -- is
    # /etc/systemd/network/10-e5-usb0.network, i.e. systemd-networkd, and the
    # busybox telnetd that is the only way into a device with no usable keypad
    # rides on that address.  Nothing else starts networkd: it used to be a
    # NetworkManager drop-in (Wants=systemd-networkd.service), which went away
    # with NetworkManager, and the device promptly came back with usb0 down,
    # no lease, and no way in.
    systemctl --root=/ enable systemd-networkd.service systemd-networkd.socket >/dev/null 2>&1 || echo "warn: networkd enable failed"
    systemctl --root=/ enable e5-bt-attach.service >/dev/null 2>&1 || echo "warn: bt-attach enable failed"
    # The baseband, G2 shape: the vendor modem_control chroot boots the CP, the
    # two vendor helpers persist the modem NV data, and unisoc-cpd is the one
    # owner of the AT/URC channels for the whole boot (it replaced e5-atd and
    # e5-mobile-data; its unit carries Conflicts= against them for images that
    # still have them enabled).  A single owner is what the SIPC channel and the
    # CP command queue both require.
    #
    # e5-regdb-load and e5-hotspot are what the Wi-Fi hotspot is (the regulatory
    # database and hostapd on wlan0), e5-telnetd is the way in on a device with no
    # usable keypad, and e5-gadget-guard keeps the USB gadget alive.  All four used
    # to be enabled by hand on a device that was already installed, which is why a
    # fresh install had no hotspot at all.  e5-fixups is the port of mu300-fixups:
    # it restores the cap_net_raw on ping and links e5-next-boot/mobile-data/e5-at into
    # /usr/local/bin, which is what makes `sudo e5-next-boot android` work.
    for s in e5-vendor e5-cp_diskserver e5-refnotify \
             unisoc-cpd e5-bearer-up \
             e5-regdb-load e5-hotspot e5-telnetd e5-gadget-guard e5-fixups; do
        systemctl --root=/ enable $s.service >/dev/null 2>&1 || echo "warn: $s enable failed"
    done
    systemctl --root=/ enable serial-getty@ttyGS0.service >/dev/null 2>&1 || echo "warn: getty enable failed"
    systemctl set-default graphical.target >/dev/null 2>&1 || true
    echo "enabled:"; ls /etc/systemd/system/graphical.target.wants/ /etc/systemd/system/multi-user.target.wants/ 2>/dev/null | head -30
'

echo "=== sessions available ==="
ls "$ROOT"/usr/share/wayland-sessions/ 2>/dev/null || echo "(none)"

echo "=== cleanup ==="
bash "$HERE/e5-chroot.sh" 'apt-get -o APT::Sandbox::User=root clean >/dev/null 2>&1 || true; rm -rf /var/lib/apt/lists/* /var/cache/apt/archives/*.deb'
rm -f "$ROOT/qemu-aarch64-static"
# informational only: the tree still has /proc and /sys bind-mounted here, where du
# races with the kernel's own fd symlinks and exits non-zero -- under `set -e` that
# used to end the build one line before "CONFIGURE-DONE"
du -sh "$ROOT" 2>/dev/null || true
echo "CONFIGURE-DONE"
