#!/usr/bin/env python3
"""荣悦 E5 OpenWrt 一键刷入 / one-click flash of OpenWrt on the Rongyue E5.

  flash.py                  first install onto the **SD card**, from rooted
                            Android over adb: the card is partitioned and
                            formatted, OpenWrt goes onto it
  flash.py --data           the same onto the phone's storage (userdata), the
                            form before the SD card; it asks three times
  flash.py --update         update, from the running e5-linux over the USB LAN
                            (OpenWrt's settings and installed apps kept)
  flash.py --boot-openwrt   from Android back to the installed OpenWrt (adb)
  flash.py --check          the checks and the device's files, from Android, and
                            nothing written (a dry run of the first install)

Options for the first install (asked for when not given):
  --apn APN            the carrier's APN (default: automatic, from the SIM)
  --ssid SSID          the hotspot's name (default E5-OpenWrt)
  --wifi-key KEY       the hotspot's WPA2 key, 8-63 characters (default: random)
  -y                   no questions: the defaults, and yes to erasing the card

Runs on Windows, macOS and Linux with Python 3.8+ and adb (Android
platform-tools).  flash.cmd (Windows) and flash.sh start it.  See README.md.
"""
import argparse
import hashlib
import http.server
import json
import os
import random
import shutil
import socket
import string
import subprocess
import sys
import tarfile
import tempfile
import threading
import time

B = os.path.dirname(os.path.abspath(__file__))
F = os.path.join(B, 'files')
SCRIPTS = os.path.join(B, 'scripts')
D = '/data/e5linux'
TMP = '/data/local/tmp'

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass


STEP = [0, 0]           # [this step, of how many]


def say(msg):
    # "[3/8] ..." while a run counts its steps (steps())
    if STEP[1]:
        STEP[0] += 1
        print(f'\n[{STEP[0]}/{STEP[1]}] ' + msg, flush=True)
    else:
        print('\n== ' + msg, flush=True)


def steps(n):
    STEP[0], STEP[1] = 0, n


def bar(frac, label, extra=''):
    """One line, redrawn: [#########.........]  45%  label  extra"""
    frac = max(0.0, min(1.0, frac))
    w = 28
    fill = int(frac * w)
    sys.stdout.write(f'\r   [{"#" * fill}{"." * (w - fill)}] {frac * 100:3.0f}%  {label}  {extra}   ')
    sys.stdout.flush()
    if frac >= 1.0:
        sys.stdout.write('\n')


class busy:
    """A running clock while something slow happens on the device."""
    def __init__(self, label):
        self.label = label
        self.done = threading.Event()

    def _run(self):
        t0 = time.time()
        spin = '|/-\\'
        i = 0
        while not self.done.wait(0.25):
            sys.stdout.write(f'\r   {spin[i % 4]} {self.label}  {int(time.time() - t0)} s   ')
            sys.stdout.flush()
            i += 1
        sys.stdout.write(f'\r   OK {self.label}  {int(time.time() - t0)} s          \n')
        sys.stdout.flush()

    def __enter__(self):
        self.t = threading.Thread(target=self._run, daemon=True)
        self.t.start()
        return self

    def __exit__(self, *exc):
        self.done.set()
        self.t.join()


def die(msg):
    print('\n错误 / error: ' + msg, file=sys.stderr, flush=True)
    sys.exit(1)


