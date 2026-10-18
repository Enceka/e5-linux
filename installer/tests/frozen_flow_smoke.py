"""Exercise the actual shipped Python coordinator/backup code with fake transports."""
import json
from pathlib import Path
import subprocess
import sys

def child(package):
    if not getattr(sys, 'frozen', False):
        raise AssertionError('Frozen check failed')
    import hashlib
    import io
    import shlex
    import struct
    import tempfile
    from types import SimpleNamespace
    import paramiko
    import backend.transport as transport
    from backend.service import Service
    from backend.state import Context, Store
    from backend.package import inspect_package
    package_info = inspect_package(package)
    cid = 'b' * 32
    serial = 'simulated-only'
    data = bytes(range(256)) * 4096
    rows = []
    with tempfile.TemporaryDirectory() as directory:
        store = Store(directory)
        device = {'serial': serial, 'cid': cid, 'profile': package_info['profile'], 'model': 'Simulated device'}
        record = store.create(package_info, device, {'method': 'reinstall'}, {'method': 'reinstall', 'openwrt_bytes': 4 << 30, 'grow': True})
        context = Context(store, record, lambda *_: None)
        adb = transport.Adb.__new__(transport.Adb)
        adb.exe = 'fixture-adb'
        adb.serial = serial
        adb.su = 'su'
        adb.context = context
        adb.backup_staging = None
        files = {}
        calls = []

        def shell(command, **kwargs):
            calls.append(command)
            if command.startswith('blockdev'):
                return str(len(data))
            if command.startswith('df '):
                return str(1024 * 1024)
            if command.startswith('umask 077; mkdir '):
                return ''
            if command.startswith('set -e; umask 077; dd '):
                target = next((word[3:] for word in command.split() if word.startswith('of='))).rstrip(';')
                files[target] = data
                return ''
            if command.startswith('sha256sum '):
                return hashlib.sha256(files[shlex.split(command)[1]]).hexdigest() + ' file'
            if command.startswith('(set -o pipefail; cat '):
                return hashlib.sha256(data).hexdigest() + ' file'
            if command.startswith('rm -f '):
                files.pop(shlex.split(command)[2], None)
                return ''
            if command.startswith('rmdir '):
                return ''
            raise AssertionError('Unexpected simulated command')

        class Pull:
            returncode = 0

            def __init__(self, args, **kwargs):
                if not args[:4] == ['fixture-adb', '-s', serial, 'pull']:
                    raise AssertionError('Frozen check failed')
                Path(args[-1]).write_bytes(files[args[-2]])

            def communicate(self, **kwargs):
                return (b'1 file pulled', b'')

            def poll(self):
                return 0
        adb.shell = shell
        original = transport.subprocess.Popen
        try:
            transport.subprocess.Popen = Pull
            destination = Path(directory) / 'boot_a.bin'
            adb.backup_partition('boot_a', destination, context)
            adb.cleanup_backup(context)
            if not (destination.read_bytes() == data and (not files)):
                raise AssertionError('Frozen check failed')
            if not not any(('base64' in call or 'gzip' in call for call in calls)):
                raise AssertionError('Frozen check failed')
        finally:
            transport.subprocess.Popen = original
        rows.append('device dd -> adb pull, full hash and staging cleanup')
        service = Service(package, store, io.StringIO())
        superblock = bytearray(1024)
        superblock[56:58] = b'S\xef'
        struct.pack_into('<I', superblock, 24, 2)
        struct.pack_into('<I', superblock, 4, (4 << 30) // 4096)

        class SSH:

            def set_missing_host_key_policy(self, *_):
                pass

            def connect(self, *_, **kwargs):
                pass

            def close(self):
                pass

            def exec_command(self, command, **kwargs):
                if command == 'cat /sys/class/block/mmcblk0/device/cid':
                    value = cid.encode()
                elif command.startswith('readlink -f') or command == 'cat /run/mu300/disk-dev':
                    value = b'/dev/mmcblk0p74'
                elif command.startswith('dd if='):
                    value = bytes(superblock)
                elif command == 'test -s /etc/openwrt_release && test -x /sbin/init':
                    value = b''
                else:
                    raise AssertionError('Unexpected simulated SSH command')
                return (None, SimpleNamespace(read=lambda: value, channel=SimpleNamespace(recv_exit_status=lambda: 0)), None)

        def forbidden(*_):
            raise AssertionError('Installation/probe replayed')
        adapter = SimpleNamespace(password='', probe=forbidden, execute=forbidden)
        original = paramiko.SSHClient
        try:
            paramiko.SSHClient = SSH
            for stage in ('openwrt_boot', 'verify_capacity'):
                record.update(stage=stage, status='failed')
                store.save(record)
                loaded = Store(directory).load(record['id'])
                service.run(Context(store, loaded, service.emit), adapter)
                if not (loaded['status'] == 'completed' and loaded['result']['filesystem_bytes'] == 4 << 30):
                    raise AssertionError('Frozen check failed')
            record.update(stage='prepare', status='running', legacy=None, choices={'method': 'tf'}, plan={'method': 'tf', 'openwrt_bytes': 4 << 30, 'grow': True}, effects={'misc-trial' if package_info['adapter'] == 'e5' else 'root-tf-write': {'state': 'done'}})
            store.save(record)
            service.run(Context(store, record, service.emit), adapter)
            if not record['status'] == 'completed':
                raise AssertionError('Frozen check failed')
        finally:
            paramiko.SSHClient = original
        rows.append('restart during final verification and final commit without replay')
        # Exercise the actual frozen command handler and retry loop. Two fake
        # routers share a default address; only the selected target has this CID.
        record.update(stage='openwrt_boot',status='waiting_user')
        record['choices']['host']='192.0.2.1'
        context=Context(store,record,service.emit)
        service.active=context
        service.worker=SimpleNamespace(is_alive=lambda:True)
        hosts=[]
        class Routers(SSH):
            def connect(self,host,**kwargs):
                hosts.append(host)
                self.host=host
            def exec_command(self,command,**kwargs):
                if self.host=='192.0.2.1':
                    if command!='cat /sys/class/block/mmcblk0/device/cid':
                        raise AssertionError('Read another router beyond identity')
                    response=service.dispatch({'protocol':1,'command':'verify_openwrt','params':{
                        'transaction':record['id'],'host':'192.0.2.2','password':'frozen-private-password'}})
                    if not response['accepted']:raise AssertionError('Confirmation rejected')
                    return None,SimpleNamespace(read=lambda:b'0'*32,channel=SimpleNamespace(recv_exit_status=lambda:0)),None
                return super().exec_command(command,**kwargs)
        try:
            paramiko.SSHClient=Routers
            service.wait_openwrt(context,adapter)
        finally:paramiko.SSHClient=original
        if hosts!=['192.0.2.1','192.0.2.2'] or record['status']!='completed' or not record['openwrt_confirmed']:
            raise AssertionError('Explicit confirmation bypassed or failed verification')
        if 'frozen-private-password' in (context.directory/'transaction.json').read_text():
            raise AssertionError('SSH password was persisted')
        rows.append('explicit boot confirmation retargets wrong-CID endpoint and verifies capacity without replay')
        old_boot='11111111-1111-4111-8111-111111111111'
        new_boot='22222222-2222-4222-8222-222222222222'
        observed=[];root_reads=[];connection_attempts=[]
        record.update(stage='prepare',status='running',update_boot_id=old_boot,
                      effects={'update-commit':{'state':'done'}},choices={'method':'update','host':'192.0.2.2'},
                      plan={'method':'update','openwrt_bytes':4<<30,'grow':True})
        class UpdateSSH(SSH):
            def connect(self,*args,**kwargs):
                connection_attempts.append(True)
                if len(connection_attempts)==1:raise EOFError('Expected reboot disconnect')
                if len(connection_attempts)==2:raise ConnectionRefusedError('OpenWrt restarting')
            def exec_command(self,command,**kwargs):
                if command=='cat /proc/sys/kernel/random/boot_id':
                    value=old_boot if not observed else new_boot
                    observed.append(value)
                    return None,SimpleNamespace(read=lambda:value.encode(),channel=SimpleNamespace(recv_exit_status=lambda:0)),None
                if command.startswith('dd if='):root_reads.append(observed[-1])
                return super().exec_command(command,**kwargs)
        original_wait=service.stop.wait
        try:
            paramiko.SSHClient=UpdateSSH
            service.stop.wait=lambda _:False
            service.run(Context(store,record,service.emit),adapter)
        finally:
            paramiko.SSHClient=original
            service.stop.wait=original_wait
        if record['status']!='completed' or observed!=[old_boot,new_boot] or root_reads!=[new_boot]:
            raise AssertionError('Old runtime completed update before actual reboot')
        if not record['stage_finished_at']>=record['stage_started_at']:
            raise AssertionError('Terminal phase time not saved')
        events=[json.loads(line) for line in service.output.getvalue().splitlines()]
        reconnects=[e['data'] for e in events if e['type']=='transaction' and e['data'].get('details',{}).get('connection_state')=='reconnecting']
        if len(reconnects)!=2 or any(r['status']!='waiting_device' or r['details'].get('verification_error') for r in reconnects):
            raise AssertionError('Expected restart disconnect became a warning or failure')
        rows.append('committed update resumes without replay; EOF/refused connections remain normal waits; old boot rejected; new boot capacity verified; phase clock frozen')
        diagnostics = service.dispatch({'protocol': 1, 'command': 'diagnostics', 'params': {'transaction': record['id']}})['text']
        if not '"level": "debug"' in diagnostics:
            raise AssertionError('Frozen check failed')
        if not (serial not in diagnostics and cid not in diagnostics):
            raise AssertionError('Frozen check failed')
        if not ('Backup verified' in diagnostics and 'verify_capacity' in diagnostics):
            raise AssertionError('Frozen check failed')
        rows.append('persistent redacted diagnostic sharing')
    print(json.dumps({'package': package.name, 'frozen_backend': True, 'simulated_transport': True, 'checks': rows, 'hardware_access': False}))
if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] == '--child':
        child(Path(sys.argv[2]).resolve())
    else:
        import argparse
        parser = argparse.ArgumentParser(description=__doc__)
        parser.add_argument('packages', nargs='+', type=Path)
        parser.add_argument('--report', type=Path)
        parser.add_argument('--backend', type=Path)
        args = parser.parse_args()
        rows = []
        for package in args.packages:
            backend = args.backend.resolve() if args.backend else package.resolve() / 'tools/backend/openwrt-backend.exe'
            result = subprocess.run([str(backend), '--run-tool', str(Path(__file__).resolve()), '--child', str(package.resolve())], capture_output=True, timeout=60)
            if result.returncode:
                raise RuntimeError(result.stderr.decode('utf-8'))
            rows.append(json.loads(result.stdout.decode('utf-8')))
            print(package.name + ': frozen backup/recovery/diagnostics passed', flush=True)
        if args.report:
            args.report.write_text(json.dumps(rows, indent=2) + '\n', encoding='utf-8')
