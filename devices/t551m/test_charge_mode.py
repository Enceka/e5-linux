"""Run on Linux: charge-only boot boundaries, keys and display restoration."""
import importlib.util
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, call, patch

spec = importlib.util.spec_from_file_location('charge', Path(__file__).with_name('charge-mode.py'))
charge = importlib.util.module_from_spec(spec)
spec.loader.exec_module(charge)
read_boot_policy = charge.power_on_supply


class ChargeModeTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.args = self.file('firmware/devicetree/base/chosen/bootargs',
                              'modem=shutdown sprdboot.mode=charger\0')
        self.bl = self.file('class/backlight/panel/brightness', '180\n')
        self.touch = self.file('class/input/event1/device/inhibited', '0\n')
        self.file('class/input/event0/device/capabilities/key', '1c000000000000 2000000000000000')
        self.file('class/input/event0/device/capabilities/abs', '0')
        self.file('class/input/event1/device/capabilities/key', '400 0 0 100040000800 0 0')
        self.file('class/input/event1/device/capabilities/abs', '265800002000003')
        self.file('class/power_supply/battery/type', 'Battery')
        self.file('class/power_supply/battery/online', '1')
        self.file('class/power_supply/usb/type', 'USB')
        self.usb = self.file('class/power_supply/usb/online', '1')
        self.sys = patch.object(charge, 'SYS', self.root)
        self.state = patch.object(charge, 'STATE', self.root / 'state.json')
        self.display = patch.object(charge, 'open_display', return_value=None)
        self.boot_policy = patch.object(charge, 'power_on_supply', return_value=False)
        self.sys.start()
        self.state.start()
        self.display.start()
        self.boot_policy.start()

    def tearDown(self):
        self.sys.stop()
        self.state.stop()
        self.display.stop()
        self.boot_policy.stop()
        self.temp.cleanup()

    def file(self, name, value):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(value)
        return path

    def test_mode_matching_and_normal_boot_bypass(self):
        for args in ['sprdboot.mode=normal', 'androidboot.mode=normal',
                     'sprdboot.mode=charger_extra', 'xandroidboot.mode=charger', '']:
            self.assertFalse(charge.charger_boot(args))
        self.assertTrue(charge.charger_boot('androidboot.mode=charger\0'))
        self.args.write_text('sprdboot.mode=normal\0')
        with patch.object(charge, 'wait_for_power') as wait:
            charge.run()
        wait.assert_not_called()
        self.assertEqual(self.bl.read_text(), '180\n')

    def test_enabled_supply_boot_does_not_start_charging_ui_or_wait_for_keys(self):
        with patch.object(charge, 'power_on_supply', return_value=True), \
             patch.object(charge, 'wait_for_power') as wait:
            charge.run()
        wait.assert_not_called()
        self.assertEqual(self.bl.read_text(), '180\n')
        self.assertEqual(self.touch.read_text(), '0\n')
        self.assertIn('power-on-supply enabled', (self.root/'state.json').read_text())

    def test_missing_or_invalid_boot_option_keeps_charging_mode(self):
        for rc, value, expected in ((0,'1\n',True),(0,'0\n',False),(0,'yes',False),(1,'1',False)):
            with patch.object(charge.subprocess, 'run', return_value=subprocess.CompletedProcess([],rc,value,'')):
                self.assertEqual(read_boot_policy(), expected)

    def test_capabilities_find_power_and_touch_without_model_names(self):
        keys, touches = charge.input_devices()
        self.assertEqual(keys, [Path('/dev/input/event0')])
        self.assertEqual(touches, [self.touch])

    def test_battery_online_is_not_a_cable(self):
        self.assertTrue(charge.cable_online())
        self.usb.write_text('0')
        self.assertFalse(charge.cable_online())
        self.usb.unlink()
        self.assertIsNone(charge.cable_online())

    def test_short_press_and_repeat_do_not_unlock(self):
        held = charge.PowerHold()
        held.event(0, 1, 116, 1, 10)
        held.event(0, 1, 116, 0, 10.4)
        self.assertFalse(held.ready(20))
        held.event(0, 1, 115, 1, 20)  # volume is not power
        self.assertFalse(held.ready(25))
        held.event(0, 1, 116, 1, 30)
        held.event(0, 1, 116, 2, 31)
        self.assertFalse(held.ready(31.4))
        self.assertTrue(held.ready(31.5))
        held.event(0, 0, 3, 0, 31.6)
        self.assertFalse(held.ready(40))

    def test_charge_black_touch_off_then_restore_user_preference(self):
        for allowed in ['1', '0']:
            self.bl.write_text('180\n')
            self.touch.write_text('0\n')
            def wait(keys, display=None):
                self.assertEqual(self.bl.read_text(), '0\n')
                self.assertEqual(self.touch.read_text(), '1\n')
                return 'power-key'
            with patch.object(charge, 'wait_for_power', side_effect=wait), \
                    patch.object(charge.subprocess, 'run', return_value=
                                 subprocess.CompletedProcess([], 0, stdout=allowed)):
                charge.run()
            self.assertEqual(self.bl.read_text(), '180\n')
            self.assertEqual(self.touch.read_text(), '0\n' if allowed == '1' else '1\n')

    def test_input_failure_restores_display_for_recovery(self):
        with patch.object(charge, 'wait_for_power', side_effect=OSError('lost key')), \
                patch.object(charge.subprocess, 'run', return_value=
                             subprocess.CompletedProcess([], 0, stdout='1')):
            with self.assertRaises(OSError):
                charge.run()
        self.assertEqual(self.bl.read_text(), '180\n')
        self.assertEqual(self.touch.read_text(), '0\n')

    def test_cable_removal_powers_off_without_resuming_startup(self):
        display = Mock()
        def command(args, **kwargs):
            # All shutdown commands run only after the UI has been closed.
            display.close.assert_called_once()
            self.assertEqual(self.bl.read_text(), '0\n')
            self.assertEqual(self.touch.read_text(), '1\n')
        with patch.object(charge, 'wait_for_power', return_value='cable-removed'), \
                patch.object(charge, 'open_display', return_value=display), \
                patch.object(Path, 'is_mount', return_value=True), \
                patch.object(charge.subprocess, 'run', side_effect=command) as run, \
                patch.object(charge.time, 'sleep', side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                charge.run()
        self.assertEqual(run.call_args_list, [call(args, check=True, timeout=5) for args in [
            ['/opt/e5/e5-next-boot', '--rearm'], ['/bin/sync'],
            ['/bin/mount', '-o', 'remount,ro', '/'],
            ['/bin/mount', '-o', 'remount,ro', '/mnt/e5-data'], ['/bin/sync'],
            ['/sbin/poweroff', '-f']]])
        self.assertEqual(self.bl.read_text(), '0\n')
        self.assertEqual(self.touch.read_text(), '1\n')

    def test_shutdown_failures_retry_and_never_restore_normal_boot(self):
        for failure in [OSError('unavailable'),
                        subprocess.CalledProcessError(1, 'shutdown'),
                        subprocess.TimeoutExpired('shutdown', 5)]:
            display = Mock()
            display.close.side_effect = OSError('lost framebuffer')
            with patch.object(charge, 'wait_for_power', return_value='cable-removed'), \
                    patch.object(charge, 'open_display', return_value=display), \
                    patch.object(Path, 'is_mount', return_value=False), \
                    patch.object(charge.subprocess, 'run', side_effect=failure) as run, \
                    patch.object(charge.time, 'sleep', side_effect=[None, KeyboardInterrupt]):
                with self.assertRaises(KeyboardInterrupt):
                    charge.run()
            commands = [c.args[0] for c in run.call_args_list]
            self.assertEqual(commands.count(['/sbin/poweroff', '-f']), 2)
            self.assertNotIn(['/sbin/poweroff'], commands)
            self.assertNotIn('uci', [c[0] for c in commands])
            self.assertEqual(self.bl.read_text(), '0\n')
            self.assertEqual(self.touch.read_text(), '1\n')
            self.assertIn('"state": "poweroff"', (self.root / 'state.json').read_text())

    def test_cable_disconnect_requires_half_second_and_resets_on_unknown(self):
        with patch.object(charge.os, 'open', return_value=10), \
                patch.object(charge.os, 'close') as close, \
                patch.object(charge, 'power_is_down', return_value=False), \
                patch.object(charge.select, 'select', return_value=([], [], [])), \
                patch.object(charge.time, 'monotonic', side_effect=
                             [0, .3, .4, .5, .8, .9, 1., 1.3, 1.5]), \
                patch.object(charge, 'cable_online', side_effect=
                             [False, False, True, False, False, None,
                              False, False, False]) as cable:
            self.assertEqual(charge.wait_for_power([Path('/dev/input/event0')]), 'cable-removed')
        self.assertEqual(cable.call_count, 9)
        close.assert_called_once_with(10)


if __name__ == '__main__':
    unittest.main()
