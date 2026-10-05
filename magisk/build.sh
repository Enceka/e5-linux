#!/bin/bash
set -euo pipefail
TOP=$(cd "$(dirname "$0")/.." && pwd)
DEST="$TOP/out/magisk"
mkdir -p "$DEST"
STAGE=$(mktemp -d)
trap 'rm -rf "$STAGE"' EXIT
cp "$TOP/magisk/e5-linux-switch/"* "$STAGE/"
cp "$TOP/magisk/README.md" "$STAGE/README.md"
cp "$TOP/rootfs/overlay/opt/e5/e5-sd-registry" "$STAGE/sd-registry.sh"
# This arm64 static executable does not depend on Android's libc or Python.
docker run --rm --platform linux/arm64 -v "$STAGE":/module "${E5_MAGISK_BUILD_IMAGE:-e5-mainline-build}" \
 sh -ec 'gcc -static -Os -s -Wall -Wextra -Werror -o /module/e5-bootctl /module/bootctl.c'
rm "$STAGE/bootctl.c"
python3 - "$STAGE" "$DEST" <<'PY'
from pathlib import Path
from datetime import datetime, timedelta, timezone
import hashlib, os, stat, sys, time, zipfile
stage,out=map(Path,sys.argv[1:])
version=dict(line.split('=',1) for line in (stage/'module.prop').read_text().splitlines())['version']
stamp=datetime.fromtimestamp(int(os.environ.get('E5_BUILD_EPOCH',time.time())),timezone(timedelta(hours=8))).strftime('%Y%m%d-%H%M%S')
path=out/f'e5-linux-switch-{version}-{stamp}.zip'
with zipfile.ZipFile(path,'w',zipfile.ZIP_DEFLATED) as archive:
 for file in sorted(stage.iterdir()):
  info=zipfile.ZipInfo(file.name)
  info.external_attr=(stat.S_IFREG | (0o755 if file.name=='e5-bootctl' or file.suffix=='.sh' else 0o644))<<16
  archive.writestr(info,file.read_bytes(),compress_type=zipfile.ZIP_DEFLATED)
path.with_suffix('.zip.sha256').write_text(hashlib.sha256(path.read_bytes()).hexdigest()+'  '+path.name+'\n')
print(path)
PY
