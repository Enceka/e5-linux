#!/usr/bin/env python3
"""Boot switching must never inspect/mount roots or change permanent settings."""
import contextlib
import importlib.util
from pathlib import Path
import unittest
import sys
from unittest.mock import patch

TOP = Path(__file__).resolve().parents[2]
sys.path.insert(0,str(TOP/'installer/tests'))
from test_boot_switch import fixture
spec = importlib.util.spec_from_file_location('flash', TOP / 'openwrt/bundle/flash.py')
flash = importlib.util.module_from_spec(spec); spec.loader.exec_module(flash)


class Switch(unittest.TestCase):
    def run_switch(self, command, chain_error=False):
        header,tail,size=fixture(command)
        with contextlib.ExitStack() as stack:
            for name in ('find_adb','android_checks','steps','say'):
                stack.enter_context(patch.object(flash,name))
            stack.enter_context(patch.object(flash,'device_size',return_value=size))
            stack.enter_context(patch.object(flash,'boot_json',side_effect=AssertionError('must not require current package boot hash')))
            read=stack.enter_context(patch.object(flash,'su',side_effect=[header.hex(),tail.hex()]))
            chain=stack.enter_context(patch.object(flash,'bootchain'))
            if chain_error:chain.side_effect=RuntimeError('boot chain mismatch')
            stack.enter_context(patch.object(flash,'su_checked',side_effect=AssertionError('unexpected root write/mount')))
            arm=stack.enter_context(patch.object(flash,'arm_slot_b'))
            adb=stack.enter_context(patch.object(flash,'adb'))
            if 'e5.part_v=2' not in command:
                with self.assertRaises(ValueError):flash.boot_openwrt(None)
                chain.assert_not_called();arm.assert_not_called();adb.assert_not_called()
            elif chain_error:
                with self.assertRaisesRegex(RuntimeError,'boot chain mismatch'):flash.boot_openwrt(None)
                arm.assert_not_called();adb.assert_not_called()
            else:
                flash.boot_openwrt(None)
                chain.assert_called_once_with('check');arm.assert_called_once_with();adb.assert_called_once_with('reboot')
            self.assertEqual(read.call_count,2)
            self.assertTrue(all('if=/dev/block/by-name/boot_b' in call.args[0] and 'of=' not in call.args[0] for call in read.call_args_list))

    def test_installed_release_and_partition_override_need_no_root_access(self):
        for command in ('loglevel=5 e5.part_v=2','loglevel=7 e5.part_v=2 e5.root=part','androidboot.hardware=stock'):
            with self.subTest(command=command):self.run_switch(command)

    def test_boot_chain_check_failure_never_arms_or_reboots(self):
        self.run_switch('e5.part_v=2',chain_error=True)


if __name__ == '__main__': unittest.main()
