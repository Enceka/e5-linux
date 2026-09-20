"""Compatibility surface for the web UI.

The frontend is written against a field vocabulary ("``ppp_status``",
"``monthly_rx_bytes``") that predates this port, so the two calls it makes are
answered locally:

* ``GET /api/ui/fields?cmd=<names>`` -- answered from :mod:`ufitools.uifields`
  (the real device) and :mod:`ufitools.modem` (AT-derived values);
* ``POST /api/ui/action`` with ``action=<name>`` -- routed to
  :mod:`ufitools.control`, which drives systemd, hostapd, dnsmasq and sysfs.

There is no vendor backend, no session, no ``AD`` signature and no second
credential: the single credential is the UFI-TOOLS token, checked by
:mod:`ufitools.auth` before the request ever reaches this module.  The commands
and actions that only existed to serve a vendor session or a vendor radio are
retired explicitly, so a stale caller gets "本机不支持" instead of a plausible
fake, and a UI action that cannot work on this hardware says so rather than
pretending to succeed.

Disable the whole surface with ``ui_compat = false`` in the configuration.
"""

from __future__ import annotations

from typing import Any, Dict, List

from .. import control as system_control
from .. import traffic
from ..httpd import ApiError, Response, json_response
from ..uifields import UiFields, qr_placeholder_svg

#: Field names that only existed to drive a vendor session (the login nonce pair
#: and the ``AD`` signature inputs).  Reading them is refused rather than faked.
RETIRED_COMMANDS = ("LD", "RD", "wa_inner_version", "psw_fail_num_str", "login_lock_time")

#: Actions the UI can ask for, mapped onto the native control layer.
_SUPPORTED_ACTIONS = (
    "REBOOT_DEVICE", "SHUTDOWN_DEVICE",
    "CONNECT_NETWORK", "DISCONNECT_NETWORK", "switchWiFiModule", "switchWiFiChip",
    "setAccessPointInfo", "setDeviceAccessControlList", "PERFORMANCE_MODE_SETTING",
    "PERFORMANCE_MODE", "INDICATOR_LIGHT_SETTING", "SAMBA_SETTING", "DATA_LIMIT_SETTING",
    "FLOW_CALIBRATION_MANUAL", "RESTART_SCHEDULE_SETTING", "SET_WIFI_SLEEP_INFO",
    "SET_CONNECTION_MODE", "EDIT_HOSTNAME",
    "SET_USB_NETWORK_PROTOCAL", "SET_BEARER_PREFERENCE",
)

#: Actions that have no meaning on a Linux handset; reported, never faked.
_UNSUPPORTED_ACTIONS = {
    "LOGIN": "本机不支持厂商后台登录：认证只使用 UFI-TOOLS 口令",
    "LOGIN_MULTI_USER": "本机不支持厂商后台登录：认证只使用 UFI-TOOLS 口令",
    "LOGOUT": "本机不支持厂商后台会话：认证只使用 UFI-TOOLS 口令",
    "LTE_BAND_LOCK": "Linux 端口不驱动基带锁频，请使用 AT 指令或厂商工具",
    "NR_BAND_LOCK": "Linux 端口不驱动基带锁频，请使用 AT 指令或厂商工具",
    "CELL_LOCK": "Linux 端口不驱动锁小区，请使用 AT 指令或厂商工具",
    "UNLOCK_ALL_CELL": "Linux 端口不驱动锁小区，请使用 AT 指令或厂商工具",
    "SEND_SMS": "本机没有短信栈，无法发送短信",
    "DELETE_SMS": "本机没有短信栈",
    "SET_MSG_READ": "本机没有短信栈",
    "SET_SIM_SLOT": "本机只有一张卡",
    "WIFI_NFC_SET": "本机没有 NFC",
    "CHANGE_PASSWORD": "Linux 端没有厂商后台密码；请使用 ufi-tools set-token 或系统账号",
    "USB_PORT_SETTING": "USB 调试开关由 Android 专有接口提供，Linux 端不适用",
    "APN_PROC_EX": "APN 由 modem 承载，请使用 AT+CGDCONT 配置",
    "DHCP_SETTING": "内网地址由 systemd-networkd 拥有、地址池由 dnsmasq 拥有，请改 /etc/systemd/network 与 /etc/dnsmasq.d",
}


