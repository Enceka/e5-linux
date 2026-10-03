#!/usr/bin/env python3
"""Test read-only allocation plans against synthetic GPT disks in OpenWrt."""
import hashlib
import os
from pathlib import Path
import struct
import subprocess
import tempfile
import uuid
import zlib

TOP = Path(__file__).resolve().parents[2]
TOOL = TOP / 'openwrt/overlay/usr/libexec/e5-gpt'
SECTOR = 512
MIB = 2048


def disk(path, mib, partitions, entries=128):
    sectors = mib * MIB
    table = bytearray(entries * 128)
    for number, start, length, name in partitions:
        offset = (number - 1) * 128
        table[offset:offset + 16] = uuid.UUID('0fc63daf-8483-4772-8e79-3d69d8477de4').bytes_le
        table[offset + 16:offset + 32] = uuid.uuid4().bytes_le
        struct.pack_into('<QQ', table, offset + 32, start * MIB, (start + length) * MIB - 1)
        table[offset + 56:offset + 56 + len(name) * 2] = name.encode('utf-16le')
    table_sectors = (len(table) + 511) // 512
    identity = uuid.uuid4().bytes_le
    def header(lba, alternate, table_lba):
        h = bytearray(512)
        struct.pack_into('<8sIIIIQQQQ16sQIII', h, 0, b'EFI PART', 0x10000, 92, 0, 0,
                         lba, alternate, 2 + table_sectors, sectors - table_sectors - 2,
                         identity, table_lba, entries, 128, zlib.crc32(table))
        struct.pack_into('<I', h, 16, zlib.crc32(h[:92]))
        return h
    with path.open('wb') as f:
        f.truncate(sectors * 512)
        f.seek(512); f.write(header(1, sectors - 1, 2))
        f.seek(1024); f.write(table)
        f.seek((sectors - table_sectors - 1) * 512); f.write(table)
        f.seek((sectors - 1) * 512); f.write(header(sectors - 1, 1, sectors - table_sectors - 1))


def metadata(path):
    with path.open('rb') as f:
        front = f.read(34 * 512)
        f.seek(-33 * 512, 2)
        return hashlib.sha256(front + f.read()).hexdigest()


with tempfile.TemporaryDirectory(prefix='e5-gpt-plan-') as directory:
    root = Path(directory)
    def check(name, size, parts, success, text='', entries=128):
        image = root / (name + '.img')
        disk(image, size, parts, entries)
        before = metadata(image)
        result = subprocess.run(['docker', 'run', '--rm', '-v', f'{root}:/test',
                                 '-v', f'{TOOL}:/gpt:ro', os.environ.get('E5_TEST_IMAGE', 'e5-openwrt-base:25.12.5'),
                                 'ucode', '/gpt', 'plan', '/test/' + image.name,
                                 'e5boot:65536', 'debian-a:8388608', 'debian-b:8388608'],
                                text=True, capture_output=True)
        assert (result.returncode == 0) == success, (name, result.stdout, result.stderr)
        assert metadata(image) == before, 'plan changed GPT metadata'
        assert text in result.stdout + result.stderr
        if success:
            rows = [row.split() for row in result.stdout.splitlines()]
            assert [row[0] for row in rows] == ['e5boot', 'debian-a', 'debian-b']
            assert all(int(row[2]) % 2048 == 0 for row in rows)
        print(name, 'PASS')

    check('enough', 16384, [(1, 1, 1024, 'e5root')], True, 'debian-b')
    # Both roots fit in separate gaps; a single 8 GiB contiguous gap is not required.
    check('fragmented-fit', 15500, [(3, 10000, 1024, 'reserved'),
                                   (1, 1, 1024, 'e5root'), (2, 5500, 1000, 'data')], True)
    check('insufficient', 8192, [(1, 1, 1024, 'e5root')], False, 'largest aligned gap')
    check('fragmented-too-small', 15000, [(1, 3500, 1000, 'one'), (2, 8000, 1000, 'two'),
                                          (3, 12500, 1000, 'three')], False, 'total remaining')
    check('entries-exhausted', 16384, [(1, 1, 1024, 'e5root')], False, 'GPT entries', entries=2)
    check('duplicate-id', 16384, [(1, 1, 1024, 'debian-a')], False, 'already exists')
print('All GPT allocation plans preserved disk metadata')
