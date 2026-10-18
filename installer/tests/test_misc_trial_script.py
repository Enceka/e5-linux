"""Execute the generated misc transaction against ordinary Linux test files."""
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from backend.boot_image import boot_installed_mu300
import test_mu300_boot_switch as fixture


@unittest.skipUnless(sys.platform=='linux' and shutil.which('bash'),'run the file-only shell fixture in Linux/WSL')
class MiscScript(unittest.TestCase):
    def test_success_corruption_short_write_and_changed_source(self):
        for slot in ('a','b'):
            for failure in ('none','corrupt','short','changed'):
                with self.subTest(slot=slot,failure=failure),tempfile.TemporaryDirectory(prefix='misc-script-') as temp:
                    root=Path(temp);android=fixture.AndroidFixture(slot)
                    boot_installed_mu300(fixture.MU300Switch().api(),android,root)
                    before=bytes(range(256))*8+android.before+bytes(range(256))*8
                    initial=before if failure!='changed' else before[:2048]+bytes(32)+before[2080:]
                    misc=root/'misc';misc.write_bytes(initial)
                    (root/'misc-trial.bin').write_bytes(android.wanted)
                    (root/'untouched-root').write_bytes(b'root must remain untouched')
                    shim=root/'bin';shim.mkdir()
                    dd=shutil.which('dd')
                    (shim/'dd').write_text('#!/bin/sh\nif [ "$1" = "if=$P/misc-trial.bin" ] && [ "$FAILURE" != none ]; then\n'+
                        '  '+shlex.quote(dd)+' if=/dev/zero of="$FIXTURE_MISC" bs=1 seek=2048 count=8 conv=notrunc,fsync 2>/dev/null\n'+
                        '  [ "$FAILURE" != short ]; exit $?\nfi\nexec '+shlex.quote(dd)+' "$@"\n')
                    (shim/'dd').chmod(0o755)
                    body=android.body.replace('/dev/block/by-name/misc',shlex.quote(str(misc))).replace('/data/adb/openwrt-boot-control',shlex.quote(str(root/'backups')))
                    script='set -eu\ngetprop() { printf "%s\\n" "_'+slot+'"; }\n'+body
                    env=dict(os.environ,P=str(root),FAILURE=failure,FIXTURE_MISC=str(misc),PATH=str(shim)+':'+os.environ['PATH'])
                    result=subprocess.run(['bash','-c',script],capture_output=True,text=True,env=env,timeout=10)
                    after=misc.read_bytes()
                    if failure=='none':
                        self.assertEqual(result.returncode,0,result.stderr)
                        self.assertEqual(after[2048:2080],android.wanted)
                        self.assertIn('MISC-TRIAL-VERIFIED',result.stdout)
                    else:
                        self.assertNotEqual(result.returncode,0)
                        self.assertEqual(after,initial)
                        self.assertNotIn('MISC-TRIAL-VERIFIED',result.stdout)
                    self.assertEqual(after[:2048],initial[:2048]);self.assertEqual(after[2080:],initial[2080:])
                    self.assertEqual((root/'untouched-root').read_bytes(),b'root must remain untouched')
                    backups=list((root/'backups').glob('before.*'))
                    self.assertEqual(len(backups),1);self.assertEqual(backups[0].read_bytes(),initial[2048:2080])


if __name__=='__main__':unittest.main()
