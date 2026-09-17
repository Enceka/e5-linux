#!/usr/bin/env python3
"""Minimal logd writer-socket sink: lets Android vendor binaries (liblog) log on
plain Linux.  Binds /dev/socket/logdw (SOCK_DGRAM) and prints decoded lines."""
import os, socket, struct, sys

path = sys.argv[1] if len(sys.argv) > 1 else '/dev/socket/logdw'
os.makedirs(os.path.dirname(path), exist_ok=True)
try:
    os.unlink(path)
except FileNotFoundError:
    pass
s = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
s.bind(path)
os.chmod(path, 0o222)
sys.stdout.write('logdw: bound %s\n' % path)
sys.stdout.flush()
prios = '??VDIWEFS'
while True:
    data = s.recv(4096)
    if len(data) < 12 or data[0] in (2, 4):
        continue
    tid = struct.unpack_from('<H', data, 1)[0]
    sec = struct.unpack_from('<I', data, 3)[0]
    payload = data[11:]
    prio = payload[0]
    tag, _, rest = payload[1:].partition(b'\0')
    msg = rest.split(b'\0', 1)[0]
    sys.stdout.write('%d %5d %s %s: %s\n' % (
        sec, tid, prios[prio] if prio < len(prios) else '?',
        tag.decode('utf-8', 'replace'), msg.decode('utf-8', 'replace')))
    sys.stdout.flush()
