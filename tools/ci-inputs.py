#!/usr/bin/env python3
"""Prepare/verify the small bootstrap archive required by a clean CI build.

The boot template retains only the Android header, vbmeta and footer; the misc
template retains only bootloader_control. No stock kernel, firmware or vendor
userspace is included. Cached WPE files must belong to the three named packages.
"""
import argparse
import hashlib
import io
import json
import os
import posixpath
import stat
import struct
import tarfile
import zlib
from pathlib import Path, PurePosixPath

TOP = Path(__file__).resolve().parents[1]
PACKAGES = {'cog', 'libcogcore', 'libwpewebkit'}
MAX_BYTES = 256 << 20


def sha(data):
    return hashlib.sha256(data).hexdigest()


def boot_template(data):
    if len(data) != 64 << 20 or data[:8] != b'ANDROID!' or struct.unpack_from('<I', data, 40)[0] != 4:
        raise ValueError('expected a 64 MiB E5 Android boot v4 image')
    if data[-64:-60] != b'AVBf':
        raise ValueError('boot image has no AVB footer')
    offset, size = struct.unpack_from('>QQ', data, len(data) - 44)
    if size < 256 or offset + size > len(data) - 64 or data[offset:offset + 4] != b'AVB0':
        raise ValueError('boot image has invalid vbmeta bounds')
    result = bytearray(len(data))
    result[:44] = data[:44]
    struct.pack_into('<II', result, 8, 0, 0)
    result[4096:4096 + size] = data[offset:offset + size]
    result[-64:] = data[-64:]
    struct.pack_into('>QQQ', result, len(result) - 52, 4096, 4096, size)
    return bytes(result)


def misc_template(data):
    bc = data[0x800:0x820]
    if len(bc) != 32 or bc[4:8] != b'BCAB' or zlib.crc32(bc[:28]) != struct.unpack_from('<I', bc, 28)[0]:
        raise ValueError('misc template has invalid bootloader_control')
    result = bytearray(4096)
    result[0x800:0x820] = bc
    return bytes(result)


def package_paths(text):
    blocks = [b for b in text.split('\n\n') if b.strip()]
    names, paths = set(), set()
    for block in blocks:
        directory = None
        for line in block.splitlines():
            if line.startswith('P:'):
                names.add(line[2:])
            elif line.startswith('F:'):
                directory = line[2:]
            elif line.startswith('R:'):
                if not directory:
                    raise ValueError('package file without a directory')
                path = directory + '/' + line[2:]
                if PurePosixPath(path).is_absolute() or '..' in PurePosixPath(path).parts:
                    raise ValueError('invalid package path')
                paths.add(path)
    if names != PACKAGES:
        raise ValueError('bootstrap cache must contain exactly cog, libcogcore and libwpewebkit')
    return paths


def create(args):
    cache = args.transplant
    installed = (cache / 'installed').read_text()
    payload = {
        'dumps/boot_b.img': (boot_template(args.boot.read_bytes()), 0o644),
        'dumps/misc-head.bin': (misc_template(args.misc.read_bytes()), 0o644),
        'work/busybox/ext/usr/bin/busybox': (args.busybox.read_bytes(), 0o755),
        'work/openwrt/transplant/installed': (installed.encode(), 0o644),
        'work/openwrt/transplant/names': ('\n'.join(sorted(PACKAGES)).encode() + b'\n', 0o644),
        'work/openwrt/transplant/deps': ((cache / 'deps').read_bytes(), 0o644),
    }
    links = {}
    for relative in sorted(package_paths(installed)):
        path = cache / 'root' / relative
        name = 'work/openwrt/transplant/root/' + relative
        if path.is_symlink():
            links[name] = os.readlink(path)
        elif path.is_file():
            payload[name] = (path.read_bytes(), stat.S_IMODE(path.stat().st_mode))
        else:
            raise ValueError('missing cached package file: ' + relative)
    manifest = {'format': 1, 'files': {n: sha(data) for n, (data, _) in payload.items()}, 'links': links}
    payload['ci-inputs.json'] = ((json.dumps(manifest, indent=2) + '\n').encode(), 0o644)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(args.output, 'w:gz', format=tarfile.GNU_FORMAT) as archive:
        for name in sorted(payload.keys() | links.keys()):
            entry = tarfile.TarInfo(name)
            if name in links:
                entry.type = tarfile.SYMTYPE
                entry.linkname = links[name]
                archive.addfile(entry)
            else:
                data, entry.mode = payload[name]
                entry.size = len(data)
                archive.addfile(entry, io.BytesIO(data))
    inspect(args.output)
    digest = sha(args.output.read_bytes())
    Path(str(args.output) + '.sha256').write_text(digest + '  ' + args.output.name + '\n')
    print(args.output)
    print('SHA256=' + digest)


