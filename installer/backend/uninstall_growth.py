"""Read-only preservation eligibility and offline filesystem growth primitives."""
import json
import re
from pathlib import PurePosixPath
import stat
import struct
import tarfile

from .state import RecoveryRequired, sha


class PreservationUnavailable(RecoveryRequired):
    def __init__(self, reason, fingerprint):
        super().__init__(reason)
        self.fingerprint = fingerprint


def eligible(device, volume):
    if (device.get('encryption_state') != 'unencrypted' or device.get('encrypted') is not False or
            device.get('encryption_type') in ('file','block')):
        raise ValueError('Android data is encrypted or its encryption state is unconfirmed / Android data 已加密或无法确认加密状态')
    if (volume['source'].rsplit('/',1)[-1] != device['storage']['NODE'] or volume['mapping_overhead'] != 0):
        raise ValueError('Android data uses a mapping; direct userdata growth is unproven / Android data 存在映射，无法确认可直接扩容 userdata')
    if volume['filesystem'] not in ('ext4','f2fs') or not volume.get('uuid') or volume['uuid'] == '0'*32:
        raise ValueError('Filesystem type or identity is unsupported / 文件系统类型或身份不受支持')


def base_boot(adapter):
    path = adapter.root/'files/boot.img' if adapter.kind == 'e5' else adapter.legacy.payload_file(adapter.root,'boot-linux.img')
    return path.read_bytes()


def growth_tools(adapter, filesystem):
    """Copy verified package maintenance binaries into a private ramdisk namespace."""
    from .uninstall_boot import archives, entries
    files = {}
    if adapter.kind == 'mu300':
        folder = adapter.root/'desktop/files/boot/repair'
        manifest = json.loads((folder/'manifest.json').read_text())['sha256']
        for name, expected in manifest.items():
            if PurePosixPath(name).is_absolute() or '..' in PurePosixPath(name).parts:
                raise ValueError('Unsafe maintenance tool path')
            source = (folder/name).resolve()
            if not source.is_relative_to(folder.resolve()) or source.stat().st_size > 16 << 20:
                raise ValueError('Unsafe maintenance tool file')
            if sha(source) != expected:
                raise ValueError('Maintenance checksum differs: '+name)
            files[name] = source.read_bytes()
    else:
        base = base_boot(adapter)
        kernel, size = struct.unpack_from('<II',base,8)
        start = 4096+((kernel+4095)&~4095)
        for archive in archives(base[start:start+size]):
            for name, content, mode in entries(archive):
                if name.startswith('repair/') and stat.S_IFMT(mode) == stat.S_IFREG and name != 'repair/manifest.json':
                    files[name[7:]] = content
        if filesystem == 'ext4':
            with tarfile.open(adapter.root/'files/ext4-tools.tar') as archive:
                for member in archive:
                    name = member.name.removeprefix('./')
                    if not member.isfile():
                        continue
                    if PurePosixPath(name).is_absolute() or '..' in PurePosixPath(name).parts or member.size > 16 << 20:
                        raise ValueError('Unsafe ext4 maintenance archive')
                    if name.startswith(('lib/','usr/lib/','usr/sbin/')):
                        files[name] = archive.extractfile(member).read()
    required = ('sbin/fsck.f2fs','sbin/resize.f2fs') if filesystem == 'f2fs' else ('usr/sbin/e2fsck','usr/sbin/resize2fs')
    if any(name not in files for name in (*required,'lib/ld-musl-aarch64.so.1')):
        raise ValueError('Package lacks compatible filesystem tools / 安装包缺少兼容的文件系统检查与扩容工具')
    libraries = ('libf2fs.so.10','libuuid.so.1','libgcc_s.so.1') if filesystem == 'f2fs' else ('libext2fs.so.2','libe2p.so.2','libcom_err.so.0','libblkid.so.1','libuuid.so.1','libgcc_s.so.1')
    if any('lib/'+name not in files and 'usr/lib/'+name not in files for name in libraries):
        raise ValueError('Filesystem maintenance libraries are incomplete / 文件系统维护库不完整')
    # Retain both lib and usr/lib layouts used by the existing two bundles.
    files['lib/libc.so'] = files['lib/ld-musl-aarch64.so.1']
    if sum(map(len,files.values())) > 32 << 20:
        raise ValueError('Maintenance bundle exceeds ramdisk limit')
    for name, content in files.items():
        if len(content)<20 or content[:6] != b'\x7fELF\x02\x01' or struct.unpack_from('<H',content,18)[0] != 183:
            raise ValueError('Maintenance tool is not ARM64 ELF: '+name)
    if filesystem == 'f2fs':
        version = re.search(rb'(?<![0-9])1\.(\d+)\.(\d+)(?![0-9])',files['sbin/resize.f2fs'])
        if not version or int(version[1]) < 16:
            raise ValueError('F2FS growth tool compatibility is unconfirmed / F2FS 扩容工具版本兼容性未经确认')
    return {'openwrt-uninstall/tools/'+name:content for name,content in files.items()}


