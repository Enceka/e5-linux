"""Allowlisted host converters with bounded execution and captured diagnostics."""
from pathlib import Path
import subprocess
import sys
import time
import types

from .diagnostics import traced
from .transport import hidden_process


def execute_script(path, arguments):
    """Keep script docstrings/guards even when the sidecar uses -OO.

    Helpers are separate source files. Their semantics must not depend on the
    optimization used to build the host executable.
    """
    path = Path(path).resolve()
    previous_main = sys.modules.get('__main__')
    previous_argv, previous_path = sys.argv, sys.path[:]
    module = types.ModuleType('__main__')
    module.__file__ = str(path)
    sys.modules['__main__'] = module
    sys.argv = [str(path), *arguments]
    sys.path.insert(0, str(path.parent))
    try:
        exec(compile(path.read_bytes(), str(path), 'exec', optimize=0), module.__dict__)
    finally:
        sys.argv, sys.path[:] = previous_argv, previous_path
        if previous_main is None:sys.modules.pop('__main__', None)
        else:sys.modules['__main__'] = previous_main


def run_helper(context, package, script, arguments, timeout=120):
    root = Path(package).resolve()
    script = Path(script).resolve()
    allowed = {root/'scripts/tools/sprd-bt-config.py', root/'scripts/tools/vbc-profile/vbc-profile.py'}
    if script not in allowed or not script.is_file():
        raise ValueError('Unsupported firmware converter / 不支持的固件转换器')
    context.boundary()
    context.stage('firmware_convert', tool=script.name)
    command = [sys.executable, *(['--run-tool'] if getattr(sys, 'frozen', False) else []), str(script), *map(str, arguments)]
    def perform():
        process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                   stderr=subprocess.STDOUT, **hidden_process())
        since = time.monotonic(); heartbeat = since
        try:
            while True:
                context.boundary()
                try:
                    output, _ = process.communicate(timeout=.2)
                    break
                except subprocess.TimeoutExpired:
                    now = time.monotonic()
                    if now-since >= timeout:
                        raise TimeoutError(f'Firmware converter {script.name} exceeded {timeout}s / 固件转换超时')
                    if now-heartbeat >= 5:
                        context.log(f'{script.name}: running, {now-since:.0f}s elapsed', scope='helper')
                        heartbeat = now
            if output:
                context.log(output.decode('utf-8', 'replace')[-32768:], scope='helper')
            if process.returncode:
                detail = context.sanitize(output.decode('utf-8', 'replace')[-4000:])
                raise ValueError(f'Firmware converter {script.name} failed ({process.returncode}) / 固件转换失败:\n{detail}')
        finally:
            if process.poll() is None:process.kill()
            process.communicate(timeout=5)
    return traced(context, 'firmware converter '+script.name, perform)
