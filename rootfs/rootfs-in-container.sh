#!/bin/bash
# The container half of rootfs/build-rootfs-container.sh -- do not run this
# directly on the host, it expects to be root inside debian:trixie with the
# workspace at /w.
#
# Stages: deps fetch install configure repair pack (see the wrapper for the
# reasoning); every stage is safe to re-run.
set -e
STAGES="${*:-all}"
want() { case " $STAGES " in *" all "*) return 0 ;; *" $1 "*) return 0 ;; *) return 1 ;; esac; }

ROOT=/w/work/rootfs-build/rootfs
OUT=/w/out/rootfs.ext4
IMG_MIB="${E5_IMG_MIB:-8192}"

if want deps; then
    export DEBIAN_FRONTEND=noninteractive
    echo "=== container deps ==="
    apt-get update -q
    apt-get install -y -q --no-install-recommends e2fsprogs python3 ca-certificates
fi

if want fetch; then
    echo "=== base tree ==="
    if [ -x "$ROOT/bin/sh" ]; then
        echo "base already present ($(du -sh "$ROOT" | cut -f1))"
    else
        mkdir -p "$ROOT"
        python3 /w/rootfs/fetch-debian-rootfs.py trixie "$ROOT"
    fi
fi

if want install || want configure || want repair; then
    echo "=== native chroot shim ==="
    cat > /tmp/chroot-native.sh <<'EOS'
#!/bin/bash
set -e
ROOT="${E5_ROOT:-/w/work/rootfs-build/rootfs}"
mkdir -p "$ROOT/proc" "$ROOT/sys" "$ROOT/dev/pts" "$ROOT/run"
mountpoint -q "$ROOT/proc"     || mount -t proc proc "$ROOT/proc"
mountpoint -q "$ROOT/sys"      || mount -t sysfs sysfs "$ROOT/sys"
mountpoint -q "$ROOT/dev"      || mount --rbind /dev "$ROOT/dev"
mountpoint -q "$ROOT/dev/pts"  || mount -t devpts devpts "$ROOT/dev/pts" 2>/dev/null || true
cp -f /etc/resolv.conf "$ROOT/etc/resolv.conf"
env -i PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin \
    HOME=/root TERM=linux LANG=C.UTF-8 SHELL=/bin/sh TMPDIR=/tmp \
    DEBIAN_FRONTEND=noninteractive \
    chroot "$ROOT" /bin/sh -c "$*"
EOS
    chmod +x /tmp/chroot-native.sh
    mount --bind /tmp/chroot-native.sh /w/rootfs/e5-chroot.sh
fi

if want install; then
    # install-packages.sh goes straight to apt-get install: it assumes the
    # package index is already in the tree (the device flow inherited one from
    # the running system), and a freshly fetched base image has none, so every
    # package comes back "Unable to locate".
    echo "=== apt index in the tree ==="
    bash /tmp/chroot-native.sh 'apt-get update'
    echo "=== install the package set ==="
    bash /w/rootfs/install-packages.sh
fi

if want configure; then
    echo "=== overlay, user, services ==="
    bash /w/rootfs/configure-rootfs.sh
fi

if want repair; then
    # Every path a package's file list names must exist in the tree.  A tree that
    # was never booted can lose the /etc/alternatives links that only resolve
    # inside it, and a missing /usr/lib/ssl/certs or libblas.so.3 is silent until
    # something needs it.  List what is gone and reinstall the owners.
    echo "=== missing files (dpkg file lists vs the tree) ==="
    bash /tmp/chroot-native.sh '
        for f in /var/lib/dpkg/info/*.list; do
            pkg=${f##*/}; pkg=${pkg%.list}
            while IFS= read -r p; do
                case "$p" in /var/*|/run/*|/proc/*|/sys/*|"") continue;; esac
                [ -e "$p" ] || [ -L "$p" ] || echo "$pkg $p"
            done < "$f"
        done | sort -u > /tmp/missing.txt
        echo "missing: $(wc -l < /tmp/missing.txt)"
        awk "{print \$1}" /tmp/missing.txt | sort -u > /tmp/missing-pkgs.txt
        head -20 /tmp/missing.txt
        echo "pkgs: $(tr "\n" " " < /tmp/missing-pkgs.txt)"' || true
    pkgs=$(bash /tmp/chroot-native.sh 'tr "\n" " " < /tmp/missing-pkgs.txt' 2>/dev/null | tail -1)
    if [ -n "${pkgs// }" ]; then
        echo "=== reinstalling: $pkgs ==="
        bash /tmp/chroot-native.sh "apt-get -o APT::Sandbox::User=root --reinstall -y install $pkgs" 2>&1 | tail -5
    else
        echo "nothing to repair"
    fi
fi

if want pack; then
    echo "=== unmount before packing ==="
    umount /w/rootfs/e5-chroot.sh || true
    for m in run dev/pts dev sys proc; do umount "$ROOT/$m" 2>/dev/null || true; done
    # the /dev rbind brings its own submounts (mqueue, shm) along, which a plain
    # umount of the tree's /dev does not remove; leaving them mounted means the
    # copy below would pack devtmpfs content into the image
    umount -R "$ROOT" 2>/dev/null || true
    mount | grep "$ROOT" || echo "(nothing left mounted)"

    # mount + cp -a, not "mkfs.ext4 -d": -d follows every absolute symlink through
    # the *build host's* root to read its attributes, and this tree is full of
    # /etc/alternatives links that only resolve inside it ("setting xattrs for
    # all_ALL: No such file or directory").  cp copies the links as links.
    echo "=== pack (${IMG_MIB} MiB) ==="
    rm -f "$OUT"
    mkdir -p "$(dirname "$OUT")"
    truncate -s "${IMG_MIB}M" "$OUT"
    # The chroot shim copies the *build container's* /etc/resolv.conf into the
    # tree so apt can resolve during the install, and that file then travels into
    # the image.  On the device it is a Docker resolver (0.250.250.200) that
    # answers nothing: dnsmasq forwarded to it, so every client of the hotspot got
    # "connected, no internet" and the device's own apt could not resolve either.
    # Write a real one before packing; systemd-resolved would overwrite it once
    # an interface with DNS is up.
    printf 'nameserver 223.5.5.5\nnameserver 119.29.29.29\n' > "$ROOT/etc/resolv.conf"
    mkfs.ext4 -F -q -L e5linux "$OUT"
    M=/mnt/e5img
    mkdir -p "$M"
    mount -o loop "$OUT" "$M"
    cp -a "$ROOT/." "$M/"
    sync
    umount "$M"
    tune2fs -m 1 "$OUT" >/dev/null
    e2fsck -f -y "$OUT" >/dev/null 2>&1 || true
    ls -la "$OUT"
    sha256sum "$OUT"
    echo "installed packages: $(grep -c '^Status: install ok installed' "$ROOT/var/lib/dpkg/status" 2>/dev/null)"
fi
echo ROOTFS-CONTAINER-DONE "$STAGES"
