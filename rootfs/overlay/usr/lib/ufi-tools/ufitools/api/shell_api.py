"""Shell and "advanced function" endpoints: ``advancedToolsModule`` port.

On Android "高级功能" is an elaborate bootstrap: samba config injection, a
``socat`` root-shell socket, ``ttyd``, a keep-alive script, FOTA disabling.  On
Linux most of that collapses into things systemd already does, so this module
keeps the *contract* (paths, response shapes, the fact that ``root_shell`` needs
the flag) and implements it with systemd units and ``/bin/sh``.
"""

from __future__ import annotations

import os
import urllib.error
import urllib.request

from ..httpd import ApiError, json_response
from ..shell import clamp_timeout, run_shell, systemctl

ADVANCED_OK_MESSAGE = "执行成功<br>Execution successful！"


def _ttyd_unit(app) -> str:
    return str(app.config.get("ttyd_unit") or "ttyd.service")


def _one_click_script(app) -> str:
    configured = str(app.config.get("one_click_shell") or "").strip()
    if configured:
        return configured
    return os.path.join(app.config.data_dir, "one_click_shell.sh")


def register(router, app) -> None:
    config = app.config

    def smb_path(request):
        enable = request.q("enable")
        if enable is None:
            raise ApiError("缺少 query 参数 enable")
        if enable == "1":
            unit = _ttyd_unit(app)
            if systemctl("start", unit).done:
                app.log("advanced: %s started" % unit)
            config.set("advanced_enabled", True)
            return json_response({"result": ADVANCED_OK_MESSAGE})
        unit = _ttyd_unit(app)
        systemctl("stop", unit)
        config.set("advanced_enabled", False)
        return json_response({"result": "已关闭高级功能<br>Advanced features disabled"})

    router.add("GET", "/api/smbPath", smb_path)

    def disable_fota(request):
        # There is no vendor OTA agent on a Debian image; report that honestly
        # rather than claiming a change that did not happen.
        return json_response({"result": "当前系统没有可禁用的 OTA 服务<br>No OTA agent on this system"})

    router.add("GET", "/api/disable_fota", disable_fota)

    def has_ttyd(request):
        port = request.q("port")
        if not port:
            raise ApiError("缺少 query 参数 port")
        host = str(config.get("gateway_ip") or "").split(":")[0] or "127.0.0.1"
        url = "http://%s:%s/" % (host, port)
        code = "000"
        try:
            with urllib.request.urlopen(url, timeout=3) as response:
                code = str(response.status)
        except urllib.error.HTTPError as exc:
            code = str(exc.code)
        except Exception:  # noqa: BLE001 - unreachable is the normal negative
            code = "000"
        return json_response({"code": code, "ip": "%s:%s" % (host, port)})

    router.add("GET", "/api/hasTTYD", has_ttyd)

    def user_shell(request):
        command = str(request.json_body().get("command") or "")
        if not command.strip():
            raise ApiError("command 不能为空")
        result = run_shell(command, timeout=clamp_timeout(request.json_body().get("timeout")))
        return json_response({"result": result.to_dict()})

    router.add("POST", "/api/user_shell", user_shell)

    def root_shell(request):
        app.require_advanced()
        body = request.json_body()
        command = str(body.get("command") or "")
        if not command.strip():
            raise ApiError("command 不能为空")
        result = run_shell(command, timeout=clamp_timeout(body.get("timeout")))
        return json_response({"result": result.to_dict()})

    router.add("POST", "/api/root_shell", root_shell)

    def one_click_shell(request):
        app.require_advanced()
        script = _one_click_script(app)
        if not os.path.isfile(script):
            raise ApiError("一键脚本不存在: %s" % script)
        result = run_shell("/bin/sh %s" % script, timeout=120.0)
        return json_response({"result": result.to_dict()})

    router.add("GET", "/api/one_click_shell", one_click_shell)

    def advanced_status(request):
        unit = _ttyd_unit(app)
        return json_response({
            "advanced_enabled": app.advanced,
            "ttyd_unit": unit,
            "one_click_shell": _one_click_script(app),
        })

    router.add("GET", "/api/advanced/status", advanced_status)
