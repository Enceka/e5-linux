"""Native control endpoints -- what UFI-TOOLS itself offers on this device.

These are the endpoints a LAN client uses to operate the E5: power, cellular
data, the Wi-Fi hotspot and its clients, LAN status, CPU performance and the
indicator LED.  They are the direct counterpart of the Android app's vendor-free
capabilities, and they are what the built-in frontend console drives.

Everything is authenticated by the normal UFI-TOOLS token; nothing here talks to
a vendor backend.
"""

from __future__ import annotations

from typing import Any, Dict

from .. import traffic
from ..control import ControlError
from ..httpd import ApiError, json_response


def _body(request) -> Dict[str, Any]:
    if request.body:
        return request.json_body()
    return {}


def register(router, app) -> None:
    control = app.control

    # -- one-shot overview for dashboards ----------------------------------
    def overview(request):
        info = app.device_info
        battery = info.battery()
        max_temp, thermal = info.thermal()
        mem, mem_percent = info.memory()
        return json_response({
            "nickname": str(app.config.get("nickname") or ""),
            "model": app.config.get("model") or info.model(),
            "uptime": app.uptime(),
            "memory": {"used_percent": mem_percent, "detail": mem},
            "thermal": {"max": max_temp, "zones": thermal},
            "battery": battery,
            "traffic": {
                "daily_bytes": traffic.today_bytes(app),
                "monthly_bytes": traffic.month_bytes(app),
                "rate": traffic.rate(app),
            },
            "mobile_data": control.mobile_data_status(),
            "hotspot": control.hotspot_status(),
            "lan": control.lan_status(),
            "clients": control.clients(),
            "performance": control.performance_status(),
            "led": control.led_status(),
            "modem": app.modem.as_dict(),
        })

    router.add("GET", "/api/linux/overview", overview)

    # -- power -------------------------------------------------------------
    def power(request):
        action = str(_body(request).get("action") or "").strip().lower()
        if action not in ("reboot", "poweroff"):
            raise ApiError("action 必须是 reboot 或 poweroff", 400)
        if action == "reboot":
            control.reboot()
        else:
            control.poweroff()
        return json_response({"result": "success", "action": action})

    router.add("POST", "/api/linux/power", power)

    # -- cellular data -----------------------------------------------------
    def mobile_data(request):
        if request.method == "POST":
            body = _body(request)
            if "enabled" not in body:
                raise ApiError("缺少 enabled")
            enabled = body["enabled"]
            if isinstance(enabled, str):
                enabled = enabled.strip().lower() in ("1", "true", "yes", "on")
            try:
                result = control.set_mobile_data(bool(enabled))
            except ControlError as exc:
                raise ApiError(str(exc))
            return json_response({"result": "success", "started": result.done,
                                  "status": control.mobile_data_status()})
        return json_response(control.mobile_data_status())

    router.add("GET", "/api/linux/mobile-data", mobile_data)
    router.add("POST", "/api/linux/mobile-data", mobile_data)

    # -- hotspot -----------------------------------------------------------
    def hotspot(request):
        if request.method == "POST":
            body = _body(request)
            if "enabled" in body:
                enabled = body["enabled"]
                if isinstance(enabled, str):
                    enabled = enabled.strip().lower() in ("1", "true", "yes", "on")
                try:
                    control.set_hotspot(bool(enabled))
                except ControlError as exc:
                    raise ApiError(str(exc))
                return json_response({"result": "success", "status": control.hotspot_status()})
            # No explicit switch: this is a configuration update.
            try:
                result = control.configure_hotspot(body)
            except ControlError as exc:
                raise ApiError(str(exc))
            return json_response({"result": "success", "applied": result,
                                  "status": control.hotspot_status()})
        return json_response(control.hotspot_status())

    router.add("GET", "/api/linux/hotspot", hotspot)
    router.add("POST", "/api/linux/hotspot", hotspot)

    def hotspot_clients(request):
        return json_response({"clients": control.clients(),
                              "count": len(control.clients())})

    router.add("GET", "/api/linux/hotspot/clients", hotspot_clients)

    def hotspot_access(request):
        body = _body(request)
        mode = str(body.get("mode") or "deny").lower()
        if mode not in ("allow", "deny"):
            raise ApiError("mode 必须是 allow 或 deny", 400)
        macs = body.get("macs") or []
        if isinstance(macs, str):
            macs = [m.strip() for m in macs.split(",") if m.strip()]
        try:
            result = control.set_client_access(mode, macs)
        except ControlError as exc:
            raise ApiError(str(exc))
        app.config.update({
            "hotspot_acl_mode": "0" if mode == "allow" else "1",
            "hotspot_blacklist": ",".join(macs) if mode == "deny" else "",
        })
        return json_response({"result": "success", "applied": result})

    router.add("POST", "/api/linux/hotspot/access", hotspot_access)

    # -- LAN (status only; addresses are owned by systemd-networkd) --------
    router.add("GET", "/api/linux/lan", lambda request: json_response(control.lan_status()))

    # -- CPU performance ---------------------------------------------------
    def performance(request):
        if request.method == "POST":
            body = _body(request)
            enabled = body.get("performance", body.get("enabled"))
            if enabled is None:
                raise ApiError("缺少 performance")
            if isinstance(enabled, str):
                enabled = enabled.strip().lower() in ("1", "true", "yes", "on")
            try:
                result = control.set_performance(bool(enabled))
            except ControlError as exc:
                raise ApiError(str(exc))
            return json_response({"result": "success", "applied": result,
                                  "status": control.performance_status()})
        return json_response(control.performance_status())

    router.add("GET", "/api/linux/performance", performance)
    router.add("POST", "/api/linux/performance", performance)

    # -- indicator LED -----------------------------------------------------
    def led(request):
        if request.method == "POST":
            body = _body(request)
            enabled = body.get("enabled", True)
            if isinstance(enabled, str):
                enabled = enabled.strip().lower() in ("1", "true", "yes", "on")
            try:
                result = control.set_led(bool(enabled))
            except ControlError as exc:
                raise ApiError(str(exc))
            return json_response({"result": "success", "applied": result,
                                  "status": control.led_status()})
        return json_response(control.led_status())

    router.add("GET", "/api/linux/led", led)
    router.add("POST", "/api/linux/led", led)

    # -- file sharing ------------------------------------------------------
    def samba(request):
        body = _body(request)
        enabled = body.get("enabled", True)
        if isinstance(enabled, str):
            enabled = enabled.strip().lower() in ("1", "true", "yes", "on")
        try:
            result = control.set_samba(bool(enabled))
        except ControlError as exc:
            raise ApiError(str(exc))
        return json_response({"result": "success", "applied": result})

    router.add("POST", "/api/linux/samba", samba)

    # -- traffic calibration ----------------------------------------------
    def calibrate(request):
        body = _body(request)
        if "bytes" not in body:
            raise ApiError("缺少 bytes")
        try:
            total = int(body["bytes"])
        except (TypeError, ValueError):
            raise ApiError("bytes 必须是整数")
        return json_response({"result": "success", "daily_bytes": traffic.calibrate(app, total)})

    router.add("POST", "/api/linux/traffic/calibrate", calibrate)