def register(router, app) -> None:
    if not app.config.get_bool("ui_shim", True):
        return
    fields = UiFields(app)
    control = app.control

    # -- reads -------------------------------------------------------------
    def get_cmd(request):
        names: List[str] = []
        for value in request.query.get("cmd", []):
            names.extend(part.strip() for part in value.split(","))
        retired = [name for name in names if name in RETIRED_COMMANDS]
        if retired:
            raise ApiError(
                "本机不支持这些字段（厂商登录已移除）：%s；认证请使用 UFI-TOOLS 口令"
                % ", ".join(retired))
        payload: Dict[str, Any] = {}
        for name in names:
            if not name:
                continue
            if name == "queryWiFiModuleSwitch":
                payload[name] = "1" if control.hotspot_status().get("active") else "0"
            elif name == "queryAccessPointInfo":
                payload[name] = fields.access_point_list()
            elif name == "queryDeviceAccessControlList":
                payload[name] = {
                    "AclMode": str(app.config.get("hotspot_acl_mode") or "0"),
                    "BlackMacList": [m for m in str(app.config.get("hotspot_blacklist") or "").split(",") if m],
                    "BlackNameList": [],
                    "WhiteMacList": [],
                    "WhiteNameList": [],
                    "devices": fields.clients(),
                }
            else:
                payload[name] = fields.get_many([name])[name]
        return json_response(payload)

    router.add("GET", "/api/ui/fields", get_cmd)

    # -- writes ------------------------------------------------------------
    def set_cmd(request):
        form = _parse_form(request)
        action = str(form.get("action") or "").strip()
        if not action:
            raise ApiError("缺少 action")
        try:
            result = _dispatch(app, control, action, form)
        except system_control.ControlError as exc:
            raise ApiError(str(exc))
        if result is None:
            message = _UNSUPPORTED_ACTIONS.get(action)
            if message:
                raise ApiError(message)
            raise ApiError("本机不支持该操作: %s" % action)
        return json_response(result)

    router.add("POST", "/api/ui/action", set_cmd)

    # The vendor rendered a QR image server-side; serve a transparent stand-in
    # so the WiFi panel does not show a broken image.
    router.add("GET", "/api/linux/placeholder.svg", lambda request: Response(
        200, qr_placeholder_svg().encode("utf-8"), "image/svg+xml"))

    # Diagnostics: what the compatibility layer answers.
    router.add("GET", "/api/linux/ui_compat", lambda request: json_response({
        "enabled": True,
        "supported_actions": list(_SUPPORTED_ACTIONS),
        "unsupported_actions": _UNSUPPORTED_ACTIONS,
    }))


def _parse_form(request) -> Dict[str, str]:
    """Accept both a urlencoded form body and a query string."""
    import urllib.parse

    merged: Dict[str, str] = {key: values[0] for key, values in request.query.items() if values}
    body = request.body.decode("utf-8", "replace") if request.body else ""
    if body:
        for key, values in urllib.parse.parse_qs(body, keep_blank_values=True).items():
            merged[key] = values[0]
    return merged


def _truthy(value: Any) -> bool:
    return str(value).strip() not in ("0", "", "false", "off", "False", "None")


