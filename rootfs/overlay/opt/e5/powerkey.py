#!/usr/bin/env python3
"""Phone-style power key for the E5 (no suspend: the modem refuses it).

Runs as the session user so it can talk to the session bus.

  * short press  -- if the panel is off, turn it back on; otherwise lock the session
                    (phosh's lock screen) and turn the panel off;
  * long press   -- gnome-session's "Power Off" dialog, i.e. the menu a phone shows
                    for a held power key.  It counts down and powers off unless it is
                    cancelled, and it is the one thing here that needs a deliberate
                    hold: suspend is unusable on this board ("sipa ... thread prepare
                    suspend err"), so power off and restart are the only actions
                    worth offering.

Every step is logged so a press can be verified from the journal.

The action happens on *release*, except for a long press, which fires as soon as the
hold passes LONG_PRESS seconds -- so the dialog appears while the key is still down,
like it does on a phone.
"""
import glob
import os
import select
import struct
import subprocess
import sys
import time

KEYS = '/dev/input/event0'
TOUCH = '/dev/input/event1'
KEY_POWER = 116
LONG_PRESS = 1.5
BL = glob.glob('/sys/class/backlight/*/bl_power')[0]
DRM_DPMS = '/sys/class/drm/card0-DSI-1/dpms'


def log(msg):
    print(msg, flush=True)


def run(cmd, timeout=10):
    try:
        res = subprocess.run(cmd, capture_output=True, timeout=timeout)
        log('%s -> rc=%d %s' % (' '.join(cmd), res.returncode,
                                res.stderr.decode().strip()[:80]))
        return res.returncode == 0
    except Exception as exc:
        log('%s -> %s' % (' '.join(cmd), exc))
        return False


def no_blank():
    """Stop the compositor blanking the panel behind our back.

    phoc blanks on idle and it owns DPMS, so once it has blanked this script can
    write bl_power all it likes and the screen stays black -- the CRTC is off and only
    the compositor can turn it back on.  Worse, bl_power still reads "0" at that
    point, so the panel would look "on" to us, the power key would *turn it off*, and
    the branch that is supposed to wake it could never run.  With idle blanking off
    the backlight is the only thing controlling the panel and the toggle is coherent.
    """
    run(['gsettings', 'set', 'org.gnome.desktop.session', 'idle-delay', '0'])


def panel(off):
    try:
        with open(BL, 'w') as f:
            f.write('1' if off else '0')
        log('panel off' if off else 'panel on')
    except OSError as exc:
        log('panel error: %s' % exc)


def screen_is_off():
    """True when the panel is dark for any reason (ours or the compositor's)."""
    try:
        with open(BL) as f:
            if f.read().strip() != '0':
                return True
    except OSError:
        pass
    try:
        with open(DRM_DPMS) as f:
            return f.read().strip().lower() != 'on'
    except OSError:
        return False


def lock_session():
    if run(['loginctl', 'lock-sessions']) or run(
            ['gdbus', 'call', '--session', '--dest', 'org.gnome.ScreenSaver',
             '--object-path', '/org/gnome/ScreenSaver',
             '--method', 'org.gnome.ScreenSaver.Lock']):
        return
    log('could not lock the session')


def short_press():
    if screen_is_off():
        panel(False)
        return
    lock_session()
    panel(True)


def long_press():
    log('long press: power menu')
    run(['gnome-session-quit', '--power-off'], timeout=5)


fds = {}
for path in (KEYS, TOUCH):
    try:
        fds[os.open(path, os.O_RDONLY | os.O_NONBLOCK)] = path
    except OSError as exc:
        log('open %s: %s' % (path, exc))
if not fds:
    sys.exit('no input devices')

no_blank()
panel(False)
log('watching %s (long press = %.1fs)' % (', '.join(fds.values()), LONG_PRESS))

pressed_at = None
handled_long = False
while True:
    timeout = None
    if pressed_at is not None and not handled_long:
        timeout = max(0.0, LONG_PRESS - (time.monotonic() - pressed_at))
    ready, _, _ = select.select(list(fds), [], [], timeout)
    if not ready and pressed_at is not None and not handled_long:
        handled_long = True
        long_press()
        continue
    for fd in ready:
        data = os.read(fd, 24 * 64)
        for off in range(0, len(data) - 23, 24):
            _, _, typ, code, val = struct.unpack_from('qqHHi', data, off)
            if fds[fd] == KEYS and code == KEY_POWER:
                if val == 1:
                    pressed_at = time.monotonic()
                    handled_long = False
                elif val == 0 and pressed_at is not None:
                    if not handled_long:
                        short_press()
                    pressed_at = None
                    handled_long = False
            elif val == 1 and screen_is_off():
                # any other key or a touch is a wake-up, same as on a phone
                panel(False)
