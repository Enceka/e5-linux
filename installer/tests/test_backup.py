"""Device dd -> adb pull backup tests; transport and device files are simulated."""
import hashlib
from pathlib import Path
import re
import shlex
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from backend.state import Context,Store,Cancelled
from backend.transport import Adb


class Pull:
    def __init__(self,args,data,corrupt=False):
        self.args=args;self.path=Path(args[-1]);self.data=data;self.steps=0
        self.returncode=None;self.killed=False;self.corrupt=corrupt
    def communicate(self,timeout=None):
        if self.killed:return b'',b'cancelled'
        self.steps+=1
        if self.steps==1:
            self.path.write_bytes(self.data[:len(self.data)//2])
            raise subprocess.TimeoutExpired(self.args,timeout)
        if self.steps==2:self.path.write_bytes((b'X'+self.data[1:]) if self.corrupt else self.data)
        self.returncode=0
        return b'1 file pulled',b''
    def poll(self):return self.returncode
    def kill(self):self.killed=True;self.returncode=-1


class Backup(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.store=Store(self.temp.name)
        self.record=self.store.create({}, {}, {}, {})
        self.events=[];self.ctx=Context(self.store,self.record,lambda k,d:self.events.append((k,d)))
        with patch('backend.transport.shutil.which',return_value='adb'):self.adb=Adb('.', 'selected')
        self.adb.su='su';self.adb.context=self.ctx
        self.data=bytes(range(256))*8192+b'last sector'
        self.target=Path(self.temp.name)/'boot_a.bin'
        self.remote={};self.commands=[];self.process=None;self.corrupt=False

    def tearDown(self):self.temp.cleanup()

    def shell(self,script,**_):
        self.commands.append(script)
        if script.startswith('blockdev'):return str(len(self.data))
        if script.startswith('df '):return str(1024*1024)
        if script.startswith('umask 077; mkdir '):return ''
        if script.startswith('set -e; umask 077; dd '):
            match=re.search(r'of=(\S+)',script)
            self.remote[match[1]]=self.data;return ''
        if script.startswith('sha256sum '):return hashlib.sha256(self.remote[shlex.split(script)[1]]).hexdigest()+'  file'
        if script.startswith('(set -o pipefail; cat '):return hashlib.sha256(self.data).hexdigest()+'  -'
        if script.startswith('rm -f '):self.remote.pop(shlex.split(script)[2],None);return ''
        if script.startswith('rmdir '):return ''
        self.fail('Unexpected backup command: '+script)

    def popen(self,args,**_):
        self.assertEqual(args[:4],['adb','-s','selected','pull'])
        self.assertTrue(args[4].startswith('/data/local/tmp/openwrt-backup-'))
        self.process=Pull(args,self.remote[args[4]],self.corrupt)
        return self.process

    def run_backup(self):
        with patch.object(self.adb,'shell',side_effect=self.shell),patch('backend.transport.subprocess.Popen',side_effect=self.popen):
            try:self.adb.backup_partition('boot_a',self.target,self.ctx)
            finally:self.adb.cleanup_backup(self.ctx)

    def test_stages_in_private_android_directory_and_pulls_with_true_progress(self):
        self.run_backup()
        self.assertEqual(self.target.read_bytes(),self.data)
        events=[d for k,d in self.events if k=='transfer']
        self.assertEqual([d['bytes'] for d in events],[len(self.data)//2,len(self.data)])
        self.assertTrue(all(d['total']==len(self.data) for d in events))
        self.assertFalse(self.remote)
        self.assertTrue(any('chmod 644 ' in command for command in self.commands))
        self.assertFalse(any('base64' in command or 'gzip' in command for command in self.commands))
        self.assertNotIn('backup_staging',self.record)

    def test_bad_download_preserves_existing_backup_and_cleans_staging(self):
        self.target.write_bytes(b'existing verified backup');self.corrupt=True
        with self.assertRaisesRegex(ValueError,'Computer backup checksum'):self.run_backup()
        self.assertEqual(self.target.read_bytes(),b'existing verified backup')
        self.assertFalse(Path(str(self.target)+'.partial').exists())
        self.assertFalse(self.remote)

    def test_cancel_kills_only_readonly_pull_and_cleans_partial_files(self):
        def emit(kind,data):
            if kind=='transfer':self.ctx.cancel=True
        self.ctx.emit=emit
        with self.assertRaises(Cancelled):self.run_backup()
        self.assertTrue(self.process.killed)
        self.assertFalse(self.target.exists())
        self.assertFalse(self.remote)

    def test_low_staging_space_stops_before_dd(self):
        def shell(script,**kwargs):
            if script.startswith('df '):return '1'
            return self.shell(script,**kwargs)
        with patch.object(self.adb,'shell',side_effect=shell):
            with self.assertRaisesRegex(ValueError,'staging space'):self.adb.backup_partition('boot_a',self.target,self.ctx)
        self.assertFalse(any('dd if=' in command for command in self.commands))

    # Metadata byte/serial integrity is covered by test_binary_io using the
    # actual staging/pull helper, including corrupt and interrupted downloads.


if __name__=='__main__':unittest.main()
