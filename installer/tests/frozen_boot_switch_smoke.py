"""Run real packaged switch entrypoints against simulated installed boot metadata."""
import json
from pathlib import Path
import subprocess
import sys


def child(package,gui_only=False):
    import hashlib
    from types import SimpleNamespace
    from backend.adapter import Adapter,load
    from backend.package import inspect_package
    assert getattr(sys,'frozen',False)
    meta=inspect_package(package)
    if meta['adapter']=='mu300':
        return child_mu300(package,meta,gui_only)
    image=package/'files/boot.img';size=image.stat().st_size
    with image.open('rb') as stream:
        original=stream.read(4096);stream.seek(size-512);tail=stream.read(512)
    header=bytearray(original)
    command=bytes(header[44:1580]).split(b'\0',1)[0]+b' e5.fixture_release=previous'
    header[44:1580]=command.ljust(1536,b'\0')
    assert hashlib.sha256(header).digest()!=hashlib.sha256(original).digest()
    checks=[]
    for mode in (('gui',) if gui_only else ('gui','cli')):
        adapter=Adapter(meta) if mode=='gui' else None
        legacy=adapter.legacy if adapter else load(package/'OpenWrt-Installer.py','switch_cli_fixture')
        if not adapter:
            legacy.B=str(package);legacy.F=str(package/'files');legacy.SCRIPTS=str(package/'scripts')
        events=[];reads=[];invalid=False;chain_error=False
        def read(script):
            assert 'if=/dev/block/by-name/boot_b' in script and 'of=' not in script
            reads.append(script)
            return bytes(4096) if invalid else bytes(header) if 'count=8' in script else tail
        def forbidden(*args,**kwargs):raise AssertionError('Unexpected package hash or root access')
        def chain(mode):
            assert mode=='check'
            if chain_error:raise ValueError('fixture chain mismatch')
            events.append('chain-check')
        def adb(*args,**kwargs):
            assert args==('reboot',);events.append('reboot')
        legacy.steps=lambda *_:None;legacy.say=lambda *_:None
        legacy.find_adb=lambda:None;legacy.android_checks=lambda:None
        legacy.device_size=lambda target:size if target=='/dev/block/by-name/boot_b' else forbidden()
        legacy.boot_json=forbidden;legacy.bootchain=chain
        legacy.arm_slot_b=lambda:events.append('misc-trial')
        legacy.adb=adb;legacy.su_checked=forbidden
        if adapter:adapter.adb=SimpleNamespace(read=read)
        else:legacy.su=lambda command:read(command).hex()
        legacy.boot_openwrt(None)
        assert events==['chain-check','misc-trial','reboot'] and len(reads)==2
        events.clear();invalid=True
        try:legacy.boot_openwrt(None)
        except ValueError:pass
        else:raise AssertionError('Invalid boot accepted')
        assert not events
        invalid=False;chain_error=True
        try:legacy.boot_openwrt(None)
        except ValueError:pass
        else:raise AssertionError('Failed chain accepted')
        assert not events
        checks.append(mode)
    print(json.dumps({'package':package.name,'frozen_backend':True,'entrypoints':checks,
                      'different_installed_release_accepted':True,'small_boot_reads_only':True,
                      'unknown_boot_rejected':True,'chain_failure_blocks_misc':True,'hardware_access':False}))


