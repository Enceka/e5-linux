#!/usr/bin/python3
"""Hold early rcS on an LK charger boot; a long power press resumes boot.

No vendor, radio, network or screen session runs while this gate is waiting.
Charging and thermal protection remain under the kernel's charger manager.
"""
import fcntl
import json
import os
from pathlib import Path
import re
import runpy
import select
import struct
import subprocess
import time

SYS = Path('/sys')
STATE = Path('/run/charge-mode.json')
EVENT = struct.Struct('@llHHi')
KEY_POWER = 116
HOLD = 1.5
UNPLUG_DEBOUNCE = .5


def charger_boot(commandline):
    return bool(re.search(r'(?:^|\s)(?:sprdboot|androidboot)\.mode=charger(?:\s|$)',
                          commandline.replace('\0', ' ')))


def power_on_supply():
    try:
        result = subprocess.run(['uci', '-q', 'get', 'e5-charge.main.power_on'],
                                capture_output=True, text=True, timeout=2)
        return result.returncode == 0 and result.stdout.strip() == '1'
    except (OSError, subprocess.TimeoutExpired):
        return False


def bitmap_has(text, bit):
    words = text.split()[::-1]
    word, offset = divmod(bit, struct.calcsize('@L') * 8)
    return word < len(words) and bool(int(words[word], 16) & (1 << offset))


def cable_online(root=None):
    root = SYS if root is None else root
    values = []
    for supply in (root / 'class/power_supply').glob('*'):
        try:
            kind = (supply / 'type').read_text().strip()
            if kind == 'Battery':
                continue
            if (kind in ('Mains', 'Wireless') or kind.startswith('USB')
                    or supply.name in ('ac', 'usb', 'wireless')):
                value = (supply / 'online').read_text().strip()
                if value in ('0', '1'):
                    values.append(value == '1')
        except OSError:
            continue
    return any(values) if values else None


def input_devices(root=None):
    root = SYS if root is None else root
    keys, touches = [], []
    for device in (root / 'class/input').glob('event*'):
        try:
            caps = device / 'device/capabilities'
            key = (caps / 'key').read_text()
            if bitmap_has(key, KEY_POWER):
                keys.append(Path('/dev/input') / device.name)
            if bitmap_has(key, 330) or bitmap_has((caps / 'abs').read_text(), 53):
                touches.append(device / 'device/inhibited')
        except OSError:
            continue
    return keys, touches


class PowerHold:
    def __init__(self):
        self.pressed = {}

    def event(self, source, kind, code, value, now):
        if kind == 0 and code == 3:  # SYN_DROPPED: never trust a lost release
            self.pressed.pop(source, None)
        elif kind == 1 and code == KEY_POWER:
            if value == 1:
                self.pressed.setdefault(source, now)
            elif value == 0:
                self.pressed.pop(source, None)

    def ready(self, now):
        return any(now - start >= HOLD for start in self.pressed.values())


def report(state, reason):
    STATE.write_text(json.dumps({'state': state, 'reason': reason,
                                 'uptime': time.monotonic()}) + '\n')
    print('charge-mode: ' + state + ': ' + reason, flush=True)


