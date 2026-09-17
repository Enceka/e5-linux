#!/usr/bin/env python3
"""Phone-style power key for the E5 (no suspend: the modem refuses it).

Runs as the session user so it can talk to the session bus.  A short KEY_POWER press
locks the session (phosh's lock screen, via org.gnome.ScreenSaver) and turns the panel
off; a touch on event1 or any other key turns the panel back on.  Every step is logged
so a press can be verified from the journal.
"""
import glob
import os
import select
import struct
import subprocess
import sys

KEYS = '/dev/input/event0'
TOUCH = '/dev/input/event1'
KEY_POWER = 116
BL = glob.glob('/sys/class/backlight/*/bl_power')[0]


def log(msg):
    print(msg, flush=True)


def panel(off):
    try:
        with open(BL, 'w') as f:
            f.write('1' if off else '0')
        log('panel off' if off else 'panel on')
    except OSError as exc:
        log('panel error: %s' % exc)


def locked():
    try:
        with open(BL) as f:
            return f.read().strip() != '0'
    except OSError:
        return False


def lock_session():
    for cmd in (['gdbus', 'call', '--session', '--dest', 'org.gnome.ScreenSaver',
                 '--object-path', '/org/gnome/ScreenSaver',
                 '--method', 'org.gnome.ScreenSaver.Lock'],
                ['loginctl', 'lock-sessions']):
        try:
            res = subprocess.run(cmd, capture_output=True, timeout=5)
            log('%s -> rc=%d %s' % (cmd[0], res.returncode, res.stderr.decode().strip()[:80]))
            if res.returncode == 0:
                return
        except Exception as exc:
            log('%s -> %s' % (cmd[0], exc))


fds = {}
for path in (KEYS, TOUCH):
    try:
        fds[os.open(path, os.O_RDONLY | os.O_NONBLOCK)] = path
    except OSError as exc:
        log('open %s: %s' % (path, exc))
if not fds:
    sys.exit('no input devices')

panel(False)
log('watching %s' % ', '.join(fds.values()))
while True:
    ready, _, _ = select.select(list(fds), [], [])
    for fd in ready:
        data = os.read(fd, 24 * 64)
        for off in range(0, len(data) - 23, 24):
            _, _, typ, code, val = struct.unpack_from('qqHHi', data, off)
            if val != 1:
                continue
            if fds[fd] == KEYS and code == KEY_POWER:
                if locked():
                    panel(False)
                else:
                    lock_session()
                    panel(True)
            elif locked():
                panel(False)
