#!/usr/bin/env python3
"""Read (and optionally write) the kernel's scancode -> keycode map for an input
device through EVIOCGKEYCODE_V2 / EVIOCSKEYCODE_V2.

    tools/keycode-query.py /dev/input/event2 0x161 [0x9e ...]
    tools/keycode-query.py /dev/input/event2 0x161=28      # set (0x1c = KEY_ENTER)

This is how the E5's keypad confirm key was pinned down: its DT keymap says
KEY_SELECT (353), which nothing in the session handles, so the hwdb rule in
rootfs/overlay/etc/udev/hwdb.d/61-e5-keypad.hwdb remaps it to Enter.
"""
import ctypes
import fcntl
import struct
import sys


class KeymapEntry(ctypes.Structure):
    _fields_ = [('flags', ctypes.c_uint8), ('len', ctypes.c_uint8),
                ('index', ctypes.c_uint16), ('keycode', ctypes.c_uint32),
                ('scancode', ctypes.c_uint8 * 32)]


SIZE = ctypes.sizeof(KeymapEntry)          # 40
EVIOCGKEYCODE_V2 = 0x80000000 | (SIZE << 16) | (0x45 << 8) | 0x04
EVIOCSKEYCODE_V2 = 0x40000000 | (SIZE << 16) | (0x45 << 8) | 0x04


def main():
    path = sys.argv[1]
    fd = open(path, 'rb')
    for arg in sys.argv[2:]:
        if '=' in arg:
            sc, code = (int(x, 0) for x in arg.split('=', 1))
            e = KeymapEntry(0, 0, sc, code)
            fcntl.ioctl(fd, EVIOCSKEYCODE_V2, e, True)
            print('set scancode 0x%03x -> %d' % (sc, code))
            continue
        sc = int(arg, 0)
        e = KeymapEntry(0, 0, sc, 0)
        fcntl.ioctl(fd, EVIOCGKEYCODE_V2, e, True)
        print('scancode 0x%03x -> keycode %d (0x%x)' % (sc, e.keycode, e.keycode))
    fd.close()


if __name__ == '__main__':
    main()
