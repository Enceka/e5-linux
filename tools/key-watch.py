#!/usr/bin/env python3
"""Print key events from an input device (an evtest for a box without one).

    tools/key-watch.py [device-name-or-path] [seconds]

Prints `code value` per event plus a name for the codes we care about, which is how
the keypad's confirm key was traced: KEY_SELECT (353) from the hardware, or whatever
a udev/hwdb KEYBOARD_KEY_<scancode> rule has remapped it to.
"""
import glob
import os
import struct
import sys
import time

NAMES = {28: 'ENTER', 96: 'KP_ENTER', 353: 'SELECT', 158: 'BACK', 103: 'UP',
         108: 'DOWN', 105: 'LEFT', 106: 'RIGHT', 523: 'PHONE', 139: 'MENU',
         169: 'NEXT', 55: 'KPASTERISK', 2: '1', 3: '2', 4: '3', 5: '4', 6: '5',
         7: '6', 8: '7', 9: '8', 10: '9', 11: '0', 1: 'ESC', 14: 'BACKSPACE',
         116: 'POWER', 115: 'VOLUMEUP', 114: 'VOLUMEDOWN'}
EVENT = struct.calcsize('<qqHHi')


def resolve(spec):
    if spec.startswith('/'):
        return spec
    for path in sorted(glob.glob('/sys/class/input/event*/device/name')):
        try:
            with open(path) as fh:
                if fh.read().strip() == spec:
                    return '/dev/input/' + path.split('/')[4]
        except OSError:
            continue
    return None


def main():
    spec = sys.argv[1] if len(sys.argv) > 1 else 'sprd-keypad'
    secs = float(sys.argv[2]) if len(sys.argv) > 2 else 30
    path = resolve(spec)
    if not path:
        sys.exit('no such input device: %s' % spec)
    print('watching %s for %.0fs' % (path, secs), flush=True)
    fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
    end = time.time() + secs
    while time.time() < end:
        try:
            data = os.read(fd, EVENT * 32)
        except BlockingIOError:
            time.sleep(0.02)
            continue
        for _s, _u, etype, code, value in struct.iter_unpack('<qqHHi', data):
            if etype == 1:                      # EV_KEY
                print('key %-12s code=%-4d value=%d'
                      % (NAMES.get(code, '?'), code, value), flush=True)
    os.close(fd)


if __name__ == '__main__':
    main()
