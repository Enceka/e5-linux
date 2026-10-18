"""Apply the real hotfix with its frozen interpreter to disposable old-package copies."""
import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from backend.package import inspect_package


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('patch',type=Path)
    parser.add_argument('workspace',type=Path)
    parser.add_argument('packages',nargs='+',type=Path)
    parser.add_argument('--report',type=Path)
    args=parser.parse_args()
    if args.workspace.exists():raise ValueError('Use a new verification workspace')
    args.workspace.mkdir(parents=True)
    rows=[]
    for source in args.packages:
        before=inspect_package(source)
        target=args.workspace/source.name
        shutil.copytree(source,target,ignore=shutil.ignore_patterns('__pycache__'))
        with zipfile.ZipFile(args.patch) as archive:
            assert archive.testzip() is None
            assert all((target/name).resolve().is_relative_to(target.resolve()) for name in archive.namelist())
            archive.extractall(target)
        backend=target/'tools/backend/openwrt-backend.exe'
        command=[str(backend.resolve()),'--run-tool',str((target/'tools/installer-hotfix/apply.py').resolve()),str(target.resolve())]
        for _ in range(2):
            result=subprocess.run(command,capture_output=True,timeout=60)
            if result.returncode:raise RuntimeError(result.stderr.decode('utf-8','replace'))
        after=inspect_package(target)
        assert before['payloads']==after['payloads']
        result=subprocess.run([str(backend.resolve()),'--cli','--package-root',str(target.resolve()),'--check','--no-pause'],
                              capture_output=True,timeout=60)
        if result.returncode:raise RuntimeError(result.stderr.decode('utf-8','replace'))
        request=json.dumps({'protocol':1,'id':1,'command':'package','params':{'path':str(target.resolve())}})+'\n'
        result=subprocess.run([str(backend.resolve()),'--package-root',str(target.resolve()),'--data-dir',str((target/'test-state').resolve())],
                              input=request.encode(),capture_output=True,timeout=60)
        replies=[json.loads(line) for line in result.stdout.decode('utf-8').splitlines()]
        response=next(row for row in replies if row.get('type')=='response')
        assert result.returncode==0 and response['data']['ok'],response
        rows.append({'package':source.name,'kernel':before['kernel'],'real_frozen_patcher':True,
                     'repeat_apply':True,'cli_package_check':True,'ndjson_package_check':True,
                     'firmware_payloads_unchanged':True,'hardware_access':False})
        print(source.name+': patched package/CLI/protocol verified; firmware preserved',flush=True)
    if args.report:args.report.write_text(json.dumps(rows,indent=2)+'\n',encoding='utf-8')


if __name__=='__main__':main()
