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
TOOL = TOP / 'boot/installer-runtime/openwrt/usr/libexec/e5-gpt'
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
    def run(*args):
        return subprocess.run(['docker', 'run', '--rm', '-v', f'{root}:/test',
                               '-v', f'{TOOL}:/gpt:ro', os.environ.get('E5_TEST_IMAGE', 'e5-openwrt-base:25.12.5'),
                               'ucode', '/gpt', *args], text=True, capture_output=True)
    def check(name, size, parts, success, text='', entries=128):
        image = root / (name + '.img')
        disk(image, size, parts, entries)
        before = metadata(image)
        result = run('plan', '/test/' + image.name,
                     'e5boot:65536', 'debian-a:8388608', 'debian-b:8388608')
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

    # A shrink in the same plan frees the gap the add lands in: the request
    # order inside one plan is the order the real commands would run in.
    image = root / 'resize-plan.img'
    disk(image, 16384, [(1, 1, 8192, 'userdata')])
    before = metadata(image)
    result = run('plan', '/test/resize-plan.img', 'resize:userdata:4194304', 'linux:4194304')
    assert result.returncode == 0, (result.stdout, result.stderr)
    assert metadata(image) == before, 'plan resize changed GPT metadata'
    rows = [row.split() for row in result.stdout.splitlines()]
    assert [row[0] for row in rows] == ['userdata', 'linux'], rows
    assert rows[0][3] == '4196351', rows        # 2048 + 4194304 - 1
    assert rows[1][2] == '4196352', rows        # 1 MiB aligned, right after the shrink
    print('resize-plan PASS')

    result = run('plan', '/test/resize-plan.img', 'resize:userdata:4194304', 'resize:linux:2048')
    assert result.returncode != 0 and 'no partition named linux' in result.stdout + result.stderr
    result = run('plan', '/test/resize-plan.img', 'resize:nosuch:4194304')
    assert result.returncode != 0 and 'no partition named nosuch' in result.stdout + result.stderr
    print('resize-plan-errors PASS')

    # The real shrink, then the real add in the freed gap, then a second
    # resize of the same size: it must load and compare BOTH GPT copies, so
    # it fails unless the first one wrote the backup table too.
    image = root / 'resize-real.img'
    disk(image, 16384, [(1, 1, 8192, 'userdata'), (2, 12288, 2048, 'tail')])
    before = metadata(image)
    result = run('resize', '/test/resize-real.img', 'userdata', '4194304')
    assert result.returncode == 0, (result.stdout, result.stderr)
    assert result.stdout.split() == ['userdata', '1', '2048', '4196351'], result.stdout
    assert metadata(image) != before, 'resize wrote nothing'
    result = run('resize', '/test/resize-real.img', 'userdata', '4194304')
    assert result.returncode == 0, ('backup GPT disagrees', result.stdout, result.stderr)
    result = run('add', '/test/resize-real.img', 'linux', '4194304')
    assert result.returncode == 0, (result.stdout, result.stderr)
    result = run('list', '/test/resize-real.img')
    rows = {row.split()[3]: row.split() for row in result.stdout.splitlines()}
    assert rows['userdata'][1:3] == ['2048', '4196351'], rows
    assert rows['linux'][1:3] == ['4196352', '8390655'], rows
    over = run('resize', '/test/resize-real.img', 'linux', '20971520')
    assert over.returncode != 0 and 'overlaps partition' in over.stdout + over.stderr
    print('resize-real PASS')

    image = root / 'carve.img'
    disk(image, 16384, [(1, 1, 8192, 'userdata'), (2, 12288, 2048, 'tail')])
    before = metadata(image)
    for target, size, old in [('4194304', '12584960', '16777216'),
                              ('4194304', '4194304', '99'), ('1', '4194304', '16777216')]:
        result = run('carve-userdata', '/test/carve.img', target, size, old)
        assert result.returncode != 0, (result.stdout, result.stderr)
        assert metadata(image) == before, 'rejected carve modified the disk'
    result = run('carve-userdata', '/test/carve.img', '8388608', '8388608', '16777216')
    assert result.returncode == 0, (result.stdout, result.stderr)
    rows = {r.split()[3]: r.split() for r in run('list', '/test/carve.img').stdout.splitlines()}
    assert rows['userdata'][1:3] == ['2048', '8390655'], rows
    assert rows['e5root'][1:3] == ['8390656', '16779263'], rows
    assert rows['tail'][1:3] == ['25165824', '29360127'], rows
    before = metadata(image)
    assert run('carve-userdata', '/test/carve.img', '4194304', '4194304', '8388608').returncode != 0
    assert metadata(image) == before, 'repeated carve changed metadata'
    # A plan reload validates primary AND backup tables after the joint commit.
    assert run('plan', '/test/carve.img', 'resize:userdata:8388608').returncode == 0
    print('destructive-carve PASS')

print('All GPT allocation plans preserved disk metadata')
