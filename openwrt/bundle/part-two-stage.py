"""Destructive userdata preparation followed by installation from stock Android.

Loaded by flash.py (also by its frozen exe); no device access on import.
The PC transaction survives factory reset. No OpenWrt payload is stored in data
until stock recovery has finished and the user grants adb/su again.
"""
import hashlib
import json
from pathlib import Path
import re
import struct
import time
import uuid


def boot_command(image, option):
    if image[:8] != b'ANDROID!' or struct.unpack_from('<I', image, 40)[0] != 4:
        raise ValueError('expected Android boot header v4')
    command = image[44:1580].split(b'\0', 1)[0].decode('ascii')
    if 'e5.part_v=2' not in command.split():
        raise ValueError('boot image lacks two-stage installer v2; rebuild the package first')
    if any(x.startswith(('e5.part_prepare=', 'e5.root=')) for x in command.split()):
        raise ValueError('boot already has a partition installation override')
    updated = (command + ' ' + option).encode('ascii')
    if len(updated) >= 1536:
        raise ValueError('boot command line is full')
    result = bytearray(image)
    result[44:1580] = updated.ljust(1536, b'\0')
    return bytes(result)


def save(path, state):
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding='utf-8')
    tmp.replace(path)


def validate_state(state):
    if state.get('version') != 2 or state.get('phase') not in ('prepared', 'awaiting-android', 'writing', 'installed', 'complete'):
        raise ValueError('invalid transaction or unsupported state')
    if not re.fullmatch('[0-9a-f]{32}', state.get('token', '')):
        raise ValueError('invalid transaction token')
    for key in ('need', 'target', 'raw_size'):
        value = state.get(key)
        if type(value) is not int or not 0 < value < 1 << 40:
            raise ValueError('invalid transaction size')
    if state['need'] % 2048 or state['target'] % 2048 or state.get('grow') not in (0, 1):
        raise ValueError('unaligned transaction size')
    for key in ('apn', 'ssid', 'key'):
        value = state.get(key)
        if not isinstance(value, str) or any(c in value for c in "'\r\n\x00"):
            raise ValueError('invalid saved settings')


def probe(g):
    raw = g['su_checked']('读取设备及分区身份 / reading device geometry',
        'for u in /sys/class/block/mmcblk*p*/uevent; do '
        'if grep -qx PARTNAME=userdata "$u" || grep -qx PARTNAME=e5root "$u"; then '
        'n=$(basename "$(dirname "$u")"); d=${n%p*}; '
        'printf "%s " "$n"; cat /sys/class/block/$d/device/cid | tr "\\n" " "; '
        'cat /sys/class/block/$n/start /sys/class/block/$n/size | tr "\\n" " "; '
        'grep ^PARTNAME= "$u"; fi; done')
    rows = {}
    for line in raw.splitlines():
        fields = line.split()
        if len(fields) != 5:
            continue
        node, cid, start, size, name = fields
        if not re.fullmatch(r'mmcblk\dp\d+', node) or not re.fullmatch('[0-9a-f]{32}', cid):
            raise ValueError('unsupported device identity')
        name = name.removeprefix('PARTNAME=') if hasattr(str, 'removeprefix') else name[9:]
        if name in rows:
            raise ValueError('ambiguous partition name')
        rows[name] = dict(node=node, cid=cid, start=int(start), size=int(size))
    return rows


def verify_geometry(state, rows):
    data, root = rows.get('userdata', {}), rows.get('e5root', {})
    expected = state['data']
    if (data.get('cid') != expected['cid'] or data.get('node') != expected['node'] or
        data.get('start') != expected['start'] or data.get('size') != state['target'] or
        root.get('cid') != expected['cid'] or root.get('start') != state.get('root_start', expected['start'] + state['target']) or
        root.get('size') != state['need'] or
        root.get('node', '').split('p')[0] != expected['node'].split('p')[0]):
        raise ValueError('device/partition geometry differs from the saved transaction; nothing written')
    return '/dev/block/' + root['node']


