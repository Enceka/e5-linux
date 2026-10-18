"""MU300 desktop updates, shared with CLI and older compatible package entries."""
import getpass
import json
import os
from pathlib import Path
import re
import secrets
import struct
import tempfile


LEGACY_LAYOUT_PROBE = '''set -eu
[ / -ef /mnt/mu300-disk/openwrt ] || { echo 'running root is not the MU300 OpenWrt container' >&2; exit 1; }
d=$(readlink -f "$(cat /run/mu300/disk-dev)")
case "$d" in /dev/loop[0-9]*) ;; *) echo 'legacy root is not a loop device' >&2; exit 1 ;; esac
[ -b "$d" ]
n=${d##*/}
id=$(cat /sys/class/block/$n/dev)
awk -v id="$id" '$3 == id && $5 == "/mnt/mu300-disk" {for (i=7;i<=NF;i++) if ($i == "-" && $(i+1) == "ext4") ok=1} END {exit !ok}' /proc/self/mountinfo
backing=$(readlink -f "$(cat /sys/class/block/$n/loop/backing_file)")
[ "$backing" = /dev/mmcblk0 ]
end=0
for p in /sys/class/block/mmcblk0p*; do
    [ -r "$p/start" ] || continue
    start=$(cat "$p/start"); size=$(cat "$p/size")
    case "$start:$size" in *[!0-9:]*|:*|*:) exit 1 ;; esac
    next=$((start + size))
    [ "$next" -le "$end" ] || end=$next
done
printf 'MU300-LEGACY-LAYOUT-V1\\n%s\\n%s\\n' "$d" "$backing"
cat /sys/class/block/$n/loop/offset /sys/class/block/$n/size /sys/class/block/mmcblk0/size /sys/class/block/$n/loop/sizelimit
printf '%s\\n' "$end"
'''


