"""Shared installed-boot recognition and misc trial selection for both families."""
import hashlib
import struct
import zlib


def inspect_linux_boot(read, size, family, slot):
    if family not in ('e5','mu300') or slot not in ('a','b'):
        raise ValueError('Unsupported boot family or slot')
    limit=(56 if family=='e5' else 48)<<20
    if type(size) is not int or size < limit or size % 512:
        raise ValueError('Invalid boot partition size / 启动分区大小无效')
    header=read(f'dd if=/dev/block/by-name/boot_{slot} bs=512 count=8 2>/dev/null')
    tail=read(f'dd if=/dev/block/by-name/boot_{slot} bs=512 skip={size//512-1} count=1 2>/dev/null')
    if len(header)!=4096 or len(tail)!=512 or header[:8]!=b'ANDROID!':
        raise ValueError('Installed boot header is missing or incomplete / 已安装启动镜像头缺失或不完整')
    kernel,ramdisk=struct.unpack_from('<II',header,8)
    header_size=struct.unpack_from('<I',header,20)[0]
    version=struct.unpack_from('<I',header,40)[0]
    if version!=4 or header_size!=1584 or not kernel or not ramdisk:
        raise ValueError('Unsupported installed boot format / 已安装启动镜像格式不受支持')
    raw=header[44:1580]
    if b'\0' not in raw:
        raise ValueError('Invalid installed boot command line / 已安装启动参数无效')
    try:command=raw.split(b'\0',1)[0].decode('ascii').split()
    except UnicodeDecodeError:raise ValueError('Invalid installed boot command line / 已安装启动参数无效') from None
    recognized='e5.part_v=2' in command if family=='e5' else 'loglevel=5' in command and not any(item.startswith('e5.') for item in command)
    if not recognized:
        raise ValueError('No recognized '+family+' Linux boot in slot '+slot+' / 目标槽未识别到相应机型系列的 Linux 启动镜像')
    if any(item.startswith('e5.part_prepare=') for item in command):
        raise ValueError('Partition preparation is pending; resume the saved installation / 分区准备尚未完成，请从保存记录续装')
    if 'openwrt.uninstall=1' in command:
        raise ValueError('Uninstall is pending; resume its saved record instead of booting OpenWrt / 卸载尚未完成，请从保存记录继续，不要临时启动 OpenWrt')
    end=4096+((kernel+4095)//4096)*4096+((ramdisk+4095)//4096)*4096
    footer=tail[-64:]
    if footer[:4]!=b'AVBf':
        raise ValueError('Installed boot footer is missing / 已安装启动镜像尾部无效')
    original,offset,length=struct.unpack_from('>QQQ',footer,12)
    if original!=end or offset!=end or not length or offset+length>limit or offset+length>size-64:
        raise ValueError('Installed boot payload bounds are invalid / 已安装启动镜像范围无效')
    return {'header_version':version,'kernel_bytes':kernel,'ramdisk_bytes':ramdisk,'header_sha256':hashlib.sha256(header).hexdigest()}


def inspect_e5_boot(read,size):
    return inspect_linux_boot(read,size,'e5','b')


def trial_control(before,slot):
    if (slot not in ('a','b') or len(before)!=32 or before[4:8]!=b'BCAB' or before[8]!=1 or before[9]&7!=2 or
            struct.unpack_from('<I',before,28)[0]!=zlib.crc32(before[:28])):
        raise ValueError('Invalid current slot or BCAB format/CRC / 当前槽位或 misc 校验无效')
    current=12 if slot=='a' else 14
    opposite=14 if slot=='a' else 12
    if not before[current]&0x80 or not before[current]&15 or before[13]&1 or before[15]&1:
        raise ValueError('Android slot is not healthy; finish Android setup/update first / Android 槽位未就绪，请先完成 Android 初始化或更新')
    if before[opposite]&15 > before[current]&15:
        raise ValueError('Another slot has higher priority; finish or cancel the pending boot first / 另一槽位优先级较高，请先完成或取消待执行的启动')
    result=bytearray(before)
    result[:4]=b'_b\0\0' if slot=='a' else b'_a\0\0'
    result[current]=(before[current]&0xf0)|14
    result[opposite]=0x2f
    struct.pack_into('<I',result,28,zlib.crc32(result[:28]))
    return bytes(result)


def boot_installed_mu300(api,android,root):
    """Select the installed opposite slot without root mounts or boot writes."""
    if android.slot not in ('a','b') or android.linux!=('b' if android.slot=='a' else 'a'):
        raise ValueError('Invalid Android/Linux slot selection')
    target='/dev/block/by-name/boot_'+android.linux
    installed=inspect_linux_boot(android.read,int(android.shell('blockdev --getsize64 '+target).strip()),'mu300',android.linux)
    current=android.read('dd if=/dev/block/by-name/boot_'+android.slot+' bs=512 count=8 2>/dev/null')
    if len(current)!=4096 or current[:8]!=b'ANDROID!':
        raise ValueError('Current Android boot header is incomplete / 当前 Android 启动镜像头不完整')
    if hashlib.sha256(current).hexdigest()==installed['header_sha256']:
        raise ValueError('Opposite slot has the same Android boot header; no distinct Linux boot identified / 另一槽与当前 Android 启动镜像头相同，未识别到独立 Linux 镜像')
    before=android.live()
    wanted=trial_control(before,android.slot)
    for name in ('busybox','android-bootchain.sh'):
        source=root/'desktop'/name if name=='android-bootchain.sh' else api['payload_file'](root,name)
        android.push(source,name)
    android.shell('chmod 755 '+android.bb)
    android.run('"$BB" sh "$P/android-bootchain.sh" check')
    android.put(wanted,'misc-trial.bin')
    expected=hashlib.sha256(before).hexdigest();checksum=hashlib.sha256(wanted).hexdigest()
    body='''set -o pipefail
[ "$(getprop ro.boot.slot_suffix)" = "_'''+android.slot+'''" ]
umask 077
mkdir -p /data/adb/openwrt-boot-control
backup=$(mktemp /data/adb/openwrt-boot-control/before.XXXXXX)
dd if=/dev/block/by-name/misc of="$backup" bs=1 skip=2048 count=32
[ "$(sha256sum "$backup" | cut -d ' ' -f1)" = '''+expected+''' ]
[ "$(stat -c %s "$P/misc-trial.bin")" = 32 ]
[ "$(sha256sum "$P/misc-trial.bin" | cut -d ' ' -f1)" = '''+checksum+''' ]
sync
if dd if="$P/misc-trial.bin" of=/dev/block/by-name/misc bs=1 seek=2048 count=32 conv=notrunc,fsync &&
   [ "$(dd if=/dev/block/by-name/misc bs=1 skip=2048 count=32 | sha256sum | cut -d ' ' -f1)" = '''+checksum+''' ]; then
    echo 'MISC-TRIAL-VERIFIED'
else
    dd if="$backup" of=/dev/block/by-name/misc bs=1 seek=2048 count=32 conv=notrunc,fsync
    [ "$(dd if=/dev/block/by-name/misc bs=1 skip=2048 count=32 | sha256sum | cut -d ' ' -f1)" = '''+expected+''' ] || echo 'MISC RESTORE FAILED; do not reboot'
    exit 1
fi
'''
    observer=api.get('GUI')
    if observer:observer.action('misc-trial',lambda:android.run(body))
    else:android.run(body)
    android.reboot()
    return api['Outcome']('success','OpenWrt trial selected; only misc changed / 已选择临时启动 OpenWrt，仅修改 misc。',
                          'Device is restarting; default-boot settings are unchanged / 设备正在重启，原默认启动设置保持不变。')


def boot_installed_e5(api, read):
    """Shared CLI/GUI trial selection, independent of the current package hash."""
    api['steps'](2)
    api['find_adb']()
    api['android_checks']()
    inspect_e5_boot(read,api['device_size']('/dev/block/by-name/boot_b'))
    api['bootchain']('check')
    api['arm_slot_b']()
    api['say']('正在临时启动 OpenWrt（未更改默认设置）/ booting OpenWrt without changing defaults')
    api['adb']('reboot')
