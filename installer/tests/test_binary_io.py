"""Binary staging, hash checks and legacy GUI delegation without real ADB."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from backend.binary_io import pull_binary
from backend.adapter import Adapter
from backend.state import Context, Store, sha
from backend.transport import Adb


class BinaryIO(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.local=self.root/'binary.bin'
        self.data=bytes(range(256))*4096+b'\x00\r\n\xfftail'
        self.corrupt=False;self.short=False;self.source_changed=False;self.free=1024*1024
        self.scripts=[];self.calls=[];self.failed=False

    def shell(self,script,**kwargs):
        self.scripts.append((script,kwargs))
        if script.startswith('df '):return str(self.free)
        if script.startswith('umask 077; mkdir '):return ''
        if script.startswith('set -e; set -o pipefail;'):
            if self.failed:raise ConnectionError('fixture staging failed')
            h=hashlib.sha256(self.data).hexdigest()
            return str(len(self.data))+'\r\n'+h+'  data.bin\r\n'+('0'*64 if self.source_changed else h)+'  -\r\n'
        if script.startswith('rm -f '):return ''
        self.fail(script)

    def pull(self,*args,**kwargs):
        self.calls.append(args)
        self.assertEqual(args[0],'pull')
        self.assertTrue(args[1].startswith('/data/local/tmp/openwrt-read-'))
        data=self.data[:-1] if self.short else b'X'+self.data[1:] if self.corrupt else self.data
        Path(args[2]).write_bytes(data)
        return b'1 file pulled'

    def test_raw_bytes_survive_crlf_and_all_byte_values(self):
        self.assertEqual(pull_binary(self.pull,self.shell,'cat /sys/firmware/fdt',self.local),len(self.data))
        self.assertEqual(self.local.read_bytes(),self.data)
        self.assertTrue(self.scripts[-1][0].startswith('rm -f '))
        self.assertTrue(self.scripts[1][1]['root'] is False)
        self.assertFalse(any('exec-out' in c for c in self.calls))

    def test_corrupt_short_or_changed_source_never_replace_verified_file(self):
        for flag in ('corrupt','short','source_changed','failed'):
            with self.subTest(flag=flag):
                self.local.write_bytes(b'previous verified data')
                setattr(self,flag,True)
                with self.assertRaises((ValueError,ConnectionError)):pull_binary(self.pull,self.shell,'dd if=fixture bs=4096 count=1',self.local)
                self.assertEqual(self.local.read_bytes(),b'previous verified data')
                self.assertFalse(self.local.with_name('binary.bin.partial').exists())
                self.assertTrue(self.scripts[-1][0].startswith('rm -f '))
                setattr(self,flag,False)

    def test_space_size_and_metadata_limits_stop_before_download(self):
        self.free=1
        with self.assertRaises(ValueError):pull_binary(self.pull,self.shell,'cat fixture',self.local)
        self.assertEqual(len(self.scripts),1)
        self.free=1024*1024
        with self.assertRaises(ValueError):pull_binary(self.pull,self.shell,'cat fixture',self.local,expected_size=len(self.data)+1)
        with self.assertRaises(ValueError):pull_binary(self.pull,self.shell,'cat fixture',self.local,limit=10)
        self.assertFalse(self.calls)

    def test_shared_read_uses_actual_serial_bound_pull(self):
        adb=Adb.__new__(Adb);adb.exe='fixture-adb';adb.serial='chosen';adb.su='su';adb.context=None
        def run(argv,**kwargs):
            self.assertEqual(argv[:4],['fixture-adb','-s','chosen','pull'])
            self.pull(*argv[3:])
            return subprocess.CompletedProcess(argv,0,b'1 file pulled',b'')
        with patch.object(adb,'shell',side_effect=self.shell),patch('backend.transport.subprocess.run',side_effect=run):
            self.assertEqual(adb.read('cat /sys/firmware/fdt'),self.data)


class LegacyGUI(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        (self.root/'OpenWrt-Installer.py').write_text('class Android:\n def call(self,*a,**k): raise AssertionError("legacy call")\n def read(self,*a): raise AssertionError("old binary transport")\n def backup(self,*a): raise AssertionError("duplicate device backup")\n')
        self.storage={'CID':'a'*32,'NODE':'mmcblk0p30','START':2048,'SIZE':40000000,'DISK_SIZE':60000000}
        device={'serial':'selected','cid':'a'*32,'slot':'_a','storage':self.storage}
        self.store=Store(self.root/'data');self.record=self.store.create({'path':str(self.root),'adapter':'mu300'},device,{}, {})
        self.record['completed']=['backup'];self.ctx=Context(self.store,self.record,lambda *_:None)
        self.adapter=Adapter(self.record['package'],self.ctx)
        self.adapter.adb=SimpleNamespace(serial='selected',read=Mock(return_value=b'raw fixture'))
        self.android=self.adapter.legacy.Android();self.android.serial='selected';self.android.slot='a'
        backup=self.ctx.directory/'backup';backup.mkdir()
        names=['misc.bin','gpt-first.bin','gpt-last.bin']+[f'{n}_{s}.bin' for n in ('boot','uboot','sml','teecfg','trustos','vbmeta') for s in ('a','b')]
        for name in names:(backup/name).write_bytes((name+'\n').encode()*20)
        (backup/'checksums.json').write_text(json.dumps({n:sha(backup/n) for n in names}))

    def test_old_package_read_and_backup_are_replaced_by_shared_backend(self):
        self.assertEqual(self.android.read('bounded read'),b'raw fixture')
        target=self.ctx.directory/'legacy-backups/fixture'
        self.android.backup(target,self.storage)
        self.assertEqual((target/'boot_a.img').read_bytes(),(self.ctx.directory/'backup/boot_a.bin').read_bytes())
        self.assertTrue((target/'SHA256SUMS').is_file())
        self.adapter.adb.read.assert_called_once_with('bounded read')

    def test_wrong_device_layout_or_corrupted_cache_stops(self):
        target=self.ctx.directory/'legacy-backups/fixture'
        with self.assertRaises(ValueError):self.android.backup(target,{**self.storage,'START':4096})
        self.assertFalse(target.exists())
        (self.ctx.directory/'backup/boot_a.bin').write_bytes(b'corrupt')
        with self.assertRaises(ValueError):self.android.backup(target,self.storage)
        self.assertFalse(target.exists())
        self.android.serial='other'
        with self.assertRaises(ValueError):self.android.read('bounded read')


if __name__=='__main__':unittest.main()
