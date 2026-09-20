"""Base device information: the ``baseDeviceInfoModule`` port.

Shape-for-shape port of ``GET /api/baseDeviceInfo`` and friends, reading the
local ``/proc`` and ``/sys``.  The Android version reported the *managed* device,
which on a phone was the hotspot it controlled; here the device UFI-TOOLS runs on
and the device it manages are the same machine, so there is no second source and
no mode switch.
"""

from __future__ import annotations

from .. import APP_VER, APP_VER_CODE
from ..httpd import ApiError, json_response
from ..traffic import month_bytes, range_bytes, range_daily, today_bytes


def _selinux_status() -> str:
    """Linux has SELinux, AppArmor or neither; the UI only gates on SELinux."""
    try:
        with open("/sys/fs/selinux/enforce", "r", encoding="ascii") as handle:
            return "Enforcing" if handle.read().strip() == "1" else "Permissive"
    except OSError:
        return "Disabled"


def register(router, app) -> None:
    config = app.config
    info = app.device_info

    def version_info(request):
        return json_response({
            "app_ver": APP_VER,
            "app_ver_code": str(APP_VER_CODE),
            "model": _model(app),
            "nickname": str(config.get("nickname") or ""),
            "accept_terms": config.get_bool("isReadUseTerms", False),
        })

    router.add("GET", "/api/version_info", version_info)

    router.add("GET", "/api/need_token",
               lambda request: json_response({"need_token": config.token_enabled}))

    router.add("GET", "/api/SELinux", lambda request: json_response({"selinux": _selinux_status()}))

    def base_device_info(request):
        battery = info.battery()
        max_temp, thermal = info.thermal()
        usage_json, cpu_usage = info.cpu_usage()
        mem_json, mem_usage = info.memory()
        internal = info.storage(config.data_dir)

        return json_response({
            "app_ver": APP_VER,
            "app_ver_code": str(APP_VER_CODE),
            "model": _model(app),
            "battery": str(battery.get("percent", -1)),
            "daily_data": today_bytes(app),
            "monthly_data": month_bytes(app),
            "internal_available_storage": internal["available"],
            "internal_used_storage": internal["used"],
            "internal_total_storage": internal["total"],
            "external_total_storage": 0,
            "external_used_storage": 0,
            "external_available_storage": 0,
            "cpu_temp_list": thermal,
            "cpu_temp": max_temp,
            "client_ip": request.client_ip,
            "cpu_usage": cpu_usage,
            "mem_usage": mem_usage,
            "cpuFreqInfo": info.cpu_freq(),
            "cpuUsageInfo": usage_json,
            "memInfo": mem_json,
            "current_now": battery.get("current_uA"),
            "voltage_now": battery.get("voltage_uV"),
            "is_reached_data_flow_limit": bool(config.get("kano_data_flow_reached", False)),
            "uptime": info.uptime(),
            "modem": app.modem.as_dict(),
        })

    router.add("GET", "/api/baseDeviceInfo", base_device_info)

    def conn_info(request):
        counts = info.conn_counts()
        return json_response({
            "result": "success",
            "data": {
                "tcp": str(counts["tcp"]),
                "tcp_active": str(counts["tcp_active"]),
                "tcp_other": str(counts["tcp_other"]),
                "tcp6": str(counts["tcp6"]),
                "udp": str(counts["udp"]),
                "udp6": str(counts["udp6"]),
                "unix": str(counts["unix"]),
            },
        })

    router.add("GET", "/api/connInfo", conn_info)

    def cellular_usage(request):
        start_raw = request.q("startTime")
        end_raw = request.q("endTime")
        if not start_raw:
            raise ApiError("获取流量使用情况出错:缺少参数 startTime")
        if not end_raw:
            raise ApiError("获取流量使用情况出错:缺少参数 endTime")
        try:
            start_ms, end_ms = int(start_raw), int(end_raw)
        except ValueError:
            raise ApiError("获取流量使用情况出错:时间参数非法")
        if request.q("method", "date-range") == "mills-range":
            return json_response({"result": "success", "usage": str(range_bytes(app, start_ms, end_ms))})
        return json_response({"result": "success", "usage": range_daily(app, start_ms, end_ms)})

    router.add("GET", "/api/cellularUsage", cellular_usage)

    def accept_terms(request):
        config.set("isReadUseTerms", True)
        return json_response({"result": "success"})

    router.add("POST", "/api/accept_terms", accept_terms)

    def set_nickname(request):
        nickname = str(request.json_body().get("nickname") or "").strip()[:255]
        config.set("nickname", nickname)
        return json_response({"result": "success"})

    router.add("POST", "/api/set_nickname", set_nickname)

    router.add("GET", "/api/device_id", lambda request: json_response({
        "device_id": str(config.get("device_uuid") or ""),
    }))

    def usb_status(request):
        max_speed, details = info.usb()
        return json_response({"maxSpeed": max_speed, "details": details})

    router.add("GET", "/api/usb_status", usb_status)

    # -- VoLTE / VoNR ------------------------------------------------------
    def _at_flag(app, command: str):
        """Read a comma-separated AT flag; ``None`` when the modem is silent."""
        try:
            raw = app.at.run(command)
        except Exception:  # noqa: BLE001 - no modem is a normal Linux state
            return None
        text = raw.upper()
        if "ERROR" in text:
            return None
        compact = text.replace(" ", "")
        if ",1" in compact:
            return True
        if ",0" in compact:
            return False
        return None

    def volte_get(request):
        slot = "1" if request.q_int("slot", 0) != 0 else "0"
        state = _at_flag(app, "AT+CAVIMS?")
        enabled = config.get_bool("volte_status_%s" % slot, True) if state is None else state
        return json_response({"enabled": enabled})

    def volte_set(request):
        body = request.json_body()
        enabled = "1" if str(body.get("enabled", "1")) != "0" else "0"
        slot = "1" if str(body.get("slot", "0")) != "0" else "0"
        try:
            app.at.run("AT+CAVIMS=%s" % enabled)
        except Exception as exc:  # noqa: BLE001
            raise ApiError("设置失败: %s" % exc)
        config.set("volte_status_%s" % slot, enabled)
        return json_response({"result": "success"})

    def vonr_get(request):
        slot = "1" if request.q_int("slot", 0) != 0 else "0"
        return json_response({"enabled": config.get_bool("vonr_status_%s" % slot, False)})

    def vonr_set(request):
        body = request.json_body()
        enabled = "1" if str(body.get("enabled", "1")) != "0" else "0"
        slot = "1" if str(body.get("slot", "0")) != "0" else "0"
        try:
            app.at.run('AT+SP5GCMDS="set nr param",45,%s' % enabled)
        except Exception as exc:  # noqa: BLE001
            raise ApiError("设置失败: %s" % exc)
        config.set("vonr_status_%s" % slot, enabled)
        return json_response({"result": "success"})

    router.add("GET", "/api/volte_status", volte_get)
    router.add("POST", "/api/volte_status", volte_set)
    router.add("GET", "/api/vonr_status", vonr_get)
    router.add("POST", "/api/vonr_status", vonr_set)


def _model(app) -> str:
    configured = str(app.config.get("model") or "").strip()
    if configured:
        return configured
    detected = app.device_info.model()
    return detected or "linux"
