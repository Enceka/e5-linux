#!/usr/bin/env python3
"""Inject key events through /dev/uinput (ctypes, no python-evdev needed).

Used to answer two questions on the E5 without a USB keyboard:

  * does phosh's lock screen unlock on Return?   (send the PIN + Return)
  * does a synthetic Enter work at all in this session?

    tools/key-inject.py 1 2 3 4 5 6 enter
    tools/key-inject.py --hold 0.05 enter

Keys are given as names from the small table below (digits, enter, backspace,
select, up/down/left/right, escape, tab, space).
"""
import ctypes
import fcntl
import struct
import sys
import time

UI_SET_EVBIT = 0x40045564
UI_SET_KEYBIT = 0x40045565
UI_DEV_CREATE = 0x5501
UI_DEV_DESTROY = 0x5502
UI_DEV_SETUP = 0x405C5503
EV_SYN, EV_KEY = 0x00, 0x01
SYN_REPORT = 0

KEYS = {
    '1': 2, '2': 3, '3': 4, '4': 5, '5': 6, '6': 7, '7': 8, '8': 9, '9': 10,
    '0': 11, 'enter': 28, 'kpenter': 96, 'escape': 1, 'backspace': 14, 'tab': 15, 'space': 57,
    'select': 353, 'up': 103, 'down': 108, 'left': 105, 'right': 106,
    'playpause': 164, 'phone': 169,
}


class InputId(ctypes.Structure):
    _fields_ = [('bustype', ctypes.c_uint16), ('vendor', ctypes.c_uint16),
                ('product', ctypes.c_uint16), ('version', ctypes.c_uint16)]


class UinputSetup(ctypes.Structure):
    _fields_ = [('id', InputId), ('name', ctypes.c_char * 80),
                ('ff_effects_max', ctypes.c_uint32)]


class Timeval(ctypes.Structure):
    _fields_ = [('tv_sec', ctypes.c_long), ('tv_usec', ctypes.c_long)]


class InputEvent(ctypes.Structure):
    _fields_ = [('time', Timeval), ('type', ctypes.c_uint16),
                ('code', ctypes.c_uint16), ('value', ctypes.c_int32)]


def main():
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    hold = 0.03
    if '--hold' in sys.argv:
        hold = float(sys.argv[sys.argv.index('--hold') + 1])
    codes = [KEYS[a] if a in KEYS else int(a, 0) for a in args]
    if not codes:
        sys.exit('no keys given')

    fd = open('/dev/uinput', 'wb', buffering=0)
    fcntl.ioctl(fd, UI_SET_EVBIT, EV_KEY)
    for code in set(codes) | {28}:
        fcntl.ioctl(fd, UI_SET_KEYBIT, code)
    setup = UinputSetup(InputId(0x03, 0x1234, 0x5678, 1), b'e5-key-inject', 0)
    fcntl.ioctl(fd, UI_DEV_SETUP, setup, True)
    fcntl.ioctl(fd, UI_DEV_CREATE)
    time.sleep(1.0)

    def emit(etype, code, value):
        ev = InputEvent(Timeval(0, 0), etype, code, value)
        fd.write(bytes(ev))

    for code in codes:
        emit(EV_KEY, code, 1)
        emit(EV_SYN, SYN_REPORT, 0)
        time.sleep(hold)
        emit(EV_KEY, code, 0)
        emit(EV_SYN, SYN_REPORT, 0)
        time.sleep(hold)
    time.sleep(0.3)
    fcntl.ioctl(fd, UI_DEV_DESTROY)
    fd.close()
    print('injected %d key(s)' % len(codes))


if __name__ == '__main__':
    main()
