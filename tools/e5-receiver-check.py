#!/usr/bin/python3
"""Read receiver registers during a user-controlled call; never control calls.

Run on Debian as root: e5-receiver-check.py [--seconds 180] [--output DIR]
Only reads ModemManager Call properties, ALSA procfs and DAPM. It does not
change mixers, open PCMs, consume audio_pipe_voice or place/answer/end calls.
Register dumps are sequential reads, so a sample during a route change is
not atomic. Interpret readiness together with the route and PCM state.
"""
import argparse
import json
from pathlib import Path
import re
import time

# Offsets from UMP9620 sprd-codec.h, relative to CODEC_AP_BASE_AGCP.
REGISTERS = {
    0x0050: 'ANA_DAC0', 0x0054: 'ANA_DAC1',
    0x0088: 'ANA_CDC5', 0x0090: 'ANA_CDC7',
    0x0094: 'ANA_CDC8', 0x0098: 'ANA_CDC9', 0x009c: 'ANA_CDC10',
    0x00a8: 'ANA_CDC13', 0x0100: 'ANA_DCL1', 0x0110: 'ANA_DCL5',
    0x0114: 'ANA_DCL6', 0x017c: 'ANA_DBG4', 0x0188: 'ANA_STS1',
}


def analog_registers(text):
    analog = text.split(' analog part\n', 1)[1].split(' audif\n', 1)[0]
    registers = {}
    for row in analog.splitlines():
        match = re.match(r'0x([0-9a-fA-F]+) \| (.+)', row)
        if match:
            offset = int(match[1], 16)
            for i, value in enumerate(match[2].split()):
                address = offset + i * 4
                if address in REGISTERS:
                    registers[REGISTERS[address]] = int(value, 16)
    if len(registers) != len(REGISTERS):
        raise RuntimeError('incomplete analog register dump')
    return registers


def snapshot(root, tag):
    stamp = time.time()
    text = Path('/proc/asound/card0/sprd-codec').read_text()
    (root / f'{tag}-registers.txt').write_text(text)
    registers = analog_registers(text)
    status = registers['ANA_STS1']
    decoded = {
        'RCV_DCCAL_DVLD': bool(status & (1 << 10)),
        'RCV_LOOP_DVLD': bool(status & (1 << 1)),
        'RCV_DAC_FDIN_DVLD': bool(status & 1),
        'SDAHPL_RCV': bool(registers['ANA_CDC9'] & 1),
        'SDAAOL_RCV': bool(registers['ANA_CDC9'] & 2),
        'RCV_EN': bool(registers['ANA_CDC10'] & 2),
        'DIG_CLK_RCV_EN': bool(registers['ANA_DCL1'] & (1 << 11)),
        'RCV_DPOP_EN': bool(registers['ANA_DBG4'] & (1 << 8)),
        'RCV_DPOP_BPS': bool(registers['ANA_DCL5'] & (1 << 8)),
    }
    pcm = {}
    for direction in ('p', 'c'):
        pcm[direction] = Path(f'/proc/asound/card0/pcm5{direction}/sub0/status').read_text()
    dapm = {}
    for directory in Path('/sys/kernel/debug/asoc').glob('*/**/dapm'):
        for name in ('EAR_HPL Path', 'EAR_HPL Mixer', 'EAR Switch', 'EAR Gain',
                     'SDAHPL RCV', 'RCV DEPOP', 'DIG_CLK_RCV', 'Ext Spk'):
            path = directory / name
            if path.is_file():
                dapm[name] = path.read_text().splitlines()[0]
    result = {'time': stamp, 'tag': tag, 'registers': registers,
              'decoded': decoded, 'pcm': pcm, 'dapm': dapm}
    (root / f'{tag}.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({'tag': tag, 'registers': registers, 'decoded': decoded}), flush=True)


def main():
    from gi.repository import Gio, GLib
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--seconds', type=int, default=180)
    parser.add_argument('--output', type=Path, default=Path('/tmp/e5-receiver-check'))
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    bus = Gio.bus_get_sync(Gio.BusType.SYSTEM, None)
    def read(path, interface):
        return bus.call_sync('org.freedesktop.ModemManager1', path,
            'org.freedesktop.DBus.Properties', 'GetAll', GLib.Variant('(s)', (interface,)),
            None, Gio.DBusCallFlags.NONE, 3000, None).unpack()[0]
    snapshot(args.output, 'idle')
    print('READY; waiting for a manual call', flush=True)
    start = time.monotonic()
    calls = {}
    ended = set()
    points = (0, 0.25, 1, 3, 7, 12)
    while time.monotonic() - start < args.seconds:
        objects = bus.call_sync('org.freedesktop.ModemManager1', '/org/freedesktop/ModemManager1',
            'org.freedesktop.DBus.ObjectManager', 'GetManagedObjects', None, None,
            Gio.DBusCallFlags.NONE, 3000, None).unpack()[0]
        active = set()
        for path, interfaces in objects.items():
            if 'org.freedesktop.ModemManager1.Modem.Voice' not in interfaces:
                continue
            for call in read(path, 'org.freedesktop.ModemManager1.Modem.Voice').get('Calls', []):
                try:
                    if read(call, 'org.freedesktop.ModemManager1.Call').get('State') == 4:
                        active.add(call)
                except GLib.Error:
                    continue  # Call may disappear between the two property reads.
        now = time.monotonic()
        for call in active:
            if call not in calls:
                calls[call] = [now, 0]
            since, index = calls[call]
            if index < len(points) and now - since >= points[index]:
                snapshot(args.output, f'call-{call.rsplit("/", 1)[-1]}-{index}')
                calls[call][1] += 1
        for call in calls.keys() - active - ended:
            snapshot(args.output, f'call-{call.rsplit("/", 1)[-1]}-ended')
            ended.add(call)
            print('ENDED manual call', call.rsplit('/', 1)[-1], flush=True)
        time.sleep(0.1)


if __name__ == '__main__':
    main()
