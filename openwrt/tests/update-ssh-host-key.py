#!/usr/bin/env python3
"""USB update connections must not inherit a key pin from another device."""
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

TOP = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('update_ssh', TOP / 'tools/e5-update.py')
update = importlib.util.module_from_spec(spec)
spec.loader.exec_module(update)


@unittest.skipUnless(importlib.util.find_spec('paramiko'), 'SSH tests need Paramiko')
class HostKeys(unittest.TestCase):
    def test_preflight_ignores_stale_profile_cache_without_writing_it(self):
        import paramiko
        with tempfile.TemporaryDirectory() as temp:
            package = Path(temp)
            (package / 'files').mkdir()
            (package / 'files/device-profile.json').write_text(json.dumps({'profile': 'e5'}))
            (package / 'files/boot.json').write_text('{}')
            (package / 'backups').mkdir()
            cache = package / 'backups/ssh-e5.known_hosts'
            cache.write_text('stale key for another E5 at the same USB IP\n')
            client = Mock()
            args = ['update', '--package', str(package), '--host', '192.168.9.1',
                    '--raw-size', '4096', '--raw-sha256', '0' * 64, '--check-only']
            with patch.object(sys, 'argv', args), \
                 patch.dict(os.environ, {'E5_TELNET_PASS': 'test-only'}), \
                 patch.object(paramiko, 'SSHClient', return_value=client), \
                 patch.object(update, 'image_capacity', return_value=4096) as capacity, \
                 patch.object(update, 'execute', side_effect=['', 'image']):
                update.main()
            capacity.assert_called_once_with(client)
            self.assertIsInstance(client.set_missing_host_key_policy.call_args.args[0], paramiko.AutoAddPolicy)
            client.load_host_keys.assert_not_called()
            client.load_system_host_keys.assert_not_called()
            client.save_host_keys.assert_not_called()
            client.close.assert_called_once()
            self.assertEqual(cache.read_text(), 'stale key for another E5 at the same USB IP\n')


if __name__ == '__main__':
    unittest.main()
