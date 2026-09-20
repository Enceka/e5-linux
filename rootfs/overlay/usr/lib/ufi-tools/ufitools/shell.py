"""Shell execution, replacing Android's ``ShellKano``/``RootShell`` pair.

On Android there is a real privilege boundary to cross: the app runs as an
unprivileged uid and reaches root through a ``socat`` UNIX socket that the
"advanced function" script creates, or through wireless adb.  A systemd unit on
Linux has no such boundary -- if it needs to run commands it runs as root and
says so in the unit file -- so the API keeps the same two endpoints but the
implementation collapses to ``/bin/sh -c``.

``/api/user_shell`` stays open because it is what the plugin system uses, while
``/api/root_shell`` honours the ``advanced_enabled`` flag so the security model
the UI describes ("高级功能未开启") is preserved instead of silently dropped.
"""

from __future__ import annotations

import os
import signal
import subprocess
from typing import Optional

DEFAULT_TIMEOUT = 100.0
MAX_TIMEOUT = 100.0

SHELL = "/bin/sh"


class ShellResult:
    """Same shape as ``KanoUtils.ShellResult``."""

    __slots__ = ("done", "content", "exit_code")

    def __init__(self, done: bool, content: str, exit_code: int):
        self.done = done
        self.content = content
        self.exit_code = exit_code

    def to_dict(self) -> dict:
        return {"done": self.done, "content": self.content}

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return "ShellResult(done=%r, exit_code=%r, content=%r)" % (
            self.done,
            self.exit_code,
            self.content[:120],
        )


def clamp_timeout(timeout) -> float:
    """``/api/root_shell`` caps the timeout at 100 s; keep that contract."""
    try:
        value = float(timeout)
    except (TypeError, ValueError):
        return DEFAULT_TIMEOUT
    if value <= 0:
        return DEFAULT_TIMEOUT
    return min(value, MAX_TIMEOUT)


def run_shell(command: str, timeout: float = DEFAULT_TIMEOUT, cwd: Optional[str] = None,
              env: Optional[dict] = None) -> ShellResult:
    """Run ``command`` through ``/bin/sh -c`` and capture stdout+stderr."""
    if not command or not command.strip():
        return ShellResult(False, "command 不能为空", 1)
    run_env = dict(os.environ)
    run_env.setdefault("PATH", "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin")
    if env:
        run_env.update({k: str(v) for k, v in env.items()})
    try:
        completed = subprocess.run(
            [SHELL, "-c", command],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            cwd=cwd,
            env=run_env,
            timeout=timeout,
            start_new_session=True,
        )
    except subprocess.TimeoutExpired as exc:
        partial = (exc.stdout or b"").decode("utf-8", "replace")
        return ShellResult(False, partial + "\n[超时 %ss]" % timeout, 124)
    except OSError as exc:
        return ShellResult(False, "执行失败: %s" % exc, 1)
    output = completed.stdout.decode("utf-8", "replace")
    return ShellResult(completed.returncode == 0, output, completed.returncode)


def run_shell_ok(command: str, timeout: float = 10.0) -> str:
    """Run a command and return its stripped stdout, or ``""`` on failure."""
    result = run_shell(command, timeout=timeout)
    return result.content.strip() if result.done else ""


def systemctl(action: str, unit: str, timeout: float = 30.0) -> ShellResult:
    """Run ``systemctl <action> <unit>``; used by the local hotspot controls."""
    if not unit:
        return ShellResult(False, "未配置单元名", 1)
    return run_shell("systemctl %s %s" % (action, unit), timeout=timeout)


def unit_active(unit: str) -> bool:
    result = run_shell("systemctl is-active %s" % unit, timeout=5.0)
    return result.content.strip() == "active"


def service_available() -> bool:
    """``true`` when systemd is running and can be driven."""
    return os.path.exists("/run/systemd/system")


def kill_process(name: str) -> ShellResult:
    return run_shell("pkill -f %s" % name, timeout=5.0)


def signal_process(pid: int, sig: int = signal.SIGTERM) -> bool:
    try:
        os.kill(pid, sig)
        return True
    except OSError:
        return False
