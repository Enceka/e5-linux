#!/usr/bin/env python3
"""Stage OpenWrt aarch64/musl f2fs tools and ucode for early recovery and the
internal-partition install.

Input is an extracted target rootfs (or a maintenance tool root), not host libs.
resize.f2fs is fsck.f2fs under a second name (f2fs-tools dispatches on argv[0]);
ucode and its fs module run the same e5-gpt the running system uses.
The resulting private bundle is consumed by build-boot-image.py.
"""
import argparse
import hashlib
import json
import struct
from pathlib import Path

FILES = ('sbin/fsck.f2fs', 'sbin/resize.f2fs', 'lib/ld-musl-aarch64.so.1', 'lib/libf2fs.so.10',
         'lib/libuuid.so.1', 'lib/libgcc_s.so.1',
         'usr/bin/ucode', 'lib/libucode.so.20230711', 'lib/libjson-c.so.5', 'usr/lib/ucode/fs.so',
         'usr/sbin/resize2fs', 'lib/libe2p.so.2', 'lib/libext2fs.so.2', 'lib/libcom_err.so.0')

def stage(root, out):
    manifest = {}
    for name in FILES:
        source = root/name
        if not source.is_file():
            source = root/'usr'/name
        payload = source.read_bytes()
        if payload[:6] != b'\x7fELF\x02\x01' or struct.unpack_from('<H', payload, 18)[0] != 183:
            raise ValueError('Expected aarch64 ELF: '+name)
        dest = out/name
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(payload)
        dest.chmod(0o755)
        manifest[name] = hashlib.sha256(payload).hexdigest()
    (out/'manifest.json').write_text(json.dumps({'sha256':manifest}, indent=2)+'\n')
    print('Staged ARM64 fsck.f2fs bundle:', out)

if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root', type=Path, required=True)
    p.add_argument('--out', type=Path, default=Path(__file__).resolve().parent.parent/'out/boot/f2fs-tools')
    a = p.parse_args()
    stage(a.root, a.out)
