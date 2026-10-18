"""Real host subprocesses, synthetic converters; no ADB or device writes."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import importlib.util
import shutil
import tarfile
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from backend.helpers import execute_script,run_helper
from backend.state import Context,Store,Cancelled


class Helpers(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.script=self.root/'scripts/tools/vbc-profile/vbc-profile.py'
        self.script.parent.mkdir(parents=True)
        self.store=Store(self.root/'app');self.record=self.store.create({}, {}, {}, {})
        self.events=[];self.ctx=Context(self.store,self.record,lambda k,d:self.events.append((k,d)))

    def tearDown(self):self.temp.cleanup()

    def test_converter_runs_captures_both_streams_and_has_named_phase(self):
        self.script.write_text('import sys\nprint("conversion stdout")\nprint("conversion stderr",file=sys.stderr)\n')
        run_helper(self.ctx,self.root,self.script,[])
        text=(self.ctx.directory/'debug.ndjson').read_text()
        self.assertIn('conversion stdout',text);self.assertIn('conversion stderr',text)
        self.assertEqual(self.record['stage'],'firmware_convert')
        self.assertEqual(self.record['details']['tool'],'vbc-profile.py')
        self.assertTrue(any(kind=='activity' for kind,data in self.events))

    def test_converter_failure_contains_its_actual_traceback(self):
        self.script.write_text('raise RuntimeError("converter-specific failure")\n')
        with self.assertRaisesRegex(ValueError,'converter-specific failure'):
            run_helper(self.ctx,self.root,self.script,[])
        self.assertIn('Traceback',(self.ctx.directory/'debug.ndjson').read_text(encoding='utf-8'))

    def test_converter_timeout_is_bounded(self):
        self.script.write_text('import time\ntime.sleep(30)\n')
        with self.assertRaisesRegex(TimeoutError,'vbc-profile.py'):
            run_helper(self.ctx,self.root,self.script,[],timeout=.3)

    def test_pause_terminates_only_host_converter(self):
        self.script.write_text('import time\ntime.sleep(30)\n')
        processes=[];original=subprocess.Popen
        def capture(*args,**kwargs):
            process=original(*args,**kwargs);processes.append(process);return process
        def emit(kind,data):
            if kind=='activity':self.ctx.cancel=True
        self.ctx.emit=emit
        with patch('backend.helpers.subprocess.Popen',side_effect=capture):
            with self.assertRaises(Cancelled):run_helper(self.ctx,self.root,self.script,[])
        self.assertEqual(len(processes),1);self.assertIsNotNone(processes[0].poll())
        self.assertFalse(self.record['effects'])

    def test_arbitrary_host_script_is_refused_before_launch(self):
        outside=self.root/'anything.py';outside.write_text('raise RuntimeError("must never execute")')
        with self.assertRaisesRegex(ValueError,'Unsupported'):run_helper(self.ctx,self.root,outside,[])
        self.assertEqual(self.record['stage'],'plan')

    def test_tool_docstrings_and_asserts_survive_optimized_host(self):
        self.script.write_text('"""converter description"""\nimport argparse\na=argparse.ArgumentParser(description=__doc__.splitlines()[0]);print(a.description)\n')
        code='import sys;sys.path.insert(0,sys.argv[1]);from backend.helpers import execute_script;execute_script(sys.argv[2],[])'
        result=subprocess.run([sys.executable,'-OO','-c',code,str(Path(__file__).resolve().parents[1]),str(self.script)],capture_output=True,timeout=10)
        self.assertEqual(result.returncode,0,result.stderr.decode('utf-8','replace'))
        self.assertIn(b'converter description',result.stdout)
        self.script.write_text('assert False, "helper guard retained"\n')
        result=subprocess.run([sys.executable,'-OO','-c',code,str(Path(__file__).resolve().parents[1]),str(self.script)],capture_output=True,timeout=10)
        self.assertNotEqual(result.returncode,0);self.assertIn(b'helper guard retained',result.stderr)

    def test_script_execution_restores_interpreter_state_after_failure(self):
        argv=sys.argv;main=sys.modules['__main__'];paths=sys.path[:]
        self.script.write_text('raise RuntimeError("test")\n')
        with self.assertRaises(RuntimeError):execute_script(self.script,['argument'])
        self.assertIs(sys.argv,argv);self.assertIs(sys.modules['__main__'],main);self.assertEqual(sys.path,paths)

    def test_actual_firmware_extraction_runs_both_converters_before_device_pack(self):
        repo=Path(__file__).resolve().parents[2]
        source=repo/'openwrt/bundle/flash.py'
        if not source.is_file():self.skipTest('Real E5 extraction is exercised in the E5 repository')
        spec=importlib.util.spec_from_file_location('helper_extraction_fixture',source)
        legacy=importlib.util.module_from_spec(spec);spec.loader.exec_module(legacy)
        shutil.copy2(repo/'tools/vbc-profile/vbc-profile.py',self.script)
        shutil.copy2(repo/'tools/sprd-bt-config.py',self.root/'scripts/tools/sprd-bt-config.py')
        names={'wcnmodem.bin':b'wcn','bt_configure_pskey.xpe.ini':b'#[0.0]__/L=176\nvalue=0\n',
               'bt_configure_rf.xpe.ini':b'#[0.0]__/L=252\nvalue=0\n','btmac.txt':b'02:00:00:00:00:01',
               'l_agdsp_a.img':b'SharkL5_AUD'+bytes(6291456-11)}
        for name in ('dsp_vbc','audio_structure','cvs'):
            names[name+'.xml']=(f'<{name} num_mode="1" struct_size="4"><item mode="0"><x id="0" t="u32" val="123"/></item></{name}>').encode()
        legacy.SCRIPTS=str(self.root/'scripts');legacy.F=str(self.root/'files')
        legacy.GUI=SimpleNamespace(stage=self.ctx.stage,run_tool=lambda script,*args:run_helper(self.ctx,self.root,script,args))
        def shell(command):
            if command.startswith('ls /odm/firmware'):return ''
            if command=='ls /data/local/tmp/e5pull':return '\n'.join(names)
            if 'e5-collect.sh' in command:return 'E5-COLLECT-OK 123'
            return ''
        pushes=[]
        def adb(command,source,target,**kwargs):
            if command=='pull':Path(target).write_bytes(names[Path(source).name])
            elif command=='push':pushes.append((source,target))
            else:self.fail('Unexpected fixture transport')
        legacy.su=shell;legacy.adb=adb
        work=self.root/'work';work.mkdir()
        with patch('sys.stdout',__import__('io').StringIO()):self.assertEqual(legacy.pull_device_files(str(work)),'123')
        with tarfile.open(work/'firmware.tar') as archive:
            for name in ('audio_structure','dsp_vbc','cvs'):
                self.assertEqual(len(archive.extractfile('lib/firmware/'+name).read()),28)
            self.assertEqual(len(archive.extractfile('lib/firmware/sprd/marlin3lite_pskey.bin').read()),176)
            self.assertEqual(len(archive.extractfile('lib/firmware/sprd/marlin3lite_rf.bin').read()),252)
        self.assertTrue(any(target.endswith('e5-firmware.tar') for source,target in pushes))
        self.assertFalse(self.record['effects'])


if __name__=='__main__':unittest.main()
