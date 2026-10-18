"""ZIP host packages without losing macOS execute bits on a Windows builder."""
from pathlib import Path
import stat
import zipfile


def write_member(archive, path, name):
    path = Path(path)
    info = zipfile.ZipInfo.from_file(path, name)
    mode = stat.S_IMODE(path.stat().st_mode)
    mac = name.startswith(('OpenWrt-Installer.app/', 'tools/macos/'))
    # Windows copy/extract/chmod cannot retain POSIX mode bits. Mach-O code,
    # the app entry and the bundled launchers must still execute after unzip.
    with path.open('rb') as stream:
        magic = stream.read(4) if mac else b''
        executable = (name.startswith('OpenWrt-Installer.app/Contents/MacOS/')
                      or name in ('tools/macos/adb', 'tools/macos/backend/openwrt-backend')
                      or name.startswith('launchers/') and name.endswith('.sh')
                      or mac and magic in (b'\xcf\xfa\xed\xfe', b'\xce\xfa\xed\xfe',
                                           b'\xfe\xed\xfa\xcf', b'\xfe\xed\xfa\xce',
                                           b'\xca\xfe\xba\xbe', b'\xbe\xba\xfe\xca'))
        if executable:
            mode = 0o755
        info.create_system = 3
        info.external_attr = (stat.S_IFREG | mode) << 16
        info.compress_type = zipfile.ZIP_STORED if path.suffix == '.gz' else zipfile.ZIP_DEFLATED
        stream.seek(0)
        with archive.open(info, 'w', force_zip64=True) as out:
            while chunk := stream.read(1 << 20):
                out.write(chunk)
