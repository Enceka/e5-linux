#!/usr/bin/env python3
"""Run the installer's real stream writer against small disposable files."""
import functools
import gzip
import http.server
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading

TOP = Path(__file__).resolve().parents[2]
script = (TOP / 'rootfs/device-install-sd.sh').read_text()
begin = script.index('write_slot_image() {')
writer = script[begin:script.index('\n}\n', begin) + 3]
MIB = 1 << 20


class QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


with tempfile.TemporaryDirectory(prefix='e5-sd-write-') as directory:
    root = Path(directory)
    image = b'I' * (4 * MIB)
    packed = gzip.compress(image)
    (root / 'good.gz').write_bytes(packed)
    corrupt = bytearray(packed); corrupt[-8] ^= 1
    (root / 'corrupt.gz').write_bytes(corrupt)
    (root / 'oversize-byte.gz').write_bytes(gzip.compress(image + b'X'))
    (root / 'oversize-large.gz').write_bytes(gzip.compress(image + b'X' * (2 * MIB)))
    (root / 'tmp').mkdir()
    server = http.server.ThreadingHTTPServer(('0.0.0.0', 0),
                functools.partial(QuietHandler, directory=str(root)))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f'http://host.docker.internal:{server.server_port}'
    def check(name, success, text='', output='/test/disk'):
        disk = root / 'disk'
        disk.write_bytes(b'P' * MIB + b'_' * (4 * MIB) + b'N' * MIB)
        # A fresh file avoids stale script sizes on Docker Desktop bind mounts.
        with tempfile.NamedTemporaryFile(mode='w', dir=root, suffix='.sh', delete=False) as script_file:
            script_file.write('set -eu\nT=/test/tmp\n' + writer +
                              f'\nwrite_slot_image {output} 2048 4 {url}/{name}\n')
            script_name = Path(script_file.name).name
        host_args = ['--add-host=host.docker.internal:host-gateway'] if sys.platform == 'linux' else []
        result = subprocess.run(['docker', 'run', '--rm', *host_args, '-v', f'{root}:/test',
                                 os.environ.get('E5_TEST_IMAGE', 'e5-openwrt-base:25.12.5'), 'sh', '/test/' + script_name],
                                capture_output=True, text=True, timeout=30)
        assert (result.returncode == 0) == success, (name, result.stdout, result.stderr)
        assert text in result.stdout + result.stderr, (name, result.stderr)
        data = disk.read_bytes()
        assert len(data) == 6 * MIB and data[:MIB] == b'P' * MIB and data[5*MIB:] == b'N' * MIB, \
            'writer touched an adjacent partition'
        if success:
            assert data[MIB:5*MIB] == image
        print(name, 'PASS')
    try:
        check('good.gz', True)
        check('corrupt.gz', False, 'decompression failed')
        check('missing.gz', False, 'download failed')
        check('oversize-byte.gz', False, 'exceeds the 4 MiB slot')
        check('oversize-large.gz', False, 'exceeds the 4 MiB slot')
        check('good.gz', False, 'card write rejected', output='/test/absent/disk')
    finally:
        server.shutdown()
print('All bounded-write cases preserved adjacent partitions')
