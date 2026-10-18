#!/usr/bin/env python3
"""Verify installer extensions are composed without changing device sources."""
from pathlib import Path
import runpy
import tempfile
import unittest

TOP = Path(__file__).resolve().parents[2]
stage = runpy.run_path(str(TOP / 'boot/stage-installer.py'))['stage']


class InstallerRuntime(unittest.TestCase):
    def test_both_systems_keep_partition_trial_confirmation(self):
        for system, name in [('openwrt', 'etc/init.d/e5-boot-ok'),
                             ('debian', 'usr/local/sbin/e5-boot-ok')]:
            with self.subTest(system=system), tempfile.TemporaryDirectory() as folder:
                root = Path(folder)
                stage(root, system)
                script = root / name
                self.assertIn('rm -f /etc/e5/part-trial', script.read_text())
                self.assertTrue(script.stat().st_mode & 0o111)
                if system == 'openwrt':
                    self.assertIn("cmd == 'carve-userdata'", (root / 'usr/libexec/e5-gpt').read_text())
                before = script.read_bytes()
                stage(root, system)
                self.assertEqual(script.read_bytes(), before)

    def test_host_root_and_unknown_system_are_rejected(self):
        with self.assertRaises(ValueError):
            stage('/', 'openwrt')
        with tempfile.TemporaryDirectory() as folder, self.assertRaises(ValueError):
            stage(folder, '../outside')


if __name__ == '__main__':
    unittest.main()