def legacy_layout(client, root, execute, read_exact):
    """Prove the mounted hidden-area layout using bounded, read-only evidence."""
    values = execute(client, LEGACY_LAYOUT_PROBE).strip().splitlines()
    if (len(values) != 8 or values[0] != 'MU300-LEGACY-LAYOUT-V1'
            or not re.fullmatch(r'/dev/loop[0-9]+', values[1]) or values[2] != '/dev/mmcblk0'
            or any(not re.fullmatch(r'[0-9]+', v) for v in values[3:])):
        raise ValueError('Cannot verify legacy hidden-area layout / 无法确认旧版隐藏区域布局，已停止更新')
    offset, sectors, disk_sectors, limit, partition_end = map(int, values[3:])
    if (not offset or offset % 512 or sectors <= 0 or partition_end <= 0
            or offset//512 < partition_end or offset//512+sectors > disk_sectors-34
            or limit not in (0, sectors*512)):
        raise ValueError('Legacy root overlaps GPT partitions or exceeds eMMC bounds / 旧版根区域与分区重叠或超出 eMMC 范围')
    # The legacy boot searches the first aligned region after GPT, then its
    # saved ROOT_OFFSET. Do not accept a region the packaged boot cannot find.
    original = (Path(root)/'desktop/files/boot/original-init').read_text(encoding='utf-8')
    defaults = re.findall(r'^ROOT_OFFSET=([0-9]+)\b', original, re.MULTILINE)
    offsets = {(partition_end//4096+1)*4096*512, *map(int, defaults)}
    if offset not in offsets:
        raise ValueError('Packaged legacy boot cannot locate this root offset / 安装包启动逻辑无法定位当前旧版根区域，已停止更新')
    superblock = read_exact(client, f'dd if={values[1]} bs=1024 skip=1 count=1 2>/dev/null', 1024)
    if (len(superblock) != 1024 or superblock[56:58] != b'\x53\xef'
            or superblock[120:136].rstrip(b'\0') != b'mu300root'):
        raise ValueError('Legacy root is not a verified mu300root ext4 filesystem / 旧版根区域不是可确认的 mu300root ext4 文件系统')
    log_size = struct.unpack_from('<I', superblock, 24)[0]
    blocks = struct.unpack_from('<I', superblock, 4)[0]
    if struct.unpack_from('<I', superblock, 96)[0] & 0x80:
        blocks |= struct.unpack_from('<I', superblock, 336)[0] << 32
    capacity = blocks*(1024 << log_size) if log_size <= 6 else 0
    if not 0 < capacity <= sectors*512:
        raise ValueError('Legacy ext4 capacity exceeds its loop extent / 旧版 ext4 容量超出挂载区域')
    return dict(mode='legacy', device=values[1], backing=values[2], offset=offset,
                sectors=sectors, disk_sectors=disk_sectors, limit=limit,
                partition_end=partition_end, capacity=capacity)


def update_mu300(api, args, root):
    """Reuse native config/vendor migration, locking, swap and verified writes."""
    import paramiko
    root = Path(root)
    gui = api.get('GUI')
    execute, read_exact = api['ssh_exec'], api['ssh_read_exact']
    if gui and not args.host:
        raise ValueError('Enter the management address in the GUI / 请在图形界面填写管理地址')
    host = args.host or input('Device IP / 设备 IP [192.168.77.1]: ').strip() or '192.168.77.1'
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        client.connect(host, username='root', password=gui.password if gui else os.environ.get('MU300_SSH_PASSWORD') or getpass.getpass('SSH root password: '),
                       timeout=15, look_for_keys=False, allow_agent=False)
        if gui:
            gui.validate_ssh(client)
        info = execute(client, '''set -e
cat /run/mu300/device
cat /run/mu300/linux-slot
cat /run/mu300/misc-dev
if [ -s /etc/mu300/desktop-mode ]; then cat /etc/mu300/desktop-mode; else
    d=$(cat /run/mu300/disk-dev)
    case "$d" in /dev/mmcblk[1-9]*) echo sd ;; *) echo legacy ;; esac
fi''').strip().splitlines()
        if (len(info) != 4 or info[0] not in ('f50', 'v50', 'u30air') or info[1] not in ('a', 'b')
                or not re.fullmatch(r'/dev/mmcblk\d+p\d+', info[2])):
            raise ValueError('Not a supported MU300 runtime')
        mode = info[3]
        if mode not in ('sd', 'part', 'data-image', 'legacy'):
            raise ValueError('Unsupported root layout / 不支持的根区域布局: '+mode)
        layout = legacy_layout(client, root, execute, read_exact) if mode == 'legacy' else None
        if layout and gui:
            planned = gui.ctx.record['plan']['openwrt_bytes']
            if planned != layout['capacity']:
                raise ValueError('Legacy root capacity changed since review / 旧版根区域容量与确认计划不一致，请重新检查设备')
            gui.ctx.record['update_layout'] = layout
            gui.ctx.store.save(gui.ctx.record)
            gui.ctx.log(f'Verified legacy eMMC hidden-area root: offset={layout["offset"]}, '
                        f'capacity={layout["capacity"]}, loop_sectors={layout["sectors"]}; preserving layout', scope='update')
        family = json.loads((root/'desktop/manifest.json').read_text(encoding='utf-8'))['kernel']
        running = execute(client, 'uname -r').strip()
        if not running.startswith(family+'.'):
            raise ValueError('Kernel family mismatch: running '+running+', package '+family)
        live = read_exact(client, f'dd if={info[2]} bs=1 skip=2048 count=32', 32)
        slot = 'b' if info[1] == 'a' else 'a'
        module = api['module'](root)
        newboot = api['boot'](root, module, mode, live, slot)
        control = module.boot_control(live, slot)
        if gui:
            gui.ctx.boundary()
        else:
            api['confirm']('Update OpenWrt while preserving settings and disk size; then reboot / 保留配置及容量更新，完成后重启。')
        # Stage on disk, never upload a complete rootfs to the device's tmpfs.
        destination = '/mnt/mu300-disk/.mu300-desktop-'+secrets.token_hex(6)
        execute(client, 'mkdir -m 700 '+destination)

        def send(local, name):
            api['ssh_upload'](client, local, destination+'/'+name)
            if execute(client, 'sha256sum '+destination+'/'+name).split()[0] != api['digest'](local):
                raise ValueError('SSH upload checksum: '+name)

        with api['payload_rootfs'](root) as archive:
            send(archive, 'mu300-openwrt-rootfs.tar.gz')
        for name in ('local-update.sh', 'mu300-update-library.sh'):
            send(root/'desktop'/name, name)
        send(api['payload_file'](root, 'busybox'), 'busybox')
        for name in ('rootfs-critical.sha256', 'rootfs.requirements'):
            send(api['payload_file'](root, name), name)
        with tempfile.TemporaryDirectory() as temp:
            for name, data in (('boot-desktop.img', newboot), ('misc-linux.bin', control)):
                path = Path(temp)/name
                path.write_bytes(data)
                send(path, name)
        if layout and legacy_layout(client, root, execute, read_exact) != layout:
            raise ValueError('Legacy root layout changed during upload; nothing committed / 上传期间旧版根区域发生变化，未执行更新写入')
        command = 'chmod 700 '+destination+'/busybox && sh '+destination+'/local-update.sh '+destination
        if gui:
            gui.action('update-commit', lambda: execute(client, command))
        else:
            execute(client, command)
    finally:
        client.close()
    return api['Outcome']('success', 'Update verified; device is rebooting / 更新校验完成，设备正在重启。',
                          'Wait for OpenWrt to start / 等待 OpenWrt 启动。')
