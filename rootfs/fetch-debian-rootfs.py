#!/usr/bin/env python3
"""Fetch a Debian arm64 root filesystem straight from the Docker registry.

No container runtime is available in this sandbox, but the registry is just
HTTPS: resolve the arm64 manifest for debian:<suite>, download its layers and
untar them in order.  The result is exactly what the official image contains,
which is the cleanest unprivileged way to get a Debian userland (debootstrap
would need mknod, which an unprivileged user namespace cannot do on the host
filesystem).

usage: fetch-debian-rootfs.py <suite> <destdir>
"""
import json
import sys
import tarfile
import urllib.request
from pathlib import Path

REG = 'https://registry-1.docker.io'
REPO = 'library/debian'


def get(url, headers=None, raw=False):
    req = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(req, timeout=120) as r:
        data = r.read()
    return data if raw else json.loads(data)


def main():
    suite = sys.argv[1] if len(sys.argv) > 1 else 'trixie'
    dest = Path(sys.argv[2] if len(sys.argv) > 2 else 'rootfs')
    tok = get(f'https://auth.docker.io/token?service=registry.docker.io'
              f'&scope=repository:{REPO}:pull')['token']
    h = {'Authorization': f'Bearer {tok}',
         'Accept': 'application/vnd.oci.image.index.v1+json,'
                   'application/vnd.docker.distribution.manifest.list.v2+json'}

    index = get(f'{REG}/v2/{REPO}/manifests/{suite}', h)
    arm = None
    for m in index.get('manifests', []):
        p = m.get('platform', {})
        if p.get('architecture') == 'arm64' and p.get('os') == 'linux':
            arm = m['digest']
    if not arm:
        sys.exit('no arm64 manifest for %s' % suite)
    print('arm64 manifest', arm)

    h2 = dict(h)
    h2['Accept'] = ('application/vnd.oci.image.manifest.v1+json,'
                    'application/vnd.docker.distribution.manifest.v2+json')
    man = get(f'{REG}/v2/{REPO}/manifests/{arm}', h2)
    layers = [l['digest'] for l in man['layers']]
    print('%d layer(s)' % len(layers))

    dest.mkdir(parents=True, exist_ok=True)
    for i, dg in enumerate(layers):
        blob = get(f'{REG}/v2/{REPO}/blobs/{dg}', h, raw=True)
        tmp = dest.parent / ('layer%d.tar' % i)
        tmp.write_bytes(blob)
        print('layer %d: %.1f MiB' % (i, len(blob) / 1048576))
        mode = 'r:*'
        with tarfile.open(tmp, mode) as tf:
            tf.extractall(dest, filter='fully_trusted')
        tmp.unlink()
    print('extracted to', dest)


if __name__ == '__main__':
    main()
