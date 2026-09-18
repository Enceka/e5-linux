#!/usr/bin/env python3
"""Tap (or swipe) on the e5's panel through /dev/uinput.

The phone's only real input devices are the 9-key keypad and the touch panel, so a
remote session cannot reach the UI without injecting events.  This creates a
touchscreen that libinput accepts (ABS_MT_POSITION_X/Y + BTN_TOUCH) and taps at a
point in *physical* pixels -- i.e. what grim captures is logical, so multiply by
320/scale first.

    tools/touch-tap.py 160 46                 # one tap
    tools/touch-tap.py 160 46 --hold 0.2      # a longer press
"""
import ctypes
import fcntl
import sys
import time

UI_SET_EVBIT = 0x40045564
UI_SET_KEYBIT = 0x40045565
UI_SET_ABSBIT = 0x40045567
UI_DEV_CREATE = 0x5501
UI_DEV_DESTROY = 0x5502
UI_DEV_SETUP = 0x405C5503
UI_ABS_SETUP = 0x401C5504

EV_SYN, EV_KEY, EV_ABS = 0x00, 0x01, 0x03
BTN_TOUCH = 0x14A
ABS_MT_SLOT = 0x2F
ABS_MT_POSITION_X = 0x35
ABS_MT_POSITION_Y = 0x36
ABS_MT_TRACKING_ID = 0x39
SYN_REPORT = 0


class InputId(ctypes.Structure):
    _fields_ = [('bustype', ctypes.c_uint16), ('vendor', ctypes.c_uint16),
                ('product', ctypes.c_uint16), ('version', ctypes.c_uint16)]


class AbsInfo(ctypes.Structure):
    _fields_ = [('value', ctypes.c_int32), ('minimum', ctypes.c_int32),
                ('maximum', ctypes.c_int32), ('fuzz', ctypes.c_int32),
                ('flat', ctypes.c_int32), ('resolution', ctypes.c_int32)]


class AbsSetup(ctypes.Structure):
    _fields_ = [('code', ctypes.c_uint16), ('pad', ctypes.c_uint16),
                ('absinfo', AbsInfo)]


class UinputSetup(ctypes.Structure):
    _fields_ = [('id', InputId), ('name', ctypes.c_char * 80),
                ('ff_effects_max', ctypes.c_uint32)]


class InputEvent(ctypes.Structure):
    _fields_ = [('tv_sec', ctypes.c_long), ('tv_usec', ctypes.c_long),
                ('type', ctypes.c_uint16), ('code', ctypes.c_uint16),
                ('value', ctypes.c_int32)]


def main():
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    if len(args) < 2:
        sys.exit(__doc__)
    x, y = int(args[0]), int(args[1])
    hold = 0.05
    if '--hold' in sys.argv:
        hold = float(sys.argv[sys.argv.index('--hold') + 1])

    fd = open('/dev/uinput', 'wb', buffering=0)
    fcntl.ioctl(fd, UI_SET_EVBIT, EV_KEY)
    fcntl.ioctl(fd, UI_SET_EVBIT, EV_ABS)
    fcntl.ioctl(fd, UI_SET_KEYBIT, BTN_TOUCH)
    for code, maximum in ((ABS_MT_SLOT, 9), (ABS_MT_TRACKING_ID, 65535),
                          (ABS_MT_POSITION_X, 4095), (ABS_MT_POSITION_Y, 4095)):
        fcntl.ioctl(fd, UI_SET_ABSBIT, code)
        fcntl.ioctl(fd, UI_ABS_SETUP,
                    AbsSetup(code, 0, AbsInfo(0, 0, maximum, 0, 0, 0)), True)
    fcntl.ioctl(fd, UI_DEV_SETUP,
                UinputSetup(InputId(0x03, 0x1234, 0x5679, 1), b'e5-touch-inject', 0),
                True)
    fcntl.ioctl(fd, UI_DEV_CREATE)
    time.sleep(1.0)

    def emit(etype, code, value):
        fd.write(bytes(InputEvent(0, 0, etype, code, value)))

    emit(EV_ABS, ABS_MT_SLOT, 0)
    emit(EV_ABS, ABS_MT_TRACKING_ID, 1)
    emit(EV_ABS, ABS_MT_POSITION_X, x)
    emit(EV_ABS, ABS_MT_POSITION_Y, y)
    emit(EV_KEY, BTN_TOUCH, 1)
    emit(EV_SYN, SYN_REPORT, 0)
    time.sleep(hold)
    emit(EV_ABS, ABS_MT_TRACKING_ID, -1)
    emit(EV_KEY, BTN_TOUCH, 0)
    emit(EV_SYN, SYN_REPORT, 0)
    time.sleep(0.2)
    fcntl.ioctl(fd, UI_DEV_DESTROY)
    fd.close()
    print('tapped %d,%d' % (x, y))


if __name__ == '__main__':
    main()
