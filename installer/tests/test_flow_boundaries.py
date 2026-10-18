"""Restart/fault matrix using real coordinator, journals and SSH verification.

Every transport is replaced before execution; no device is contacted.
"""
import io
import struct
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.service import Service, plan_install
from backend.state import Context, Store
from test_state import PACKAGE, DEVICE


class FlowBoundaries(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(self.temp.name)
        self.service = Service('.', self.store, io.StringIO())
        self.record = self.store.create(PACKAGE, DEVICE.copy(), {'method':'part', 'size_gib':4},
                                        plan_install(PACKAGE, DEVICE, {'method':'part', 'size_gib':4}))

    def tearDown(self):
        self.temp.cleanup()

    def restart_and_verify(self, expected_failure=False, disconnect=False):
        # Load from disk with a new Store/Context, as after a computer restart.
        store = Store(self.temp.name)
        record = store.load(self.record['id'])
        context = Context(store, record, self.service.emit)
        adapter = SimpleNamespace(password='', probe=Mock(side_effect=AssertionError('Android probe replayed')),
                                  execute=Mock(side_effect=AssertionError('Device writes replayed')))
        raw = bytearray(1024)
        raw[56:58] = b'\x53\xef'
        struct.pack_into('<I', raw, 24, 2)
        struct.pack_into('<I', raw, 4, ((2 if expected_failure else 4) << 30)//4096)
        def read(command, timeout=15):
            if command == 'cat /sys/class/block/mmcblk0/device/cid':
                value = DEVICE['cid']
            elif command.startswith('readlink -f') or command == 'cat /run/mu300/disk-dev':
                value = '/dev/mmcblk0p20'
            elif command.startswith('dd if='):
                value = bytes(raw)
            elif command == 'test -s /etc/openwrt_release && test -x /sbin/init':
                value = ''
            else:
                raise AssertionError('Unexpected SSH command: '+command)
            return None, SimpleNamespace(read=lambda:value if isinstance(value,bytes) else value.encode(), channel=SimpleNamespace(recv_exit_status=lambda:0)), None
        client = Mock()
        client.exec_command.side_effect = read
        if disconnect:
            client.connect.side_effect = [EOFError('Expected SSH loss during reboot'), None]
        with patch('paramiko.SSHClient', return_value=client), patch.object(self.service.stop, 'wait', return_value=False):
            self.service.run(context, adapter)
        adapter.probe.assert_not_called()
        adapter.execute.assert_not_called()
        saved = store.load(record['id'])
        self.assertEqual(saved['status'], 'failed' if expected_failure else 'completed')
        if expected_failure:
            self.assertIn('capacity', saved['error']['message'])
            self.assertTrue(saved['error']['retryable'])
        else:
            self.assertEqual(saved['result']['filesystem_bytes'], 4 << 30)
        return saved

    def test_restart_during_final_capacity_check_only_verifies_openwrt(self):
        for status in ('running', 'cancelled', 'failed'):
            with self.subTest(status=status):
                self.record.update(stage='verify_capacity', status=status)
                self.store.save(self.record)
                self.restart_and_verify()

    def test_capacity_failure_retry_does_not_reinstall(self):
        self.record.update(stage='verify_capacity', status='failed')
        self.store.save(self.record)
        self.restart_and_verify(expected_failure=True)
        self.restart_and_verify()

    def test_restart_between_final_write_and_wait_checkpoint(self):
        for kind, method, final in [('e5','tf','misc-trial'), ('e5','part','misc-trial'),
                                    ('e5','image','misc-trial'), ('e5','boot','misc-trial'),
                                    ('mu300','boot','misc-trial'), ('mu300','tf','root-tf-write'), ('mu300','part','boot-and-misc-1234'),
                                    ('mu300','reinstall','boot-and-misc-5678'), ('mu300','image','boot-and-misc-90ab')]:
            with self.subTest(adapter=kind,method=method):
                self.record.update(package={**PACKAGE,'adapter':kind}, choices={'method':method},
                                   stage='prepare', status='running', effects={final:{'state':'done'}}, legacy=None)
                self.record['plan']['method'] = method
                self.store.save(self.record)
                self.restart_and_verify()

    def test_preparation_or_partial_effect_is_not_a_final_commit(self):
        from backend.adapter import installation_committed
        for kind, effects, legacy in [('e5',{'root-tf-write':{'state':'done'}},None),
                                      ('e5',{'misc-trial':{'state':'started'}},None),
                                      ('mu300',{'root-tf-write':{'state':'started'}},None),
                                      ('mu300',{'boot-and-misc-1234':{'state':'done'}},'stage-one.json'),
                                      ('e5',{'misc-trial-prepared':{'state':'done'}},'stage-one.json')]:
            with self.subTest(kind=kind,effects=effects):
                record={**self.record,'package':{**PACKAGE,'adapter':kind},'effects':effects,'legacy':legacy}
                self.assertFalse(installation_committed(record))

    def test_transaction_revisions_increase_across_restart(self):
        original = self.record.get('revision', 0)
        store = Store(self.temp.name)
        record = store.load(self.record['id'])
        Context(store, record, lambda *_:None).stage('android_boot', 'waiting_device')
        self.assertGreater(store.load(record['id'])['revision'], original)

    def test_expected_ssh_reboot_disconnect_is_waiting_then_verified(self):
        self.record.update(stage='openwrt_boot', status='waiting_device')
        self.store.save(self.record)
        self.restart_and_verify(disconnect=True)
        import json
        events=[json.loads(line) for line in self.service.output.getvalue().splitlines()]
        self.assertNotIn('failed',[e['data'].get('status') for e in events])

    def test_final_wait_distinguishes_manual_restart_from_requested_reboot(self):
        for kind, method, manual in [('e5','reinstall',True), ('e5','part',True),
                                     ('e5','tf',True), ('e5','image',True), ('e5','boot',False),
                                     ('e5','update',False), ('mu300','boot',True),
                                     ('mu300','reinstall',True), ('mu300','update',False)]:
            with self.subTest(adapter=kind, method=method):
                self.record.update(package={**PACKAGE,'adapter':kind},
                                   choices={'method':method,'host':'192.0.2.1'})
                context=Context(self.store,self.record,self.service.emit)
                self.service.openwrt_wait_stage(context)
                self.assertEqual(self.record['stage'],'openwrt_boot')
                self.assertEqual(self.record['status'],'waiting_user' if manual else 'waiting_device')
                self.assertEqual(self.record['details']['host'],'192.0.2.1')
                self.assertEqual(self.record['details']['reboot_manually'],manual)
                # Reconnection failure and an application restart must retain
                # the same instruction, without replaying an installation.
                context=Context(self.store,self.store.load(self.record['id']),self.service.emit)
                self.service.openwrt_wait_stage(context)
                self.assertEqual(context.record['details']['reboot_manually'],manual)

    def test_finished_worker_does_not_accept_pause(self):
        self.service.active = Context(self.store, self.record, self.service.emit)
        self.service.worker = SimpleNamespace(is_alive=lambda:False)
        result = self.service.dispatch({'protocol':1,'command':'cancel','params':{}})
        self.assertFalse(result['accepted'])
        self.assertFalse(self.record['cancel_requested'])


if __name__ == '__main__':
    unittest.main()
