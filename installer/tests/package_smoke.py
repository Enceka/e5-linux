"""Verify actual Windows distributions without connecting to any device."""
import argparse
import json
from pathlib import Path
import subprocess
import tempfile


def check(package):
    package=Path(package).resolve()
    backend=package/'tools/backend/openwrt-backend.exe'
    mu=(package/'desktop/manifest.json').is_file()
    row={'package':package.name,'commands':{}}
    for flag in (['--check','--check-boot'] if mu else ['--verify-package']):
        result=subprocess.run([str(backend),'--cli','--package-root',str(package),flag,'--no-pause'],capture_output=True,timeout=180)
        row['commands'][flag]={'exit':result.returncode,'stdout':result.stdout.decode('utf-8')[-1500:],
                              'stderr':result.stderr.decode('utf-8')[-1000:]}
        if result.returncode:raise RuntimeError(row['commands'][flag])
    with tempfile.TemporaryDirectory(prefix='openwrt-smoke-') as directory:
        requests=''.join(json.dumps({'protocol':1,'id':i,'command':command,'params':{}})+'\n'
                         for i,command in enumerate(['hello','package','list','probe']))
        result=subprocess.run([str(backend),'--package-root',str(package),'--data-dir',directory],
                              input=requests.encode('utf-8'),capture_output=True,timeout=180)
        events=[json.loads(line) for line in result.stdout.decode('utf-8').splitlines()]
        row['protocol_ok']=result.returncode==0 and len(events)==4 and all(e['data']['ok'] for e in events[:3]) and not events[3]['data']['ok']
        # The intentional missing-serial error exercises Chinese UTF-8 over the
        # real frozen protocol, without issuing even a device probe.
        row['utf8_error']=events[-1]['data'].get('error') if events else None
        if not row['protocol_ok']:raise RuntimeError(events)
    adb=subprocess.run([str(package/'tools/adb.exe'),'version'],capture_output=True,timeout=20)
    if adb.returncode:raise RuntimeError('Bundled ADB cannot start')
    row['adb_version']=adb.stdout.decode('utf-8')
    return row


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('packages',type=Path,nargs='+')
    parser.add_argument('--report',type=Path)
    options=parser.parse_args()
    results=[]
    for package in options.packages:
        results.append(check(package))
        print(package.name+': PASS',flush=True)
    if options.report:
        options.report.parent.mkdir(parents=True,exist_ok=True)
        options.report.write_text(json.dumps(results,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
