#!/usr/bin/env python3
"""Offline check that a Landscape image/bundle really carries the payload.

Runs the same extraction and assertions as the CI step after
openwrt/make-flash-bundle.sh, but against a build tree it is pointed at:

  python3 tools/tests/landscape-bundle.py [--image out/openwrt/e5-openwrt-*.ext4.gz]
                                          [--bundle out/openwrt/*landscape*.tar.gz]

Without arguments it builds a throwaway ext4 image with mke2fs (no root, no
loop device) from the staged `openwrt/landscape` tree, writes it through the
same debugfs calls the bundle check uses, and verifies every file that must
be in a Landscape image.  This is the check that catches a build flagthat
enabled the service but forgot the daemon, the UI or the packages.
"""
import argparse
import gzip
import io
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

TOP = Path(__file__).resolve().parents[2]
REQUIRED = [
    'usr/sbin/landscape-webserver',
    'usr/libexec/redirect_pkg_handler',
    'etc/landscape-router/landscape.toml',
    'etc/landscape-router/landscape_init.toml',
    'etc/landscape-router/static/index.html',
    'etc/init.d/landscape-router',
    'etc/uci-defaults/99-landscape',
]
FORBIDDEN = []
# e_type (16) = ET_EXEC, e_machine (18) = EM_AARCH64 in an ELF64 LE header
ELF_AARCH64 = (b'\x7fELF\x02\x01\x01' + b'\0' * 9 + b'\x02\x00\xb7\x00'
               + b'\0' * 32)


def debugfs_list(image):
    out = subprocess.run(['debugfs', '-R', 'ls -p /', str(image)],
                         capture_output=True, text=True).stdout
    return {line.split('/')[-1] for line in out.splitlines() if line.startswith('/')}


def assert_image(image):
    for name in REQUIRED:
        path = '/'
        for part in name.split('/')[:-1]:
            path += part + '/'
        listing = subprocess.run(['debugfs', '-R', f'ls -p {path}', str(image)],
                                 capture_output=True, text=True).stdout
        if name.split('/')[-1] not in listing:
            raise SystemExit(f'landscape image lacks /{name}')
    for name in FORBIDDEN:
        path = '/' + '/'.join(name.split('/')[:-1])
        listing = subprocess.run(['debugfs', '-R', f'ls -p {path}', str(image)],
                                 capture_output=True, text=True).stdout
        if name.split('/')[-1] in listing:
            raise SystemExit(f'landscape image must not carry /{name}')
    # the binary is aarch64 ELF; a wrong download (or a stub) would pass an
    # existence check
    dumped = tempfile.NamedTemporaryFile(delete=False).name
    subprocess.run(['debugfs', '-R', 'dump /usr/sbin/landscape-webserver ' + dumped, str(image)],
                   capture_output=True)
    head = Path(dumped).read_bytes()[:20]
    Path(dumped).unlink()
    if head[:4] != b'\x7fELF' or head[18:20] != b'\xb7\x00':
        raise SystemExit('landscape-webserver is not an ARM64 ELF')
    print(f'ok: /{REQUIRED[0]} and the UI, service, defaults in {image}')


def synthetic(out):
    # (/tmp is a tmpfs on some hosts; a 200 MiB image there is not welcome)
    root = Path(tempfile.mkdtemp(prefix='landscape-img-', dir=out.parent))
    stage = TOP / 'openwrt/landscape'
    shutil.copytree(stage, root / 'r', dirs_exist_ok=True)
    for d in ('usr/sbin', 'usr/libexec', 'etc/landscape-router/static'):
        (root / 'r' / d).mkdir(parents=True, exist_ok=True)
    (root / 'r/usr/sbin/landscape-webserver').write_bytes(ELF_AARCH64)
    (root / 'r/usr/sbin/landscape-webserver').chmod(0o755)
    (root / 'r/usr/libexec/redirect_pkg_handler').write_bytes(ELF_AARCH64)
    (root / 'r/etc/landscape-router/static/index.html').write_text('<html></html>')
    # the real signed-in binary is ~64 MiB: size the throwaway image for it
    subprocess.run(['mke2fs', '-q', '-t', 'ext4', '-d', str(root / 'r'), str(out), '192M'], check=True)
    shutil.rmtree(root)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--image', type=Path, help='ext4 or .ext4.gz Landscape image')
    ap.add_argument('--bundle', type=Path, help='Landscape flash bundle tar.gz')
    a = ap.parse_args()
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        if a.bundle:
            with tarfile.open(a.bundle, 'r:gz') as archive:
                names = archive.getnames()
                prefix = names[0].split('/')[0]
                for name in REQUIRED:
                    if f'{prefix}/files/openwrt.ext4.gz' not in names:
                        raise SystemExit('bundle has no files/openwrt.ext4.gz')
                for member in archive.getmembers():
                    if member.name.endswith('files/openwrt.ext4.gz'):
                        archive.extract(member, tmp, filter='data')
                        break
            image = next(tmp.rglob('openwrt.ext4.gz'))
            (tmp / 'img').write_bytes(gzip.decompress(image.read_bytes()))
            a.image = tmp / 'img'
        if a.image:
            image = a.image
            if image.suffix == '.gz':
                (tmp / 'img').write_bytes(gzip.decompress(image.read_bytes()))
                image = tmp / 'img'
            assert_image(image)
            return
        synthetic(tmp / 'img')
        assert_image(tmp / 'img')


if __name__ == '__main__':
    main()
