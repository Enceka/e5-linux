import io
import json
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.state import Cancelled, Context, DeviceLock, Pending, RecoveryRequired, Store, compatible
from backend.service import Service, plan_install, verify_ext4_capacity
from backend.transport import Adb


PACKAGE = dict(protocol=1, adapter='e5', profile='e5', layout='e5root-ext4', kernel='v2', payloads={'boot':'a'*64}, path='.', name='test')
DEVICE = dict(serial='private-serial', cid='b'*32, profile='e5', model='E5', readiness='ready', slot='_a',
              root=True, encrypted=True, existing=False, userdata_bytes=32 << 30, free_bytes=20 << 30,
              storage={'ROOT':None, 'SIZE':32*2097152}, gpt={'safe_gaps':[], 'empty':[1]})


class StateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(self.temp.name)
        self.record = self.store.create(PACKAGE, DEVICE.copy(), {'method':'part', 'size_gib':4}, plan_install(PACKAGE, DEVICE, {'method':'part','size_gib':4}))
        self.events = []
        self.ctx = Context(self.store, self.record, lambda kind, data:self.events.append((kind, data)))

    def tearDown(self):
        self.temp.cleanup()

    def test_atomic_restart_and_moved_package(self):
        self.ctx.stage('android_setup', 'waiting_user')
        other = Store(self.temp.name).load(self.record['id'])
        self.assertEqual(other['status'], 'waiting_user')
        self.assertTrue(compatible(other['package'], {**PACKAGE, 'path':'D:/moved', 'name':'repair'}))

    def test_compatible_repair_excludes_gui_changes(self):
        self.assertTrue(compatible(PACKAGE, {**PACKAGE, 'gui':'fixed'}))
        for field in ('adapter','profile','layout','kernel','protocol'):
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, field):
                compatible(PACKAGE, {**PACKAGE, field:'different'})
        with self.assertRaisesRegex(ValueError, 'boot'):
            compatible(PACKAGE, {**PACKAGE, 'payloads':{'boot':'c'*64}})

    def test_completed_effects_are_not_replayed(self):
        calls = []
        self.ctx.effect('format', lambda:calls.append('once'))
        restarted = Context(self.store, self.store.load(self.record['id']), lambda *_:None)
        restarted.effect('format', lambda:calls.append('twice'))
        self.assertEqual(calls, ['once'])

    def test_uncertain_partition_write_stops(self):
        with self.assertRaises(ConnectionError):
            self.ctx.effect('gpt', lambda: (_ for _ in ()).throw(ConnectionError()))
        restarted = Context(self.store, self.store.load(self.record['id']), lambda *_:None)
        with self.assertRaises(RecoveryRequired):
            restarted.effect('gpt', lambda:self.fail('must never write'))

    def test_failed_safe_transfer_can_retry(self):
        with self.assertRaises(ConnectionError):
            self.ctx.effect('upload', lambda: (_ for _ in ()).throw(ConnectionError()), retry_safe=True)
        self.assertEqual(self.ctx.effect('upload', lambda:42, retry_safe=True), 42)

    def test_cancel_is_deferred_through_write(self):
        def write():
            self.assertTrue(self.record['unsafe'])
            self.ctx.cancel = True
            return 'verified'
        with self.assertRaises(Cancelled):
            self.ctx.effect('boot', write)
        self.assertEqual(self.store.load(self.record['id'])['effects']['boot']['state'], 'done')

    def test_cross_process_device_mutex(self):
        code = "import sys;sys.path.insert(0,sys.argv[1]);from backend.state import DeviceLock\nwith DeviceLock(sys.argv[2],'same-cid'): pass"
        with DeviceLock(self.temp.name, 'same-cid'):
            result = subprocess.run([sys.executable,'-c',code,str(Path(__file__).resolve().parents[1]),self.temp.name],capture_output=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn(b'Another installer', result.stderr)
        with DeviceLock(self.temp.name, 'same-cid'):
            pass

    def test_public_events_mask_identity(self):
        self.ctx.stage('backup')
        serialized = json.dumps(self.events)
        self.assertNotIn(DEVICE['serial'], serialized)
        self.assertNotIn(DEVICE['cid'], serialized)

    def test_gap_avoids_userdata_reset(self):
        device = {**DEVICE,'gpt':{'safe_gaps':[(90000000, 10*2097152)], 'empty':[1]}}
        plan = plan_install(PACKAGE, device, {'method':'part','size_gib':4})
        self.assertFalse(plan['wipe'])
        self.assertEqual(plan['android_bytes'], DEVICE['userdata_bytes'])
        self.assertEqual(plan['gap_start'], 90000000)

    def test_unencrypted_userdata_preserved(self):
        plan = plan_install(PACKAGE, {**DEVICE,'encrypted':False}, {'method':'part','size_gib':4})
        self.assertFalse(plan['wipe'])
        self.assertFalse(plan['two_stage'])

    def test_tf_no_capacity_ceiling(self):
        plan = plan_install(PACKAGE, {**DEVICE,'tf':'/dev/block/mmcblk1p1','tf_bytes':128 << 30}, {'method':'tf'})
        self.assertEqual(plan['openwrt_bytes'], 128 << 30)

    def test_real_capacity_validation(self):
        raw = bytearray(1024)
        raw[56:58] = b'\x53\xef'
        struct.pack_into('<I',raw,24,2)
        struct.pack_into('<I',raw,4,(10 << 30)//4096)
        self.assertEqual(verify_ext4_capacity(raw, 10 << 30), 10 << 30)
        struct.pack_into('<I',raw,4,(2 << 30)//4096)
        with self.assertRaisesRegex(ValueError,'capacity'):
            verify_ext4_capacity(raw, 10 << 30)

    def test_multiple_devices_need_selection(self):
        service = Service('.', self.store, io.StringIO())
        service.package = PACKAGE
        with self.assertRaisesRegex(ValueError, 'Select'):
            service.dispatch({'protocol':1,'command':'probe','params':{}})

    def test_device_refresh_without_verified_package(self):
        service = Service('.', self.store, io.StringIO())
        with patch('backend.service.Adb') as factory:
            factory.return_value.devices.side_effect = [[], [], [{'serial':'chosen','state':'unauthorized'}]]
            for expected in [[], [], [{'serial':'chosen','state':'unauthorized'}]]:
                self.assertEqual(service.dispatch({'protocol':1,'command':'devices','params':{}}), expected)
            self.assertIsNone(service.package)
            factory.return_value.shell.assert_not_called()
        with self.assertRaisesRegex(ValueError, 'Verify a package first'):
            service.dispatch({'protocol':1,'command':'probe','params':{'serial':'chosen'}})

    def test_adb_empty_list_is_not_failure(self):
        with patch('backend.transport.shutil.which',return_value='adb'):
            transport = Adb('.')
        with patch.object(transport, 'call', return_value='List of devices attached\n\n') as call:
            self.assertEqual(transport.devices(), [])
            call.assert_called_once_with('devices','-l')

    def test_adb_list_preserves_all_device_states(self):
        with patch('backend.transport.shutil.which',return_value='adb'):
            transport = Adb('.')
        listing = 'List of devices attached\nchosen device product:test model:E5 transport_id:1\nother unauthorized transport_id:2\nwaiting offline transport_id:3\n'
        with patch.object(transport, 'call', return_value=listing):
            values = transport.devices()
        self.assertEqual([(d['serial'], d['state']) for d in values], [('chosen','device'),('other','unauthorized'),('waiting','offline')])

    def test_expected_reboot_waits_without_failure_or_deadline(self):
        service = Service('.', self.store, io.StringIO())
        states = iter(['android_boot', 'debug_authorization', 'android_setup', 'magisk', 'root_permission', 'ready'])
        class Adapter:
            def probe(_, serial, method):
                return {**DEVICE, 'readiness':next(states)}
        with patch.object(service.stop, 'wait', return_value=False):
            service.wait_android(self.ctx, Adapter())
        stages = [event[1]['stage'] for event in self.events if event[0]=='transaction']
        self.assertEqual(stages, ['android_boot', 'debug_authorization', 'android_setup', 'magisk', 'root_permission', 'root_ready'])
        self.assertNotIn('failed',[event[1]['status'] for event in self.events if event[0]=='transaction'])

    def test_wrong_device_after_reset_is_rejected(self):
        service = Service('.', self.store, io.StringIO())
        class Adapter:
            def probe(_, *args): return {**DEVICE,'cid':'c'*32}
        with self.assertRaises(RecoveryRequired):
            service.wait_android(self.ctx, Adapter())

    def test_unknown_commands_cannot_execute_shell(self):
        service = Service('.', self.store, io.StringIO())
        with self.assertRaises(ValueError):
            service.dispatch({'protocol':1,'command':'exec','params':{'command':'format'}})

    def test_adb_serial_binding_on_all_operations(self):
        with patch('backend.transport.shutil.which',return_value='adb'):
            transport = Adb('.', 'chosen')
        result = type('Result', (), {'returncode':0,'stdout':b'ok'})()
        with patch('backend.transport.subprocess.run',return_value=result) as run:
            transport.call('shell','id')
            self.assertEqual(run.call_args.args[0][:3], ['adb','-s','chosen'])

    def test_authorized_su_is_used_without_installing_magisk(self):
        with patch('backend.transport.shutil.which',return_value='adb'):
            transport = Adb('.', 'chosen')
        with patch.object(transport,'shell',side_effect=['2000','0','uid=0(root)']):
            self.assertEqual(transport.root_status(),'ready')


if __name__ == '__main__':
    unittest.main()
