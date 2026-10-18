#!/usr/bin/env python3
"""Hybrid layout, local firmware conversion and fail-closed Magisk stage order.

Uses tiny fake images and regular files only; never contacts or writes a device.
"""
import contextlib
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import runpy
import shutil
import subprocess
import tempfile
import unittest
import zipfile
from unittest.mock import patch

TOP = Path(__file__).resolve().parents[2]
BUNDLE = TOP / 'openwrt/bundle'
entries = runpy.run_path(str(BUNDLE / 'install-entrypoints.py'))
finish = runpy.run_path(str(BUNDLE / 'finalize-package.py'))
firmware = runpy.run_path(str(BUNDLE / 'magisk-firmware.py'))


class Package(unittest.TestCase):
    def test_flash_bundle_builds_the_helper_as_the_packaging_user(self):
        # The build image runs as root, so a root-owned files/e5-bootctl cannot
        # be chmod(0755) by finalize() on a non-root build host (EPERM).
        script = (TOP / 'openwrt/make-flash-bundle.sh').read_text(encoding='utf-8')
        helper = script.split('docker run --rm --platform linux/arm64', 1)[1].split('/src.c', 1)[0]
        self.assertIn('--user "$(id -u):$(id -g)"', helper)
        self.assertIn('[ ! -O "$P/files/e5-bootctl" ]', script)

    def test_switcher_apk_is_in_extras_and_stale_apk_is_rejected(self):
        add = finish['add_android_switcher']
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); (root / 'docs').mkdir()
            add(root)
            self.assertEqual((root / 'extras/android/op-system-switcher.apk').read_bytes(),
                             (TOP / 'tools/switch-apk/op-system-switcher.apk').read_bytes())
            self.assertTrue((root / 'docs/ANDROID-SWITCHER.md').is_file())
            with patch.dict(add.__globals__, {'digest': lambda path: 'tampered'}):
                with self.assertRaisesRegex(ValueError, 'APK is stale'): add(root)

    def fixture(self, root, profile):
        source = root / 'source'; source.mkdir()
        for name in ('flash.py', 'part-two-stage.py', 'userdata-image.sh', 'android-loop.sh', 'README.md', 'README.zh-CN.md', 'START-HERE.md'):
            shutil.copyfile(BUNDLE / name, source / name)
        package = root / 'package with spaces'
        entries['assemble'](package, source)
        files = package / 'files'
        (files / 'boot.img').write_bytes(b'fake boot payload')
        (files / 'ext4-tools.tar').write_bytes(b'ext4 tools fixture; never executed')
        (files / 'boot.json').write_text(json.dumps({'overlay_files': 0, 'sha256': finish['digest'](files / 'boot.img')}))
        (files / 'device-profile.json').write_text(json.dumps({'profile': profile, 'android_models': [finish['MODELS'][profile]]}))
        (files / 'VERSION').write_text('hybrid fixture\n')
        with gzip.open(files / 'openwrt.ext4.gz', 'wb') as stream: stream.write(bytes(4096))
        for src, dst in [('tools/android-bootchain.sh', 'files/android-bootchain.sh'),
                         ('openwrt/bundle/collect-device-files.sh', 'files/collect-device-files.sh'),
                         ('tools/sprd-bt-config.py', 'scripts/tools/sprd-bt-config.py'),
                         ('tools/vbc-profile/vbc-profile.py', 'scripts/tools/vbc-profile/vbc-profile.py')]:
            p = package / dst; p.parent.mkdir(parents=True, exist_ok=True); shutil.copyfile(TOP / src, p)
        # An architecture fixture, deliberately never executed.
        elf = bytearray(64); elf[:6] = b'\x7fELF\x02\x01'; elf[18:20] = b'\xb7\x00'
        (root / 'bootctl').write_bytes(elf)
        # Static ARM64 ELF header fixture, deliberately never executed.
        import struct
        elf[6] = 1
        struct.pack_into('<HH', elf, 16, 2, 183)
        struct.pack_into('<Q', elf, 32, 64)
        struct.pack_into('<HH', elf, 54, 56, 1)
        (files / 'busybox').write_bytes(elf + struct.pack('<IIQQQQQQ', 1, 5, 0, 0, 0, 120, 120, 4096))
        return package

    def test_three_profiles_share_one_payload_and_keep_only_public_files_on_top(self):
        for profile in finish['MODELS']:
            with self.subTest(profile=profile), tempfile.TemporaryDirectory() as folder:
                root = Path(folder); package = self.fixture(root, profile)
                hashes = finish['finalize'](package, profile, root / 'bootctl')
                self.assertEqual({p.name for p in package.iterdir() if p.is_file()},
                                 {'OpenWrt-Installer.py', 'START-HERE.md', 'customize.sh', 'module.prop', 'skip_mount'})
                self.assertEqual(len(list(package.rglob('*.ext4.gz'))), 1)
                self.assertIn('files/busybox', hashes)
                self.assertTrue(all(p.name.isascii() for p in package.rglob('*')))
                self.assertNotIn('@MODEL@', (package / 'START-HERE.md').read_text(encoding='utf-8'))
                self.assertIn(f'ANDROID_MODEL=', (package / 'files/tf-install.env').read_text())
                self.assertEqual(hashes, {line.split(None, 1)[1]: line.split(None, 1)[0]
                                         for line in (package / 'files/SHA256SUMS').read_text().splitlines()})
                for name, expected in hashes.items(): self.assertEqual(finish['digest'](package / name), expected, name)
                result = subprocess.run([os.sys.executable, str(package / 'OpenWrt-Installer.py'), '--verify-package', '--no-pause'],
                                        cwd=root, capture_output=True, text=True, encoding='utf-8', timeout=20)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertIn('SUCCESS', result.stdout)
                zip_path=root/'fixture.zip'
                finish['write_zip'](package,zip_path)
                with zipfile.ZipFile(zip_path) as archive:
                    self.assertIn('module.prop',archive.namelist())
                    self.assertIn('customize.sh',archive.namelist())
                    self.assertEqual(len([n for n in archive.namelist() if n.endswith('.ext4.gz')]),1)
                    for name,expected in hashes.items():
                        self.assertEqual(hashlib.sha256(archive.read(name)).hexdigest(),expected,name)
                (package / 'files/boot.img').write_bytes(b'damaged')
                result = subprocess.run([os.sys.executable, str(package / 'OpenWrt-Installer.py'), '--verify-package', '--no-pause'],
                                        cwd=root, capture_output=True, text=True, encoding='utf-8', timeout=20)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('FAILED', result.stdout)

    def test_finalize_rejects_wrong_architecture_profile_and_modified_boot(self):
        for damage in ('arch', 'profile', 'boot', 'busybox', 'missing-busybox'):
            with self.subTest(damage=damage), tempfile.TemporaryDirectory() as folder:
                root = Path(folder); package = self.fixture(root, 'e5')
                if damage == 'arch': (root / 'bootctl').write_bytes(b'not ARM64')
                elif damage == 'profile': (package / 'files/device-profile.json').write_text('{}')
                elif damage == 'boot': (package / 'files/boot.img').write_bytes(b'different boot')
                elif damage == 'busybox': (package / 'files/busybox').write_bytes(b'not static ARM64')
                else: (package / 'files/busybox').unlink()
                with self.assertRaises(ValueError): finish['finalize'](package, 'e5', root / 'bootctl')
                self.assertFalse((package / 'customize.sh').exists())


