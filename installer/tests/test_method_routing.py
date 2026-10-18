"""Exercise real probe/routing code with read-only simulated ADB, never hardware."""
import io
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from backend.adapter import Adapter, args_for
from backend.service import Service
from backend.state import Context, RecoveryRequired, Store

TOP=Path(__file__).resolve().parents[2]
SERIAL='fixture-selected'
CID='b'*32


class ReadOnlyAdb:
    exe='test-adb'
    su='su'
    card=False
    commands=[]

    def devices(self):return [{'serial':SERIAL,'state':'device'}]
    def properties(self):return {'ro.product.model':'E5','ro.product.device':'fixture','ro.board.platform':'fixture','ro.boot.slot_suffix':'_a','ro.boot.verifiedbootstate':'orange','ro.crypto.state':'unencrypted','ro.crypto.type':'','sys.boot_completed':'1'}
    def root_status(self):return 'ready'
    def read(self,script):
        self.commands.append(script)
        if script in ('dd if=/dev/block/by-name/boot_b bs=512 count=8 2>/dev/null',
                      'dd if=/dev/block/by-name/boot_a bs=512 count=8 2>/dev/null'):
            return bytes(4096)
        raise AssertionError('Unexpected binary read: '+script)
    def shell(self,script,root=False):
        self.commands.append(script)
        if script=='cat /proc/sys/kernel/random/boot_id':return 'boot-fixture'
        if script=='settings get secure user_setup_complete':return '1'
        if script.startswith('set -e; d='):
            return f'NODE=mmcblk1p16\nCID={CID}\nSTART=2048\nSIZE=33554432\nDISK_SIZE=134217728\nFREE=12582912\nSOURCE=/dev/block/mmcblk1p16\nROOT=mmcblk1p20\n'+('TF=/dev/block/mmcblk0p1\n' if self.card else '')
        if script=='cat /sys/class/block/mmcblk1p20/start /sys/class/block/mmcblk1p20/size':return '33556480 8388608'
        if script=='test -b /dev/block/mmcblk0p1; echo $?':return '0'
        if script=='cat /sys/class/block/mmcblk0p1/size':return '16777216'
        if script=='cat /sys/class/block/mmcblk0/device/cid':return 'c'*32
        if script=='cat /sys/class/block/mmcblk0p1/start 2>/dev/null || echo 0':return '2048'
        raise AssertionError('Unexpected simulated ADB command: '+script)