GROWTH = r'''
kernel_node_matches() {
    IFS=: read -r major minor < /sys/class/block/$1/dev
    case "$major:$minor" in *[!0-9:]*|:*) return 1 ;; esac
    [ "$(stat -c '%t:%T' /dev/$1)" = "$(printf '%x:%x' "$major" "$minor")" ]
}
fs_measure() {
    dd if="$1" of=fs-super bs=1024 skip=1 count=1 2>/dev/null
    [ "$(wc -c < fs-super)" = 1024 ]
    if [ "$action" = grow-f2fs ]; then
        [ "$(od -An -tx1 -N4 fs-super | tr -d ' \n')" = 1020f5f2 ]
        [ "$(od -An -tu4 -j16 -N4 fs-super | tr -d ' \n')" = 12 ]
        set -- $(od -An -tu4 -j36 -N8 fs-super)
        fs_bytes=$(( ($1 + ($2 << 32))*4096 ))
        uuid_offset=108
    else
        [ "$(od -An -tx1 -j56 -N2 fs-super | tr -d ' \n')" = 53ef ]
        fs_blocks=$(od -An -tu4 -j4 -N4 fs-super | tr -d ' \n')
        fs_shift=$(od -An -tu4 -j24 -N4 fs-super | tr -d ' \n')
        [ "$fs_shift" -le 6 ]
        fs_features=$(od -An -tu4 -j96 -N4 fs-super | tr -d ' \n')
        if [ "$((fs_features & 128))" != 0 ]; then
            fs_high=$(od -An -tu4 -j336 -N4 fs-super | tr -d ' \n')
            fs_blocks=$((fs_blocks + (fs_high << 32)))
        fi
        fs_bytes=$((fs_blocks * (1024 << fs_shift)))
        uuid_offset=104
    fi
    fs_uuid_now=$(od -An -tx1 -j "$uuid_offset" -N16 fs-super | tr -d ' \n')
    [ "$fs_uuid_now" = "$fs_uuid" ]
    [ "$fs_bytes" -ge "$fs_before" ] && [ "$fs_bytes" -le "$((data_size*512))" ]
}
fs_tool() {
    /openwrt-uninstall/tools/lib/ld-musl-aarch64.so.1 --library-path /openwrt-uninstall/tools/lib:/openwrt-uninstall/tools/usr/lib "$@"
}
fs_check() {
    if [ "$action" = grow-f2fs ]; then
        printf 'n\n' > /run/uninstall-fsck.stdin
        fs_tool /openwrt-uninstall/tools/sbin/fsck.f2fs -f "$1" < /run/uninstall-fsck.stdin || {
            rc=$?; [ "$rc" = 1 ] || return "$rc";
        }
    else
        fs_tool /openwrt-uninstall/tools/usr/sbin/e2fsck -pf "$1" </dev/null || {
            rc=$?; [ "$rc" = 1 ] || return "$rc";
        }
    fi
}
fs_grow() {
    # The caller verified the kernel's reread userdata extent. Never use a
    # whole-disk or unbounded loop fallback, mount, format or shrink it.
    [ "$(blockdev --getsize64 "$grow_device")" = "$((data_size*512))" ]
    fs_measure "$grow_device"
    fs_check "$grow_device"
    if [ "$fs_bytes" -lt "$((data_size*512-4194304))" ]; then
        if [ "$action" = grow-f2fs ]; then
            # -s is the shrink-only path; normal growth relocates metadata.
            fs_tool /openwrt-uninstall/tools/sbin/resize.f2fs -t "$data_size" "$grow_device" </dev/null
        else
            fs_tool /openwrt-uninstall/tools/usr/sbin/resize2fs "$grow_device" </dev/null
        fi
    fi
    fs_check "$grow_device"
    fs_measure "$grow_device"
    [ "$fs_bytes" -ge "$((data_size*512-4194304))" ]
    sync
}
'''
