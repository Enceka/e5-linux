#!/usr/bin/env python3
"""Run the image updater's config migration against disposable directories."""
from pathlib import Path
import subprocess
import tempfile

top = Path(__file__).resolve().parents[2]
source = (top / 'openwrt/device-install-image.sh').read_text()
start = source.index('keep_config() {')
function = source[start:source.index('\n}\n', start) + 3]
with tempfile.TemporaryDirectory() as directory:
    base = Path(directory)
    for bundled in (True, False):
        old, new = base / ('old-' + str(bundled)), base / ('new-' + str(bundled))
        def put(root, name, text):
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text)
        phone = 'etc/e5-infoscreen/plugins/phone/'
        for name, text in {
            'etc/config/network': 'user network', 'etc/shadow': 'user password',
            'etc/e5/contacts.json': 'user contacts', 'etc/e5/image-version': 'old',
            'etc/e5/sim-radio': '0 1\n',
            'etc/e5-infoscreen/plugins/other/user.json': 'other app data',
            phone + 'phone.js': 'old phone', phone + 'manifest.json': 'old manifest',
        }.items():
            put(old, name, text)
        for name in ('image-version', 'image-form', 'build-time'):
            put(new, 'etc/e5/' + name, 'new ' + name)
        if bundled:
            put(new, phone + 'phone.js', 'new phone')
            put(new, phone + 'manifest.json', 'new manifest')
        script = function.replace('/tmp/e5-img.', str(base / 'e5-img.'))
        subprocess.run(['sh', '-ec', script + '\nkeep_config "$1" "$2"',
                        'test', str(old), str(new)], check=True)
        assert (new / (phone + 'phone.js')).read_text() == ('new phone' if bundled else 'old phone')
        assert (new / 'etc/e5/contacts.json').read_text() == 'user contacts'
        assert (new / 'etc/e5/sim-radio').read_text() == '0 1\n'
        assert (new / 'etc/config/network').read_text() == 'user network'
        assert (new / 'etc/shadow').read_text() == 'user password'
        assert (new / 'etc/e5-infoscreen/plugins/other/user.json').read_text() == 'other app data'
        assert (new / 'etc/e5/image-version').read_text() == 'new image-version'
        assert not list(base.glob('e5-img.phone.*'))
print('PASS: bundled phone upgraded; contacts, credentials, settings and other apps preserved; legacy image fallback')
