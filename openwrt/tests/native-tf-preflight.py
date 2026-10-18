#!/usr/bin/env python3
"""Exercise native TF preflight with disposable package files, no devices."""
import os
from pathlib import Path
import subprocess
import tarfile
import tempfile
import unittest

TOP=Path(__file__).resolve().parents[2]


class Preflight(unittest.TestCase):
    def test_geometry_helper_is_required_before_boot_or_card_operations(self):
        for include in (False,True):
            with self.subTest(include=include),tempfile.TemporaryDirectory() as directory:
                root=Path(directory);package=root/'package';state=root/'state'
                (package/'files').mkdir(parents=True);state.mkdir()
                (package/'files/tf-install.env').write_text('ANDROID_MODEL=E5\nBOOT_BYTES=4096\n')
                node=root/'dev/block/by-name';node.mkdir(parents=True)
                for n in ('boot_b','misc'):(node/n).touch()
                script=(TOP/'openwrt/bundle/magisk-tf-install.sh').read_text()
                script=script.replace('/dev/block',str(root/'dev/block')).replace('/data/e5linux',str(root/'data'))
                script=script.replace('[ -b ','[ -f ')
                with tarfile.open(package/'files/ext4-tools.tar','w') as tar:
                    for name in ['lib/ld-musl-aarch64.so.1','usr/sbin/e2fsck','usr/sbin/resize2fs','SHA256SUMS']+(['ext4-geometry.sh'] if include else []):
                        info=tarfile.TarInfo(name);info.size=1
                        tar.addfile(info,__import__('io').BytesIO(b'x'))
                stop=package/'files/e5-bootctl'
                stop.write_text('#!/bin/sh\ntouch "$STATE/reached-boot-check"\nexit 21\n');stop.chmod(0o755)
                code='''id(){ echo 0; }
getprop(){ case "$1" in ro.product.model) echo E5;; ro.boot.slot_suffix) echo _a;; ro.boot.verifiedbootstate) echo orange;; esac; }
sha256sum(){ return 0; }
blockdev(){ echo 4096; }
'''+script+'\npreflight\n'
                # Library loading returns before main; the appended preflight is explicit.
                fixture=root/'library.sh';fixture.write_text(code)
                harness='. "$LIB"; preflight'
                env=dict(os.environ,LIB=str(fixture),E5_TF_LIB='1',P=str(package),STATE=str(state))
                result=subprocess.run(['busybox','ash','-ec',harness],env=env,capture_output=True,text=True)
                self.assertNotEqual(result.returncode,0)
                self.assertEqual((state/'reached-boot-check').exists(),include,result.stdout+result.stderr)
                self.assertEqual('missing ext4 tool: ext4-geometry.sh' in result.stderr,not include)


if __name__=='__main__':unittest.main()
