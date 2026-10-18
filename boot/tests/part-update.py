#!/usr/bin/env python3
"""Exercise the actual offline updater on regular sparse files, never devices."""
import gzip
import hashlib
import io
import os
from pathlib import Path
import subprocess
import tarfile
import tempfile
import unittest

TOP = Path(__file__).resolve().parents[2]
SOURCE = (TOP / 'boot/part-update.sh').read_text()


def archive(path, files):
    with tarfile.open(path, 'w') as tar:
        for name, value in files.items():
            member = tarfile.TarInfo(name); member.size = len(value); member.mode = 0o755
            tar.addfile(member, io.BytesIO(value))


class OfflineUpdate(unittest.TestCase):
    def exercise(self, fault='ok', kind='part', raw_card=False):
        with tempfile.TemporaryDirectory(prefix='e5-offline-update-') as folder:
            root = Path(folder)
            old = root / 'old'; new = root / 'new'; ram = root / 'run'
            pending = old / '.e5-update'; pending.mkdir(parents=True)
            (old / 'etc/e5').mkdir(parents=True)
            (old / 'etc/e5/part-root').write_text('e5root /dev/mmcblk0\n')
            (old / 'etc/e5/device-profile').write_text('t551m\n')
            if kind == 'sd':
                (old / 'etc/e5/part-root').unlink()
                (old / 'etc/e5/sd-root').write_text('e5-openwrt-sd\n')
            base = root / 'base'; (base / 'etc/e5').mkdir(parents=True)
            (base / 'etc/e5-infoscreen/plugins/phone').mkdir(parents=True)
            (base / 'etc/e5-infoscreen/plugins/phone/phone.js').write_text('new phone code')
            (base / 'etc/e5/device-profile').write_text('t551m\n')
            (base / 'etc/e5/image-version').write_text('new release\n')
            (base / 'sbin').mkdir(); (base / 'sbin/init').write_text('#!/bin/sh\n'); (base / 'sbin/init').chmod(0o755)
            image = root / 'image'
            subprocess.run(['mke2fs','-q','-t','ext4','-b','4096','-d',str(base),str(image),'64M'],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            raw = image.read_bytes()
            (pending / 'openwrt.ext4.gz').write_bytes(gzip.compress(raw,compresslevel=1))
            archive(pending / 'firmware.tar', {'lib/firmware/wcnmodem.bin':b'own firmware',
                'opt/e5/android/vendor/bin/modem_control':b'#!/bin/sh\n'})
            archive(pending / 'settings.tar', {'etc/config/wireless':'自己的热点'.encode(),
                **({'etc/e5/sd-root':b'e5-openwrt-sd\n', 'etc/e5/sd-gen':b'7\n'} if kind == 'sd' else {}),
                'etc/e5/image-version':b'OLD release', 'etc/e5/device-profile':b't551m\n',
                'etc/e5-infoscreen/plugins/phone/phone.js':b'old phone code',
                'etc/shadow':b'root:saved-password-hash:\n'})
            archive(pending / 'ext4-tools.tar', {'lib/ld-musl-aarch64.so.1':b'#!/bin/sh\nshift 3\nexec /usr/sbin/e2fsck "$@"\n',
                'usr/sbin/e2fsck':b'placeholder'})
            hashes = ''.join(hashlib.sha256((pending/n).read_bytes()).hexdigest()+'  '+n+'\n'
                for n in ('openwrt.ext4.gz','firmware.tar','settings.tar','ext4-tools.tar'))
            (pending / 'SHA256SUMS').write_text(hashes)
            cid = 'b'*32
            (pending / 'request').write_text(f'VERSION=1\n'+('KIND=sd\n' if kind == 'sd' else '')+f'CID={cid}\nROOT_BYTES={96<<20}\nRAW_BYTES={len(raw)}\nRAW_SHA256={hashlib.sha256(raw).hexdigest()}\nPROFILE=t551m\n')
            name = ('mmcblk1' if raw_card else 'mmcblk1p1') if kind == 'sd' else 'mmcblk0p71'
            disk = name.split('p')[0]
            device = root / 'dev' / name; device.parent.mkdir()
            with device.open('wb') as stream: stream.truncate(96<<20)
            for path, content in (
                (f'sys/class/block/{name}/uevent','PARTNAME=old-card\n' if kind == 'sd' else 'PARTNAME=e5root\n'),
                (f'sys/class/block/{name}/dev','179:71\n'),
                (f'sys/class/block/{disk}/device/cid',cid+'\n'),
                (f'sys/class/block/{disk}/device/type', 'SD\n' if kind == 'sd' and fault != 'emmc' else 'MMC\n'),
                ('proc/cmdline','e5.root=part e5.part_update=1\n'),
                ('proc/meminfo','MemAvailable: 1000000 kB\n'),
                ('proc/self/mountinfo',''),
            ):
                path = root / path; path.parent.mkdir(parents=True,exist_ok=True); path.write_text(content)
            if fault == 'cid': (root / f'sys/class/block/{disk}/device/cid').write_text('wrong')
            if fault == 'ram': (root / 'proc/meminfo').write_text('MemAvailable: 100 kB\n')
            if fault == 'busy': (root / 'proc/self/mountinfo').write_text('1 2 179:71 / /old rw - ext4 device rw\n')
            if fault == 'corrupt': (pending / 'firmware.tar').write_bytes(b'corrupt')
            ram.mkdir(); (ram/'part-update-pending').write_text(str(device)+'\n')
            new.mkdir(); mountpoint = root / 'mounted-old'; mountpoint.mkdir()
            (root / 'bc').write_bytes(b'boot-control')
            progress = (TOP / 'boot/part-progress.sh').read_text()
            grow = progress[progress.index('part_grow_ext4()'):].replace('/run/',str(ram)+'/')
            helpers = root / 'helpers'
            helpers.write_text('part_progress_start() { :; }; part_stop() { :; }; part_fail() { echo "FAIL $*"; return 1; };\n'+
                ('part_grow_ext4() { return 1; }\n' if fault == 'grow' else grow))
            code = SOURCE
            for a,b in (('/part-update-old',str(mountpoint)),('/part-update-new',str(new)),('/run/',str(ram)+'/'),
                ('/proc/',str(root / 'proc')+'/'),('/sys/',str(root / 'sys')+'/'),('/dev/',str(root / 'dev')+'/'),
                ('/etc/part-progress.sh',str(helpers)),('/etc/misc-bc-slot-b-trial.bin',str(root / 'bc'))):
                code = code.replace(a,b)
            harness = f'''
mount() {{ for dest; do :; done; if [ "$dest" = "{mountpoint}" ]; then cp -a "{old}/." "$dest/"; else debugfs -R "rdump / $dest" "{device}" >/dev/null 2>&1; fi; }}
umount() {{ echo "unmount $1" >> "{root}/calls"; {'[ "$1" != "'+str(new)+'" ] || printf corrupt > "'+str(new)+'/lib/firmware/wcnmodem.bin";' if fault == 'readback' else ':;'} }}
blockdev() {{ [ "$1" != --getsize64 ] || echo {96<<20}; }}
dd() {{ echo WRITE >> "{root}/calls"; {'return 1;' if fault == 'write' else 'command dd "$@";'} }}
log() {{ echo "$*"; }}
write_misc_bc() {{ cp "{root}/bc" "{ram}/bc.bin"; }}
reboot() {{ echo REBOOT >> "{root}/calls"; }}
'''+code+'\npart_update_pending\n'
            result = subprocess.run(['busybox','ash'],input=harness,text=True,capture_output=True,timeout=30)
            calls = (root/'calls').read_text() if (root/'calls').exists() else ''
            if fault == 'ok':
                self.assertEqual(result.returncode,0,result.stdout+result.stderr)
                self.assertLess(calls.index('unmount '+str(mountpoint)),calls.index('WRITE'))
                self.assertIn('REBOOT',calls)
                self.assertEqual((new/'etc/config/wireless').read_text(),'自己的热点')
                self.assertIn('saved-password-hash',(new/'etc/shadow').read_text())
                self.assertEqual((new/'etc/e5/image-version').read_text(),'new release\n')
                self.assertEqual((new/'etc/e5-infoscreen/plugins/phone/phone.js').read_text(),'new phone code')
                self.assertEqual((new/'lib/firmware/wcnmodem.bin').read_bytes(),b'own firmware')
                self.assertEqual(int.from_bytes(device.read_bytes()[1028:1032],'little')*4096,96<<20)
                if kind == 'sd':
                    self.assertTrue((new/'etc/e5/sd-root').is_file())
                    self.assertEqual((new/'etc/e5/sd-gen').read_text(), '7\n')
                    self.assertFalse((new/'etc/e5/part-root').exists())
                    self.assertFalse((new/'etc/e5/sd-trial').exists())
            elif fault in ('write', 'grow', 'readback'):
                self.assertNotEqual(result.returncode,0); self.assertNotIn('REBOOT',calls)
            else:
                self.assertNotEqual(result.returncode,0,result.stdout+result.stderr)
                self.assertNotIn('WRITE',calls)
                self.assertNotIn('REBOOT',calls)

    def test_update_preserves_capacity_settings_firmware_and_new_phone_code(self): self.exercise()
    def test_wrong_device_never_writes(self): self.exercise('cid')
    def test_low_ram_never_writes(self): self.exercise('ram')
    def test_corrupt_payload_never_writes(self): self.exercise('corrupt')
    def test_mounted_root_never_writes(self): self.exercise('busy')
    def test_write_failure_never_reboots_as_success(self): self.exercise('write')
    def test_capacity_failure_never_reboots_as_success(self): self.exercise('grow')
    def test_post_unmount_corruption_never_reboots_as_success(self): self.exercise('readback')
    def test_tf_keeps_capacity_configuration_and_legacy_generation(self): self.exercise(kind='sd')
    def test_unpartitioned_tf_keeps_capacity_and_boot_marker(self): self.exercise(kind='sd', raw_card=True)
    def test_tf_request_cannot_overwrite_emmc(self): self.exercise('emmc', kind='sd')
    def test_tf_wrong_card_never_writes(self): self.exercise('cid', kind='sd')
    def test_tf_corrupt_payload_never_writes(self): self.exercise('corrupt', kind='sd')
    def test_normal_boot_without_request_performs_no_mount_or_write(self):
        with tempfile.TemporaryDirectory() as folder:
            code = SOURCE.replace('/run/',folder+'/')
            p = subprocess.run(['busybox','ash'],input=code+'\npart_update_pending\n',text=True,capture_output=True,timeout=3)
            self.assertEqual(p.returncode,0,p.stderr)
            self.assertEqual(list(Path(folder).iterdir()),[])

    def test_conflicting_tf_transactions_fail_without_mount_or_write(self):
        with tempfile.TemporaryDirectory() as folder:
            (Path(folder)/'tf-update-conflict').touch()
            code = SOURCE.replace('/run/',folder+'/')
            p = subprocess.run(['busybox','ash'],input=code+'\npart_update_pending\n',text=True,capture_output=True,timeout=3)
            self.assertNotEqual(p.returncode,0)
            self.assertEqual([p.name for p in Path(folder).iterdir()],['tf-update-conflict'])


if __name__ == '__main__': unittest.main()
