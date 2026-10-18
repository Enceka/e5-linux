"""Installed-image recognition and trial switching with no physical device."""
from pathlib import Path
import struct
import sys
import unittest
from unittest.mock import Mock

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from backend.boot_image import inspect_e5_boot,boot_installed_e5


def fixture(command='loglevel=7 e5.part_v=2', kernel=1048576):
    header=bytearray(4096);header[:8]=b'ANDROID!'
    struct.pack_into('<II',header,8,kernel,524288)
    struct.pack_into('<I',header,20,1584);struct.pack_into('<I',header,40,4)
    header[44:1580]=command.encode().ljust(1536,b'\0')
    tail=bytearray(512);tail[-64:-60]=b'AVBf'
    end=4096+((kernel+4095)//4096)*4096+524288
    struct.pack_into('>QQQ',tail,512-64+12,end,end,4096)
    return bytes(header),bytes(tail),64<<20


class InstalledBoot(unittest.TestCase):
    def test_valid_different_releases_and_partition_override_use_only_small_reads(self):
        for command,kernel in [('loglevel=7 e5.part_v=2',1048576),('loglevel=5 e5.part_v=2 e5.root=part',2097152)]:
            header,tail,size=fixture(command,kernel)
            read=Mock(side_effect=[header,tail])
            result=inspect_e5_boot(read,size)
            self.assertEqual(result['kernel_bytes'],kernel)
            self.assertEqual(read.call_count,2)
            for call in read.call_args_list:
                self.assertIn('if=/dev/block/by-name/boot_b',call.args[0])
                self.assertNotIn('of=',call.args[0])
                self.assertNotIn('sha256sum',call.args[0])

    def test_unknown_stock_truncated_pending_or_invalid_bounds_are_rejected(self):
        header,tail,size=fixture()
        cases=[(header[:-1],tail,size),(b'x'+header[1:],tail,size),
               (fixture('console=tty0')[0],tail,size),
               (fixture('e5.part_v=2 e5.part_prepare=deadbeef')[0],tail,size),
               (fixture(kernel=60<<20)[0],fixture(kernel=60<<20)[1],size),
               (header,tail[:-1],size),(header,bytes(512),size),(header,tail,1)]
        bad=bytearray(header);struct.pack_into('<I',bad,40,3);cases.append((bytes(bad),tail,size))
        bad=bytearray(tail);struct.pack_into('>Q',bad,512-64+20,1);cases.append((header,bytes(bad),size))
        for h,t,n in cases:
            with self.subTest(size=n,header=h[:8]),self.assertRaises(ValueError):
                inspect_e5_boot(Mock(side_effect=[h,t]),n)

    def test_only_misc_trial_and_reboot_follow_successful_checks(self):
        header,tail,size=fixture('e5.part_v=2 e5.root=part')
        order=[]
        api={name:Mock(side_effect=lambda *a,key=name:order.append(key)) for name in ('steps','find_adb','android_checks','bootchain','arm_slot_b','say','adb')}
        api['device_size']=Mock(return_value=size)
        boot_installed_e5(api,Mock(side_effect=[header,tail]))
        self.assertEqual(order,['steps','find_adb','android_checks','bootchain','arm_slot_b','say','adb'])
        api['bootchain'].assert_called_once_with('check')
        api['adb'].assert_called_once_with('reboot')

    def test_failed_image_or_chain_never_arms_misc_or_reboots(self):
        header,tail,size=fixture()
        for bad_header,bad_chain in [(True,False),(False,True)]:
            api={name:Mock() for name in ('steps','find_adb','android_checks','bootchain','arm_slot_b','say','adb')}
            api['device_size']=Mock(return_value=size)
            if bad_chain:api['bootchain'].side_effect=ValueError('chain mismatch')
            with self.assertRaises(ValueError):boot_installed_e5(api,Mock(side_effect=[bytes(4096) if bad_header else header,tail]))
            api['arm_slot_b'].assert_not_called();api['adb'].assert_not_called()


if __name__=='__main__':unittest.main()
