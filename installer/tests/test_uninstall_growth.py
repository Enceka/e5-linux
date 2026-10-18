"""Preservation choice, explicit reset consent and real filesystem file fixtures."""
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import test_uninstall as fixtures
from backend.service import Service
from backend.state import Context, RecoveryRequired, Cancelled
from backend.uninstall import prepare, persist, Uninstaller
from backend.uninstall_growth import eligible, growth_tools, PreservationUnavailable, GROWTH


class Preservation(unittest.TestCase):
    def setUp(self):
        self.fx=fixtures.Journal();self.fx.setUp()
    def tearDown(self):self.fx.tearDown()
    def fresh(self,kind='ext4'):
        fx=self.fx
        fx.device.update(encrypted=False,encryption_state='unencrypted',encryption_type='')
        fx.adb.shell=Mock(side_effect=['/dev/block/mmcblk0p4',str(28*fixtures.GIB//512)])
        fx.adb.read=Mock(return_value=fixtures.superblock(28*fixtures.GIB,kind))
    def plan(self,kind='ext4'):
        self.fresh(kind);fx=self.fx
        with patch('backend.uninstall.growth_tools',return_value={'openwrt-uninstall/tools/fixture':b'tool'}),patch('backend.uninstall.base_boot'),patch('backend.uninstall.build'):
            plan,meta,files=prepare(fx.adapter,fx.store,fx.device)
        r=fx.store.create(fx.package,fx.device,{'method':'uninstall'},plan)
        ctx=Context(fx.store,r,lambda *_:None);persist(ctx,meta,files)
        return ctx

    def test_confirmed_direct_unencrypted_ext4_and_f2fs_preserve_without_asking_reset(self):
        for kind in ('ext4','f2fs'):
            ctx=self.plan(kind)
            self.assertFalse(ctx.record['plan']['wipe'])
            self.assertEqual(ctx.record['plan']['data_action'],'grow-'+kind)
            self.assertEqual(ctx.record['uninstall']['version'],2)
            Uninstaller(None,ctx,self.fx.adapter)
            self.assertFalse(any('of=' in call.args[0] for call in self.fx.adb.shell.call_args_list))

    def test_unknown_encryption_encrypted_mapping_and_missing_tools_need_explicit_consent(self):
        fx=self.fx
        for failure in ('encrypted','unknown','mapped','tools'):
            self.fresh()
            if failure=='encrypted':fx.device.update(encrypted=True,encryption_state='encrypted',encryption_type='file')
            if failure=='unknown':fx.device.pop('encryption_state')
            if failure=='mapped':fx.adb.shell=Mock(side_effect=['/dev/block/dm-0',str(28*fixtures.GIB//512)])
            with patch('backend.uninstall.growth_tools',side_effect=ValueError('tool incompatible')):
                with self.assertRaises(PreservationUnavailable) as caught:prepare(fx.adapter,fx.store,fx.device)
            self.assertTrue(caught.exception.fingerprint)
            self.assertEqual(len(fx.store.list()),1)
            self.assertFalse(any('of=' in call.args[0] for call in fx.adb.shell.call_args_list))

    def test_format_consent_is_bound_to_fresh_device_evidence_not_a_sticky_boolean(self):
        fx=self.fx;self.fresh();fx.device.update(encrypted=True,encryption_state='encrypted')
        service=Service('.',fx.store,io.StringIO());service.package=fx.package
        fx.adapter.probe=Mock(side_effect=lambda *_:fx.device)
        original_read=fx.adb.read
        fx.adb.read=Mock(side_effect=lambda cmd: bytes(4096) if 'by-name/boot_' in cmd else original_read(cmd))
        fx.adb.shell=Mock(side_effect=lambda cmd,**_: '/dev/block/mmcblk0p4' if cmd.startswith('readlink') else str(28*fixtures.GIB//512))
        service.adapters=lambda *_:fx.adapter
        def request(token=None,**choices):
            return service.dispatch({'protocol':1,'command':'plan','params':{'serial':'selected','reset_token':token,'choices':{'method':'uninstall',**choices}}})
        first=request(reset_android=True)
        self.assertEqual(first['confirmation_required'],'format_android')
        self.assertEqual(len(fx.store.list()),1)
        second=request('invalid')
        self.assertEqual(second['confirmation_required'],'format_android')
        # A different encryption observation invalidates the previous prompt.
        fx.device['encryption_type']='file'
        third=request(second['reset_token'])
        self.assertEqual(third['confirmation_required'],'format_android')
        result=request(third['reset_token'])
        self.assertTrue(result['plan']['wipe']);self.assertEqual(result['status'],'ready')
        self.assertEqual(result['plan']['data_action'],'reset');self.assertEqual(len(fx.store.list()),2)
        self.assertIsNone(service.uninstall_reset_prompt)
        self.assertFalse(any('of=' in call.args[0] for call in fx.adb.shell.call_args_list))

    def test_preserving_plan_rechecks_encryption_before_backup_or_boot_write(self):
        ctx=self.plan();self.fx.device.update(encryption_state='encrypted',encrypted=True)
        self.fx.adb.shell=Mock(side_effect=['/dev/block/mmcblk0p4',str(28*fixtures.GIB//512)])
        self.fx.adapter.backup=Mock()
        with self.assertRaises(ValueError):Uninstaller(None,ctx,self.fx.adapter).arm(self.fx.device)
        self.fx.adapter.backup.assert_not_called()
        self.assertFalse(ctx.record['effects'])

    def test_import_cannot_change_reset_plan_to_preserving_or_preserve_wrong_filesystem(self):
        ctx=self.plan();ctx.record['plan']['wipe']=True
        with self.assertRaises(RecoveryRequired):Uninstaller(None,ctx,self.fx.adapter)
        ctx.record['plan']['wipe']=False;ctx.record['uninstall']['action']='grow-f2fs'
        ctx.record['plan']['data_action']='grow-f2fs'
        with self.assertRaises(RecoveryRequired):Uninstaller(None,ctx,self.fx.adapter)

    def test_final_shortfall_persists_retry_without_format_or_boot_cleanup(self):
        ctx=self.plan();device={**self.fx.device,'existing':False,'userdata_bytes':32*fixtures.GIB}
        self.fx.adb.shell=Mock(side_effect=['/dev/block/mmcblk0p4',str(32*fixtures.GIB//512)])
        self.fx.adb.read=Mock(return_value=fixtures.superblock(28*fixtures.GIB))
        with self.assertRaisesRegex(RecoveryRequired,'never formats'),patch.object(Uninstaller,'finish_boot',side_effect=AssertionError('cleanup before capacity')):
            Uninstaller(None,ctx,self.fx.adapter).finish(device)
        self.assertTrue(ctx.record['uninstall_growth_pending']);self.assertNotEqual(ctx.record['status'],'completed')
        self.assertEqual(ctx.record['android_capacity_check']['filesystem_bytes'],28*fixtures.GIB)
        self.assertNotIn('uuid',ctx.record['android_capacity_check'])

    def test_old_unconfirmed_reset_plan_must_be_replanned_but_armed_records_keep_their_contract(self):
        ctx=self.fx.plan();r=ctx.record;r['uninstall']['version']=1
        self.fx.store.save(r)
        service=Service('.',self.fx.store,io.StringIO())
        with self.assertRaisesRegex(ValueError,'Regenerate'):
            service.dispatch({'protocol':1,'command':'start','params':{'transaction':r['id'],'confirmed':True}})
        r['effects']['uninstall-arm']={'state':'done'};r['status']='waiting_device';self.fx.store.save(r)
        Uninstaller(None,Context(self.fx.store,self.fx.store.load(r['id']),lambda *_:None),self.fx.adapter)

    def test_missing_libraries_and_old_f2fs_tools_are_rejected_before_offline_boot(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);folder=root/'desktop/files/boot/repair';folder.mkdir(parents=True)
            binary=bytearray(32);binary[:6]=b'\x7fELF\x02\x01';struct.pack_into('<H',binary,18,183)
            binary=bytes(binary)+b'1.14.0\0'
            def manifest(names):
                hashes={}
                for name in names:
                    p=folder/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(binary)
                    hashes[name]=hashlib.sha256(binary).hexdigest()
                (folder/'manifest.json').write_text(json.dumps({'sha256':hashes}))
            names=['sbin/fsck.f2fs','sbin/resize.f2fs','lib/ld-musl-aarch64.so.1']
            manifest(names)
            with self.assertRaisesRegex(ValueError,'libraries'):growth_tools(SimpleNamespace(root=root,kind='mu300'),'f2fs')
            manifest(names+['lib/libf2fs.so.10','lib/libuuid.so.1','lib/libgcc_s.so.1'])
            with self.assertRaisesRegex(ValueError,'compatibility'):growth_tools(SimpleNamespace(root=root,kind='mu300'),'f2fs')

    def test_explicit_growth_retry_only_rearms_misc_and_never_rewrites_gpt_or_formats(self):
        ctx=self.plan();r=ctx.record;fx=self.fx
        r.update(uninstall_android_sha256='a'*64,uninstall_boot_sha256='b'*64,uninstall_growth_pending=True,status='failed')
        fx.adb.shell=Mock(side_effect=['/dev/block/mmcblk0p4',str(32*fixtures.GIB//512),'a'*64+'  boot_a\n'+'b'*64+'  boot_b\n','',''])
        fx.adb.read=Mock(side_effect=[fixtures.superblock(28*fixtures.GIB),fixtures.android_bc()]);fx.adb.call=Mock()
        worker=Uninstaller(None,ctx,fx.adapter)
        with patch.object(worker,'layout_state',return_value='after'),patch('backend.uninstall.push_chunks'):
            worker.rearm_growth({**fx.device,'userdata_bytes':32*fixtures.GIB,'boot_id':'current'})
        command=fx.adb.shell.call_args_list[-1].args[0]
        self.assertIn('of=/dev/block/by-name/misc',command)
        for forbidden in ('wipe_data','mkfs','of=/dev/block/mmcblk','of=/dev/block/by-name/boot'):
            self.assertNotIn(forbidden,command)
        self.assertIsNone(fx.adb.shell.call_args.kwargs['timeout'])
        self.assertEqual(r['effects']['uninstall-grow-rearm']['state'],'done')
        self.assertEqual(r['uninstall_wait_boot_id'],'current')

    def test_cancel_after_verified_rearm_resumes_without_another_misc_write(self):
        ctx=self.plan();r=ctx.record;fx=self.fx
        r.update(uninstall_android_sha256='a'*64,uninstall_boot_sha256='b'*64,uninstall_growth_pending=True,status='failed')
        current_device={**fx.device,'userdata_bytes':32*fixtures.GIB,'boot_id':'current'}
        def setup(bc,cancel=False):
            def shell(command,**_):
                if command.startswith('readlink'):return '/dev/block/mmcblk0p4'
                if command.startswith('cat '):return str(32*fixtures.GIB//512)
                if command.startswith('sha256sum'):return 'a'*64+'  boot_a\n'+'b'*64+'  boot_b\n'
                if command.startswith('set -eu;') and cancel:ctx.cancel=True
                return ''
            fx.adb.shell=Mock(side_effect=shell);fx.adb.read=Mock(side_effect=[fixtures.superblock(28*fixtures.GIB),bc]);fx.adb.call=Mock()
        worker=Uninstaller(None,ctx,fx.adapter);setup(fixtures.android_bc(),cancel=True)
        with patch.object(worker,'layout_state',return_value='after'),patch('backend.uninstall.push_chunks'),self.assertRaises(Cancelled):
            worker.rearm_growth(current_device)
        self.assertEqual(r['effects']['uninstall-grow-rearm']['state'],'done')
        self.assertFalse(r['unsafe']);fx.adb.call.assert_not_called()
        ctx.cancel=False;setup(bytes.fromhex(r['uninstall_growth_trial']))
        with patch.object(worker,'layout_state',return_value='after'),patch('backend.uninstall.push_chunks',side_effect=AssertionError('staging repeated')):
            worker.rearm_growth(current_device)
        self.assertFalse(any('of=' in call.args[0] for call in fx.adb.shell.call_args_list))
        fx.adb.call.assert_called_once_with('reboot')


@unittest.skipUnless(os.name!='nt' and all(shutil.which(name) for name in ('busybox','mkfs.f2fs','fsck.f2fs','resize.f2fs','mkfs.ext4','e2fsck','resize2fs')),'requires native Linux filesystem tools')
class NativeGrowth(unittest.TestCase):
    def run_kind(self,kind):
        qemu=os.environ.get('UNINSTALL_QEMU');bundle=os.environ.get('UNINSTALL_F2FS_ROOT' if kind=='f2fs' else 'UNINSTALL_EXT4_ROOT')
        if kind=='f2fs' and not (qemu and bundle):
            version=subprocess.run(['resize.f2fs','-V'],capture_output=True,text=True).stdout
            import re
            match=re.search(r'1\.(\d+)\.',version)
            if not match or int(match[1])<16:self.skipTest('Native F2FS <1.16 is not accepted; set UNINSTALL_QEMU and UNINSTALL_F2FS_ROOT for the packaged tools')
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);image=root/'userdata.img'
            old=512<<20;target=768<<20
            with image.open('wb') as f:f.truncate(target if kind=='f2fs' else old)
            def run(*cmd):
                if qemu and bundle and cmd[0] in ('resize.f2fs','fsck.f2fs','resize2fs','e2fsck'):
                    executable=Path(bundle)/('sbin' if kind=='f2fs' else 'usr/sbin')/cmd[0]
                    cmd=(qemu,str(Path(bundle)/'lib/ld-musl-aarch64.so.1'),'--library-path',str(Path(bundle)/'lib')+':'+str(Path(bundle)/'usr/lib'),str(executable),*cmd[1:])
                result=subprocess.run(cmd,cwd=root,capture_output=True,text=True,timeout=60)
                self.assertEqual(result.returncode,0,result.stdout+result.stderr);return result
            run('mkfs.'+kind,'-f' if kind=='f2fs' else '-F',str(image))
            marker=(b'ANDROID USER FILE MUST SURVIVE '+b'42'*25)*1024
            if kind=='ext4':
                (root/'user.txt').write_bytes(marker)
                run('debugfs','-w','-R','write '+str(root/'user.txt')+' /user.txt',str(image))
            else:
                (root/'files').mkdir();(root/'files/user.txt').write_bytes(marker)
                run('sload.f2fs','-f',str(root/'files'),str(image))
            if kind=='f2fs':
                run('resize.f2fs','-s','-t',str(old//512),str(image))
                with image.open('r+b') as f:f.truncate(old)
            with image.open('rb') as f:f.seek(1024);sb=f.read(1024)
            at=104 if kind=='ext4' else 108;identity=sb[at:at+16].hex()
            if kind=='ext4':before=struct.unpack_from('<I',sb,4)[0]*(1024<<struct.unpack_from('<I',sb,24)[0])
            else:before=struct.unpack_from('<Q',sb,36)[0]*4096
            with image.open('r+b') as f:f.truncate(target)
            # Only kernel size queries and the ARM64 loader are replaced. Real
            # fsck/resize tools execute the production growth functions on this
            # regular test file, with no block device access or mounts.
            shell=GROWTH.replace('/run/uninstall-fsck.stdin',str(root/'fsck.stdin'))
            if qemu and bundle:
                shell+='\nfs_tool() { tool=$1; shift; '+qemu+' '+bundle+'/lib/ld-musl-aarch64.so.1 --library-path '+bundle+'/lib:'+bundle+'/usr/lib '+bundle+('/sbin/' if kind=='f2fs' else '/usr/sbin/')+'"${tool##*/}" "$@"; }\n'
            else:
                shell+='\nfs_tool() { tool=$1; shift; "${tool##*/}" "$@"; }\n'
            shell+='blockdev() { wc -c < "$2"; }\n'
            shell+=f'action=grow-{kind}; fs_uuid={identity}; fs_before={before}; data_start=2048; data_size={target//512}; grow_device={image}\n'
            shell+='fs_grow\nfs_grow\n' # Completed retries must not resize again.
            run('busybox','ash','-ec',shell)
            with image.open('rb') as f:f.seek(1024);sb=f.read(1024)
            self.assertEqual(sb[at:at+16].hex(),identity)
            size=struct.unpack_from('<Q',sb,36)[0]*4096 if kind=='f2fs' else struct.unpack_from('<I',sb,4)[0]*(1024<<struct.unpack_from('<I',sb,24)[0])
            self.assertGreaterEqual(size,target-(4<<20));self.assertLessEqual(size,target)
            if kind=='ext4':
                recovered=run('debugfs','-R','cat /user.txt',str(image)).stdout.encode()
                self.assertEqual(recovered,marker)
            else:
                # Read through the inode and its block pointers, not a raw scan
                # which could find stale data after incorrect metadata moves.
                result=subprocess.run(['dump.f2fs','-i','4',str(image)],cwd=root,input='y\n',capture_output=True,text=True,timeout=30)
                self.assertEqual(result.returncode,0,result.stdout+result.stderr)
                self.assertEqual((root/'lost_found/user.txt').read_bytes(),marker)
    def test_ext4_real_file_and_actual_capacity_survive_growth_and_retry(self):self.run_kind('ext4')
    def test_f2fs_real_file_and_actual_capacity_survive_growth_and_retry(self):self.run_kind('f2fs')


if __name__=='__main__':unittest.main()
