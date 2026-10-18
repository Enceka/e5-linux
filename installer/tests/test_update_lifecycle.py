"""An update is complete only after a new boot, not a pre-reboot SSH response."""
import hashlib
import io
import json
from pathlib import Path
import struct
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from backend.adapter import Adapter,installation_committed
from backend.service import Service,plan_install
from backend.state import Context,Store
from test_state import PACKAGE,DEVICE

OLD='11111111-1111-4111-8111-111111111111'
NEW='22222222-2222-4222-8222-222222222222'


class UpdateLifecycle(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.store=Store(self.temp.name)
        self.output=io.StringIO()
        self.service=Service('.',self.store,self.output)
        device={**DEVICE,'capacity':4<<30}
        self.record=self.store.create(PACKAGE,device,{'method':'update','host':'192.0.2.1'},
                                     plan_install(PACKAGE,device,{'method':'update','host':'192.0.2.1'}))
        self.ctx=Context(self.store,self.record,self.service.emit)

    def tearDown(self):self.temp.cleanup()

    def test_capture_actual_boot_identity_before_update_uploads(self):
        adapter=Adapter.__new__(Adapter);adapter.ctx=self.ctx
        adapter.expected_ssh_key=hashlib.sha256(b'key').hexdigest()
        client=Mock()
        client.get_transport.return_value.get_remote_server_key.return_value.asbytes.return_value=b'key'
        client.exec_command.return_value=(None,SimpleNamespace(read=lambda:OLD.encode(),channel=SimpleNamespace(recv_exit_status=lambda:0)),None)
        adapter.validate_ssh(client)
        self.assertEqual(self.store.load(self.record['id'])['update_boot_id'],OLD)
        self.assertEqual(self.record['stage'],'transfer_install')
        self.assertFalse(self.record['effects'])
        client.exec_command.return_value=(None,SimpleNamespace(read=lambda:b'',channel=SimpleNamespace(recv_exit_status=lambda:0)),None)
        with self.assertRaisesRegex(ValueError,'boot identity'):adapter.validate_ssh(client)

    def test_committed_update_announces_reboot_and_is_not_replayed(self):
        adapter=Adapter.__new__(Adapter);adapter.ctx=self.ctx
        operation=Mock(return_value='verified')
        self.assertEqual(adapter.action('update-commit',operation),'verified')
        self.assertEqual(self.record['stage'],'openwrt_boot')
        self.assertEqual(self.record['status'],'waiting_device')
        self.assertFalse(self.record['details']['reboot_manually'])
        self.assertTrue(installation_committed(self.record))
        self.assertEqual(adapter.action('update-commit',operation),'verified')
        operation.assert_called_once()

    def run_final_check(self,boot_ids,confirmed=False,missing=False,connection_errors=(),read_disconnect=False):
        self.record.update(stage='prepare',effects={'update-commit':{'state':'done'}})
        if not missing:self.record['update_boot_id']=OLD
        if confirmed:self.record['openwrt_confirmed']=True
        self.store.save(self.record)
        # A new app process reloads the committed transaction, preserving the
        # pre-update boot proof even if the final wait checkpoint was not saved.
        record=Store(self.temp.name).load(self.record['id'])
        context=Context(self.store,record,self.service.emit)
        values=iter(boot_ids);observed=[];root_reads=[];read_losses=[]
        raw=bytearray(1024);raw[56:58]=b'\x53\xef'
        struct.pack_into('<I',raw,24,2);struct.pack_into('<I',raw,4,(4<<30)//4096)
        def read(command,timeout=15):
            if command=='cat /sys/class/block/mmcblk0/device/cid':value=DEVICE['cid']
            elif command=='cat /proc/sys/kernel/random/boot_id':
                if read_disconnect and not read_losses:
                    read_losses.append(True)
                    if read_disconnect == 'exit-status':
                        return None,SimpleNamespace(read=lambda:b'',channel=SimpleNamespace(recv_exit_status=lambda:-1)),None
                    raise EOFError('SSH closed during reboot')
                value=next(values);observed.append(value)
            elif command.startswith('readlink -f') or command=='cat /run/mu300/disk-dev':
                root_reads.append(observed[-1]);value='/dev/mmcblk0p20'
            elif command.startswith('dd if='):value=bytes(raw)
            elif command.startswith('test -s /etc/openwrt_release'):value=''
            else:raise AssertionError(command)
            return None,SimpleNamespace(read=lambda:value if isinstance(value,bytes) else value.encode(),channel=SimpleNamespace(recv_exit_status=lambda:0)),None
        client=Mock();client.exec_command.side_effect=read
        if connection_errors:client.connect.side_effect=[*connection_errors,None]
        adapter=SimpleNamespace(password='',probe=Mock(side_effect=AssertionError('Unexpected Android probe')),
                                execute=Mock(side_effect=AssertionError('Update replayed')))
        with patch('paramiko.SSHClient',return_value=client),patch.object(self.service.stop,'wait',return_value=False):
            self.service.run(context,adapter)
        adapter.execute.assert_not_called();adapter.probe.assert_not_called()
        return record,observed,root_reads

    def test_old_runtime_responding_before_reboot_cannot_complete_update(self):
        record,observed,reads=self.run_final_check([OLD,OLD,NEW])
        self.assertEqual(observed,[OLD,OLD,NEW]);self.assertEqual(reads,[NEW])
        self.assertEqual(record['status'],'completed')
        events=[json.loads(line) for line in self.output.getvalue().splitlines()]
        states=[e['data']['stage'] for e in events if e['type']=='transaction']
        self.assertGreaterEqual(states.count('openwrt_boot'),3)
        self.assertEqual(states[-2:],['verify_capacity','complete'])

    def test_manual_boot_confirmation_still_requires_actual_new_boot(self):
        record,observed,reads=self.run_final_check([OLD,NEW],confirmed=True)
        self.assertEqual(observed,[OLD,NEW]);self.assertEqual(reads,[NEW])
        self.assertEqual(record['status'],'completed')

    def test_update_disconnects_are_normal_waits_until_reconnected(self):
        import paramiko
        for kind in ('e5','mu300'):
            with self.subTest(adapter=kind):
                self.record['package']={**PACKAGE,'adapter':kind}
                self.output.seek(0);self.output.truncate(0)
                errors=[ConnectionRefusedError('restarting'),TimeoutError('restarting'),
                        OSError('USB network absent'),EOFError('restarting'),paramiko.SSHException('banner interrupted')]
                record,observed,reads=self.run_final_check([NEW],connection_errors=errors)
                self.assertEqual(record['status'],'completed')
                self.assertEqual(observed,[NEW]);self.assertEqual(reads,[NEW])
                events=[json.loads(line) for line in self.output.getvalue().splitlines()]
                reconnects=[e['data'] for e in events if e['type']=='transaction' and e['data'].get('details',{}).get('connection_state')=='reconnecting']
                self.assertEqual(len(reconnects),len(errors))
                self.assertTrue(all(r['status']=='waiting_device' and not r['details'].get('verification_error') and not r.get('error') for r in reconnects))
                self.assertEqual(sum(e['type']=='log' and e['data'].get('scope')=='reconnect' for e in events),len(errors))

    def test_disconnect_during_remote_read_is_normal_wait(self):
        record,_,reads=self.run_final_check([NEW],read_disconnect=True)
        self.assertEqual(record['status'],'completed');self.assertEqual(reads,[NEW])
        events=[json.loads(line) for line in self.output.getvalue().splitlines()]
        reconnects=[e['data'] for e in events if e['type']=='transaction' and e['data'].get('details',{}).get('connection_state')=='reconnecting']
        self.assertEqual(len(reconnects),1)
        self.assertEqual(reconnects[0]['status'],'waiting_device')
        self.assertIsNone(reconnects[0]['details']['verification_error'])

    def test_ssh_close_without_exit_status_is_also_a_reconnection_wait(self):
        record,_,reads=self.run_final_check([NEW],read_disconnect='exit-status')
        self.assertEqual(record['status'],'completed');self.assertEqual(reads,[NEW])
        events=[json.loads(line) for line in self.output.getvalue().splitlines()]
        self.assertTrue(any(e['type']=='transaction' and e['data'].get('details',{}).get('connection_state')=='reconnecting'
                            and not e['data']['details']['verification_error'] for e in events))

    def test_missing_or_invalid_boot_proof_stops_before_capacity_reads(self):
        for missing in (False,True):
            with self.subTest(missing=missing):
                self.record.pop('update_boot_id',None)
                record,_,reads=self.run_final_check(['invalid'],missing=missing)
                self.assertEqual(record['status'],'failed')
                self.assertFalse(reads)
                self.assertIn('boot',record['error']['message'])

    def test_phase_clock_persists_freezes_and_restarts_on_retry(self):
        with patch('backend.state.time.time',return_value=100):self.ctx.stage('backup')
        with patch('backend.state.time.time',return_value=105):self.ctx.stage('backup','waiting_device')
        self.assertEqual(self.record['stage_started_at'],100)
        with patch('backend.state.time.time',return_value=108):self.ctx.stage('backup','failed')
        saved=self.store.load(self.record['id'])
        self.assertEqual(saved['stage_finished_at']-saved['stage_started_at'],8)
        with patch('backend.state.time.time',return_value=200):self.ctx.stage('backup')
        self.assertEqual(self.record['stage_started_at'],200)
        self.assertNotIn('stage_finished_at',self.record)
        with patch('backend.state.time.time',return_value=207):self.ctx.stage('complete','completed')
        self.assertEqual(self.record['stage_finished_at']-self.record['stage_started_at'],7)


if __name__=='__main__':unittest.main()
