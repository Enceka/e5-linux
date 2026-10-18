#!/usr/bin/env python3
"""TF selection and full-capacity growth using isolated sparse files, no devices."""
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile
import unittest

TOP = Path(__file__).resolve().parents[2]
SOURCE = (TOP / 'openwrt/bundle/android-tf.sh').read_text()


class TF(unittest.TestCase):
    def run_helper(self, root, args, source=SOURCE):
        source = source.replace('/sys/class/block', str(root/'sys')).replace('/dev/block', str(root/'dev'))
        # Regular fixture files stand in for block nodes; no real devices are opened.
        source = source.replace('[ -b ', '[ -f ')
        script = root/'helper.sh'; script.write_text(source)
        return subprocess.run(['busybox', 'ash', str(script), *map(str, args)], capture_output=True, text=True, timeout=40)

    def fixture(self, root):
        (root/'dev/by-name').mkdir(parents=True)
        (root/'dev/mmcblk0p1').touch()
        (root/'dev/by-name/misc').symlink_to(root/'dev/mmcblk0p1')
        (root/'dev/mmcblk1').touch()
        (root/'sys/mmcblk1').mkdir(parents=True)
        (root/'sys/mmcblk1/ro').write_text('0\n')
        (root/'sys/mmcblk1/device').mkdir()
        (root/'sys/mmcblk1/device/type').write_text('SD\n')

    def test_existing_first_partition_and_unpartitioned_card(self):
        for partitioned in (False, True):
            with self.subTest(partitioned=partitioned), tempfile.TemporaryDirectory() as folder:
                root=Path(folder); self.fixture(root)
                if partitioned: (root/'dev/mmcblk1p1').touch()
                result=self.run_helper(root, ['target',root/'dev/mmcblk1'])
                self.assertEqual(result.returncode,0,result.stderr)
                self.assertEqual(result.stdout.strip(),str(root/('dev/mmcblk1p1' if partitioned else 'dev/mmcblk1')))

    def test_missing_p1_with_other_partitions_is_never_whole_card(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder); self.fixture(root)
            (root/'sys/mmcblk1p2').mkdir()
            self.assertNotEqual(self.run_helper(root,['target',root/'dev/mmcblk1']).returncode,0)

    def test_internal_storage_or_readonly_card_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder); self.fixture(root)
            self.assertNotEqual(self.run_helper(root,['target',root/'dev/mmcblk0']).returncode,0)
            (root/'sys/mmcblk1/ro').write_text('1\n')
            self.assertNotEqual(self.run_helper(root,['target',root/'dev/mmcblk1']).returncode,0)

    def test_growth_reaches_64_gib_and_preserves_files(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder); disk=root/'tf.ext4'
            subprocess.run(['mke2fs','-q','-t','ext4','-b','4096',str(disk),'64M'],check=True,stderr=subprocess.DEVNULL)
            (root/'proof').write_text('preserved TF firmware')
            subprocess.run(['debugfs','-w','-R',f'write {root}/proof /proof',str(disk)],check=True,capture_output=True)
            with disk.open('r+b') as stream: stream.truncate(64<<30)
            tools=root/'tools'; (tools/'lib').mkdir(parents=True); (tools/'usr/sbin').mkdir(parents=True)
            loader=tools/'lib/ld-musl-aarch64.so.1'
            loader.write_text('#!/bin/sh\nshift 2\nexec "$@"\n'); loader.chmod(0o755)
            shutil.copyfile(TOP/'openwrt/bundle/ext4-geometry.sh', tools/'ext4-geometry.sh')
            for name in ('e2fsck','resize2fs'): shutil.copyfile(shutil.which(name),tools/'usr/sbin'/name); (tools/'usr/sbin'/name).chmod(0o755)
            files=[p for p in tools.rglob('*') if p.is_file()]
            (tools/'SHA256SUMS').write_text(''.join(hashlib.sha256(p.read_bytes()).hexdigest()+'  '+p.relative_to(tools).as_posix()+'\n' for p in files))
            archive=root/'tools.tar'
            with tarfile.open(archive,'w') as tar:
                for p in tools.rglob('*'):
                    if p.is_file(): tar.add(p,arcname=p.relative_to(tools).as_posix())
            # blockdev reads the fixture's geometry, all ext4 operations are real.
            source=SOURCE.replace('set -eu','set -eu\nblockdev() { echo 134217728; }',1)
            result=self.run_helper(root,['grow',disk,archive,root/'extract'],source)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            with disk.open('rb') as stream: stream.seek(1028); blocks=int.from_bytes(stream.read(4),'little')
            self.assertEqual(blocks*4096,64<<30)
            data=subprocess.check_output(['debugfs','-R','cat /proof',str(disk)],stderr=subprocess.DEVNULL)
            self.assertEqual(data,b'preserved TF firmware')

    def test_tiny_tail_and_partial_group_are_both_supported(self):
        checker = TOP/'openwrt/bundle/ext4-geometry.sh'
        with tempfile.TemporaryDirectory() as folder:
            disk = Path(folder)/'geometry.ext4'
            subprocess.run(['mke2fs','-q','-t','ext4','-b','4096',str(disk),'128M'],
                           check=True, stderr=subprocess.DEVNULL)
            for wanted, expected in ((65787,65536),(81920,81920)):
                with self.subTest(wanted=wanted):
                    with disk.open('r+b') as stream: stream.truncate(wanted*4096)
                    subprocess.run(['resize2fs',str(disk)],check=True,capture_output=True)
                    subprocess.run(['e2fsck','-fn',str(disk)],check=True,capture_output=True)
                    with disk.open('rb') as stream:
                        stream.seek(1028); self.assertEqual(int.from_bytes(stream.read(4),'little'),expected)
                    result=subprocess.run(['busybox','ash','-c',
                        '. "$1"; ext4_verify_grown "$2" "$3"','verify',str(checker),str(disk),str(wanted*8)],
                        capture_output=True,text=True)
                    self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            for sectors in (32768*8, 10*32768*8):
                result=subprocess.run(['busybox','ash','-c',
                    '. "$1"; ext4_verify_grown "$2" "$3"','verify',str(checker),str(disk),str(sectors)],
                    capture_output=True,text=True)
                self.assertNotEqual(result.returncode,0,'must reject overflow and substantial undergrowth')


