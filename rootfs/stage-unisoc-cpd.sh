#!/bin/bash
# Refresh the overlay's copy of unisoc-cpd from a checkout of its own repository.
#
#     rootfs/stage-unisoc-cpd.sh [path/to/unisoc-cpd]      (default ./unisoc-cpd)
#
# unisoc-cpd is developed in its own repository (.gitignore); this tree carries
# the deployed artifact -- the static aarch64 binary, the E5 profile, the units
# and the two reference docs -- so that building an image never needs the
# checkout.  This script is the one way that copy is updated:
#
#   * builds the binary with the checkout's own tools/build-aarch64.sh (static
#     aarch64-unknown-linux-musl; rustup's target and rust-lld must be there)
#   * copies it, README.md, docs/BASEBAND-CONTRACTS.md and the profiles
#   * applies the places where the Linux side differs from the checkout,
#     whose defaults describe the handset's Android:
#       - [data.nat] is off: the checkout's profile drives Android's iptables
#         (tetherctrl_FORWARD, the legacy_system table); on Linux e5-nat.service
#         does the masquerading with nftables
#       - the web page binds to the LAN (br0, 192.168.9.1), not 0.0.0.0: it has
#         no authentication and offers raw AT, IMEI writes, SMS and dialling, so
#         it must not face the uplink, and etc/e5/nat.nft's bridge table keeps
#         the Wi-Fi port of br0 away from it (only the USB port reaches it)
#       - the web unit gets --profiles-dir /etc/unisoc-cpd, as the daemon's has
#   * writes etc/unisoc-cpd/VERSION with the commit it was built from
set -eu
HERE=$(cd "$(dirname "$0")" && pwd)
SRC=$(cd "${1:-$HERE/../unisoc-cpd}" && pwd)
OVL=$HERE/overlay
ETC=$OVL/etc/unisoc-cpd
UNITS=$OVL/etc/systemd/system

[ -f "$SRC/Cargo.toml" ] && [ -f "$SRC/platform/profiles/e5.toml" ] ||
    { echo "not a unisoc-cpd checkout: $SRC" >&2; exit 1; }
rev=$(git -C "$SRC" rev-parse --short HEAD)
dirty=$(git -C "$SRC" status --porcelain --untracked-files=no | grep -q . && echo "-dirty" || true)
[ -z "$dirty" ] || echo "warning: $SRC has uncommitted changes; VERSION will say so" >&2

echo "== building unisoc-cpd $rev$dirty"
bash "$SRC/tools/build-aarch64.sh" | tail -2
BIN=$SRC/target/aarch64-unknown-linux-musl/release/unisoc-cpd
file "$BIN" | grep -q "ARM aarch64.*statically linked" || { echo "not a static aarch64 binary: $BIN" >&2; exit 1; }

install -m 0755 "$BIN" "$OVL/usr/local/bin/unisoc-cpd"
install -m 0644 "$SRC/README.md" "$ETC/README.md"
install -m 0644 "$SRC/docs/BASEBAND-CONTRACTS.md" "$ETC/BASEBAND-CONTRACTS.md"
install -m 0644 "$SRC/platform/profiles/mu300.toml" "$ETC/mu300.toml"

python3 - "$SRC/platform/profiles/e5.toml" "$ETC/e5.toml" <<'EOF'
import re, sys
src, dst = sys.argv[1], sys.argv[2]
s = open(src).read()
m = re.search(r'^\[data\.nat\]\n(.*?)(?=^\[)', s, re.M | re.S)
assert m, "no [data.nat] section in the profile"
body, n = re.subn(r'^enabled\s*=\s*true\s*$',
                  '# e5-linux: off on the Linux side -- e5-nat.service masquerades with\n'
                  '# nftables; the chain/table below are Android\'s iptables names.\n'
                  'enabled = false', m.group(1), count=1, flags=re.M)
assert n == 1, "[data.nat] has no 'enabled = true' to turn off"
s = s[:m.start(1)] + body + s[m.end(1):]
head = ('# Staged by e5-linux rootfs/stage-unisoc-cpd.sh from unisoc-cpd\'s\n'
        '# platform/profiles/e5.toml; edit it there, not here.  Linux-side change:\n'
        '# [data.nat] enabled = false.\n\n')
open(dst, 'w').write(head + s)
EOF

for u in unisoc-cpd.service unisoc-cpd-soak.service unisoc-cpd-soak.timer; do
    install -m 0644 "$SRC/units/$u" "$UNITS/$u"
done
grep -q ' web 0\.0\.0\.0:7887' "$SRC/units/unisoc-cpd-web.service" ||
    { echo "unisoc-cpd-web.service no longer says 'web 0.0.0.0:7887'; update this script" >&2; exit 1; }
# The checkout's web unit gives no --profiles-dir, and without one the binary
# looks in the build host's source tree (CARGO_MANIFEST_DIR): on the device
# "cannot read profile /Volumes/.../platform/profiles/e5.toml", every restart.
pd=
grep -q -- '--profiles-dir' "$SRC/units/unisoc-cpd-web.service" || pd=' --profiles-dir /etc/unisoc-cpd'
sed -e 's| web 0\.0\.0\.0:7887| web 192.168.9.1:7887|' \
    -e "s|^ExecStart=/usr/local/bin/unisoc-cpd --profile e5 --mode native|&$pd|" \
    -e 's|^Requires=unisoc-cpd.service|&\
# e5-linux: bound to the LAN (br0, 192.168.9.1), and only the USB port of br0\
# reaches it: the page has no authentication and can send AT, SMS and IMEI\
# writes, and etc/e5/nat.nft drops frames for it that arrive on the Wi-Fi port.\
# Until br0 has its address the bind fails and Restart= tries again.|' \
    "$SRC/units/unisoc-cpd-web.service" > "$UNITS/unisoc-cpd-web.service"
chmod 0644 "$UNITS/unisoc-cpd-web.service"

printf '%s%s\n' "$rev" "$dirty" > "$ETC/VERSION"
echo "staged unisoc-cpd $rev$dirty into $OVL"
