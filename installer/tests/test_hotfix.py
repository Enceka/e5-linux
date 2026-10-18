"""Host overlay checks operate on temporary files and never connect to devices."""
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from apply_hotfix import apply, digest


class Hotfix(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        for name in ('tools/installer-hotfix','desktop','payload','tools/backend'):(self.root/name).mkdir(parents=True,exist_ok=True)
        for name in ('payload/mu300-openwrt.tar.gz','payload/boot-linux.img','desktop/boot_image.py','tools/backend/obsolete.dll'):
            (self.root/name).write_bytes(('original '+name).encode())
        self.manifest={'format':2,'kernel':'7.2','magisk':{n:digest(self.root/n) for n in ('payload/mu300-openwrt.tar.gz','payload/boot-linux.img')},
                       'desktop':{n:digest(self.root/n) for n in ('desktop/boot_image.py','tools/backend/obsolete.dll')}}
        self.path=self.root/'desktop/manifest.json'
        self.path.write_text(json.dumps(self.manifest))
        files={}
        for name in ('OpenWrt-Installer.exe','OpenWrt-Installer.py','desktop/installer.py','desktop/update_control.py','tools/backend/openwrt-backend.exe'):
            (self.root/name).write_bytes(('new '+name).encode());files[name]=digest(self.root/name)
        self.metadata=self.root/'tools/installer-hotfix/patch.json'
        self.patch={'format':1,'id':'20261016-220000-mu300-windows','files':files}
        self.metadata.write_text(json.dumps(self.patch))

    def run_patch(self):
        with redirect_stdout(io.StringIO()):return apply(self.root)

    def test_apply_and_retry_preserve_firmware_and_update_only_host_hashes(self):
        before=(self.root/'payload/mu300-openwrt.tar.gz').read_bytes()
        self.run_patch();self.run_patch()
        updated=json.loads(self.path.read_text())
        self.assertEqual(updated['magisk'],self.manifest['magisk'])
        self.assertEqual((self.root/'payload/mu300-openwrt.tar.gz').read_bytes(),before)
        self.assertEqual(updated['source']['installer.py'],digest(self.root/'desktop/installer.py'))
        self.assertFalse((self.root/'tools/backend/obsolete.dll').exists())
        for name,wanted in {**updated['magisk'],**updated['desktop']}.items():self.assertEqual(digest(self.root/name),wanted)

    def test_corrupt_patch_payload_and_original_host_file_do_not_change_manifest(self):
        for name in ('OpenWrt-Installer.exe','payload/boot-linux.img','desktop/boot_image.py'):
            with self.subTest(name=name):
                path=self.root/name;original=path.read_bytes();before=self.path.read_bytes()
                path.write_bytes(b'changed')
                with self.assertRaises(ValueError):self.run_patch()
                self.assertEqual(self.path.read_bytes(),before)
                path.write_bytes(original)

    def test_firmware_entries_and_escaping_paths_are_refused(self):
        for name in ('payload/boot-linux.img','tools/backend/../../../outside'):
            with self.subTest(name=name):
                self.patch['files'][name]='0'*64
                self.metadata.write_text(json.dumps(self.patch))
                before=self.path.read_bytes()
                with self.assertRaises(ValueError):self.run_patch()
                self.assertEqual(self.path.read_bytes(),before)
                self.patch['files'].pop(name)

    def test_retry_after_old_runtime_file_was_already_removed(self):
        (self.root/'tools/backend/obsolete.dll').unlink()
        self.run_patch()
        self.assertNotIn('tools/backend/obsolete.dll',json.loads(self.path.read_text())['desktop'])


if __name__=='__main__':unittest.main()
