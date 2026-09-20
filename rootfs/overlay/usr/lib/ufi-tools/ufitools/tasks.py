"""Scheduled task execution (``/api/add_task`` and the scheduler loop).

A task action has exactly two shapes, both of them native:

* ``{"kind": "command", "command": "..."}`` -- run a shell command, which is what
  "定时执行维护动作" means on a Linux device;
* ``{"kind": "forward", "command": "..."}`` -- send the rendered text through the
  configured forwarding channel (``command`` is the optional template).

``kind`` may be omitted when a ``command`` is present: a bare command is the
common case for hand-written tasks and means the same as ``kind=command``.
Anything else is rejected with an explicit reason rather than being guessed at.

Failures are recorded in ``runtime.json`` so an operator can see why a nightly
action stopped happening instead of the failure vanishing into a log.
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

MAX_HISTORY = 20

DEFAULT_FORWARD_TEMPLATE = (
    "UFI-TOOLS 定时设备信息：\n"
    "型号: {{model}}\n"
    "开机时长: {{boot-time}}s\n"
    "CPU温度: {{cpu-temp}}\n"
    "内存占用: {{mem-usage}}%\n"
    "电池: {{battery-level}}%"
)


def _today_epoch(epoch_seconds: float) -> str:
    return time.strftime("%Y-%m-%d", time.localtime(epoch_seconds))


def _should_fire(task: Dict[str, Any], now: time.struct_time) -> bool:
    expected = "%02d:%02d" % (now.tm_hour, now.tm_min)
    if str(task.get("time") or "") != expected:
        return False
    last_ms = int(task.get("lastRunTimestamp") or 0)
    if last_ms:
        if _today_epoch(last_ms / 1000.0) == _today_epoch(time.time()):
            return False  # already fired today
        if not task.get("repeatDaily", True):
            return False
    return True


def parse_time(task: Dict[str, Any]) -> Optional[tuple]:
    parts = str(task.get("time") or "").split(":")
    if len(parts) < 2:
        return None
    try:
        return int(parts[0]), int(parts[1])
    except ValueError:
        return None


def run_task(app, task: Dict[str, Any]) -> Dict[str, Any]:
    """Execute one task and return a result record."""
    action: Dict[str, str] = task.get("actionMap") or {}
    started = time.time()
    result: Dict[str, Any] = {"id": task.get("id"), "at": int(started * 1000), "ok": False}

    try:
        result.update(_execute(app, action))
    except Exception as exc:  # noqa: BLE001 - reported to the operator
        result["detail"] = "执行失败: %s" % exc
    return result


def _execute(app, action: Dict[str, str]) -> Dict[str, Any]:
    kind = str(action.get("kind") or "").strip().lower()
    command = str(action.get("command") or "").strip()

    if kind == "forward":
        return _forward(app, command)

    if kind in ("", "command"):
        if not command:
            return {"ok": False, "detail": "任务缺少 command"}
        from .shell import run_shell

        outcome = run_shell(command, timeout=60.0)
        return {"ok": outcome.done, "detail": outcome.content[-400:]}

    return {"ok": False, "detail": "未知的 kind=%s（只支持 command 与 forward）" % kind}


def _forward(app, command: str) -> Dict[str, Any]:
    from . import forward
    from .traffic import today_bytes

    template = command or DEFAULT_FORWARD_TEMPLATE
    values = forward.build_device_info(app.config, app.device_info)
    values.update({"daily-flow": today_bytes(app)})
    method = str(app.config.get("sms_forward_method") or "")
    forward.dispatch(method, app.config.data, forward.expand_template(template, values))
    return {"ok": True, "detail": "forwarded via %s" % (method or "?")}


def run_due_restart(app, now: Optional[time.struct_time] = None) -> bool:
    """Honour the UI's "定时重启" switch.

    The Android app delegated this to the vendor backend; here the scheduler
    performs it, so the panel is not a knob that does nothing.
    """
    now = now or time.localtime()
    if str(app.config.get("restart_schedule_switch") or "0") != "1":
        return False
    expected = str(app.config.get("restart_time") or "")
    if expected != "%02d:%02d" % (now.tm_hour, now.tm_min):
        return False
    last = float(app.runtime.data.get("restart_last_at") or 0)
    if last and _today_epoch(last) == _today_epoch(time.time()):
        return False
    app.runtime.data["restart_last_at"] = time.time()
    app.runtime.save()
    app.log("scheduled restart at %s" % expected)
    app.control.reboot()
    return True


def run_due_tasks(app, now: Optional[time.struct_time] = None) -> List[Dict[str, Any]]:
    """Fire every task whose time matches the current minute."""
    now = now or time.localtime()
    due = [task for task in app.tasks.tasks() if _should_fire(task, now)]
    if not due:
        return []

    results: List[Dict[str, Any]] = []
    for task in due:
        outcome = run_task(app, task)
        results.append(outcome)
        task["lastRunTimestamp"] = int(time.time() * 1000)
        task["hasTriggered"] = True

    app.tasks.save()
    history = app.runtime.data.setdefault("task_history", [])
    history.extend(results)
    del history[:-MAX_HISTORY]
    app.runtime.save()
    return results
