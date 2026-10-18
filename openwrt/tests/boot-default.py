#!/usr/bin/env python3
"""Run real boot helpers against files in a disposable directory, never misc."""
from pathlib import Path
import json,os,subprocess,tempfile,unittest

TOP=Path(__file__).resolve().parents[2]
MU=Path(os.environ.get('MU300_REPO',str(TOP.parent/'mu300-linux-clean-tf-7.2')))

class BootDefault(unittest.TestCase):
    def run_case(self,repo,model,op='linux',bad_block=False,fail_write=False,fail_save=False):
        original=repo/('device/linux_device_common/overlay/opt/e5/e5-next-boot' if model=='e5' else 'rootfs/overlay/opt/mu300/bin/mu300-next-boot')
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);conf=root/'etc';runtime=root/'run';runtime.mkdir();conf.mkdir()
            (conf/'default-boot').write_text('android\n')
            misc=root/'misc';misc.write_bytes(b'A'*4096)
            for name in ['misc-bc-slot-a.bin','misc-bc-slot-b-trial.bin','misc-bc-android.bin','misc-bc-linux-trial.bin']:
                (runtime/name).write_bytes(b'B'*(31 if bad_block else 32))
            (runtime/'misc-dev').write_text(str(misc)+'\n');(runtime/'linux-slot').write_text('b\n')
            cmdline=root/'cmdline';cmdline.write_text('test\n')
            script=original.read_text().replace('/etc/e5linux',str(conf)).replace('/etc/mu300',str(conf))
            script=script.replace('/run/e5linux',str(runtime)).replace('/run/mu300',str(runtime)).replace('/proc/cmdline',str(cmdline))
            script=script.replace('/run/openwrt-',str(runtime/'openwrt-')).replace('"${CONF%/*}" /run','"${CONF%/*}" '+str(runtime))
            env=dict(os.environ)
            if fail_write or fail_save:
                bins=root/'bin';bins.mkdir()
                if fail_write:
                    (bins/'dd').write_text('#!/bin/sh\ncase " $* " in *" seek=2048 "*) exit 1;; esac\nexec /bin/dd "$@"\n')
                    (bins/'dd').chmod(0o755)
                if fail_save:
                    (bins/'mv').write_text('#!/bin/sh\ncase "$2" in *.backup.*) ;; *) exit 1;; esac\nexec /bin/mv "$@"\n')
                    (bins/'mv').chmod(0o755)
                env['PATH']=str(bins)+':'+env['PATH']
            p=root/'next-boot';p.write_text(script)
            before=misc.read_bytes();r=subprocess.run(['bash',str(p),op],capture_output=True,text=True,env=env)
            if bad_block or fail_write or fail_save:
                self.assertNotEqual(r.returncode,0,r.stdout+r.stderr)
                self.assertEqual((conf/'default-boot').read_text(),'android\n')
                self.assertEqual(before,misc.read_bytes())
            else:
                self.assertEqual(r.returncode,0,r.stdout+r.stderr)
                self.assertEqual((conf/'default-boot').read_text(),'linux\n')
                self.assertEqual(before[:2048],misc.read_bytes()[:2048])
                self.assertEqual(before[2080:],misc.read_bytes()[2080:])
    def test_e5_commit(self):self.run_case(TOP,'e5')
    @unittest.skipUnless((MU/'rootfs/overlay/opt/mu300/bin/mu300-next-boot').exists(),'MU300 checkout not supplied')
    def test_mu_commit(self):self.run_case(MU,'mu')
    def test_e5_reject_short_block(self):self.run_case(TOP,'e5',bad_block=True)
    @unittest.skipUnless((MU/'rootfs/overlay/opt/mu300/bin/mu300-next-boot').exists(),'MU300 checkout not supplied')
    def test_mu_reject_short_block(self):self.run_case(MU,'mu',bad_block=True)
    def test_e5_write_failure_keeps_intent(self):self.run_case(TOP,'e5',fail_write=True)
    @unittest.skipUnless((MU/'rootfs/overlay/opt/mu300/bin/mu300-next-boot').exists(),'MU300 checkout not supplied')
    def test_mu_write_failure_keeps_intent(self):self.run_case(MU,'mu',fail_write=True)
    def test_e5_failed_save_restores_misc(self):self.run_case(TOP,'e5',fail_save=True)
    @unittest.skipUnless((MU/'rootfs/overlay/opt/mu300/bin/mu300-next-boot').exists(),'MU300 checkout not supplied')
    def test_mu_failed_save_restores_misc(self):self.run_case(MU,'mu',fail_save=True)
    def test_local_snapshot(self):
        for repo,app in [(TOP,'t551m'),(MU,'mu300')]:
            source=repo/'openwrt'/('luci-app-'+app)/'root/usr/libexec/unisoc-modem/boot-status'
            if not source.exists():continue
            with tempfile.TemporaryDirectory() as d:
                root=Path(d);cmdline=root/'cmdline';cmdline.write_text('test\n')
                helper=root/'helper';helper.write_text('#!/bin/sh\nexit 88\n');helper.chmod(0o755)
                for f in ['misc-bc-slot-a.bin','misc-bc-slot-b-trial.bin','misc-bc-linux-trial.bin','misc-bc-android.bin']:(root/f).write_bytes(b'B'*32)
                env=dict(os.environ,BOOT_STATE_DIR=d,BOOT_RUNTIME_DIR=d,BOOT_CONTROL_HELPER=str(helper),BOOT_CMDLINE=str(cmdline))
                for value,temporary in [(None,True),('android',True),('linux',False),('broken',None)]:
                    p=root/'default-boot'
                    if value is None:p.unlink(missing_ok=True)
                    else:p.write_text(value+'\n')
                    r=subprocess.run(['sh',str(source)],capture_output=True,text=True,env=env,check=True)
                    result=json.loads(r.stdout);self.assertIs(result['temporary'],temporary)
                    self.assertTrue(result['can_set_default'])
                if app=='t551m':
                    cmdline.write_text('e5.openwrt=trial.ext4\n')
                    r=subprocess.run(['sh',str(source)],capture_output=True,text=True,env=env,check=True)
                    self.assertFalse(json.loads(r.stdout)['can_set_default'])

if __name__=='__main__':unittest.main()
