"""Audit first-party installer sources and preserved releases; never run ADB."""
import argparse
import io
import json
from pathlib import Path
import re
import tokenize
import zipfile

PATTERN=re.compile(r'\b(?:base64|b64encode|b64decode|encodebytes|decodebytes|btoa|atob|FromBase64String|ToBase64String)\b',re.I)
SUFFIXES={'.py','.sh','.ps1','.cmd','.bat','.rs','.ts','.tsx','.java','.c'}
EXCLUDE={'node_modules','target','artifacts','__pycache__','tests','test','.git'}
ROOTS=('installer/backend','desktop','openwrt/bundle','boot','tools','android-vendor','upstream')


def matches(name, data):
    text=data.decode('utf-8-sig',errors='replace')
    if name.endswith('.py'):
        # Keep executable strings (including remote shell commands), drop
        # Python comments. A mention in a docstring is conservatively reported.
        tokens=tokenize.generate_tokens(io.StringIO(text).readline)
        return sorted({token.start[0] for token in tokens if token.type!=tokenize.COMMENT and PATTERN.search(token.string)})
    return [number for number,line in enumerate(text.splitlines(),1)
            if not line.lstrip().startswith(('#','//','/*','*')) and PATTERN.search(line)]


def source_audit(repo):
    paths=set()
    for root in ROOTS:
        for path in (repo/root).rglob('*'):
            relative=path.relative_to(repo)
            if path.is_file() and path.suffix in SUFFIXES and not EXCLUDE.intersection(relative.parts) and not path.name.startswith(('test_','test-')):
                paths.add(path)
    paths.update(path for path in repo.glob('*') if path.is_file() and path.suffix in SUFFIXES)
    findings=[]
    for path in sorted(paths):
        lines=matches(path.name,path.read_bytes())
        if lines:findings.append({'file':path.relative_to(repo).as_posix(),'lines':lines})
    return {'files_checked':len(paths),'encoded_transfer_candidates':findings}


def release_audit(repo):
    rows=[]
    for root in (repo/'out/releases',repo/'release'):
        if not root.is_dir():continue
        for entry in sorted(root.rglob('OpenWrt-Installer.py')):
            files=[entry,entry.parent/'desktop/installer.py']
            findings=[path.relative_to(entry.parent).as_posix() for path in files if path.is_file() and matches(path.name,path.read_bytes())]
            rows.append({'path':entry.parent.relative_to(repo).as_posix(),'kind':'directory','encoded_cli_files':findings})
        for archive in sorted(root.rglob('*.zip')):
            with zipfile.ZipFile(archive) as bundle:
                names=set(bundle.namelist())
                entries=[name for name in names if name=='OpenWrt-Installer.py' or name.endswith('/OpenWrt-Installer.py')]
                if not entries:continue
                candidates=set(entries)
                for name in entries:
                    prefix=name.removesuffix('OpenWrt-Installer.py')
                    if prefix+'desktop/installer.py' in names:candidates.add(prefix+'desktop/installer.py')
                findings=[name for name in sorted(candidates) if matches(name,bundle.read(name))]
            rows.append({'path':archive.relative_to(repo).as_posix(),'kind':'archive','encoded_cli_files':findings})
    return rows


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('repository',type=Path)
    parser.add_argument('--releases',action='store_true')
    parser.add_argument('--report',type=Path)
    args=parser.parse_args();repo=args.repository.resolve()
    result={'repository':repo.name,'scope':list(ROOTS)+['root entrypoints'],'sources':source_audit(repo),'hardware_access':False}
    if args.releases:result['releases']=release_audit(repo)
    result['source_audit_passed']=not result['sources']['encoded_transfer_candidates']
    if args.report:args.report.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(result,indent=2))
    if not result['source_audit_passed']:raise SystemExit(1)


if __name__=='__main__':main()
