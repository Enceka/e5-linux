#!/usr/bin/env python3
"""Persistent AT channel for the E5's baseband (what Android's urild does).

The CP pushes unsolicited results (+CSQ/+CESQ/+CREG/+CEREG/+SIND/+ECIND/...)
continuously.  Nothing in this port ever read /dev/stty_nr0, and the shell
`at()` in mobile-data opened /dev/stty_nr1 per command and closed it again, so
the CP's queue fills up and the PS task asserts:

    modem cmd Modem Assert: MN_AL Task PS CP assert ... The queue was full

This daemon holds both channels open for its whole lifetime, drains the URC
channel continuously, and serialises commands on the command channel with a
minimum gap, the way a RIL does.

  atd.py serve                 run in the foreground (systemd unit)
  atd.py cmd 'AT+CEREG?' [t]   send one command, print the response
  atd.py state                 print the state file

Verified facts this is built on: /dev/stty_nr0 is the URC channel (a 45 s read
dumps +CSQ/+CESQ pairs every ~2 s and the SIM/SMS URCs), /dev/stty_nr1 is silent
while idle and answers commands.
"""
import errno
import json
import os
import select
import socket
import sys
import termios
import time
import tty

URC_DEV = os.environ.get('E5_URC_DEV', '/dev/stty_nr0')
CMD_DEV = os.environ.get('E5_AT_DEV', '/dev/stty_nr1')
SOCK = os.environ.get('E5_AT_SOCK', '/run/e5-atd.sock')
STATE = os.environ.get('E5_AT_STATE', '/run/e5-atd.state')
URCLOG = os.environ.get('E5_AT_URCLOG', '/var/log/e5-atd.urc')
MIN_GAP = float(os.environ.get('E5_AT_MIN_GAP', '0.3'))
PROBE_EVERY = float(os.environ.get('E5_AT_PROBE', '60'))
CMD_TIMEOUT = float(os.environ.get('E5_AT_TIMEOUT', '8'))
FAIL_TIMEOUT = float(os.environ.get('E5_AT_FAIL_TIMEOUT', '30'))
URCLOG_MAX = int(os.environ.get('E5_AT_URCLOG_MAX', str(256 * 1024)))

FINAL = ('OK', 'ERROR', '+CME ERROR', '+CMS ERROR', 'CONNECT', 'NO CARRIER')


def log(msg):
    sys.stderr.write('%s %s\n' % (time.strftime('%H:%M:%S'), msg))
    sys.stderr.flush()


