"""Both MU300 Android slots and all profiles share one misc-only switch."""
from pathlib import Path
import struct
import sys
import unittest
from types import SimpleNamespace
import zlib
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from backend.boot_image import boot_installed_mu300,trial_control
from backend.adapter import installation_committed
from test_boot_switch import fixture


def control(slot):
    raw=bytearray(32);raw[:4]=('_'+slot).encode()+b'\0\0';raw[4:8]=b'BCAB';raw[8]=1;raw[9]=2
    raw[12],raw[14]=(0x9f,0x1e) if slot=='a' else (0x1e,0x9f)
    struct.pack_into('<I',raw,28,zlib.crc32(raw[:28]));return bytes(raw)


class AndroidFixture:
    def __init__(self,slot,model='MU300'):
        self.slot=slot;self.linux='b' if slot=='a' else 'a';self.model=model;self.bb='/fixture/busybox'
        self.header,self.tail,self.size=fixture('console=tty0 loglevel=5 androidboot.fixture=previous')
        self.android_header=fixture('androidboot.fixture=stock')[0]
        self.before=control(slot);self.calls=[];self.body='';self.chain_failed=False;self.write_failed=False
    def read(self,script):
        self.calls.append(('read',script))
        if 'if=/dev/block/by-name/boot_'+self.slot+' ' in script:return self.android_header
        assert 'if=/dev/block/by-name/boot_'+self.linux in script
        return self.header if 'count=8' in script else self.tail
    def shell(self,script):
        self.calls.append(('shell',script))
        return str(self.size) if script.startswith('blockdev --getsize64 ') else ''
    def live(self):return self.before
    def push(self,path,name):self.calls.append(('push',name))
    def put(self,data,name):self.calls.append(('put',name));self.wanted=data
    def run(self,script):
        if script.endswith('android-bootchain.sh" check'):
            if self.chain_failed:raise ValueError('chain mismatch')
            self.calls.append(('chain','check'))
        else:
            self.body=script;self.calls.append(('misc','write'))
            if self.write_failed:raise ValueError('write/readback failed')
    def reboot(self):self.calls.append(('reboot',))


class MU300Switch(unittest.TestCase):
    def api(self,observer=None):
        return {'GUI':observer,'payload_file':lambda root,name:root/'payload'/name,'Outcome':lambda *args:SimpleNamespace(state=args[0],message=args[1],next_step=args[2])}

    def test_profiles_slots_and_extra_boot_arguments_share_verified_trial(self):
        for model in ('MU300','F50','V50','U30Air'):
            for slot in ('a','b'):
                with self.subTest(model=model,slot=slot):
                    android=AndroidFixture(slot,model);effects=[]
                    def action(name,fn):effects.append(name);return fn()
                    result=boot_installed_mu300(self.api(SimpleNamespace(action=action)),android,Path('/fixture'))
                    self.assertEqual(result.state,'success');self.assertEqual(effects,['misc-trial'])
                    self.assertEqual(android.calls[-1],('reboot',))
                    wanted=trial_control(android.before,slot)
                    self.assertEqual(android.wanted,wanted)
                    self.assertEqual(wanted[:4],b'_b\0\0' if slot=='a' else b'_a\0\0')
                    current=12 if slot=='a' else 14
                    self.assertTrue(wanted[current]&0x80)
                    self.assertEqual(wanted[14 if slot=='a' else 12],0x2f)
                    self.assertEqual(zlib.crc32(wanted[:28]),struct.unpack_from('<I',wanted,28)[0])
                    for forbidden in ('mount ','of=/dev/block/by-name/boot','userdata','default-boot',' sync "$T/bootchain'):
                        self.assertNotIn(forbidden,android.body)
                    self.assertIn('count=32 conv=notrunc,fsync',android.body)
                    self.assertIn('dd if="$backup" of=/dev/block/by-name/misc',android.body)

    def test_chain_or_write_failure_never_reboots(self):
        for flag in ('chain_failed','write_failed'):
            android=AndroidFixture('a');setattr(android,flag,True)
            with self.assertRaises(ValueError):boot_installed_mu300(self.api(),android,Path('/fixture'))
            self.assertNotIn(('reboot',),android.calls)
            if flag=='chain_failed':self.assertFalse(android.body)

    def test_invalid_misc_crc_health_and_pending_priority_stop_before_writes(self):
        for change in ('crc','health','verity','priority'):
            android=AndroidFixture('b');raw=bytearray(android.before)
            if change=='crc':raw[28]^=1
            else:
                if change=='health':raw[14]=0x1f
                if change=='verity':raw[13]=1
                if change=='priority':raw[14]=0x9e;raw[12]=0x1f
                struct.pack_into('<I',raw,28,zlib.crc32(raw[:28]))
            android.before=bytes(raw)
            with self.subTest(change=change),self.assertRaises(ValueError):boot_installed_mu300(self.api(),android,Path('/fixture'))
            self.assertFalse(any(call[0] in ('push','put','misc','reboot') for call in android.calls))

    def test_wrong_family_unknown_slot_and_invalid_header_stop_before_writes(self):
        for variant in ('e5','stock','truncated','slot','identical'):
            android=AndroidFixture('a')
            if variant=='e5':android.header=fixture('loglevel=5 e5.part_v=2')[0]
            elif variant=='stock':android.header=fixture('androidboot.hardware=stock')[0]
            elif variant=='truncated':android.header=bytes(40)
            elif variant=='identical':android.android_header=android.header
            else:android.linux=android.slot
            with self.subTest(variant=variant),self.assertRaises(ValueError):boot_installed_mu300(self.api(),android,Path('/fixture'))
            self.assertFalse(any(call[0] in ('push','put','misc','reboot') for call in android.calls))

    def test_completed_trial_resumes_wait_without_replaying_misc(self):
        record={'package':{'adapter':'mu300'},'choices':{'method':'boot'},'plan':{'method':'boot'},'effects':{'misc-trial':{'state':'done'}}}
        self.assertTrue(installation_committed(record))
        record['effects']['misc-trial']['state']='started'
        self.assertFalse(installation_committed(record))


if __name__=='__main__':unittest.main()
