#!/usr/bin/env python3
"""Exercise the web policy adapter without writing to any real charger."""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / 'luci-app-t551m'
spec = importlib.util.spec_from_file_location('charge', APP / 'root/usr/lib/e5/e5_charge.py')
c = importlib.util.module_from_spec(spec)
spec.loader.exec_module(c)


class Charge(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        for name, value in [('BAT', root/'power/battery'), ('SUPPLY', root/'power'),
                            ('STATE', root/'state'), ('SERVICE', root/'service'), ('LOCK', root/'lock')]:
            mock = patch.object(c, name, value)
            mock.start(); self.addCleanup(mock.stop)
        (c.BAT/'charger.0').mkdir(parents=True)
        (c.BAT/'charger.0/stop_charge').write_text('0')
        (c.BAT/'capacity').write_text('76')
        (c.BAT/'status').write_text('Not charging')
        (c.SUPPLY/'usb').mkdir()
        (c.SUPPLY/'usb/online').write_text('1')
        c.STATE.mkdir()
        c.SERVICE.write_text('#!/bin/sh\n')
        c.SERVICE.chmod(0o755)
        self.config = dict(enabled='1', start='70', stop='80', full_once='0', power_on='0')
        self.calls = []
        self.reload_rc = self.batch_rc = 0
        mock = patch.object(c, 'run', side_effect=self.command)
        mock.start(); self.addCleanup(mock.stop)

    def command(self, args, **kwargs):
        self.calls.append((args, kwargs))
        if args[:3] == ['uci', '-q', 'get']:
            return subprocess.CompletedProcess(args, 0, self.config[args[-1].split('.')[-1]], '')
        if args == ['uci', '-q', 'batch']:
            if self.batch_rc == 0:
                for line in kwargs['input'].splitlines():
                    if line.startswith('set e5-charge.main.'):
                        key, value = line[len('set e5-charge.main.'):].split('=')
                        self.config[key] = value
            return subprocess.CompletedProcess(args, self.batch_rc, '', '')
        self.assertEqual(args, [str(c.SERVICE), 'reload'])
        return subprocess.CompletedProcess(args, self.reload_rc, '', '')

    def save(self, **kwargs):
        return c.dispatch('configure', dict(enabled='1', start='65', stop='85', **kwargs))

    def test_screen_and_web_share_persistent_values(self):
        result = self.save()
        self.assertTrue(result['ok'])
        self.assertEqual((result['start'], result['stop']), (65, 85))
        self.assertEqual(self.config['start'], '65')
        self.assertIn('commit e5-charge\n', self.calls[0][1]['input'])
        # Simulate the screen changing UCI: the very next web read follows it.
        self.config.update(start='60', stop='90')
        self.assertEqual(c.status()['start'], 60)
        self.assertEqual(c.status()['stop'], 90)

    def test_supply_boot_option_is_persistent_and_older_clients_preserve_it(self):
        self.assertTrue(self.save(power_on='1')['power_on'])
        self.assertEqual(self.config['power_on'], '1')
        self.assertTrue(self.save()['power_on'])
        self.assertFalse(self.save(power_on='0')['power_on'])
        self.calls.clear()
        with self.assertRaises(ValueError):
            self.save(power_on='2')
        self.assertEqual(self.calls, [])
        self.assertEqual((c.BAT/'charger.0/stop_charge').read_text(), '0')

    def test_bad_input_never_changes_config_or_calls_service(self):
        for key, value in [('start','95'), ('start','19'), ('stop','101'),
                           ('start','65;reboot'), ('stop','80.5'), ('enabled',True),
                           ('enabled','2'), ('start',None)]:
            with self.subTest(key=key, value=value):
                self.calls.clear()
                args = dict(enabled='1', start='70', stop='80'); args[key] = value
                with self.assertRaises(ValueError): c.dispatch('configure', args)
                self.assertEqual(self.calls, [])

    def test_unavailable_hardware_cannot_save_or_request_full(self):
        (c.BAT/'charger.0/stop_charge').unlink()
        self.assertFalse(c.status()['available'])
        self.calls.clear()
        for method in ('configure', 'full_once'):
            with self.assertRaisesRegex(ValueError, 'charge_unavailable'):
                c.dispatch(method, dict(enabled='1', start='70', stop='80'))
        self.assertFalse(self.calls)

    def test_charge_once_and_disabling_limit(self):
        once = c.dispatch('full_once', {})
        self.assertTrue(once['full_once'])
        self.assertEqual(once['stop'], 80)
        result = c.dispatch('configure', dict(enabled='0', start='70', stop='80'))
        self.assertFalse(result['full_once'])
        self.assertFalse(result['enabled'])

    def test_runtime_status_and_missing_capacity(self):
        (c.STATE/'stopped').write_text('1')
        self.assertTrue(c.status()['stopped'])
        self.assertTrue(c.status()['online'])
        (c.BAT/'current_now').write_text('250000')
        self.assertEqual(c.status()['current_ma'], 250)
        (c.SUPPLY/'usb/online').write_text('0')
        self.assertFalse(c.status()['online'])
        (c.BAT/'capacity').write_text('invalid')
        self.assertIsNone(c.status()['capacity'])

    def test_no_false_success_on_save_or_service_failure(self):
        self.batch_rc = 1
        with self.assertRaisesRegex(RuntimeError, 'charge_save_failed'): self.save()
        self.assertEqual(len(self.calls), 1)
        self.calls.clear(); self.batch_rc = 0; self.reload_rc = 1
        result = self.save()
        self.assertFalse(result['ok'])
        self.assertTrue(result['saved'])
        self.assertEqual(result['error'], 'charge_reload_failed')
        self.assertEqual(self.config['stop'], '85')

    def test_packaging_and_acl(self):
        acl = json.loads((APP/'root/usr/share/rpcd/acl.d/luci-app-mu300.json').read_text())['luci-app-mu300']
        self.assertEqual(acl['read']['ubus']['e5-charge'], ['get'])
        self.assertEqual(acl['write']['ubus']['e5-charge'], ['configure','full_once'])
        self.assertIn('usr/libexec/rpcd/e5-charge', (APP/'Makefile').read_text())
        screen = (ROOT.parent/'devices/t551m/infoscreen/base/settings.uc').read_text()
        for key in ('enabled','start','stop','full_once'):
            self.assertIn(key, screen)
        self.assertIn('e5-charge.main.stop', screen)


if __name__ == '__main__': unittest.main()
