"""CLI device selection uses simulated ADB; no connected device is accessed."""
from contextlib import ExitStack, redirect_stdout
import importlib.util
import io
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

TOP=Path(__file__).resolve().parents[2]
SOURCE=TOP/'openwrt/bundle/flash.py'
E5=SOURCE.is_file()
if not E5:SOURCE=TOP/'desktop/installer.py'


class LegacyBinding(unittest.TestCase):
    def run_selection(self, explicit):
        spec=importlib.util.spec_from_file_location('selection_fixture',SOURCE)
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        with ExitStack() as stack:
            stack.enter_context(redirect_stdout(io.StringIO()))
            stack.enter_context(patch.object(sys.stdin,'isatty',return_value=True))
            stack.enter_context(patch('builtins.input',return_value='2'))
            listing='List of devices attached\nfirst\tdevice\nsecond\tdevice\n'
            if E5:
                module.SERIAL='second' if explicit else None
                stack.enter_context(patch.object(module,'adb',return_value=listing))
                stack.enter_context(patch.object(module,'ask',return_value='2'))
                stack.enter_context(patch.object(module,'package_profile',return_value={'profile':'e5','android_models':['E5']}))
                stack.enter_context(patch.object(module,'su',return_value='ok'))
                stack.enter_context(patch.object(module,'su_checked',return_value=''))
                # Device selection does not upload package tools; that boundary
                # is exercised with real shell probes in android-root-tools.py.
                stack.enter_context(patch.object(module,'android_tools'))
                def shell(cmd):
                    if cmd.endswith('-c id'):return 'uid=0(root)'
                    return {'getprop ro.product.model':'E5','getprop ro.boot.slot_suffix':'_a',
                            'getprop ro.boot.verifiedbootstate':'orange'}.get(cmd,'')
                stack.enter_context(patch.object(module,'sh',side_effect=shell))
                module.android_checks()
                self.assertEqual(module.SERIAL,'second')
            else:
                stack.enter_context(patch.object(module.Android,'call',return_value=listing.encode()))
                def shell(_,cmd,**kwargs):
                    return {'id -u':'0','getprop ro.product.model; getprop ro.product.device':'MU300\nF50',
                            'getprop ro.board.platform':'ums9620','getprop ro.boot.slot_suffix':'_a'}[cmd]
                stack.enter_context(patch.object(module.Android,'shell',shell))
                device=module.Android(SimpleNamespace(adb='fake-adb',serial='second' if explicit else None,probe=True))
                self.assertEqual(device.serial,'second')

    def test_explicit_serial_among_multiple_devices(self):self.run_selection(True)
    def test_interactive_selection_among_multiple_devices(self):self.run_selection(False)


if __name__=='__main__':unittest.main()
