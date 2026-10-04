#!/usr/bin/env python3
"""Record release sources/time, then verify a flash bundle before publication."""
import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tarfile
import time
import zipfile

TOP = Path(__file__).resolve().parents[1]
UTC8 = timezone(timedelta(hours=8))
RELEASE = TOP / 'out/release'


def digest(stream):
    result = hashlib.sha256()
    while data := stream.read(1 << 20):
        result.update(data)
    return result.hexdigest()


def file_digest(path):
    with path.open('rb') as stream:
        return digest(stream)


def revision(path):
    return subprocess.check_output(['git', '-C', str(path), 'rev-parse', 'HEAD'], text=True).strip()


def outputs(values):
    target = os.environ.get('GITHUB_OUTPUT')
    if target:
        with open(target, 'a') as stream:
            for name, value in values.items():
                stream.write(f'{name}={value}\n')


def prepare():
    epoch = int(time.time())
    started = datetime.fromtimestamp(epoch, UTC8)
    stamp = started.strftime('%Y%m%d-%H%M%S')
    ver = os.environ.get('E5_WRT_VER', '25.12.5')
    if not re.fullmatch(r'\d+\.\d+\.\d+', ver):
        raise ValueError('invalid OpenWrt version')
    sources = {name: {'repository': repo, 'revision': revision(path)} for name, repo, path in [
        ('e5-linux', os.environ.get('GITHUB_REPOSITORY', 'Enceka/e5-linux'), TOP),
        ('kernel', 'Enceka/linux-lts-e5', TOP / 'linux-lts-e5'),
        ('infoscreen', 'Enceka/infoscreen', TOP / 'ci/infoscreen'),
        ('plugins', 'Enceka/infoscreen-plugins', TOP / 'ci/infoscreen-plugins'),
    ]}
    RELEASE.mkdir(parents=True, exist_ok=True)
    info = {'build_epoch': epoch, 'build_started_at': started.isoformat(timespec='seconds'),
            'timestamp': stamp, 'openwrt_version': ver, 'sources': sources,
            'bootstrap_sha256': os.environ.get('E5_CI_INPUTS_SHA256'),
            'run_url': os.environ.get('E5_RUN_URL')}
    (RELEASE / 'build.json').write_text(json.dumps(info, indent=2) + '\n')
    env = os.environ.get('GITHUB_ENV')
    if env:
        with open(env, 'a') as stream:
            stream.write(f'E5_BUILD_EPOCH={epoch}\n')
            stream.write('KBUILD_BUILD_TIMESTAMP=' + started.strftime('%a %b %d %H:%M:%S %z %Y') + '\n')
    outputs({'timestamp': stamp, 'release_tag': f'build-{stamp}-{sources["e5-linux"]["revision"][:7]}'})
    print(info['build_started_at'])


def audit_root(info):
    expected = {}
    for source, relative, prefix in [('infoscreen', 'root', ''), ('plugins', 'plugins/phone', 'etc/e5-infoscreen/plugins/phone/')]:
        root = TOP / 'ci' / ('infoscreen' if source == 'infoscreen' else 'infoscreen-plugins')
        files = subprocess.check_output(['git', '-C', str(root), 'ls-files', relative], text=True).splitlines()
        for item in files:
            tail = Path(item).relative_to(relative).as_posix()
            # rc/config may be changed while packages are assembled; check all UI/backend files.
            if source == 'infoscreen' and not tail.startswith(('usr/', 'www/')):
                continue
            expected[prefix + tail] = file_digest(root / item)
    found, versions, modules = {}, {}, set()
    rootfs = TOP / 'work/openwrt' / f'e5-openwrt-{info["openwrt_version"]}-generic-rootfs.tar.gz'
    if not rootfs.is_file():
        raise ValueError(f'root filesystem archive was not built: {rootfs}; inspect bundle-build.log for the original failure')
    forbidden = re.compile(r'^(?:lib/firmware/(?:wcnmodem|gnssmodem|l_agdsp|wifi_board|sprd/)|'
                           r'opt/e5/android/.+|etc/e5/install\.conf|etc/dropbear/dropbear_.+_host_key|etc/ssh/ssh_host_)')
    wanted = {'usr/share/e5-infoscreen/VERSION', 'etc/e5-infoscreen/plugins/phone/manifest.json',
              'etc/e5/build-time', 'etc/machine-id'}
    with tarfile.open(rootfs, 'r|gz') as archive:
        for entry in archive:
            name = entry.name.removeprefix('./')
            if forbidden.match(name):
                raise ValueError('device-specific file in generic image: ' + name)
            if name.startswith('lib/modules/') and entry.isfile() and name.endswith('.ko'):
                modules.add(name.split('/')[2])
            if entry.isfile() and (name in expected or name in wanted):
                stream = archive.extractfile(entry)
                if name in wanted:
                    data = stream.read()
                    versions[name] = data
                    found[name] = hashlib.sha256(data).hexdigest()
                else:
                    found[name] = digest(stream)
    missing = set(expected) - set(found)
    different = [name for name in expected if name in found and expected[name] != found[name]]
    if missing or different:
        raise ValueError(f'root source mismatch: missing={sorted(missing)}, changed={different}')
    kernel = (TOP / 'upstream/out-release/kernel.release').read_text().strip()
    if modules != {kernel}:
        raise ValueError('root modules do not all match the release kernel')
    if int(versions['etc/e5/build-time']) != info['build_epoch']:
        raise ValueError('root image build time differs from CI compile start')
    if versions.get('etc/machine-id', b'').strip():
        raise ValueError('generic image has a machine ID')
    info.update({'kernel_release': kernel, 'infoscreen_version': versions['usr/share/e5-infoscreen/VERSION'].decode().strip(),
                 'phone_version': json.loads(versions['etc/e5-infoscreen/plugins/phone/manifest.json'])['version']})


