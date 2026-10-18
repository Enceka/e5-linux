"""Bounded, redacted diagnostic text; never used to drive installation state."""
import io
import re
import threading
import time


def redact(text, secrets=()):
    text = str(text)
    for value in sorted({str(v) for v in secrets if v}, key=len, reverse=True):
        text = text.replace(value, '[redacted]')
    # Mask credentials even when a legacy helper creates its own settings.
    text = re.sub(r"(?im)((?:[\w-]*(?:password|passwd|wifi_key|pwhash|token)|密码|密钥|key)\s*[:=]\s*)(?:'[^']*'|\"[^\"]*\"|[^\s;,]+)",
                  r'\1[redacted]', text)
    text = re.sub(r'\b[a-fA-F0-9]{32}\b', '[redacted-id]', text)
    # Strip terminal control sequences; these are text records, not a terminal.
    return re.sub(r'\x1b\[[0-?]*[ -/]*[@-~]', '', text).replace('\x00', '')


class DebugStream(io.TextIOBase):
    def __init__(self, context):
        self.context = context
        self.pending = ''
        self.lock = threading.RLock()

    def write(self, value):
        with self.lock:return self._write(value)

    def _write(self, value):
        self.pending += value.replace('\r', '\n')
        while '\n' in self.pending or len(self.pending) > 8192:
            line, separator, rest = self.pending.partition('\n')
            if not separator:
                line, rest = self.pending[:8192], self.pending[8192:]
            self.pending = rest
            if line.strip():self.context.log(line, scope='legacy')
        return len(value)

    def flush(self):
        with self.lock:
            if self.pending.strip():self.context.log(self.pending, scope='legacy')
            self.pending = ''


def traced(context, label, operation, output=False):
    if context is None:return operation()
    context.activity(label)
    context.log('BEGIN '+label, scope='transport')
    started = time.monotonic()
    try:
        result = operation()
    except BaseException as error:
        context.log(f'FAILED {label}: {type(error).__name__}: {error} ({time.monotonic()-started:.2f}s)',
                    level='error', scope='transport')
        raise
    context.log(f'END {label} ({time.monotonic()-started:.2f}s)', scope='transport')
    if output and isinstance(result, str) and result.strip():
        # Large encoded or root-image output is not a useful CLI diagnostic.
        if len(result) > 32768:context.log(f'Captured {len(result)} characters; tail:\n'+result[-4096:], scope='transport')
        else:context.log(result, scope='transport')
    return result
