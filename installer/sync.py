"""Update the MU300 vendored shared installer in one direction, with hashes."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil

HERE = Path(__file__).resolve().parent
EXCLUDE = {'node_modules','dist','target','artifacts','__pycache__','.git','tsconfig.tsbuildinfo'}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('repository',type=Path)
    p.add_argument('--check',action='store_true')
    a=p.parse_args(); destination=a.repository.resolve()/'installer'
    files={p.relative_to(HERE).as_posix():p for p in HERE.rglob('*') if p.is_file() and not any(x in EXCLUDE for x in p.relative_to(HERE).parts) and p.name!='SHARED-SOURCE.json'}
    hashes={name:hashlib.sha256(path.read_bytes()).hexdigest() for name,path in files.items()}
    compatibility = {'desktop/binary_io.py':HERE/'backend/binary_io.py','desktop/boot_control.py':HERE/'backend/boot_image.py',
                     'desktop/update_control.py':HERE/'backend/mu300_update.py'} if (a.repository/'desktop/installer.py').is_file() else {}
    if a.check:
        if any(not (destination/name).is_file() or hashlib.sha256((destination/name).read_bytes()).hexdigest()!=h for name,h in hashes.items()):
            raise SystemExit('Shared installer differs; run installer/sync.py without --check')
        if any(not (a.repository/name).is_file() or (a.repository/name).read_bytes()!=path.read_bytes() for name,path in compatibility.items()):
            raise SystemExit('CLI binary helper differs; regenerate it from the shared backend')
    else:
        for name,path in files.items():
            target=destination/name;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(path,target)
        for name,path in compatibility.items():shutil.copy2(path,a.repository/name)
        (destination/'SHARED-SOURCE.json').write_text(json.dumps({'source':'e5-linux/installer','policy':'Generated mirror. Edit upstream then run sync.py; do not fork UI/protocol.','sha256':hashes},indent=2)+'\n')
    print('Shared installer synchronized:',len(files))


if __name__=='__main__':main()