class Firmware(unittest.TestCase):
    def test_native_conversion_matches_existing_tools_and_imports_unicode_hotspot(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); raw = root / 'raw'; raw.mkdir(); out = root / 'out'
            (raw / 'wcnmodem.bin').write_bytes(b'own WCN')
            (raw / 'wifi_board_config_a.ini').write_text('own board config')
            (raw / 'btmac.txt').write_text('02:11:22:33:44:55')
            (raw / 'bt_configure_pskey.xpe.ini').write_text('#[1.1]__/L=6\ndevice_addr=0,0,0,0,0,0\n')
            (raw / 'bt_configure_rf.xpe.ini').write_text('#[1.1]__/L=4\nrf=0x1234,0x5678\n')
            (raw / 'l_agdsp_a.img').write_bytes(b'SharkL5_AUD' + bytes(6291456 - len(b'SharkL5_AUD')))
            for name in ('dsp_vbc', 'audio_structure', 'cvs'):
                (raw / (name + '.xml')).write_text(f'<{name} num_mode="1" struct_size="4"><m mode="0"><x id="0" t="u32" val="0x12345678"/></m></{name}>')
            (raw / 'android-hotspot.xml').write_text('<root><string name="WifiSsid">&quot;联通&amp;测试&quot;</string><string name="Passphrase">pass&apos;word</string></root>', encoding='utf-8')
            firmware['convert'](raw, out, TOP / 'tools', 'T551M-OpenWrt')
            fw = out / 'lib/firmware'
            self.assertEqual((fw / 'sprd/marlin3lite_pskey.bin').read_bytes()[:6], bytes.fromhex('554433221102'))
            self.assertEqual((fw / 'sprd/marlin3lite_rf.bin').read_bytes()[:4], bytes.fromhex('34127856'))
            for name in ('dsp_vbc', 'audio_structure', 'cvs'):
                self.assertEqual((fw / name).read_bytes(), b'audio_profile\0\0\0' + bytes.fromhex('010000000400000078563412'))
            text = (out / 'install.conf').read_text(encoding='utf-8')
            self.assertIn('联通&测试', text)
            import shlex
            values = dict(word.split('=', 1) for word in shlex.split(text))
            self.assertEqual(values['E5_WIFI_KEY'], "pass'word")

    def test_invalid_hotspot_falls_back_without_shell_injection(self):
        import shlex
        with tempfile.TemporaryDirectory() as folder:
            raw = Path(folder)
            (raw / 'android-hotspot.xml').write_text('<root><string name="WifiSsid">bad\nname</string><string name="Passphrase">12345678</string></root>')
            values = dict(word.split('=', 1) for word in shlex.split(firmware['settings'](raw, 'M8-OpenWrt')))
            self.assertEqual(values['E5_WIFI_SSID'], 'M8-OpenWrt')
            self.assertGreaterEqual(len(values['E5_WIFI_KEY']), 8)
            self.assertEqual(values['E5_DEFAULT_BOOT'], 'linux')


