#!/usr/bin/python3
"""Feed the sole platform input from internal or SCO PCM, only when in use."""
import importlib.util
import json
import logging
import os
from pathlib import Path
import re
import select
import signal
import stat
import subprocess
import time

import e5_audio_routing as routing

spec = importlib.util.spec_from_file_location('e5_voice', '/opt/e5/e5-call-audio.py')
voice = importlib.util.module_from_spec(spec)
spec.loader.exec_module(voice)


class Capture:
    def __init__(self):
        self.hardware = voice.VoiceHardware()
        self.lease = routing.Lease()
        self.recorder = None
        self.saved = {}
        self.device = None
        self.key = None
        pcms = Path('/proc/asound/pcm').read_text()
        self.pcms = {}
        for name in ('FE_ST_CAPTURE_DSP', 'FE_ST_CAPTURE_BTSCO_DSP'):
            match = re.search(r'^(\d+)-(\d+): ' + name + r' ', pcms, re.M)
            if not match:
                raise RuntimeError('missing capture frontend ' + name)
            self.pcms[name] = tuple(map(int, match.groups()))

    def stop(self):
        if self.recorder:
            self.recorder.send_signal(signal.SIGINT)
            try:
                self.recorder.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.recorder.kill()
                self.recorder.wait()
            self.recorder.stdout.close()
            self.recorder = None
        # PCM closes before route restoration and before the next scene opens.
        try:
            if self.saved:
                self.hardware.restore(self.saved)
        finally:
            self.saved = {}
            self.key = None
            self.device = None
            self.lease.release()

    def start(self, device):
        self.stop()
        if routing.pending_voice() or not self.lease.acquire():
            return False
        try:
            self.device = device
            if device:
                controls = dict(routing.BT_ROUTES)
                controls['S_BTSCO_CAP_DSP_C SWITCH'] = 'on'
                controls['VBC_SRC_BT_DAC'] = device['rate']
                controls['VBC_SRC_BT_ADC'] = device['rate']
                self.saved = {name: self.hardware.get(name) for name in controls}
                for name, value in controls.items():
                    self.hardware.put(name, value)
                name = 'FE_ST_CAPTURE_BTSCO_DSP'
            else:
                name = 'FE_ST_CAPTURE_DSP'
            card, pcm = self.pcms[name]
            self.recorder = subprocess.Popen([
                'arecord', '-q', '-D', f'hw:{card},{pcm}', '-t', 'raw', '-f',
                'S16_LE', '-r', '48000', '-c', '1', '--period-size=960',
                '--buffer-size=7680', '-'], stdout=subprocess.PIPE)
            status = Path(f'/proc/asound/card{card}/pcm{pcm}c/sub0/status')
            for attempt in range(100):
                if self.recorder.poll() is not None:
                    raise RuntimeError('capture PCM exited during startup')
                if 'state: RUNNING' in status.read_text():
                    break
                time.sleep(.01)
            else:
                raise RuntimeError('capture PCM did not start')
            if device:
                # DSP scene startup reloads SRC: apply the actual SCO rate again.
                self.hardware.put('VBC_SRC_BT_DAC', device['rate'])
                self.hardware.put('VBC_SRC_BT_ADC', device['rate'])
            os.set_blocking(self.recorder.stdout.fileno(), False)
            self.key = (device['address'], device['rate']) if device else ('internal', 48000)
            logging.info('capture route=%s PCM=hw:%s,%s', self.key, card, pcm)
            return True
        except Exception:
            self.stop()
            raise


def main():
    logging.basicConfig(level=logging.INFO, format='e5-capture: %(message)s')
    stop = False

    def end(*args):
        nonlocal stop
        stop = True

    signal.signal(signal.SIGTERM, end)
    signal.signal(signal.SIGINT, end)
    capture = Capture()
    fifo = routing.RUNTIME / 'e5-capture.pcm'
    deadline = time.monotonic() + 15
    while not fifo.exists() and time.monotonic() < deadline:
        time.sleep(.1)
    if not fifo.exists() or not stat.S_ISFIFO(fifo.stat().st_mode):
        raise RuntimeError('PipeWire microphone FIFO is unavailable')
    fifo.chmod(0o600)
    fd = os.open(fifo, os.O_WRONLY | os.O_NONBLOCK)
    update = 0
    wanted = False
    device = None
    retry = 0
    try:
        while not stop:
            now = time.monotonic()
            if now >= update:
                objects = routing.graph()
                node = next((o for o in objects if o['type'] == 'PipeWire:Interface:Node'
                             and o.get('info', {}).get('props', {}).get('node.name') == 'e5_microphone'), None)
                wanted = bool(node and node['info'].get('state') == 'running')
                device = routing.headset(objects)
                if device and not device['active'].get('name', '').startswith('headset-head-unit'):
                    device = None
                if routing.pending_voice():
                    wanted = False
                key = ((device['address'], device['rate']) if device else ('internal', 48000)) if wanted else None
                if capture.key != key:
                    capture.stop()
                    if wanted and now >= retry:
                        try:
                            if not capture.start(device):
                                retry = now + .5
                        except Exception:
                            logging.exception('capture route could not start')
                            retry = now + 2
                update = now + .2
            if capture.recorder and capture.recorder.poll() is not None:
                logging.error('capture stream ended; releasing hardware')
                capture.stop()
                retry = now + 1
            if capture.recorder:
                if select.select([capture.recorder.stdout], [], [], .02)[0]:
                    data = os.read(capture.recorder.stdout.fileno(), 4096)
                else:
                    continue
            else:
                if not wanted:
                    time.sleep(.02)
                    continue
                data = bytes(960)
                time.sleep(.01)
            if data:
                try:
                    os.write(fd, data)
                except BlockingIOError:
                    pass
    finally:
        capture.stop()
        os.close(fd)


if __name__ == '__main__':
    main()
