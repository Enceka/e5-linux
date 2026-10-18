"""Run the shipped MU300 update backend against old packages and fake SSH only."""
import json
from pathlib import Path
import subprocess
import sys


def child(package):
    from contextlib import nullcontext, redirect_stdout
    import hashlib
    import builtins
    import getpass
    import io
    import struct
    import tempfile
    from types import SimpleNamespace
    import zlib
    import paramiko
    from backend.adapter import Adapter
    from backend.mu300_update import LEGACY_LAYOUT_PROBE
    from backend.package import inspect_package
    from backend.state import Context, Store, sha
    assert getattr(sys,'frozen',False)
    meta=inspect_package(package)
    assert meta['adapter']=='mu300'
    capacity=34779168768
    end=400000000;offset=(end//4096+1)*4096*512;sectors=capacity//512
    fields=['MU300-LEGACY-LAYOUT-V1','/dev/loop0','/dev/mmcblk0',offset,sectors,(256<<30)//512,sectors*512,end]
    raw=bytearray(1024);raw[56:58]=b'\x53\xef';raw[120:129]=b'mu300root'
    struct.pack_into('<I',raw,24,2);struct.pack_into('<I',raw,4,capacity//4096)
    live=bytearray(32);live[:4]=b'_a\0\0';live[4:8]=b'BCAB';live[8]=1;live[9]=2;live[12]=0x9f;live[14]=0x1e
    struct.pack_into('<I',live,28,zlib.crc32(live[:28]))
    key=hashlib.sha256(b'frozen-only-test-key').hexdigest()
    original_client=paramiko.SSHClient
    original_input=builtins.input
    original_getpass=getpass.getpass
    def no_console(*args,**kwargs):raise AssertionError('GUI attempted console input')
    builtins.input=no_console
    getpass.getpass=no_console
    results=[]
    try:
        for mode in ('legacy','sd','part','data-image'):
            with tempfile.TemporaryDirectory() as temp:
                root=Path(temp);archive=root/'tiny-rootfs.tar.gz';archive.write_bytes(b'fake staged archive')
                store=Store(root/'state')
                record=store.create(meta,{'serial':'ssh:'+key,'cid':'a'*32,'ssh_key':key},
                                    {'method':'update','host':'192.168.78.1'}, {'method':'update','openwrt_bytes':capacity})
                adapter=Adapter(meta,Context(store,record,lambda *_:None));adapter.password='fixture-only'
                prompt_output=io.StringIO()
                with redirect_stdout(prompt_output):
                    assert adapter.legacy.confirm('Userdata will be formatted and Android reset') is True
                assert prompt_output.getvalue()==''
                events=[];uploads={};probes=[]
                channel=SimpleNamespace(recv_exit_status=lambda:0)
                public_key=SimpleNamespace(asbytes=lambda:b'frozen-only-test-key')
                transport=SimpleNamespace(get_remote_server_key=lambda:public_key)
                client=SimpleNamespace(set_missing_host_key_policy=lambda *_:None,
                    connect=lambda *args,**kwargs:events.append('connect'),get_transport=lambda:transport,
                    exec_command=lambda *args,**kwargs:(None,SimpleNamespace(channel=channel,read=lambda:b'11111111-1111-4111-8111-111111111111'),None),
                    close=lambda:events.append('close'))
                paramiko.SSHClient=lambda:client
                def execute(c,command):
                    if 'cat /run/mu300/device' in command:return 'u30air\nb\n/dev/mmcblk0p3\n'+mode
                    if command==LEGACY_LAYOUT_PROBE:probes.append(command);return '\n'.join(map(str,fields))+'\n'
                    if command=='uname -r':return meta['kernel']+'.99-fixture'
                    if command.startswith('mkdir '):events.append('stage');return ''
                    if command.startswith('sha256sum '):return uploads[command.split(' ',1)[1]]+'  staged'
                    if command.startswith('chmod '):events.append('commit');return ''
                    raise AssertionError(command)
                adapter.legacy.ssh_exec=execute
                adapter.legacy.ssh_read_exact=lambda c,command,count:bytes(raw) if count==1024 else bytes(live)
                adapter.legacy.ssh_upload=lambda c,local,remote:uploads.__setitem__(remote,sha(local))
                adapter.legacy.payload_rootfs=lambda _:nullcontext(archive)
                def obsolete(*args,**kwargs):raise AssertionError('Old package update gate executed')
                adapter.legacy.update=obsolete
                adapter.legacy.confirm=no_console
                # The real package boot repacker executes; only transport and
                # the uploaded rootfs fixture are replaced. No device opens.
                with redirect_stdout(io.StringIO()):adapter.execute()
                assert events==['connect','stage','commit','close'],events
                assert record['effects']['update-commit']['state']=='done'
                assert record['status']=='waiting_device' and len(uploads)==8
                if mode=='legacy':
                    assert len(probes)==2 and record['update_layout']['capacity']==capacity
                    assert record['update_layout']['offset']==offset
                else:assert not probes
                results.append(mode)
    finally:
        paramiko.SSHClient=original_client
        builtins.input=original_input
        getpass.getpass=original_getpass
    print(json.dumps({'package':package.name,'kernel':meta['kernel'],'frozen_backend':True,
                      'modes':results,'real_package_boot_repacker':True,'old_gate_bypassed':True,
                      'original_capacity':capacity,'gui_console_input_blocked':True,
                      'gui_confirmation_no_output':True,'hardware_access':False}))


if __name__=='__main__':
    if len(sys.argv)>1 and sys.argv[1]=='--child':child(Path(sys.argv[2]).resolve())
    else:
        import argparse
        parser=argparse.ArgumentParser(description=__doc__)
        parser.add_argument('packages',nargs='+',type=Path)
        parser.add_argument('--backend',required=True,type=Path)
        parser.add_argument('--report',type=Path)
        args=parser.parse_args();rows=[]
        for package in args.packages:
            result=subprocess.run([str(args.backend.resolve()),'--run-tool',str(Path(__file__).resolve()),'--child',str(package.resolve())],
                                  capture_output=True,timeout=90)
            if result.returncode:raise RuntimeError(result.stderr.decode('utf-8','replace'))
            rows.append(json.loads(result.stdout.decode('utf-8')))
            print(package.name+': actual frozen update modes passed',flush=True)
        if args.report:args.report.write_text(json.dumps(rows,indent=2)+'\n',encoding='utf-8')
