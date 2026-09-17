#!/usr/bin/env python3
"""Minimal telnet client for the e5-linux initramfs console."""
import socket, sys, time

HOST, PORT = '192.168.77.1', 23

def connect(timeout=8):
    s = socket.create_connection((HOST, PORT), timeout=timeout)
    s.settimeout(timeout)
    return s

def drain(s, seconds=2.0):
    end = time.time() + seconds
    buf = b''
    while time.time() < end:
        try:
            d = s.recv(4096)
            if not d:
                break
            buf += d
        except socket.timeout:
            break
    return buf

def run(cmds, wait=2.0):
    s = connect()
    # refuse all telnet options
    drain(s, 1.5)
    for c in cmds:
        s.sendall(c.encode() + b'\n')
        out = drain(s, wait)
        sys.stdout.write(out.decode('utf-8', 'replace'))
    s.close()

if __name__ == '__main__':
    cmds = sys.argv[1:] or ['echo hello']
    run(cmds)