def backup(g, remote, local):
    temp = g['TMP'] + '/e5-prepare-backup'
    g['su_checked']('备份 / backup', f'dd if={remote} of={temp} bs=1048576; chmod 644 {temp}')
    g['adb']('pull', temp, str(local), check=True)
    if g['sha256'](str(local)) != g['su'](f'sha256sum {remote}').split()[0]:
        raise ValueError('device backup checksum mismatch')
    g['su_checked']('清理临时备份 / cleanup', f'rm -f {temp}')


def backup_gpt(g, data, directory):
    disk = data['node'].split('p')[0]
    sectors = int(g['su_checked']('读取磁盘容量 / disk capacity', f'cat /sys/class/block/{disk}/size').strip())
    if sectors <= data['start'] + data['size']:
        raise ValueError('invalid disk bounds')
    for name, start, count in [('gpt-primary.bin', 0, 34), ('gpt-backup.bin', sectors-33, 33)]:
        remote = '/data/local/tmp/e5-gpt-backup'
        g['su_checked']('备份 GPT / backing up GPT',
            f'dd if=/dev/block/{disk} of={remote} bs=512 skip={start} count={count}; chmod 644 {remote}')
        local = directory/name
        g['adb']('pull', remote, str(local), check=True)
        if local.stat().st_size != count*512 or g['sha256'](str(local)) != g['su'](f'sha256sum {remote}').split()[0]:
            raise ValueError('GPT backup failed')
        g['su_checked']('清理临时 GPT / cleanup', f'rm -f {remote}')


def flash_boot(g, path):
    remote = g['TMP'] + '/e5-two-stage-boot.img'
    g['push'](str(path), remote, 'boot.img')
    g['su_checked']('写入并校验 B 槽 / writing slot B',
        f'dd if={remote} of=/dev/block/by-name/boot_b bs=1048576 conv=fsync; '
        f'[ "$(sha256sum /dev/block/by-name/boot_b | cut -d " " -f1)" = {g["sha256"](str(path))} ]; '
        f'rm -f {remote}', **({'effect': 'boot-image-' + path.name} if g.get('GUI') else {}))


