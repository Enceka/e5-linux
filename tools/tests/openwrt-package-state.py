#!/usr/bin/env python3
"""Reject legacy APKs, source drift and changed binaries before image assembly."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

TOP = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('package_state', TOP / 'tools/openwrt-package-state.py')
package = importlib.util.module_from_spec(spec)
spec.loader.exec_module(package)


class PackageState(unittest.TestCase):
    def test_apk_and_source_changes_make_the_record_different(self):
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory)
            daemon = out / 'modemmanager-1.24.0-r914.apk'; daemon.write_bytes(b'daemon build A')
            rpc = out / 'modemmanager-rpcd-1.24.0-r914.apk'; rpc.write_bytes(b'RPC build A')
            with patch.object(package, 'OUT', out), patch.object(package, 'sources', return_value={'patch': 'A'}):
                saved = package.inspect('25.12.5')
                daemon.write_bytes(b'old daemon copied into new build')
                self.assertNotEqual(package.inspect('25.12.5'), saved)
                daemon.write_bytes(b'daemon build A')
                self.assertEqual(package.inspect('25.12.5'), saved)
            with patch.object(package, 'OUT', out), patch.object(package, 'sources', return_value={'patch': 'B'}):
                self.assertNotEqual(package.inspect('25.12.5'), saved)

    def test_missing_required_package_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory)
            (out / 'modemmanager-rpcd-1.24.0-r914.apk').write_bytes(b'RPC only')
            with patch.object(package, 'OUT', out), self.assertRaises(ValueError):
                package.inspect('25.12.5')


if __name__ == '__main__':
    unittest.main()
