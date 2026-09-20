"""AT command endpoints: the ``atModule`` port.

``/api/AT`` accepts the same query parameter and answers the same
``{"result": "..."}`` shape; the work goes to :mod:`ufitools.at`, which on an
E5-LINUX device means the ``e5-atd`` broker, through the ``e5-at`` client.

The Android module's ``/api/getSupportNrBandList`` is gone: it existed to feed
the vendor's band-lock page, which has no counterpart here.
"""

from __future__ import annotations

from ..at import ATError, normalize_response
from ..httpd import ApiError, json_response


def register(router, app) -> None:
    def run_at(request):
        command = request.q("command")
        if not command:
            raise ApiError("AT指令执行错误：缺少 query 参数 command")
        command = command.strip()
        if not command.upper().startswith("AT"):
            raise ApiError("AT指令执行错误：解析失败，AT指令需要以 “AT” 开头")
        try:
            raw = app.at.run(command)
        except ATError as exc:
            raise ApiError("AT指令执行错误：%s" % exc)
        return json_response({"result": normalize_response(raw)})

    router.add("GET", "/api/AT", run_at)

    # Diagnostics: which AT backend is live, and when the cached modem snapshot
    # was last refreshed.  The first thing to look at when the status block is
    # empty.
    router.add("GET", "/api/at/status", lambda request: json_response({
        "backend": app.at.describe(),
        "available": app.at.available(),
        "socket": app.config.get("at_socket"),
        "device": app.config.get("at_device"),
        "poll_interval": app.config.at_poll_interval,
        "snapshot_age": round(app.modem.age, 1),
        "snapshot": app.modem.as_dict(),
    }))

    router.add("POST", "/api/at/refresh", lambda request: json_response({
        "result": "success",
        "snapshot": app.modem.refresh_now() if app.at.available() else {},
    }))
