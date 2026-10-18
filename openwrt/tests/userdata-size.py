#!/usr/bin/env python3
"""Validate capacity limits and failure ordering without writing a device."""
import contextlib
import importlib.util
import io
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('flash', Path(__file__).parents[1] / 'bundle/flash.py')
flash = importlib.util.module_from_spec(spec)
spec.loader.exec_module(flash)
GIB = 1 << 30


class Userdata(unittest.TestCase):
    def test_hotspot_default_matches_package_model(self):
        for profile, ssid in (('e5', 'E5-OpenWrt'), ('t551m', 'T551M-OpenWrt'), ('m8', 'M8-OpenWrt')):
            with self.subTest(profile=profile), patch.object(flash, 'package_profile', return_value={'profile': profile}):
                self.assertEqual(flash.default_hotspot_name(), ssid)
        with patch.object(flash, 'package_profile', return_value=None):
            self.assertEqual(flash.default_hotspot_name(), 'E5-OpenWrt')

    def select(self, value, free=12 * GIB, y=True):
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            return flash.choose_userdata_size(SimpleNamespace(image_size=value, y=y), 2 * GIB, free, 256 << 20)

    def test_fractional_and_minimum(self):
        self.assertEqual(self.select('6.5'), 13 * GIB // 2)
        self.assertEqual(self.select(None), 2 * GIB)
        with patch.object(flash, 'ask', return_value='4') as ask:
            self.assertEqual(self.select(None, y=False), 4 * GIB)
            ask.assert_called_once()

    def test_invalid_and_insufficient(self):
        for value in ('0', '-1', 'nan', 'Infinity', 'oops', '1.99', '12', '1e1000'):
            with self.subTest(value=value), self.assertRaises(SystemExit):
                self.select(value)
        with self.assertRaises(SystemExit):
            self.select(None, free=3 * GIB)

    def test_space_recheck_does_not_count_existing_images(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            flash.ensure_userdata_space(4 * GIB, 5 * GIB, 0)
        flash.ensure_userdata_space(4 * GIB, 6 * GIB, 0)

    def test_large_images_pass_mib_arithmetic_to_android(self):
        for gib in (2, 4, 6.5, 10, 15):
            selected = int(gib * GIB)
            with self.subTest(gib=gib), patch.object(flash, 'push'), patch.object(flash, 'su_checked') as checked:
                flash.stage_userdata_image(2 * GIB, selected)
                command = checked.call_args.args[1]
                self.assertEqual(command.split()[-4:],
                                 [str(2 * GIB), str(selected), '2048', str(selected // (1 << 20))])
        with patch.object(flash, 'push') as upload, self.assertRaises(SystemExit):
            flash.stage_userdata_image(2 * GIB, 2 * GIB + 1)
        upload.assert_not_called()

    def test_resize_failure_never_syncs_chain_or_writes_boot(self):
        args = SimpleNamespace(apn='', ssid='test', wifi_key='12345678', y=True, image_size='4')
        calls = []
        def checked(stage, cmd, timeout=600):
            calls.append(cmd)
            return ''
        replacements = {
            'find_adb': lambda: None, 'android_checks': lambda: None,
            'check_userdata_image_source': lambda: None,
            'install_preflight': lambda: None, 'boot_json': lambda: {'sha256': 'abc'},
            'gz_usize': lambda _: 2 * GIB, 'userdata_free': lambda: 12 * GIB,
            'pull_device_files': lambda *args: 1024, 'push': lambda *args: None,
            'su_checked': checked,
            'stage_userdata_image': lambda *args: (_ for _ in ()).throw(SystemExit('resize failure')),
        }
        with contextlib.ExitStack() as stack:
            for name, fn in replacements.items():
                stack.enter_context(patch.object(flash, name, fn))
            stack.enter_context(patch.object(flash.os.path, 'getsize', return_value=1 << 20))
            stack.enter_context(patch.object(flash.os.path, 'isfile', return_value=True))
            chain = stack.enter_context(patch.object(flash, 'bootchain'))
            arm = stack.enter_context(patch.object(flash, 'arm_slot_b'))
            stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
            with self.assertRaises(SystemExit):
                flash.install(args)
            chain.assert_not_called()
            arm.assert_not_called()
            self.assertFalse(any('of=/dev/block/by-name/boot_b' in c or 'mv ' in c for c in calls))


if __name__ == '__main__':
    unittest.main()
