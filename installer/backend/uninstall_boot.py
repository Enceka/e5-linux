"""Append a device-bound offline uninstall request to a verified boot v4 image."""
import stat
import struct
from .uninstall_worker import WORKER

MAGIC = bytes.fromhex('02214c18')


def archives(ram):
    import lz4.block
    at = 0
    while at < len(ram):
        if ram[at:at+4] != MAGIC:
            raise ValueError('Unsupported uninstall ramdisk compression / 卸载启动镜像压缩格式不受支持')
        at += 4
        data = bytearray()
        while at < len(ram) and ram[at:at+4] != MAGIC:
            if at+4 > len(ram):
                raise ValueError('Truncated ramdisk')
            size = struct.unpack_from('<I', ram, at)[0]; at += 4
            if size == 0:
                break
            if size > 9 << 20 or at+size > len(ram):
                raise ValueError('Invalid ramdisk block')
            data.extend(lz4.block.decompress(ram[at:at+size], uncompressed_size=8 << 20))
            at += size
            if len(data) > 192 << 20:
                raise ValueError('Uninstall ramdisk is too large')
        yield bytes(data)


def entries(data):
    at = 0
    while at < len(data):
        if data[at:at+6] not in (b'070701', b'070702') or at+110 > len(data):
            if not data[at:].strip(b'\0'):
                return
            raise ValueError('Invalid ramdisk cpio')
        values = [int(data[at+6+i*8:at+14+i*8], 16) for i in range(13)]
        size, namesize = values[6], values[11]
        end = at+110+namesize
        if namesize < 1 or end > len(data) or data[end-1] != 0:
            raise ValueError('Invalid ramdisk filename')
        name = data[at+110:end-1].decode('utf-8')
        at = (end+3)&~3
        if at+size > len(data):
            raise ValueError('Truncated ramdisk entry')
        if name == 'TRAILER!!!':
            return
        yield name.removeprefix('./'), data[at:at+size], values[1]
        at = (at+size+3)&~3


def record(name, data, mode, ino):
    name = name.encode()+b'\0'
    fields = [ino, mode, 0, 0, 1, 0, len(data), 0, 0, 0, 0, len(name), 0]
    result = b'070701'+b''.join(f'{n:08x}'.encode() for n in fields)+name
    return result+b'\0'*(-len(result)%4)+data+b'\0'*(-len(data)%4)


def overlay(files):
    import lz4.block
    directories = {'openwrt-uninstall'}
    for name in files:
        parts = name.split('/')
        directories.update('/'.join(parts[:i]) for i in range(1,len(parts)))
    data = b''; index = 1
    for name in sorted(directories,key=lambda name:(name.count('/'),name)):
        data += record(name,b'',stat.S_IFDIR|0o700,index); index += 1
    for name, content in files.items():
        executable = name == 'init' or name.startswith('openwrt-uninstall/tools/')
        data += record(name, content, stat.S_IFREG|(0o755 if executable else 0o600), index); index += 1
    data += record('TRAILER!!!', b'', 0, index)
    result = bytearray(MAGIC)
    for at in range(0, len(data), 8 << 20):
        block = lz4.block.compress(data[at:at+(8 << 20)], store_size=False)
        result.extend(struct.pack('<I', len(block))+block)
    return bytes(result)


def build(base, family, files):
    if (family not in ('e5','mu300') or len(base) != 64 << 20 or base[:8] != b'ANDROID!' or
            struct.unpack_from('<I', base, 40)[0] != 4 or base[-64:-60] != b'AVBf'):
        raise ValueError('A verified 64 MiB boot v4 image is required for uninstall')
    kernel, size = struct.unpack_from('<II', base, 8)
    start = 4096+((kernel+4095)&~4095)
    original_size, avb, avb_size = struct.unpack_from('>QQQ', base, len(base)-52)
    limit = (56 if family == 'e5' else 48) << 20
    if not kernel or not size or start+size > avb or avb+avb_size > limit or original_size != avb:
        raise ValueError('Invalid boot payload bounds')
    init = None
    for archive in archives(base[start:start+size]):
        for name, content, mode in entries(archive):
            if name == 'init':
                if stat.S_IFMT(mode) != stat.S_IFREG:
                    raise ValueError('Uninstall requires a regular init script')
                init = content.decode('utf-8').replace('\r\n','\n')
    if not init or not init.startswith('#!'):
        raise ValueError('Cannot find the packaged init script')
    # Use the existing model's drivers and setup. Never reach root mounting,
    # pending installation or pending update code in this one-shot image.
    anchor = '\ntf_update_probe\n' if family == 'e5' else '\nROOT_OFFSET='
    if init.count(anchor) != 1:
        raise ValueError('Unsupported offline uninstall hook / 此安装包不支持离线卸载，请使用新版安装包')
    begin = init.find('persist() {')
    end = init.find('\n}\n', begin)
    if begin < 0 or end < 0:
        raise ValueError('Cannot disable boot log writes during uninstall')
    init = init[:begin]+'persist() { :; }'+init[end+2:]
    hook = '\ntouch /run/stay\n'
    if family == 'mu300':
        hook += 'setup_usb_gadget\n'
    hook += 'exec /bin/busybox sh /openwrt-uninstall/worker.sh\n'
    init = init[:init.index(anchor)]+hook
    files = {'init': init.encode(), **files,
             'openwrt-uninstall/worker.sh': WORKER.encode()}
    ram = base[start:start+size]+overlay(files)
    header = bytearray(base[:4096]); struct.pack_into('<I', header, 12, len(ram))
    command = base[44:1580].split(b'\0',1)[0]+b' openwrt.uninstall=1'
    if len(command) >= 1536:
        raise ValueError('Boot command line has no room for the uninstall guard')
    header[44:1580] = command.ljust(1536,b'\0')
    body = (bytes(header)+base[4096:start]+ram)
    body = body.ljust((len(body)+4095)&~4095,b'\0')
    new_avb = len(body)
    body += base[avb:avb+avb_size]
    if len(body) > limit:
        raise ValueError('Uninstall request would overlap boot diagnostics; nothing written')
    footer = bytearray(base[-64:]); struct.pack_into('>QQQ', footer, 12, new_avb, new_avb, avb_size)
    return body.ljust(len(base)-64,b'\0')+footer
