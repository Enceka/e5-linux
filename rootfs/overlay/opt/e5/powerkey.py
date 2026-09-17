#!/usr/bin/env python3
"""Phone-style power key for the E5.

Suspend is not usable on this board -- the modem data path refuses it
('sipa 25220000.sipa: thread prepare suspend err'), and phosh does not act on
KEY_POWER itself -- so the key is handled here: a short press turns the panel off
(bl_power=1) and asks logind to lock the session; a touch or any other key turns it
back on.  gpio-keys is /dev/input/event0 and the panel is the sprd backlight.
"""
import glob
import os
import select
import struct
import subprocess

KEYS = '/dev/input/event0'
TOUCH = '/dev/input/event1'
KEY_POWER = 116
BL = glob.glob('/sys/class/backlight/*/bl_power')[0]


def panel(on):
    try:
        with open(BL, 'w') as f:
            f.write('0' if on else '1')
    except OSError as exc:
        print('panel:', exc)


def is_off():
    try:
        with open(BL) as f:
            return f.read().strip() == '1'
    except OSError:
        return False


fds = {}
for path in (KEYS, TOUCH):
    try:
        fds[os.open(path, os.O_RDONLY | os.O_NONBLOCK)] = path
    except OSError as exc:
        print('open', path, exc)
if not fds:
    raise SystemExit('no input devices')

panel(True)
print('powerkey: watching', ', '.join(fds.values()))
while True:
    ready, _, _ = select.select(list(fds), [], [])
    for fd in ready:
        data = os.read(fd, 24 * 64)
        for off in range(0, len(data) - 23, 24):
            _, _, typ, code, val = struct.unpack_from('qqHHi', data, off)
            power = fds[fd] == KEYS and code == KEY_POWER
            if typ == 1 and val == 1:
                if power and not is_off():
                    subprocess.run(['loginctl', 'lock-sessions'], check=False)
                    panel(False)
                elif is_off():
                    panel(True)
            elif is_off() and fds[fd] == TOUCH and typ == 3:
                panel(True)
