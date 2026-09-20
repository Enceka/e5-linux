"""Speed test, SMS/status forwarding and diagnostics.

The Android app's APK updater, wireless-adb toggles and "official backend
password" endpoints are gone with the rest of the vendor layer: a Debian rootfs
has no APK installer, no adbd to toggle and no vendor web password.  What is left
is the part that is genuinely platform-neutral and useful on a Linux handset.
"""

from __future__ import annotations

import os
import threading
from typing import Any, Dict, Optional

from .. import forward
from .. import __version__
from ..httpd import ApiError, Response, json_response
from ..traffic import today_bytes

BLOCK_SIZE = 8 * 1024 * 1024  # 8 MiB, same as the Android module
MAX_BLOCKS = 1024
SPEEDTEST_CONCURRENCY = 3

_speedtest_lock = threading.Lock()
_speedtest_active = 0
_speedtest_block: Optional[bytes] = None


def _random_block() -> bytes:
    global _speedtest_block
    if _speedtest_block is None:
        _speedtest_block = os.urandom(BLOCK_SIZE)
    return _speedtest_block


def register(router, app) -> None:
    config = app.config

    # -- /api/speedtest ----------------------------------------------------
    def speedtest(request):
        global _speedtest_active
        blocks = request.q_int("ckSize", 4)
        if blocks <= 0:
            blocks = 4
        blocks = min(blocks, MAX_BLOCKS)
        with _speedtest_lock:
            if _speedtest_active >= SPEEDTEST_CONCURRENCY:
                return Response(429, "测速请求过多，请稍后再试".encode("utf-8"),
                                "text/plain; charset=utf-8")
            _speedtest_active += 1
        try:
            payload = _random_block() * blocks
        finally:
            with _speedtest_lock:
                _speedtest_active -= 1
        headers = {
            "Content-Disposition": "attachment; filename=random.dat",
            "Cache-Control": "no-store",
        }
        if request.q("cors") is not None:
            headers["Access-Control-Allow-Origin"] = "*"
        return Response(200, payload, "application/octet-stream", headers)

    router.add("GET", "/api/speedtest", speedtest)

    # -- SMS / status forwarding ------------------------------------------
    router.add("GET", "/api/sms_forward_method", lambda request: json_response({
        "sms_forward_method": str(config.get("sms_forward_method") or ""),
    }))

    def mail_post(request):
        body = request.json_body()
        required = ("smtp_host", "smtp_to", "smtp_username", "smtp_password")
        missing = [key for key in required if not str(body.get(key) or "").strip()]
        if missing:
            raise ApiError("缺少字段: %s" % ", ".join(missing))
        settings = {
            "smtp_host": str(body.get("smtp_host")),
            "smtp_port": str(body.get("smtp_port") or "465"),
            "smtp_to": str(body.get("smtp_to")),
            "smtp_username": str(body.get("smtp_username")),
            "smtp_password": str(body.get("smtp_password")),
        }
        config.update({
            "kano_smtp_host": settings["smtp_host"],
            "kano_smtp_port": settings["smtp_port"],
            "kano_smtp_to": settings["smtp_to"],
            "kano_smtp_username": settings["smtp_username"],
            "kano_smtp_password": settings["smtp_password"],
            "kano_smtp_forward_dev_info": "1" if str(body.get("forward_dev_info") or "0") == "1" else "0",
            "sms_forward_method": "SMTP",
        })
        try:
            forward.send_mail(settings, "UFI-TOOLS", forward.TEST_BODY)
        except forward.ForwardError as exc:
            raise ApiError("测试邮件发送失败: %s" % exc)
        return json_response({"result": "success"})

    def mail_get(request):
        return json_response({
            "smtp_host": config.get("kano_smtp_host", ""),
            "smtp_port": config.get("kano_smtp_port", "465"),
            "smtp_to": config.get("kano_smtp_to", ""),
            "smtp_username": config.get("kano_smtp_username", ""),
            "smtp_password": config.get("kano_smtp_password", ""),
            "forward_dev_info": config.get("kano_smtp_forward_dev_info", "0"),
        })

    router.add("POST", "/api/sms_forward_mail", mail_post)
    router.add("GET", "/api/sms_forward_mail", mail_get)

    def curl_post(request):
        text = str(request.json_body().get("curl_text") or "").strip()
        if not text:
            raise ApiError("curl_text 不能为空")
        for token in ("{{sms-body}}", "{{sms-time}}", "{{sms-from}}"):
            if token not in text:
                raise ApiError("curl 命令必须包含 %s" % token)
        config.update({"kano_curl_text": text, "sms_forward_method": "CURL"})
        try:
            forward.send_curl(text, "UFI-TOOLS TEST消息")
        except forward.ForwardError as exc:
            raise ApiError("测试转发失败: %s" % exc)
        return json_response({"result": "success"})

    router.add("POST", "/api/sms_forward_curl", curl_post)
    router.add("GET", "/api/sms_forward_curl",
               lambda request: json_response({"curl_text": config.get("kano_curl_text", "")}))

    def dingtalk_post(request):
        body = request.json_body()
        url = str(body.get("webhook_url") or "").strip()
        if not url:
            raise ApiError("webhook_url 不能为空")
        secret = str(body.get("secret") or "")
        config.update({
            "kano_dingtalk_url": url,
            "kano_dingtalk_secret": secret,
            "kano_dingtalk_forward_dev_info": "1" if str(body.get("forward_dev_info") or "0") == "1" else "0",
            "sms_forward_method": "DINGTALK",
        })
        try:
            forward.send_dingtalk(url, secret, forward.TEST_BODY)
        except forward.ForwardError as exc:
            raise ApiError("测试转发失败: %s" % exc)
        return json_response({"result": "success"})

    router.add("POST", "/api/sms_forward_dingtalk", dingtalk_post)
    router.add("GET", "/api/sms_forward_dingtalk", lambda request: json_response({
        "webhook_url": config.get("kano_dingtalk_url", ""),
        "secret": config.get("kano_dingtalk_secret", ""),
        "forward_dev_info": config.get("kano_dingtalk_forward_dev_info", "0"),
    }))

    def _switch(key: str):
        def handler(request):
            value = request.q("enable")
            if value is None:
                raise ApiError("缺少 query 参数 enable")
            config.set(key, "1" if str(value) == "1" else "0")
            return json_response({"result": "success"})

        return handler

    def _switch_get(key: str):
        return lambda request: json_response({"enabled": str(config.get(key, "0"))})

    router.add("POST", "/api/sms_forward_enabled", _switch("sms_forward_enabled"))
    router.add("GET", "/api/sms_forward_enabled", _switch_get("sms_forward_enabled"))
    router.add("POST", "/api/power_status_forward_enabled", _switch("kano_power_status_forward_enabled"))
    router.add("GET", "/api/power_status_forward_enabled", _switch_get("kano_power_status_forward_enabled"))

    def blacklist_post(request):
        body = request.json_body()
        if "phone" not in body or "keywords" not in body:
            raise ApiError("phone 与 keywords 两个键都必须存在")
        phone = str(body.get("phone") or "")
        if not __import__("re").match(r"^[0-9\n]*$", phone):
            raise ApiError("号码只能包含数字与换行符")
        config.update({
            "kano_sms_blacklist_phone": phone,
            "kano_sms_blacklist_keywords": str(body.get("keywords") or ""),
        })
        return json_response({"result": "success"})

    router.add("POST", "/api/sms_forward_blacklist", blacklist_post)
    router.add("GET", "/api/sms_forward_blacklist", lambda request: json_response({
        "phone": config.get("kano_sms_blacklist_phone", ""),
        "keywords": config.get("kano_sms_blacklist_keywords", ""),
    }))

    def do_forward_msg(request):
        body = request.json_body()
        values = forward.sms_values(
            str(body.get("body") or ""),
            str(body.get("address") or ""),
            body.get("timestamp"),
            bool(body.get("is_sms", True)),
        )
        include_info = str(config.get("kano_smtp_forward_dev_info", "0")) == "1" or \
            str(config.get("kano_dingtalk_forward_dev_info", "0")) == "1"
        if include_info:
            values.update(forward.build_device_info(
                config, app.device_info, {"daily-flow": today_bytes(app)}))
        method = str(config.get("sms_forward_method") or "")
        if method == "SMTP":
            content = values["sms-body"]
            if include_info:
                extra = "\n".join(
                    "%s: %s" % (key, values[key]) for key in sorted(values)
                    if key.startswith(("cpu-", "mem-", "battery-", "model", "daily-",
                                       "monthly-", "boot-")))
                content = "%s\n\n---\n%s" % (content, extra)
            try:
                forward.send_mail(config.data, "UFI-TOOLS", content)
            except forward.ForwardError as exc:
                raise ApiError(str(exc))
            return json_response({"result": "success"})
        template = config.get("kano_curl_text", "") if method == "CURL" else forward.TEST_BODY
        try:
            forward.dispatch(method, config.data, forward.expand_template(template, values))
        except forward.ForwardError as exc:
            raise ApiError(str(exc))
        return json_response({"result": "success"})

    router.add("POST", "/api/do_forward_msg", do_forward_msg)

    # -- diagnostics -------------------------------------------------------
    def platform(request):
        info = app.device_info
        return json_response({
            "app_ver": __version__,
            "python": __import__("sys").version.split()[0],
            "hostname": __import__("socket").gethostname(),
            "kernel": os.uname().release,
            "model": info.model(),
            "uptime": app.uptime(),
            "at_backend": app.at.describe(),
            "at_available": app.at.available(),
            "modem_snapshot_age": round(app.modem.age, 1),
            "data_dir": config.data_dir,
            "static_root": app.static_root,
            "shim_root": app.shim_root,
            "advanced_enabled": app.advanced,
            "tasks": len(app.tasks.tasks()),
            "plugins_bytes": len(app.plugins.text.encode("utf-8")),
            # The shim hides the file-sharing panel when there is no unit to drive.
            "samba_unit": app.control.samba_unit(),
            "ui_shim": config.get_bool("ui_shim", True),
            "wlan_interface": config.get("wlan_interface"),
        })

    router.add("GET", "/api/platform", platform)

    router.add("GET", "/api/task_history", lambda request: json_response(
        app.runtime.data.get("task_history") or []))

    router.add("GET", "/api/config/dump", lambda request: json_response(config.as_public_dict()))
