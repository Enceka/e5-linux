#!/usr/bin/env python3
"""Bundle musl ARM64 ext4 tools and their ELF dependencies for rooted Android."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import tarfile
import tempfile


def build(root, out):
    root = root.resolve()
    with tempfile.TemporaryDirectory() as directory:
        stage = Path(directory)
        pending = ['usr/sbin/e2fsck', 'usr/sbin/resize2fs', 'lib/ld-musl-aarch64.so.1']
        hashes = {}
        while pending:
            name = pending.pop()
            if name in hashes:
                continue
            source = root / name
            data = source.read_bytes()
            if data[:6] != b'\x7fELF\x02\x01' or int.from_bytes(data[18:20], 'little') != 183:
                raise ValueError('Expected ARM64 ELF: ' + name)
            target = stage / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            target.chmod(0o755)
            hashes[name] = hashlib.sha256(data).hexdigest()
            # OpenWrt sstrip removes section headers. Parse the dynamic segment.
            dynamic = subprocess.check_output(['readelf', '-D', '-d', str(source)], text=True,
                                              stderr=subprocess.DEVNULL)
            for lib in re.findall(r'\(NEEDED\).*\[(.*?)\]', dynamic):
                candidates = [d + '/' + lib for d in ('lib', 'usr/lib') if (root / d / lib).is_file()]
                if not candidates:
                    raise ValueError('Missing dependency: ' + lib)
                pending.append(candidates[0])
        name = 'ext4-geometry.sh'
        data = (Path(__file__).resolve().parent / 'bundle' / name).read_bytes().replace(b'\r\n', b'\n')
        (stage / name).write_bytes(data)
        hashes[name] = hashlib.sha256(data).hexdigest()
        (stage / 'manifest.json').write_text(json.dumps({'sha256': hashes}, indent=2) + '\n')
        (stage / 'SHA256SUMS').write_text(''.join(v + '  ' + k + '\n' for k, v in sorted(hashes.items())))
        out.parent.mkdir(parents=True, exist_ok=True)
        with tarfile.open(out, 'w') as archive:
            for p in sorted(stage.rglob('*')):
                if p.is_file():
                    info = archive.gettarinfo(str(p), arcname=p.relative_to(stage).as_posix())
                    info.uid = info.gid = 0
                    info.uname = info.gname = 'root'
                    with p.open('rb') as stream:
                        archive.addfile(info, stream)
        print(out, hashes)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    build(args.root, args.out)
