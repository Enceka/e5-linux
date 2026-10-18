#!/usr/bin/env python3
"""Stage parent-owned installer extensions after composing device overlays."""
import argparse
from pathlib import Path
import shutil

HERE = Path(__file__).resolve().parent


def stage(root, system):
    root = Path(root).resolve()
    if root == Path('/') or not root.is_dir():
        raise ValueError('Choose an existing image root directory')
    source = HERE / 'installer-runtime' / system
    if system not in ('openwrt', 'debian'):
        raise ValueError('Unsupported installer runtime: ' + system)
    for asset in sorted(source.rglob('*')):
        if not asset.is_file():
            continue
        target = root / asset.relative_to(source)
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.is_symlink():
            target.unlink()
        shutil.copyfile(asset, target)
        target.chmod(0o755)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', required=True, type=Path)
    parser.add_argument('--system', required=True, choices=('openwrt', 'debian'))
    args = parser.parse_args()
    stage(args.root, args.system)
