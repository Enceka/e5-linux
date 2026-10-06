#!/usr/bin/env python3
"""Run the production modem-lock block under OpenWrt's BusyBox flock."""
import os
from pathlib import Path
import subprocess
import tempfile

TOP = Path(__file__).resolve().parents[2]
text = (TOP / 'openwrt/overlay/usr/sbin/e5-sim').read_text()
lock = text[text.index('if [ "${E5_SMS_MODEM_LOCKED'):text.index('\nlog()')]
with tempfile.TemporaryDirectory() as directory:
    root = Path(directory)
    (root / 'lock.sh').write_text('#!/bin/sh\nset -eu\n' + lock + '\n[ "$E5_SMS_MODEM_LOCKED" = 1 ]\necho acquired\n')
    (root / 'test.sh').write_text('''#!/bin/sh
set -eu
mkdir -p /tmp/run/e5-sms
# Acquires the real BusyBox lock, not a stub implementing util-linux flags.
sh /tests/lock.sh | grep -x acquired
exec 8>/tmp/run/e5-sms/modem.lock
flock -n 8
# Speed up contention retries without changing flock or locking semantics.
mkdir -p /tmp/fake-bin
printf '#!/bin/sh\nexit 0\n' > /tmp/fake-bin/sleep
chmod +x /tmp/fake-bin/sleep
if PATH=/tmp/fake-bin:$PATH sh /tests/lock.sh > /tmp/stdout 2>/tmp/stderr; then exit 1; fi
grep -x 'Modem is busy; try again shortly' /tmp/stderr
test ! -s /tmp/stdout
flock -u 8
sh /tests/lock.sh | grep -x acquired
echo 'BusyBox SIM lock checks passed: acquisition, contention, release'
''')
    subprocess.run(['docker', 'run', '--rm', '-v', f'{root}:/tests:ro',
                    os.environ.get('E5_TEST_IMAGE', 'e5-openwrt-base:25.12.5'),
                    '/bin/sh', '/tests/test.sh'], check=True)
