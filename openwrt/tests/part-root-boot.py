#!/usr/bin/env python3
"""part_root() of boot/init: the internal partition system's discovery.

The function is extracted from boot/init and run against a fake sysfs and a
mount stub, so the selection logic (GPT name match, disk scope, markers) is
checked without a device.  The same extraction trick as
openwrt/tests/screen-session-startup.py.
"""
from pathlib import Path
import subprocess
import tempfile
import unittest

TOP = Path(__file__).resolve().parents[2]
SOURCE = (TOP / 'boot/init').read_text()


def block():
    start = SOURCE.index('part_root() {')
    end = SOURCE.index('\n}\n', start) + 3
    text = SOURCE[start:end]
    # relative paths so the harness runs the globs in a temp directory
    return text.replace('/sys/class/block', 'sys/class/block').replace('/sdtry', 'sdtry')


HARNESS = '''
mounted=
mount() {
    dev=; for a in "$@"; do case "$a" in /dev/*) dev=$a;; esac; done
    echo "mount ${dev##*/}" >> activity
    d=fx/${dev##*/}
    [ -d "$d" ] || return 1
    rm -rf sdtry; mkdir -p sdtry; cp -a "$d/." sdtry/
    mounted=1
}
umount() { echo "umount $1" >> activity; rm -rf sdtry; mounted=; }
''' + block() + '''
misc=/dev/mmcblk0p3
PARTROOT= PARTTRIAL=
if part_root; then echo "FOUND $PARTROOT TRIAL=${PARTTRIAL:-none}"; else echo NOTFOUND; fi
[ -z "$mounted" ] || echo LEAKED-MOUNT
'''


class PartRoot(unittest.TestCase):
    def run_case(self, fixtures, contents=None):
        with tempfile.TemporaryDirectory(prefix='part-root-') as tmp:
            root = Path(tmp)
            for name, files in fixtures.items():
                for file in files:
                    target = root / 'fx' / name / file
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_text('#!/bin/sh\n' if file.endswith('init') else 'x')
                    if file.endswith('init'):
                        target.chmod(0o755)
            for file, content in (contents or {}).items():
                (root / 'fx' / 'mmcblk0p20' / file).write_text(content)
            (root / 'sys/class/block/mmcblk0p20').mkdir(parents=True)
            (root / 'sys/class/block/mmcblk0p20/uevent').write_text('PARTNAME=e5root\n')
            (root / 'sys/class/block/mmcblk0p21').mkdir(parents=True)
            (root / 'sys/class/block/mmcblk0p21/uevent').write_text('PARTNAME=userdata\n')
            (root / 'sys/class/block/mmcblk1p1').mkdir(parents=True)
            (root / 'sys/class/block/mmcblk1p1/uevent').write_text('PARTNAME=e5root\n')
            result = subprocess.run(['sh', '-c', HARNESS], cwd=root,
                                    text=True, capture_output=True)
            assert result.returncode == 0, result.stderr
            activity = (root / 'activity').read_text() if (root / 'activity').exists() else ''
            return result.stdout, activity

    def test_marked_partition_on_the_system_disk_is_found(self):
        out, activity = self.run_case({
            'mmcblk0p20': ['sbin/init', 'etc/e5/part-root'],
            'mmcblk0p21': [],
            'mmcblk1p1': ['sbin/init', 'etc/e5/part-root'],   # the card's copy is out of scope
        })
        self.assertIn('FOUND /dev/mmcblk0p20', out)
        self.assertNotIn('LEAKED-MOUNT', out)
        self.assertEqual(activity.count('mount mmcblk0p20'), 1)
        self.assertEqual(activity.count('umount sdtry'), 1)

    def test_name_match_without_marker_is_skipped(self):
        out, activity = self.run_case({
            'mmcblk0p20': [],                                  # named e5root, no marker
            'mmcblk0p21': [],
            'mmcblk1p1': ['sbin/init', 'etc/e5/part-root'],    # only the card one is valid
        })
        self.assertIn('NOTFOUND', out)
        self.assertNotIn('LEAKED-MOUNT', out)
        self.assertIn('mount mmcblk0p20', activity)

    def test_marker_without_init_is_not_a_system(self):
        out, _ = self.run_case({
            'mmcblk0p20': ['etc/e5/part-root'],
            'mmcblk0p21': [],
            'mmcblk1p1': [],
        })
        self.assertIn('NOTFOUND', out)

    def test_trial_marker_is_reported(self):
        out, _ = self.run_case({
            'mmcblk0p20': ['sbin/init', 'etc/e5/part-root', 'etc/e5/part-trial'],
            'mmcblk0p21': [],
            'mmcblk1p1': [],
        }, contents={'etc/e5/part-trial': '1'})
        self.assertIn('TRIAL=1', out)
        out, _ = self.run_case({
            'mmcblk0p20': ['sbin/init', 'etc/e5/part-root', 'etc/e5/part-trial'],
            'mmcblk0p21': [],
            'mmcblk1p1': [],
        }, contents={'etc/e5/part-trial': '0'})
        self.assertIn('TRIAL=0', out)

    def test_selection_arm_and_capability_are_wired(self):
        # the branch runs before the image path and only for boot-os=part; the
        # installers gate on the advertised token
        self.assertLess(SOURCE.index('stage=openwrt-part'),
                        SOURCE.index('elif [ -z "$rootdir" ] && [ -z "$SDMETA" ]'))
        self.assertIn('[ "$want" = part ] && part_root', SOURCE)
        self.assertIn('[ "$PARTTRIAL" != 0 ]', SOURCE)
        self.assertIn('stage=openwrt-part-trial', SOURCE)
        self.assertIn('[ -z "$rootdir" ] && [ -z "$e5_trial" ] && sd_wait 8', SOURCE)
        self.assertIn('openwrt-image userdata-boot-os sd-gen part-root', SOURCE)
        self.assertIn('part-root-dev', SOURCE)
        boot_ok = (TOP / 'boot/installer-runtime/openwrt/etc/init.d/e5-boot-ok').read_text()
        self.assertIn('rm -f /etc/e5/part-trial', boot_ok)
        # on-screen progress: a shared heartbeat names the step; the
        # framebuffer console font has no CJK, so console lines stay ASCII,
        # and the backlight is not touched
        install = (TOP / 'boot/install-part.sh').read_text()
        self.assertIn('part_progress_start', install)
        # the install boot consumes one of slot b's two tries and LK treats a
        # single remaining try as failure: the trial must be refilled before
        # the restart into the new system (found on the M8, 2026-10-13)
        self.assertLess(install.index('part-install-rearm'), install.index('reboot -f'))
        for line in install.splitlines():
            if '/dev/kmsg' in line:
                self.assertTrue(all(ord(c) < 128 for c in line), line)
        self.assertNotIn('/sys/class/backlight', install)


if __name__ == '__main__':
    unittest.main()
