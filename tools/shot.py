#!/usr/bin/env python3
"""Capture the compositor's output on the e5 and POST it to the build host.

Runs *on the device*; the build host has to be listening (work/upload-server.py
writes work/uploads/<name>).  Saves a lot of quoting when the screen has to be
looked at from the other side of a telnet connection.

    tools/shot.py [name.png] [--user e5]
"""
import os
import subprocess
import sys
import urllib.request

HOST = os.environ.get('E5_UPLOAD', 'http://192.168.9.2:8020/')


def main():
    name = sys.argv[1] if len(sys.argv) > 1 else 'shot.png'
    path = '/tmp/' + name
    env = {'XDG_RUNTIME_DIR': '/run/user/1000', 'WAYLAND_DISPLAY': 'wayland-0',
           'HOME': '/home/e5', 'PATH': '/usr/bin:/bin'}
    subprocess.run(['setpriv', '--reuid=1000', '--regid=1000', '--clear-groups',
                    'grim', path], env=env, check=True)
    with open(path, 'rb') as fh:
        data = fh.read()
    req = urllib.request.Request(HOST + name, data=data, method='POST')
    print(urllib.request.urlopen(req).read().decode())
    print('%s: %d bytes' % (path, len(data)))


if __name__ == '__main__':
    main()
