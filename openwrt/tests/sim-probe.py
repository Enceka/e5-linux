#!/usr/bin/env python3
"""Exercise the real pre-WWAN SIM probe against a fake AT port, never a modem."""
import errno
import os
from pathlib import Path
import pty
import select
import subprocess
import tempfile
import time

TOP = Path(__file__).resolve().parents[2]


def check(binary, preferred, responses, expected, delayed=False):
    master, slave = pty.openpty()
    port = binary.parent / 'late-port' if delayed else os.ttyname(slave)
    process = subprocess.Popen([str(binary), str(port), str(preferred)],
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if delayed:
        time.sleep(.3)
        os.symlink(os.ttyname(slave), port)
    commands, pending = [], b''
    deadline = time.monotonic() + 10
    try:
        while process.poll() is None:
            assert time.monotonic() < deadline, 'probe timed out'
            if not select.select([master], [], [], .1)[0]:
                continue
            pending += os.read(master, 4096)
            while b'\r' in pending:
                command, pending = pending.split(b'\r', 1)
                commands.append(command.decode())
                if command == b'AT':
                    response = 'OK'
                elif command in (b'AT+SPACTCARD=0;+CPIN?', b'AT+SPACTCARD=1;+CPIN?'):
                    response = responses[int(command.split(b'=')[1][:1])]
                else:
                    assert command == f'AT+SPACTCARD={expected};+CFUN?'.encode(), command
                    response = '+CFUN: 0\r\n\r\nOK'
                # Fragment a response to exercise stream parsing rather than packet assumptions.
                data = ('\r\n' + response + '\r\n').encode()
                os.write(master, data[:3])
                time.sleep(.005)
                os.write(master, data[3:])
        stdout, stderr = process.communicate(timeout=1)
        assert process.returncode == 0, stderr
        assert stdout.strip() == str(expected), (stdout, stderr)
        assert commands == ['AT', 'AT+SPACTCARD=0;+CPIN?', 'AT+SPACTCARD=1;+CPIN?',
                            f'AT+SPACTCARD={expected};+CFUN?'], commands
        assert 'secret' not in stdout + stderr
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()
        os.close(master)
        os.close(slave)


if __name__ == '__main__':
    present = '+CPIN: READY\r\n\r\nOK'
    absent = '+CME ERROR: 10'
    unknown = '+CME ERROR: 14'  # busy is not absence
    cases = [(0, [absent, present], 1), (1, [present, absent], 0),
             (0, [present, present], 0), (1, [present, present], 1),
             (0, [absent, absent], 0), (1, [absent, absent], 1),
             (0, [absent, '+CPIN: SIM PIN\r\n\r\nOK'], 1),
             (0, [unknown, present], 0), (0, [absent, unknown], 0)]
    with tempfile.TemporaryDirectory() as temporary:
        binary = Path(temporary) / 'probe'
        subprocess.run(['cc', '-DE5_SIM_PROBE_TEST', '-Wall', '-Wextra', '-Werror',
                        str(TOP / 'openwrt/src/e5-sim-probe.c'), '-o', str(binary)], check=True)
        for preferred, responses, expected in cases:
            check(binary, preferred, responses, expected)
        check(binary, 0, [absent, present], 1, delayed=True)
    print('SIM probe checks passed: both single slots, preference, empty, locked, unknown, read-only AT')