def inspect(path):
    with tarfile.open(path) as archive:
        entries = archive.getmembers()
        names = [e.name for e in entries]
        if len(names) != len(set(names)) or sum(e.size for e in entries) > MAX_BYTES:
            raise ValueError('duplicate entries or oversized bootstrap archive')
        data, links, modes = {}, {}, {}
        for entry in entries:
            name = entry.name
            if PurePosixPath(name).is_absolute() or '..' in PurePosixPath(name).parts or name.endswith('/'):
                raise ValueError('invalid bootstrap path: ' + name)
            if entry.isfile():
                data[name] = archive.extractfile(entry).read()
                modes[name] = entry.mode & 0o777
            elif entry.issym():
                target = posixpath.normpath(posixpath.join(posixpath.dirname(name), entry.linkname))
                if entry.linkname.startswith('/') or not target.startswith('work/openwrt/transplant/root/'):
                    raise ValueError('unsafe cache symlink: ' + name)
                links[name] = entry.linkname
            else:
                raise ValueError('unexpected bootstrap file type: ' + name)
        manifest = json.loads(data.pop('ci-inputs.json'))
        if manifest.get('format') != 1 or manifest['files'] != {n: sha(v) for n, v in data.items()} or manifest['links'] != links:
            raise ValueError('bootstrap manifest mismatch')
        if boot_template(data['dumps/boot_b.img']) != data['dumps/boot_b.img']:
            raise ValueError('boot template includes a stock payload')
        if misc_template(data['dumps/misc-head.bin']) != data['dumps/misc-head.bin']:
            raise ValueError('misc template includes data outside bootloader_control')
        bb = data['work/busybox/ext/usr/bin/busybox']
        if bb[:4] != b'\x7fELF' or struct.unpack_from('<H', bb, 18)[0] != 183:
            raise ValueError('BusyBox must be an ARM64 ELF')
        permitted = {'dumps/boot_b.img', 'dumps/misc-head.bin', 'work/busybox/ext/usr/bin/busybox',
                     'work/openwrt/transplant/installed', 'work/openwrt/transplant/names', 'work/openwrt/transplant/deps'}
        installed = data['work/openwrt/transplant/installed'].decode()
        permitted.update('work/openwrt/transplant/root/' + p for p in package_paths(installed))
        if set(data) | set(links) != permitted:
            raise ValueError('bootstrap includes files outside the boot templates, BusyBox and WPE packages')
        for link in links:
            if any(parent.as_posix() in links for parent in PurePosixPath(link).parents):
                raise ValueError('nested cache symlink')
        for name in data:
            if any(parent.as_posix() in links for parent in PurePosixPath(name).parents):
                raise ValueError('file beneath cache symlink')
        data['ci-inputs.json'] = (json.dumps(manifest, indent=2) + '\n').encode()
        modes['ci-inputs.json'] = 0o644
        return data, links, modes


def restore(args):
    if sha(args.archive.read_bytes()) != args.sha256.lower():
        raise ValueError('bootstrap SHA-256 mismatch')
    data, links, modes = inspect(args.archive)
    for name in data.keys() | links.keys():
        target = args.destination / name
        if target.exists() or target.is_symlink():
            raise ValueError('bootstrap destination already exists: ' + name)
        if any(p.is_symlink() for p in target.parents):
            raise ValueError('bootstrap destination contains a symlink: ' + name)
    for name, content in data.items():
        target = args.destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
        target.chmod(modes[name])
    for name, link in links.items():
        target = args.destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.symlink_to(link)
    print('Verified and restored CI inputs')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    build = sub.add_parser('create')
    build.add_argument('--boot', type=Path, default=TOP / 'dumps/boot_b.img')
    build.add_argument('--misc', type=Path, default=TOP / 'dumps/misc-head.bin')
    build.add_argument('--busybox', type=Path, default=TOP / 'work/busybox/ext/usr/bin/busybox')
    build.add_argument('--transplant', type=Path, default=TOP / 'work/openwrt/transplant')
    build.add_argument('--output', type=Path, default=TOP / 'out/e5-ci-inputs.tar.gz')
    unpack = sub.add_parser('restore')
    unpack.add_argument('archive', type=Path)
    unpack.add_argument('--sha256', required=True)
    unpack.add_argument('--destination', type=Path, default=TOP)
    args = parser.parse_args()
    try:
        (create if args.command == 'create' else restore)(args)
    except (ValueError, KeyError) as error:
        parser.exit(1, 'CI inputs: ' + str(error) + '\n')