def verify():
    info = json.loads((RELEASE / 'build.json').read_text())
    audit_root(info)
    # Ensure nobody advanced one of the checkouts during the build.
    for name, path in [('e5-linux', TOP), ('kernel', TOP / 'linux-lts-e5'),
                       ('infoscreen', TOP / 'ci/infoscreen'), ('plugins', TOP / 'ci/infoscreen-plugins')]:
        if revision(path) != info['sources'][name]['revision']:
            raise ValueError('source revision changed: ' + name)
    glob = f'e5-openwrt-flash-{info["openwrt_version"]}-mainline-{info["timestamp"]}-*.tar.gz'
    candidates = list((TOP / 'out/openwrt').glob(glob))
    if len(candidates) != 1:
        raise ValueError('expected exactly one completed bundle for this build timestamp')
    tarpath = candidates[0]
    stem = tarpath.name.removesuffix('.tar.gz')
    zipath = tarpath.with_name(stem + '.zip')
    members, data = {}, {}
    with tarfile.open(tarpath, 'r|gz') as archive:
        for entry in archive:
            if not entry.isfile():
                continue
            if not entry.name.startswith(stem + '/'):
                raise ValueError('unexpected archive root')
            name = entry.name[len(stem) + 1:]
            if name in members:
                raise ValueError('duplicate bundle member: ' + name)
            stream = archive.extractfile(entry)
            if name in ('SHA256SUMS', 'files/VERSION', 'files/boot.json'):
                content = stream.read()
                data[name] = content
                members[name] = hashlib.sha256(content).hexdigest()
            else:
                members[name] = digest(stream)
    listed = {}
    for line in data['SHA256SUMS'].decode().splitlines():
        checksum, name = line.split(None, 1)
        listed[name] = checksum
    expected_members = {name: checksum for name, checksum in members.items() if name.startswith(('files/', 'scripts/')) or name in ('flash.py', 'flash.sh', 'flash.cmd')}
    if listed != expected_members:
        raise ValueError('bundle SHA256SUMS mismatch')
    for name, path in [('files/boot.img', TOP / 'work/boot-linux-slotb-bundle-mainline.img'),
                       ('files/openwrt.ext4.gz', TOP / 'out/openwrt' / f'e5-openwrt-{info["openwrt_version"]}-generic.ext4.gz')]:
        if members[name] != file_digest(path):
            raise ValueError('bundle uses a different build output: ' + name)
    boot = json.loads(data['files/boot.json'])
    if boot['overlay_files'] or boot['sha256'] != members['files/boot.img']:
        raise ValueError('boot image contains an overlay or mismatches its manifest')
    version = data['files/VERSION'].decode()
    if info['build_started_at'] not in version or info['kernel_release'] not in version:
        raise ValueError('bundle version/time mismatch')
    with zipfile.ZipFile(zipath) as archive:
        if archive.testzip() is not None:
            raise ValueError('ZIP CRC check failed')
        for name, checksum in members.items():
            with archive.open(stem + '/' + name) as stream:
                if digest(stream) != checksum:
                    raise ValueError('ZIP differs from tar: ' + name)
    info['assets'] = {}
    for path in (tarpath, zipath):
        checksum = file_digest(path)
        info['assets'][path.name] = {'sha256': checksum, 'bytes': path.stat().st_size}
        destination = RELEASE / path.name
        os.link(path, destination)
    (RELEASE / 'SHA256SUMS').write_text(''.join(f'{item["sha256"]}  {name}\n' for name, item in info['assets'].items()))
    (RELEASE / 'build.json').write_text(json.dumps(info, indent=2) + '\n')
    refs = '\n'.join(f'- {name}: `{item["repository"]}@{item["revision"]}`' for name, item in info['sources'].items())
    (RELEASE / 'release-notes.md').write_text(
        f'编译时间（UTC+8）：**{info["build_started_at"]}**\n\n'
        f'OpenWrt {info["openwrt_version"]} · 内核 `{info["kernel_release"]}` · '
        f'信息屏 {info["infoscreen_version"]} · 电话插件 {info["phone_version"]}\n\n'
        '下载 ZIP 或 TAR.GZ，解压后运行 `flash.cmd`（Windows）或 `./flash.sh`（macOS/Linux）。'
        '已安装 OpenWrt 使用 `--update` 保留设置。刷入说明在包内 README。\n\n'
        '镜像不含设备固件和 Android vendor 运行库；安装器从目标设备提取。'
        'CI 已验证文件和模块一致性，硬件实测仍需在 E5 上进行。\n\n'
        f'源码版本：\n\n{refs}\n\n[构建记录]({info.get("run_url")})\n')
    outputs({'bundle_name': stem, 'release_title': 'E5 OpenWrt ' + info['build_started_at']})
    print('Verified release:', stem)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['prepare', 'verify'])
    args = parser.parse_args()
    try:
        (prepare if args.command == 'prepare' else verify)()
    except (ValueError, KeyError) as error:
        parser.exit(1, 'Release check: ' + str(error) + '\n')
