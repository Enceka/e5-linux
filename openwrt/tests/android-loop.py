"""Loop-node timing and cleanup tests; no block devices or Android access."""
from pathlib import Path
import os
import re
import shutil
import subprocess
import tempfile
import unittest

TOP=Path(__file__).resolve().parents[2]
HELPER=TOP/'openwrt/bundle/android-loop.sh'
SCRIPTS=[TOP/'openwrt/bundle/magisk-tf-install.sh',TOP/'openwrt/bundle/userdata-image.sh']


class LoopNodes(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='loop-node-');self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.block=self.root/'block';self.block.mkdir()
        self.node=self.block/'loop31';self.log=self.root/'events';self.ticks=self.root/'ticks'
        self.shells=[shutil.which(name) for name in ('dash','bash') if shutil.which(name)]
        if not self.shells:self.skipTest('A POSIX shell is required')
        requested=os.environ.get('ANDROID_LOOP_TEST_SHELL','dash')
        if requested=='ash':
            if not shutil.which('busybox'):self.skipTest('BusyBox ash is required')
            self.runner=[shutil.which('busybox'),'ash']
        else:
            selected=shutil.which(requested)
            if not selected:self.skipTest('Requested shell is unavailable: '+requested)
            self.runner=[selected]

    def run_case(self,mode='fallback',identity='7:248',candidate='/dev/loop31'):
        text=HELPER.read_text(encoding='utf-8').replace('/dev/block/',str(self.block)+'/').replace('[ -d /dev/block ]','[ -d "$TEST_BLOCK" ]')
        text+='''
losetup() { printf '%s\\n' "$TEST_CANDIDATE"; }
desktop_loop_is_block() { [ -f "$1.block" ]; }
desktop_loop_sysdev() { printf '%s\\n' "$TEST_IDENTITY"; }
sleep() {
    echo tick >> "$TEST_TICKS"
    if [ "$TEST_MODE" = delayed ] && [ "$(wc -l < "$TEST_TICKS")" = 3 ]; then
        : > "$TEST_BLOCK/loop31.block"
    fi
}
mknod() {
    printf 'mknod %s\\n' "$*" >> "$TEST_LOG"
    [ "$TEST_MODE" != fail ] || return 1
    : > "$3"; : > "$3.block"
    [ "$TEST_MODE" != raced ]
}
restorecon() { printf 'restorecon %s\\n' "$*" >> "$TEST_LOG"; }
desktop_free_loop
'''
        env=dict(os.environ,TEST_BLOCK=str(self.block),TEST_LOG=str(self.log),TEST_TICKS=str(self.ticks),
                 TEST_MODE=mode,TEST_IDENTITY=identity,TEST_CANDIDATE=candidate)
        return subprocess.run(self.runner+['-ec',text],env=env,text=True,capture_output=True,timeout=5)

    def test_existing_node_is_immediate_and_never_creates_an_alias(self):
        Path(str(self.node)+'.block').touch()
        result=self.run_case()
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(result.stdout.strip(),str(self.node))
        self.assertFalse(self.ticks.exists());self.assertFalse(self.log.exists())

    def test_delayed_uevent_node_is_used_without_mknod(self):
        result=self.run_case('delayed')
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(result.stdout.strip(),str(self.node))
        self.assertEqual(len(self.ticks.read_text().splitlines()),3)
        self.assertFalse(self.log.exists())

    def test_missing_node_is_created_only_at_canonical_dev_path(self):
        result=self.run_case()
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(result.stdout.strip(),str(self.node))
        self.assertEqual(len(self.ticks.read_text().splitlines()),10)
        events=self.log.read_text()
        self.assertIn('mknod -m 600 '+str(self.node)+' b 7 248',events)
        self.assertIn('restorecon '+str(self.node),events)
        self.assertNotIn('MU300_INSTALL_TMP',HELPER.read_text())

    def test_concurrent_node_creation_is_success(self):
        result=self.run_case('raced')
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(result.stdout.strip(),str(self.node))

    def test_creation_failure_is_not_reported_as_a_usable_node(self):
        result=self.run_case('fail')
        self.assertNotEqual(result.returncode,0);self.assertEqual(result.stdout,'')

    def test_wrong_kernel_device_numbers_never_create_a_node(self):
        for identity in ('8:248','7:249','7:248:9','7:x',':248'):
            with self.subTest(identity=identity):
                result=self.run_case(identity=identity)
                self.assertNotEqual(result.returncode,0);self.assertFalse(self.log.exists())

    def test_nonblock_or_symlink_collision_never_gets_overwritten(self):
        self.node.write_text('occupied')
        result=self.run_case()
        self.assertNotEqual(result.returncode,0);self.assertEqual(self.node.read_text(),'occupied')
        self.assertFalse(self.log.exists())
        self.node.unlink();self.node.symlink_to(self.root/'missing')
        result=self.run_case()
        self.assertNotEqual(result.returncode,0);self.assertTrue(self.node.is_symlink())
        self.assertFalse(self.log.exists())

    def test_invalid_names_never_wait_or_touch_dev(self):
        for candidate in ('/dev/loop31oops','/dev/loop08','/dev/loop131072','/data/loop31','/dev/block/loop'):
            with self.subTest(candidate=candidate):
                result=self.run_case(candidate=candidate)
                self.assertNotEqual(result.returncode,0);self.assertFalse(self.ticks.exists());self.assertFalse(self.log.exists())

    def test_shell_syntax(self):
        for shell in self.shells:
            for path in [HELPER]+SCRIPTS:
                result=subprocess.run([shell,'-n',str(path)],capture_output=True,text=True)
                self.assertEqual(result.returncode,0,(path,result.stderr))

    def test_failure_cleanup_preserves_mounted_loops_and_never_detaches_unowned_ones(self):
        for source in SCRIPTS:
            body=source.read_text(encoding='utf-8')
            start=body.index('cleanup() {');end=body.index('\n}',start)+2
            cleanup=body[start:end]
            for mounted,attached,unmount_rc,detached in [(0,0,0,False),(0,1,0,True),(1,1,0,True),(1,1,1,False)]:
                with self.subTest(source=source,mounted=mounted,attached=attached,unmount_rc=unmount_rc):
                    self.log.unlink(missing_ok=True)
                    # These are shell ownership shims; no mounts/ioctls run.
                    setup='''
umount() { echo unmount >> "$TEST_LOG"; return "$TEST_UNMOUNT_RC"; }
losetup() { echo detach >> "$TEST_LOG"; }
loop=/owned/loop; LOOP=$loop; T=/owned/stage; STATE=$T
heartbeat=; lock=/owned/lock; mounted=$TEST_MOUNTED; VIEW_MOUNTED=$mounted
loop_attached=$TEST_ATTACHED; LOOP_ATTACHED=$loop_attached
stage=$TEST_STAGE; image=$stage/image; bound=0; devbound=0; procbound=0; ok=0
mkdir -p "$stage"; touch "$image"
'''
                    env=dict(os.environ,TEST_LOG=str(self.log),TEST_STAGE=str(self.root/'cleanup-stage'),TEST_UNMOUNT_RC=str(unmount_rc),TEST_MOUNTED=str(mounted),TEST_ATTACHED=str(attached))
                    result=subprocess.run(self.runner+['-c',setup+cleanup+'\n(exit 7); cleanup'],env=env,text=True,capture_output=True,timeout=5)
                    self.assertEqual(result.returncode,1 if mounted and unmount_rc else 7)
                    events=self.log.read_text() if self.log.exists() else ''
                    self.assertEqual('detach' in events,detached)
                    if mounted and not unmount_rc:self.assertLess(events.index('unmount'),events.index('detach'))


if __name__=='__main__':unittest.main()
