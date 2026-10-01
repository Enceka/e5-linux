#!/usr/bin/env python3
"""Exercise SD selections without mounting or writing a real card."""
import os
from pathlib import Path
import subprocess
import tempfile

TOP = Path(__file__).resolve().parents[2]
SELECT = TOP / 'rootfs/overlay/opt/e5/e5-os'
SHARED = TOP / 'rootfs/overlay/opt/e5/e5-sd-registry'

with tempfile.TemporaryDirectory(prefix='e5-sd-check-') as directory:
    root = Path(directory)
    meta, blocks = root / 'meta', root / 'sys'
    meta.mkdir()
    blocks.mkdir()
    uuids = {
        'openwrt': '11111111-1111-1111-1111-111111111111',
        'debian': '22222222-2222-2222-2222-222222222222',
    }
    for number, (system, uuid) in enumerate(uuids.items(), 1):
        slot = meta / 'systems' / system
        slot.mkdir(parents=True)
        (slot / 'a').write_text(uuid + '\n')
        device = blocks / f'mmcblk1p{number}'
        device.mkdir()
        (device / 'uevent').write_text(f'PARTUUID={uuid}\n')
    (meta / 'format').write_text('1\n')
    (meta / 'default').write_text('openwrt\n')
    env = dict(os.environ, E5_SD_BOOT=str(meta), E5_SYS_BLOCK=str(blocks))

    def select(*arguments, success=True):
        result = subprocess.run(['sh', str(SELECT), *arguments], env=env,
                                text=True, capture_output=True)
        assert (result.returncode == 0) == success, (arguments, result.stdout, result.stderr)

    select('debian', '--once')
    assert (meta / 'next').read_text().strip() == 'debian'
    assert (meta / 'default').read_text().strip() == 'openwrt'
    select('debian')
    assert (meta / 'default').read_text().strip() == 'debian'
    assert not (meta / 'next').exists()
    select('../openwrt', success=False)
    select('missing', success=False)
    select('openwrt', '--bad', success=False)
    (blocks / 'mmcblk1p1/uevent').write_text('PARTUUID=33333333-3333-3333-3333-333333333333\n')
    select('openwrt', success=False)
    (meta / '.choice-lock').mkdir()
    select('debian', success=False)
    (meta / '.choice-lock').rmdir()
    for system, uuid, expected in [('debian', uuids['debian'], 0),
                                   ('debian', uuids['openwrt'], 1),
                                   ('../openwrt', uuids['openwrt'], 1)]:
        result = subprocess.run(['sh', '-c', '. "$1"; sd_registered "$2" "$3" "$4"',
                                 'check', str(SHARED), str(meta), system, uuid])
        assert result.returncode == expected
    (meta / 'format').write_text('2\n')
    select('status', success=False)
print('SD registry checks passed')