def sha256(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def gz_usize(path):
    """The uncompressed size of a gzip file, from its last four bytes (ISIZE;
    modulo 4 GiB, and these images are 1 GiB)."""
    with open(path, 'rb') as f:
        f.seek(-4, os.SEEK_END)
        return int.from_bytes(f.read(4), 'little')


def boot_json():
    with open(os.path.join(F, 'boot.json')) as f:
        return json.load(f)


def check_package():
    say('检查刷机包 / checking the package')
    bad = None
    with busy('校验文件 / verifying the files'), open(os.path.join(B, 'SHA256SUMS')) as f:
        for line in f:
            want, name = line.split(None, 1)
            name = name.strip()
            if sha256(os.path.join(B, *name.split('/'))) != want:
                bad = name
                break
    if bad:
        die(f'{bad} is damaged: download the package again')
    with open(os.path.join(F, 'VERSION'), encoding='utf-8') as f:
        print('   ' + f.read().strip())


# ------------------------------------------------------------------ adb

ADB = None
SU = None


def find_adb():
    global ADB
    for c in (shutil.which('adb'), os.path.join(B, 'platform-tools', 'adb.exe'),
              os.path.join(B, 'platform-tools', 'adb')):
        if c and os.path.isfile(c):
            ADB = c
            return
    die('adb not found: install Android platform-tools and put adb in PATH '
        '(or unpack platform-tools next to this script)')


def adb(*args, check=False, capture=True, timeout=600):
    r = subprocess.run([ADB, *args], stdout=subprocess.PIPE if capture else None,
                       stderr=subprocess.STDOUT if capture else None, timeout=timeout)
    out = r.stdout.decode('utf-8', 'replace').replace('\r', '') if capture else ''
    if check and r.returncode != 0:
        die(f'adb {" ".join(args[:2])} failed: {out.strip()[-300:]}')
    return out


def sh(cmd, timeout=600):
    return adb('shell', cmd, timeout=timeout)


def su(cmd, timeout=600):
    # one argument for adb, one single-quoted string for su: cmd has no '
    assert "'" not in cmd
    return adb('shell', f"{SU} -c '{cmd}'", timeout=timeout)


def push(local, remote, label):
    """In pieces, each checked: adb push has no resume."""
    size = os.path.getsize(local)
    want = sha256(local)
    su(f'rm -f {remote}')
    # (16 MiB pieces: a finer bar, and a failed piece costs less)
    part = 16 << 20
    t0 = time.time()
    bar(0, label)
    n = 0
    with open(local, 'rb') as f, tempfile.TemporaryDirectory() as td:
        while True:
            data = f.read(part)
            if not data:
                break
            p = os.path.join(td, f'p{n:03d}')
            with open(p, 'wb') as o:
                o.write(data)
            rp = f'{TMP}/e5-part{n:03d}'
            for _ in range(3):
                adb('push', p, rp)
                if su(f'stat -c %s {rp}').strip() == str(len(data)):
                    break
            else:
                die(f'pushing {label} failed')
            su(f'cat {rp} >> {remote}; rm -f {rp}')
            os.remove(p)
            n += 1
            done = min(n * part, size)
            rate = done / max(time.time() - t0, 0.1) / 1048576
            bar(done / size, label, f'{done >> 20}/{size >> 20} MiB  {rate:.1f} MiB/s')
    with busy('校验 / verifying'):
        ok = su(f'sha256sum {remote}').split()[0:1] == [want]
    if not ok:
        die(f'{label} arrived damaged')


def od_hex(path_or_cmd):
    return su(f'dd if=/dev/block/by-name/misc bs=1 skip=2048 count=32 2>/dev/null | od -An -tx1 -v').replace(' ', '').replace('\n', '')


def arm_slot_b():
    local = os.path.join(F, 'boot-misc-slot-b.bin')
    adb('push', local, f'{TMP}/e5-bc-b.bin', check=True)
    su(f'dd if={TMP}/e5-bc-b.bin of=/dev/block/by-name/misc bs=1 seek=2048 conv=notrunc 2>/dev/null; sync')
    with open(local, 'rb') as f:
        want = f.read().hex()
    if od_hex(None) != want:
        die('arming slot b failed')
    su(f'rm -f {TMP}/e5-bc-b.bin')


def android_checks():
    global SU
    say('连接设备 / looking for the E5 (Android, USB debugging on)')
    devs = [l for l in adb('devices').splitlines()[1:] if l.strip().endswith('\tdevice')]
    if len(devs) != 1:
        die(f'need exactly one device in "adb devices" (found {len(devs)}; allow USB debugging on the phone)')
    for s in ('su', '/debug_ramdisk/su', '/sbin/su'):
        if 'uid=0' in sh(f'{s} -c id'):
            SU = s
            break
    if not SU:
        die('no root: install Magisk and grant Shell superuser access')
    if sh('getprop ro.boot.slot_suffix').strip() != '_a':
        die('Android is not running from slot a')
    if sh('getprop ro.boot.verifiedbootstate').strip() != 'orange':
        die('the bootloader is locked (verifiedbootstate is not orange)')
    if 'ok' not in su('[ -e /dev/block/by-name/boot_b ] && [ -e /dev/block/by-name/l_agdsp_a ] && echo ok'):
        die('no boot_b or l_agdsp_a partition: not an E5?')
    print(f'   ok ({sh("getprop ro.product.model").strip()}, root via {SU})')


# ------------------------------------------------------ the device's files

def pull_device_files(work, out=None):
    """The firmware off Android, converted here; the vendor subset collected
    and everything packed on the device (collect-device-files.sh), into out
    (the install's device-files.tar by default)."""
    out = out or f'{D}/device-files.tar'
    say('从这台设备提取固件和基带文件 / the firmware and baseband files of this device')
    st = f'{TMP}/e5pull'
    su(f'rm -rf {st}; mkdir -p {st}')
    wanted = ['/odm/firmware/wcnmodem.bin', '/odm/firmware/gnssmodem.bin',
              '/odm/firmware/bt_configure_pskey.xpe.ini', '/odm/firmware/bt_configure_rf.xpe.ini',
              '/mnt/vendor/btmac.txt', '/vendor/firmware/aw87xxx_acf.bin',
              '/odm/etc/audio_params/sprd/audio_structure.xml',
              '/odm/etc/audio_params/sprd/dsp_vbc.xml', '/odm/etc/audio_params/sprd/cvs.xml']
    wanted += ['/odm/firmware/' + n for n in su('ls /odm/firmware/').split()
               if n.startswith('wifi_board_config') and n.endswith('.ini')]
    for p in wanted:
        su(f'cp -f {p} {st}/ 2>/dev/null')
    # optional on some units (a dangling link on this one)
    su(f'cp -f /vendor/firmware/tsx_data {st}/ 2>/dev/null')
    su(f'dd if=/dev/block/by-name/l_agdsp_a of={st}/l_agdsp_a.img bs=1M count=6 2>/dev/null; chmod -R a+r {st}')
    raw = os.path.join(work, 'raw')
    os.makedirs(raw)
    names = su(f'ls {st}').split()
    for i, n in enumerate(names):
        adb('pull', f'{st}/{n}', os.path.join(raw, n), check=True)
        bar((i + 1) / len(names), '固件 / firmware', n)
    su(f'rm -rf {st}')
    need = ['wcnmodem.bin', 'bt_configure_pskey.xpe.ini', 'bt_configure_rf.xpe.ini', 'btmac.txt',
            'l_agdsp_a.img', 'audio_structure.xml', 'dsp_vbc.xml', 'cvs.xml']
    for n in need:
        if not os.path.isfile(os.path.join(raw, n)):
            die(f'this device has no {n}: not an E5, or a different firmware')
    img = os.path.join(raw, 'l_agdsp_a.img')
    with open(img, 'rb') as f:
        head = f.read(11)
    if os.path.getsize(img) < 6291456 or not head.startswith(b'SharkL5_AUD'):
        die('the audio DSP image (l_agdsp_a) is not the expected one')

    fw = os.path.join(work, 'lib', 'firmware')
    os.makedirs(os.path.join(fw, 'sprd'))
    for n in os.listdir(raw):
        if n in ('wcnmodem.bin', 'gnssmodem.bin', 'aw87xxx_acf.bin', 'tsx_data', 'l_agdsp_a.img') or \
                (n.startswith('wifi_board_config') and n.endswith('.ini')):
            shutil.copy(os.path.join(raw, n), fw)
    tools = os.path.join(SCRIPTS, 'tools')
    subprocess.run([sys.executable, os.path.join(tools, 'sprd-bt-config.py'),
                    os.path.join(raw, 'bt_configure_pskey.xpe.ini'), os.path.join(raw, 'bt_configure_rf.xpe.ini'),
                    os.path.join(raw, 'btmac.txt'), os.path.join(fw, 'sprd')], check=True)
    subprocess.run([sys.executable, os.path.join(tools, 'vbc-profile', 'vbc-profile.py'),
                    os.path.join(raw, 'dsp_vbc.xml'), os.path.join(raw, 'audio_structure.xml'),
                    os.path.join(raw, 'cvs.xml'), '-o', fw], check=True, stdout=subprocess.DEVNULL)
    for n in ('sprd/marlin3lite_pskey.bin', 'sprd/marlin3lite_rf.bin', 'audio_structure', 'dsp_vbc', 'cvs'):
        if not os.path.isfile(os.path.join(fw, *n.split('/'))):
            die(f'converting the firmware made no {n}')

    def root(t):
        t.uid = t.gid = 0
        t.uname = t.gname = 'root'
        t.mode = (t.mode | 0o644) if t.isfile() else (t.mode | 0o755)
        return t
    fwtar = os.path.join(work, 'firmware.tar')
    with tarfile.open(fwtar, 'w', format=tarfile.GNU_FORMAT) as t:
        t.add(os.path.join(work, 'lib'), 'lib', filter=root)
    adb('push', fwtar, f'{TMP}/e5-firmware.tar', check=True)
    adb('push', os.path.join(F, 'collect-device-files.sh'), f'{TMP}/e5-collect.sh', check=True)
    with busy('在手机上打包 vendor 文件 / packing the vendor files on the phone'):
        res = su(f'mkdir -p {os.path.dirname(out)}; sh {TMP}/e5-collect.sh {out} {TMP}/e5-firmware.tar; rm -f {TMP}/e5-collect.sh')
    if 'E5-COLLECT-OK' not in res:
        die('collecting the device files failed: ' + res.strip()[-300:])
    return res.split('E5-COLLECT-OK')[-1].strip()


# ------------------------------------------------------------------ modes

def ask(prompt, default=''):
    try:
        v = input(prompt).strip()
    except EOFError:
        v = ''
    return v or default


def confirm(prompt, word='yes'):
    """A typed confirmation: anything but the word is a no."""
    try:
        v = input(prompt).strip()
    except EOFError:
        v = ''
    return v.lower() == word


def device_sd():
    """The removable card's block device: the mmcblk device that is not the one
    Android's partitions live on (userdata, misc).  "Removable" cannot be asked
    of this controller -- both mmcblk devices report 0 -- so it is told apart by
    what it carries."""
    emmc = ''
    for line in su('for u in /sys/class/block/mmcblk*p*/uevent; do '
                   'grep -qx PARTNAME=userdata "$u" 2>/dev/null && '
                   'n=${u%/*} && n=${n##*/} && echo ${n%%p*}; done').split():
        emmc = line
        break
    if not emmc:
        die('no userdata partition: not an E5?')
    devs = [d for d in su('for d in /sys/class/block/mmcblk*; do n=${d##*/}; '
                          'case $n in *p[0-9]*|*boot*) continue;; esac; '
                          f'[ $n = {emmc} ] && continue; echo $n; done').split()
            if d.startswith('mmcblk')]
    if len(devs) != 1:
        die('expected one SD card, found %d (%s): is a card in the slot?'
            % (len(devs), ' '.join(devs) or 'none'))
    return '/dev/block/' + devs[0]


def device_size(dev):
    out = su('blockdev --getsize64 %s' % dev).strip()
    return int(out) if out.isdigit() else 0


def install_sd(a):
    """The default first install: OpenWrt onto the SD card.

    The card is partitioned (GPT, one Linux partition) and the generic OpenWrt
    image is written onto the partition -- the partition *is* the filesystem, so
    boot/init mounts it directly (the marked card, /etc/e5/sd-root) instead of a
    file on userdata.  The device's own firmware is unpacked into it, so the
    card carries the whole system and userdata is not the root's home.  Only
    boot_b and, to record the boot target, e5linux/boot-os on userdata are
    written outside the card."""
    steps(8)
    find_adb()
    android_checks()
    bj = boot_json()
    live = od_hex(None)
    if live != bj['misc_slot_a_hex']:
        die(f'the boot control block is not the one this package expects ({live}): '
            'boot Android normally once, then try again')
    sd = device_sd()
    if device_size(sd) < 2 << 30:
        die('the card in the slot is smaller than 2 GiB')

    apn, ssid, key = a.apn, a.ssid, a.wifi_key
    if not a.y:
        if apn is None:
            apn = ask('APN [自动识别 / automatic, from the SIM]: ')
        ssid = ask(f'热点名称 / hotspot name [{ssid}]: ', ssid)
        if not key:
            key = ask('热点密码 / hotspot key, 8-63 characters [random]: ')
    apn = apn or ''
    if not key:
        key = ''.join(random.SystemRandom().choice('abcdefghjkmnpqrstuvwxyz23456789') for _ in range(10))
    if not 8 <= len(key) <= 63 or "'" in key or "'" in ssid or "'" in apn:
        die("the hotspot key must have 8-63 characters, and no ' anywhere")

    say(f'准备 SD 卡 / preparing the card ({sd})')
    print(f'   {sd}  {device_size(sd) >> 30} GiB')
    if not a.y:
        print('   OpenWrt 会装到这张卡上，卡上现有的数据会全部丢失。')
        print('   OpenWrt goes onto this card and everything on it is erased.')
        if not confirm('   输入 yes 继续 / type yes to continue: '):
            die('aborted: nothing was written, the card is untouched')

    with tempfile.TemporaryDirectory() as work:
        say(f'分区并格式化 / partitioning and formatting the card')
        img = os.path.join(F, 'openwrt.ext4.gz')
        # The root partition is only as large as the image: the rest of the card
        # stays free, for more systems (another partition the initramfs can be
        # pointed at) and a persistent store of its own.  So the filesystem is
        # not grown to the card -- it fills the partition exactly as built.
        sec = (gz_usize(img) + 511) // 512 + 2048       # a MiB of slack past it
        su(f'sgdisk --zap-all {sd}')
        su(f'sgdisk --new=1:0:+{sec} --typecode=1:8300 --change-name=1:e5root {sd}')
        part = sd + 'p1'
        for _ in range(20):
            if 'ok' in su(f'[ -b {part} ] && echo ok'):
                break
            time.sleep(1)
        else:
            die('the card shows no first partition after partitioning')

        say('写入 OpenWrt / OpenWrt -> the card')
        push(img, f'{TMP}/openwrt.ext4.gz', 'openwrt.ext4.gz')
        with busy('解压到 SD 卡 / unpacking onto the card'):
            su(f'gzip -dc {TMP}/openwrt.ext4.gz > {part} && sync', timeout=1800)
        su(f'rm -f {TMP}/openwrt.ext4.gz')
        # (no e2fsck here: the image is built by a newer e2fsprogs than the
        # device's, whose feature set -- metadata_csum_seed, orphan_file -- the
        # device's e2fsck calls an error.  The mount below is the check.)

        say('这台设备的文件和首次启动设置 / this device\'s files and the first boot\'s settings')
        size = pull_device_files(work, f'{TMP}/e5-device-files.tar')
        conf = os.path.join(work, 'install.conf')
        with open(conf, 'w', newline='\n') as f:
            f.write('# the flash package (flash.py), for OpenWrt\'s first boot\n'
                    f"E5_APN='{apn}'\nE5_WIFI_SSID='{ssid}'\nE5_WIFI_KEY='{key}'\n"
                    "E5_WIFI_CHANNEL='149'\nE5_DEFAULT_BOOT='linux'\n")
        mark = os.path.join(work, 'sd-root')
        with open(mark, 'w', newline='\n') as f:
            f.write('e5-openwrt-sd %s %s\n' % (time.strftime('%Y-%m-%d'), bj['sha256'][:12]))
        adb('push', conf, f'{TMP}/e5-install.conf', check=True)
        adb('push', mark, f'{TMP}/e5-sd-root', check=True)
        m = f'{TMP}/e5sd'
        su(f'umount {m} 2>/dev/null; mkdir -p {m}; mount -t ext4 {part} {m}')
        with busy('在卡上写设置和设备文件 / writing the settings and the device files'):
            su(f'mkdir -p {m}/etc/e5; '
               f'mv {TMP}/e5-install.conf {m}/etc/e5/install.conf; '
               f'chmod 600 {m}/etc/e5/install.conf; '
               f'mv {TMP}/e5-sd-root {m}/etc/e5/sd-root; '
               f'tar -xf {TMP}/e5-device-files.tar -C {m}; '
               f'sha256sum {TMP}/e5-device-files.tar | cut -c1-64 > {m}/etc/e5/device-files.stamp; '
               'sync', timeout=900)
        ok = 'ok' in su(f'[ -x {m}/sbin/init ] && [ -f {m}/lib/firmware/wcnmodem.bin ] && echo ok')
        su(f'umount {m}; rm -f {TMP}/e5-device-files.tar')
        if not ok:
            die('the card does not hold the image and the device files it should')
        print(f'   OpenWrt and {size} bytes of device files are on the card')
        free = device_size(sd) - device_size(part)
        print(f'   {free >> 30}.{(free % (1 << 30)) * 10 // (1 << 30)} GiB of the card '
              'are left free, for more partitions (systems, a store)')

        say('写入启动镜像 / boot image -> boot_b')
        push(os.path.join(F, 'boot.img'), f'{TMP}/e5-boot.img', 'boot.img')
        with busy('写入并校验 boot_b / writing and verifying boot_b'):
            su(f'dd if={TMP}/e5-boot.img of=/dev/block/by-name/boot_b bs=4M 2>/dev/null; sync')
            ok = su('sha256sum /dev/block/by-name/boot_b').split()[0:1] == [bj['sha256']]
        if not ok:
            die('boot_b did not verify; Android stays as it is')
        su(f'rm -f {TMP}/e5-boot.img')
        arm_slot_b()

    # The boot target, explicit: e5linux/boot-os on userdata is a few bytes, and
    # it is what makes a later `--data` install win over the card again.  The root
    # filesystem itself is not on userdata; if userdata cannot be written, the
    # marked card boots anyway (boot/init).
    su(f'mkdir -p {D}; rm -f {D}/boot-os-next; echo sd > {D}/boot-os')

    say('完成，正在重启进 OpenWrt / done, rebooting into OpenWrt')
    adb('reboot')
    print(f'''
  第一次启动约 2 分钟 / the first boot takes about 2 minutes.
  OpenWrt 在 SD 卡上 / OpenWrt is on the SD card ({sd}p1).
  热点 / hotspot:  {ssid}   密码 / key:  {key}
  管理 / admin:    http://192.168.9.1  (LuCI, root / root -- 请改密码 / change it)
  回 Android:      屏幕 高级 -> 系统 -> 下次启动 Android, or: e5-next-boot android; reboot
  若启动失败，设备会在两次尝试后自动回到 Android。
  If the boot fails, the E5 falls back to Android after two tries.''')

def install(a):
    # checks, device files, OpenWrt, settings, boot image, reboot
    steps(6)
    find_adb()
    android_checks()
    bj = boot_json()
    live = od_hex(None)
    if live != bj['misc_slot_a_hex']:
        die(f'the boot control block is not the one this package expects ({live}): '
            'boot Android normally once, then try again')
    avail = su('df -k /data | tail -1').split()
    if len(avail) < 4 or int(avail[3]) < 2621440:
        die("less than 2.5 GiB free on the phone's storage")
    if not a.y:
        say("安装到 userdata（旧方式）/ installing to the phone's storage (userdata)")
        print('   OpenWrt goes into a file on userdata (/data/e5linux), about 1.1 GiB of it,')
        print('   the way it was before the SD card.  The SD card is the default install;')
        print('   this form is the fallback, for a device whose slot is not usable.  It')
        print("   writes to the phone's own storage, so it asks three times.")
        for n in (1, 2, 3):
            if not confirm(f'   确认 {n}/3 -- 输入 yes 继续 / type yes to continue: '):
                die('aborted: nothing was written')

    apn, ssid, key = a.apn, a.ssid, a.wifi_key
    if not a.y:
        if apn is None:
            apn = ask('APN [自动识别 / automatic, from the SIM]: ')
        ssid = ask(f'热点名称 / hotspot name [{ssid}]: ', ssid)
        if not key:
            key = ask('热点密码 / hotspot key, 8-63 characters [random]: ')
    apn = apn or ''
    if not key:
        key = ''.join(random.SystemRandom().choice('abcdefghjkmnpqrstuvwxyz23456789') for _ in range(10))
    if not 8 <= len(key) <= 63 or "'" in key or "'" in ssid or "'" in apn:
        die("the hotspot key must have 8-63 characters, and no ' anywhere")

    with tempfile.TemporaryDirectory() as work:
        size = pull_device_files(work)
        print(f'   device-files.tar: {size} bytes (stays on the device)')

        say(f'写入 OpenWrt / OpenWrt -> {D}/openwrt.ext4')
        push(os.path.join(F, 'openwrt.ext4.gz'), f'{TMP}/openwrt.ext4.gz', 'openwrt.ext4.gz')
        with busy('解压到手机存储 / unpacking onto the phone (1 GiB)'):
            su(f'gzip -dc {TMP}/openwrt.ext4.gz > {D}/openwrt.ext4.part && mv {D}/openwrt.ext4.part {D}/openwrt.ext4; '
               f'rm -f {TMP}/openwrt.ext4.gz {D}/openwrt.ext4.new {D}/openwrt.ext4.old', timeout=900)
        print('   ' + su(f'ls -l {D}/openwrt.ext4').split()[4] + ' bytes')

        say('首次启动设置 / the first boot\'s settings')
        conf = os.path.join(work, 'install.conf')
        with open(conf, 'w', newline='\n') as f:
            f.write('# the flash package (flash.py), for OpenWrt\'s first boot\n'
                    f"E5_APN='{apn}'\nE5_WIFI_SSID='{ssid}'\nE5_WIFI_KEY='{key}'\n"
                    "E5_WIFI_CHANNEL='149'\nE5_DEFAULT_BOOT='linux'\n")
        adb('push', conf, f'{TMP}/e5-install.conf', check=True)
        su(f'mv {TMP}/e5-install.conf {D}/openwrt-install.conf && chmod 600 {D}/openwrt-install.conf')
        # OpenWrt from now on, also when an e5-linux Debian is installed as well
        su(f'rm -f {D}/boot-os-next; echo openwrt > {D}/boot-os')

    say('写入启动镜像 / boot image -> boot_b')
    push(os.path.join(F, 'boot.img'), f'{TMP}/e5-boot.img', 'boot.img')
    with busy('写入并校验 boot_b / writing and verifying boot_b'):
        su(f'dd if={TMP}/e5-boot.img of=/dev/block/by-name/boot_b bs=4M 2>/dev/null; sync')
        ok = su('sha256sum /dev/block/by-name/boot_b').split()[0:1] == [bj['sha256']]
    if not ok:
        die('boot_b did not verify; Android stays as it is')
    su(f'rm -f {TMP}/e5-boot.img')
    arm_slot_b()

    say('完成，正在重启进 OpenWrt / done, rebooting into OpenWrt')
    adb('reboot')
    print(f'''
  第一次启动约 2 分钟 / the first boot takes about 2 minutes.
  热点 / hotspot:  {ssid}   密码 / key:  {key}
  管理 / admin:    http://192.168.9.1  (LuCI, root / root -- 请改密码 / change it)
  回 Android:      屏幕 高级 -> 系统 -> 下次启动 Android, or: e5-next-boot android; reboot
  若启动失败，设备会在两次尝试后自动回到 Android。
  If the boot fails, the E5 falls back to Android after two tries.''')


def check(a):
    steps(3)
    find_adb()
    android_checks()
    live = od_hex(None)
    print('   boot control block: ' + ('as expected' if live == boot_json()['misc_slot_a_hex'] else 'NOT as expected: ' + live))
    print('   free on /data: ' + su('df -k /data | tail -1').split()[3] + ' KiB')
    # packed as for an install, to see that it works, and deleted again: a
    # check leaves nothing on the device
    with tempfile.TemporaryDirectory() as work:
        size = pull_device_files(work, f'{TMP}/e5-check-device-files.tar')
    su(f'rm -f {TMP}/e5-check-device-files.tar')
    print(f'   device-files.tar: {size} bytes (a trial, deleted again)')
    say('检查完成，设备上什么都没有写入 / checked; nothing written to the device')


def boot_openwrt(a):
    steps(2)
    find_adb()
    android_checks()
    bj = boot_json()
    if 'ok' not in su(f'{{ [ -f {D}/openwrt.ext4 ] || [ "$(cat {D}/boot-os 2>/dev/null)" = sd ]; }} && echo ok'):
        die('OpenWrt is not installed: run the first install')
    mb = bj['persist_log_offset'] // 1048576
    head = su(f'dd if=/dev/block/by-name/boot_b bs=1048576 count={mb} 2>/dev/null | sha256sum').split()[0:1]
    if head != [bj['sha256_head56m']]:
        die('boot_b holds another boot image: use the package it was flashed with, or a first install')
    # OpenWrt the default again, not only for this boot (the screen's "boot
    # Android" made Android the default); /etc/init.d/e5-boot-ok takes it
    su(f'echo linux > {D}/openwrt-default-boot')
    arm_slot_b()
    say('正在重启进 OpenWrt / rebooting into OpenWrt')
    adb('reboot')


def local_ip(host):
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect((host, 80))
        return s.getsockname()[0]
    finally:
        s.close()


def update(a):
    host = os.environ.get('E5_HOST', '192.168.9.1')
    try:
        ip = local_ip(host)
    except OSError:
        ip = ''
    if not ip.startswith('192.168.9.') and not ip.startswith('192.168.77.'):
        die("no address on the E5's USB LAN (192.168.9.x): is it connected and running OpenWrt?")
    pw = os.environ.get('E5_TELNET_PASS')
    if pw is None and (a.y or not sys.stdin.isatty()):
        pw = 'root'     # (-y: the default, not asked)
    if pw is None:
        import getpass
        pw = getpass.getpass('root password of the E5 [root]: ') or 'root'
    bj = boot_json()
    mb = bj['persist_log_offset'] // 1048576
    with tempfile.TemporaryDirectory() as td:
        head = os.path.join(td, 'boot-head.img')
        with open(os.path.join(F, 'boot.img'), 'rb') as i, open(head, 'wb') as o:
            o.write(i.read(mb << 20))
        files = {'/boot-head.img': head,
                 '/openwrt.ext4.gz': os.path.join(F, 'openwrt.ext4.gz'),
                 '/dii.sh': os.path.join(F, 'device-install-image.sh'),
                 '/e5-gpt': os.path.join(F, 'e5-gpt'),
                 '/dfb.sh': os.path.join(F, 'device-flash-boot.sh')}

        class H(http.server.SimpleHTTPRequestHandler):
            def translate_path(self, path):
                return files.get(path.split('?')[0], os.path.join(td, 'nothing'))

            def log_message(self, *args):
                pass

        srv = http.server.ThreadingHTTPServer((ip, 0), H)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        u = f'http://{ip}:{srv.server_address[1]}'
        say(f'更新 / updating {host}')
        env = dict(os.environ, E5_TELNET_HOST=host, E5_TELNET_PASS=pw, E5_TELNET_WAIT='1800')
        telnet = [sys.executable, os.path.join(SCRIPTS, 'tools', 'e5-telnet.py')]
        # The steps as a script the device fetches: a long command line typed over
        # telnet gets lost (the 80-column pty's line editing), so only a short one is.
        steps_sh = f"""set -e
cd /tmp
wget -q -O dfb.sh {u}/dfb.sh
wget -q -O dii.sh {u}/dii.sh
sh dfb.sh {u}/boot-head.img {bj["sha256_head56m"]} {mb}
if [ -f /etc/e5/sd-root ]; then
    # an SD card system (the default install): the new image goes into the card's
    # other root partition, the next boot is its trial; userdata is not touched
    # (FINDINGS 49)
    wget -q -O e5-gpt {u}/e5-gpt
    E5_IMAGE_SIZE={gz_usize(os.path.join(F, "openwrt.ext4.gz"))} sh dii.sh {u}/openwrt.ext4.gz
else
    # the form on userdata (--data, kept for tests)
    sh dii.sh {u}/openwrt.ext4.gz
    d=/mnt/e5-data/e5linux
    rm -f $d/boot-os-next
    echo openwrt > $d/boot-os
    sync
fi
echo E5-UPDATE-$((1+1))
"""
        with open(os.path.join(td, 'update.sh'), 'w', newline='\n') as f:
            f.write(steps_sh)
        files['/update.sh'] = os.path.join(td, 'update.sh')
        cmd = f'cd /tmp && wget -q -O e5-update.sh {u}/update.sh && sh e5-update.sh'
        # the device's own steps as they happen: the boot image, the unpacking,
        # the settings kept, the device's files
        lines = []
        with subprocess.Popen(telnet + [cmd], env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT) as pr:
            with busy('设备上的更新 / the update on the device'):
                for raw in pr.stdout:
                    line = raw.decode('utf-8', 'replace').replace('\r', '').rstrip('\n')
                    lines.append(line)
                    if line.startswith(('==', 'installed', 'WARNING', 'error', 'the image', '   ')):
                        sys.stdout.write('\r   ' + line + ' ' * 20 + '\n')
                        sys.stdout.flush()
        out = '\n'.join(lines)
        srv.shutdown()
        if 'E5-UPDATE-2' not in out:
            print('\n'.join(out.splitlines()[-20:]))
            die('the update did not finish (the log is above)')
        # the reboot on its own: a session the reboot cuts never sees its end
        env['E5_TELNET_WAIT'] = '20'
        subprocess.run(telnet + ['( (sleep 2; reboot) >/dev/null 2>&1 & )'], env=env,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    say('完成，设备正在重启 / done, the E5 is rebooting')


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    g = ap.add_mutually_exclusive_group()
    g.add_argument('--update', action='store_true')
    g.add_argument('--boot-openwrt', action='store_true')
    g.add_argument('--check', action='store_true')
    g.add_argument('--data', action='store_true',
                   help="install to the phone's storage (userdata) as before; the SD card is the default")
    ap.add_argument('--apn')
    ap.add_argument('--ssid', default='E5-OpenWrt')
    ap.add_argument('--wifi-key')
    ap.add_argument('-y', action='store_true')
    a = ap.parse_args()
    if sys.version_info < (3, 8):
        die('Python 3.8 or newer is needed')
    check_package()
    if a.update:
        update(a)
    elif a.boot_openwrt:
        boot_openwrt(a)
    elif a.check:
        check(a)
    elif a.data:
        install(a)          # the form before the SD card; three confirmations
    else:
        install_sd(a)


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        die('interrupted')