def power_is_down(fd):
    keys = bytearray(96)
    fcntl.ioctl(fd, 0x80000000 | (len(keys) << 16) | (ord('E') << 8) | 0x18, keys)
    return bool(keys[KEY_POWER // 8] & (1 << (KEY_POWER % 8)))


def open_display(backlights):
    try:
        module = runpy.run_path('/usr/libexec/e5-charge-screen')
        return module['Display'](backlights)
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        print('charge-mode: display unavailable: ' + str(error), flush=True)
        return None


def wait_for_power(keys, display=None):
    held = PowerHold()
    descriptors = {}
    disconnected = None
    try:
        for key in keys:
            fd = os.open(key, os.O_RDONLY | os.O_NONBLOCK | os.O_CLOEXEC)
            descriptors[fd] = b''
            if power_is_down(fd):
                held.event(fd, 1, KEY_POWER, 1, time.monotonic())
        while True:
            for fd in select.select(list(descriptors), [], [], .1)[0]:
                chunk = os.read(fd, EVENT.size * 64)
                if not chunk:
                    raise RuntimeError('power input disconnected')
                data = descriptors[fd] + chunk
                count = len(data) // EVENT.size * EVENT.size
                for _, _, kind, code, value in EVENT.iter_unpack(data[:count]):
                    held.event(fd, kind, code, value, time.monotonic())
                    if display and kind == 1 and code == KEY_POWER and value == 1:
                        display.show(time.monotonic())
                descriptors[fd] = data[count:]
            now = time.monotonic()
            if display:
                try:
                    display.tick(now)
                except (OSError, ValueError, RuntimeError) as error:
                    print('charge-mode: display stopped: ' + str(error), flush=True)
                    display.close()
                    display = None
            if held.ready(now):
                # Verify against the kernel state, not just a potentially lost
                # key-up event. Repeats must not restart the hold timer.
                if any(power_is_down(fd) for fd, start in held.pressed.items()
                       if now - start >= HOLD):
                    return 'power-key'
                held.pressed.clear()
            online = cable_online()
            if online is False:
                if disconnected is None:
                    disconnected = now
                if now - disconnected >= UNPLUG_DEBOUNCE:
                    return 'cable-removed'
            else:
                disconnected = None
    finally:
        for fd in descriptors:
            os.close(fd)


def shutdown_step(command):
    try:
        subprocess.run(command, check=True, timeout=5)
    except (OSError, subprocess.SubprocessError) as error:
        print('charge-mode: shutdown: ' + str(error), flush=True)


def poweroff_charging(display, backlights):
    # rcS is deliberately still inside S14. Do not ask procd to run its K
    # queue over the active boot queue and then wait forever for it to finish.
    # Only this early charging gate may use the direct kernel poweroff path.
    if display:
        try:
            display.close()
        except (OSError, ValueError, RuntimeError) as error:
            print('charge-mode: closing display: ' + str(error), flush=True)
    for path in backlights:
        try:
            path.write_text('0\n')
        except OSError as error:
            print('charge-mode: blanking display: ' + str(error), flush=True)
    try:
        report('poweroff', 'cable-removed')
    except OSError as error:
        print('charge-mode: poweroff state: ' + str(error), flush=True)
    # S99 boot-ok has not run. A deliberate charging shutdown must not consume
    # the next Linux attempt; --rearm preserves the user's default/trial choice.
    shutdown_step(['/opt/e5/e5-next-boot', '--rearm'])
    shutdown_step(['/bin/sync'])
    # Freeze the root filesystem before its image's backing filesystem. This
    # also works with a TF root; virtual filesystems and NV are not touched.
    shutdown_step(['/bin/mount', '-o', 'remount,ro', '/'])
    if Path('/mnt/e5-data').is_mount():
        shutdown_step(['/bin/mount', '-o', 'remount,ro', '/mnt/e5-data'])
    shutdown_step(['/bin/sync'])
    while True:
        # BusyBox -f calls reboot(RB_POWER_OFF), still syncing and running the
        # kernel's device shutdown/PMIC callbacks. Never use -n or reboot here.
        shutdown_step(['/sbin/poweroff', '-f'])
        print('charge-mode: poweroff returned; retrying in one second', flush=True)
        time.sleep(1)


def run():
    commandline = (SYS / 'firmware/devicetree/base/chosen/bootargs').read_text()
    if not charger_boot(commandline) or Path('/tmp/.failsafe').exists():
        return
    if power_on_supply():
        report('normal', 'power-on-supply enabled')
        return
    # Treat absent input/backlight as a recoverable boot fault, not a device
    # that can no longer be switched on. No undocumented PMIC writes.
    deadline = time.monotonic() + 10
    while True:
        keys, touches = input_devices()
        backlights = list((SYS / 'class/backlight').glob('*/brightness'))
        if keys and backlights and touches and cable_online() is not None:
            break
        if time.monotonic() >= deadline:
            raise RuntimeError('charging-mode hardware unavailable; continuing normal boot')
        time.sleep(.1)
    saved = {p: p.read_text() for p in backlights + touches}
    resume = True
    display = None
    try:
        for path in touches:
            path.write_text('1\n')
        for path in backlights:
            path.write_text('0\n')
        report('charging', 'waiting for a 1.5 second power press')
        display = open_display(backlights)
        reason = wait_for_power(keys, display)
        if reason == 'cable-removed':
            resume = False
            closing, display = display, None
            poweroff_charging(closing, backlights)
            return
        report('normal', reason)
    finally:
        if display:
            display.close()
        if resume:
            setting = subprocess.run(['uci', '-q', 'get', 'e5-infoscreen.main.touch'],
                                     capture_output=True, text=True, timeout=3)
            for path in touches:
                path.write_text('1\n' if setting.stdout.strip() == '0' else '0\n')
            for path in backlights:
                path.write_text(saved[path])


if __name__ == '__main__':
    try:
        with open('/run/charge-mode.lock', 'a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            run()
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        report('normal', 'recovery: ' + str(error))
