#!/usr/bin/env python3
"""Read and write the kernel's scancode -> keycode map for an input device.

    tools/keycode-query.py /dev/input/event2 0x161            # read
    tools/keycode-query.py /dev/input/event2 0x161=96         # remap to KP_ENTER

Uses EVIOCGKEYCODE_V2 / EVIOCSKEYCODE_V2 with INPUT_KEYMAP_BY_INDEX, which is
what udev's keyboard builtin uses for a KEYBOARD_KEY_<scancode>=<key> hwdb rule --
so this is also how such a rule is verified.  (Without the BY_INDEX flag the
kernel wants the scancode in the entry's scancode[] buffer with len 1/2/4 and
returns EINVAL for len 0 -- which is what made an earlier attempt look like "this
device cannot be remapped at all".)
"""
import ctypes
import fcntl
import sys

INPUT_KEYMAP_BY_INDEX = 0x01
KEY_NAMES = {28: 'ENTER', 96: 'KP_ENTER', 353: 'SELECT', 158: 'BACK', 103: 'UP',
             108: 'DOWN', 105: 'LEFT', 106: 'RIGHT', 523: 'PHONE', 139: 'MENU',
             169: 'NEXT', 55: 'KPASTERISK'}


class KeymapEntry(ctypes.Structure):
    _fields_ = [('flags', ctypes.c_uint8), ('len', ctypes.c_uint8),
                ('index', ctypes.c_uint16), ('keycode', ctypes.c_uint32),
                ('scancode', ctypes.c_uint8 * 32)]


SIZE = ctypes.sizeof(KeymapEntry)                      # 40
EVIOCGKEYCODE_V2 = 0x80000000 | (SIZE << 16) | (0x45 << 8) | 0x04
EVIOCSKEYCODE_V2 = 0x40000000 | (SIZE << 16) | (0x45 << 8) | 0x04


def parse(value):
    value = value.strip().upper()
    if value in KEY_NAMES.values():
        return [k for k, v in KEY_NAMES.items() if v == value][0]
    return int(value, 0)


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    fd = open(sys.argv[1], 'rb')
    for arg in sys.argv[2:]:
        if '=' in arg:
            sc, code = arg.split('=', 1)
            e = KeymapEntry(INPUT_KEYMAP_BY_INDEX, 0, int(sc, 0), parse(code))
            fcntl.ioctl(fd, EVIOCSKEYCODE_V2, e, True)
            print('set 0x%03x -> %d (%s)' % (int(sc, 0), e.keycode,
                                             KEY_NAMES.get(e.keycode, '?')))
            continue
        sc = int(arg, 0)
        e = KeymapEntry(INPUT_KEYMAP_BY_INDEX, 0, sc, 0)
        fcntl.ioctl(fd, EVIOCGKEYCODE_V2, e, True)
        print('0x%03x -> %d (%s)' % (sc, e.keycode, KEY_NAMES.get(e.keycode, '?')))
    fd.close()


if __name__ == '__main__':
    main()
