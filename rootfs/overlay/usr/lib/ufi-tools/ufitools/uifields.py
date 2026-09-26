"""Maps the web UI's field vocabulary onto this device's real state.

The frontend asks for names like ``ppp_status`` or ``monthly_rx_bytes``, which
it inherited from the hotspot firmware it was originally written for.  Those
names are a *UI contract*, not a protocol, and the values behind them exist on a
Linux device too -- they just come from ``/proc``, ``/sys``, systemd, hostapd
and the modem.  This module is that translation, and it is read-only.

Nothing here emulates a vendor backend: there is no session, no request signing
and no vendor service.  Control actions live in :mod:`ufitools.control` and reach
the device through systemd and sysfs.
"""

from __future__ import annotations

import base64
import os
import time
from typing import Any, Dict, List, Optional

from . import APP_VER
from .traffic import month_bytes, rate, today_bytes

#: Fields whose value comes from a subprocess; cached briefly so the UI's 1 Hz
#: poll does not fork ``iw`` every second.
SUBprocess_TTL = 2.0


class UiFields:
    """Builds the field snapshot the web UI polls for."""

    def __init__(self, app):
        self.app = app
        self.control = app.control
        self._cache: Dict[str, Any] = {}

    # -- caches ------------------------------------------------------------
    def _cached(self, key: str, producer):
        now = time.time()
        entry = self._cache.get(key)
        if entry and now - entry[0] < SUBprocess_TTL:
            return entry[1]
        value = producer()
        self._cache[key] = (now, value)
        return value

    def clients(self) -> List[Dict[str, str]]:
        return self._cached("clients", self.control.clients)

    def hotspot(self) -> Dict[str, Any]:
        return self._cached("hotspot", self.control.hotspot_status)

    # -- snapshot ----------------------------------------------------------
    def snapshot(self) -> Dict[str, Any]:
        app = self.app
        config = app.config
        info = app.device_info
        modem = app.modem

        battery = info.battery()
        percent = battery.get("percent", -1)
        status = (battery.get("status") or "").lower()
        hotspot = self.hotspot()
        clients = self.clients()
        lan = self.control.lan_status()
        link_rate = rate(app)
        mobile = self.control.mobile_data_status()
        mac = lan.get("mac_address") or ""
        uname = os.uname()

        fields: Dict[str, Any] = {
            # -- session ---------------------------------------------------
            # The UI treats this as "the request is authenticated", which it is:
            # the token check happened before the handler ran.
            "loginfo": "ok",
            "Language": "zh",
            "cr_version": "%s / %s" % (config.get("nickname") or "E5-LINUX", uname.release),
            # -- power / battery -------------------------------------------
            "battery_value": percent,
            "battery_vol_percent": percent,
            "battery_charging": "1" if status in ("charging", "full") else "0",
            "battery_status": battery.get("status") or "",
            # -- SIM / identity --------------------------------------------
            "imei": modem.get("imei"),
            "imsi": modem.get("imsi"),
            "iccid": modem.get("iccid"),
            "msisdn": modem.get("msisdn"),
            "sim_msisdn": modem.get("msisdn"),
            "sim_slot": "0",
            "dual_sim_support": "0",
            "network_provider": modem.get("network_provider"),
            "network_type": modem.get("network_type"),
            "network_information": "E5-LINUX",
            # -- signal -----------------------------------------------------
            "network_signalbar": modem.get("network_signalbar", "0"),
            "network_rssi": modem.get("network_rssi", ""),
            "rssi": modem.get("rssi", ""),
            "lte_rsrp": modem.get("lte_rsrp", ""),
            "lte_rsrq": modem.get("lte_rsrq", ""),
            "Z5g_rsrp": modem.get("Z5g_rsrp", ""),
            "Lte_ca_status": "",
            # -- connectivity ----------------------------------------------
            "ppp_status": mobile.get("ppp_status", "ppp_disconnected"),
            "ipv4_wan_ipaddr": modem.get("ipv4_wan_ipaddr", ""),
            "ipv6_wan_ipaddr": self._ipv6(mobile.get("interface") or ""),
            "lan_ipaddr": hotspot.get("ipv4") or lan.get("lan_ipaddr", ""),
            "lan_netmask": lan.get("lan_netmask", ""),
            "mac_address": mac,
            "dhcpEnabled": "1" if lan.get("dhcpEnabled") else "0",
            "dhcpStart": lan.get("dhcpStart", ""),
            "dhcpEnd": lan.get("dhcpEnd", ""),
            "dhcpLease_hour": "12",
            "mtu": "1500",
            "tcp_mss": "1460",
            # -- traffic ----------------------------------------------------
            "realtime_rx_thrpt": str(link_rate["rx_bps"]),
            "realtime_tx_thrpt": str(link_rate["tx_bps"]),
            "realtime_time": str(app.uptime()),
            "monthly_rx_bytes": str(_rx(app)),
            "monthly_tx_bytes": str(_tx(app)),
            "monthly_bytes": str(month_bytes(app)),
            "daily_bytes": str(today_bytes(app)),
            "monthly_time": str(app.uptime()),
            # -- data limit -------------------------------------------------
            "data_volume_limit_switch": str(config.get("kano_data_flow_limit_enabled", "0")),
            "data_volume_alert_percent": str(config.get("kano_data_flow_alert_percent", "80")),
            "data_volume_limit_size": str(config.get("kano_data_flow_max_limit", -1)),
            "traffic_clear_date": str(config.get("kano_traffic_clear_date", "1")),
            # -- wifi -------------------------------------------------------
            "WiFiModuleSwitch": "1" if hotspot.get("active") else "0",
            "wifi_access_sta_num": str(len(clients)),
            "station_list": clients,
            "lan_station_list": [],
            "hostNameList": [
                {"hostname": item.get("hostname", ""), "mac_addr": item.get("mac_addr", ""),
                 "ip_addr": item.get("ip_addr", "")}
                for item in clients
            ],
            "BlackMacList": [m for m in str(config.get("hotspot_blacklist") or "").split(",") if m],
            "BlackNameList": [],
            "AclMode": str(config.get("hotspot_acl_mode") or "0"),
            "devices": [],
            # -- switches ---------------------------------------------------
            "usb_port_switch": "1" if self._usb_is_gadget() else "0",
            "performance_mode": "1" if self.control.performance_status().get("performance") else "0",
            "indicator_light_switch": str(config.get("indicator_light_switch", "1")),
            "samba_switch": "1" if self._unit_active(config.get("samba_unit")) else "0",
            "roam_setting_option": str(config.get("roam_setting_option", "off")),
            "dial_roam_setting_option": str(config.get("dial_roam_setting_option", "off")),
            "restart_schedule_switch": str(config.get("restart_schedule_switch", "0")),
            "restart_time": str(config.get("restart_time", "00:00")),
            "sleep_sysIdleTimeToSleep": str(config.get("sleep_sysIdleTimeToSleep", "0")),
            "net_select": str(config.get("net_select", "5G/4G/3G")),
            "usb_network_protocal": str(config.get("usb_network_protocal", "auto")),
            "is_support_nfc_functions": "0",
            "web_wifi_nfc_switch": "0",
            # -- locks (intent only: the modem is not driven here) ----------
            "lte_band_lock": str(config.get("lte_band_lock", "")),
            "nr_band_lock": str(config.get("nr_band_lock", "")),
            "neighbor_cell_info": [],
            "locked_cell_info": [],
            # -- sms (this device has no SMS stack) -------------------------
            "sms_received_flag": "0",
            "sms_unread_num": "0",
            "sms_sim_unread_num": "0",
            "sms_data_total": [],
            # -- version ----------------------------------------------------
            "app_ver": APP_VER,
        }
        return fields

    def get_many(self, names: List[str]) -> Dict[str, Any]:
        snapshot = self.snapshot()
        out: Dict[str, Any] = {}
        for name in names:
            name = name.strip()
            if not name:
                continue
            out[name] = snapshot.get(name, "")
        return out

    # -- helpers -----------------------------------------------------------
    def _ipv6(self, interface: str) -> str:
        if not interface:
            return ""
        from .shell import run_shell

        text = run_shell("ip -6 -o addr show dev %s scope global" % interface, timeout=5.0).content
        for line in (text or "").splitlines():
            parts = line.split()
            for index, token in enumerate(parts):
                if token == "inet6" and index + 1 < len(parts):
                    return parts[index + 1].split("/")[0]
        return ""

    def _usb_is_gadget(self) -> bool:
        return bool(self.app.device_info.usb()[1].get("typec_mode") == "gadget")

    def _unit_active(self, unit) -> bool:
        if not unit:
            return False
        from .shell import unit_active

        return unit_active(str(unit))

    # -- AP list (the WiFi panel's shape) ----------------------------------
    def access_point_list(self) -> List[Dict[str, Any]]:
        hotspot = self.hotspot()
        if not hotspot.get("active") and not hotspot.get("ssid"):
            return []
        return [{
            "AccessPointSwitchStatus": "1",
            "AccessPointIndex": 0,
            "ChipIndex": "0" if self._is_2g(hotspot) else "1",
            "SSID": hotspot.get("ssid", ""),
            "Password": base64.b64encode(str(hotspot.get("psk", "")).encode("utf-8")).decode("ascii"),
            "AuthMode": hotspot.get("auth", "WPA2(AES)-PSK"),
            "ApMaxStationNumber": hotspot.get("max_clients", "8"),
            "ApBroadcastDisabled": "0" if not hotspot.get("hidden") else "1",
            "ApIsolate": "0",
            # Upstream rendered a QR image server-side; this build serves a
            # transparent placeholder so the panel does not show a broken image.
            "QrImageUrl": "/linux/placeholder.svg",
        }]

    @staticmethod
    def _is_2g(hotspot: Dict[str, Any]) -> bool:
        return str(hotspot.get("hw_mode") or "").lower() in ("g", "b")


def _month_direction(app, direction: str) -> int:
    """This month's received or sent bytes (``monthly_*`` is a monthly figure,
    not the sum of every day ever sampled)."""
    traffic = app.runtime.data.get("traffic") or {}
    prefix = time.strftime("%Y-%m")
    return sum(int((value or {}).get(direction, 0)) for key, value in traffic.items()
               if isinstance(value, dict) and str(key).startswith(prefix))


def _rx(app) -> int:
    return _month_direction(app, "rx")


def _tx(app) -> int:
    return _month_direction(app, "tx")


def qr_placeholder_svg() -> str:
    """A 1x1 transparent SVG standing in for the vendor's QR image."""
    return ('<svg xmlns="http://www.w3.org/2000/svg" width="1" height="1" '
            'viewBox="0 0 1 1"></svg>')
