#!/system/bin/sh
# Finish configuring the root filesystem with a clean environment.
#
# The first pass aborted with "too many errors" and the reason was in the log:
#
#   mktemp: failed to create directory via template
#   '/data/local/tmp/ispell-auto.XXXXXXXXXX': No such file or directory
#
# Android exports TMPDIR=/data/local/tmp (and a pile of ANDROID_* variables plus
# LD_LIBRARY_PATH) and chroot inherits the environment, so maintainer scripts
# that use mktemp failed for a reason that has nothing to do with Debian.  env -i
# gives the chroot a sane environment; the chroot itself already has PATH set by
# the caller.
#
# dpkg --configure -a is safe to repeat: it only looks at packages still marked
# for configuration.
set -e
ROOT=/data/e5build/root

run() {
    env -i PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin \
        TMPDIR=/tmp HOME=/root TERM=linux LANG=C.UTF-8 SHELL=/bin/sh \
        DEBIAN_FRONTEND=noninteractive chroot "$ROOT" /bin/sh -c "$1"
}

echo "=== sanity ==="
run 'uname -m; echo TMPDIR=$TMPDIR; mktemp -d && echo mktemp-ok'

for round in 1 2 3 4 5; do
    echo "=== configure round $round ==="
    run 'dpkg --force-confold --configure -a 2>&1 | tail -25' || true
    n=$(grep -c '^Status: install ok installed' "$ROOT/var/lib/dpkg/status" 2>/dev/null)
    left=$(grep -c '^Status: .*not-installed\|^Status: .*half-configured\|^Status: .*unpacked' "$ROOT/var/lib/dpkg/status" 2>/dev/null)
    echo "configured=$n  pending=$left"
    [ "$left" = "0" ] && break
done
echo "DEVICE-CONFIGURE-DONE"
