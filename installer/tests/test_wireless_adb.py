"""Host-only ADB connection management; no physical device or network access."""
import copy
import io
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.service import Service
from backend.state import DeviceLock, Store
from backend.transport import Adb, adb_endpoint, wireless_serial


class WirelessAdbTest(unittest.TestCase):
    def adb(self):
        adb = Adb.__new__(Adb)
        adb.exe, adb.serial, adb.context = 'fixture-adb', 'usb-existing', None
        return adb

    def result(self, output, code=0):
        return subprocess.CompletedProcess([], code, output.encode(), b'')

    def test_endpoints_are_normalized_without_command_text(self):
        for value, expected in [('192.168.0.1','192.168.0.1:5555'),
                                (' PHONE.local:12345 ','phone.local:12345'),
                                ('[2001:db8::1]:5556','[2001:db8::1]:5556'),
                                ('::1','[::1]:5555')]:
            with self.subTest(value=value): self.assertEqual(adb_endpoint(value), expected)
        for value in [None, 123, '', '-a', '--help', 'x;reboot', 'x&reboot', 'x$(reboot)',
                      'x\nreboot', 'x y', 'http://x', 'x/abc', 'x:', 'x:0', 'x:65536',
                      'x:-1', 'x:abc', '999.168.0.1', '[bad::ip]:5555', 'a..b', '-a.local']:
            with self.subTest(value=value), self.assertRaises(ValueError): adb_endpoint(value)

    def test_connect_uses_fixed_argv_and_actual_enumeration_even_if_cli_claims_failure(self):
        replies = [self.result('cannot connect (fixture terminal text)'),
                   self.result('List of devices attached\n192.168.0.1:5555 unauthorized\nusb-1234 device model:M8\n')]
        with patch('backend.transport.subprocess.run', side_effect=replies) as run:
            result = self.adb().connect('192.168.0.1')
        self.assertEqual(result['state'], 'unauthorized')
        self.assertEqual(len(result['devices']), 2)
        self.assertTrue(result['devices'][0]['wireless'])
        self.assertFalse(result['devices'][1]['wireless'])
        self.assertEqual(run.call_args_list[0].args[0], ['fixture-adb','connect','192.168.0.1:5555'])
        self.assertEqual(run.call_args_list[1].args[0], ['fixture-adb','devices','-l'])
        self.assertNotIn('shell', run.call_args_list[0].kwargs)

    def test_success_text_without_device_is_failure_and_can_retry(self):
        replies = [self.result('connected to 192.168.0.1:5555'), self.result('List of devices attached\n'),
                   self.result('anything'), self.result('List of devices attached\n192.168.0.1:5555 device model:M8\n')]
        with patch('backend.transport.subprocess.run', side_effect=replies):
            adb = self.adb()
            with self.assertRaises(ConnectionError): adb.connect('192.168.0.1')
            self.assertEqual(adb.connect('192.168.0.1')['state'], 'device')

    def test_offline_device_is_reported_as_offline(self):
        with patch('backend.transport.subprocess.run', side_effect=[self.result(''), self.result('List of devices attached\n192.168.0.1:5555 offline\n')]):
            self.assertEqual(self.adb().connect('192.168.0.1')['state'], 'offline')

    def test_timeout_and_invalid_address_cannot_report_success(self):
        with patch('backend.transport.subprocess.run') as run:
            with self.assertRaises(ValueError): self.adb().connect('x;reboot')
            run.assert_not_called()
        with patch('backend.transport.subprocess.run', side_effect=subprocess.TimeoutExpired('adb',15)):
            with self.assertRaisesRegex(ConnectionError, 'timed out'): self.adb().connect('192.168.0.1')

    def test_disconnect_is_exactly_one_observed_wireless_device(self):
        before = 'List of devices attached\n192.168.0.1:5555 device\n192.168.0.2:5555 device\nusb-1234 device\n'
        after = 'List of devices attached\n192.168.0.2:5555 device\nusb-1234 device\n'
        with patch('backend.transport.subprocess.run', side_effect=[self.result(before),self.result('done'),self.result(after)]) as run:
            result = self.adb().disconnect('192.168.0.1:5555')
        self.assertEqual(run.call_args_list[1].args[0], ['fixture-adb','disconnect','192.168.0.1:5555'])
        self.assertEqual([d['serial'] for d in result['devices']], ['192.168.0.2:5555','usb-1234'])
        for serial in [None, '', 'usb-1234', '--all', '192.168.0.3:5555']:
            with self.subTest(serial=serial), patch('backend.transport.subprocess.run', return_value=self.result(before)) as run:
                with self.assertRaises(ValueError): self.adb().disconnect(serial)
                self.assertFalse(any('disconnect' in c.args[0] for c in run.call_args_list))

    def test_disconnect_checks_result_and_supports_mdns_network_serials(self):
        serial = 'adb-DEVICE-ABC._adb-tls-connect._tcp'
        self.assertTrue(wireless_serial(serial))
        self.assertFalse(wireless_serial('usb-1234'))
        listing = self.result('List of devices attached\n'+serial+' device\n')
        with patch('backend.transport.subprocess.run', side_effect=[listing,self.result('disconnected'),listing]):
            with self.assertRaises(ConnectionError): self.adb().disconnect(serial)

    def test_protocol_needs_no_package_and_keeps_the_transaction_bound(self):
        with tempfile.TemporaryDirectory() as temp, patch('backend.service.Adb') as adb:
            service = Service(temp, Store(temp), io.StringIO())
            service.worker = Mock(is_alive=lambda:True)
            record = {'stage':'android_setup','status':'waiting_user','unsafe':False,
                      'device':{'serial':'192.168.0.1:5555','cid':'original'}}
            service.active = SimpleNamespace(record=record)
            original = copy.deepcopy(record)
            adb.return_value.connect.return_value = {'endpoint':'192.168.0.1:5555','state':'device','devices':[]}
            service.dispatch({'protocol':1,'command':'adb_connect','params':{'address':'192.168.0.1'}})
            self.assertEqual(record, original)
            self.assertIsNone(service.package)
            with self.assertRaises(ValueError): service.dispatch({'protocol':1,'command':'adb_disconnect','params':{'serial':'192.168.0.1:5555'}})
            for stage,status,unsafe in [('transfer_install','running',False),('prepare','running',True),('openwrt_boot','waiting_device',False)]:
                record.update(stage=stage,status=status,unsafe=unsafe)
                with self.assertRaises(ValueError): service.dispatch({'protocol':1,'command':'adb_connect','params':{'address':'192.168.0.1'}})
                with self.assertRaises(ValueError): service.dispatch({'protocol':1,'command':'adb_disconnect','params':{'serial':'192.168.0.1:5555'}})
            self.assertEqual(adb.return_value.connect.call_count, 1)
            adb.return_value.disconnect.assert_not_called()
            service.worker = None
            service.dispatch({'protocol':1,'command':'adb_disconnect','params':{'serial':'192.168.0.1:5555'}})
            adb.return_value.disconnect.assert_called_once_with('192.168.0.1:5555')

    def test_another_installer_process_cannot_disconnect_the_locked_transport(self):
        code = """
import io,sys
from unittest.mock import patch
sys.path.insert(0,sys.argv[1])
from backend.service import Service
from backend.state import Store
with patch('backend.service.Adb') as adb:
    try:
        Service(sys.argv[2],Store(sys.argv[2]),io.StringIO()).dispatch({'protocol':1,'command':'adb_disconnect','params':{'serial':'192.0.2.1:5555'}})
    except ValueError as error:
        assert 'Another installer' in str(error)
        adb.assert_not_called()
        print('blocked by device lock')
    else:
        raise AssertionError('Disconnect bypassed the active device lock')
"""
        with tempfile.TemporaryDirectory() as temp, DeviceLock(temp,'192.0.2.1:5555'):
            result=subprocess.run([sys.executable,'-c',code,str(Path(__file__).resolve().parents[1]),temp],capture_output=True,timeout=20)
            self.assertEqual(result.returncode,0,result.stderr.decode('utf-8','replace'))
            self.assertIn(b'blocked by device lock',result.stdout)


if __name__ == '__main__': unittest.main()