def start(g, a, node, part_mib, data_mib, grow, raw_size, apn, ssid, key):
    files = Path(g['F'])
    normal = (files / 'boot.img').read_bytes()
    # Refuse stale packages BEFORE modifying boot chain or partitions.
    boot_command(normal, 'e5.root=part')
    for name in ('ext4-tools.tar', 'part-write.sh'):
        if not (files / name).is_file():
            raise ValueError('new package required: missing ' + name)
    rows = probe(g)
    if 'e5root' in rows or rows.get('userdata', {}).get('node') != node:
        raise ValueError('unexpected existing root or userdata')
    data = rows['userdata']
    if data['start'] % 2048 or data_mib * 2048 + part_mib * 2048 > data['size']:
        raise ValueError('unaligned or oversized partition plan')
    # Stock recovery, not a mainline mkfs on encrypted raw sectors, performs
    # Android's wipe including device-specific hooks and metadata setup.
    # Zero BCB only (0..2047, AOSP bootloader_message); the vendor flashing
    # tool's erase-userdata writes the same 0x800 block with the same strings.
    bcb = g['su_checked']('检查 recovery 请求 / checking recovery request',
        'dd if=/dev/block/by-name/misc bs=1 count=2048 2>/dev/null | od -An -tx1 -v')
    if any(bytes.fromhex(bcb)):
        raise ValueError('an existing recovery/OTA message is present; finish it before preparing data')
    directory = Path(g['GUI'].backup_base() if g.get('GUI') else g['B']) / 'backups' / ('part-' + time.strftime('%Y%m%d-%H%M%S') + '-' + uuid.uuid4().hex[:8])
    directory.mkdir(parents=True)
    path = directory / 'transaction.json'
    bc = g['read_boot_control']()
    backup(g, '/dev/block/by-name/boot_b', directory / 'boot-b-before.img')
    backup_gpt(g, data, directory)
    (directory / 'boot-control-before.bin').write_bytes(bc)
    (directory / 'bcb-before.bin').write_bytes(bytes.fromhex(bcb))
    token = uuid.uuid4().hex
    state = dict(version=2, phase='prepared', token=token, serial=g['adb']('get-serialno').strip(),
        model=g['sh']('getprop ro.product.model').strip(), data=data,
        target=data_mib * 2048, need=part_mib * 2048, grow=grow,
        boot_sha=g['sha256'](str(files/'boot.img')), image_sha=g['sha256'](str(files/'openwrt.ext4.gz')),
        raw_size=raw_size, apn=apn, ssid=ssid, key=key)
    # State lives on the PC, including credentials; do not publish backups.
    save(path, state)
    if g.get('GUI'): g['GUI'].saved(path, state)
    request = ':'.join(map(str, (token, data['cid'], node, data['start'], data['size'],
                                state['target'], state['need'], bc.hex())))
    temporary = directory / 'boot-prepare.img'
    temporary.write_bytes(boot_command(normal, 'e5.part_prepare=' + request))
    g['bootchain']('sync')
    g['su_checked']('保存启动链备份 / retaining boot-chain backups',
        'mkdir -p /data/adb/e5-bootchain; tar -cf /data/local/tmp/e5-chain-backup.tar -C /data/adb e5-bootchain; '
        'chmod 644 /data/local/tmp/e5-chain-backup.tar')
    g['adb']('pull', '/data/local/tmp/e5-chain-backup.tar', str(directory/'bootchain.tar'), check=True)
    if g['sha256'](str(directory/'bootchain.tar')) != g['su']('sha256sum /data/local/tmp/e5-chain-backup.tar').split()[0]:
        raise ValueError('boot chain PC backup checksum mismatch')
    flash_boot(g, temporary)
    g['arm_slot_b']()
    print('\n第一阶段已就绪：重启后重建分区，进入原厂 recovery 清空数据，再回 Android。')
    print('首次开机的离线缩容通常需要数分钟，数据较多或闪存较慢时更久；请保持供电，不要中断。')
    print('缩容完成后会自动重启；原厂 recovery 清空数据还可能再次重启，然后回到 Android。')
    print('The first offline resize can take several minutes; keep power connected. It reboots after resizing.')
    print('请重新完成首次设置、开启 USB 调试，并恢复 Magisk/Shell root 授权。')
    print('续装记录（请保留）：' + str(path))
    print('如 recovery 要求确认清空数据，请在设备上确认；不要重复运行第一阶段。')
    state['phase'] = 'awaiting-android'
    save(path, state)
    if g.get('GUI'): g['GUI'].saved(path, state)
    # The erase was confirmed in install_part. Reboot is part of this two-stage
    # operation, unlike the legacy path which remains manually rebooted.
    g['adb']('reboot', check=True)
    wait_android(g, a, path, state)


def wait_android(g, a, path, state):
    if g.get('GUI'): return g['GUI'].wait_android(g, a, path, state)
    print('等待新的 Android 和 USB/Shell 授权；可 Ctrl+C，之后用 --resume-part transaction.json 续装。', flush=True)
    time.sleep(8)
    since = time.monotonic()
    last_notice = 0
    while True:
        ready = False
        try:
            devices = [x.split()[0] for x in g['adb']('devices', timeout=10).splitlines()[1:]
                       if x.strip().endswith('\tdevice')]
            if devices == [state['serial']] and g['sh']('getprop sys.boot_completed', timeout=10).strip() == '1':
                g['android_checks']()
                ready = True
        except (SystemExit, OSError, __import__('subprocess').TimeoutExpired):
            pass
        if ready:
            verify_geometry(state, probe(g))
            break
        if time.monotonic() - last_notice >= 30:
            print('等待 Android 完成设置及 ADB/root 授权，已等待 %d 秒。' % (time.monotonic()-since), flush=True)
            last_notice = time.monotonic()
        time.sleep(5)
    finish(g, a, path, state)


def resume(g, a):
    path = Path(a.resume_part).resolve()
    state = json.loads(path.read_text(encoding='utf-8'))
    validate_state(state)
    g['find_adb']()
    g['android_checks']()
    finish(g, a, path, state)


