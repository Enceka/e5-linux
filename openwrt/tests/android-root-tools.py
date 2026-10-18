#!/usr/bin/env python3
"""Bundled tools: ELF checks, upload proof and standalone ash, no devices."""
import contextlib
import importlib.util
import io
import os
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('flash', Path(__file__).parents[1]/'bundle/flash.py')
flash = importlib.util.module_from_spec(spec)
spec.loader.exec_module(flash)


class RootTools(unittest.TestCase):
    def test_reject_dynamic_wrong_arch_and_truncated_elf(self):
        with tempfile.TemporaryDirectory() as folder:
            p = Path(folder)/'busybox'
            header = bytearray(64); header[:7] = b'\x7fELF\x02\x01\x01'
            struct.pack_into('<HH', header, 16, 2, 183)
            struct.pack_into('<Q', header, 32, 64)
            struct.pack_into('<HH', header, 54, 56, 1)
            load = struct.pack('<IIQQQQQQ', 1, 5, 0, 0, 0, 120, 120, 4096)
            p.write_bytes(header + load)
            flash.validate_installer_busybox(p)
            for kind in (2, 3):
                p.write_bytes(header + struct.pack('<I', kind) + load[4:])
                with self.assertRaises(ValueError): flash.validate_installer_busybox(p)
            for offset, value in ((18, 62), (4, 1), (54, 8)):
                bad = bytearray(header + load); bad[offset] = value; p.write_bytes(bad)
                with self.assertRaises(ValueError): flash.validate_installer_busybox(p)
            p.write_bytes(header + load[:8])
            with self.assertRaises(ValueError): flash.validate_installer_busybox(p)

    def test_missing_tool_stops_before_any_upload(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(flash, 'F', folder), \
                patch.object(flash, 'ANDROID_BUSYBOX', None), patch.object(flash, 'adb') as adb, \
                contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit): flash.android_tools()
            adb.assert_not_called()
            with self.assertRaises(ValueError): flash.android_shell('/installer.sh')

    def test_actual_staging_and_probe_without_manager_paths(self):
        bb = shutil.which('busybox')
        if not bb: self.skipTest('Linux BusyBox required')
        for fault in ('none', 'corrupt', 'missing-applet'):
            with self.subTest(fault=fault), tempfile.TemporaryDirectory() as folder:
                root=Path(folder); files=root/'files'; files.mkdir(); shutil.copyfile(bb, files/'busybox')
                calls=[]
                def adb(*args, **kwargs):
                    calls.append(args)
                    if args[0] == 'push':
                        shutil.copyfile(args[1], args[2])
                        if fault == 'corrupt':
                            with open(args[2], 'ab') as stream: stream.write(b'corruption')
                        return ''
                    self.assertEqual(args[0], 'shell')
                    command=args[1]
                    if fault == 'missing-applet': command=command.replace('for tool in sh ', 'for tool in no_such_applet sh ')
                    # Ownership changes need no root in this disposable fixture.
                    r=subprocess.run(['sh','-c','chown(){ :; }; '+command],capture_output=True,text=True)
                    if kwargs.get('check') and r.returncode: raise RuntimeError(r.stderr)
                    return r.stdout
                with patch.object(flash, 'F', str(files)), patch.object(flash, 'TMP', str(root)), \
                        patch.object(flash, 'SU', None), patch.object(flash, 'ANDROID_BUSYBOX', None), \
                        patch.object(flash, 'validate_installer_busybox'), patch.object(flash, 'adb', side_effect=adb), \
                        contextlib.redirect_stderr(io.StringIO()):
                    if fault == 'none':
                        flash.android_tools()
                        self.assertTrue(flash.ANDROID_BUSYBOX.endswith('/busybox'))
                        # Exercise both shell layers, including quotes.
                        flash.SU='sh'
                        self.assertEqual(flash.su('printf "%s" "a\'b"'), "a'b")
                    else:
                        with self.assertRaises(SystemExit): flash.android_tools()
                        self.assertIsNone(flash.ANDROID_BUSYBOX)
                self.assertFalse(any('/data/adb/' in str(c) for c in calls))

    def test_native_entry_uses_own_tools_and_stops_on_missing_applet(self):
        bb = shutil.which('busybox')
        if not bb: self.skipTest('Linux BusyBox required')
        for broken in (False, True):
            with self.subTest(broken=broken), tempfile.TemporaryDirectory() as folder:
                root = Path(folder)/'package with spaces'; files=root/'files'; files.mkdir(parents=True)
                (files/'busybox').write_text('''#!/bin/sh
case "$1" in
    timeout) shift 4; exec "$@";;
    nsenter) shift 4; exec "$@";;
    --list) if [ "$BROKEN" = 1 ]; then "$HOST_BB" --list | "$HOST_BB" grep -vx nsenter; exit; fi;;
esac
exec "$HOST_BB" "$@"
''')
                (files/'magisk-tf-install.sh').write_text('''#!/bin/sh
[ "$E5_PACKAGE" = "$MODPATH" ] || exit 1
echo reached > "$MODPATH/worker-reached"
''')
                (files/'e5-bootctl').touch()
                source=Path(__file__).parents[1]/'bundle/magisk-customize.sh'
                env=dict(os.environ, MODPATH=str(root), HOST_BB=bb, BOOTMODE='true', BROKEN=str(int(broken)), SOURCE=str(source))
                result=subprocess.run(['sh','-c','uname(){ echo aarch64; }; abort(){ echo "$*" >&2; exit 1; }; ui_print(){ :; }; . "$SOURCE"'],
                                      env=env,capture_output=True,text=True,timeout=10)
                self.assertEqual(result.returncode, 1 if broken else 0, result.stderr)
                self.assertEqual((root/'worker-reached').exists(), not broken)
                self.assertEqual((root/'disable').exists(), not broken)


if __name__ == '__main__':
    unittest.main()
