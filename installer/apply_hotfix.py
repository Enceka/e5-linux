"""Apply a MU300 Windows host-only overlay using its bundled interpreter."""
import hashlib
import json
from pathlib import Path
import re
import sys


HOST_FILES = {'OpenWrt-Installer.exe', 'OpenWrt-Installer.py', 'APPLY-HOTFIX.cmd', 'HOTFIX-README.md',
              'desktop/installer.py', 'desktop/binary_io.py', 'desktop/boot_control.py', 'desktop/update_control.py',
              'desktop/local-update.sh', 'desktop/mu300-update-library.sh', 'desktop/android-write-part.sh',
              'desktop/android-write-free.sh', 'docs/GUI-BUILD.json', 'tools/installer-hotfix/apply.py'}


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1 << 20), b''):h.update(block)
    return h.hexdigest()


def safe_file(root, name):
    if not isinstance(name, str) or '\\' in name or name.startswith('/') or '..' in name.split('/'):
        raise ValueError('Unsafe package path: '+str(name))
    path = (root/name).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise ValueError('Missing or unsafe package file: '+name)
    return path


def apply(root):
    root = Path(root).resolve()
    metadata = safe_file(root, 'tools/installer-hotfix/patch.json')
    patch = json.loads(metadata.read_text(encoding='utf-8'))
    if patch.get('format') != 1 or not re.fullmatch(r'[0-9]{8}-[0-9]{6}-mu300-windows', patch.get('id','')):
        raise ValueError('Unsupported installer patch')
    files = patch.get('files', {})
    if not {'OpenWrt-Installer.exe','tools/backend/openwrt-backend.exe','desktop/update_control.py'}.issubset(files):
        raise ValueError('Incomplete installer patch')
    for name, checksum in files.items():
        if (name not in HOST_FILES and not name.startswith('tools/backend/')) or not re.fullmatch('[0-9a-f]{64}',checksum):
            raise ValueError('Patch contains an unsupported host file: '+name)
        if digest(safe_file(root, name)) != checksum:
            raise ValueError('Patch file checksum failed; extract the complete ZIP again: '+name)
    manifest_path = safe_file(root, 'desktop/manifest.json')
    original = manifest_path.read_bytes()
    manifest = json.loads(original)
    if manifest.get('format') not in (1,2) or manifest.get('kernel') not in ('6.18','7.2'):
        raise ValueError('Select an extracted MU300 6.18 or 7.2 desktop package')
    previous = manifest.get('installer_hotfix', {}).get('id','')
    if previous > patch['id']:
        raise ValueError('This package already has a newer installer patch')
    payloads, desktop = manifest['magisk'], manifest['desktop']
    if len([name for name in payloads if name.endswith('mu300-openwrt.tar.gz')]) != 1:
        raise ValueError('Expected exactly one original MU300 firmware payload')
    if set(payloads) & set(files):
        raise ValueError('Refusing to replace a Magisk or firmware payload file')
    # Overlaid host files have their own expected hashes. Every other original
    # entry, including Mac binaries, must still match the original manifest.
    for name, checksum in {**payloads, **desktop}.items():
        if name in files or name == 'tools/installer-hotfix/patch.json':continue
        # A previous partial attempt may already have removed an obsolete
        # backend dependency. Retrying must not require that removed file.
        if name.startswith('tools/backend/') and not (root/name).exists():continue
        if digest(safe_file(root, name)) != checksum:
            raise ValueError('Original package checksum failed; use a complete original package: '+name)
    backup = root/'tools/installer-hotfix'/('manifest-before-'+hashlib.sha256(original).hexdigest()+'.json')
    if not backup.exists():backup.write_bytes(original)
    # Only obsolete files from the recorded Windows backend may be removed.
    obsolete = [name for name in desktop if name.startswith('tools/backend/') and name not in files]
    for name in obsolete:
        if (root/name).exists():safe_file(root, name).unlink()
        desktop.pop(name)
    desktop.update(files)
    desktop['tools/installer-hotfix/patch.json'] = digest(metadata)
    if 'desktop/installer.py' in files:
        manifest.setdefault('source', {})['installer.py'] = files['desktop/installer.py']
    manifest['installer_hotfix'] = {'id':patch['id'], 'platform':'windows-x64'}
    temporary = manifest_path.with_suffix('.json.hotfix-partial')
    temporary.write_text(json.dumps(manifest,indent=2)+'\n',encoding='utf-8',newline='\n')
    temporary.replace(manifest_path)
    print('Installer patch verified / 安装器补丁校验完成。')
    print('Open OpenWrt-Installer.exe and retry from the original saved record.\n请打开 OpenWrt-Installer.exe，从原记录重试更新。')
    print('Firmware and saved installation records were preserved / 固件载荷和电脑续装记录均已保留。')
    return patch['id']


if __name__ == '__main__':
    try:apply(Path(sys.argv[1]) if len(sys.argv)>1 else Path(__file__).resolve().parents[2])
    except (OSError,ValueError,KeyError,TypeError) as error:
        print('Patch stopped / 补丁已停止: '+str(error),file=sys.stderr)
        raise SystemExit(1)
