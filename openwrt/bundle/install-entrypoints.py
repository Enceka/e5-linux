#!/usr/bin/env python3
"""Create descriptive public installer entries, shared by both bundle builders."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import os
import runpy

HERE = Path(__file__).resolve().parent
ACTIONS = {
    'install-to-tf-card': '--tf',
    'install-to-userdata-image': '--data',
    'install-to-internal-storage': '--part',
    'reinstall-internal-system': '--reinstall-part',
    'resume-internal-install': '--resume-part',
    'switch-to-openwrt': '--boot-openwrt',
    'update-openwrt': '--update',
}


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def assemble(package, source=HERE):
    package, source = Path(package).resolve(), Path(source).resolve()
    if package == source:
        raise ValueError('expected a separate package directory')
    package.mkdir(parents=True, exist_ok=True)
    internal = package / 'scripts/installer'; internal.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source / 'flash.py', package / 'OpenWrt-Installer.py')
    launchers = package / 'launchers'; launchers.mkdir(parents=True, exist_ok=True)
    # The interpreter and executable resolve payloads relative to the package,
    # not the current directory or the directory containing a shortcut.
    cmd = ('@echo off\r\nchcp 65001 >nul\r\npushd "%~dp0.."\r\n'
           'if exist "tools\\backend\\openwrt-backend.exe" (\r\n'
           '  "tools\\backend\\openwrt-backend.exe" --cli --package-root "%cd%" --no-pause %*\r\n'
           ') else (\r\n'
           '  where py >nul 2>nul\r\n'
           '  if not errorlevel 1 (\r\n'
           '    py -3 "OpenWrt-Installer.py" --no-pause %*\r\n'
           '  ) else (\r\n'
           '    python "OpenWrt-Installer.py" --no-pause %*\r\n'
           '  )\r\n)\r\n'
           'set "INSTALL_EXIT=%ERRORLEVEL%"\r\npause\r\npopd\r\nexit /b %INSTALL_EXIT%\r\n')
    (launchers / 'start-installer.cmd').write_bytes(cmd.encode('ascii'))
    (launchers / 'start-installer.sh').write_text(
        '#!/bin/sh\ncd "$(dirname "$0")/.." || exit 1\n'
        'if [ "$(uname -s)" = Darwin ] && [ -x ./tools/macos/backend/openwrt-backend ]; then\n'
        '  exec ./tools/macos/backend/openwrt-backend --cli --package-root "$PWD" "$@"\n'
        'fi\n'
        'exec python3 ./OpenWrt-Installer.py "$@"\n', encoding='utf-8', newline='\n')
    shutil.copy2(source / 'part-two-stage.py', internal / 'part-two-stage.py')
    shutil.copy2(HERE.parents[1] / 'installer/backend/boot_image.py', internal / 'boot-control.py')
    exe = source / 'flash.exe'
    if exe.is_file() and (source != HERE or os.environ.get('OPENWRT_BUILD_LEGACY_EXE') == '1'):
        metadata = json.loads((source / 'flash-exe.json').read_text(encoding='utf-8'))
        if metadata != {'source_sha256': digest(source / 'flash.py'), 'binary_sha256': digest(exe)}:
            raise ValueError('Windows installer is stale; run python tools/build-flash-exe.py on Windows')
        (package / 'tools/legacy').mkdir(parents=True, exist_ok=True)
        shutil.copy2(exe, package / 'tools/legacy/flash.exe')
        shutil.copy2(source / 'flash-exe.json', internal / 'flash-exe.json')
    for name, option in ACTIONS.items():
        cmd = '@echo off\r\ncd /d "%~dp0"\r\n'
        if name == 'resume-internal-install':
            cmd += ('if not "%~1"=="" goto resume_given\r\n'
                    'set /p "TRANSACTION=Saved transaction.json path: "\r\n'
                    'if not defined TRANSACTION exit /b 1\r\n'
                    'call "%~dp0start-installer.cmd" --resume-part "%TRANSACTION%"\r\n'
                    'exit /b %ERRORLEVEL%\r\n'
                    ':resume_given\r\n'
                    'call "%~dp0start-installer.cmd" --resume-part %*\r\n'
                    'exit /b %ERRORLEVEL%\r\n')
            sh = ('#!/bin/sh\ncd "$(dirname "$0")" || exit 1\n'
                  'transaction=${1:-}\n'
                  'if [ -z "$transaction" ]; then printf "Saved transaction.json path: "; read -r transaction || exit 1; else shift; fi\n'
                  '[ -n "$transaction" ] || exit 1\n'
                  'exec sh ./start-installer.sh --resume-part "$transaction" "$@"\n')
        else:
            cmd += f'call "%~dp0start-installer.cmd" {option} %*\r\n'
            sh = ('#!/bin/sh\ncd "$(dirname "$0")" || exit 1\n'
                  f'exec sh ./start-installer.sh {option} "$@"\n')
        (launchers / (name + '.cmd')).write_bytes(cmd.encode('ascii'))
        target = launchers / (name + '.sh'); target.write_text(sh, encoding='utf-8', newline='\n'); target.chmod(0o755)
    (package / 'OpenWrt-Installer.py').chmod(0o755)
    (launchers / 'start-installer.sh').chmod(0o755)
    files = package / 'files'; files.mkdir(exist_ok=True)
    shutil.copy2(source / 'userdata-image.sh', files / 'userdata-image.sh')
    shutil.copy2(source / 'android-loop.sh', files / 'android-loop.sh')
    docs = package / 'docs'; docs.mkdir(exist_ok=True)
    for name in ('README.md', 'README.zh-CN.md'):
        shutil.copy2(source / name, docs / name)
    shutil.copy2(source / 'START-HERE.md', package / 'START-HERE.md')
    if source == HERE and os.environ.get('OPENWRT_GUI_OPTIONAL') != '1':
        runpy.run_path(str(HERE.parents[1] / 'installer/package_gui.py'))['attach'](package)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('package', type=Path)
    assemble(parser.parse_args().package)
