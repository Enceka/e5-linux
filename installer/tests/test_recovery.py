"""Exercise the coordinator with real journals and simulated transport/files."""
import io
import json
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from backend.service import Service, plan_install, verify_ext4_capacity
from backend.state import Context, Pending, Store
from backend.adapter import Adapter, args_for
from test_state import DEVICE, PACKAGE


class Recovery(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.store=Store(self.temp.name)
        self.output=io.StringIO()
        self.service=Service('.',self.store,self.output)
        self.record=self.store.create(PACKAGE,{**DEVICE,'boot_id':'old'}, {'method':'part','size_gib':4}, plan_install(PACKAGE,DEVICE,{'method':'part','size_gib':4}))
        self.ctx=Context(self.store,self.record,self.service.emit)
        self.prepare_calls=0;self.write_calls=0

    def tearDown(self):self.temp.cleanup()

    def fake_adapter(self):
        owner=self
        context=self.ctx
        class Adapter:
            password=''
            reads=0
            def probe(self,*_):
                self.reads+=1
                if owner.record.get('legacy'):
                    stages=['android_boot','android_setup','debug_authorization','root_permission','ready']
                    ready=stages[min(self.reads-2,len(stages)-1)]
                    return {**DEVICE,'boot_id':'new','readiness':ready}
                return {**DEVICE,'boot_id':'old'}
            def execute(self):
                if not owner.record.get('legacy'):
                    owner.prepare_calls+=1
                    path=context.directory/'legacy.json'
                    path.write_text(json.dumps({'token':'trusted','phase':'awaiting-android'}))
                    context.legacy_record(path,{'phase':'awaiting-android'})
                    context.stage('android_boot','waiting_device')
                    raise Pending()
                def install():
                    owner.write_calls+=1
                    # Disposable file stands in for the grown ext4 superblock.
                    raw=bytearray(1024);raw[56:58]=b'\x53\xef'
                    struct.pack_into('<I',raw,24,2);struct.pack_into('<I',raw,4,(4<<30)//4096)
                    (context.directory/'root.superblock').write_bytes(raw)
                context.effect('root-write',install)
                return SimpleNamespace(state='success')
        return Adapter()

    def final_verify(self,ctx,adapter):
        raw=(ctx.directory/'root.superblock').read_bytes()
        measured=verify_ext4_capacity(raw,ctx.record['plan']['openwrt_bytes'])
        ctx.record['result']={'filesystem_bytes':measured}
        ctx.stage('complete','completed')

    def test_expected_reboot_authorization_then_automatic_resume(self):
        with patch.object(self.service.stop,'wait',return_value=False),patch.object(self.service,'wait_openwrt',side_effect=self.final_verify):
            self.service.run(self.ctx,self.fake_adapter())
        self.assertEqual(self.prepare_calls,1)
        self.assertEqual(self.write_calls,1)
        self.assertEqual(self.store.load(self.record['id'])['status'],'completed')
        events=[json.loads(line) for line in self.output.getvalue().splitlines()]
        self.assertIn('waiting_user',[e['data'].get('status') for e in events if e['type']=='transaction'])

    def test_app_restart_in_reset_wait_does_not_prepare_again(self):
        adapter=self.fake_adapter()
        with self.assertRaises(Pending):adapter.execute()
        self.ctx.stage('android_setup','waiting_user')
        self.record=Store(self.temp.name).load(self.record['id'])
        self.ctx=Context(self.store,self.record,self.service.emit)
        with patch.object(self.service.stop,'wait',return_value=False),patch.object(self.service,'wait_openwrt',side_effect=self.final_verify):
            self.service.run(self.ctx,self.fake_adapter())
        self.assertEqual(self.prepare_calls,1)
        self.assertEqual(self.write_calls,1)
        self.assertEqual(self.record['status'],'completed')

    def test_export_import_keeps_relative_legacy_and_backups(self):
        adapter=self.fake_adapter()
        with self.assertRaises(Pending):adapter.execute()
        self.record['data_directory']=str(self.ctx.directory)
        self.store.save(self.record)
        exported=Path(self.temp.name)/'export.zip'
        self.service.dispatch({'protocol':1,'command':'export','params':{'transaction':self.record['id'],'path':str(exported)}})
        import zipfile
        with tempfile.TemporaryDirectory() as other:
            source=Path(other)/'import'
            with zipfile.ZipFile(exported) as z:z.extractall(source)
            target=Service('.',Store(Path(other)/'app'),io.StringIO())
            value=target.dispatch({'protocol':1,'command':'import','params':{'path':str(source)}})
            restored=target.store.load(value['id'])
            self.assertTrue(Path(restored['legacy']).is_file())

    def test_stale_pre_reboot_adb_does_not_advance(self):
        states=iter(['old','old','new'])
        class Adapter:
            def probe(_, *_args):return {**DEVICE,'boot_id':next(states)}
        with patch.object(self.service.stop,'wait',return_value=False):
            self.service.wait_android(self.ctx,Adapter())
        self.assertEqual(self.record['stage'],'root_ready')

    def test_two_stage_boot_chain_checkpoints_are_distinct(self):
        source=self.ctx.directory/'package'
        source.mkdir(parents=True)
        (source/'OpenWrt-Installer.py').write_text('GUI=None\ndef adb(*args, **kwargs):pass\n')
        adapter=Adapter({**PACKAGE,'path':str(source)},self.ctx)
        legacy=self.ctx.directory/'legacy.json'
        self.record['legacy']=str(legacy)
        calls=[]
        legacy.write_text('{"phase":"prepared"}')
        adapter.action('bootchain-sync',lambda:calls.append('prepare'))
        adapter.action('bootchain-sync',lambda:calls.append('duplicate'))
        legacy.write_text('{"phase":"installed"}')
        adapter.action('bootchain-sync',lambda:calls.append('final'))
        self.assertEqual(calls,['prepare','final'])

    def test_backend_cannot_escalate_confirmed_gap_plan_to_android_reset(self):
        source=self.ctx.directory/'package';source.mkdir(parents=True)
        (source/'OpenWrt-Installer.py').write_text('GUI=None\ndef adb(*args, **kwargs):pass\n')
        adapter=Adapter({**PACKAGE,'path':str(source)},self.ctx)
        self.record['plan'].update(target='GPT unallocated space',wipe=False,gap_start=90000000)
        with self.assertRaisesRegex(ValueError,'confirmed plan'):
            adapter.validate_plan('userdata shrink',wipe=True,capacity=4<<30)
        adapter.validate_plan('GPT unallocated space',capacity=4<<30,gap_start=90000000)

    def test_adapter_uses_confirmed_aligned_allocation(self):
        self.record['choices']['size_gib']=4.1
        self.record['plan']['openwrt_bytes']=4200*1048576
        args=args_for(self.record,self.ctx.directory)
        self.assertEqual(float(args.size)*1024,4200)


if __name__=='__main__':unittest.main()
