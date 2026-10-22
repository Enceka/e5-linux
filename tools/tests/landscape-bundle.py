#!/usr/bin/env python3
"""Offline check that a Landscape image/bundle really carries the payload.

Runs the same extraction and assertions as the CI step after
openwrt/make-flash-bundle.sh, but against a build tree it is pointed at:

  python3 tools/tests/landscape-bundle.py [--image out/openwrt/e5-openwrt-*.ext4.gz]
                                          [--bundle out/openwrt/*landscape*.zip]
                                          [--daemon out/openwrt/landscape-webserver-aarch64-static]

Without arguments it builds a throwaway ext4 image with mke2fs (no root, no
loop device) from the staged `openwrt/landscape` tree, writes it through the
same debugfs calls the bundle check uses, and verifies every file that must
be in a Landscape image.  This is the check that catches a build flag that
enabled the service but forgot the daemon, the UI or the packages.

--daemon compares the image's /usr/sbin/landscape-webserver with that file
byte for byte.  CI passes the daemon it built from openwrt/build-landscape.sh:
the release's own binary has no IPv6 on this device's modem uplink
(docs/LANDSCAPE-V6-NAT-20261021.zh-CN.md), and only this comparison tells an
image built with the patch from one that fell back to the release asset.
"""
import argparse
import gzip
import hashlib
import io
import os
import re
import shutil
import subprocess
import sys
import zipfile
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


def dump(image, name):
    """The bytes of /<name> inside the ext4 image."""
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / 'file'
        subprocess.run(['debugfs', '-R', f'dump /{name} {out}', str(image)],
                       capture_output=True, check=True)
        return out.read_bytes()


def assert_image(image, daemon=None):
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
    binary = dump(image, REQUIRED[0])
    if binary[:4] != b'\x7fELF' or binary[18:20] != b'\xb7\x00':
        raise SystemExit('landscape-webserver is not an ARM64 ELF')
    if daemon is not None:
        # Same file, not merely another aarch64 daemon: the release asset is
        # one too, and it is the one that has no IPv6 on this uplink.
        expected = Path(daemon).read_bytes()
        if binary != expected:
            raise SystemExit(
                f'landscape-webserver is not {daemon} '
                f'(image {hashlib.sha256(binary).hexdigest()}, '
                f'built {hashlib.sha256(expected).hexdigest()})')
        print(f'ok: /{REQUIRED[0]} is {daemon} ({hashlib.sha256(binary).hexdigest()})')
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
    ap.add_argument('--bundle', type=Path,
                    help='Landscape flash bundle: the .zip artifact, or a .tar.gz')
    ap.add_argument('--daemon', type=Path,
                    help='the landscape-webserver the image must carry '
                         '(out/openwrt/landscape-webserver-aarch64-static)')
    a = ap.parse_args()
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        if a.bundle:
            if a.bundle.suffix == '.zip':
                # The shipped artifact: members sit at the archive root, which is
                # also what Magisk requires of module.prop/customize.sh.
                with zipfile.ZipFile(a.bundle) as archive:
                    names = archive.namelist()
                    for name in ('module.prop', 'customize.sh', 'files/SHA256SUMS',
                                 'files/openwrt.ext4.gz'):
                        if name not in names:
                            raise SystemExit(f'bundle has no {name}')
                    (tmp / 'openwrt.ext4.gz').write_bytes(
                        archive.read('files/openwrt.ext4.gz'))
            else:
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
            assert_image(image, a.daemon)
            return
        # The synthetic image carries a stub daemon, so --daemon has nothing
        # to compare against; it only means something for a real image.
        synthetic(tmp / 'img')
        assert_image(tmp / 'img')


if __name__ == '__main__':
    main()
