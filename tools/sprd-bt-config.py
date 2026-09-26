#!/usr/bin/env python3
"""Build the Unisoc marlin3 Bluetooth vendor configuration from the chip's
own ini files -- the payloads Android's BT HAL (bt_vnd_conf, marlin3_lite)
sends before the first HCI Reset:

    0xFCA0  pskey  (bt_configure_pskey*.ini, the BD address patched in)
    0xFCA2  RF     (bt_configure_rf*.ini)

Each ini block starts with `#[n.m]__/L=<bytes>`; its values are written
little-endian, each taking L / (number of values in the block) bytes, in
file order, and the payload is zero-padded to the length the HAL sends.

    sprd-bt-config.py PSKEY.ini RF.ini BTMAC.txt OUTDIR
writes OUTDIR/marlin3lite_pskey.bin (176 bytes) and marlin3lite_rf.bin (252).
"""
import re, sys

PSKEY_LEN, RF_LEN = 176, 252


def parse(path):
    """[(key, width, values)] in file order.  One `/L=` marker can cover
    several value lines (rf.ini's BR/EDR channel powers share one), so the
    width is L divided by the values of the whole block."""
    blocks, cur = [], None
    for raw in open(path, errors="replace"):
        line = raw.strip()
        m = re.match(r"#\[\d+\.\d+\]_*/L=(\d+)", line)
        if m:
            cur = [int(m.group(1)), []]
            blocks.append(cur)
            continue
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, val = (s.strip() for s in line.split("=", 1))
        if cur is None:
            raise SystemExit(f"{path}: no /L= marker before {key}")
        cur[1].append((key, [int(v.strip(), 0) for v in val.split(",") if v.strip()]))
    fields = []
    for length, lines in blocks:
        n = sum(len(v) for _, v in lines)
        if not n or length % n:
            raise SystemExit(f"{path}: {n} values do not divide L={length} ({lines[0][0] if lines else '?'})")
        fields += [(key, length // n, vals) for key, vals in lines]
    return fields


def pack(fields, total, bdaddr=None):
    out = bytearray()
    for key, width, vals in fields:
        if key == "device_addr" and bdaddr is not None:
            vals = list(bdaddr)
        for v in vals:
            out += (v & ((1 << (8 * width)) - 1)).to_bytes(width, "little")
    if len(out) > total:
        raise SystemExit(f"payload {len(out)} > {total}")
    return bytes(out) + bytes(total - len(out))


def main():
    pskey_ini, rf_ini, btmac, outdir = sys.argv[1:5]
    mac = open(btmac).read().strip()
    octets = [int(x, 16) for x in mac.split(":")]
    if len(octets) != 6:
        raise SystemExit(f"bad BD address in {btmac}: {mac!r}")
    bdaddr = bytes(reversed(octets))              # HCI order, as the HAL sends it
    open(f"{outdir}/marlin3lite_pskey.bin", "wb").write(pack(parse(pskey_ini), PSKEY_LEN, bdaddr))
    open(f"{outdir}/marlin3lite_rf.bin", "wb").write(pack(parse(rf_ini), RF_LEN))


if __name__ == "__main__":
    main()
