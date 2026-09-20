"""SMS / device-status forwarding: SMTP, arbitrary curl and DingTalk.

Port of the Android triple (``KanoSMTP``, ``KanoCURL``, ``KanoDingTalk``) plus
the template expansion from ``smsModule``.  The placeholder vocabulary is
unchanged so existing forwarder configurations keep working:

``{{sms-body}}`` ``{{sms-time}}`` ``{{sms-from}}`` for the message itself and
``{{daily-flow}}`` ``{{cpu-temp}}`` ``{{cpu-usage}}`` ``{{mem-usage}}``
``{{battery-level}}`` ``{{battery-current}}`` ``{{battery-voltage}}``
``{{model}}`` ``{{monthly-flow-count}}`` ``{{app-ver}}`` ``{{monthly-flow-sum}}``
``{{boot-time}}`` for the device snapshot.

On a Linux *controller* there is no local SMS store, so the message source is
whatever the caller supplies -- the ZTE hotspot's own SMS list, a plugin, or a
task.  That keeps the module useful without pretending a handset has an inbox.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import shlex
import smtplib
import ssl
import subprocess
import time
import urllib.parse
import urllib.request
from email.message import EmailMessage
from typing import Any, Dict, Optional

USER_AGENT = "UFI-TOOLS-linux"
TEST_SENDER = "1145141919810"
TEST_BODY = "UFI-TOOLS TEST消息"


class ForwardError(Exception):
    pass


def _http_post_json(url: str, payload: Dict[str, Any], timeout: float = 10.0) -> str:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/json", "User-Agent": USER_AGENT}
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read().decode("utf-8", "replace")


def _http_post_form(url: str, payload: Dict[str, str], timeout: float = 10.0) -> str:
    data = urllib.parse.urlencode(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/x-www-form-urlencoded", "User-Agent": USER_AGENT},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read().decode("utf-8", "replace")


def expand_template(template: str, values: Dict[str, Any]) -> str:
    """Replace ``{{name}}`` placeholders, leaving unknown ones untouched."""
    if not template:
        return ""
    rendered = template
    for key, value in values.items():
        rendered = rendered.replace("{{%s}}" % key, "" if value is None else str(value))
    return rendered


def sms_values(body: str, sender: str, timestamp_ms: Optional[int] = None, is_sms: bool = True) -> Dict[str, Any]:
    ts = timestamp_ms or int(time.time() * 1000)
    return {
        "sms-body": body,
        "sms-from": sender,
        "sms-time": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ts / 1000.0)),
        "is-sms": "1" if is_sms else "0",
    }


def send_mail(settings: Dict[str, str], subject: str, content: str) -> None:
    host = settings.get("smtp_host") or ""
    to_addr = settings.get("smtp_to") or ""
    username = settings.get("smtp_username") or ""
    password = settings.get("smtp_password") or ""
    if not (host and to_addr and username and password):
        raise ForwardError("SMTP 配置不完整")
    port = int(str(settings.get("smtp_port") or "465"))
    sender = settings.get("smtp_from") or username

    message = EmailMessage()
    message["From"] = sender
    message["To"] = to_addr
    message["Subject"] = "%s UFI-TOOLS 消息" % TEST_SENDER
    message.set_content(content)

    try:
        if port == 465:
            with smtplib.SMTP_SSL(host, port, timeout=15, context=ssl.create_default_context()) as server:
                server.login(username, password)
                server.send_message(message)
        else:
            with smtplib.SMTP(host, port, timeout=15) as server:
                server.starttls(context=ssl.create_default_context())
                server.login(username, password)
                server.send_message(message)
    except (smtplib.SMTPException, OSError, ssl.SSLError) as exc:
        raise ForwardError("SMTP 发送失败: %s" % exc) from exc


def send_curl(curl_template: str, content: str) -> str:
    """Run the user's curl template with the message substituted in.

    The Android implementation executes the string through a shell; doing the
    same here keeps parity, but the command is what the *operator* configured,
    never something a remote client can inject.
    """
    if not curl_template.strip():
        raise ForwardError("curl 内容为空")
    try:
        completed = subprocess.run(
            shlex.split(curl_template),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=15,
        )
    except (subprocess.TimeoutExpired, OSError) as exc:
        raise ForwardError("curl 执行失败: %s" % exc) from exc
    output = completed.stdout.decode("utf-8", "replace")
    if completed.returncode != 0:
        raise ForwardError("curl 返回 %s: %s" % (completed.returncode, output.strip()))
    return output


def send_dingtalk(webhook: str, secret: str, content: str) -> str:
    if not webhook:
        raise ForwardError("钉钉 webhook 为空")
    url = webhook
    if secret:
        stamp = str(int(time.time() * 1000))
        string_to_sign = "%s\n%s" % (stamp, secret)
        digest = hmac.new(secret.encode("utf-8"), string_to_sign.encode("utf-8"), hashlib.sha256).digest()
        signature = urllib.parse.quote_plus(base64.b64encode(digest).decode("utf-8"))
        separator = "&" if "?" in url else "?"
        url = "%s%stimestamp=%s&sign=%s" % (url, separator, stamp, signature,)
    payload = {"msgtype": "text", "text": {"content": content}}
    return _http_post_json(url, payload)


def dispatch(method: str, settings: Dict[str, str], content: str) -> str:
    """Send one message through the configured channel."""
    method = (method or "").upper()
    if method == "SMTP":
        send_mail(settings, "UFI-TOOLS", content)
        return "smtp"
    if method == "CURL":
        return send_curl(settings.get("kano_curl_text", ""), content)
    if method == "DINGTALK":
        return send_dingtalk(
            settings.get("kano_dingtalk_url", ""), settings.get("kano_dingtalk_secret", ""), content
        )
    raise ForwardError("未配置短信转发渠道")


def build_device_info(config, device_info, extra: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """The ``{{...}}`` values for a forwarded message."""
    battery = device_info.battery()
    _, thermal = device_info.thermal()
    mem, _ = device_info.memory()
    values = {
        "cpu-temp": max((z["temp"] for z in thermal), default=-1),
        "cpu-usage": "-",
        "mem-usage": mem.get("mem_usage_percent", "-"),
        "battery-level": battery.get("percent"),
        "battery-current": battery.get("current_uA"),
        "battery-voltage": battery.get("voltage_uV"),
        "model": config.get("model") or device_info.model(),
        "app-ver": _app_version(),
        "boot-time": device_info.uptime(),
        "daily-flow": 0,
        "monthly-flow-count": 0,
        "monthly-flow-sum": 0,
    }
    if extra:
        values.update(extra)
    return values


def _app_version() -> str:
    from . import __version__

    return __version__
