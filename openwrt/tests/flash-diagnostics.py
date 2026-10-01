#!/usr/bin/env python3
"""Exercise installer failures without adb, a device or card writes."""
import contextlib
import gzip
import importlib.util
import io
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('flash', Path(__file__).parents[1] / 'bundle/flash.py')
flash = importlib.util.module_from_spec(spec)
spec.loader.exec_module(flash)


class Diagnostics(unittest.TestCase):
    def failure(self, stage, response, context='EXT4-fs: unsupported feature'):
        def remote(command, timeout=600):
            if command.startswith('dmesg'):
                if isinstance(context, Exception):
                    raise context
                return context
            return response
        error = io.StringIO()
        with patch.object(flash, 'su', remote), contextlib.redirect_stderr(error):
            with self.assertRaises(SystemExit):
                flash.su_checked(stage, 'mount /dev/card /mnt/card')
        return error.getvalue()

    def test_mount_failure_reports_stage_status_and_kernel(self):
        error = self.failure('mounting card', 'mount: Invalid argument\n__E5_STAGE_STATUS__=32\n')
        for text in ('mounting card', 'exit 32', 'Invalid argument', 'unsupported feature'):
            self.assertIn(text, error)

    def test_disconnect_not_reported_as_missing_image(self):
        error = self.failure('writing image', 'adb: device offline\n')
        self.assertIn('no completion status', error)
        self.assertIn('device offline', error)

    def test_diagnostic_timeout_does_not_hide_original_error(self):
        error = self.failure('writing image', 'dd: I/O error\n__E5_STAGE_STATUS__=1\n',
                             subprocess.TimeoutExpired('diagnostics', 20))
        self.assertIn('dd: I/O error', error)
        self.assertIn('diagnostics unavailable', error)

    def test_sequence_stops_before_later_writes(self):
        with tempfile.TemporaryDirectory() as directory:
            sentinel = Path(directory) / 'must-not-exist'
            def shell(command, timeout=600):
                if command.startswith('dmesg'):
                    return ''
                return subprocess.run(['sh', '-c', command], capture_output=True, text=True).stdout
            with patch.object(flash, 'su', shell), contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit):
                    flash.su_checked('sequence', f'false; touch "{sentinel}"')
            self.assertFalse(sentinel.exists())

    def test_vold_unmounts_only_sd_not_internal_storage(self):
        calls = []
        def checked(stage, command, timeout=600):
            calls.append(command)
            if 'list-volumes' in command:
                return 'public:179,1 mounted card\nprivate:253,0 mounted data\n'
            return ''
        with patch.object(flash, 'sd_device_numbers', return_value={'179:0', '179:1'}), \
             patch.object(flash, 'su_checked', checked):
            flash.unmount_android_sd('/dev/card')
        self.assertIn('sm unmount public:179,1', calls)
        self.assertNotIn('sm unmount private:253,0', calls)

    def test_still_mounted_aborts_before_gpt(self):
        def checked(stage, command, timeout=600):
            return '1 2 179:1 / /mnt/media_rw/card rw - vfat /dev/cardp1 rw\n' if 'mountinfo' in command else ''
        with patch.object(flash, 'sd_device_numbers', return_value={'179:1'}), \
             patch.object(flash, 'su_checked', checked), contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                flash.unmount_android_sd('/dev/card')

    def test_gzip_checks_crc_and_real_size(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'image.gz'
            path.write_bytes(gzip.compress(b'x' * 10000))
            self.assertEqual(flash.gz_usize(path), 10000)
            data = bytearray(path.read_bytes()); data[-8] ^= 1; path.write_bytes(data)
            with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                flash.gz_usize(path)


if __name__ == '__main__':
    unittest.main()
