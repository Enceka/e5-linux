#!/bin/bash
# Build the e5-linux root filesystem inside an arm64 Debian container.
#
# rootfs/build-rootfs.sh is written for "a Linux build host".  On the Mac this
# project is developed on, that host is `docker run debian:trixie` on Apple
# Silicon, which is aarch64 *natively* -- so the package install runs at native
# speed instead of under qemu-aarch64.  That emulation is why the device used to
# do this install itself (rootfs/device-build.sh) and why apt's resolver timed
# out there.
#
# e5-chroot.sh (user namespace + qemu + binfmt_misc) cannot work here: qemu-user
# is a Linux ELF binary, so it does not run on macOS at all.  It is bind-mounted
# over for the duration of the run; the file in the tree is untouched.
#
#   rootfs/build-rootfs-container.sh [deps] [fetch] [install] [configure] [repair] [pack]
#
# With no argument it runs all of them.  The stages exist so a later step can be
# re-run without the ~40 minute apt pass:
#
#   ./build-rootfs-container.sh deps pack      # re-pack after an overlay change
#   ./build-rootfs-container.sh install        # only the package set changed
#
# The result is out/rootfs.ext4, 8 GiB by default (E5_IMG_MIB overrides it).
set -e
HERE="$(cd "$(dirname "$0")" && pwd)"
TOP="$(cd "$HERE/.." && pwd)"

exec docker run --rm --privileged \
    -e E5_IMG_MIB="${E5_IMG_MIB:-8192}" \
    -v "$TOP":/w -w /w debian:trixie \
    bash /w/rootfs/rootfs-in-container.sh "$@"
