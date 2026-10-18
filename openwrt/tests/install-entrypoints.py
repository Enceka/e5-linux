#!/usr/bin/env python3
"""Run packaged launchers and menu choices without ADB or disk operations."""
import importlib.util
import io
import json
import os
from pathlib import Path
import runpy
import shutil
import subprocess
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

TOP = Path(__file__).resolve().parents[2]
api = runpy.run_path(str(TOP / 'openwrt/bundle/install-entrypoints.py'))
spec = importlib.util.spec_from_file_location('flasher', TOP / 'openwrt/bundle/flash.py')
flash = importlib.util.module_from_spec(spec); spec.loader.exec_module(flash)


class Entrypoints(unittest.TestCase):
    def test_userdata_image_menu_explicitly_warns_about_f2fs(self):
        a=SimpleNamespace()
        with patch.object(flash,'ask',return_value='7'), patch.object(sys,'stdout',io.StringIO()) as output:
            self.assertTrue(flash.choose_install_action(a))
        self.assertTrue(a.data)
        self.assertIn('EXPERIMENTAL',output.getvalue())
        self.assertIn('Android F2FS',output.getvalue())

    def test_full_partition_is_default_but_explicit_no_remains_available(self):
        for answer,expected in [('',1),('yes',1),('y',1),('no',0),('n',0)]:
            with self.subTest(answer=answer), patch('builtins.input',return_value=answer):
                self.assertEqual(flash.part_growth(SimpleNamespace(grow_fs=None,y=False)),expected)
        for value,unattended,expected in [(None,True,1),(True,False,1),(False,False,0),(False,True,0)]:
            with patch('builtins.input',side_effect=AssertionError('unnecessary prompt')):
                self.assertEqual(flash.part_growth(SimpleNamespace(grow_fs=value,y=unattended)),expected)

    def source(self, path):
        path.mkdir()
        for name in ('flash.py', 'flash.cmd', 'flash.sh', 'part-two-stage.py', 'userdata-image.sh', 'android-loop.sh',
                     'README.md', 'README.zh-CN.md', 'START-HERE.md'):
            shutil.copy2(TOP / 'openwrt/bundle' / name, path / name)

    def test_menu_selects_exact_action_and_cancel_does_not_install(self):
        for choice, field in [('1','tf'),('2','part'),('3','reinstall_part'),('4','resume_part'),
                              ('5','boot_openwrt'),('6','update'),('7','data'),('0',None)]:
            a=SimpleNamespace(tf=False,part=False,reinstall_part=False,resume_part=None,
                              boot_openwrt=False,update=False,data=False)
            with patch.object(flash,'ask',side_effect=[choice,'"a path/transaction.json"']):
                result=flash.choose_install_action(a)
            self.assertEqual(result, field is not None)
            self.assertEqual([k for k,v in vars(a).items() if v], [field] if field else [])
            if field=='resume_part':self.assertEqual(a.resume_part,'a path/transaction.json')

    def test_names_and_real_launcher_argument_forwarding(self):
        with tempfile.TemporaryDirectory(prefix='installer entries ') as folder:
            root=Path(folder); source=root/'source'; self.source(source)
            package=root/'package with spaces'; api['assemble'](package,source)
            self.assertFalse((package/'flash.py').exists())
            self.assertFalse((package/'install-part.cmd').exists())
            self.assertTrue((package/'scripts/installer/part-two-stage.py').exists())
            self.assertTrue((package/'files/userdata-image.sh').exists())
            self.assertTrue((package/'files/android-loop.sh').exists())
            self.assertTrue((package/'docs/README.zh-CN.md').exists())
            self.assertEqual({p.name for p in package.iterdir() if p.is_file()},
                             {'OpenWrt-Installer.py','START-HERE.md'})
            self.assertTrue(all(p.name.isascii() for p in package.rglob('*')))
            output=root/'args.json'
            (package/'OpenWrt-Installer.py').write_text(
                'import sys,json\nfrom pathlib import Path\n'
                f'Path({str(output)!r}).write_text(json.dumps(sys.argv[1:]))\n'
                'raise SystemExit(7)\n')
            extension='cmd' if os.name=='nt' else 'sh'
            for name,flag in api['ACTIONS'].items():
                args=['C:/saved files/transaction.json','-y'] if name=='resume-internal-install' else ['--ssid','a hotspot']
                entry=package/'launchers'/(name+'.'+extension)
                command=['cmd','/d','/c','.\\'+entry.name,*args] if os.name=='nt' else ['sh',str(entry),*args]
                result=subprocess.run(command,input='\n',text=True,capture_output=True,timeout=20,cwd=entry.parent)
                self.assertEqual(result.returncode,7,(name,result.stderr,result.stdout))
                self.assertEqual(json.loads(output.read_text()),(['--no-pause'] if os.name=='nt' else [])+[flag,*args])

    def test_global_flags_do_not_skip_the_menu_and_erase_tf_by_default(self):
        for flags in ([], ['--no-pause'], ['--pause']):
            with patch.object(sys,'argv',['OpenWrt-Installer.py',*flags]), \
                 patch.object(flash,'choose_install_action',return_value=False) as menu, \
                 patch.object(flash,'install_sd') as install:
                self.assertFalse(flash.main())
                menu.assert_called_once()
                install.assert_not_called()

    def test_exit_status_and_pause_after_success_failure_and_cancel(self):
        import io
        for result,error,expected in ((True,None,0),(None,SystemExit(7),7),(False,None,0)):
            with patch.object(sys,'argv',['OpenWrt-Installer.py','--pause']), \
                 patch.object(flash,'main',return_value=result,side_effect=error), \
                 patch.object(sys,'stdout',io.StringIO()) as output, \
                 patch('builtins.input',return_value='') as pause:
                self.assertEqual(flash.run_cli(),expected)
                pause.assert_called_once()
                self.assertIn('FAILED' if error else 'SUCCESS' if result else 'CANCELLED',output.getvalue())

    def test_stale_windows_binary_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder); source=root/'source'; self.source(source)
            (source/'flash.exe').write_bytes(b'old binary')
            (source/'flash-exe.json').write_text(json.dumps({'source_sha256':'0'*64,'binary_sha256':'0'*64}))
            with self.assertRaisesRegex(ValueError,'stale'):
                api['assemble'](root/'package',source)


if __name__=='__main__':unittest.main()