class MethodRouting(unittest.TestCase):
    def adapter(self,kind='e5',card=False):
        a=Adapter.__new__(Adapter);a.kind=kind;a.root=Path('.');a.ctx=None;a.password=''
        a.package={'adapter':kind,'path':'.','profile':'e5' if kind=='e5' else 'mu300-family'}
        a.adb=ReadOnlyAdb();a.adb.card=card;a.adb.commands=[]
        a.bind=Mock()
        a.legacy=SimpleNamespace(package_profile=Mock(return_value={'profile':'e5','android_models':['E5']}),android_profile=Mock(return_value='f50'),device_sd=Mock(side_effect=AssertionError('Internal mode touched TF discovery')),device_size=Mock(side_effect=AssertionError('Internal mode read TF capacity')))
        a.read_gpt=Mock(return_value={'empty':[1],'safe_gaps':[]})
        return a

    def test_internal_modes_do_not_require_or_validate_a_card(self):
        for kind in ('e5','mu300'):
            for card in (False,True):
                for method in ('part','reinstall','image','boot'):
                    with self.subTest(kind=kind,card=card,method=method):
                        a=self.adapter(kind,card)
                        device=a.probe(SERIAL,method)
                        self.assertTrue(device['root']);self.assertTrue(device['existing'])
                        self.assertEqual(device['storage']['ROOT'],'mmcblk1p20')
                        a.legacy.device_sd.assert_not_called();a.legacy.device_size.assert_not_called()
                        self.assertNotIn('tf_bytes',device)
                        if method=='boot':a.read_gpt.assert_not_called()

    def test_reinstall_plan_on_device_without_card(self):
        for kind in ('e5','mu300'):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as directory:
                a=self.adapter(kind)
                service=Service('.',Store(directory),io.StringIO());service.package=a.package
                service.adapters=lambda *_args:a
                result=service.dispatch({'protocol':1,'command':'plan','params':{'serial':SERIAL,'choices':{'method':'reinstall','size_gib':4,'grow':True}}})
                self.assertEqual(result['choices']['method'],'reinstall')
                self.assertEqual(result['plan']['method'],'reinstall')
                self.assertEqual(result['plan']['target'],'mmcblk1p20')
                self.assertEqual(result['plan']['openwrt_bytes'],4<<30)
                self.assertFalse(result['plan']['wipe'])
                self.assertFalse(result['plan']['two_stage'])
                a.legacy.device_sd.assert_not_called()

    def test_real_legacy_tf_error_only_applies_to_tf(self):
        source=TOP/'openwrt/bundle/flash.py'
        if not source.is_file():self.skipTest('E5 legacy source is tested in the E5 repository')
        spec=importlib.util.spec_from_file_location('routing_legacy_fixture',source)
        legacy=importlib.util.module_from_spec(spec);spec.loader.exec_module(legacy)
        for cards in ('','mmcblk0 mmcblk2'):
            with self.subTest(cards=cards):
                a=self.adapter();a.legacy=legacy;legacy.GUI=a
                with patch.object(legacy,'package_profile',return_value={'profile':'e5','android_models':['E5']}), patch.object(legacy,'su',side_effect=lambda script:'mmcblk1' if 'PARTNAME=userdata' in script else cards):
                    self.assertTrue(a.probe(SERIAL,'reinstall')['existing'])
                    with self.assertRaisesRegex(ValueError,'expected one SD card'):
                        a.probe(SERIAL,'tf')

    def test_tf_retains_first_partition_priority(self):
        a=self.adapter(card=True)
        a.legacy.device_sd=Mock(return_value='/dev/block/mmcblk0')
        a.legacy.device_size=Mock(return_value=8<<30)
        result=a.probe(SERIAL,'tf')
        self.assertEqual(result['tf'],'/dev/block/mmcblk0p1')
        self.assertEqual(result['tf_bytes'],8<<30)
        a.legacy.device_size.assert_called_once_with('/dev/block/mmcblk0p1')

    def test_execute_routes_and_flags_are_exclusive(self):
        for kind in ('e5','mu300'):
            for method in ('tf','part','reinstall','image','boot','update'):
                with self.subTest(kind=kind,method=method), tempfile.TemporaryDirectory() as directory:
                    root=Path(directory);(root/'desktop').mkdir();(root/'desktop/manifest.json').write_text('{}')
                    record=Store(root/'app').create({'path':directory,'adapter':kind},{'serial':SERIAL},{'method':method},{'method':method,'openwrt_bytes':4<<30})
                    a=self.adapter(kind);a.root=root;a.ctx=Context(Store(root/'app'),record,lambda *_:None)
                    a.probe=Mock();a.backup=Mock();a.stage=Mock();a.update_e5=Mock();a.boot_mu300=Mock()
                    a.legacy=SimpleNamespace(**{n:Mock() for n in ('install_sd','install','part_two_stage','boot_openwrt','install_part','update')})
                    flags=args_for(record,root)
                    self.assertEqual(sum(bool(getattr(flags,n)) for n in ('tf','part','reinstall_part','data','boot_openwrt')),0 if method=='update' else 1)
                    with patch('backend.adapter.update_mu300') as shared_update:
                        a.execute()
                    if method=='update':
                        if kind=='e5':a.update_e5.assert_called_once();shared_update.assert_not_called()
                        else:
                            shared_update.assert_called_once()
                            self.assertIs(shared_update.call_args.args[0],vars(a.legacy))
                            a.legacy.update.assert_not_called()
                    elif kind=='mu300' and method=='boot':
                        a.boot_mu300.assert_called_once();a.legacy.install.assert_not_called()
                    elif kind=='mu300':a.legacy.install.assert_called_once()
                    else:
                        target={'tf':'install_sd','part':'install_part','reinstall':'part_two_stage','image':'install','boot':'boot_openwrt'}[method]
                        getattr(a.legacy,target).assert_called_once()
                        if method=='reinstall':self.assertEqual(a.legacy.part_two_stage.call_args.args[0],'reinstall')
                        for name in ('install_sd','install','part_two_stage','boot_openwrt','install_part'):
                            if name!=target:getattr(a.legacy,name).assert_not_called()

    def test_mismatched_saved_mode_stops_before_probe_or_write(self):
        a=self.adapter();a.ctx=SimpleNamespace(record={'choices':{'method':'tf'},'plan':{'method':'reinstall'}})
        with self.assertRaises(RecoveryRequired):a.execute()
        a.bind.assert_not_called()


if __name__=='__main__':unittest.main()
