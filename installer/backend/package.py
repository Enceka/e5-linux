"""Content identity permits moved directories and compatible repair releases."""
import json
from pathlib import Path
import re

from .state import sha


def safe_file(root, name):
    path = (root / name).resolve()
    if not path.is_relative_to(root.resolve()) or not path.is_file():
        raise ValueError('Missing or unsafe package file / 安装包文件缺失或路径不安全: ' + name)
    return path


def inspect_package(directory):
    root = Path(directory).resolve()
    mu = root / 'desktop/manifest.json'
    if mu.is_file():
        manifest = json.loads(mu.read_text(encoding='utf-8'))
        checks = {**manifest['magisk'], **manifest['desktop']}
        adapter, profile, layout, kernel = 'mu300', 'mu300-family', 'mu300root-container', manifest['kernel']
        mapping = manifest.get('magisk_layout', {})
        names = [mapping.get(n, n) for n in ('boot-linux.img', 'mu300-openwrt.tar.gz', 'busybox',
                                             'rootfs-critical.sha256', 'rootfs.requirements')]
        names += [n for n in checks if n.startswith('desktop/files/boot/repair/')]
    else:
        profile_data = json.loads(safe_file(root, 'files/device-profile.json').read_text())
        adapter, profile, layout, kernel = 'e5', profile_data['profile'], 'e5root-ext4', 'e5-boot-v2'
        if profile not in ('e5', 'm8', 't551m'):
            raise ValueError('Unsupported device profile / 不支持的机型')
        checks = {}
        for line in safe_file(root, 'files/SHA256SUMS').read_text().splitlines():
            digest, name = line.split(None, 1)
            checks[name.strip().removeprefix('*')] = digest
        names = ['files/boot.img', 'files/openwrt.ext4.gz', 'files/ext4-tools.tar']
    for name, expected in checks.items():
        if not re.fullmatch('[a-f0-9]{64}', expected) or sha(safe_file(root, name)) != expected:
            raise ValueError('Package checksum mismatch / 安装包校验失败: ' + name)
    payloads = {name: sha(safe_file(root, name)) for name in names}
    if not (root/'OpenWrt-Installer.py').is_file():
        raise ValueError('Missing compatible Python entry / 缺少兼容安装入口')
    return {'protocol': 1, 'adapter': adapter, 'profile': profile, 'layout': layout, 'kernel': kernel,
            'payloads': payloads, 'path': str(root), 'name': root.name}
