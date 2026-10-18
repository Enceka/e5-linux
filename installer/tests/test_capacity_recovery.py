"""Capacity failures retain evidence and never replay installation writes."""
import io
import json
from pathlib import Path
import struct
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.service import Service, FilesystemCapacityError, plan_install, verify_ext4_capacity
from backend.state import Context, Store
from test_state import PACKAGE, DEVICE


class CapacityRecovery(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(self.temp.name)
        self.service = Service('.', self.store, io.StringIO())

    def tearDown(self):
        self.temp.cleanup()

    def record(self, kind, method, grow=True, legacy=False):
        plan = {'method': method, 'openwrt_bytes': 4 << 30}
        if not legacy:
            plan['grow'] = grow
        record = self.store.create({**PACKAGE, 'adapter': kind}, DEVICE.copy(),
                                   {'method': method, 'grow': grow}, plan)
        record.update(stage='verify_capacity', status='failed',
                      update_boot_id='11111111-1111-4111-8111-111111111111')
        self.store.save(record)
        return record

    def verify(self, record, size):
        raw = bytearray(1024)
        raw[56:58] = b'\x53\xef'
        struct.pack_into('<II', raw, 4, size // 4096, 0)
        struct.pack_into('<I', raw, 24, 2)
        commands = []
        def read(command, timeout=15):
            commands.append(command)
            if command == 'cat /sys/class/block/mmcblk0/device/cid':
                value = DEVICE['cid']
            elif command == 'cat /proc/sys/kernel/random/boot_id':
                value = '22222222-2222-4222-8222-222222222222'
            elif command.startswith('readlink -f') or command == 'cat /run/mu300/disk-dev':
                value = '/dev/mmcblk0p20'
            elif command.startswith('dd if='):
                value = bytes(raw)
            elif command == 'test -s /etc/openwrt_release && test -x /sbin/init':
                value = ''
            else:
                raise AssertionError(command)
            return None, SimpleNamespace(read=lambda: value if isinstance(value, bytes) else value.encode(),
                                         channel=SimpleNamespace(recv_exit_status=lambda: 0)), None
        client = Mock()
        client.exec_command.side_effect = read
        adapter = SimpleNamespace(password='', probe=Mock(side_effect=AssertionError('Android probe replayed')),
                                  execute=Mock(side_effect=AssertionError('Installer replayed')))
        context = Context(self.store, self.store.load(record['id']), self.service.emit)
        with patch('paramiko.SSHClient', return_value=client):
            self.service.run(context, adapter)
        adapter.probe.assert_not_called()
        adapter.execute.assert_not_called()
        self.assertTrue(all(command.startswith(('cat ', 'readlink -f', 'dd if=', 'test -s '))
                            and 'of=' not in command for command in commands))
        return self.store.load(record['id'])

    def test_short_filesystem_keeps_diagnostics_across_restart_and_retry(self):
        for kind in ('e5', 'mu300'):
            for method in ('tf', 'part', 'reinstall', 'image', 'update'):
                with self.subTest(kind=kind, method=method):
                    record = self.record(kind, method)
                    failed = self.verify(record, 2 << 30)
                    self.assertEqual(failed['status'], 'failed')
                    self.assertEqual(failed['error']['code'], 'capacity_mismatch')
                    self.assertTrue(failed['error']['retryable'])
                    evidence = failed['capacity_check']
                    self.assertEqual(evidence['status'], 'mismatch')
                    self.assertEqual(evidence['filesystem_bytes'], 2 << 30)
                    self.assertEqual(evidence['expected_bytes'], 4 << 30)
                    self.assertEqual(evidence['allocated_bytes'], 4 << 30)
                    self.assertEqual(evidence['device'], '/dev/mmcblk0p20')
                    self.assertEqual((evidence['adapter'], evidence['method']), (kind, method))
                    reopened = Service('.', Store(self.temp.name), io.StringIO())
                    copied = reopened.dispatch({'protocol': 1, 'command': 'diagnostics',
                                                'params': {'transaction': record['id']}})['text']
                    header = json.loads(copied.split('\n\n')[0].split('\n', 1)[1])
                    self.assertEqual(header['capacity_check'], evidence)
                    for private in (DEVICE['cid'], DEVICE['serial']):
                        self.assertNotIn(private, copied)
                    verified = self.verify(failed, 4 << 30)
                    self.assertEqual(verified['status'], 'completed')
                    self.assertEqual(verified['capacity_check']['status'], 'verified')
                    self.assertEqual(verified['result']['filesystem_bytes'], 4 << 30)

    def test_old_no_grow_records_do_not_report_a_failed_expansion(self):
        for kind in ('e5', 'mu300'):
            for method in ('part', 'reinstall'):
                with self.subTest(kind=kind, method=method):
                    record = self.record(kind, method, grow=False, legacy=True)
                    result = self.verify(record, 2 << 30)
                    self.assertEqual(result['status'], 'completed')
                    self.assertEqual(result['result']['filesystem_bytes'], 2 << 30)
                    self.assertFalse(result['capacity_check']['grow'])

    def test_hidden_no_grow_choice_cannot_skip_tf_image_or_update_checks(self):
        for kind in ('e5', 'mu300'):
            for method in ('tf', 'image', 'update'):
                with self.subTest(kind=kind, method=method):
                    result = self.verify(self.record(kind, method, grow=False), 2 << 30)
                    self.assertEqual(result['error']['code'], 'capacity_mismatch')
                    self.assertTrue(result['capacity_check']['grow'])

    def test_confirmed_plan_overrides_legacy_choice(self):
        record = self.record('mu300', 'part', grow=False)
        record['plan']['grow'] = True
        self.store.save(record)
        self.assertEqual(self.verify(record, 2 << 30)['error']['code'], 'capacity_mismatch')

    def test_growth_option_only_applies_to_partition_install_or_reinstall(self):
        for kind in ('e5', 'mu300'):
            for method in ('tf', 'part', 'reinstall', 'image', 'boot', 'update'):
                with self.subTest(kind=kind, method=method):
                    device = {**DEVICE, 'encrypted': False, 'capacity': 4 << 30,
                              'tf': '/dev/block/mmcblk1p1', 'tf_bytes': 32 << 30,
                              'existing': method == 'reinstall',
                              'storage': {**DEVICE['storage'], 'ROOT': 'mmcblk0p20',
                                          'ROOT_SIZE': (4 << 30) // 512}}
                    package = {**PACKAGE, 'adapter': kind, 'payloads': {}}
                    plan = plan_install(package, device, {'method': method, 'grow': False,
                                                         'host': '192.0.2.1'})
                    self.assertEqual(plan['grow'], method not in ('part', 'reinstall'))

    def test_error_explains_boot_and_capacity_are_separate(self):
        raw = bytearray(1024)
        raw[56:58] = b'\x53\xef'
        struct.pack_into('<I', raw, 4, (2 << 30) // 4096)
        struct.pack_into('<I', raw, 24, 2)
        with self.assertRaises(FilesystemCapacityError) as raised:
            verify_ext4_capacity(raw, 4 << 30)
        self.assertEqual((raised.exception.actual, raised.exception.expected), (2 << 30, 4 << 30))
        self.assertIn('2.00 GiB', str(raised.exception))
        self.assertIn('4.00 GiB', str(raised.exception))
        self.assertIn('重试只复核容量', str(raised.exception))


if __name__ == '__main__':
    unittest.main()
