#!/usr/bin/env python3
"""Build and fingerprint the Windows installer used by release packaging."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

TOP = Path(__file__).resolve().parents[1]


def main():
    if os.name != 'nt':
        raise SystemExit('Run on Windows with Python and PyInstaller installed.')
    work = TOP / 'work/flash-exe'
    source = TOP / 'openwrt/bundle/flash.py'
    source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    command = [sys.executable, '-m', 'PyInstaller', '--noconfirm', '--onefile', '--console', '--name', 'flash',
               '--distpath', str(work), '--workpath', str(work / 'build'), '--specpath', str(work)]
    for name in ('xml.etree.ElementTree', 'xml.parsers.expat', 'binascii', 'zlib', 'lzma', 'bz2', 'paramiko'):
        command += ['--hidden-import', name]
    subprocess.run(command + [str(source)], cwd=TOP, check=True)
    exe = work / 'flash.exe'
    subprocess.run([str(exe), '--help'], check=True, stdout=subprocess.DEVNULL)
    if hashlib.sha256(source.read_bytes()).hexdigest() != source_hash:
        raise SystemExit('Installer source changed during the build; rebuild before packaging.')
    target = TOP / 'openwrt/bundle/flash.exe'
    shutil.copy2(exe, target)
    metadata = {'source_sha256': source_hash, 'binary_sha256': hashlib.sha256(target.read_bytes()).hexdigest()}
    target.with_name('flash-exe.json').write_text(json.dumps(metadata, indent=2) + '\n', encoding='utf-8', newline='\n')
    print('Windows installer and source fingerprint updated.')


if __name__ == '__main__':
    main()