@unittest.skipUnless(shutil.which('busybox'), 'native worker tests require BusyBox ash')
class NativeStages(unittest.TestCase):
    def run_script(self, code, root):
        env = dict(os.environ, E5_TF_LIB='1', STATE=str(root), P=str(root / 'package'))
        return subprocess.run(['busybox', 'ash', '-c', '. "$SOURCE"\n' + code],
                              env=dict(env, SOURCE=str(BUNDLE / 'magisk-tf-install.sh')),
                              capture_output=True, text=True, timeout=10)

    def test_any_failed_stage_prevents_later_writes_or_slot_selection(self):
        stages = ['preflight', 'prepare_firmware', 'release_card', 'write_root', 'write_boot', 'arm_linux']
        for stop in [None, *stages]:
            with self.subTest(stop=stop), tempfile.TemporaryDirectory() as folder:
                root = Path(folder)
                code = '\n'.join(name + '() { echo ' + name + ' >> "$STATE/calls"; return ' + ('1' if name == stop else '0') + '; }' for name in stages)
                result = self.run_script(code + '\ninstall_tf', root)
                expected = stages if stop is None else stages[:stages.index(stop) + 1]
                self.assertEqual((root / 'calls').read_text().splitlines(), expected)
                self.assertEqual(result.returncode, 0 if stop is None else 1)

    def test_wrong_model_slot_or_lock_state_is_rejected_before_block_operations(self):
        for model, slot, unlocked in [('T551M', '_a', 'orange'), ('E5', '_b', 'orange'), ('E5', '_a', 'green')]:
            with self.subTest(model=model, slot=slot, unlocked=unlocked), tempfile.TemporaryDirectory() as folder:
                root = Path(folder); package = root / 'package'; (package / 'files').mkdir(parents=True)
                (package / 'files/tf-install.env').write_text('ANDROID_MODEL=E5\n')
                expected = hashlib.sha256((package / 'files/tf-install.env').read_bytes()).hexdigest()
                (package / 'files/SHA256SUMS').write_text(expected + '  files/tf-install.env\n')
                code = ('id() { echo 0; }; getprop() { case "$1" in '
                        f'ro.product.model) echo {model} ;; ro.boot.slot_suffix) echo {slot} ;; '
                        f'ro.boot.verifiedbootstate) echo {unlocked} ;; esac; }}\n'
                        'blockdev() { echo unexpected > "$STATE/block-write"; return 1; }\npreflight')
                result = self.run_script(code, root)
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse((root / 'block-write').exists())

    def test_android_mount_or_mapper_holder_prevents_partition_work(self):
        for held in ('mounted', 'mapper', 'released'):
            with self.subTest(held=held), tempfile.TemporaryDirectory() as folder:
                root=Path(folder)
                sysfs=root/'sys';(sysfs/'mmcblk1p1/holders').mkdir(parents=True)
                (sysfs/'mmcblk1').mkdir()
                (sysfs/'mmcblk1/dev').write_text('179:32\n')
                (sysfs/'mmcblk1p1/dev').write_text('179:33\n')
                if held=='mapper':(sysfs/'mmcblk1p1/holders/dm-9').touch()
                (root/'mountinfo').write_text('1 2 179:33 / /mnt/card rw - vfat /dev/block/mmcblk1p1 rw\n' if held=='mounted' else '')
                source=(BUNDLE/'magisk-tf-install.sh').read_text()
                source=source.replace('/sys/class/block',str(sysfs)).replace('/proc/self/mountinfo',str(root/'mountinfo')).replace('/proc/1/mountinfo',str(root/'mountinfo'))
                script=root/'worker.sh';script.write_text(source)
                code=('export E5_TF_LIB=1; . "$WORKER"\nSD=/dev/block/mmcblk1\n'
                      'sm() { if [ "$1" = list-volumes ]; then echo "public:179,33 mounted card"; else echo "$*" >> "$STATE/events"; fi; }\n'
                      'blockdev() { echo 10000000; }\n'
                      'dd() { echo backup >> "$STATE/events"; }\nrelease_card')
                result=subprocess.run(['busybox','ash','-c',code],capture_output=True,text=True,timeout=10,
                                      env=dict(os.environ,STATE=str(root),WORKER=str(script)))
                events=(root/'events').read_text()
                self.assertIn('unmount public:179,33',events)
                self.assertEqual(result.returncode,0 if held=='released' else 1,result.stderr)
                self.assertEqual('backup' in events,held=='released')


if __name__ == '__main__': unittest.main()