def child_mu300(package,meta,gui_only):
    import contextlib
    import hashlib
    import io
    import struct
    import tempfile
    import zlib
    from types import SimpleNamespace
    from backend.adapter import Adapter,load
    from backend.state import Store,Context
    manifest=json.loads((package/'desktop/manifest.json').read_text())
    image=package/manifest['magisk_layout'].get('boot-linux.img','boot-linux.img')
    size=image.stat().st_size
    with image.open('rb') as stream:
        original=stream.read(4096);stream.seek(size-512);tail=stream.read(512)
    header=bytearray(original);header[44:1580]=b'console=tty0 loglevel=5 mu300.fixture_release=previous'.ljust(1536,b'\0')
    assert hashlib.sha256(header).digest()!=hashlib.sha256(original).digest()
    rows=[]
    with tempfile.TemporaryDirectory() as temp:
        for mode in (('gui',) if gui_only else ('gui','cli')):
            for model in ('MU300','F50','V50','U30Air'):
                for slot in ('a','b'):
                    events=[];reads=[];bodies=[]
                    before=bytearray(32);before[:4]=('_'+slot).encode()+b'\0\0';before[4:8]=b'BCAB';before[8]=1;before[9]=2
                    before[12],before[14]=(0x9f,0x1e) if slot=='a' else (0x1e,0x9f)
                    struct.pack_into('<I',before,28,zlib.crc32(before[:28]))
                    class Android:
                        def read(self,script):
                            reads.append(script)
                            if 'if=/dev/block/by-name/boot_'+self.slot+' ' in script:
                                current=bytearray(original);current[44:1580]=b'androidboot.fixture=stock'.ljust(1536,b'\0');return bytes(current)
                            assert 'if=/dev/block/by-name/boot_'+self.linux in script and 'of=' not in script
                            return bytes(header) if 'count=8' in script else tail
                        def shell(self,script):return str(size) if script.startswith('blockdev --getsize64 ') else ''
                        def live(self):return bytes(before)
                        def push(self,path,name):assert name in ('busybox','android-bootchain.sh')
                        def put(self,data,name):
                            assert name=='misc-trial.bin' and len(data)==32
                            assert data[:4]==(b'_b\0\0' if slot=='a' else b'_a\0\0')
                            assert zlib.crc32(data[:28])==struct.unpack_from('<I',data,28)[0]
                        def run(self,body):
                            if body.endswith('android-bootchain.sh" check'):events.append('chain-check')
                            else:
                                bodies.append(body);events.append('misc-trial')
                                assert 'count=32 conv=notrunc,fsync' in body
                                assert 'dd if="$backup" of=/dev/block/by-name/misc' in body
                                assert not any(word in body for word in ('mount ','of=/dev/block/by-name/boot','userdata','default-boot'))
                        def reboot(self):events.append('reboot')
                    android=Android();android.slot=slot;android.linux='b' if slot=='a' else 'a';android.model=model;android.bb='/fixture/busybox'
                    if mode=='gui':
                        store=Store(Path(temp)/(model+slot));record=store.create(meta,{'serial':'fixture','cid':'a'*32},{'method':'boot'},{'method':'boot','two_stage':False})
                        adapter=Adapter(meta,Context(store,record,lambda *_:None));legacy=adapter.legacy
                    else:
                        legacy=load(package/'OpenWrt-Installer.py','mu300_switch_fixture');legacy.package_root=lambda:package
                    names='V50\nMU3351' if model=='V50' else model
                    assert legacy.android_profile(names,'ums9620') in ('f50','v50','u30air')
                    legacy.Android=lambda *_:android
                    if mode=='gui':result=adapter.boot_mu300(SimpleNamespace())
                    else:
                        with contextlib.redirect_stdout(io.StringIO()):
                            result=legacy.install(SimpleNamespace(boot_openwrt=True),package,manifest)
                    assert result.state=='success' and events==['chain-check','misc-trial','reboot'] and len(reads)==3
                    if mode=='gui':
                        assert record['effects']['misc-trial']['state']=='done'
                        from backend.adapter import installation_committed
                        assert installation_committed(record)
                    rows.append({'entrypoint':mode,'model':model,'android_slot':slot})
    print(json.dumps({'package':package.name,'frozen_backend':True,'matrix':rows,'different_installed_release_accepted':True,
                      'small_boot_reads_only':True,'misc_trial_recorded':True,'hardware_access':False}))


if __name__=='__main__':
    if len(sys.argv)>1 and sys.argv[1]=='--child':child(Path(sys.argv[2]).resolve(),'--gui-only' in sys.argv[3:])
    else:
        import argparse
        parser=argparse.ArgumentParser(description=__doc__)
        parser.add_argument('packages',nargs='+',type=Path)
        parser.add_argument('--report',type=Path)
        parser.add_argument('--backend',type=Path)
        parser.add_argument('--gui-only',action='store_true')
        args=parser.parse_args();rows=[]
        for package in args.packages:
            backend=args.backend.resolve() if args.backend else package.resolve()/'tools/backend/openwrt-backend.exe'
            command=[str(backend),'--run-tool',str(Path(__file__).resolve()),'--child',str(package.resolve())]
            if args.gui_only:command.append('--gui-only')
            result=subprocess.run(command,capture_output=True,timeout=45)
            if result.returncode:raise RuntimeError(result.stderr.decode('utf-8','replace'))
            rows.append(json.loads(result.stdout.decode('utf-8')))
            print(package.name+': frozen GUI/CLI cross-release boot switch passed',flush=True)
        if args.report:args.report.write_text(json.dumps(rows,indent=2)+'\n',encoding='utf-8')
