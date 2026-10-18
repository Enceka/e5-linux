"""Read-only ADB enumeration through a real bundled backend before package checks."""
import argparse
import json
from pathlib import Path
import subprocess
import tempfile


def check(package):
    package=Path(package).resolve()
    with tempfile.TemporaryDirectory(prefix='openwrt-enumeration-') as directory:
        commands=['hello','devices','devices','list']
        requests=''.join(json.dumps({'protocol':1,'id':i,'command':command,'params':{}})+'\n' for i,command in enumerate(commands))
        result=subprocess.run([str(package/'tools/backend/openwrt-backend.exe'),'--package-root',str(package),'--data-dir',directory],input=requests.encode('utf-8'),capture_output=True,timeout=90)
        events=[json.loads(line) for line in result.stdout.decode('utf-8').splitlines()]
        if result.returncode or len(events)!=4 or not all(event['data']['ok'] for event in events):
            raise RuntimeError('Bundled enumeration failed: '+package.name)
        lists=[event['data']['result'] for event in events[1:3]]
        if not all(isinstance(values,list) for values in lists):raise AssertionError('Expected device lists')
        # Device identity remains private; report only count and transport state.
        row={'package':package.name,'commands':commands,'verified_package_required':False,
             'device_counts':[len(values) for values in lists],
             'states':[[device['state'] for device in values] for values in lists],
             'device_writes':False}
        print(package.name+': enumeration passed, counts='+str(row['device_counts']),flush=True)
        return row


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('packages',nargs='+',type=Path)
    parser.add_argument('--report',type=Path)
    args=parser.parse_args()
    rows=[check(package) for package in args.packages]
    if args.report:args.report.write_text(json.dumps(rows,indent=2)+'\n',encoding='utf-8')
