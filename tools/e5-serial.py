#!/usr/bin/env python3
"""Talk to the E5 over its USB gadget serial console (CDC-ACM).

The NCM interface (en8) carries the management LAN, but when the guest is
unreachable over IP this is the only way in: the gadget also exposes an ACM
port, and serial-getty@ttyGS0 listens on it.

    e5-serial.py                 read whatever is on the wire
    e5-serial.py -s root -s root -s "systemctl status systemd-networkd"
"""
import argparse
import os
import select
import sys
import termios
import time

def default_port():
    import glob

    for pattern in ("/dev/cu.usbmodemE5LINUX*", "/dev/cu.usbmodem*"):
        found = sorted(glob.glob(pattern))
        if found:
            return found[0]
    return "/dev/cu.usbmodemE5LINUX3"


PORT = default_port()


def drain(fd, seconds):
    out = b""
    end = time.time() + seconds
    while time.time() < end:
        r, _, _ = select.select([fd], [], [], 0.2)
        if not r:
            continue
        try:
            chunk = os.read(fd, 4096)
        except OSError:
            break
        if not chunk:
            break
        out += chunk
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", default=PORT)
    ap.add_argument("--read", type=float, default=3.0, help="seconds to read at the end")
    ap.add_argument("--gap", type=float, default=1.5, help="seconds to read after each send")
    ap.add_argument("-s", "--send", action="append", default=[])
    a = ap.parse_args()

    fd = os.open(a.port, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
    try:
        attrs = termios.tcgetattr(fd)
        attrs[0] = 0
        attrs[1] = 0
        attrs[2] = termios.CS8 | termios.CREAD | termios.CLOCAL
        attrs[3] = 0
        attrs[4] = termios.B115200
        attrs[5] = termios.B115200
        termios.tcsetattr(fd, termios.TCSANOW, attrs)
        out = drain(fd, 1.0)
        for line in a.send:
            os.write(fd, line.encode() + b"\n")
            out += drain(fd, a.gap)
        out += drain(fd, a.read)
        sys.stdout.write(out.decode("utf-8", "replace"))
    finally:
        os.close(fd)


if __name__ == "__main__":
    main()
