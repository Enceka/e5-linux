"""Small JSON-file stores for the things Android kept in SharedPreferences.

The Android app splits its state over several preference files
(``kano_ZTE_store`` for config, ``kano_plugin_store`` for the plugin text) and
several JSON blobs for theme and scheduled tasks.  Every one of those is a
key/value document, so they are all instances of :class:`JsonFile` here; keeping
them as separate files (rather than one big config) means a plugin payload of a
few megabytes does not get rewritten every time the token changes.
"""

from __future__ import annotations

import json
import os
import threading
import time
import uuid
from typing import Any, Dict, List, Optional

#: Defaults identical to ``ThemeConfig`` in themeModule.kt.
DEFAULT_THEME: Dict[str, str] = {
    "backgroundEnabled": "false",
    "backgroundUrl": "",
    "textColor": "rgba(255, 255, 255, 1)",
    "textColorPer": "100",
    "themeColor": "201",
    "colorPer": "67",
    "saturationPer": "100",
    "brightPer": "21",
    "opacityPer": "21",
    "blurSwitch": "true",
    "overlaySwitch": "true",
}

#: The backend refuses plugin payloads larger than this (5 MiB, as on Android).
MAX_PLUGIN_BYTES = 5 * 1024 * 1024
#: The web UI stops at 10 MiB for uploads.
MAX_UPLOAD_BYTES = 10 * 1024 * 1024


class JsonFile:
    """Atomic, thread-safe JSON document with a default value."""

    def __init__(self, path: str, default: Any):
        self.path = path
        self._default = default
        self._lock = threading.RLock()
        self.data = json.loads(json.dumps(default))
        self.load()

    def load(self) -> None:
        with self._lock:
            try:
                with open(self.path, "r", encoding="utf-8") as handle:
                    loaded = json.load(handle)
                self.data = loaded
            except FileNotFoundError:
                pass
            except (OSError, ValueError):
                self.data = json.loads(json.dumps(self._default))

    def save(self) -> None:
        with self._lock:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as handle:
                json.dump(self.data, handle, ensure_ascii=False, indent=2)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp, self.path)

    def replace(self, value: Any, persist: bool = True) -> None:
        with self._lock:
            self.data = value
        if persist:
            self.save()

    def reset(self) -> None:
        self.replace(json.loads(json.dumps(self._default)))


class PluginStore(JsonFile):
    """``GET/POST /api/get_custom_head`` -- one text blob."""

    def __init__(self, path: str):
        super().__init__(path, {"text": ""})

    @property
    def text(self) -> str:
        if isinstance(self.data, dict):
            return str(self.data.get("text") or "")
        return ""

    def set_text(self, text: str) -> None:
        self.replace({"text": text or ""})


class ThemeStore(JsonFile):
    """``GET/POST /api/get_theme`` and ``/api/set_theme``."""

    def __init__(self, path: str):
        super().__init__(path, DEFAULT_THEME)

    def merged(self) -> Dict[str, str]:
        theme = dict(DEFAULT_THEME)
        if isinstance(self.data, dict):
            for key in DEFAULT_THEME:
                if key in self.data and self.data[key] is not None:
                    theme[key] = str(self.data[key])
        return theme

    def update(self, incoming: Dict[str, Any]) -> Dict[str, str]:
        theme = self.merged()
        if isinstance(incoming, dict):
            for key in DEFAULT_THEME:
                if key in incoming and incoming[key] is not None:
                    theme[key] = str(incoming[key])
        self.replace(theme)
        return theme


class TaskStore(JsonFile):
    """``/api/add_task`` and friends -- a list of scheduled actions."""

    def __init__(self, path: str):
        super().__init__(path, [])

    def tasks(self) -> List[Dict[str, Any]]:
        return self.data if isinstance(self.data, list) else []

    def add(self, task: Dict[str, Any]) -> None:
        tasks = self.tasks()
        task_id = str(task.get("id") or "")
        tasks = [t for t in tasks if str(t.get("id")) != task_id]
        tasks.append(task)
        self.replace(tasks)

    def remove(self, task_id: str) -> bool:
        tasks = self.tasks()
        remaining = [t for t in tasks if str(t.get("id")) != task_id]
        if len(remaining) == len(tasks):
            return False
        self.replace(remaining)
        return True

    def get(self, task_id: str) -> Optional[Dict[str, Any]]:
        for task in self.tasks():
            if str(task.get("id")) == task_id:
                return task
        return None


def normalize_task(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Validate an ``/api/add_task`` body and stamp the scheduling fields.

    ``time`` is ``HH:mm`` or ``HH:mm:ss``; the seconds are dropped exactly like
    the Kotlin implementation does.
    """
    task_id = str(payload.get("id") or "").strip()
    if not task_id:
        raise ValueError("缺少任务ID")
    raw_time = str(payload.get("time") or "").strip()
    parts = raw_time.split(":")
    if len(parts) < 2:
        raise ValueError("时间格式错误，应为 HH:mm")
    try:
        hour, minute = int(parts[0]), int(parts[1])
    except ValueError:
        raise ValueError("时间格式错误，应为 HH:mm")
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ValueError("时间超出范围")
    action = payload.get("action")
    if not isinstance(action, dict):
        raise ValueError("缺少 action")
    repeat = payload.get("repeatDaily", True)
    if isinstance(repeat, str):
        repeat = repeat.strip().lower() in ("1", "true", "yes")
    now = int(time.time() * 1000)
    return {
        "key": payload.get("key") or now,
        "id": task_id,
        "time": "%02d:%02d" % (hour, minute),
        "repeatDaily": bool(repeat),
        "actionMap": {str(k): str(v) for k, v in action.items()},
        "lastRunTimestamp": int(payload.get("lastRunTimestamp") or 0),
        "hasTriggered": bool(payload.get("hasTriggered") or False),
    }


def new_upload_name(original: str) -> str:
    ext = original.rsplit(".", 1)[-1].lower() if "." in original else "unknown"
    return "%s.%s" % (uuid.uuid4(), ext)
