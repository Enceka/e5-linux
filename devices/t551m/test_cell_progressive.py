"""Run the real collector against a gated AT adapter, with no modem access.

Linux/WSL: python3 devices/t551m/test_cell_progressive.py
"""
import json
import os
from pathlib import Path
import signal
import subprocess
import tempfile
import time
import unittest
from test_dashboard_data import JSONFILTER_STUB

COLLECTOR = Path(__file__).resolve().parents[2] / 'openwrt/luci-app-t551m/root/usr/libexec/unisoc-modem/cell'
ADAPTER = '''#!/usr/bin/env python3
import os, sys, time
from pathlib import Path
root = Path(os.environ['TEST_CELL_ROOT'])
cmd = sys.argv[-1]
with (root / 'commands').open('a') as f: f.write(cmd + '\\n')
gate = {'AT+SPENGMD=0,6,0':'engineering', 'AT+SPENGMD=0,6,6':'neighbors', 'AT+CGEQOSRDP=4':'identity'}.get(cmd)
if gate:
    (root / (gate + '.waiting')).touch()
    until = time.monotonic() + 10
    while not (root / (gate + '.release')).exists():
        if time.monotonic() > until: sys.exit(1)
        time.sleep(.01)
answers = {
    'AT+CFUN?': '+CFUN: 1',
    'AT+CEREG?': '+CEREG: 2,1,"0010","00123456",7',
    'AT+C5GREG?': '+C5GREG: 2,0',
    'AT+CESQ': '+CESQ: 99,99,255,255,20,50',
    'AT+CSCS?;+COPS?': '+CSCS: "UCS2"\\n+COPS: 0,0,"4E2D56FD8054901A",7',
    'AT+SPENGMD=0,6,0': '8-3500-22-+9300-+1100-0-0-5-0-0-10-2',
    'AT+SPENGMD=0,6,6': '3500,23,+9600,+1200,0-0,0,0,0',
    'AT+CGMI': 'TEST', 'AT+CGMM': 'TEST', 'AT+CGMR': 'TEST',
    'AT+CGSN': '123456789012345', 'AT+CIMI': '001010000000001',
    'AT+CCID': '00000000000000000001'
}
print(answers.get(cmd, ''))
print('OK')
'''


class ProgressiveCollector(unittest.TestCase):
    def wait_gate(self, root, name, proc):
        deadline = time.monotonic() + 8
        while not (root / (name + '.waiting')).exists():
            self.assertIsNone(proc.poll(), 'Collector exited before its next stage')
            self.assertLess(time.monotonic(), deadline, 'Collector stage timed out')
            time.sleep(.02)

    def test_stages_are_visible_before_slow_commands_finish(self):
        for slot in ['0', '1']:
            with self.subTest(slot=slot), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                at = root / 'at'
                at.write_text(ADAPTER); at.chmod(0o755)
                bins=root/'bin';bins.mkdir()
                for name,body in (('jsonfilter',JSONFILTER_STUB),('ubus','#!/bin/sh\nprintf \'%s\\n\' "$TEST_WAN"\n')):
                    path=bins/name;path.write_text(body);path.chmod(0o755)
                env = dict(os.environ, MU300_SIM_SLOT=slot, MU300_AT=str(at),
                           PATH=str(bins)+os.pathsep+os.environ['PATH'],
                           TEST_WAN=json.dumps({'up':True,'l3_device':'sipa_eth3' if slot=='0' else 'sipa_eth11','uptime':42}),
                           MU300_DASH_DIR=str(root / 'cache'), MU300_DASH_IDENT_DIR=str(root / 'ident'),
                           MU300_DASH_POOL_DIR=str(root / 'pool'), TEST_CELL_ROOT=str(root))
                proc = subprocess.Popen(['sh', str(COLLECTOR)], env=env, start_new_session=True)
                read = lambda name: json.loads((root / 'cache' / (name + '.json')).read_text())
                try:
                    self.wait_gate(root, 'engineering', proc)
                    self.assertEqual(read('sig')['partial'], 1)
                    self.assertEqual(read('sig')['card'], int(slot))
                    (root / 'engineering.release').touch()
                    self.wait_gate(root, 'neighbors', proc)
                    self.assertEqual(read('sig')['lte']['band'], 8)
                    self.assertEqual(read('cell')['neigh_pending'], 1)
                    (root / 'neighbors.release').touch()
                    self.wait_gate(root, 'identity', proc)
                    cell = read('cell')
                    self.assertEqual(cell['neigh_pending'], 0)
                    self.assertEqual(cell['partial'], 1)
                    self.assertEqual(cell['neigh'][0]['pci'], 23)
                    self.assertIsNone(cell['ident'])
                    (root / 'identity.release').touch()
                    self.assertEqual(proc.wait(timeout=8), 0)
                    cell = read('cell')
                    self.assertEqual(cell['partial'], 0)
                    self.assertEqual(cell['ident']['model'], 'TEST')
                    self.assertEqual(cell['neigh'][0]['pci'], 23)
                    self.assertEqual(cell['card'], int(slot))
                    self.assertEqual(cell['operator'],{'name':'中国联通','plmn':None,'act':7})
                    self.assertFalse((root / 'cache/collect.lck').exists())
                    commands = (root / 'commands').read_text()
                    self.assertNotIn('AT+SFUN', commands)
                    self.assertNotIn('AT+SPACTCARD', commands)
                finally:
                    if proc.poll() is None:
                        os.killpg(proc.pid, signal.SIGKILL); proc.wait()


if __name__ == '__main__':
    unittest.main()
