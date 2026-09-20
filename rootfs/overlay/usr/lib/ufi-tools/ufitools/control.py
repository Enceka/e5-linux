"""Native control of the local Linux device.

This is the device's control plane: rather than asking a vendor web backend to
reboot the device or change the hotspot, UFI-TOOLS drives the Linux facilities
that already own those resources -- systemd units, hostapd, dnsmasq, sysfs.

E5-LINUX caveat that shaped the hotspot code: the initramfs overlay is copied
over ``/etc`` on every boot, so a file that exists in the baked overlay (such as
``/etc/hostapd/e5.conf``) silently reverts.  Edits are therefore written to
``<data_dir>/hostapd-managed.conf`` and a systemd drop-in is pointed at it;
neither path is in the overlay, so both survive a reboot.
"""

from __future__ import annotations

import os
import re
import shutil
import socket
import struct
from typing import Any, Dict, List, Optional

from .shell import ShellResult, run_shell, systemctl, unit_active

#: hostapd keys this module understands, with the config key that overrides them.
HOSTAPD_KEYS = {
    "ssid": "ssid",
    "wpa_passphrase": "psk",
    "channel": "channel",
    "hw_mode": "hw_mode",
    "max_num_sta": "max_clients",
    "ignore_broadcast_ssid": "hidden",
    "country_code": "country",
}

_IFACE_RE = re.compile(r"^\s+(?:inet|inet6)\s+([0-9a-fA-F:.]+\S*)(?:/(\d+))?", re.MULTILINE)
_STATION_MAC_RE = re.compile(r"^Station\s+([0-9a-fA-F:]{17})", re.MULTILINE)


class ControlError(Exception):
    """Raised for a control action that cannot be performed on this board."""


def read_text(path: str) -> Optional[str]:
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            return handle.read()
    except OSError:
        return None


def write_text(path: str, text: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        handle.write(text)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, path)


def parse_hostapd(text: str) -> Dict[str, str]:
    """Parse the flat ``key=value`` hostapd configuration."""
    result: Dict[str, str] = {}
    for line in (text or "").splitlines():
        line = line.split("#", 1)[0].strip()
        if not line or "=" not in line:
            continue
        key, value = line.split("=", 1)
        result[key.strip()] = value.strip()
    return result


def render_hostapd(values: Dict[str, str]) -> str:
    """Render a hostapd configuration, keeping unknown keys untouched by order."""
    lines = ["# Managed by UFI-TOOLS -- do not edit by hand; change it in the web UI."]
    for key, value in values.items():
        lines.append("%s=%s" % (key, value))
    return "\n".join(lines) + "\n"


def auth_mode(values: Dict[str, str]) -> str:
    """Map a hostapd config onto the auth names the web UI knows."""
    if values.get("wpa", "0") in ("0", "") and values.get("auth_algs", "1") == "1":
        return "OPEN"
    key_mgmt = values.get("wpa_key_mgmt", "WPA-PSK")
    if "SAE" in key_mgmt and "WPA-PSK" in key_mgmt:
        return "WPA2-PSK/WPA3-PSK"
    if "SAE" in key_mgmt or values.get("wpa", "2") == "3":
        return "WPA3-PSK"
    return "WPA2(AES)-PSK"


def iface_ipv4(interface: str) -> Dict[str, str]:
    """Address and netmask of ``interface`` from /proc/net (no external tools)."""
    text = run_shell("ip -4 addr show dev %s" % interface, timeout=5.0).content
    info: Dict[str, str] = {}
    for match in _IFACE_RE.finditer(text or ""):
        address = match.group(1)
        if ":" in address:
            continue
        prefix = match.group(2)
        info["lan_ipaddr"] = address
        if prefix:
            try:
                info["lan_netmask"] = str(prefix)
            except (TypeError, ValueError):
                pass
        break
    if info.get("lan_ipaddr"):
        info["dhcpStart"], info["dhcpEnd"] = _dhcp_range_hint(info["lan_ipaddr"])
    return info


def _dhcp_range_hint(address: str) -> tuple:
    parts = address.split(".")
    if len(parts) != 4:
        return "", ""
    return ".".join(parts[:3] + ["2"]), ".".join(parts[:3] + ["200"])


