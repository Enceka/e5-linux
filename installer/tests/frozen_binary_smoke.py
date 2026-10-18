"""Exercise shipped binary readers and cached legacy backups without hardware."""
import json
from pathlib import Path
import subprocess
import sys


def child(package, legacy_package=False):
    import hashlib
    import tempfile
    from backend.adapter import Adapter, load
    from backend.binary_io import pull_binary
    from backend.package import inspect_package
    from backend.state import Context, Store, sha
    from backend.transport import Adb

    assert getattr(sys, 'frozen', False)
    data = bytes(range(256))*4096+b'\x00\r\n\xfftail'
    checksum = hashlib.sha256(data).hexdigest()
    calls = []
    scripts = []
    corrupt = False

    def shell(script, **kwargs):
        scripts.append(script)
        if script.startswith('df '): return '1048576'
        if script.startswith('umask 077; mkdir '): return ''
        if script.startswith('set -e; set -o pipefail;'):
            return str(len(data))+'\r\n'+checksum+'  data.bin\r\n'+checksum+'  -\r\n'
        if script.startswith('rm -f '): return ''
        raise AssertionError('Unexpected device command: '+script)

    def call(*args, **kwargs):
        assert args[0]=='pull' and args[1].startswith('/data/local/tmp/openwrt-read-')
        calls.append(args)
        Path(args[2]).write_bytes(b'X'+data[1:] if corrupt else data)
        return b'1 file pulled'

    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        local = root/'binary.bin'
        pull_binary(call, shell, 'cat /sys/firmware/fdt', local)
        assert local.read_bytes()==data
        corrupt = True
        try: pull_binary(call, shell, 'cat fixture', local)
        except ValueError: pass
        else: raise AssertionError('Corrupted download accepted')
        assert local.read_bytes()==data and not local.with_name('binary.bin.partial').exists()
        corrupt = False
        adb = Adb.__new__(Adb)
        adb.exe='fixture-adb'; adb.serial='selected'; adb.su='su'; adb.context=None
        adb.call=call; adb.shell=shell
        assert adb.read('cat /sys/firmware/fdt')==data
        meta = inspect_package(package)
        mu = meta['adapter']=='mu300'
        if mu and not legacy_package:
            cli = load(package/'OpenWrt-Installer.py', 'binary_cli_fixture')
            cli.package_root=lambda:package
            android = cli.Android.__new__(cli.Android)
            android.call=call; android.shell=shell
            assert android.read('cat /sys/firmware/fdt')==data
            assert (package/'desktop/binary_io.py').is_file()
        if mu:
            if legacy_package:
                assert '| base64' in (package/'OpenWrt-Installer.py').read_text(encoding='utf-8')
            storage={'CID':'a'*32,'NODE':'mmcblk0p30','START':2048,'SIZE':40000000,'DISK_SIZE':60000000}
            device={'serial':'selected','cid':'a'*32,'slot':'_a','storage':storage}
            store=Store(root/'transactions')
            record=store.create(meta,device,{}, {})
            record['completed']=['backup']
            ctx=Context(store,record,lambda *_:None)
            adapter=Adapter(meta,ctx)
            adapter.adb=adb
            legacy=adapter.legacy.Android.__new__(adapter.legacy.Android)
            legacy.serial='selected';legacy.slot='a'
            assert legacy.read('cat /sys/firmware/fdt')==data
            cache=ctx.directory/'backup';cache.mkdir()
            names=['misc.bin','gpt-first.bin','gpt-last.bin']+[f'{name}_{slot}.bin' for name in ('boot','uboot','sml','teecfg','trustos','vbmeta') for slot in ('a','b')]
            for name in names:(cache/name).write_bytes((name+'\n').encode()*20)
            (cache/'checksums.json').write_text(json.dumps({name:sha(cache/name) for name in names}))
            target=ctx.directory/'legacy-backups/fixture'
            before=len(calls)
            legacy.backup(target,storage)
            assert len(calls)==before
            assert (target/'boot_a.img').read_bytes()==(cache/'boot_a.bin').read_bytes()
            assert (target/'SHA256SUMS').is_file()
        assert all('base64' not in script and 'exec-out' not in script for script in scripts)
    print(json.dumps({'package':package.name,'frozen_backend':True,'raw_bytes_verified':True,
                      'corrupt_download_rejected':True,'shared_read':True,'mu300_cli_read':mu and not legacy_package,
                      'mu300_gui_read_override':mu,'legacy_package':legacy_package,
                      'mu300_cached_backup_reused':mu,'simulated_transport':True,'hardware_access':False}))


if __name__=='__main__':
    if len(sys.argv)>1 and sys.argv[1]=='--child': child(Path(sys.argv[2]).resolve(), '--legacy-package' in sys.argv[3:])
    else:
        import argparse
        parser=argparse.ArgumentParser(description=__doc__)
        parser.add_argument('packages',nargs='+',type=Path)
        parser.add_argument('--report',type=Path)
        parser.add_argument('--backend',type=Path)
        parser.add_argument('--legacy-package',action='store_true',help='Test only the GUI overrides against a deliberately old CLI')
        args=parser.parse_args();rows=[]
        for package in args.packages:
            backend=args.backend.resolve() if args.backend else package.resolve()/'tools/backend/openwrt-backend.exe'
            command=[str(backend),'--run-tool',str(Path(__file__).resolve()),'--child',str(package.resolve())]
            if args.legacy_package:command.append('--legacy-package')
            result=subprocess.run(command,capture_output=True,timeout=45)
            if result.returncode:raise RuntimeError(result.stderr.decode('utf-8','replace'))
            rows.append(json.loads(result.stdout.decode('utf-8')))
            print(package.name+': frozen binary transfer and backup checks passed',flush=True)
        if args.report:args.report.write_text(json.dumps(rows,indent=2)+'\n',encoding='utf-8')
