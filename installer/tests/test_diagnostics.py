"""Detailed diagnostics must remain actionable, durable and safe to share."""
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from backend.adapter import debug_output
from backend.service import Service,plan_install
from backend.state import Context,Store
from test_state import PACKAGE,DEVICE


class Diagnostics(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.store=Store(self.temp.name)
        self.record=self.store.create(PACKAGE,DEVICE.copy(),{'method':'part','size_gib':4},
                                      plan_install(PACKAGE,DEVICE,{'method':'part','size_gib':4}))
        self.record['secrets']={'wifi_key':'private-wireless-secret'}
        self.events=[]
        self.ctx=Context(self.store,self.record,lambda kind,data:self.events.append((kind,data)))

    def tearDown(self):self.temp.cleanup()

    def test_split_cli_output_and_trace_details_are_redacted_and_persisted(self):
        self.ctx.private.append('private-root-password')
        with debug_output(self.ctx) as _:
            sys.stdout.write('partition backup started\npassword=private-')
            sys.stdout.write('root-password\n'+DEVICE['serial']+'\n')
            sys.stderr.write('E5_WIFI_KEY=private-wireless-secret\n')
        text=(self.ctx.directory/'debug.ndjson').read_text(encoding='utf-8')
        self.assertIn('partition backup started',text)
        for secret in (DEVICE['serial'],'private-root-password','private-wireless-secret'):
            self.assertNotIn(secret,text)
        self.assertTrue(all(data['level']=='debug' for kind,data in self.events))

    def test_actual_exception_is_visible_in_error_and_copyable_after_restart(self):
        service=Service('.',self.store,io.StringIO())
        def fail(*_):raise subprocess.TimeoutExpired(['adb','-s',DEVICE['serial'],'private-root-password'],120)
        adapter=SimpleNamespace(password='private-root-password',probe=fail)
        service.run(self.ctx,adapter)
        self.assertIn('TimeoutExpired',self.record['error']['message'])
        reopened=Service('.',Store(self.temp.name),io.StringIO())
        reopened.worker=SimpleNamespace(is_alive=lambda:True)
        result=reopened.dispatch({'protocol':1,'command':'diagnostics','params':{'transaction':self.record['id']}})['text']
        self.assertIn('Traceback',result)
        self.assertIn('120',result)
        for secret in (DEVICE['serial'],DEVICE['cid'],'private-root-password','private-wireless-secret'):
            self.assertNotIn(secret,result)

    def test_log_rotation_and_copy_size_are_bounded(self):
        path=self.ctx.directory/'debug.ndjson';path.write_text('x'*(4*1024*1024+1))
        self.ctx.log('latest failure detail',level='error')
        self.assertTrue((self.ctx.directory/'debug.previous.ndjson').is_file())
        service=Service('.',self.store,io.StringIO())
        copied=service.dispatch({'protocol':1,'command':'diagnostics','params':{'transaction':self.record['id']}})['text']
        self.assertIn('latest failure detail',copied)
        self.assertLess(len(copied),1100000)

    def test_resumed_legacy_secret_does_not_leak(self):
        legacy=self.ctx.directory/'legacy.json';legacy.write_text(json.dumps({'key':'old-legacy-secret'}))
        self.record['legacy']=str(legacy)
        resumed=Context(self.store,self.record,lambda *_:None)
        resumed.log('old-legacy-secret')
        self.assertNotIn('old-legacy-secret',(self.ctx.directory/'debug.ndjson').read_text())


if __name__=='__main__':unittest.main()