class SystemControl:
    """Every write this project performs on the local device."""

    def __init__(self, app):
        self.app = app

    @property
    def config(self):
        return self.app.config

    # -- power -------------------------------------------------------------
    def reboot(self) -> ShellResult:
        # --no-block so the HTTP response gets out before the socket disappears.
        return run_shell("systemctl reboot --no-block", timeout=10)

    def poweroff(self) -> ShellResult:
        return run_shell("systemctl poweroff", timeout=10)

    # -- mobile data -------------------------------------------------------
    def mobile_data_status(self) -> Dict[str, Any]:
        unit = str(self.config.get("mobile_data_unit") or "")
        interface = self.gateway_interface()
        status: Dict[str, Any] = {
            "active": unit_active(unit) if unit else False,
            "unit": unit,
            "interface": interface,
        }
        if interface:
            info = iface_ipv4(interface)
            status.update(info)
        status["connected"] = bool(interface) and bool(status.get("lan_ipaddr"))
        status["ppp_status"] = "ppp_connected" if status["connected"] else "ppp_disconnected"
        return status

    def gateway_interface(self) -> str:
        """Interface holding the default route -- the cellular uplink."""
        from .traffic import default_route_interface

        return default_route_interface() or ""

    def set_mobile_data(self, enable: bool) -> ShellResult:
        unit = str(self.config.get("mobile_data_unit") or "")
        if not unit:
            raise ControlError("未配置蜂窝数据服务单元")
        return systemctl("start" if enable else "stop", unit)

    # -- hotspot -----------------------------------------------------------
    def _base_conf(self) -> str:
        return str(self.config.get("hotspot_conf") or "")

    def _managed_conf(self) -> str:
        return os.path.join(self.config.data_dir, "hostapd-managed.conf")

    def _effective_conf(self) -> str:
        managed = self._managed_conf()
        if os.path.isfile(managed):
            return managed
        return self._base_conf()

    def hotspot_values(self) -> Dict[str, str]:
        raw = parse_hostapd(read_text(self._effective_conf()) or "")
        values = dict(raw)
        values.setdefault("ssid", "")
        values.setdefault("channel", "")
        values.setdefault("max_num_sta", "8")
        values.setdefault("ignore_broadcast_ssid", "0")
        return values

    def hotspot_status(self) -> Dict[str, Any]:
        interface = str(self.config.get("wlan_interface") or "wlan0")
        values = self.hotspot_values()
        unit = str(self.config.get("hotspot_unit") or "")
        info = iface_ipv4(interface)
        return {
            "active": unit_active(unit) if unit else False,
            "unit": unit,
            "interface": interface,
            "ssid": values.get("ssid", ""),
            "psk": values.get("wpa_passphrase", ""),
            "channel": values.get("channel", ""),
            "hw_mode": values.get("hw_mode", ""),
            "auth": auth_mode(values),
            "hidden": values.get("ignore_broadcast_ssid", "0") not in ("0", ""),
            "max_clients": values.get("max_num_sta", ""),
            "country": values.get("country_code", ""),
            "managed_conf": self._managed_conf(),
            "using_managed_conf": os.path.isfile(self._managed_conf()),
            "ipv4": info.get("lan_ipaddr", ""),
        }

    def set_hotspot(self, enable: bool) -> ShellResult:
        unit = str(self.config.get("hotspot_unit") or "")
        if not unit:
            raise ControlError("未配置热点服务单元")
        if enable:
            self._ensure_unit_dropin()
        return systemctl("start" if enable else "stop", unit)

    def configure_hotspot(self, updates: Dict[str, Any]) -> Dict[str, Any]:
        """Merge ``updates`` into the managed hostapd config and restart.

        Accepts the same field names the vendor UI used
        (``SSID``/``Password``/``ApMaxStationNumber``/``ApBroadcastDisabled``/
        ``channel``) so both the shim and a direct API caller work.
        """
        mapping = {
            "SSID": "ssid",
            "ssid": "ssid",
            "Password": "wpa_passphrase",
            "psk": "wpa_passphrase",
            "channel": "channel",
            "ApMaxStationNumber": "max_num_sta",
            "max_clients": "max_num_sta",
        }
        values = parse_hostapd(read_text(self._base_conf()) or "")
        values.setdefault("ssid", "E5-Linux")
        values.setdefault("channel", "149")
        values.setdefault("hw_mode", "a")
        values.setdefault("max_num_sta", "8")
        values.setdefault("ignore_broadcast_ssid", "0")
        values.setdefault("wpa", "2")
        values.setdefault("wpa_key_mgmt", "WPA-PSK")
        values.setdefault("rsn_pairwise", "CCMP")
        values.setdefault("country_code", "CN")

        applied: Dict[str, Any] = {}
        for source, target in mapping.items():
            if source in updates and updates[source] not in (None, ""):
                values[target] = str(updates[source])
                applied[target] = values[target]
        if "ApBroadcastDisabled" in updates:
            values["ignore_broadcast_ssid"] = "1" if str(updates["ApBroadcastDisabled"]) == "0" else "0"
            applied["ignore_broadcast_ssid"] = values["ignore_broadcast_ssid"]
        if "hidden" in updates:
            values["ignore_broadcast_ssid"] = "1" if updates["hidden"] else "0"
            applied["ignore_broadcast_ssid"] = values["ignore_broadcast_ssid"]
        auth = str(updates.get("AuthMode") or updates.get("auth") or "")
        if auth:
            if auth == "OPEN":
                values.update({"wpa": "0", "auth_algs": "1"})
                values.pop("wpa_key_mgmt", None)
                values.pop("wpa_passphrase", None)
            elif auth == "WPA3-PSK":
                values.update({"wpa": "2", "wpa_key_mgmt": "SAE", "ieee80211w": "2"})
            else:
                values.update({"wpa": "2", "wpa_key_mgmt": "WPA-PSK", "rsn_pairwise": "CCMP"})
            applied["auth"] = auth

        if not values.get("wpa_passphrase") and values.get("wpa", "0") != "0":
            raise ControlError("非开放网络必须设置密码")

        write_text(self._managed_conf(), render_hostapd(values))
        self._ensure_unit_dropin()
        result = systemctl("restart", str(self.config.get("hotspot_unit") or ""))
        return {"applied": applied, "conf": self._managed_conf(), "restarted": result.done}

    def _ensure_unit_dropin(self) -> Optional[str]:
        """Point the hotspot unit at the managed config (survives the overlay)."""
        unit = str(self.config.get("hotspot_unit") or "")
        base = self._base_conf()
        if not unit or not os.path.isfile(self._managed_conf()):
            return None
        dropin_dir = "/etc/systemd/system/%s.d" % unit
        dropin = os.path.join(dropin_dir, "10-ufi-tools.conf")
        script = "/opt/e5/hotspot-start.sh"
        if not os.path.isfile(script):
            return None
        write_text(dropin, "[Service]\nExecStart=\nExecStart=%s %s\n" % (
            script, self._managed_conf()))
        run_shell("systemctl daemon-reload", timeout=10)
        return dropin

    # -- clients -----------------------------------------------------------
    def clients(self) -> List[Dict[str, str]]:
        """Wireless clients, merged from station dump, ARP and DHCP leases."""
        interface = str(self.config.get("wlan_interface") or "wlan0")
        by_mac: Dict[str, Dict[str, str]] = {}

        stations = run_shell("iw dev %s station dump" % interface, timeout=5.0).content
        for mac in _STATION_MAC_RE.findall(stations or ""):
            by_mac[mac.lower()] = {"mac_addr": mac.lower(), "ip_addr": "", "hostname": "",
                                   "type": "wireless"}

        # `ip neigh` prints "<ip> dev <if> lladdr <mac> <state>".
        arp = run_shell("ip -4 neigh show dev %s" % interface, timeout=5.0).content
        for line in (arp or "").splitlines():
            fields = line.split()
            if len(fields) < 4 or "lladdr" not in fields:
                continue
            address = fields[0]
            mac = fields[fields.index("lladdr") + 1] if fields.index("lladdr") + 1 < len(fields) else ""
            if mac.count(":") != 5:
                continue
            entry = by_mac.setdefault(mac.lower(),
                                      {"mac_addr": mac.lower(), "ip_addr": "",
                                       "hostname": "", "type": "wireless"})
            entry["ip_addr"] = address

        for mac, address, hostname in self._leases():
            entry = by_mac.setdefault(mac.lower(),
                                      {"mac_addr": mac.lower(), "ip_addr": "", "hostname": "",
                                       "type": "wireless"})
            if address:
                entry["ip_addr"] = address
            if hostname:
                entry["hostname"] = hostname
        for entry in by_mac.values():
            if not entry["hostname"]:
                entry["hostname"] = entry["mac_addr"]
        return sorted(by_mac.values(), key=lambda item: item.get("ip_addr") or "")

    def _leases(self) -> List[tuple]:
        """dnsmasq leases: ``<expiry> <mac> <ip> <hostname> <client-id>``."""
        for path in ("/var/lib/misc/dnsmasq.leases", "/var/lib/dnsmasq/dnsmasq.leases",
                     "/run/dnsmasq.leases"):
            text = read_text(path)
            if not text:
                continue
            out = []
            for line in text.splitlines():
                fields = line.split()
                if len(fields) >= 4:
                    out.append((fields[1], fields[2], "" if fields[3] == "*" else fields[3]))
            return out
        return []

    def set_client_access(self, mode: str, macs: List[str]) -> Dict[str, Any]:
        """Allow/deny list, applied through the managed hostapd config."""
        values = parse_hostapd(read_text(self._effective_conf()) or "")
        values.pop("macaddr_acl", None)
        values.pop("accept_mac_file", None)
        values.pop("deny_mac_file", None)
        if macs:
            list_path = os.path.join(self.config.data_dir, "hostapd-maclist.conf")
            write_text(list_path, "\n".join(macs) + "\n")
            values["macaddr_acl"] = "0" if mode == "allow" else "1"
            values["accept_mac_file" if mode == "allow" else "deny_mac_file"] = list_path
        else:
            list_path = ""
        write_text(self._managed_conf(), render_hostapd(values))
        self._ensure_unit_dropin()
        systemctl("restart", str(self.config.get("hotspot_unit") or ""))
        return {"mode": mode, "count": len(macs), "list": list_path}

    # -- LAN (read-only) ---------------------------------------------------
    def lan_status(self) -> Dict[str, Any]:
        interface = str(self.config.get("wlan_interface") or "wlan0")
        info = iface_ipv4(interface)
        mac = read_text("/sys/class/net/%s/address" % interface)
        conf = read_text(str(self.config.get("dnsmasq_conf") or "")) or ""
        start, end = "", ""
        match = re.search(r"dhcp-range=([^,\s]+),([^,\s]+)", conf)
        if match:
            start, end = match.group(1), match.group(2)
        else:
            start, end = info.get("dhcpStart", ""), info.get("dhcpEnd", "")
        return {
            "lan_ipaddr": info.get("lan_ipaddr", ""),
            "lan_netmask": info.get("lan_netmask", ""),
            "dhcpStart": start,
            "dhcpEnd": end,
            "dhcpEnabled": bool(start),
            "mac_address": (mac or "").strip(),
        }

    # -- performance -------------------------------------------------------
    def _governor_paths(self) -> List[str]:
        base = "/sys/devices/system/cpu/cpufreq"
        try:
            return sorted(
                os.path.join(base, entry, "scaling_governor")
                for entry in os.listdir(base)
                if entry.startswith("policy")
            )
        except OSError:
            return []

    def performance_status(self) -> Dict[str, Any]:
        paths = self._governor_paths()
        governors = []
        for path in paths:
            value = (read_text(path) or "").strip()
            if value:
                governors.append(value)
        current = governors[0] if governors else ""
        available = []
        if paths:
            candidates = read_text(os.path.join(os.path.dirname(paths[0]), "scaling_available_governors"))
            available = (candidates or "").split()
        return {
            "governors": sorted(set(governors)),
            "governor": current,
            "available": available,
            "performance": current == "performance",
            "supported": bool(paths),
        }

    def set_performance(self, enabled: bool) -> Dict[str, Any]:
        paths = self._governor_paths()
        if not paths:
            raise ControlError("当前内核没有 cpufreq 调速器")
        target = "performance" if enabled else str(self.config.get("powersave_governor") or "schedutil")
        written = []
        for path in paths:
            try:
                write_text(path, target + "\n")
                written.append(path)
            except OSError:
                continue
        if not written:
            raise ControlError("写入调速器失败（需要 root）")
        return {"governor": target, "interfaces": len(written)}

    # -- indicator LED -----------------------------------------------------
    def _led_paths(self) -> List[str]:
        configured = [name for name in str(self.config.get("led_names") or "").split(",") if name.strip()]
        base = "/sys/class/leds"
        try:
            entries = sorted(os.listdir(base))
        except OSError:
            return []
        if configured:
            entries = [entry for entry in entries if entry in [c.strip() for c in configured]]
        return [os.path.join(base, entry) for entry in entries]

    def led_status(self) -> Dict[str, Any]:
        paths = self._led_paths()
        leds = []
        for path in paths:
            leds.append({
                "name": os.path.basename(path),
                "brightness": (read_text(os.path.join(path, "brightness")) or "").strip(),
                "trigger": (read_text(os.path.join(path, "trigger")) or "").strip().split()[-1:],
            })
        return {"supported": bool(paths), "leds": leds}

    def set_led(self, enabled: bool) -> Dict[str, Any]:
        paths = self._led_paths()
        if not paths:
            raise ControlError("当前设备没有可控指示灯")
        changed = 0
        for path in paths:
            try:
                write_text(os.path.join(path, "trigger"), "default-on\n" if enabled else "none\n")
                write_text(os.path.join(path, "brightness"),
                           ("255" if enabled else "0") + "\n")
                changed += 1
            except OSError:
                continue
        if not changed:
            raise ControlError("写入指示灯失败（需要 root）")
        return {"enabled": enabled, "leds": changed}

    # -- misc --------------------------------------------------------------
    def samba_unit(self) -> str:
        return str(self.config.get("samba_unit") or "")

    def set_samba(self, enabled: bool) -> Dict[str, Any]:
        unit = self.samba_unit()
        if not unit:
            raise ControlError("未配置文件共享服务单元（samba_unit）")
        result = systemctl("start" if enabled else "stop", unit)
        return {"unit": unit, "started": result.done}

    def uptime(self) -> int:
        return self.app.device_info.uptime()

    def ip_to_int(self, address: str) -> int:
        try:
            return struct.unpack("!I", socket.inet_aton(address))[0]
        except OSError:
            return 0

    def which(self, binary: str) -> Optional[str]:
        return shutil.which(binary)
