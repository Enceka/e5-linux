#!/usr/bin/env python3
"""Fetch a Debian arm64 root filesystem straight from the Docker registry.

No container runtime is available in this sandbox, but the registry is just
HTTPS: resolve the arm64 manifest for debian:<suite>, download its layers and
untar them in order.  The result is exactly what the official image contains,
which is the cleanest unprivileged way to get a Debian userland (debootstrap
would need mknod, which an unprivileged user namespace cannot do on the host
filesystem).

usage: fetch-debian-rootfs.py <suite> <destdir>

Ownership and set-id bits.  Run as root on a Linux filesystem, the extraction
reproduces the image exactly (numeric ids: the tree's own /etc/group is the
authority, not the build host's).  Anywhere else it cannot: an unprivileged
user cannot chown, the kernel drops setgid on a file whose group the user is
not in, and a macOS bind mount does not store groups at all -- and a later
blanket "chown root:root" clears every set-id bit on top.  That is how the
device ended up with a 0755 root:root unix_chkpwd (every PAM password check
from the session user failed) and a setuid-less su.  So the ownership and
special bits of the image are also written, straight from the tar headers, to
<destdir>/var/lib/e5linux/base-perms, and overlay/opt/e5/e5-base-perms
restores them on whatever filesystem the tree finally lands on.
"""
import json
import os
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
    perms = {}
    for i, dg in enumerate(layers):
        blob = get(f'{REG}/v2/{REPO}/blobs/{dg}', h, raw=True)
        tmp = dest.parent / ('layer%d.tar' % i)
        tmp.write_bytes(blob)
        print('layer %d: %.1f MiB' % (i, len(blob) / 1048576))
        mode = 'r:*'
        with tarfile.open(tmp, mode) as tf:
            for m in tf:
                path = os.path.normpath(m.name).lstrip('/')
                if path == '.':
                    continue
                if not path or m.issym():
                    continue
                perms.pop(path, None)  # a later layer's entry replaces it
                if m.uid or m.gid or m.mode & 0o7000:
                    perms[path] = (m.mode & 0o7777, m.uid, m.gid)
            tf.extractall(dest, filter='fully_trusted', numeric_owner=True)
        tmp.unlink()
    print('extracted to', dest)

    out = dest / 'var/lib/e5linux/base-perms'
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, 'w') as f:
        f.write('# mode uid gid path -- non-root ownership and set-id/sticky bits of\n'
                '# the Debian base image, from its tar headers (fetch-debian-rootfs.py).\n'
                '# Replayed by /opt/e5/e5-base-perms.\n')
        for path in sorted(perms):
            m, u, g = perms[path]
            f.write('%04o %d %d %s\n' % (m, u, g, path))
    print('%d special entries recorded in %s' % (len(perms), out))
    if os.geteuid() != 0:
        print('not root: ownership and set-id bits were NOT applied; '
              'run overlay/opt/e5/e5-base-perms on the tree as root')


if __name__ == '__main__':
    main()