def _dispatch(app, control, action: str, form: Dict[str, str]):
    """Route one UI action onto the native control layer."""
    config = app.config

    if action == "REBOOT_DEVICE":
        control.reboot()
        return {"result": "success"}
    if action == "SHUTDOWN_DEVICE":
        control.poweroff()
        return {"result": "success"}

    if action == "CONNECT_NETWORK":
        control.set_mobile_data(True)
        return {"result": "success"}
    if action == "DISCONNECT_NETWORK":
        control.set_mobile_data(False)
        return {"result": "success"}

    if action == "switchWiFiModule":
        control.set_hotspot(_truthy(form.get("SwitchOption")))
        return {"result": "success"}
    if action == "switchWiFiChip":
        band = "2g" if str(form.get("ChipEnum") or "").endswith("1") else "5g"
        conf = config.get("hotspot_conf_2g" if band == "2g" else "hotspot_conf_5g")
        if conf:
            config.update({"hotspot_conf": str(conf), "hotspot_band": band})
        channel = "6" if band == "2g" else "149"
        control.configure_hotspot({"channel": channel,
                                   "hw_mode": "g" if band == "2g" else "a"})
        return {"result": "success"}
    if action == "setAccessPointInfo":
        control.configure_hotspot(form)
        return {"result": "success"}
    if action == "setDeviceAccessControlList":
        black = [m for m in str(form.get("BlackMacList") or "").split(",") if m]
        white = [m for m in str(form.get("WhiteMacList") or "").split(",") if m]
        mode = "deny" if black else "allow"
        macs = black or white
        config.update({"hotspot_acl_mode": str(form.get("AclMode") or "0"),
                       "hotspot_blacklist": ",".join(black)})
        control.set_client_access(mode, macs)
        return {"result": "success"}

    if action in ("PERFORMANCE_MODE_SETTING", "PERFORMANCE_MODE"):
        enabled = _truthy(form.get("performance_mode"))
        control.set_performance(enabled)
        config.set("performance_mode", "1" if enabled else "0")
        return {"result": "success"}
    if action == "INDICATOR_LIGHT_SETTING":
        enabled = _truthy(form.get("indicator_light_switch"))
        control.set_led(enabled)
        config.set("indicator_light_switch", "1" if enabled else "0")
        return {"result": "success"}
    if action == "SAMBA_SETTING":
        control.set_samba(_truthy(form.get("samba_switch")))
        return {"result": "success"}

    if action == "DATA_LIMIT_SETTING":
        updates = {}
        if "data_volume_limit_switch" in form:
            updates["kano_data_flow_limit_enabled"] = "1" if _truthy(form["data_volume_limit_switch"]) else "0"
        if "data_volume_alert_percent" in form:
            updates["kano_data_flow_alert_percent"] = str(form["data_volume_alert_percent"])
        if "data_volume_limit_size" in form:
            updates["kano_data_flow_max_limit"] = int(float(form["data_volume_limit_size"] or 0))
        if "traffic_clear_date" in form:
            updates["kano_traffic_clear_date"] = str(form["traffic_clear_date"])
        if updates:
            config.update(updates)
        return {"result": "success"}
    if action == "FLOW_CALIBRATION_MANUAL":
        total = int(float(str(form.get("data") or "0").replace(",", "")) or 0)
        traffic.calibrate(app, total)
        return {"result": "success"}

    if action == "RESTART_SCHEDULE_SETTING":
        config.update({
            "restart_schedule_switch": "1" if _truthy(form.get("restart_schedule_switch")) else "0",
            "restart_time": str(form.get("restart_time") or "00:00"),
        })
        return {"result": "success"}
    if action == "SET_WIFI_SLEEP_INFO":
        config.set("sleep_sysIdleTimeToSleep", str(form.get("sleep_sysIdleTimeToSleep") or "0"))
        return {"result": "success"}
    if action == "SET_CONNECTION_MODE":
        config.set("dial_roam_setting_option", str(form.get("dial_roam_setting_option") or "off"))
        return {"result": "success"}
    if action == "SET_USB_NETWORK_PROTOCAL":
        config.set("usb_network_protocal", str(form.get("usb_network_protocal") or "auto"))
        return {"result": "success"}
    if action == "SET_BEARER_PREFERENCE":
        config.set("net_select", str(form.get("BearerPreference") or ""))
        return {"result": "success"}
    if action == "EDIT_HOSTNAME":
        mac = str(form.get("mac") or "").strip().lower()
        name = str(form.get("hostname") or "").strip()
        names = dict(config.get("client_names") or {})
        if mac:
            names[mac] = name
            config.set("client_names", names)
        return {"result": "success"}

    return None
