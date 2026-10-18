"""Verify the shipped connection coordinator with an isolated fake ADB process."""
import json
from pathlib import Path
import subprocess
import sys


def child(package):
    import io
    import tempfile
    from types import SimpleNamespace
    from backend.service import Service
    from backend.state import DeviceLock, Store
    from backend import transport
    assert getattr(sys, 'frozen', False)
    devices = {'usb-fixture':'device'}
    commands = []
    original = transport.subprocess.run

    def run(argv, **kwargs):
        assert not kwargs.get('shell')
        assert Path(argv[0]).name.lower() in ('adb.exe','adb')
        args = argv[1:]; commands.append(args)
        if args == ['devices','-l']:
            output = 'List of devices attached\n'+''.join(s+' '+state+' model:Fixture\n' for s,state in devices.items())
        elif len(args)==2 and args[0]=='connect':
            devices[args[1]] = 'unauthorized'; output = 'ignored localized terminal text'
        elif len(args)==2 and args[0]=='disconnect':
            assert args[1] in devices and args[1]!='usb-fixture'
            del devices[args[1]]; output = 'ignored terminal text'
        else:
            raise AssertionError('Unexpected ADB operation: '+repr(args))
        return SimpleNamespace(returncode=0,stdout=output.encode(),stderr=b'')

    transport.subprocess.run = run
    try:
        with tempfile.TemporaryDirectory() as temp:
            service = Service(package, Store(temp), io.StringIO())
            def dispatch(command, **params):
                return service.dispatch({'protocol':1,'command':command,'params':params})
            result = dispatch('adb_connect', address='192.168.0.1')
            assert result['state']=='unauthorized' and len(result['devices'])==2
            assert result['endpoint']=='192.168.0.1:5555'
            count = len(commands)
            try: dispatch('adb_connect', address='--help')
            except ValueError: pass
            else: raise AssertionError('Option injection accepted')
            assert len(commands)==count
            try: dispatch('adb_disconnect', serial='usb-fixture')
            except ValueError: pass
            else: raise AssertionError('USB disconnect accepted')
            service.active = SimpleNamespace(record={'stage':'android_setup','status':'waiting_user','unsafe':False,'device':{'serial':'192.168.0.1:5555'}})
            service.worker = SimpleNamespace(is_alive=lambda:True)
            dispatch('adb_connect', address='192.168.0.1')
            assert service.active.record['device']['serial']=='192.168.0.1:5555'
            try: dispatch('adb_disconnect', serial='192.168.0.1:5555')
            except ValueError: pass
            else: raise AssertionError('Active transaction disconnected')
            service.worker = None
            count = len(commands)
            with DeviceLock(service.store.base,'192.168.0.1:5555'):
                try: dispatch('adb_disconnect', serial='192.168.0.1:5555')
                except ValueError as error: assert 'Another installer' in str(error)
                else: raise AssertionError('Device mutex bypassed')
            assert len(commands)==count
            result = dispatch('adb_disconnect', serial='192.168.0.1:5555')
            assert [d['serial'] for d in result['devices']]==['usb-fixture']
            assert ['disconnect','192.168.0.1:5555'] in commands
            assert not any(c==['disconnect'] or c[0] in ('shell','kill-server','tcpip') for c in commands)
    finally:
        transport.subprocess.run = original
    print(json.dumps({'frozen_backend':True,'wireless_connection':True,'authorization_state':True,
                      'exact_disconnect':True,'transaction_binding':True,'active_disconnect_blocked':True,'device_mutex':True,
                      'unsafe_arguments_rejected':True,'simulated_adb_only':True,'hardware_access':False}))


if __name__=='__main__':
    if len(sys.argv)>1 and sys.argv[1]=='--child': child(Path(sys.argv[2]).resolve())
    else:
        package=Path(sys.argv[1]).resolve()
        result=subprocess.run([str(package/'tools/backend/openwrt-backend.exe'),'--run-tool',str(Path(__file__).resolve()),'--child',str(package)],capture_output=True,timeout=30)
        if result.returncode: raise RuntimeError(result.stderr.decode('utf-8','replace'))
        print(result.stdout.decode('utf-8').strip())
