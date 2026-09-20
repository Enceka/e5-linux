"""AT command execution -- the Linux replacement for Android's ``sendat``.

On Android, ``/api/AT`` shells out to the ``sendat`` binary, which goes through
``service call vendor.sprd.hardware.tool.IToolControl``.  On an E5 running
E5-LINUX the same job is done by ``unisoc-cpd``, which owns
``/dev/stty_nr1`` for the whole boot and runs AT as a capability of its own;
``/opt/e5/e5-at`` is the one-line client in front of it.  That daemon exists
because the tty has exactly one reader and because opening the command channel
per request makes the CP's queue overflow and the PS task assert, so this module
must talk to the daemon rather than poke the tty itself.  The default
configuration therefore uses the ``command`` backend below.

Three backends are supported, tried in this order:

``unix``     a Unix socket, one line in and response lines out (kept for
             deployments that broker AT over a socket rather than a fifo).
``tty``      a raw character device (``/dev/stty_nr1``); correct once, but do not
             point this at a busy CP for long.
``command``  an arbitrary helper (``/opt/e5/e5-at {cmd}`` on this image, or an
             Android ``sendat`` binary kept around during a migration).

The module never raises on "no backend": :meth:`ATRunner.available` reports it
and the API returns a clear error, which is what an operator on a device without
a modem needs to see.
"""

from __future__ import annotations

import os
import re
import select
import shlex
import socket
import stat
import subprocess
import termios
import time
import tty
from typing import List, Optional

#: Lines that end an AT response (the same set unisoc-cpd recognises).
FINAL_TOKENS = ("OK", "ERROR", "+CME ERROR", "+CMS ERROR", "CONNECT", "NO CARRIER")

AT_ECHO_RE = re.compile(r"^AT.*$", re.IGNORECASE)


class ATError(Exception):
    """Raised when an AT command cannot be delivered or times out."""


class ATBackend:
    name = "abstract"

    def available(self) -> bool:  # pragma: no cover - interface
        raise NotImplementedError

    def run(self, command: str, timeout: float) -> str:  # pragma: no cover
        raise NotImplementedError


class UnixSocketBackend(ATBackend):
    """Talk to a broker that serves AT over a Unix socket."""

    name = "unix"

    def __init__(self, path: str):
        self.path = path

    def available(self) -> bool:
        try:
            return stat.S_ISSOCK(os.stat(self.path).st_mode)
        except OSError:
            return False

    def run(self, command: str, timeout: float) -> str:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        try:
            sock.connect(self.path)
            sock.sendall((command + "\n").encode("utf-8"))
            chunks: List[bytes] = []
            while True:
                try:
                    chunk = sock.recv(4096)
                except socket.timeout:
                    break
                if not chunk:
                    break
                chunks.append(chunk)
        except OSError as exc:
            raise ATError("无法连接 AT 通道 %s: %s" % (self.path, exc)) from exc
        finally:
            sock.close()
        return b"".join(chunks).decode("utf-8", "replace")


