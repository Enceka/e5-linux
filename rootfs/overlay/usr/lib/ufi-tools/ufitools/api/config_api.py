"""Configuration endpoints: the ``configModule`` port.

Token handling keeps the Android semantics: ``login_token`` stores the SHA-256
of the passphrase and ``authorization`` must equal it, so the web UI's login
form and the shipped ``ufi_req`` CLI need no changes.
"""

from __future__ import annotations

from ..auth import check_token_rules, is_weak_token
from ..httpd import ApiError, json_response


def register(router, app) -> None:
    config = app.config

    router.add("GET", "/api/is_weak_token", lambda request: json_response({
        "is_weak_token": is_weak_token(config.token_hash),
    }))

    def set_token(request):
        token = str(request.json_body().get("token") or "").strip()
        problem = check_token_rules(token)
        if problem:
            raise ApiError(problem)
        config.set_token(token)
        app.log("口令已更新")
        return json_response({"result": "success"})

    router.add("POST", "/api/set_token", set_token)

    router.add("GET", "/api/get_res_server", lambda request: json_response({
        "res_server": str(config.get("GLOBAL_SERVER_URL") or ""),
    }))

    def set_res_server(request):
        url = str(request.json_body().get("res_server") or "").strip()
        if not url:
            raise ApiError("请提供 res_server")
        config.set("GLOBAL_SERVER_URL", url)
        return json_response({"result": "success"})

    router.add("POST", "/api/set_res_server", set_res_server)

    router.add("GET", "/api/get_log_status", lambda request: json_response({
        "debug_log_enabled": config.get_bool("kano_is_debug", False),
    }))

    def set_log_status(request):
        body = request.json_body()
        enabled = body.get("debug_log_enabled", False)
        if isinstance(enabled, str):
            enabled = enabled.strip().lower() in ("1", "true", "yes", "on")
        config.set("kano_is_debug", bool(enabled))
        return json_response({"result": "success"})

    router.add("POST", "/api/set_log_status", set_log_status)

    def set_wakelock_status(request):
        # Android holds a PowerManager.WakeLock so the CPU does not sleep; the
        # Linux analogue is the systemd inhibitor that ships in the unit file,
        # so this is recorded rather than acted on.
        body = request.json_body()
        enabled = body.get("wakelock_enabled", False)
        if isinstance(enabled, str):
            enabled = enabled.strip().lower() in ("1", "true", "yes", "on")
        config.set("wakeLock", bool(enabled))
        return json_response({"result": "success"})

    router.add("POST", "/api/set_wakelock_status", set_wakelock_status)

    def set_data_limit(request):
        body = request.json_body()
        enabled = body.get("data_flow_limit_enabled", "0")
        forward = body.get("data_limit_status_forward_enabled", "0")
        try:
            limit = int(body.get("data_flow_max_limit") or -1)
        except (TypeError, ValueError):
            limit = -1
        period = str(body.get("data_flow_check_daily_or_monthly") or "monthly")
        reference = str(body.get("data_check_reference") or "android")
        config.update({
            "kano_data_flow_limit_enabled": "1" if str(enabled) in ("1", "true", "True") else "0",
            "kano_data_limit_status_forward_enabled":
                "1" if str(forward) in ("1", "true", "True") else "0",
            "kano_data_flow_max_limit": limit if limit > 0 else -1,
            "kano_data_flow_check_daily_or_monthly": period if period in ("daily", "monthly") else "monthly",
            "kano_data_check_reference": "android" if reference in ("android", "ufi") else "default",
        })
        return json_response({"result": "success"})

    router.add("POST", "/api/set_data_limit", set_data_limit)

    router.add("GET", "/api/get_data_limit", lambda request: json_response({
        "data_flow_limit_enabled": str(config.get("kano_data_flow_limit_enabled", "0")),
        "data_flow_max_limit": config.get_int("kano_data_flow_max_limit", -1),
        "data_flow_check_daily_or_monthly": str(config.get("kano_data_flow_check_daily_or_monthly", "monthly")),
        "data_check_reference": str(config.get("kano_data_check_reference", "android")),
        "data_limit_status_forward_enabled": str(config.get("kano_data_limit_status_forward_enabled", "0")),
    }))

    # Not part of the Android surface, but the only way to switch deployment
    # modes without editing a file over ssh.  Kept under /api/config/ so it can
    # never collide with an upstream route.
    def get_mode(request):
        return json_response({
            "device_mode": config.device_mode,
            "gateway_ip": str(config.get("gateway_ip") or ""),
            "static_root": app.static_root,
            "data_dir": config.data_dir,
            "at_backend": app.at.describe(),
            "advanced_enabled": app.advanced,
        })

    def set_mode(request):
        body = request.json_body()
        mode = str(body.get("device_mode") or "").strip().lower()
        if mode and mode not in ("remote", "self"):
            raise ApiError("device_mode 只能是 remote 或 self")
        updates = {}
        if mode:
            updates["device_mode"] = mode
        if "gateway_ip" in body:
            updates["gateway_ip"] = str(body["gateway_ip"]).strip()
        if updates:
            config.update(updates)
        return json_response({"result": "success", **updates})

    router.add("GET", "/api/config/deployment", get_mode)
    router.add("POST", "/api/config/deployment", set_mode)
