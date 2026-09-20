"""Scheduled task endpoints: the ``scheduledTaskModule`` port.

The stored shape is the same ``TaskInfo`` document the Android app uses
(``key``/``id``/``time``/``repeatDaily``/``actionMap``/``lastRunTimestamp``/
``hasTriggered``), so an exported task list can be moved between the two.
"""

from __future__ import annotations

from ..httpd import ApiError, json_response
from ..store import normalize_task


def register(router, app) -> None:
    def add_task(request):
        try:
            task = normalize_task(request.json_body())
        except ValueError as exc:
            raise ApiError(str(exc))
        app.tasks.add(task)
        return json_response({"result": "success"})

    router.add("POST", "/api/add_task", add_task)

    def remove_task(request):
        task_id = str(request.json_body().get("id") or "").strip()
        if not task_id:
            raise ApiError("缺少任务ID", 400)
        if not app.tasks.remove(task_id):
            raise ApiError("任务不存在", 404)
        return json_response({"result": "removed"})

    router.add("POST", "/api/remove_task", remove_task)

    def clear_task(request):
        app.tasks.replace([])
        return json_response({"result": "success"})

    router.add("POST", "/api/clear_task", clear_task)

    router.add("GET", "/api/list_tasks", lambda request: json_response(app.tasks.tasks()))

    def get_task(request):
        task_id = request.q("id")
        if not task_id:
            raise ApiError("缺少任务ID", 400)
        task = app.tasks.get(task_id)
        if task is None:
            raise ApiError("任务不存在", 404)
        return json_response(task)

    router.add("GET", "/api/get_task", get_task)

    # Extra: make the task engine's outcome observable.  Android only logs it.
    router.add("GET", "/api/task_history", lambda request: json_response(
        app.runtime.data.get("task_history") or []))