def installed_settings(g):
    """The settings of the system already on e5root, when it can still be read.

    Best effort on purpose: a rewrite is about to replace that filesystem, so an
    unreadable one must not stop it.  (The M8's e5root was found with a damaged
    journal -- ext4_get_journal_inode: checksum invalid -- which made the mount
    fail; there is nothing to preserve in that case.)  su_checked is wrong here:
    it wraps the command in `set -e`, so a failing mount aborts before any
    fallback.  The values that cannot be read come from the command line and the
    defaults instead.
    """
    mount = '/data/local/tmp/e5-reinstall-mnt'
    text = g['su'](
        f'rm -rf {mount}; mkdir -p {mount}; '
        f'if mount -t ext4 -o ro /dev/block/by-name/e5root {mount} 2>/dev/null; then '
        f'cat {mount}/etc/e5/install.conf 2>/dev/null; umount {mount} 2>/dev/null; '
        f'else echo __E5_NO_OLD_SYSTEM__; fi; true')
    if '__E5_NO_OLD_SYSTEM__' in text:
        print('   现有系统的设置读不出来（e5root 挂载失败，多半文件系统已损坏）；'
              '沿用命令行与默认值 / could not read the installed settings; using the command line and defaults')
    out = {}
    for name, key in (('apn', 'E5_APN'), ('ssid', 'E5_WIFI_SSID'), ('key', 'E5_WIFI_KEY')):
        found = re.search(rf"^{key}='([^'\n]*)'", text, re.M)
        if found:
            out[name] = found.group(1)
    return out


def reinstall(g, a):
    """Overwrite an existing internal-partition installation.

    What a re-install needs, and all it does: userdata, its filesystem and the
    partition table stay untouched, the e5root filesystem is written again from
    this package (with the settings the installed system already has), and
    boot_b is replaced and slot b armed.  No preparation stage, no wipe.
    """
    files = Path(g['F'])
    for name in ('ext4-tools.tar', 'part-write.sh'):
        if not (files / name).is_file():
            raise ValueError('new package required: missing ' + name)
    # Refuse a stale package before touching boot_b or the partition.
    boot_command((files / 'boot.img').read_bytes(), 'e5.root=part')
    g['find_adb']()
    g['android_checks']()
    rows = probe(g)
    if 'e5root' not in rows or 'userdata' not in rows:
        raise ValueError('this device has no internal partition installation to rewrite')
    data, root = rows['userdata'], rows['e5root']
    if data['node'].split('p')[0] != root['node'].split('p')[0]:
        raise ValueError('userdata and e5root are not on the same disk')
    old = installed_settings(g)
    apn = a.apn or old.get('apn', '')
    ssid = a.ssid or old.get('ssid', '') or g['default_hotspot_name']()
    key = a.wifi_key or old.get('key', '') or uuid.uuid4().hex[:12]
    if not 8 <= len(key) <= 63:
        raise ValueError('the hotspot key must have 8-63 characters')
    for value in (apn, ssid, key):
        if any(c in value for c in "'\r\n\x00"):
            raise ValueError('invalid saved settings')
    if not a.y and not g['confirm'](
            f'   覆盖重装 {root["node"]}（{root["size"] * 512 // (1 << 20)} MiB）：'
            'e5root 里现有系统及其配置会被替换，Android 数据与分区表不动。'
            '输入 yes 继续 / type yes to continue: ', word='yes'):
        raise ValueError('aborted: nothing was written')
    state = dict(version=2, phase='writing', token=uuid.uuid4().hex,
                 serial=g['adb']('get-serialno').strip(),
                 model=g['sh']('getprop ro.product.model').strip(),
                 data=data, target=data['size'], need=root['size'], grow=int(getattr(a, 'grow_fs', True) is not False),
                 boot_sha=g['sha256'](str(files/'boot.img')),
                 image_sha=g['sha256'](str(files/'openwrt.ext4.gz')),
                 raw_size=g['gz_usize'](str(files/'openwrt.ext4.gz')),
                 apn=apn, ssid=ssid, key=key)
    validate_state(state)
    directory = Path(g['GUI'].backup_base() if g.get('GUI') else g['B']) / 'reinstalls' / (time.strftime('%Y%m%d-%H%M%S') + '-' + state['token'][:8])
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / 'transaction.json'
    save(path, state)
    if g.get('GUI'): g['GUI'].saved(path, state)
    print(f'''
   覆盖重装 / rewriting the existing installation
   e5root: {root["node"]} ({root["size"] * 512 // (1 << 20)} MiB), userdata 不动
   Android 用户数据、分区表、userdata 文件系统都保留；会重写 e5root 并刷新 boot_b。
   hotspot: {ssid}   密码 / key: {key}
   事务记录 / transaction: {path}''')
    finish(g, a, path, state)