class CharDeviceBackend(ATBackend):
    """Write/read a raw tty directly (fallback when no broker is running)."""

    name = "tty"

    def __init__(self, device: str):
        self.device = device

    def available(self) -> bool:
        try:
            return stat.S_ISCHR(os.stat(self.device).st_mode)
        except OSError:
            return False

    def run(self, command: str, timeout: float) -> str:
        try:
            fd = os.open(self.device, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
        except OSError as exc:
            raise ATError("无法打开 %s: %s" % (self.device, exc)) from exc
        try:
            try:
                tty.setraw(fd, termios.TCSANOW)
            except termios.error:
                pass
            deadline = time.monotonic() + timeout
            _drain(fd, min(0.3, timeout))
            os.write(fd, (command + "\r").encode("utf-8"))
            lines = _read_until_final(fd, deadline)
        finally:
            os.close(fd)
        return "\n".join(lines)


class CommandBackend(ATBackend):
    """Run an external helper; ``{cmd}``/``%s`` is replaced by the command."""

    name = "command"

    def __init__(self, template: str):
        self.template = template.strip()

    def available(self) -> bool:
        if not self.template:
            return False
        binary = self.template.split()[0]
        if "/" in binary:
            return os.path.exists(binary)
        from shutil import which

        return which(binary) is not None

    def _argv(self, command: str) -> List[str]:
        if "{cmd}" in self.template:
            rendered = self.template.replace("{cmd}", command)
            return shlex.split(rendered)
        if "%s" in self.template:
            return shlex.split(self.template % command)
        return shlex.split(self.template) + [command]

    def run(self, command: str, timeout: float) -> str:
        try:
            completed = subprocess.run(
                self._argv(command),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                timeout=timeout,
            )
        except (subprocess.TimeoutExpired, OSError) as exc:
            raise ATError("AT 助手执行失败: %s" % exc) from exc
        return completed.stdout.decode("utf-8", "replace")


def _drain(fd: int, seconds: float) -> None:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        ready, _, _ = select.select([fd], [], [], max(0.0, deadline - time.monotonic()))
        if not ready:
            return
        try:
            if not os.read(fd, 4096):
                return
        except OSError:
            return


def _read_until_final(fd: int, deadline: float) -> List[str]:
    buffer = b""
    lines: List[str] = []
    while time.monotonic() < deadline:
        ready, _, _ = select.select([fd], [], [], max(0.0, deadline - time.monotonic()))
        if not ready:
            break
        try:
            chunk = os.read(fd, 4096)
        except OSError:
            break
        if not chunk:
            break
        buffer += chunk
        while b"\n" in buffer:
            raw, buffer = buffer.split(b"\n", 1)
            line = raw.strip(b"\r").decode("utf-8", "replace").strip()
            if not line or AT_ECHO_RE.match(line):
                continue
            lines.append(line)
            if line.startswith(FINAL_TOKENS):
                return lines
    if buffer:
        tail = buffer.strip(b"\r").decode("utf-8", "replace").strip()
        if tail and not AT_ECHO_RE.match(tail):
            lines.append(tail)
    return lines


class ATRunner:
    """Selects and drives the first available AT backend."""

    def __init__(self, socket_path: str = "/run/e5-atd.sock", device: str = "/dev/stty_nr1",
                 command: str = "", timeout: float = 8.0, prefer_socket: bool = True):
        self.timeout = float(timeout or 8.0)
        backends = [UnixSocketBackend(socket_path), CharDeviceBackend(device), CommandBackend(command)]
        if not prefer_socket:
            backends.reverse()
        self.backends = backends

    def active(self) -> Optional[ATBackend]:
        for backend in self.backends:
            try:
                if backend.available():
                    return backend
            except OSError:
                continue
        return None

    def available(self) -> bool:
        return self.active() is not None

    def describe(self) -> str:
        backend = self.active()
        return backend.name if backend else "none"

    def run(self, command: str, timeout: Optional[float] = None) -> str:
        command = (command or "").strip()
        if not command:
            raise ATError("AT 指令为空")
        if not command.upper().startswith("AT"):
            raise ATError("解析失败，AT指令需要以 “AT” 开头")
        backend = self.active()
        if backend is None:
            raise ATError("没有可用的 AT 通道（unisoc-cpd 未运行，且找不到 AT 设备）")
        return backend.run(command, timeout or self.timeout)


def normalize_response(raw: str) -> str:
    """Reformat a raw AT response the way ``atModule.kt`` does.

    Newlines and quotes are removed, a trailing ``ok`` is normalised to `` OK``
    and a leading comma (this modem sometimes emits one) is dropped.
    """
    if raw is None:
        return ""
    text = raw.replace('"', '\\"').replace("\n", "").replace("\r", "").lstrip()
    if text.lower().endswith("ok"):
        text = text[:-2].rstrip() + " OK"
    if text.startswith(","):
        text = text[1:].lstrip()
    return text
