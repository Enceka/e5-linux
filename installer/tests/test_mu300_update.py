"""Hidden-area updates use proven loop geometry; all transports are simulated."""
from contextlib import nullcontext, redirect_stdout
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import shlex
import struct
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.adapter import Adapter
from backend.mu300_update import LEGACY_LAYOUT_PROBE, legacy_layout
from backend.state import Context, Store

CAPACITY = 34779168768  # Capacity from the supplied U30Air report.
PARTITION_END = 400000000
OFFSET = (PARTITION_END//4096+1)*4096*512
SECTORS = CAPACITY//512
DISK_SECTORS = (256 << 30)//512


def geometry(**changes):
    fields = dict(device='/dev/loop0', backing='/dev/mmcblk0', offset=OFFSET,
                  sectors=SECTORS, disk_sectors=DISK_SECTORS, limit=SECTORS*512,
                  partition_end=PARTITION_END)
    fields.update(changes)
    return 'MU300-LEGACY-LAYOUT-V1\n'+'\n'.join(map(str, fields.values()))+'\n'


def superblock(capacity=CAPACITY):
    data = bytearray(1024)
    data[56:58] = b'\x53\xef'
    data[120:129] = b'mu300root'
    struct.pack_into('<I', data, 24, 2)
    struct.pack_into('<I', data, 4, capacity//4096)
    return bytes(data)


class LegacyUpdate(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        boot = self.root/'desktop/files/boot'
        boot.mkdir(parents=True)
        (boot/'original-init').write_text('ROOT_OFFSET=27762098176\n')
        (self.root/'desktop/manifest.json').write_text(json.dumps({'kernel':'7.2'}))

    def probe(self, text=None, raw=None):
        execute = Mock(return_value=geometry() if text is None else text)
        read = Mock(return_value=superblock() if raw is None else raw)
        result = legacy_layout('client', self.root, execute, read)
        read.assert_called_once_with('client', 'dd if=/dev/loop0 bs=1024 skip=1 count=1 2>/dev/null', 1024)
        return result

    def test_reported_capacity_in_256_gib_hidden_area_needs_only_one_kib(self):
        layout = self.probe()
        self.assertEqual(layout['capacity'], CAPACITY)
        self.assertEqual(layout['offset'], OFFSET)
        self.assertEqual(layout['mode'], 'legacy')

    def test_gpt_overlap_overflow_wrong_backing_and_unbootable_offsets_stop(self):
        invalid = [dict(device='/dev/mmcblk0p40'), dict(device='/dev/loop0;reboot'),
                   dict(backing='/data/mu300linux/openwrt.ext4'), dict(offset=OFFSET+1),
                   dict(offset=4096), dict(sectors=DISK_SECTORS), dict(limit=17),
                   dict(partition_end=0), dict(offset=OFFSET+4096)]
        for change in invalid:
            with self.subTest(change=change), self.assertRaises(ValueError):self.probe(geometry(**change))
        for text in ('', geometry().replace('MU300-LEGACY-LAYOUT-V1','unknown'), geometry()+'extra\n'):
            with self.assertRaises(ValueError):self.probe(text)

    def test_ext4_identity_and_capacity_are_required(self):
        for pos in (56, 120):
            bad = bytearray(superblock());bad[pos] ^= 1
            with self.assertRaises(ValueError):self.probe(raw=bytes(bad))
        with self.assertRaises(ValueError):self.probe(raw=superblock(CAPACITY+(1 << 30)))
        with self.assertRaises(ValueError):self.probe(raw=superblock()[:-1])
        with self.assertRaises(ValueError):self.probe(raw=superblock(0))

    def test_saved_legacy_boot_offset_is_supported_without_repartition(self):
        offset = OFFSET+4096
        (self.root/'desktop/files/boot/original-init').write_text('ROOT_OFFSET='+str(offset)+'\n')
        self.assertEqual(self.probe(geometry(offset=offset))['offset'], offset)

    @unittest.skipUnless(sys.platform.startswith('linux'), 'Linux target-shell fixture; run in Linux/WSL')
    def test_real_readonly_probe_checks_mounted_container_and_loop_source(self):
        fake = self.root/'runtime'
        files = {'run/mu300/disk-dev':'/dev/loop0', 'sys/class/block/loop0/dev':'7:0',
                 'sys/class/block/loop0/loop/backing_file':'/dev/mmcblk0',
                 'sys/class/block/loop0/loop/offset':str(OFFSET), 'sys/class/block/loop0/size':str(SECTORS),
                 'sys/class/block/loop0/loop/sizelimit':str(SECTORS*512),
                 'sys/class/block/mmcblk0/size':str(DISK_SECTORS),
                 'sys/class/block/mmcblk0p1/start':'2048',
                 'sys/class/block/mmcblk0p1/size':str(PARTITION_END-2048),
                 'proc/self/mountinfo':'17 11 7:0 / /mnt/mu300-disk rw - ext4 /dev/loop0 rw'}
        for name, value in files.items():
            path = fake/name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(value+'\n')
        root = fake/'root'
        root.mkdir()
        container = fake/'container'
        container.symlink_to(root, target_is_directory=True)
        script = LEGACY_LAYOUT_PROBE.replace('[ / -ef /mnt/mu300-disk/openwrt ]',
                    '[ '+shlex.quote(str(root))+' -ef '+shlex.quote(str(container))+' ]')
        # Only the block-device predicate is replaced; every sysfs/mount read,
        # case guard, arithmetic operation and protocol printf runs unchanged.
        script = script.replace('[ -b "$d" ]', '[ "$d" = /dev/loop0 ]')
        for prefix in ('/sys/class/block', '/run/mu300', '/proc/self/mountinfo'):
            script = script.replace(prefix, str(fake)+prefix)
        def run():return subprocess.run(['/bin/sh','-c',script], capture_output=True, text=True, timeout=5)
        result = run()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, geometry())
        (fake/'proc/self/mountinfo').write_text(files['proc/self/mountinfo'].replace('7:0','7:1'))
        self.assertNotEqual(run().returncode, 0)
        (fake/'proc/self/mountinfo').write_text(files['proc/self/mountinfo'])
        (fake/'sys/class/block/loop0/loop/backing_file').write_text('/data/mu300linux/openwrt.ext4')
        self.assertNotEqual(run().returncode, 0)

    def execute_update(self, mode='legacy', fail=None, changed=False, capacity=CAPACITY, family='7.2.8', entry='gui'):
        package = dict(path=str(self.root), adapter='mu300', profile='mu300-family', kernel='7.2', layout='mu300root-container')
        store = Store(self.root/'state')
        choices = dict(method='update', host='192.168.78.1', grow=True)
        record = store.create(package, {'serial':'ssh:fixture', 'cid':'a'*32}, choices,
                              {'method':'update', 'openwrt_bytes':capacity, 'preserves_settings':True})
        adapter = Adapter.__new__(Adapter)
        adapter.root, adapter.kind = self.root, 'mu300'
        adapter.ctx = Context(store, record, lambda *_:None)
        adapter.validate_ssh = Mock()
        adapter.password = 'fixture-only'
        captured, commands, probes = {}, [], []
        for name in ('rootfs.tar.gz', 'local-update.sh', 'mu300-update-library.sh', 'busybox', 'rootfs-critical.sha256', 'rootfs.requirements'):
            (self.root/name).write_bytes(('fixture '+name).encode())
            if name.endswith('.sh'):(self.root/name).replace(self.root/'desktop'/name)

        def upload(client, local, remote):captured[remote] = Path(local).read_bytes()

        def execute(client, command):
            commands.append(command)
            if 'cat /run/mu300/device' in command:return 'u30air\nb\n/dev/mmcblk0p3\n'+mode+'\n'
            if command == LEGACY_LAYOUT_PROBE:
                probes.append(command)
                return geometry(device='/dev/loop1') if changed and len(probes)>1 else geometry()
            if command == 'uname -r':return family
            if command.startswith('sha256sum '):
                return 'wrong hash' if fail else hashlib.sha256(captured[command.split(' ',1)[1]]).hexdigest()+'  staged'
            if command.startswith(('mkdir ', 'chmod ')):return ''
            raise AssertionError(command)

        read = Mock(side_effect=lambda client, command, count:superblock() if count == 1024 else bytes(32))
        repacker = SimpleNamespace(boot_control=Mock(return_value=bytes(32)))
        boot = Mock(return_value=b'fixture-new-boot')
        old_update = Mock(side_effect=AssertionError('Obsolete package gate executed'))
        adapter.legacy = SimpleNamespace(GUI=adapter, ssh_exec=execute, ssh_read_exact=read,
            module=lambda root:repacker, boot=boot, confirm=Mock(), ssh_upload=upload,
            digest=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest(),
            payload_rootfs=lambda root:nullcontext(self.root/'rootfs.tar.gz'),
            payload_file=lambda root,name:self.root/name, Outcome=lambda *args:SimpleNamespace(state=args[0]), update=old_update)
        client = Mock()
        error = None
        with patch('paramiko.SSHClient', return_value=client), patch.dict(os.environ, {'MU300_SSH_PASSWORD':'fixture-only'}), redirect_stdout(io.StringIO()):
            try:
                if entry == 'cli':
                    spec = importlib.util.spec_from_file_location('hidden_area_cli_fixture', Path(__file__).resolve().parents[2]/'desktop/installer.py')
                    cli = importlib.util.module_from_spec(spec);spec.loader.exec_module(cli)
                    for key, value in vars(adapter.legacy).items():
                        if key != 'update':setattr(cli, key, value)
                    cli.GUI = None
                    cli.update(SimpleNamespace(host='192.168.78.1'), self.root)
                else:adapter.execute()
            except ValueError as caught:error = caught
        client.close.assert_called_once()
        old_update.assert_not_called()
        return record, commands, captured, boot, error

    def test_actual_adapter_bypasses_old_gate_and_commits_preserved_legacy_mode(self):
        record, commands, captured, boot, error = self.execute_update()
        self.assertIsNone(error)
        self.assertEqual(boot.call_args.args[2], 'legacy')
        self.assertEqual(record['update_layout']['capacity'], CAPACITY)
        self.assertEqual(record['update_layout']['offset'], OFFSET)
        self.assertEqual(record['effects']['update-commit']['state'], 'done')
        self.assertEqual(record['status'], 'waiting_device')
        self.assertEqual(sum(c == LEGACY_LAYOUT_PROBE for c in commands), 2)
        self.assertEqual(sum(c.startswith('chmod ') for c in commands), 1)
        self.assertEqual(len(captured), 8)
        self.assertTrue(all(p.startswith('/mnt/mu300-disk/.mu300-desktop-') for p in captured))

    def test_actual_compatible_cli_uses_same_hidden_area_update(self):
        if not (Path(__file__).resolve().parents[2]/'desktop/installer.py').is_file():
            self.skipTest('MU300 CLI source is tested in its repository')
        _, commands, captured, boot, error = self.execute_update(entry='cli')
        self.assertIsNone(error)
        self.assertEqual(boot.call_args.args[2], 'legacy')
        self.assertEqual(sum(c == LEGACY_LAYOUT_PROBE for c in commands), 2)
        self.assertEqual(sum(c.startswith('chmod ') for c in commands), 1)
        self.assertEqual(len(captured), 8)

    def test_transfer_failure_never_commits(self):
        record, commands, _, _, error = self.execute_update(fail=True)
        self.assertIn('checksum', str(error))
        self.assertFalse(any(c.startswith('chmod ') for c in commands))
        self.assertNotIn('update-commit', record['effects'])

    def test_changed_loop_binding_before_commit_stops(self):
        record, commands, _, _, error = self.execute_update(changed=True)
        self.assertIn('layout changed', str(error))
        self.assertFalse(any(c.startswith('chmod ') for c in commands))
        self.assertNotIn('update-commit', record['effects'])

    def test_stale_capacity_and_kernel_family_stop_before_upload(self):
        for change, message in [({'capacity':4 << 30}, 'capacity changed'), ({'family':'6.18.54'}, 'Kernel family')]:
            with self.subTest(change=change):
                _, commands, captured, _, error = self.execute_update(**change)
                self.assertIn(message, str(error))
                self.assertFalse(captured)
                self.assertFalse(any(c.startswith('mkdir ') for c in commands))

    def test_existing_modes_keep_their_boot_target(self):
        for mode in ('sd', 'part', 'data-image'):
            with self.subTest(mode=mode):
                record, commands, _, boot, error = self.execute_update(mode=mode)
                self.assertIsNone(error)
                self.assertEqual(boot.call_args.args[2], mode)
                self.assertNotIn('update_layout', record)
                self.assertNotIn(LEGACY_LAYOUT_PROBE, commands)
                self.assertEqual(record['effects']['update-commit']['state'], 'done')


if __name__ == '__main__':unittest.main()