def finish(g, a, path, state):
    if state.get('phase') == 'complete':
        # Resuming a finished transaction is a no-op, not a rewrite of the
        # partition: say so instead of failing validation on the terminal state.
        print(f'这个事务已经完成，不需要重跑：{path}')
        return
    validate_state(state)
    files = Path(g['F'])
    if (g['adb']('get-serialno').strip() != state['serial'] or
        g['sh']('getprop ro.product.model').strip() != state['model'] or
        g['sha256'](str(files/'boot.img')) != state['boot_sha'] or
        g['sha256'](str(files/'openwrt.ext4.gz')) != state['image_sha']):
        raise ValueError('wrong device or different installation package')
    target = verify_geometry(state, probe(g))
    # Android may have updated its boot chain since preparation or the first
    # install. Reinstall/resume needs the same size/BCAB/chain checks as TF.
    g['install_preflight']()
    if state['phase'] != 'installed':
        if state['phase'] != 'writing':
            marker = g['su_checked']('检查分区准备标记 / checking preparation marker', f'head -c 128 {target}')
            if not marker.startswith('E5-PART-PREPARED-V2 ' + state['token'] + '\n'):
                raise ValueError('missing preparation marker; do not overwrite this partition')
        with __import__('tempfile').TemporaryDirectory() as work:
            g['pull_device_files'](work, g['TMP'] + '/e5-device-files.tar')
            g['push'](str(files/'openwrt.ext4.gz'), g['TMP']+'/openwrt.ext4.gz', 'OpenWrt')
            g['push'](str(files/'ext4-tools.tar'), g['TMP']+'/e5-ext4-tools.tar', 'ext4 tools')
            settings = Path(work)/'install.conf'
            settings.write_bytes(("E5_APN='%s'\nE5_WIFI_SSID='%s'\nE5_WIFI_KEY='%s'\nE5_DEFAULT_BOOT='linux'\n" %
                                (state['apn'], state['ssid'], state['key'])).encode('utf-8'))
            g['push'](str(settings), g['TMP']+'/e5-install.conf', 'settings')
            g['push'](str(files/'part-write.sh'), g['TMP']+'/e5-part-write.sh', 'partition installer')
            state['phase'] = 'writing'; save(path, state)
            command = g['android_shell']('/data/local/tmp/e5-part-write.sh',
                       f'{target} {state["need"]} {state["raw_size"]} {int(state["grow"])} {state["token"]}')
            with g['busy']('写入、扩容并校验独立分区 / installing and verifying root partition'):
                g['su_checked']('安装独立分区 / install independent root', command, timeout=1800,
                                **({'effect': 'root-part-write'} if g.get('GUI') else {}))
        state['phase'] = 'installed'; save(path, state)
    # No dependency on decrypting /data during OpenWrt boot.
    final_boot = path.parent/'boot-part.img'
    final_boot.write_bytes(boot_command((files/'boot.img').read_bytes(), 'e5.root=part'))
    g['bootchain']('sync')
    flash_boot(g, final_boot)
    g['arm_slot_b']()
    state['phase'] = 'complete'; save(path, state)
    print('安装及容量校验完成。请手动重启进入 OpenWrt；Android userdata 不再修改。')