class BootProbe(unittest.TestCase):
    def test_requests_are_found_only_on_tf_and_conflicts_stop_updates(self):
        init=(TOP/'boot/init').read_text()
        start=init.index('# The PC installer alone arms a TF update.')
        probe=init[start:init.index('. /etc/part-update.sh',start)]
        cases=[('ordinary',False,'SD',[],None),
               ('forced-cmdline',False,'SD',['mmcblk1p1'],'mmcblk1p1'),
               ('partition',True,'SD',['mmcblk1p1'],'mmcblk1p1'),
               ('raw',True,'SD',['mmcblk1'],'mmcblk1'),
               ('internal',True,'MMC',['mmcblk1p1'],None),
               ('conflict',True,'SD',['mmcblk1p1','mmcblk1p2'],'mmcblk1p2')]
        for label,enabled,kind,targets,want in cases:
            with self.subTest(label=label), tempfile.TemporaryDirectory() as folder:
                root=Path(folder); (root/'run').mkdir(); (root/'dev').mkdir()
                (root/'sys/mmcblk1/device').mkdir(parents=True)
                (root/'sys/mmcblk1/device/type').write_text(kind)
                (root/'cmdline').write_text('e5.tf_update=1' if enabled else 'console=tty0')
                for name in targets:
                    (root/'dev'/name).touch()
                    (root/'payload'/name/'etc/e5').mkdir(parents=True)
                    (root/'payload'/name/'etc/e5/sd-root').touch()
                    (root/'payload'/name/'.e5-update').mkdir()
                    (root/'payload'/name/'.e5-update/request').write_text('KIND=sd\n')
                code=probe.replace('/proc/cmdline',str(root/'cmdline')).replace('/sys/class/block',str(root/'sys'))
                code=code.replace('/run/',str(root/'run')+'/').replace('/dev/',str(root/'dev')+'/').replace('/tmp/tf-update-probe',str(root/'view'))
                code=code.replace('[ -b ','[ -f ')
                harness=f'''
mount() {{ for dest; do :; done; node=; for arg; do case "$arg" in {root}/dev/*) node=${{arg##*/}};; esac; done
  cp -a "{root}/payload/$node/." "$dest/"; }}
umount() {{ rm -rf "$1"; mkdir -p "$1"; }}
'''
                result=subprocess.run(['busybox','ash'],input=harness+code,text=True,capture_output=True,timeout=3)
                self.assertEqual(result.returncode,0,result.stderr)
                pending=root/'run/part-update-pending'
                self.assertEqual(pending.exists(),want is not None)
                if want: self.assertEqual(pending.read_text().strip(),str(root/'dev'/want))
                self.assertEqual((root/'run/tf-update-conflict').exists(),label=='conflict')


if __name__=='__main__': unittest.main()
