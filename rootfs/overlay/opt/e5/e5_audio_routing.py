#!/usr/bin/python3
"""Shared E5 audio routing and ownership. No modem call-control operations."""
import fcntl
import json
import os
from pathlib import Path
import subprocess
import time

RUNTIME = Path(os.environ.get('XDG_RUNTIME_DIR', '/run/user/1000'))
VOICE_PENDING = RUNTIME / 'e5-voice.pending'


def graph():
    return json.loads(subprocess.check_output(['pw-dump'], timeout=5))


def headset(objects):
    """Use a connected HFP-capable device; never persist a particular MAC."""
    for obj in objects:
        if obj['type'] != 'PipeWire:Interface:Device':
            continue
        info = obj.get('info', {})
        props = info.get('props', {})
        if props.get('device.api') != 'bluez5':
            continue
        profiles = info.get('params', {}).get('EnumProfile', [])
        hfp = [p for p in profiles if p['name'].startswith('headset-head-unit')
               and p.get('available') == 'yes']
        if not hfp:
            continue
        active = info.get('params', {}).get('Profile', [{}])[0]
        return {'id': obj['id'], 'address': props['api.bluez5.address'],
                'name': props.get('device.description', 'Bluetooth headset'),
                'profiles': profiles, 'hfp': hfp, 'active': active,
                'rate': 16000 if active.get('name') == 'headset-head-unit' else 8000}
    return None


def select_hfp(device):
    if not device['active'].get('name', '').startswith('headset-head-unit'):
        profile = next((p for p in device['hfp'] if p['name'] == 'headset-head-unit'), device['hfp'][0])
        subprocess.run(['wpctl', 'set-profile', str(device['id']), str(profile['index'])],
                       check=True, timeout=5)
        device['rate'] = 16000 if profile['name'] == 'headset-head-unit' else 8000


def offload(device, enabled):
    subprocess.run(['pw-cli', 'set-param', str(device['id']), 'Props',
                    '{ bluetoothOffloadActive: ' + str(bool(enabled)).lower() + ' }'],
                   check=True, timeout=5, stdout=subprocess.DEVNULL)


def pending_voice():
    try:
        pid = int(VOICE_PENDING.read_text())
        os.kill(pid, 0)
        return True
    except FileNotFoundError:
        return False
    except (ValueError, ProcessLookupError):
        VOICE_PENDING.unlink(missing_ok=True)
        return False


class Lease:
    def __init__(self):
        self.file = None

    def acquire(self, wait=False, voice=False):
        if self.file:
            return True
        RUNTIME.mkdir(mode=0o700, parents=True, exist_ok=True)
        if voice:
            VOICE_PENDING.write_text(str(os.getpid()))
        file = open(RUNTIME / 'e5-audio-hardware.lock', 'a')
        deadline = time.monotonic() + (5 if wait else 0)
        while True:
            try:
                fcntl.flock(file, fcntl.LOCK_EX | fcntl.LOCK_NB)
                self.file = file
                return True
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    file.close()
                    if voice:
                        VOICE_PENDING.unlink(missing_ok=True)
                    return False
                time.sleep(.05)

    def release(self, voice=False):
        if self.file:
            self.file.close()
            self.file = None
        if voice:
            VOICE_PENDING.unlink(missing_ok=True)


BT_ROUTES = {
    'SYS_IIS0': 'vbc_iis3',
    'VBC_MUX_DAC1_IIS_PORT_SEL': 'VBC_IIS_PORT_IIS3',
    'VBC_MUX_IIS3_PORT_DO_SEL': 'IIS_DO_VAL_DAC1',
    'VBC_MUX_MST_IIS0_PORT_DO_SEL': 'IIS_DO_VAL_DAC0',
    'VBC_MUX_ADC2': 'ADC_IN_IIS0_ADC',
    'VBC_MUX_ADC2_IIS_PORT_SEL': 'VBC_IIS_PORT_IIS3',
    'VBC_IIS_TX0_WD_SEL': 'WD_16BIT',
    'VBC_IIS_TX1_WD_SEL': 'WD_16BIT',
    'VBC_IIS_RX2_WD_SEL': 'WD_16BIT',
    'VBC_IIS_MASTER_ENALBE': 'enable',
    'VBC_IIS_MST_SEL_0_TYPE': 'VBC_MASTER_INTERNAL',
    'VBC ADC2 DG Set': '24,24',
}
