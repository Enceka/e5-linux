"""Manual boot confirmation selects an SSH endpoint, never bypasses verification."""
import io
import json
from pathlib import Path
import struct
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from backend.service import Service,plan_install
from backend.state import Context,Store
from test_state import PACKAGE,DEVICE


class OpenwrtConfirmation(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.store=Store(self.temp.name)
        self.output=io.StringIO()
        self.service=Service('.',self.store,self.output)
        device={**DEVICE,'existing':True,'storage':{**DEVICE['storage'],'ROOT':'mmcblk0p20','ROOT_SIZE':(4<<30)//512}}
        self.record=self.store.create(PACKAGE,device,{'method':'reinstall','host':'192.0.2.1'},
                                     plan_install(PACKAGE,device,{'method':'reinstall'}))
        self.ctx=Context(self.store,self.record,self.service.emit)
        self.service.active=self.ctx
        self.service.worker=SimpleNamespace(is_alive=lambda:True)
        self.service.openwrt_wait_stage(self.ctx)

    def tearDown(self):self.temp.cleanup()

    def confirm(self,**extra):
        return self.service.dispatch({'protocol':1,'command':'verify_openwrt',
                'params':{'transaction':self.record['id'],'host':'192.0.2.2','password':'private-root-secret',**extra}})

    def test_confirmation_is_queued_and_does_not_complete_or_persist_password(self):
        self.assertTrue(self.confirm()['accepted'])
        self.assertEqual(self.record['status'],'waiting_user')
        self.assertFalse(self.record.get('openwrt_confirmed'))
        self.assertNotIn('private-root-secret',(self.ctx.directory/'transaction.json').read_text())
        self.assertEqual(self.record['choices']['host'],'192.0.2.1')

    def test_rejects_wrong_transaction_unsafe_stage_and_invalid_endpoint(self):
        for extra in ({'transaction':'b'*32},{'host':''},{'host':'127.0.0.1; reboot'},
                      {'host':'https://router/'},{'password':123}):
            with self.subTest(extra=extra),self.assertRaises(ValueError):self.confirm(**extra)
        for stage,unsafe in [('transfer_install',False),('verify_capacity',False),('openwrt_boot',True)]:
            self.record.update(stage=stage,unsafe=unsafe)
            with self.assertRaises(ValueError):self.confirm()

    def verify_after_retry(self,authentication=False,bad_capacity=False):
        import paramiko
        targets=[];reads=[];client=Mock()
        def connect(host,**options):
            targets.append((host,options['password']))
            if authentication and options['password']!='private-root-secret':
                raise paramiko.AuthenticationException('denied')
        client.connect.side_effect=connect
        raw=bytearray(1024);raw[56:58]=b'\x53\xef'
        struct.pack_into('<I',raw,24,2)
        expected=self.record['plan']['openwrt_bytes']
        struct.pack_into('<I',raw,4,(expected//2 if bad_capacity else expected)//4096)
        def read(command,timeout=15):
            reads.append((targets[-1][0],command))
            if command=='cat /sys/class/block/mmcblk0/device/cid':
                value=DEVICE['cid'] if targets[-1][0]=='192.0.2.2' else '0'*32
            elif command.startswith('readlink -f'):value='/dev/mmcblk0p20'
            elif command.startswith('dd if='):value=bytes(raw)
            elif command.startswith('test -s /etc/openwrt_release'):value=''
            else:raise AssertionError(command)
            return None,SimpleNamespace(read=lambda:value if isinstance(value,bytes) else value.encode(),
                     channel=SimpleNamespace(recv_exit_status=lambda:0)),None
        client.exec_command.side_effect=read
        def user_action(_seconds):
            if not self.service.verification_wake.is_set():self.confirm()
            return False
        adapter=SimpleNamespace(password='')
        with patch('paramiko.SSHClient',return_value=client),patch.object(self.service.stop,'wait',side_effect=user_action):
            if bad_capacity:
                with self.assertRaisesRegex(ValueError,'capacity'):self.service.wait_openwrt(self.ctx,adapter)
            else:self.service.wait_openwrt(self.ctx,adapter)
        self.assertEqual([host for host,_ in targets],['192.0.2.1','192.0.2.2'])
        self.assertTrue(all(host=='192.0.2.2' for host,cmd in reads if cmd.startswith('dd if=')))
        self.assertEqual(self.record['choices']['host'],'192.0.2.2')
        self.assertTrue(self.record['openwrt_confirmed'])
        self.assertNotIn('private-root-secret',self.output.getvalue())
        self.assertNotIn('private-root-secret',(self.ctx.directory/'transaction.json').read_text())
        return [json.loads(line) for line in self.output.getvalue().splitlines()]

    def test_multiple_openwrt_devices_allow_retargeting_without_accepting_wrong_identity(self):
        events=self.verify_after_retry()
        self.assertTrue(any('another device' in str(e['data'].get('details',{})) for e in events))
        self.assertEqual(self.record['status'],'completed')
        self.assertEqual(self.record['result']['url'],'http://192.0.2.2')
        # Confirmation and endpoint survive restart; credentials do not.
        ctx=Context(self.store,self.store.load(self.record['id']),lambda *_:None)
        self.service.openwrt_wait_stage(ctx)
        self.assertFalse(ctx.record['details']['reboot_manually'])
        self.assertEqual(ctx.record['details']['host'],'192.0.2.2')

    def test_authentication_failure_can_be_corrected_while_waiting(self):
        events=self.verify_after_retry(authentication=True)
        self.assertTrue(any('authentication failed' in str(e['data'].get('details',{})) for e in events))
        self.assertEqual(self.record['status'],'completed')

    def test_manual_confirmation_cannot_bypass_final_capacity_check(self):
        self.verify_after_retry(bad_capacity=True)
        self.assertNotEqual(self.record['status'],'completed')


if __name__=='__main__':unittest.main()