class Channel:
    """A char device we keep open forever."""

    def __init__(self, path):
        self.path = path
        self.fd = None
        self.buf = b''

    def open(self):
        try:
            fd = os.open(self.path, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
        except OSError as exc:
            if exc.errno not in (errno.ENODEV, errno.ENXIO, errno.EBUSY):
                log('open %s: %s' % (self.path, exc))
            return False
        try:
            tty.setraw(fd, termios.TCSANOW)
        except termios.error:
            pass
        self.fd = fd
        self.buf = b''
        return True

    def close(self):
        if self.fd is not None:
            try:
                os.close(self.fd)
            except OSError:
                pass
        self.fd = None

    def write(self, text):
        if self.fd is None:
            return False
        try:
            os.write(self.fd, text.encode())
            return True
        except OSError as exc:
            log('write %s: %s' % (self.path, exc))
            return False

    def read(self):
        try:
            return os.read(self.fd, 4096)
        except OSError:
            return b''

    def lines(self, data):
        self.buf += data
        out = []
        while b'\n' in self.buf:
            line, self.buf = self.buf.split(b'\n', 1)
            out.append(line.strip(b'\r').decode('utf-8', 'replace'))
        if len(self.buf) > 8192:
            out.append(self.buf[:8192].decode('utf-8', 'replace'))
            self.buf = b''
        return out


def append_urc(lines):
    if not lines:
        return
    try:
        with open(URCLOG, 'a') as f:
            stamp = time.strftime('%H:%M:%S')
            for line in lines:
                if line:
                    f.write('%s %s\n' % (stamp, line))
        if os.path.getsize(URCLOG) > URCLOG_MAX:
            with open(URCLOG) as f:
                tail = f.read()[-URCLOG_MAX // 2:]
            with open(URCLOG, 'w') as f:
                f.write(tail)
    except OSError:
        pass


class Server:
    def __init__(self):
        self.urc = Channel(URC_DEV)
        self.cmd = Channel(CMD_DEV)
        self.srv = None
        self.client = None
        self.last_ok = 0.0
        self.last_rx = 0.0
        self.last_probe = 0.0
        self.fails = 0
        self.urc_count = 0
        self.cmd_count = 0
        self.last_send = 0.0
        self.pending = False
        self.pending_cmd = ''
        self.pending_lines = []
        self.pending_deadline = 0.0
        self.pending_internal = False
        self.client_cmd = b''
        self.write_state('starting')

    def write_state(self, note):
        now = time.time()
        state = {
            'ts': round(now, 1),
            'note': note,
            'urc_dev': URC_DEV,
            'cmd_dev': CMD_DEV,
            'urc_open': self.urc.fd is not None,
            'cmd_open': self.cmd.fd is not None,
            'last_ok': round(self.last_ok, 1),
            'last_rx': round(self.last_rx, 1),
            'urc_lines': self.urc_count,
            'commands': self.cmd_count,
            'fails': self.fails,
        }
        tmp = STATE + '.tmp'
        try:
            with open(tmp, 'w') as f:
                json.dump(state, f)
            os.replace(tmp, STATE)
        except OSError:
            pass

    def open_channels(self):
        if self.urc.fd is None and self.urc.open():
            log('opened %s (URC channel)' % URC_DEV)
        if self.cmd.fd is None and self.cmd.open():
            log('opened %s (command channel)' % CMD_DEV)

    def reap(self, fd):
        if self.cmd.fd is not None and fd == self.cmd.fd:
            self.cmd.close()
            log('%s went away' % CMD_DEV)
        elif self.urc.fd is not None and fd == self.urc.fd:
            self.urc.close()
            log('%s went away' % URC_DEV)

    def serve(self):
        self.open_channels()
        if os.path.exists(SOCK):
            os.unlink(SOCK)
        self.srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.srv.bind(SOCK)
        os.chmod(SOCK, 0o666)
        self.srv.listen(4)
        self.srv.setblocking(False)
        log('listening on %s' % SOCK)
        self.loop()

    def loop(self):
        last_open_try = 0.0
        while True:
            fds = [self.srv]
            if self.urc.fd is not None:
                fds.append(self.urc.fd)
            if self.cmd.fd is not None:
                fds.append(self.cmd.fd)
            if self.client is not None:
                fds.append(self.client)
            try:
                ready, _, _ = select.select(fds, [], [], 5.0)
            except OSError as exc:
                if exc.errno == errno.EINTR:
                    continue
                raise
            for fd in ready:
                if fd is self.srv:
                    self.accept()
                elif self.client is not None and fd == self.client:
                    self.client_input()
                else:
                    data = self.urc.read() if fd == self.urc.fd else self.cmd.read()
                    if not data:
                        self.reap(fd)
                        continue
                    self.last_rx = time.time()
                    lines = (self.urc if fd == self.urc.fd else self.cmd).lines(data)
                    if fd == self.urc.fd:
                        self.urc_count += len(lines)
                        append_urc(lines)
                    else:
                        self.route_cmd_lines(lines)
            now = time.time()
            self.loop_timeouts(now)
            if (self.urc.fd is None or self.cmd.fd is None) and now - last_open_try > 10:
                last_open_try = now
                self.open_channels()
                self.write_state('reopened')
            if self.client is None and not self.pending and self.cmd.fd is not None \
                    and now - self.last_probe > PROBE_EVERY:
                self.probe()
            if self.client is None and self.fails >= 3 and now - self.last_ok > FAIL_TIMEOUT:
                self.fails = 0
                self.write_state('no answer')

    def accept(self):
        try:
            conn, _ = self.srv.accept()
        except OSError:
            return
        if self.client is not None:
            conn.close()
            return
        conn.setblocking(False)
        self.client = conn
        self.client_cmd = b''

    def client_input(self):
        try:
            data = self.client.recv(4096)
        except OSError:
            data = b''
        if not data:
            self.drop_client()
            return
        self.client_cmd += data
        if b'\n' not in self.client_cmd:
            return
        cmd, self.client_cmd = self.client_cmd.split(b'\n', 1)
        cmd = cmd.decode('utf-8', 'replace').strip()
        if cmd.lower().startswith('state'):
            self.client_send(json.dumps(self.state_dict()) + '\n')
            return
        if not cmd or self.cmd.fd is None:
            self.client_send('ERROR\n')
            return
        self.send_command(cmd)

    def state_dict(self):
        now = time.time()
        return {
            'ts': round(now, 1),
            'last_ok': round(self.last_ok, 1),
            'last_rx': round(self.last_rx, 1),
            'urc_lines': self.urc_count,
            'commands': self.cmd_count,
            'alive': (now - self.last_ok) < FAIL_TIMEOUT,
            'urc_open': self.urc.fd is not None,
            'cmd_open': self.cmd.fd is not None,
        }

    def client_send(self, text):
        if self.client is None:
            return
        try:
            self.client.sendall(text.encode())
        except OSError:
            self.drop_client()

    def drop_client(self):
        if self.client is not None:
            try:
                self.client.close()
            except OSError:
                pass
        self.client = None
        self.pending = False

    def send_command(self, cmd, internal=False):
        if time.time() - self.last_send < MIN_GAP:
            time.sleep(MIN_GAP - (time.time() - self.last_send))
        if not self.cmd.write(cmd + '\r'):
            if not internal:
                self.client_send('ERROR\n')
            self.drop_client()
            return
        self.last_send = time.time()
        self.cmd_count += 1
        self.pending = True
        self.pending_cmd = cmd
        self.pending_lines = []
        self.pending_deadline = time.time() + CMD_TIMEOUT
        self.pending_internal = internal
        self.write_state('command')

    def route_cmd_lines(self, lines):
        if not self.pending:
            for line in lines:
                append_urc([line])
            return
        for line in lines:
            if not line or line == self.pending_cmd:
                continue
            self.pending_lines.append(line)
            if line.startswith(FINAL):
                self.finish_command(line)
                return

    def finish_command(self, final):
        self.pending = False
        if final == 'OK' or final.startswith('CONNECT'):
            self.last_ok = time.time()
            self.fails = 0
        else:
            self.fails += 1
        self.write_state('answered')
        if not self.pending_internal:
            self.client_send('\n'.join(self.pending_lines) + '\n')
            self.drop_client()
        self.pending_lines = []

    def probe(self):
        self.last_probe = time.time()
        self.send_command('AT', internal=True)

    def loop_timeouts(self, now):
        if self.pending and now > self.pending_deadline:
            self.fails += 1
            self.write_state('timeout')
            if not self.pending_internal:
                self.client_send('ERROR\n')
                self.drop_client()
            self.pending = False


def _send_socket(cmd, timeout):
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.settimeout(timeout)
    s.connect(SOCK)
    s.sendall((cmd + '\n').encode())
    data = b''
    while True:
        chunk = s.recv(4096)
        if not chunk:
            break
        data += chunk
    s.close()
    return data.decode('utf-8', 'replace')


def main(argv):
    if len(argv) > 1 and argv[1] == 'serve':
        while True:
            try:
                Server().serve()
            except Exception as exc:  # keep the unit alive across channel resets
                log('server error: %r' % (exc,))
            time.sleep(2)
    if len(argv) > 1 and argv[1] == 'cmd':
        if len(argv) < 3:
            sys.stderr.write('usage: atd.py cmd <command> [timeout]\n')
            return 2
        timeout = float(argv[3]) if len(argv) > 3 else CMD_TIMEOUT + 5
        try:
            sys.stdout.write(_send_socket(argv[2], timeout))
        except OSError:
            sys.stderr.write('atd: cannot reach %s\n' % SOCK)
            return 3
        return 0
    if len(argv) > 1 and argv[1] == 'state':
        try:
            with open(STATE) as f:
                sys.stdout.write(f.read() + '\n')
            return 0
        except OSError:
            return 3
    sys.stderr.write(__doc__)
    return 2


if __name__ == '__main__':
    sys.exit(main(sys.argv))
