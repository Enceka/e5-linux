#!/bin/bash
# Unpack the downloaded .deb set without going through apt's resolver.
#
# apt-get install spent over twenty minutes of solid CPU on dependency
# resolution for ~1450 packages and never reached the unpack phase (the count of
# /var/lib/dpkg/info/*.list stayed at the 78 files the base image ships).  The
# resolver is the pathological part and under qemu emulation it does not finish
# in any sane time.  dpkg on its own does no resolution: --unpack takes the files
# in the order given and only Dependency warnings come out of it, which is why
# the configuration pass afterwards is a separate step (apt would normally have
# ordered everything first).
set -e
HERE="$(cd "$(dirname "$0")" && pwd)"
bash "$HERE/e5-chroot.sh" 'dpkg --unpack /var/cache/apt/archives/*.deb 2>&1 | grep -vE "^(Selecting|Preparing|Unpacking)" | tail -60'
echo "UNPACK-DONE"
