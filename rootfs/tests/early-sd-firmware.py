#!/usr/bin/env python3
"""Check the actual early firmware function against fake disks and mounts."""
import os
from pathlib import Path
import subprocess
import tempfile

TOP=Path(__file__).resolve().parents[2]
source=(TOP/'boot/init').read_text()
function=source[source.index('early_card_firmware() {'):source.index('\nearly_device_firmware() {')]
assert '-o ro,noload,noatime' in function
assert source.index('[ "$module" = wcn_bsp.ko ] && early_device_firmware') < source.index('insmod "/linux-modules/$module"')
with tempfile.TemporaryDirectory(prefix='e5-early-fw-') as directory:
    root=Path(directory)
    for path in ['sys/mmcblk0','sys/mmcblk1','dev','card/lib/firmware','card/etc/e5','card/sbin','bin','firmware']:
        (root/path).mkdir(parents=True)
    for name in ['mmcblk0p1','mmcblk1p1']:(root/'dev'/name).touch()
    (root/'card/etc/e5/sd-root').touch()
    (root/'card/lib/firmware/wcnmodem.bin').write_text('this-device-firmware')
    (root/'card/sbin/init').write_text('#!/bin/sh\n');(root/'card/sbin/init').chmod(0o755)
    def command(name,body):
        path=root/'bin'/name;path.write_text('#!/bin/sh\n'+body);path.chmod(0o755)
    command('mdev','exit 0\n')
    command('sleep','exit 0\n')
    command('mount','echo "$*" >> "$TEST_LOG"\n[ "${5##*/}" = mmcblk1p1 ] || exit 1\ncp -R "$TEST_CARD/." "$6/"\n')
    command('umount','rm -rf "$1"; mkdir -p "$1"\n')
    actual=function.replace('/sys/class/block',str(root/'sys')).replace('/dev/',str(root/'dev')+'/')
    actual=actual.replace('/tmp/e5-early-fw',str(root/'mounted')).replace('[ -b "$part" ]','[ -f "$part" ]')
    actual=actual.replace('mkdir -p /lib/firmware','mkdir -p '+str(root/'firmware'))
    actual=actual.replace(' /lib/firmware/;', ' '+str(root/'firmware')+'/;').replace('ls /lib/firmware','ls '+str(root/'firmware'))
    script=root/'test.sh';script.write_text('set -eu\nlog() { echo "$*"; }\n'+actual+'\nearly_card_firmware mmcblk0\n')
    env={**os.environ,'PATH':str(root/'bin')+':'+os.environ['PATH'],'TEST_LOG':str(root/'mounts'),'TEST_CARD':str(root/'card')}
    result=subprocess.run(['sh',str(script)],env=env,capture_output=True,text=True)
    assert result.returncode==0,result.stderr
    assert (root/'firmware/wcnmodem.bin').read_text()=='this-device-firmware'
    log=(root/'mounts').read_text();assert 'ro,noload,noatime' in log and 'mmcblk0p1' not in log
    (root/'card/lib/firmware/wcnmodem.bin').unlink()
    result=subprocess.run(['sh',str(script)],env=env,capture_output=True,text=True)
    assert result.returncode!=0,'missing card firmware was reported as loaded'
print('Early SD firmware checks passed without mounting userdata')
