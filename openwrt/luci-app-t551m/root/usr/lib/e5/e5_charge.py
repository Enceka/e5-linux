"""Web settings for the existing e5-charge policy, also used by the screen."""
import fcntl
import os
from pathlib import Path
import re
import subprocess

BAT = Path('/sys/class/power_supply/battery')
SUPPLY = BAT.parent
STATE = Path('/tmp/run/e5-charge')
SERVICE = Path('/etc/init.d/e5-charge')
LOCK = Path('/var/lock/e5-charge-web.lock')
METHODS = {'get': {}, 'configure': {'enabled': '', 'start': '', 'stop': '', 'power_on': ''},
           'full_once': {}}


def read(path, default=''):
    try:
        return path.read_text().strip()
    except OSError:
        return default


def run(args, **kwargs):
    return subprocess.run(args, capture_output=True, text=True, timeout=8, **kwargs)


def cfg(key, default):
    result = run(['uci', '-q', 'get', 'e5-charge.main.' + key])
    return result.stdout.strip() if result.returncode == 0 else default


def integer(value, low, high):
    if isinstance(value, bool) or not re.fullmatch(r'[0-9]{1,3}', str(value)):
        raise ValueError('charge_invalid')
    number = int(value)
    if not low <= number <= high:
        raise ValueError('charge_invalid')
    return number


def available():
    return (os.access(BAT / 'charger.0/stop_charge', os.W_OK)
            and (BAT / 'capacity').is_file() and os.access(SERVICE, os.X_OK))


def status():
    cap = read(BAT / 'capacity')
    try:
        capacity = integer(cap, 0, 100)
    except ValueError:
        capacity = None
    try:
        current_ma = int(read(BAT / 'current_now')) / 1000
    except ValueError:
        current_ma = None
    return {'ok': True, 'available': available(), 'capacity': capacity,
            'current_ma': current_ma,
            'status': read(BAT / 'status'),
            'online': any(read(SUPPLY / name / 'online') == '1' for name in ('usb', 'ac')),
            'stopped': read(STATE / 'stopped') == '1',
            'enabled': cfg('enabled', '0') == '1',
            'power_on': cfg('power_on', '0') == '1',
            'start': integer(cfg('start', '70'), 20, 95),
            'stop': integer(cfg('stop', '80'), 50, 100),
            'full_once': cfg('full_once', '0') == '1'}


def dispatch(method, data):
    if method == 'get':
        return status()
    if method not in ('configure', 'full_once'):
        raise ValueError('charge_invalid')
    # Validate everything before changing any UCI setting or touching hardware.
    if method == 'configure':
        enabled = integer(data.get('enabled'), 0, 1)
        start = integer(data.get('start'), 20, 95)
        stop = integer(data.get('stop'), 50, 100)
        if start >= stop:
            raise ValueError('charge_threshold_order')
        values = {'enabled': enabled, 'start': start, 'stop': stop}
        # Older clients omit this key; preserve the independent boot preference.
        if data.get('power_on') not in (None, ''):
            values['power_on'] = integer(data['power_on'], 0, 1)
        if not enabled:
            values['full_once'] = 0
    else:
        values = {'full_once': 1}
    if not available():
        raise ValueError('charge_unavailable')
    LOCK.parent.mkdir(parents=True, exist_ok=True)
    with LOCK.open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        commands = ['set e5-charge.main=charge']
        commands += ['set e5-charge.main.%s=%s' % item for item in values.items()]
        commands += ['commit e5-charge']
        # Only bounded integers and fixed keys enter UCI; never invoke a shell.
        if run(['uci', '-q', 'batch'], input='\n'.join(commands) + '\n').returncode:
            raise RuntimeError('charge_save_failed')
        try:
            result = run([str(SERVICE), 'reload'])
            if result.returncode:
                return {'ok': False, 'saved': True, 'error': 'charge_reload_failed'}
        except (OSError, subprocess.TimeoutExpired):
            return {'ok': False, 'saved': True, 'error': 'charge_reload_failed'}
    return status()
