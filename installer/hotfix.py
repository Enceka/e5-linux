"""Create a Windows-only MU300 host overlay, without copying device payloads."""
import argparse
from datetime import datetime
import json
from pathlib import Path
import shutil
import zipfile

from package_gui import digest, sources

HERE = Path(__file__).resolve().parent
TOP = HERE.parent


def build_patch(destination, artifact=None):
    destination = Path(destination).resolve()
    if destination.exists():raise ValueError('Choose a new patch directory; existing output is preserved')
    artifact = Path(artifact or HERE/'artifacts/windows')
    metadata = json.loads((artifact/'build.json').read_text(encoding='utf-8'))
    if metadata.get('platform') != 'windows-x64' or metadata['source'] != sources():
        raise ValueError('Build the current Windows installer first')
    for name, checksum in metadata['files'].items():
        path = (artifact/name).resolve()
        if not path.is_relative_to(artifact.resolve()) or digest(path) != checksum:
            raise ValueError('Build artifact checksum failed: '+name)
    destination.mkdir(parents=True)
    shutil.copy2(artifact/'OpenWrt-Installer.exe',destination/'OpenWrt-Installer.exe')
    shutil.copytree(artifact/'tools/backend',destination/'tools/backend')
    files = {'OpenWrt-Installer.py':TOP/'desktop/installer.py', 'desktop/installer.py':TOP/'desktop/installer.py',
             'desktop/binary_io.py':HERE/'backend/binary_io.py','desktop/boot_control.py':HERE/'backend/boot_image.py',
             'desktop/update_control.py':HERE/'backend/mu300_update.py',
             'desktop/mu300-update-library.sh':TOP/'rootfs/overlay/opt/mu300/bin/mu300-update',
             'docs/GUI-BUILD.json':artifact/'build.json','tools/installer-hotfix/apply.py':HERE/'apply_hotfix.py'}
    for name in ('local-update.sh','android-write-part.sh','android-write-free.sh'):
        files['desktop/'+name] = TOP/'desktop'/name
    for name, source in files.items():
        target = destination/name
        target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(source,target)
    (destination/'APPLY-HOTFIX.cmd').write_bytes(
        b'@echo off\r\nchcp 65001 >nul\r\ncd /d "%~dp0"\r\n'
        b'"tools\\backend\\openwrt-backend.exe" --run-tool "tools\\installer-hotfix\\apply.py" "%cd%"\r\n'
        b'set "PATCH_EXIT=%ERRORLEVEL%"\r\npause\r\nexit /b %PATCH_EXIT%\r\n')
    guide = '''# MU300 Windows installer fix / MU300 Windows 安装器修复

1. 关闭旧安装器。将本 ZIP 的全部文件解压到原安装包目录，允许覆盖。不要只复制 EXE。
2. 双击 APPLY-HOTFIX.cmd。看到“安装器补丁校验完成”后关闭窗口。
3. 双击 OpenWrt-Installer.exe，选择“继续未完成的安装”，使用原记录重试更新。

本补丁适用于 MU300/F50/V50/U30Air 的 6.18、7.2 安装包，仅更新 Windows 安装器。
它修复旧版隐藏额外空间安装被 legacy 检查拒绝的问题。
无需重新分区、重装或清空 Android。请保留原包全部载荷、子目录和备份。
Mac 版本未更新。补丁不会连接或操作设备。
图形界面无需在日志输入 yes，只需确认页面上的最终安装计划。
更新 OpenWrt 不会格式化 Android userdata；首次安装需要重置时，以确认页面的数据影响为准。
若提示校验失败，停止并保留完整提示；不要跳过校验或改选首次分区安装。

Close the installer. Extract every ZIP member over the original package, run
APPLY-HOTFIX.cmd once, then open OpenWrt-Installer.exe and retry the original record.
The patch updates Windows host files only; device payloads, Mac binaries and saved
transactions stay in place. No separate Python or PowerShell installation is needed.
'''
    (destination/'HOTFIX-README.md').write_text(guide,encoding='utf-8',newline='\n')
    patch = {'format':1,'id':datetime.now().strftime('%Y%m%d-%H%M%S')+'-mu300-windows',
             'platform':'windows-x64','files':{p.relative_to(destination).as_posix():digest(p) for p in sorted(destination.rglob('*')) if p.is_file()}}
    (destination/'tools/installer-hotfix/patch.json').write_text(json.dumps(patch,indent=2)+'\n',encoding='utf-8',newline='\n')
    archive = destination.with_suffix('.zip')
    if archive.exists():raise ValueError('Patch archive already exists')
    with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as output:
        for path in sorted(destination.rglob('*')):
            if path.is_file():output.write(path,path.relative_to(destination).as_posix())
    with zipfile.ZipFile(archive) as output:
        if output.testzip():raise ValueError('Patch ZIP CRC failed')
    report = {'archive':str(archive),'sha256':digest(archive),'archive_bytes':archive.stat().st_size,
              'gui_bytes':(destination/'OpenWrt-Installer.exe').stat().st_size,
              'backend_bytes':sum(p.stat().st_size for p in (destination/'tools/backend').rglob('*') if p.is_file()),
              'firmware_payload_bytes':0,'patch_id':patch['id']}
    archive.with_suffix('.size.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    archive.with_suffix('.zip.sha256').write_text(report['sha256']+'  '+archive.name+'\n',encoding='utf-8')
    print(json.dumps(report,indent=2))
    return archive


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('destination',type=Path)
    parser.add_argument('--artifact',type=Path)
    args=parser.parse_args()
    build_patch(args.destination,args.artifact)
