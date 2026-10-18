"""Shared binary downloads for the GUI backend and generated MU300 CLI helper."""
import hashlib
import os
from pathlib import Path
import re
import secrets
import shlex


def pull_binary(call, shell, command, destination, expected_size=None, limit=16 << 20):
    """Stage in shell-owned Android storage, pull bytes and verify all hashes."""
    destination = Path(destination)
    partial = destination.with_name(destination.name+'.partial')
    directory = '/data/local/tmp/openwrt-read-'+secrets.token_hex(12)
    remote = directory+'/data.bin'
    free = int(shell("df -Pk /data/local/tmp | tail -n1 | awk '{print $4}'", root=False, timeout=20).strip())*1024
    if expected_size is not None and expected_size <= 0:
        raise ValueError('Invalid binary read size')
    if free < (expected_size if expected_size is not None else limit)+(32 << 20):
        raise ValueError('Insufficient Android temporary space / Android 临时空间不足')
    shell('umask 077; mkdir '+shlex.quote(directory), root=False, timeout=20)
    try:
        # Only ASCII sizes/hashes return through a root shell. Binary output
        # never goes through a PTY, terminal codec, compressor or text encoder.
        metadata = shell('set -e; set -o pipefail; ('+command+') > '+remote+
                         '; chmod 644 '+remote+'; wc -c < '+remote+'; sha256sum '+remote+
                         '; ('+command+') | sha256sum', root=True, timeout=120).splitlines()
        if len(metadata) != 3 or not metadata[0].strip().isdigit():
            raise ValueError('Invalid binary read verification / 二进制读取校验信息无效')
        size = int(metadata[0].strip())
        staged, source = (line.split()[0] if line.split() else '' for line in metadata[1:])
        if size <= 0 or expected_size is not None and size != expected_size or expected_size is None and size > limit:
            raise ValueError('Binary read size mismatch / 二进制读取大小不符')
        if not re.fullmatch('[a-f0-9]{64}', staged) or source != staged:
            raise ValueError('Source changed during binary read / 二进制源数据校验不一致')
        call('pull', remote, str(partial), timeout=120)
        if not partial.is_file() or partial.stat().st_size != size:
            raise ValueError('Incomplete binary download / 二进制文件下载不完整')
        digest = hashlib.sha256()
        with partial.open('rb') as stream:
            for block in iter(lambda:stream.read(1 << 20), b''): digest.update(block)
        if digest.hexdigest() != staged:
            raise ValueError('Binary download checksum mismatch / 二进制文件下载校验失败')
        with partial.open('r+b') as stream: os.fsync(stream.fileno())
        os.replace(partial, destination)
        return size
    finally:
        try: shell('rm -f '+remote+'; rmdir '+directory, root=True, timeout=20)
        except Exception: pass
        if partial.exists(): partial.unlink()
