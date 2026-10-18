"""Byte progress/checksum/retry tests using in-memory Android staging files."""
import hashlib
from pathlib import Path
import shlex
import sys
import tempfile
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from backend.state import Cancelled, Context, Store
from backend.transport import push_chunks


class Transfer(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.source=Path(self.temp.name)/'payload.bin'
        self.source.write_bytes(bytes(range(256))*32768+b'last chunk')
        store=Store(Path(self.temp.name)/'app')
        self.record=store.create({}, {}, {}, {})
        self.events=[]
        self.ctx=Context(store,self.record,lambda kind,data:self.events.append((kind,data)))
        self.files={};self.pushes=0;self.corrupt=False;self.disconnect_at=None
        self.remote="/data/local/tmp/fixture payload's.bin"

    def tearDown(self):self.temp.cleanup()

    def call(self,command,local,remote):
        self.assertEqual(command,'push')
        self.pushes+=1
        self.files[remote]=Path(local).read_bytes()
        if self.corrupt:self.files[remote]=b'corrupted'
        if self.pushes==self.disconnect_at:raise ConnectionError('USB disconnected')

    def shell(self,command):
        parts=shlex.split(command)
        if parts[:2]==['rm','-f']:
            self.files.pop(parts[2],None);return ''
        if parts[0]=='sha256sum':
            return hashlib.sha256(self.files[parts[1]]).hexdigest()+'  file'
        if parts[0]=='cat' and parts[2]=='>>':
            self.files[parts[3]]=self.files.get(parts[3],b'')+self.files.pop(parts[1]);return ''
        self.fail('Unexpected simulated staging command: '+command)

    def transfer(self):return push_chunks(self.call,self.shell,self.source,self.remote,self.ctx)

    def test_progress_counts_only_verified_appended_bytes(self):
        self.transfer()
        self.assertEqual(self.files[self.remote],self.source.read_bytes())
        events=[data for kind,data in self.events if kind=='transfer']
        self.assertEqual([data['bytes'] for data in events],[8<<20,self.source.stat().st_size])
        self.assertTrue(all(data['total']==self.source.stat().st_size and data['bytes_per_second']>0 for data in events))

    def test_corrupt_chunk_stops_before_append_or_progress(self):
        self.corrupt=True
        with self.assertRaisesRegex(ValueError,'checksum'):self.transfer()
        self.assertNotIn(self.remote,self.files)
        self.assertFalse(self.events)

    def test_disconnect_retry_replaces_partial_upload(self):
        self.disconnect_at=2
        with self.assertRaises(ConnectionError):self.transfer()
        self.assertEqual(len(self.files[self.remote]),8<<20)
        self.disconnect_at=None
        self.transfer()
        self.assertEqual(self.files[self.remote],self.source.read_bytes())

    def test_pause_stops_between_verified_chunks(self):
        def emit(kind,data):
            self.events.append((kind,data));self.ctx.cancel=True
        self.ctx.emit=emit
        with self.assertRaises(Cancelled):self.transfer()
        self.assertEqual(self.pushes,1)
        self.assertEqual(len(self.files[self.remote]),8<<20)


if __name__=='__main__':unittest.main()
