#!/usr/bin/env python3
"""Upload an update over authenticated SSH; no inbound PC firewall rule needed."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import socket
import struct
import sys
import time
import uuid
GUI = None


def image_capacity(client):
    if GUI:
        return int(GUI.ctx.record['plan']['openwrt_bytes'])
    # Use raw SSH stdout, without requiring od/hexdump or SFTP on OpenWrt.
    dev = execute(client, "readlink -f $(awk '$2==\"/\" {print $1}' /proc/mounts | tail -1)").strip()
    if not re.fullmatch(r'/dev/(?:block/)?(?:mmcblk\d+(?:p\d+)?|loop\d+)', dev):
        raise ValueError('Cannot identify the current image root')
    _, out, err = client.exec_command(f'dd if={dev} bs=1024 skip=1 count=1 2>/dev/null', timeout=15)
    raw = out.read()
    err.read()
    if out.channel.recv_exit_status() or len(raw) != 1024 or raw[56:58] != b'\x53\xef':
        raise ValueError('Cannot read the current ext4 image capacity')
    shift = struct.unpack_from('<I', raw, 24)[0]
    blocks = struct.unpack_from('<I', raw, 4)[0]
    if struct.unpack_from('<I', raw, 96)[0] & 0x80:
        blocks |= struct.unpack_from('<I', raw, 336)[0] << 32
    if shift > 6 or not blocks:
        raise ValueError('Invalid ext4 image capacity')
    return blocks * (1024 << shift)


def execute(client, command, timeout=1800):
    channel = client.get_transport().open_session()
    channel.settimeout(timeout)
    channel.exec_command('set -eu\n' + command)
    result = bytearray()
    deadline = time.monotonic() + timeout
    while not channel.exit_status_ready() or channel.recv_ready() or channel.recv_stderr_ready():
        if time.monotonic() > deadline:
            channel.close()
            raise TimeoutError('device update command timed out')
        for ready, read in ((channel.recv_ready, channel.recv), (channel.recv_stderr_ready, channel.recv_stderr)):
            if ready():
                data = read(65536)
                result.extend(data)
                print(data.decode('utf-8', 'replace'), end='', flush=True)
        time.sleep(.03)
    status = channel.recv_exit_status()
    channel.close()
    if status:
        raise RuntimeError(f'device command failed (exit {status}); no success was reported')
    return result.decode('utf-8', 'replace')


def upload(client, path, destination):
    size = path.stat().st_size
    channel = client.get_transport().open_session()
    channel.settimeout(120)
    channel.exec_command('umask 077; cat > ' + shlex.quote(destination))
    count = 0; digest = hashlib.sha256(); last = 0
    started = time.monotonic()
    with path.open('rb') as stream:
        while data := stream.read(262144):
            channel.sendall(data); digest.update(data); count += len(data)
            if GUI: GUI.transfer(path.name, count, size, started)
            if time.monotonic() - last >= 1:
                print(f'\r   {path.name}: {count >> 20}/{size >> 20} MiB', end='', flush=True)
                last = time.monotonic()
    channel.shutdown_write()
    error = channel.makefile_stderr().read().decode('utf-8', 'replace')
    status = channel.recv_exit_status(); channel.close()
    print()
    if status:
        raise RuntimeError('upload failed: ' + error)
    expected = digest.hexdigest()
    got = execute(client, 'sha256sum ' + shlex.quote(destination)).split()[0]
    if got != expected:
        raise RuntimeError('uploaded file checksum mismatch: ' + path.name)


def main():
    import paramiko
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--package', type=Path, required=True)
    p.add_argument('--host', required=True)
    p.add_argument('--raw-size', type=int, required=True)
    p.add_argument('--raw-sha256', required=True)
    p.add_argument('--check-only', action='store_true', help='validate the connected device without staging or flashing')
    a = p.parse_args()
    files = a.package / 'files'
    profile = json.loads((files / 'device-profile.json').read_text())['profile'] if (files / 'device-profile.json').exists() else 'e5'
    client = paramiko.SSHClient()
    # USB-connected devices reuse the same management address. Keep trust
    # within this connection rather than pinning that IP to one installation.
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(a.host, username='root', password=GUI.password if GUI else os.environ['E5_TELNET_PASS'],
                   look_for_keys=False, allow_agent=False, timeout=15, auth_timeout=20)
    if GUI: GUI.validate_ssh(client)
    stage = None
    try:
        execute(client, '[ "$(id -u)" = 0 ] && [ "$(cat /etc/e5/device-profile)" = ' + shlex.quote(profile) + ' ]')
        # Detection and capacity checks precede uploads and all boot writes.
        layout = execute(client, 'if [ -f /etc/e5/part-root ]; then echo part; '
            'elif [ -f /etc/e5/sd-root ]; then echo sd; else echo image; fi').strip()
        capacity_env = ''
        if layout == 'image':
            capacity = image_capacity(client)
            if capacity < a.raw_size:
                raise ValueError('New image exceeds the installed filesystem capacity; nothing staged')
            capacity_env = 'E5_IMAGE_FS_BYTES=' + str(capacity) + ' '
        boot = json.loads((files / 'boot.json').read_text())
        if layout in ('part', 'sd') and not boot.get('part_update'):
            raise RuntimeError('this package has no independent-partition update support; use a newer package')
        if layout == 'sd' and not boot.get('tf_update'):
            raise RuntimeError('this package has no single-root TF update support; rebuild the package')
        if layout in ('part', 'sd'):
            execute(client, 'dev=$(cat /run/e5linux/' + layout + '-root-dev); '
                '[ -b "$dev" ] && [ "$(awk \'$2=="/" {print $1}\' /proc/mounts | tail -1)" = "$dev" ]; '
                'sectors=$(cat /sys/class/block/${dev##*/}/size); '
                'test "$((sectors * 512))" -ge ' + str(a.raw_size))
        if a.check_only:
            print('Update preflight passed / 更新预检查通过: ' + profile + ', ' + layout)
            return
        stage = '/tmp/e5-update-' + uuid.uuid4().hex
        required = sum((files / n).stat().st_size for n in ('boot.img', 'openwrt.ext4.gz', 'ext4-tools.tar')) + (64 << 20)
        execute(client, 'test "$(df -Pk /tmp | awk \'NR==2 {print $4}\')" -gt ' + str((required+1023)//1024) + '; mkdir -m 700 ' + stage)
        # Internal partition updates carry the selection in the boot header,
        # allowing encrypted Android userdata to stay completely unmounted.
        with __import__('tempfile').TemporaryDirectory() as temporary:
            image = bytearray((files / 'boot.img').read_bytes())
            if layout == 'part':
                image[44:1580] = b'e5.part_v=2 e5.root=part e5.part_update=1'.ljust(1536, b'\0')
            head = Path(temporary) / 'boot-head.img'
            head.write_bytes(image[:boot['persist_log_offset']])
            for name in ('openwrt.ext4.gz', 'ext4-tools.tar', 'device-install-image.sh',
                         'device-flash-boot.sh', 'device-stage-part-update.sh', 'e5-gpt'):
                upload(client, files / name, stage + '/' + name)
            upload(client, head, stage + '/boot-head.img')
            command = ('umask 077; mkdir -p /run/e5-upgrade; '
                '[ ! -L /run/e5-upgrade ] && [ "$(stat -c %u:%a /run/e5-upgrade)" = 0:700 ]; '
                '[ ! -L /run/e5-upgrade/lock ]; exec 8>>/run/e5-upgrade/lock; '
                'flock -n 8 || { echo "another upgrade is running"; exit 1; }; '
                'export E5_UPGRADE_LOCK_HELD=1; ' +
                capacity_env + 'E5_IMAGE_SIZE=' + str(a.raw_size) + ' E5_IMAGE_SHA256=' + shlex.quote(a.raw_sha256) +
                ' E5_UPDATE_PROFILE=' + shlex.quote(profile) + ' sh ' + stage + '/device-stage-part-update.sh ' + stage)
            command += '; sh ' + stage + '/device-flash-boot.sh ' + stage + '/boot-head.img ' + \
                    hashlib.sha256(head.read_bytes()).hexdigest() + ' ' + str(boot['persist_log_offset'] >> 20)
            # Publish an internal update request only after boot readback passes.
            if layout in ('part', 'sd'):
                command += '; mv /.e5-update/request.ready /.e5-update/request; sync'
            else:
                command += '; e5-os openwrt'
            command += '; echo "== all uploaded files verified; rebooting"; (sleep 3; reboot) </dev/null >/dev/null 2>&1 &'
            if GUI: GUI.action('update-commit', lambda: execute(client, command))
            else: execute(client, command)
            print('Update verified; rebooting / 更新已校验，正在重启', flush=True)
    finally:
        if stage:
            try:
                execute(client, 'rm -rf ' + shlex.quote(stage), timeout=15)
            except Exception:
                pass  # The device may already have restarted; /tmp is volatile.
        client.close()


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        raise SystemExit('Update failed / 更新失败: ' + str(error))
