#!/usr/bin/env python3
"""Minimal telnet client for the e5-linux box.

The early initramfs shell had no login; now that a real root filesystem boots,
e5-telnetd.service hands out a login prompt, so this logs in first and then runs
each command, waiting for a sentinel instead of guessing how long output takes.

    E5_TELNET_USER=e5 E5_TELNET_PASS=... tools/e5-telnet.py 'command' ...

Credentials come from the environment and are never written to a file here:
they are the kind of thing that ends up in a log by accident.
"""
import os
import socket
import sys
import time

HOST = os.environ.get('E5_TELNET_HOST', '192.168.77.1')
PORT = int(os.environ.get('E5_TELNET_PORT', '23'))
USER = os.environ.get('E5_TELNET_USER', 'root')
PASS = os.environ.get('E5_TELNET_PASS', 'root')
END = '__E5_CMD_DONE__'
# Lines that mean the session is unusable and there is no point waiting.
FATAL = ('Login incorrect', 'Connection closed')


def connect(timeout=10):
    s = socket.create_connection((HOST, PORT), timeout=timeout)
    s.settimeout(timeout)
    return s


def read_until(s, markers, limit=45.0):
    """Read until one of markers appears. Returns (text, matched_marker_or_None)."""
    end = time.time() + limit
    buf = ''
    while time.time() < end:
        try:
            d = s.recv(4096)
        except socket.timeout:
            continue
        if not d:
            break
        buf += d.decode('utf-8', 'replace')
        for m in markers:
            if m in buf:
                return buf, m
        if any(f in buf for f in FATAL):
            return buf, 'FATAL'
    return buf, None


def _read_n(s, marker, n, limit):
    """Read until marker has been seen at least n times."""
    end = time.time() + limit
    buf = ''
    while time.time() < end:
        try:
            d = s.recv(4096)
        except socket.timeout:
            continue
        if not d:
            break
        buf += d.decode('utf-8', 'replace')
        if buf.count(marker) >= n:
            return buf, marker
        if any(f in buf for f in FATAL):
            return buf, 'FATAL'
    return buf, None


def login(s, log):
    out, m = read_until(s, ['login:', 'Password:', '# ', '$ ', '~ #'], limit=15)
    log.write(out)
    if m == 'FATAL' or m is None:
        return False
    if m in ('# ', '$ ', '~ #'):
        return True                      # already at a shell
    s.sendall(USER.encode() + b'\n')
    out, m = read_until(s, ['Password:', '# ', '$ ', 'Login incorrect'], limit=15)
    log.write(out)
    if m in ('# ', '$ '):
        return True
    if m != 'Password:':
        return False
    s.sendall(PASS.encode() + b'\n')
    # Deciding "logged in" from the prompt is unreliable here: bash's
    # bracketed-paste escapes and the login banner arrive interleaved, and the
    # prompt is usually consumed by the read that was waiting for the password,
    # so a successful login was being reported as "login failed".  Ask a question
    # that only a shell answers, and count its echo as well as its output.
    s.sendall(b'echo __E5_LOGIN_OK__\n')
    out, m = _read_n(s, '__E5_LOGIN_OK__', 2, 20)
    log.write(out)
    if m == '__E5_LOGIN_OK__':
        return True
    out, m = read_until(s, ['Login incorrect', '# ', '$ '], limit=10)
    log.write(out)
    return m in ('# ', '$ ')


def run(cmds, wait=60.0):
    s = connect()
    ok = login(s, sys.stdout)
    if not ok:
        print('\n[e5-telnet] login failed', file=sys.stderr)
        return 1
    rc = 0
    for c in cmds:
        s.sendall(('%s; echo %s\n' % (c, END)).encode())
        # The pty echoes the command back, so the sentinel appears once in the
        # echo of what we typed; only the second occurrence is real output.
        out, m = read_until(s, [END + '\r\n' + END], limit=wait) if False else _read_n(s, END, 2, wait)
        # strip the echoed command and the sentinel itself
        body = out.replace(END, '')
        for line in body.splitlines():
            if line.strip() == c.strip():
                continue
            print(line)
        if m is None:
            print('[e5-telnet] timed out waiting for command to finish', file=sys.stderr)
            rc = 2
            break
    s.close()
    return rc


if __name__ == '__main__':
    # Association and DHCP take tens of seconds, so allow a longer per-command wait.
    wait = float(os.environ.get('E5_TELNET_WAIT', '60'))
    sys.exit(run(sys.argv[1:] or ['echo hello'], wait=wait))
