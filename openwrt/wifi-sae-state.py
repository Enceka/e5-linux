#!/usr/bin/env python3
"""Verify that an incremental package uses the current SAE userspace build."""
from pathlib import Path
import hashlib
import re

HERE = Path(__file__).resolve().parent
SOURCES = ('build-hostapd.sh', 'build-hostapd-inner.sh', 'hostapd.Dockerfile',
           'patch-hostapd-sae.py', 'hostapd-unisoc-sae.h', 'hostapd-unisoc.sh',
           'hostapd-unisoc.uc', 'wifi-sae-state.py')


def build_id():
    return hashlib.sha256(b''.join((HERE / n).read_bytes() for n in SOURCES)).hexdigest()


def inspect(directory):
    directory = Path(directory)
    if (directory / 'build-id').read_text().strip() != build_id():
        raise ValueError('WPA3 APKs are stale; run openwrt/build-hostapd.sh')
    expected = {}
    for line in (directory / 'SHA256SUMS').read_text().splitlines():
        checksum, name = line.split()
        name = name.removeprefix('./')
        if not re.fullmatch(r'(?:wpad-basic-mbedtls|hostapd-common|wifi-scripts)-[a-zA-Z0-9.~+-]+-r1001\.apk', name):
            raise ValueError('Unexpected WPA3 APK: ' + name)
        if name in expected or not re.fullmatch(r'[a-f0-9]{64}', checksum):
            raise ValueError('Invalid WPA3 APK manifest')
        actual = hashlib.sha256((directory / name).read_bytes()).hexdigest()
        if actual != checksum:
            raise ValueError('WPA3 APK checksum mismatch: ' + name)
        expected[name] = checksum
    for pkg in ('wpad-basic-mbedtls', 'hostapd-common', 'wifi-scripts'):
        if sum(n.startswith(pkg + '-') for n in expected) != 1:
            raise ValueError('Expected one WPA3 package: ' + pkg)
    if len(expected) != 3 or set(p.name for p in directory.glob('*.apk')) != set(expected):
        raise ValueError('Unexpected extra WPA3 APKs')
    return {'build_id': build_id(), 'apks': expected}


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path)
    args = parser.parse_args()
    print(inspect(args.directory)['build_id'])
